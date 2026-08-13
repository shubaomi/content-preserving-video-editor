#!/usr/bin/env python3
"""Validate and compile the HongRun portrait motion recipe layer."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file
from brand_motion_playbook import validate_playbook
from portrait_brand_contracts import validate_portrait_contract_schema
from safe_generated_output import (
    SafeGeneratedOutputError, atomic_replace_file, safe_generated_directory,
    safe_generated_target,
)


ROOT = Path(__file__).parents[1]
DEFAULT_PORTRAIT_RECIPE_REGISTRY = ROOT / "references" / "portrait-motion-recipes-v2.json"
PORTRAIT_RECIPE_IDS = tuple(f"PBM-{index:02d}" for index in range(1, 9))
ALLOWED_LAYERS = {
    "ambient_light_field", "micro_grain", "orbit_particles",
    "focus_vignette", "icon_burst",
}
ALLOWED_CAPABILITIES = {
    "dom", "svg", "gsap", "media_transform", "hand_tracking",
    "subject_tracking", "subject_mask", "asset_adapter", "remotion_event",
}
FORBIDDEN_KEYS = {
    "events_per_minute", "minimum_event_count", "minimum_family_count",
    "keyword_score", "random_family", "random_template", "random_sfx",
}
PROTECTED_REGION_IDS = [
    "portrait:face", "portrait:eyes", "portrait:mouth", "portrait:hands",
    "portrait:caption", "portrait:platform-ui",
]
PORTRAIT_COMPONENT_JS = ROOT / "references" / "hyperframes-portrait-components-v2.js"
PORTRAIT_COMPONENT_CSS = ROOT / "references" / "hyperframes-portrait-components-v2.css"


class PortraitRecipeError(ValueError):
    """Raised when portrait motion cannot be compiled without guessing."""


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PortraitRecipeError(f"{label} must be a mapping")
    return value


def _authority_by_id(energy_map: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = energy_map.get("evidence_authorities")
    if not isinstance(rows, list):
        raise PortraitRecipeError("portrait energy map lacks typed evidence authorities")
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise PortraitRecipeError(f"evidence_authorities[{index}] must be a mapping")
        evidence_id = str(row.get("evidence_id") or "")
        if not evidence_id or evidence_id in result:
            raise PortraitRecipeError("typed evidence authority IDs must be non-empty and unique")
        expected_hash = _stable_hash({key: value for key, value in row.items() if key != "authority_sha256"})
        if row.get("authority_sha256") != expected_hash:
            raise PortraitRecipeError(f"{evidence_id}: typed evidence authority is stale")
        result[evidence_id] = row
    return result


def _typed_binding(
    authority_by_id: Mapping[str, Mapping[str, Any]], evidence_id: Any,
    *, expected_kind: str, label: str, event: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence_id, str) or not evidence_id:
        raise PortraitRecipeError(f"{label} requires a typed evidence ID")
    row = authority_by_id.get(evidence_id)
    if not isinstance(row, Mapping) or row.get("kind") != expected_kind:
        raise PortraitRecipeError(f"{label} requires current {expected_kind} evidence")
    status = row.get("status")
    if status not in {"current", "tracked", "visible"}:
        raise PortraitRecipeError(f"{label} evidence status is not usable")
    if expected_kind in {"subject_track", "gesture_track"} and row.get("visible") is not True:
        raise PortraitRecipeError(f"{label} evidence is not visible")
    domain = row.get("time_domain")
    if domain not in {"source", "output"}:
        raise PortraitRecipeError(f"{label} evidence lacks a valid time domain")
    window = row.get("window")
    if not isinstance(window, Mapping):
        raise PortraitRecipeError(f"{label} evidence window is malformed")
    event_start_key, event_end_key = (
        ("source_start", "source_end") if domain == "source"
        else ("output_start", "output_end")
    )
    try:
        observed_start = float(window.get("start_seconds"))
        observed_end = float(window.get("end_seconds"))
        event_start = float(event.get(event_start_key))
        event_end = float(event.get(event_end_key))
    except (TypeError, ValueError):
        raise PortraitRecipeError(f"{label} evidence/event window is malformed")
    if observed_end < event_start or observed_start > event_end:
        raise PortraitRecipeError(f"{label} evidence does not overlap the event")
    binding = {
        "evidence_id": evidence_id,
        "kind": expected_kind,
        "authority_sha256": row.get("authority_sha256"),
        "source_sha256": row.get("source_sha256"),
        "window": dict(window),
        "time_domain": domain,
        "status": status,
    }
    for key in (
        "visible", "points", "face", "crop", "smoothed_center",
        "source_apex_seconds", "output_apex_seconds",
    ):
        if key in row:
            binding[key] = row[key]
    if expected_kind == "gesture_track" and not isinstance(binding.get("points"), list):
        raise PortraitRecipeError(f"{label} gesture geometry is missing")
    return binding


def _energy_inheritance_errors(
    event: Mapping[str, Any], energy: Mapping[str, Any], semantic_hash: str,
    energy_map: Mapping[str, Any],
) -> list[str]:
    intent = event.get("portrait_energy_intent")
    if not isinstance(intent, Mapping):
        return ["semantic portrait_energy_intent is missing"]
    pairs = (
        ("tier", "tier"), ("chapter_id", "chapter_id"),
        ("transition_intent", "transition_intent"),
        ("max_attention_layers", "max_attention_layers"),
        ("rationale", "rationale"), ("evidence_refs", "evidence_refs"),
        ("fallback_tier", "fallback_tier"),
    )
    errors = [
        f"energy {energy_key} differs from semantic intent"
        for energy_key, intent_key in pairs
        if energy.get(energy_key) != intent.get(intent_key)
    ]
    signals = intent.get("signals") if isinstance(intent.get("signals"), Mapping) else {}
    for field in ("gesture_evidence_id", "chapter_boundary_evidence_id"):
        if energy.get(field) != signals.get(field):
            errors.append(f"energy {field} differs from semantic intent")
    if (energy_map.get("input_hashes") or {}).get("semantic_brief") != semantic_hash:
        errors.append("energy semantic brief hash is stale")
    return errors


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [str(key) for key in value] + [
            nested for child in value.values() for nested in _walk_keys(child)
        ]
    if isinstance(value, list):
        return [nested for child in value for nested in _walk_keys(child)]
    return []


def load_portrait_recipe_registry(
    path: Path = DEFAULT_PORTRAIT_RECIPE_REGISTRY,
) -> dict[str, Any]:
    return read_json(path.resolve())


def recipe_fingerprint(recipe: Mapping[str, Any]) -> dict[str, str]:
    dimensions = {
        "hierarchy": recipe.get("hierarchy"),
        "layout": recipe.get("layout"),
        "camera": recipe.get("camera"),
        "choreography": recipe.get("choreography"),
        "layers": list(recipe.get("supporting_layers") or []),
    }
    return {
        **{f"{key}_sha256": _stable_hash(value) for key, value in dimensions.items()},
        "composite_sha256": _stable_hash(dimensions),
    }


def validate_portrait_recipe_registry(registry: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(registry, Mapping):
        return ["portrait recipe registry must be a mapping"]
    expected_root = {
        "schema_version", "registry_id", "producer", "selection_policy",
        "fixed_cadence", "minimum_event_quota", "random_rotation",
        "product_card_default", "recipes",
    }
    unknown_root = set(registry) - expected_root
    if unknown_root:
        errors.append("portrait recipe registry has unknown keys: " + ", ".join(sorted(unknown_root)))
    if registry.get("schema_version") != 2:
        errors.append("portrait recipe registry schema_version must be 2")
    if registry.get("registry_id") != "hongrun-portrait-motion-recipes-v2":
        errors.append("portrait recipe registry ID is invalid")
    if registry.get("selection_policy") != "portrait_energy_semantic_role_and_current_evidence_only":
        errors.append("portrait recipe selection policy is invalid")
    for key in ("fixed_cadence", "minimum_event_quota", "random_rotation", "product_card_default"):
        if registry.get(key) is not False:
            errors.append(f"portrait recipe registry requires {key}=false")
    recipes = registry.get("recipes")
    if not isinstance(recipes, list):
        return [*errors, "portrait recipe registry recipes must be a list"]
    ids = [row.get("recipe_id") for row in recipes if isinstance(row, Mapping)]
    if ids != list(PORTRAIT_RECIPE_IDS):
        errors.append("portrait recipe registry must contain PBM-01 through PBM-08 in order")
    composites: list[str] = []
    for index, recipe in enumerate(recipes):
        if not isinstance(recipe, Mapping):
            errors.append(f"recipes[{index}] must be a mapping")
            continue
        required = {
            "recipe_id", "name", "semantic_roles", "energy_tiers", "component",
            "hierarchy", "layout", "camera", "choreography", "supporting_layers",
            "required_capabilities", "required_evidence", "contraindications",
            "fallback", "phases", "reduced_motion", "seek_safe", "post_exit",
        }
        unknown = set(recipe) - required
        missing = required - set(recipe)
        if unknown:
            errors.append(f"recipes[{index}] has unknown keys: {', '.join(sorted(unknown))}")
        if missing:
            errors.append(f"recipes[{index}] lacks keys: {', '.join(sorted(missing))}")
        for field in ("name", "component", "hierarchy", "layout", "camera", "choreography", "reduced_motion"):
            if not isinstance(recipe.get(field), str) or not recipe.get(field).strip():
                errors.append(f"recipes[{index}] requires non-empty {field}")
        roles = recipe.get("semantic_roles")
        tiers = recipe.get("energy_tiers")
        if not isinstance(roles, list) or not roles or len(roles) != len(set(roles)):
            errors.append(f"recipes[{index}] requires unique semantic roles")
        if not isinstance(tiers, list) or not tiers or not set(tiers) <= {"micro", "meso", "macro"}:
            errors.append(f"recipes[{index}] has invalid energy tiers")
        layers = recipe.get("supporting_layers")
        if not isinstance(layers, list) or len(layers) > 2 or not set(layers) <= ALLOWED_LAYERS:
            errors.append(f"recipes[{index}] has invalid supporting layers")
        capabilities = recipe.get("required_capabilities")
        if not isinstance(capabilities, list) or not capabilities or not set(capabilities) <= ALLOWED_CAPABILITIES:
            errors.append(f"recipes[{index}] has invalid required capabilities")
        phases = recipe.get("phases")
        if not isinstance(phases, list) or len(phases) != 4 or [
            str(value).split(":", 1)[0] for value in phases
        ] != ["entrance", "explain", "hold", "exit"]:
            errors.append(f"recipes[{index}] requires entrance/explain/hold/exit phases")
        if recipe.get("seek_safe") is not True or not str(recipe.get("post_exit") or "").endswith(("only", "clear", "identity")):
            errors.append(f"recipes[{index}] must be seek-safe and restore a clean source state")
        fallback = recipe.get("fallback")
        if not isinstance(fallback, Mapping) or fallback.get("kind") not in {
            "portrait_recipe", "existing_portrait_typography", "caption_only",
            "quiet_source", "action_required",
        } or not str(fallback.get("target") or ""):
            errors.append(f"recipes[{index}] fallback is invalid")
        forbidden = FORBIDDEN_KEYS.intersection(_walk_keys(recipe))
        layout = str(recipe.get("layout") or "").lower()
        if forbidden or any(marker in layout for marker in (
            "rounded_card", "product_card", "card_shell", "opaque_cards",
        )):
            errors.append(f"recipes[{index}] contains forbidden cadence/card semantics")
        composites.append(recipe_fingerprint(recipe)["composite_sha256"])
    if len(composites) != len(set(composites)):
        errors.append("portrait recipe structural fingerprints must be distinct")
    return errors


def _select_recipe(
    event: Mapping[str, Any], energy: Mapping[str, Any],
) -> str:
    role = str(event.get("semantic_role") or "").lower()
    tier = str(energy.get("tier") or "")
    intent = event.get("portrait_energy_intent") or {}
    signals = intent.get("signals") or {}
    if role == "transition" and tier == "macro" and signals.get("chapter_boundary_evidence_id"):
        return "PBM-07"
    if role in {"mark", "sequence"} and signals.get("gesture_evidence_id"):
        return "PBM-03"
    if event.get("asset_request_id") or event.get("asset_request"):
        return "PBM-06"
    if role == "relate":
        return "PBM-04"
    if role == "resolve" and tier in {"meso", "macro"}:
        return "PBM-08"
    if role in {"explain", "transition"} and tier in {"meso", "macro"} and (
        event.get("subject_track_id") and event.get("camera_intent") is True
    ):
        return "PBM-05"
    if role in {"explain", "resolve"} and tier == "meso" and event.get("subject_region_id"):
        return "PBM-02"
    return "PBM-01"


def compile_portrait_motion_contracts(
    *, semantic_brief: Mapping[str, Any], base_motion_contract: Mapping[str, Any],
    profile_path: Path, energy_map_path: Path, registry_path: Path,
    brand_playbook_path: Path,
) -> dict[str, Any]:
    """Compile an additive portrait renderer layer over the stable MQE contract."""
    semantic_brief = _require_mapping(semantic_brief, "semantic_brief")
    base_motion_contract = _require_mapping(base_motion_contract, "base_motion_contract")
    profile_path = profile_path.resolve()
    energy_map_path = energy_map_path.resolve()
    registry_path = registry_path.resolve()
    brand_playbook_path = brand_playbook_path.resolve()
    for path in (profile_path, energy_map_path, registry_path, brand_playbook_path):
        if not path.is_file():
            raise PortraitRecipeError(f"portrait motion authority is missing: {path}")
    registry = load_portrait_recipe_registry(registry_path)
    registry_errors = validate_portrait_recipe_registry(registry)
    if registry_errors:
        raise PortraitRecipeError("; ".join(registry_errors))
    profile = read_json(profile_path)
    profile_errors = validate_portrait_contract_schema("portrait-brand-profile", profile)
    if profile_errors:
        raise PortraitRecipeError("invalid portrait brand profile: " + "; ".join(profile_errors))
    energy_map = read_json(energy_map_path)
    energy_errors = validate_portrait_contract_schema("portrait-energy-map", energy_map)
    if energy_errors:
        raise PortraitRecipeError("invalid portrait energy map: " + "; ".join(energy_errors))
    playbook = read_json(brand_playbook_path)
    playbook_errors = validate_playbook(playbook)
    if playbook_errors:
        raise PortraitRecipeError("invalid portrait brand playbook: " + "; ".join(playbook_errors))
    portrait_playbook = playbook.get("portrait_brand")
    if not isinstance(portrait_playbook, Mapping) or (
        portrait_playbook.get("profile_id") != profile.get("profile_id")
        or portrait_playbook.get("profile_version") != profile.get("profile_version")
        or portrait_playbook.get("profile_sha256") != sha256_file(profile_path)
        or portrait_playbook.get("direction") != profile.get("direction")
    ):
        raise PortraitRecipeError("portrait playbook does not bind the current profile and direction")
    authority_by_id = _authority_by_id(energy_map)
    energy_by_id = {
        str(row.get("semantic_event_id")): row
        for row in energy_map.get("opportunities") or [] if isinstance(row, Mapping)
    }
    semantic_by_id = {
        str(row.get("id")): row
        for row in semantic_brief.get("events") or [] if isinstance(row, Mapping)
    }
    base_rows = [
        row for row in base_motion_contract.get("opportunities") or []
        if isinstance(row, Mapping) and row.get("decision") == "render"
    ]
    semantic_ids = [str(row.get("id") or "") for row in semantic_brief.get("events") or [] if isinstance(row, Mapping)]
    energy_ids = [str(row.get("semantic_event_id") or "") for row in energy_map.get("opportunities") or [] if isinstance(row, Mapping)]
    if not semantic_ids or energy_ids != semantic_ids:
        raise PortraitRecipeError("portrait energy event set/order differs from semantic brief")
    render_ids = [
        str(row.get("id") or "") for row in semantic_brief.get("events") or []
        if isinstance(row, Mapping) and row.get("decision", "render") == "render"
    ]
    base_ids = [str(row.get("semantic_event_id") or "") for row in base_rows]
    if base_ids != render_ids:
        raise PortraitRecipeError("base motion render event set/order differs from semantic brief")
    recipes = {row["recipe_id"]: row for row in registry["recipes"]}
    input_hashes = {
        "brand_profile": sha256_file(profile_path),
        "energy_map": sha256_file(energy_map_path),
        "recipe_registry": sha256_file(registry_path),
        "brand_playbook": sha256_file(brand_playbook_path),
        "base_motion_contract": _stable_hash(base_motion_contract),
        "semantic_brief": _stable_hash(semantic_brief),
    }
    contracts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for base in base_rows:
        event_id = str(base.get("semantic_event_id") or "")
        event = semantic_by_id.get(event_id)
        energy = energy_by_id.get(event_id)
        if event is None or energy is None:
            raise PortraitRecipeError(f"{event_id}: portrait semantic or energy binding is missing")
        inheritance_errors = _energy_inheritance_errors(
            event, energy, _stable_hash(semantic_brief), energy_map,
        )
        if inheritance_errors:
            raise PortraitRecipeError(f"{event_id}: " + "; ".join(inheritance_errors))
        semantic_copy = list(event.get("approved_visible_copy") or [])
        if list(base.get("approved_visible_copy") or []) != semantic_copy:
            raise PortraitRecipeError(
                f"{event_id}: base approved visible copy differs from semantic brief"
            )
        semantic_window = {
            "start_seconds": event.get("output_start"),
            "end_seconds": event.get("output_end"),
        }
        if dict(base.get("output_window") or {}) != semantic_window:
            raise PortraitRecipeError(
                f"{event_id}: base output window differs from semantic brief"
            )
        tier = str(energy.get("tier") or "")
        if tier == "quiet":
            raise PortraitRecipeError(f"{event_id}: render decision cannot use quiet portrait energy")
        selected = _select_recipe(event, energy)
        recipe = recipes[selected]
        role = str(event.get("semantic_role") or "").lower()
        if role not in recipe["semantic_roles"] or tier not in recipe["energy_tiers"]:
            fallback = recipe["fallback"]
            if fallback["kind"] == "portrait_recipe" and fallback["target"] in recipes:
                selected = str(fallback["target"])
                recipe = recipes[selected]
            if role not in recipe["semantic_roles"] or tier not in recipe["energy_tiers"]:
                raise PortraitRecipeError(
                    f"{event_id}: no portrait recipe supports role={role} tier={tier}"
                )
        approved_copy = semantic_copy
        if selected == "PBM-04" and len(approved_copy) != 2:
            raise PortraitRecipeError(f"{event_id}: PBM-04 requires exactly two approved concepts")
        signals = (event.get("portrait_energy_intent") or {}).get("signals") or {}
        binding_cache: dict[str, dict[str, Any]] = {}
        try:
            if selected == "PBM-03":
                binding_cache["gesture_binding"] = _typed_binding(
                    authority_by_id, signals.get("gesture_evidence_id"),
                    expected_kind="gesture_track", label=f"{event_id}: PBM-03",
                    event=event,
                )
            if selected in {"PBM-02", "PBM-05"}:
                binding_cache["subject_binding"] = _typed_binding(
                    authority_by_id, event.get("subject_track_id"),
                    expected_kind="subject_track", label=f"{event_id}: {selected}",
                    event=event,
                )
            if selected == "PBM-07":
                binding_cache["chapter_boundary_binding"] = _typed_binding(
                    authority_by_id, signals.get("chapter_boundary_evidence_id"),
                    expected_kind="chapter_boundary", label=f"{event_id}: PBM-07",
                    event=event,
                )
        except PortraitRecipeError:
            fallback = recipe["fallback"]
            if fallback.get("kind") == "portrait_recipe" and fallback.get("target") in recipes:
                fallback_recipe = recipes[str(fallback["target"])]
                if role in fallback_recipe["semantic_roles"] and tier in fallback_recipe["energy_tiers"]:
                    selected = str(fallback["target"])
                    recipe = fallback_recipe
                    binding_cache = {}
                else:
                    raise
            else:
                raise
        contract: dict[str, Any] = {
            "schema_version": 1,
            "contract_id": f"portrait:{_stable_hash([event_id, selected, input_hashes])[:20]}",
            "semantic_event_id": event_id,
            "brand_profile": {"path": str(profile_path), "sha256": sha256_file(profile_path)},
            "energy_map": {"path": str(energy_map_path), "sha256": sha256_file(energy_map_path)},
            "energy_tier": tier,
            "primary_recipe_id": selected,
            "supporting_layers": list(recipe["supporting_layers"][: int(energy.get("max_attention_layers", 0))]),
            "approved_visible_copy": approved_copy,
            "source_window": {
                "start_seconds": event.get("source_start"),
                "end_seconds": event.get("source_end"),
            },
            "output_window": semantic_window,
            "protected_region_ids": list(PROTECTED_REGION_IDS),
            "required_capabilities": list(recipe["required_capabilities"]),
            "fallback": dict(recipe["fallback"]),
            "input_hashes": input_hashes,
            "source_media": dict(energy_map["source_media"]),
        }
        gesture_id = signals.get("gesture_evidence_id")
        if selected == "PBM-03":
            contract["gesture_binding_id"] = gesture_id
            contract["gesture_binding"] = binding_cache["gesture_binding"]
        if selected in {"PBM-02", "PBM-05"}:
            contract["subject_binding"] = binding_cache["subject_binding"]
            contract["source_target_id"] = str(event.get("source_target_id") or "source-media")
            if event.get("subject_mask_ref"):
                contract["subject_mask_ref"] = dict(event["subject_mask_ref"])
        if selected == "PBM-06":
            asset_request = event.get("asset_request")
            asset_id = event.get("asset_request_id") or (asset_request or {}).get("id")
            if not asset_id:
                raise PortraitRecipeError(f"{event_id}: PBM-06 requires an asset request ID")
            contract["asset_request_id"] = str(asset_id)
            asset_ref = (asset_request or {}).get("asset_ref") if isinstance(asset_request, Mapping) else None
            if not isinstance(asset_ref, Mapping):
                raise PortraitRecipeError(f"{event_id}: PBM-06 requires a provenance-bound asset_ref")
            asset_path = Path(str(asset_ref.get("path") or "")).resolve()
            if not asset_path.is_file() or asset_ref.get("sha256") != sha256_file(asset_path):
                raise PortraitRecipeError(f"{event_id}: PBM-06 asset_ref is missing or stale")
            contract["asset_ref"] = {"path": str(asset_path), "sha256": sha256_file(asset_path)}
        if selected == "PBM-07":
            contract["chapter_boundary_binding"] = binding_cache["chapter_boundary_binding"]
        schema_errors = validate_portrait_contract_schema("portrait-motion-contract", contract)
        if schema_errors:
            raise PortraitRecipeError("; ".join(schema_errors))
        contracts.append(contract)
        diagnostics.append({
            "semantic_event_id": event_id,
            "primary_recipe_id": selected,
            "selection_inputs": ["semantic_role", "energy_tier", "current_capability_evidence"],
            "fingerprints": recipe_fingerprint(recipe),
            "component": recipe["component"],
            "phases": list(recipe["phases"]),
            "reduced_motion": recipe["reduced_motion"],
            "seek_safe": recipe["seek_safe"],
            "post_exit": recipe["post_exit"],
        })
    return {
        "schema_version": 1,
        "registry": {"path": str(registry_path), "sha256": sha256_file(registry_path)},
        "base_motion_contract_sha256": _stable_hash(base_motion_contract),
        "contracts": contracts,
        "diagnostics": diagnostics,
        "selected_event_ids": [row["semantic_event_id"] for row in contracts],
        "selection_policy": registry["selection_policy"],
        "fixed_cadence_used": False,
        "quota_used": False,
        "keyword_selection_used": False,
        "random_selection_used": False,
        "product_card_fallback_used": False,
    }


def portrait_choreography_by_event(
    bundle: Mapping[str, Any], registry: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    recipes = {row["recipe_id"]: row for row in registry.get("recipes") or []}
    diagnostics = {
        row["semantic_event_id"]: row for row in bundle.get("diagnostics") or []
    }
    result: dict[str, dict[str, Any]] = {}
    for contract in bundle.get("contracts") or []:
        event_id = str(contract["semantic_event_id"])
        recipe = recipes[contract["primary_recipe_id"]]
        result[event_id] = {
            "portrait_contract_id": contract["contract_id"],
            "portrait_recipe_id": contract["primary_recipe_id"],
            "portrait_component": recipe["component"],
            "portrait_energy_tier": contract["energy_tier"],
            "portrait_source_window": dict(contract["source_window"]),
            "supporting_layers": list(contract["supporting_layers"]),
            "protected_region_ids": list(contract["protected_region_ids"]),
            "portrait_phases": list(recipe["phases"]),
            "reduced_motion": recipe["reduced_motion"],
            "seek_safe": recipe["seek_safe"],
            "post_exit": recipe["post_exit"],
            "portrait_fingerprints": diagnostics[event_id]["fingerprints"],
            "portrait_source_media": dict(contract["source_media"]),
            "portrait_input_hashes": dict(contract["input_hashes"]),
            "portrait_fallback": dict(contract["fallback"]),
        }
        for source_key, target_key in (
            ("gesture_binding_id", "gesture_binding_id"),
            ("gesture_binding", "gesture_binding"),
            ("subject_binding", "subject_binding"),
            ("source_target_id", "source_target_id"),
            ("asset_request_id", "asset_request_id"),
            ("asset_ref", "asset_ref"),
            ("chapter_boundary_binding", "chapter_boundary_binding"),
            ("subject_mask_ref", "subject_mask_ref"),
        ):
            if source_key in contract:
                result[event_id][target_key] = contract[source_key]
    return result


def build_portrait_renderer_payload(
    bundle: Mapping[str, Any], registry: Mapping[str, Any], *,
    project_root: Path | None = None,
    materialize_assets: bool = True,
) -> dict[str, Any]:
    """Adapt canonical contracts to the only supported portrait component API."""
    bundle = _require_mapping(bundle, "portrait contract bundle")
    registry = _require_mapping(registry, "portrait recipe registry")
    choreography = portrait_choreography_by_event(bundle, registry)
    contracts = bundle.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise PortraitRecipeError("portrait renderer payload requires contracts")
    events: list[dict[str, Any]] = []
    for index, contract in enumerate(contracts):
        if not isinstance(contract, Mapping):
            raise PortraitRecipeError(f"contracts[{index}] must be a mapping")
        event_id = str(contract.get("semantic_event_id") or "")
        row = choreography.get(event_id)
        if not isinstance(row, Mapping):
            raise PortraitRecipeError(f"{event_id}: choreography is missing")
        recipe_id = str(contract.get("primary_recipe_id") or "")
        bindings: dict[str, Any] = {}
        for source_key, target_key in (
            ("subject_binding", "subjectBinding"),
            ("gesture_binding", "gestureBinding"),
            ("chapter_boundary_binding", "chapterBoundaryBinding"),
        ):
            if source_key in contract:
                bindings[target_key] = dict(contract[source_key])
        if "source_target_id" in contract:
            bindings["sourceTargetId"] = contract["source_target_id"]
        if "asset_ref" in contract:
            asset_ref = dict(contract["asset_ref"])
            asset_path = Path(str(asset_ref.get("path") or "")).resolve()
            if not asset_path.is_file() or asset_ref.get("sha256") != sha256_file(asset_path):
                raise PortraitRecipeError(f"{event_id}: renderer asset is missing or stale")
            try:
                from PIL import Image

                with Image.open(asset_path) as image:
                    image.verify()
            except Exception as error:
                raise PortraitRecipeError(
                    f"{event_id}: renderer asset must be a decodable image"
                ) from error
            bindings["assetRef"] = asset_ref
            if project_root is None:
                bindings["assetUrl"] = asset_path.as_uri()
            else:
                project_root = Path(os.path.abspath(project_root))
                try:
                    asset_dir = safe_generated_directory(
                        project_root, Path("assets") / "portrait-brand-v2" / "media",
                    )
                except SafeGeneratedOutputError as error:
                    raise PortraitRecipeError(str(error)) from error
                suffix = asset_path.suffix.lower() or ".bin"
                rendered_asset = asset_dir / f"{asset_ref['sha256']}{suffix}"
                if not rendered_asset.is_file() or sha256_file(rendered_asset) != asset_ref["sha256"]:
                    if not materialize_assets:
                        raise PortraitRecipeError(
                            f"{event_id}: current project renderer asset is missing or stale"
                        )
                    atomic_replace_file(asset_path, rendered_asset)
                bindings["assetUrl"] = (
                    f"./assets/portrait-brand-v2/media/{rendered_asset.name}"
                )
                bindings["assetRuntimeUrl"] = rendered_asset.as_uri()
                bindings["renderAssetRef"] = {
                    "path": str(rendered_asset.resolve()),
                    "sha256": sha256_file(rendered_asset),
                }
                bindings["sourceAssetRef"] = asset_ref
                bindings["assetRef"] = dict(bindings["renderAssetRef"])
        authority_digests = {
            key: value
            for key, value in (
                ("subjectBinding", (bindings.get("subjectBinding") or {}).get("authority_sha256")),
                ("gestureBinding", (bindings.get("gestureBinding") or {}).get("authority_sha256")),
                ("chapterBoundaryBinding", (bindings.get("chapterBoundaryBinding") or {}).get("authority_sha256")),
                ("assetRef", (bindings.get("assetRef") or {}).get("sha256")),
            )
            if value
        }
        events.append({
            "recipeId": recipe_id,
            "eventId": f"event-{event_id}",
            "semanticEventId": event_id,
            "contractId": contract["contract_id"],
            "contractSha256": _stable_hash(contract),
            "visibleCopy": list(contract["approved_visible_copy"]),
            "supportingLayers": list(contract["supporting_layers"]),
            "sourceWindow": dict(contract["source_window"]),
            "outputWindow": dict(contract["output_window"]),
            "bindings": bindings,
            "expectedBindings": json.loads(json.dumps(bindings)),
            "authorityDigests": authority_digests,
        })
    payload = {
        "schema_version": 1,
        "component_api": "hongrun-portrait-components-v2",
        "events": events,
    }
    payload["payload_sha256"] = _stable_hash(payload)
    return payload


def materialize_portrait_component_assets(project_root: Path) -> dict[str, Any]:
    """Copy versioned reusable assets into one generated HyperFrames project."""
    project_root = Path(os.path.abspath(project_root))
    try:
        output_dir = safe_generated_directory(
            project_root, Path("assets") / "portrait-brand-v2",
        )
    except SafeGeneratedOutputError as error:
        raise PortraitRecipeError(str(error)) from error
    outputs = []
    for source in (PORTRAIT_COMPONENT_JS, PORTRAIT_COMPONENT_CSS):
        if not source.is_file():
            raise PortraitRecipeError(f"portrait component source is missing: {source}")
        try:
            output = safe_generated_target(
                project_root, Path("assets") / "portrait-brand-v2" / source.name,
            )
            atomic_replace_file(source, output)
        except SafeGeneratedOutputError as error:
            raise PortraitRecipeError(str(error)) from error
        outputs.append({
            "source": {"path": str(source.resolve()), "sha256": sha256_file(source)},
            "output": {"path": str(output.resolve()), "sha256": sha256_file(output)},
        })
    return {
        "schema_version": 1,
        "component_bundle": "hongrun-portrait-components-v2",
        "outputs": outputs,
        "usage": {
            "stylesheet": "assets/portrait-brand-v2/hyperframes-portrait-components-v2.css",
            "module": "assets/portrait-brand-v2/hyperframes-portrait-components-v2.js",
            "visible_copy_owner": "portrait-motion-contract.approved_visible_copy",
            "project_specific_copy_in_bundle": False,
        },
    }


def validate_storyboard_portrait_binding(
    storyboard: Any, bundle: Mapping[str, Any],
) -> list[str]:
    """Require HyperFrames to consume portrait contracts without reselection."""
    if not isinstance(storyboard, Mapping):
        return ["portrait storyboard must be a mapping"]
    if not isinstance(bundle, Mapping):
        return ["portrait contract bundle must be a mapping"]
    rows = storyboard.get("events")
    if not isinstance(rows, list):
        return ["portrait storyboard events must be a list"]
    contracts = bundle.get("contracts")
    if not isinstance(contracts, list) or not contracts or not all(isinstance(row, Mapping) for row in contracts):
        return ["portrait contract bundle contracts must be a non-empty mapping list"]
    contract_ids = [str(row.get("semantic_event_id") or "") for row in contracts]
    if any(not value for value in contract_ids) or len(contract_ids) != len(set(contract_ids)):
        return ["portrait contract semantic event IDs must be non-empty and unique"]
    expected = {event_id: row for event_id, row in zip(contract_ids, contracts)}
    observed: dict[str, Mapping[str, Any]] = {}
    errors: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"storyboard events[{index}] must be a mapping")
            continue
        event_id = str(row.get("semantic_event_id") or "")
        if event_id in observed:
            errors.append(f"storyboard duplicates portrait event {event_id}")
        observed[event_id] = row
    if list(observed) != list(expected):
        errors.append("storyboard portrait event set/order differs from portrait contracts")
        return errors
    registry = load_portrait_recipe_registry()
    try:
        expected_projection = portrait_choreography_by_event(bundle, registry)
    except (KeyError, TypeError, PortraitRecipeError) as error:
        return [f"portrait contract bundle is incomplete: {error}"]
    for event_id, contract in expected.items():
        row = observed[event_id]
        for key, expected_value in expected_projection[event_id].items():
            if row.get(key) != expected_value:
                errors.append(f"{event_id}: {key} differs from portrait compiler output")
        if row.get("visible_copy_manifest") != contract["approved_visible_copy"]:
            errors.append(f"{event_id}: portrait visible copy differs from approved copy")
        allowed = {"semantic_event_id", "visible_copy_manifest", *expected_projection[event_id]}
        unexpected = {
            key for key in row
            if (key.startswith("portrait_") or key in {
                "supporting_layers", "protected_region_ids", "reduced_motion", "seek_safe",
                "post_exit", "gesture_binding_id", "gesture_binding", "subject_binding",
                "source_target_id", "asset_request_id", "asset_ref",
                "chapter_boundary_binding", "subject_mask_ref",
            }) and key not in allowed
        }
        if unexpected:
            errors.append(f"{event_id}: unexpected portrait fields: {', '.join(sorted(unexpected))}")
    return errors
