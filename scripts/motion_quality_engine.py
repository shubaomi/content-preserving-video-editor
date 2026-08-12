#!/usr/bin/env python3
"""Deterministically compile approved semantics into typed motion choreography."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from director_contracts import read_json, sha256_file
from motion_contracts import (
    ACTION_REQUIRED_FALLBACK,
    canonical_contract_evidence_refs,
    load_recipe_registry,
    validate_motion_design_contract,
)


class MotionCompilationError(ValueError):
    """Raised when approved semantics cannot be compiled without inventing evidence."""


FORM_TO_RECIPE = {
    "semantic_mark": "MQE-01",
    "ui_focus": "MQE-02",
    "cursor_causality": "MQE-03",
    "compare": "MQE-04",
    "comparison": "MQE-04",
    "process": "MQE-05",
    "sequence": "MQE-05",
    "relation": "MQE-06",
    "causal_path": "MQE-06",
    "metric_proof": "MQE-07",
    "chart_focus": "MQE-07",
    "before_after": "MQE-08",
    "state_transform": "MQE-08",
    "product_lens": "MQE-09",
    "magnified_detail": "MQE-09",
    "camera_focus": "MQE-10",
    "guided_pan": "MQE-10",
    "chapter_bridge": "MQE-11",
    "kinetic_phrase": "MQE-12",
    "evidence_pip": "MQE-13",
    "ip_vignette": "MQE-14",
    "architecture": "MQE-15",
    "map_layers": "MQE-15",
    "depth_stage": "MQE-16",
}
ROLE_DEFAULT_RECIPE = {
    "mark": "MQE-01",
    "explain": "MQE-12",
    "relate": "MQE-06",
    "sequence": "MQE-05",
    "prove": "MQE-13",
    "resolve": "MQE-12",
    "transition": "MQE-11",
}


FORMAT_GRAMMARS: dict[str, dict[str, Any]] = {
    "screen_recording": {
        "grammar_id": "screen-product-explainer-v1",
        "primary_subject_priority": [
            "verified_source_target", "source_state_change", "spoken_meaning", "captions",
        ],
        "preferred_treatments": [
            "target_relative_callout", "focus_box", "connector_explanation",
            "process_map", "comparison_layout", "evidence_zoom",
        ],
        "disallowed_default_treatments": [
            "speaker_face_overlay", "decorative_kinetic_phrase",
        ],
        "role_treatments": {
            "mark": "target_relative_callout", "explain": "focus_box",
            "relate": "connector_explanation", "sequence": "process_map",
            "prove": "evidence_zoom", "resolve": "result_summary",
            "transition": "source_state_transition",
        },
        "composition_rules": [
            "bind callouts to verified target geometry",
            "prefer source-relative explanation over detached cards",
            "fall back to semantic typography when the target is not visible",
        ],
    },
    "talking_head": {
        "grammar_id": "talking-head-expressive-v1",
        "primary_subject_priority": [
            "speaker_face", "speaker_gesture", "spoken_meaning", "captions",
        ],
        "preferred_treatments": [
            "kinetic_typography", "face_safe_side_rail", "rhythmic_word_emphasis",
            "depth_light_accent", "brief_semantic_cutaway", "chapter_transition_accent",
        ],
        "disallowed_default_treatments": [
            "floating_product_card", "dashboard_focus_box", "ui_target_callout",
        ],
        "role_treatments": {
            "mark": "rhythmic_word_emphasis", "explain": "face_safe_side_rail",
            "relate": "brief_semantic_cutaway", "sequence": "kinetic_step_sequence",
            "prove": "evidence_pip", "resolve": "kinetic_typography",
            "transition": "chapter_transition_accent",
        },
        "composition_rules": [
            "keep the speaker face, hands, emotional tone, and captions primary",
            "use expressive typography, depth, light, and rhythm instead of product cards",
            "keep persistent overlays outside the face and gesture zones",
            "use a brief semantic cutaway only when evidence adds explanatory value",
        ],
    },
    "mixed": {
        "grammar_id": "hybrid-source-explainer-v1",
        "primary_subject_priority": [
            "active_source_subject", "spoken_meaning", "verified_source_target", "captions",
        ],
        "preferred_treatments": [
            "speaker_safe_callout", "target_relative_callout", "evidence_pip",
            "source_mode_transition",
        ],
        "disallowed_default_treatments": ["full_frame_decorative_card"],
        "role_treatments": {
            "mark": "speaker_safe_callout", "explain": "target_relative_callout",
            "relate": "evidence_pip", "sequence": "source_mode_sequence",
            "prove": "evidence_pip", "resolve": "semantic_summary",
            "transition": "source_mode_transition",
        },
        "composition_rules": [
            "select the active subject from source evidence at the event window",
            "do not cover the speaker or verified UI target",
        ],
    },
    "other": {
        "grammar_id": "evidence-led-neutral-v1",
        "primary_subject_priority": ["source_content", "spoken_meaning", "captions"],
        "preferred_treatments": ["semantic_mark", "evidence_pip", "chapter_transition"],
        "disallowed_default_treatments": ["identity_specific_vignette"],
        "role_treatments": {
            "mark": "semantic_mark", "explain": "semantic_explanation",
            "relate": "semantic_relation", "sequence": "semantic_sequence",
            "prove": "evidence_pip", "resolve": "semantic_summary",
            "transition": "chapter_transition",
        },
        "composition_rules": ["prefer source evidence over decorative treatment"],
    },
}

ADVANCED_RUNTIME_EVIDENCE_KINDS = (
    "seek_safe", "deterministic_2d_fallback", "preview_render_parity",
    "device_support", "license", "cost",
)
ADVANCED_RUNTIME_CLAIMS = {
    "seek_safe": ("random_access_samples", "seek_error_frames"),
    "deterministic_2d_fallback": ("fallback_artifact",),
    "preview_render_parity": ("parity_report",),
    "device_support": ("tested_devices",),
    "license": ("rights_basis", "license_artifact"),
    "cost": ("estimated_cost", "currency"),
}
SUPPORTED_RIGHTS_BASES = {
    "project-owned", "commercial-license", "open-source-license",
    "provider-terms", "internal-test-only",
}
SUPPORTED_COST_CURRENCIES = {
    "AUD", "CAD", "CHF", "CNY", "EUR", "GBP", "HKD", "INR", "JPY",
    "KRW", "SGD", "USD",
}


def _valid_hash_bound_file(record: Any) -> Path | None:
    if not isinstance(record, Mapping):
        return None
    path = Path(str(record.get("path") or ""))
    if (
        not path.is_absolute() or not path.is_file()
        or record.get("sha256") != sha256_file(path)
    ):
        return None
    return path.resolve()


def _decodable_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.load()
            return image.width > 0 and image.height > 0
    except (OSError, UnidentifiedImageError):
        return False


def _advanced_artifact_valid(
    name: str, path: Path, *, subject_id: str, claims: Mapping[str, Any],
    expected_source_duration_seconds: float | None,
) -> bool:
    """Validate the kind-specific proof behind an advanced-runtime receipt."""
    try:
        proof = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(proof, Mapping):
        return False
    if (
        proof.get("schema_version") != 1
        or proof.get("kind") != f"advanced_{name}_evidence"
        or proof.get("status") != "pass"
        or proof.get("subject_id") != subject_id
        or proof.get("claims_sha256") != _stable_hash(claims)
        or proof.get("evidence_sha256") != _stable_hash({
            key: value for key, value in proof.items() if key != "evidence_sha256"
        })
    ):
        return False
    if name == "seek_safe":
        samples = proof.get("samples")
        requested = proof.get("requested_timestamps_seconds")
        duration = proof.get("source_duration_seconds")
        expected_count = claims.get("random_access_samples")
        if (
            not isinstance(samples, list) or len(samples) != expected_count
            or not isinstance(requested, list) or len(requested) != expected_count
            or not isinstance(duration, (int, float)) or isinstance(duration, bool)
            or not math.isfinite(float(duration)) or float(duration) <= 0
        ):
            return False
        if (
            expected_source_duration_seconds is None
            or not math.isclose(
                float(duration), float(expected_source_duration_seconds),
                rel_tol=0.0, abs_tol=0.001,
            )
        ):
            return False
        timestamps = [row.get("timestamp_seconds") for row in samples if isinstance(row, Mapping)]
        if len(timestamps) != expected_count or timestamps != requested:
            return False
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and 0 <= float(value) <= float(duration)
            for value in timestamps
        ):
            return False
        if any(float(left) >= float(right) for left, right in zip(timestamps, timestamps[1:])):
            return False
        return all(
            isinstance(row, Mapping)
            and isinstance(row.get("seek_error_frames"), (int, float))
            and not isinstance(row.get("seek_error_frames"), bool)
            and math.isfinite(float(row["seek_error_frames"]))
            and 0 <= float(row["seek_error_frames"]) <= float(claims["seek_error_frames"])
            for row in samples
        )
    if name == "deterministic_2d_fallback":
        output = _valid_hash_bound_file(proof.get("fallback_output"))
        return output is not None and _decodable_image(output)
    if name == "preview_render_parity":
        measurements = proof.get("measurements")
        if not isinstance(measurements, list) or not measurements:
            return False
        for row in measurements:
            if not isinstance(row, Mapping) or row.get("status") != "pass":
                return False
            reference = _valid_hash_bound_file(row.get("reference"))
            rendered = _valid_hash_bound_file(row.get("rendered"))
            if reference is None or rendered is None:
                return False
            if not _decodable_image(reference) or not _decodable_image(rendered):
                return False
            if reference.read_bytes() != rendered.read_bytes():
                return False
        return True
    if name == "device_support":
        devices = proof.get("devices")
        declared_values = claims.get("tested_devices")
        if not isinstance(declared_values, list) or not all(
            isinstance(value, str) and bool(value.strip()) for value in declared_values
        ) or len(set(declared_values)) != len(declared_values):
            return False
        declared = list(declared_values)
        return (
            isinstance(devices, list)
            and [row.get("device_id") for row in devices if isinstance(row, Mapping)] == declared
            and all(
                isinstance(row, Mapping) and row.get("status") == "pass"
                and isinstance(row.get("device_id"), str) and bool(row["device_id"].strip())
                for row in devices
            )
        )
    if name == "license":
        document = _valid_hash_bound_file(proof.get("license_document"))
        rights_basis = claims.get("rights_basis")
        return (
            isinstance(rights_basis, str) and rights_basis in SUPPORTED_RIGHTS_BASES
            and proof.get("rights_basis") == rights_basis
            and document is not None and bool(document.read_bytes())
        )
    if name == "cost":
        currency = claims.get("currency")
        return (
            proof.get("estimated_cost") == claims.get("estimated_cost")
            and isinstance(currency, str) and currency in SUPPORTED_COST_CURRENCIES
            and proof.get("currency") == currency
            and isinstance(proof.get("calculation_inputs"), Mapping)
            and bool(proof.get("calculation_inputs"))
        )
    return False


def format_motion_grammar(source_type: str) -> dict[str, Any]:
    """Return the deterministic content-type grammar used by the renderer."""
    key = str(source_type or "other").strip().lower()
    grammar = FORMAT_GRAMMARS.get(key, FORMAT_GRAMMARS["other"])
    return {
        **json.loads(json.dumps(grammar, ensure_ascii=False)),
        "source_type": key if key in FORMAT_GRAMMARS else "other",
        "fixed_event_cadence": False,
        "random_template_rotation": False,
        "semantic_selection_owner": "director_motion_quality_engine",
    }


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def choreography_fingerprint(recipe: dict[str, Any]) -> str:
    """Fingerprint visible choreography, not project copy or event timing."""
    return _stable_hash({
        "recipe_id": recipe.get("recipe_id"),
        "recipe_version": recipe.get("recipe_version"),
        "runtime": recipe.get("runtime"),
        "orientation_variants": recipe.get("orientation_variants"),
        "phases": recipe.get("phases"),
        "proof_requirements": recipe.get("proof_requirements"),
    })


def validate_advanced_runtime_evidence(
    enabled: bool, evidence: Mapping[str, Any] | None, *,
    expected_subject_id: str | None = None,
    expected_source_duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Authorize advanced rendering only from current external evidence bytes."""
    records = evidence if isinstance(evidence, Mapping) else {}
    valid: dict[str, dict[str, str]] = {}
    invalid: list[str] = []
    for name in ADVANCED_RUNTIME_EVIDENCE_KINDS:
        row = records.get(name)
        if not enabled:
            invalid.append(name)
            continue
        if not isinstance(row, Mapping) or row.get("status") != "pass":
            invalid.append(name)
            continue
        path = Path(str(row.get("path") or ""))
        declared_hash = str(row.get("sha256") or "").lower()
        if not path.is_absolute() or not path.is_file() or sha256_file(path) != declared_hash:
            invalid.append(name)
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            invalid.append(name)
            continue
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != 1
            or payload.get("kind") != name
            or payload.get("status") != "pass"
            or not str(payload.get("subject_id") or "").strip()
            or (expected_subject_id is not None and payload.get("subject_id") != expected_subject_id)
            or not str(payload.get("tool_version") or "").strip()
            or payload.get("evidence_sha256") != _stable_hash({
                key: value for key, value in payload.items() if key != "evidence_sha256"
            })
        ):
            invalid.append(name)
            continue
        claims = payload.get("claims")
        artifacts = payload.get("artifacts")
        if not isinstance(claims, Mapping) or any(
            field not in claims for field in ADVANCED_RUNTIME_CLAIMS[name]
        ) or not isinstance(artifacts, list) or not artifacts:
            invalid.append(name)
            continue
        artifact_valid = True
        artifact_by_path: dict[str, Mapping[str, Any]] = {}
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                artifact_valid = False
                continue
            artifact_path = Path(str(artifact.get("path") or ""))
            if (
                not isinstance(artifact, Mapping) or not artifact_path.is_absolute()
                or not artifact_path.is_file()
                or artifact.get("sha256") != sha256_file(artifact_path)
            ):
                artifact_valid = False
            else:
                artifact_by_path[str(artifact_path.resolve())] = artifact
        if name == "seek_safe":
            samples = claims.get("random_access_samples")
            error_frames = claims.get("seek_error_frames")
            claim_valid = (
                isinstance(samples, int) and not isinstance(samples, bool) and samples > 0
                and isinstance(error_frames, (int, float)) and not isinstance(error_frames, bool)
                and 0 <= float(error_frames) <= 1
            )
        elif name in {"deterministic_2d_fallback", "preview_render_parity"}:
            field = "fallback_artifact" if name == "deterministic_2d_fallback" else "parity_report"
            claim_valid = str(Path(str(claims.get(field) or "")).resolve()) in artifact_by_path
        elif name == "device_support":
            devices = claims.get("tested_devices")
            claim_valid = isinstance(devices, list) and bool(devices) and all(
                isinstance(value, str) and bool(value.strip()) for value in devices
            ) and len(set(devices)) == len(devices)
        elif name == "license":
            rights_basis = claims.get("rights_basis")
            claim_valid = isinstance(rights_basis, str) and rights_basis in SUPPORTED_RIGHTS_BASES and str(
                Path(str(claims.get("license_artifact") or "")).resolve()
            ) in artifact_by_path
        else:
            cost = claims.get("estimated_cost")
            currency = claims.get("currency")
            claim_valid = (
                isinstance(cost, (int, float)) and not isinstance(cost, bool)
                and math.isfinite(float(cost)) and float(cost) >= 0
                and isinstance(currency, str) and currency in SUPPORTED_COST_CURRENCIES
            )
        subject_id = str(payload.get("subject_id") or "")
        proof_valid = bool(artifact_by_path) and all(
            _advanced_artifact_valid(
                name, artifact_path, subject_id=subject_id, claims=claims,
                expected_source_duration_seconds=expected_source_duration_seconds,
            )
            for artifact_path in (Path(value) for value in artifact_by_path)
        )
        if not artifact_valid or not claim_valid or not proof_valid:
            invalid.append(name)
            continue
        valid[name] = {"path": str(path.resolve()), "sha256": declared_hash}
    if not enabled:
        status = "disabled"
    elif invalid:
        status = "action_required"
    else:
        status = "ready"
    return {
        "status": status,
        "required_evidence": list(ADVANCED_RUNTIME_EVIDENCE_KINDS),
        "missing_or_invalid_evidence": invalid,
        "evidence": valid,
        "deterministic_2d_fallback": status != "ready",
    }


