#!/usr/bin/env python3
"""Schema and cross-contract validation for portrait brand motion v2."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).parents[1]
SCHEMA_ROOT = ROOT / "references" / "portrait-brand-motion-v2" / "schemas"
PORTRAIT_CONTRACT_SCHEMA_NAMES = (
    "portrait-brand-profile",
    "portrait-energy-map",
    "portrait-motion-contract",
    "portrait-sonic-plan",
    "style-reel-plan",
    "style-reel-review",
)
SCHEMA_PATHS = {
    name: SCHEMA_ROOT / f"{name}.schema.json"
    for name in PORTRAIT_CONTRACT_SCHEMA_NAMES
}
STYLE_DIRECTIONS = (
    "luminous_intelligence",
    "high_energy_creator",
    "humanist_cinema",
)
PRODUCT_CARD_MARKERS = (
    "mqe-04",
    "product-card",
    "product_card",
    "dashboard-card",
    "dashboard_card",
    "generic-card",
    "generic_card",
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: Any) -> str:
    return sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def validate_portrait_contract_schema(name: str, payload: Any) -> list[str]:
    """Validate one portrait-v2 instance against its frozen Draft 2020-12 schema."""
    path = SCHEMA_PATHS.get(name)
    if path is None:
        return [f"unknown portrait contract schema: {name}"]
    if not path.is_file():
        return [f"portrait contract schema is missing: {path}"]
    validator = Draft202012Validator(
        _read_json(path), format_checker=FormatChecker()
    )
    return [
        f"{name} schema "
        + (".".join(str(value) for value in error.absolute_path) or "root")
        + f": {error.message}"
        for error in sorted(
            validator.iter_errors(payload),
            key=lambda row: tuple(str(value) for value in row.absolute_path),
        )
    ]


def validate_all_portrait_schema_definitions() -> list[str]:
    """Meta-validate every portrait-v2 schema without claiming implementation."""
    errors: list[str] = []
    for name in PORTRAIT_CONTRACT_SCHEMA_NAMES:
        path = SCHEMA_PATHS[name]
        if not path.is_file():
            errors.append(f"portrait contract schema is missing: {path}")
            continue
        try:
            Draft202012Validator.check_schema(_read_json(path))
        except Exception as error:
            errors.append(f"{name} schema definition is invalid: {error}")
    return errors


def _file_reference_errors(value: Any, label: str) -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        if "path" in value and "sha256" in value:
            raw_path = value.get("path")
            digest = value.get("sha256")
            if not isinstance(raw_path, str) or not raw_path.strip():
                return [f"{label} file reference path must be a non-empty string"]
            path = Path(raw_path)
            if not path.is_absolute():
                return [f"{label} file reference path must be absolute: {raw_path}"]
            if not path.is_file():
                return [f"{label} file reference is missing: {path}"]
            if not isinstance(digest, str) or digest != _sha256_file(path):
                return [f"{label} file reference hash is stale: {path}"]
            return []
        for key, item in value.items():
            errors.extend(_file_reference_errors(item, f"{label}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_file_reference_errors(item, f"{label}[{index}]"))
    return errors


def _artifact_binding_errors(
    bundle: Mapping[str, Any], artifact_paths: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    for name in ("portrait-brand-profile", "portrait-energy-map", "style-reel-plan"):
        raw_path = artifact_paths.get(name)
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"artifact_paths.{name} must be an absolute path")
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            errors.append(f"artifact_paths.{name} must be absolute")
            continue
        if not path.is_file():
            errors.append(f"artifact_paths.{name} is missing: {path}")
            continue
        try:
            stored = _read_json(path)
        except (OSError, ValueError, TypeError) as error:
            errors.append(f"artifact_paths.{name} is not valid JSON: {error}")
            continue
        if stored != bundle.get(name):
            errors.append(f"{name} artifact hash is stale relative to supplied contract")
    return errors


def _canonical_ref(path_value: Any) -> tuple[str, str] | None:
    if not isinstance(path_value, Mapping):
        return None
    raw_path = path_value.get("path")
    digest = path_value.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(digest, str):
        return None
    return str(Path(raw_path).resolve()), digest


def _expected_artifact_ref(artifact_paths: Mapping[str, Any], name: str) -> tuple[str, str] | None:
    raw_path = artifact_paths.get(name)
    if not isinstance(raw_path, str):
        return None
    path = Path(raw_path).resolve()
    if not path.is_file():
        return None
    return str(path), _sha256_file(path)


def validate_portrait_contract_bundle(
    bundle: Mapping[str, Any], *,
    expected_all_event_ids: Sequence[str],
    expected_render_event_ids: Sequence[str],
    expected_visible_copy: Mapping[str, Sequence[str]],
) -> list[str]:
    """Validate the six contract families and their non-schema invariants."""
    if not isinstance(bundle, Mapping):
        return ["portrait contract bundle must be a mapping"]
    errors: list[str] = []
    profile = bundle.get("portrait-brand-profile")
    energy = bundle.get("portrait-energy-map")
    motions = bundle.get("portrait-motion-contracts")
    sonic = bundle.get("portrait-sonic-plan")
    plan = bundle.get("style-reel-plan")
    review = bundle.get("style-reel-review")
    artifact_paths = bundle.get("artifact_paths")
    required_objects = {
        "portrait-brand-profile": profile,
        "portrait-energy-map": energy,
        "portrait-sonic-plan": sonic,
        "style-reel-plan": plan,
        "style-reel-review": review,
    }
    for name, payload in required_objects.items():
        errors.extend(validate_portrait_contract_schema(name, payload))
    if not isinstance(motions, list) or not motions:
        errors.append("portrait-motion-contracts must be a non-empty list")
        motions = []
    else:
        for index, motion in enumerate(motions):
            errors.extend(
                f"portrait-motion-contracts[{index}]: {error}"
                for error in validate_portrait_contract_schema(
                    "portrait-motion-contract", motion
                )
            )
    if not isinstance(artifact_paths, Mapping):
        errors.append("artifact_paths must be a mapping")
        artifact_paths = {}
    errors.extend(_artifact_binding_errors(bundle, artifact_paths))
    for name, payload in required_objects.items():
        errors.extend(_file_reference_errors(payload, name))
    for index, motion in enumerate(motions):
        errors.extend(_file_reference_errors(motion, f"portrait-motion-contracts[{index}]"))

    if not isinstance(profile, Mapping) or not isinstance(energy, Mapping):
        return errors
    if profile.get("profile_id") != "hongrun" or profile.get("identity_mode") != "self":
        errors.append("portrait brand profile must bind HongRun self identity")

    opportunities = energy.get("opportunities")
    if not isinstance(opportunities, list):
        opportunities = []
    opportunity_ids = [
        row.get("semantic_event_id")
        for row in opportunities
        if isinstance(row, Mapping)
    ]
    if opportunity_ids != list(expected_all_event_ids):
        errors.append("portrait energy semantic opportunity set/order differs from authority")
    if len(opportunity_ids) != len(set(opportunity_ids)):
        errors.append("portrait energy semantic opportunity IDs must be unique")
    policy = energy.get("selection_policy")
    if not isinstance(policy, Mapping) or policy.get("fixed_cadence") is not False:
        errors.append("portrait energy selection must not use fixed cadence")
    if not isinstance(policy, Mapping) or policy.get("minimum_event_quota") is not False:
        errors.append("portrait energy selection must not use event quotas")
    if not isinstance(policy, Mapping) or policy.get("random_rotation") is not False:
        errors.append("portrait energy selection must not use random rotation")

    energy_by_id = {
        str(row.get("semantic_event_id")): row
        for row in opportunities
        if isinstance(row, Mapping) and row.get("semantic_event_id")
    }
    authority_rows = energy.get("evidence_authorities")
    authority_by_id: dict[str, Mapping[str, Any]] = {}
    if not isinstance(authority_rows, list):
        errors.append("portrait energy typed evidence authorities are missing")
    else:
        for index, row in enumerate(authority_rows):
            if not isinstance(row, Mapping):
                errors.append(f"portrait energy evidence_authorities[{index}] must be a mapping")
                continue
            evidence_id = str(row.get("evidence_id") or "")
            if not evidence_id or evidence_id in authority_by_id:
                errors.append("portrait energy evidence authority IDs must be non-empty and unique")
                continue
            if row.get("authority_sha256") != _stable_hash(
                {key: value for key, value in row.items() if key != "authority_sha256"}
            ):
                errors.append(f"portrait energy evidence authority {evidence_id} hash is stale")
            authority_by_id[evidence_id] = row
    motion_ids = [
        row.get("semantic_event_id")
        for row in motions
        if isinstance(row, Mapping)
    ]
    if motion_ids != list(expected_render_event_ids):
        errors.append("portrait motion contract set/order differs from render authority")
    if len(motion_ids) != len(set(motion_ids)):
        errors.append("portrait motion contract semantic IDs must be unique")
    profile_ref = _expected_artifact_ref(artifact_paths, "portrait-brand-profile")
    energy_ref = _expected_artifact_ref(artifact_paths, "portrait-energy-map")
    for index, motion in enumerate(motions):
        if not isinstance(motion, Mapping):
            continue
        event_id = str(motion.get("semantic_event_id") or "")
        energy_row = energy_by_id.get(event_id)
        if isinstance(energy_row, Mapping) and motion.get("energy_tier") != energy_row.get("tier"):
            errors.append(f"portrait motion {event_id} energy tier differs from energy map")
        expected_copy = list(expected_visible_copy.get(event_id) or [])
        if list(motion.get("approved_visible_copy") or []) != expected_copy:
            errors.append(f"portrait motion {event_id} visible copy differs from authority")
        if profile_ref is not None and _canonical_ref(motion.get("brand_profile")) != profile_ref:
            errors.append(f"portrait motion {event_id} brand profile reference is stale")
        if energy_ref is not None and _canonical_ref(motion.get("energy_map")) != energy_ref:
            errors.append(f"portrait motion {event_id} energy map reference is stale")
        for field, expected_kind in (
            ("gesture_binding", "gesture_track"),
            ("subject_binding", "subject_track"),
            ("chapter_boundary_binding", "chapter_boundary"),
        ):
            binding = motion.get(field)
            if binding is None:
                continue
            if not isinstance(binding, Mapping):
                errors.append(f"portrait motion {event_id} {field} must be a mapping")
                continue
            authority = authority_by_id.get(str(binding.get("evidence_id") or ""))
            if not isinstance(authority, Mapping) or authority.get("kind") != expected_kind:
                errors.append(f"portrait motion {event_id} {field} is not typed current evidence")
                continue
            if binding.get("authority_sha256") != authority.get("authority_sha256") or (
                binding.get("source_sha256") != authority.get("source_sha256")
            ):
                errors.append(f"portrait motion {event_id} {field} hash binding is stale")
            for key, value in binding.items():
                if key in authority and authority.get(key) != value:
                    errors.append(
                        f"portrait motion {event_id} {field} {key} differs from authority"
                    )
            if binding.get("status") not in {"current", "tracked", "visible"}:
                errors.append(f"portrait motion {event_id} {field} is not usable")
            if expected_kind in {"subject_track", "gesture_track"} and binding.get("visible") is not True:
                errors.append(f"portrait motion {event_id} {field} is not usable or visible")
            time_domain = binding.get("time_domain")
            event_window = motion.get(
                "source_window" if time_domain == "source" else "output_window"
            ) if time_domain in {"source", "output"} else None
            authority_window = binding.get("window")
            if not isinstance(event_window, Mapping) or not isinstance(authority_window, Mapping):
                errors.append(f"portrait motion {event_id} {field} time window is invalid")
            else:
                try:
                    event_start = float(event_window["start_seconds"])
                    event_end = float(event_window["end_seconds"])
                    authority_start = float(authority_window["start_seconds"])
                    authority_end = float(authority_window["end_seconds"])
                except (KeyError, TypeError, ValueError):
                    errors.append(f"portrait motion {event_id} {field} time window is invalid")
                else:
                    if authority_end < event_start or authority_start > event_end:
                        errors.append(f"portrait motion {event_id} {field} is outside event window")
            if expected_kind == "chapter_boundary" and (
                authority.get("source") != "edl" or authority.get("structural") is not True
            ):
                errors.append(
                    f"portrait motion {event_id} chapter boundary is not independent EDL structure"
                )
        fallback = motion.get("fallback")
        fallback_target = str(
            fallback.get("target") if isinstance(fallback, Mapping) else ""
        ).lower()
        if any(marker in fallback_target for marker in PRODUCT_CARD_MARKERS):
            errors.append(f"portrait motion {event_id} uses a forbidden product-card fallback")

    if isinstance(sonic, Mapping):
        decisions = sonic.get("decisions")
        if not isinstance(decisions, list):
            decisions = []
        decision_ids = [
            row.get("event_id") for row in decisions if isinstance(row, Mapping)
        ]
        if decision_ids != list(expected_render_event_ids):
            errors.append("portrait sonic decisions must exactly cover render events")
        recipe_by_event = {
            str(row.get("semantic_event_id")): row.get("primary_recipe_id")
            for row in motions
            if isinstance(row, Mapping)
        }
        for row in decisions:
            if not isinstance(row, Mapping):
                continue
            event_id = str(row.get("event_id") or "")
            if row.get("recipe_id") != recipe_by_event.get(event_id):
                errors.append(f"portrait sonic decision {event_id} recipe is stale")
            family = row.get("motif_family_id")
            if family is not None and family not in (profile.get("sonic_family_ids") or []):
                errors.append(f"portrait sonic decision {event_id} family is outside profile")

    if isinstance(plan, Mapping):
        directions = plan.get("directions")
        if not isinstance(directions, list):
            directions = []
        direction_ids = [
            row.get("direction_id") for row in directions if isinstance(row, Mapping)
        ]
        if direction_ids != list(STYLE_DIRECTIONS):
            errors.append("Style Reel directions must equal the frozen A/B/C order")
        fingerprints = [
            row.get("structural_fingerprint")
            for row in directions
            if isinstance(row, Mapping)
        ]
        if len(fingerprints) != len(set(fingerprints)):
            errors.append("Style Reel structural fingerprints must be distinct")
        basis = plan.get("comparison_basis")
        basis_ids = (
            list(basis.get("semantic_event_ids") or [])
            if isinstance(basis, Mapping)
            else []
        )
        if basis_ids != list(expected_render_event_ids):
            errors.append("Style Reel comparison event IDs differ from render authority")

    if isinstance(review, Mapping):
        user = review.get("user")
        if not isinstance(user, Mapping) or user.get("actor") != "HongRun":
            errors.append("brand approval actor must be HongRun")
        reels = review.get("reels")
        if not isinstance(reels, list):
            reels = []
        reel_directions = [
            row.get("direction_id") for row in reels if isinstance(row, Mapping)
        ]
        if reel_directions != list(STYLE_DIRECTIONS):
            errors.append("Style Reel review directions differ from plan")
        for index, reel in enumerate(reels):
            if not isinstance(reel, Mapping):
                continue
            if list(reel.get("event_ids") or []) != list(expected_render_event_ids):
                errors.append(f"Style Reel reel event IDs differ at index {index}")
        if review.get("status") == "approved":
            automated = review.get("automated")
            multimodal = review.get("multimodal")
            if not isinstance(automated, Mapping) or automated.get("status") != "pass":
                errors.append("approved Style Reel requires passing automated evidence")
            if isinstance(multimodal, Mapping) and multimodal.get("recommendation") == "reject":
                errors.append("rejected multimodal review cannot become approved")
            if not isinstance(user, Mapping) or user.get("decision") != "select":
                errors.append("approved Style Reel requires HongRun selection")
            else:
                for field in (
                    "format_fit",
                    "person_primary",
                    "expressive_not_noisy",
                    "semantic_help",
                    "repeat_use_willingness",
                ):
                    if user.get(field) != "yes":
                        errors.append(f"approved Style Reel requires user {field}=yes")
                if user.get("sonic_fit") not in {"yes", "not_applicable"}:
                    errors.append("approved Style Reel requires user sonic_fit decision")
                if user.get("selected_direction_id") not in STYLE_DIRECTIONS:
                    errors.append("approved Style Reel selected direction is invalid")
                if not isinstance(user.get("reason"), str) or not user["reason"].strip():
                    errors.append("approved Style Reel requires a non-empty user reason")
                if not isinstance(user.get("reviewed_at"), str) or not user["reviewed_at"].strip():
                    errors.append("approved Style Reel requires reviewed_at")
    return errors