def _event_facts(
    event: dict[str, Any], *, identity_mode: str, target_bindings: Mapping[str, Any],
    adaptive_layout: dict[str, Any], advanced_runtimes_enabled: bool,
) -> tuple[set[str], set[str]]:
    facts: set[str] = set()
    contraindications: set[str] = set()
    if event.get("approved_visible_copy"):
        facts.add("approved_copy.present")
    target_ids = event.get("target_binding_ids") or []
    if target_ids and all(
        isinstance(target_bindings.get(str(binding_id)), dict)
        and target_bindings[str(binding_id)].get("status") == "resolved"
        for binding_id in target_ids
    ):
        facts.add("target_binding.resolved")
    else:
        contraindications.add("target_binding.lost")
    form = str(event.get("form") or "").strip().lower()
    evidence_types = {str(value) for value in (event.get("evidence_types") or [])}
    if form in {"compare", "comparison"} or "comparison" in evidence_types:
        facts.add("evidence.comparison")
    if form in {"process", "sequence"} or "sequence" in evidence_types:
        facts.add("evidence.sequence")
    if form in {"relation", "causal_path"} or "relation" in evidence_types:
        facts.add("evidence.relation")
    if form in {"metric_proof", "chart_focus"} or "chart" in evidence_types:
        facts.add("evidence.chart")
    if form in {"before_after", "state_transform", "cursor_causality"} or event.get("state_pair_evidence"):
        facts.add("state_pair.present")
    if form == "chapter_bridge" or event.get("chapter_boundary_evidence"):
        facts.add("evidence.chapter_boundary")
    if form == "evidence_pip" or event.get("media_evidence"):
        facts.add("evidence.media")
    if form == "depth_stage" or event.get("depth_evidence"):
        facts.add("evidence.depth")
    if identity_mode == "self":
        facts.add("identity.self")
    if identity_mode == "third_party":
        contraindications.add("identity.third_party")
    if adaptive_layout.get("status") in {"ready", "resolved"}:
        facts.add("safe_layout.available")
    else:
        contraindications.add("layout.unsafe")
    if advanced_runtimes_enabled:
        facts.add("advanced_runtime.enabled")
    else:
        contraindications.add("device.unsupported")
    return facts, contraindications


def _select_recipe(
    event: dict[str, Any], *, registry: dict[str, Any], identity_mode: str,
    target_bindings: Mapping[str, Any], adaptive_layout: dict[str, Any],
    advanced_runtimes_enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    recipes = {row["recipe_id"]: row for row in registry["recipes"]}
    role = str(event.get("semantic_role") or "").strip().lower()
    form = str(event.get("form") or "").strip().lower()
    requested = FORM_TO_RECIPE.get(form) or ROLE_DEFAULT_RECIPE.get(role)
    if not requested:
        raise MotionCompilationError(
            f"{event.get('id')}: render decision requires a supported semantic_role or structured form"
        )
    facts, active_contraindications = _event_facts(
        event, identity_mode=identity_mode, target_bindings=target_bindings,
        adaptive_layout=adaptive_layout,
        advanced_runtimes_enabled=advanced_runtimes_enabled,
    )
    chain: list[str] = []
    rejected_rules: list[str] = []
    current = requested
    while current != ACTION_REQUIRED_FALLBACK:
        if current in chain:
            raise MotionCompilationError(f"{event.get('id')}: recipe fallback cycle at {current}")
        chain.append(current)
        recipe = recipes.get(current)
        if recipe is None:
            raise MotionCompilationError(f"{event.get('id')}: unknown recipe {current}")
        missing = [rule for rule in recipe["preconditions"] if rule not in facts]
        blocked = [rule for rule in recipe["contraindications"] if rule in active_contraindications]
        unsupported_role = role not in recipe["semantic_roles"]
        if not missing and not blocked and not unsupported_role:
            return recipe, {
                "semantic_event_id": str(event.get("id")),
                "requested_recipe_id": requested,
                "selected_recipe_id": current,
                "fallback_chain": chain,
                "rejected_rules": rejected_rules,
                "choreography_fingerprint_sha256": choreography_fingerprint(recipe),
                "guessed_coordinates": False,
            }
        rejected_rules.extend(missing)
        rejected_rules.extend(blocked)
        if unsupported_role:
            rejected_rules.append(f"semantic_role.unsupported:{role}")
        current = str(recipe["fallback_recipe_id"])
    raise MotionCompilationError(
        f"{event.get('id')}: no safe recipe; action_required after {' -> '.join(chain)} "
        f"({', '.join(dict.fromkeys(rejected_rules))})"
    )


def _artifact_hashes(input_artifacts: Mapping[str, Path]) -> dict[str, str]:
    required = ("semantic_brief", "production_contract", "evidence_bundle", "brand_playbook")
    missing = [name for name in required if name not in input_artifacts]
    if missing:
        raise MotionCompilationError("missing motion-design input artifacts: " + ", ".join(missing))
    hashes: dict[str, str] = {}
    for name, value in input_artifacts.items():
        path = Path(value).resolve()
        if not path.is_file():
            raise MotionCompilationError(f"motion-design input artifact is missing: {name}")
        hashes[f"{name}_sha256"] = sha256_file(path)
    return hashes


def compile_motion_design(
    *, project_id: str, semantic_brief: dict[str, Any], source_media: dict[str, Any],
    identity_mode: str, input_artifacts: Mapping[str, Path],
    adaptive_layout: dict[str, Any], target_bindings: Mapping[str, Any],
    advanced_runtimes_enabled: bool,
    advanced_runtime_evidence: Mapping[str, Any] | None = None,
    recipe_registry: dict[str, Any] | None = None,
    created_at: str,
) -> dict[str, Any]:
    """Compile all decisions and the exact render subset with deterministic fallbacks."""
    if semantic_brief.get("schema_version") != 3 or (
        semantic_brief.get("opportunity_model") != "decision_complete_v1"
    ):
        raise MotionCompilationError("Motion Quality Engine requires a decision-complete schema 3 brief")
    semantic_path = Path(input_artifacts.get("semantic_brief", "")).resolve()
    if not semantic_path.is_file() or read_json(semantic_path) != semantic_brief:
        raise MotionCompilationError(
            "semantic brief payload must exactly match the hashed semantic_brief artifact"
        )
    registry = recipe_registry or load_recipe_registry()
    events = semantic_brief.get("events")
    if not isinstance(events, list) or not events:
        raise MotionCompilationError("semantic brief requires at least one opportunity")
    hashes = _artifact_hashes(input_artifacts)
    advanced_subject = _stable_hash({
        "project_id": project_id,
        "source_sha256": source_media.get("sha256"),
        "input_hashes": hashes,
    })
    advanced_runtime = validate_advanced_runtime_evidence(
        advanced_runtimes_enabled, advanced_runtime_evidence,
        expected_subject_id=advanced_subject,
        expected_source_duration_seconds=(
            float(source_media["duration_seconds"])
            if isinstance(source_media.get("duration_seconds"), (int, float))
            and not isinstance(source_media.get("duration_seconds"), bool)
            and math.isfinite(float(source_media["duration_seconds"]))
            and float(source_media["duration_seconds"]) > 0
            else None
        ),
    )
    evidence_bundle_path = Path(input_artifacts["evidence_bundle"]).resolve()
    opportunities: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            raise MotionCompilationError("semantic opportunities must be mappings")
        event_id = str(event.get("id") or "")
        decision = str(event.get("decision") or "")
        row: dict[str, Any] = {
            "semantic_event_id": event_id,
            "decision": decision,
            "rationale": str(event.get("decision_rationale") or ""),
            "source_window": {
                "start_seconds": event.get("source_start"),
                "end_seconds": event.get("source_end"),
            },
            "output_window": {
                "start_seconds": event.get("output_start"),
                "end_seconds": event.get("output_end"),
            },
            "transcript_word_ids": list(event.get("transcript_word_ids") or []),
            "approved_visible_copy": list(event.get("approved_visible_copy") or []),
            "viewer_takeaway": str(event.get("viewer_takeaway") or ""),
            "evidence_refs": [],
        }
        try:
            row["evidence_refs"] = canonical_contract_evidence_refs(
                event, evidence_bundle_path=evidence_bundle_path,
            )
        except ValueError as error:
            raise MotionCompilationError(str(error)) from error
        if decision == "render":
            recipe, diagnostic = _select_recipe(
                event, registry=registry, identity_mode=identity_mode,
                target_bindings=target_bindings, adaptive_layout=adaptive_layout,
                advanced_runtimes_enabled=advanced_runtime["status"] == "ready",
            )
            row.update({
                "semantic_role": str(event.get("semantic_role")),
                "recipe_id": recipe["recipe_id"],
                "target_binding_ids": (
                    list(event.get("target_binding_ids") or [])
                    if "target_binding.resolved" in recipe.get("preconditions", []) else []
                ),
                "audio_decision_id": str(
                    (event.get("audio_decision") or {}).get("id") or f"audio-{event_id}"
                ),
                "estimated_cost_tier": recipe["cost_tier"],
            })
            selected_ids.append(event_id)
            diagnostics.append(diagnostic)
        opportunities.append(row)
    contract_seed = {
        "project_id": project_id,
        "source_media": source_media,
        "identity_mode": identity_mode,
        "input_hashes": hashes,
        "opportunities": opportunities,
        "selected_event_ids": selected_ids,
        "created_at": created_at,
    }
    contract = {
        "schema_version": "1.0.0",
        "contract_id": f"motion-{_stable_hash(contract_seed)[:24]}",
        "project_id": project_id,
        "created_at": created_at,
        "producer": "content-preserving-video-editor.motion-quality-engine",
        "source_media": source_media,
        "identity_mode": identity_mode,
        "input_hashes": hashes,
        "opportunities": opportunities,
        "selected_event_ids": selected_ids,
        "constraints": {
            "max_concurrent_primary_events": 1,
            "max_attention_units": 2,
            "caption_safe_zone": {"x": 0.0, "y": 0.80, "width": 1.0, "height": 0.20},
            "platform_safe_zone": {"x": 0.05, "y": 0.05, "width": 0.90, "height": 0.90},
            "protected_region_binding_ids": list(
                (adaptive_layout.get("constraints") or {}).get("protected_region_binding_ids") or []
            ),
        },
    }
    errors = validate_motion_design_contract(
        contract, artifact_paths=input_artifacts, recipe_registry=registry,
    )
    if errors:
        raise MotionCompilationError("; ".join(errors))
    return {
        "schema_version": "1.0.0",
        "contract": contract,
        "diagnostics": diagnostics,
        "registry_sha256": _stable_hash(registry),
        "selection_inputs": "semantic_role_and_structured_form_only",
        "fixed_cadence_used": False,
        "quota_used": False,
        "keyword_selection_used": False,
        "random_selection_used": False,
        "sfx_selection_used": False,
        "advanced_runtime": advanced_runtime,
    }


def build_hyperframes_choreography(
    contract: dict[str, Any], recipe_registry: dict[str, Any] | None = None,
    advanced_runtime: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the typed, renderer-facing choreography map without re-authoring meaning."""
    registry = recipe_registry or load_recipe_registry()
    recipes = {row["recipe_id"]: row for row in registry["recipes"]}
    grammar = format_motion_grammar(
        str((contract.get("source_media") or {}).get("source_type") or "other")
    )
    grammar_hash = _stable_hash(grammar)
    events = []
    for opportunity in contract.get("opportunities") or []:
        if opportunity.get("decision") != "render":
            continue
        recipe = recipes[opportunity["recipe_id"]]
        orientation = contract["source_media"]["orientation"]
        layout_key = orientation if orientation in recipe["orientation_variants"] else "landscape"
        events.append({
            "semantic_event_id": opportunity["semantic_event_id"],
            "recipe_id": recipe["recipe_id"],
            "recipe_version": recipe["recipe_version"],
            "semantic_role": opportunity["semantic_role"],
            "approved_visible_copy": opportunity["approved_visible_copy"],
            "source_window": opportunity["source_window"],
            "output_window": opportunity["output_window"],
            "target_binding_ids": opportunity.get("target_binding_ids") or [],
            "runtime": recipe["runtime"],
            "layout": recipe["orientation_variants"][layout_key],
            "phases": recipe["phases"],
            "proof_requirements": recipe["proof_requirements"],
            "audio_profile": recipe["audio_profile"],
            **({
                "advanced_runtime_gate": {
                    "status": "ready",
                    "required_evidence": list(ADVANCED_RUNTIME_EVIDENCE_KINDS),
                    "evidence_sha256": {
                        name: row["sha256"]
                        for name, row in ((advanced_runtime or {}).get("evidence") or {}).items()
                    },
                    "evidence_may_not_be_self_declared_by_renderer": True,
                    "fallback_recipe_id": recipe["fallback_recipe_id"],
                },
            } if recipe["runtime"].get("advanced_feature_flag_required") is True else {}),
            "format_grammar_id": grammar["grammar_id"],
            "format_treatment": (
                grammar["role_treatments"].get(opportunity["semantic_role"])
                or grammar["preferred_treatments"][0]
            ),
            "choreography_fingerprint_sha256": choreography_fingerprint(recipe),
        })
    return {
        "schema_version": "1.0.0",
        "motion_design_contract_id": contract.get("contract_id"),
        "motion_design_contract_sha256": _stable_hash(contract),
        "format_grammar": grammar,
        "format_grammar_sha256": grammar_hash,
        "events": events,
    }
