#!/usr/bin/env python3
"""Hash-bound delivery contract for preservation-first video productions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from director_contracts import sha256_file


PROMISE_TYPES = {
    "source_led", "motion_led", "screen_demo", "talking_head", "teacher_explainer", "hybrid",
    "localization",
}
FORBIDDEN_QUOTA_FIELDS = {
    "events_per_minute", "minimum_motion_ratio", "minimum_event_count",
    "required_motion_coverage", "motion_quota",
}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _binding(path: Path, purpose: str) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "purpose": purpose,
    }


def _promise_type(project: dict[str, Any], input_mode: str) -> str:
    configured = str(
        project.get("workflow", {}).get("production_contract", {}).get("promise_type") or ""
    )
    if configured in PROMISE_TYPES:
        return configured
    content_type = str(project.get("content", {}).get("type") or "").lower()
    if any(token in content_type for token in ("screen", "tutorial", "demo")):
        return "screen_demo"
    if any(token in content_type for token in ("talking", "teacher", "course", "lecture")):
        return "talking_head" if "talking" in content_type else "teacher_explainer"
    if "hybrid" in content_type or "mixed" in content_type:
        return "hybrid"
    if "localization" in content_type:
        return "localization"
    if "motion" in content_type or "animation" in content_type:
        return "motion_led"
    return "source_led" if input_mode in {"preserve", "polish_existing"} else "hybrid"


def build_contract(
    *,
    project: dict[str, Any],
    source_path: Path,
    transcript_path: Path,
    edl_path: Path,
    semantic_brief_path: Path,
    input_mode: str,
) -> dict[str, Any]:
    """Build a deterministic contract from current evidence, without editing it."""
    inputs = {
        "source": _binding(source_path, "immutable source media"),
        "transcript": _binding(transcript_path, "video-use word transcript"),
        "edl": _binding(edl_path, "video-use retained timeline"),
        "semantic_brief": _binding(semantic_brief_path, "evidence-backed semantic direction"),
    }
    editing = project.get("editing", {})
    audio = project.get("audio", {})
    cover = project.get("cover", {})
    identity_mode = str(project.get("identity", {}).get("mode") or "generic")
    personal_identity_allowed = identity_mode == "self"
    implementation = Path(__file__).resolve()
    contract = {
        "schema_version": 1,
        "project_schema_version": project.get("schema_version", project.get("version")),
        "project_config_sha256": _stable_hash(project),
        "implementation": {
            "path": str(implementation),
            "sha256": sha256_file(implementation),
        },
        "inputs": inputs,
        "project_mode": input_mode,
        "identity": {
            "mode": identity_mode,
            "hongrun_assets_allowed": personal_identity_allowed,
            "personal_intro_outro_allowed": personal_identity_allowed,
            "first_person_brand_expression_allowed": personal_identity_allowed,
        },
        "delivery_promise": {
            "type": _promise_type(project, input_mode),
            "quality_floor": "publishable_after_human_review",
            "source_required": input_mode in {"preserve", "polish_existing"},
            "silent_downgrade_forbidden": True,
        },
        "preservation": {
            "source_meaning_required": True,
            "source_tail_required": True,
            "minimum_retained_ratio": 0.98 if input_mode == "polish_existing" else 0.95,
            "semantic_deletion_requires_review": True,
            "reorder_or_duplicate_requires_approval": True,
            "established_timeline_immutable": input_mode == "polish_existing",
        },
        "captions": {
            "source": "video-use-output-timeline-word-map",
            "wording": "spoken_words_only",
            "punctuation": editing.get("caption_punctuation", "spoken_clean"),
        },
        "motion_policy": {
            "author": "semantic_evidence_then_hyperframes",
            "fixed_event_quota_forbidden": True,
            "selection_basis": "viewer_takeaway_and_explanatory_value",
            "quiet_source_allowed": True,
            "low_information_anchors_forbidden": True,
            "random_decorative_motion_forbidden": True,
            "allowed_visual_families": [
                "keyword_typography", "ui_focus", "process", "comparison", "steps",
                "numeric_result", "chapter", "pip_zoom", "ip_asset", "quiet_source",
            ],
        },
        "owners": {
            "timeline": "video-use",
            "captions": "video-use",
            "creative_motion": "hyperframes",
            "final_media": "ffmpeg",
            "policy_qa_delivery": "content-preserving-video-editor",
        },
        "ip_visuals": {
            "mode": "content_specific_when_semantically_useful",
            "identity_reference_required": True,
            "topic_relevance_required": True,
            "forced_quota": False,
        },
        "audio": {
            "speech_dominant": True,
            "bgm_optional": True,
            "bgm_enabled_when_authorized": bool(
                audio.get("bgm", {}).get("enabled_by_default", True)
            ),
            "sfx_requires_event_decision": True,
            "post_mix_measurement_required": True,
        },
        "cover": {
            "route": cover.get("editorial", {}).get("mode", "auto"),
            "topic_evidence_required": True,
            "user_likeness_approval_required": True,
        },
        "external_policy": {
            "paid_call_requires_authorization": True,
            "provider_unavailable_must_be_reported": True,
            "privacy_and_locality_must_be_scored": True,
            "cost_estimate_reserve_reconcile_required": True,
            "privacy": "prefer authorized local processing; disclose configured external transfer",
        },
        "delivery": {
            "default_output": "single_universal_mp4",
            "platform_validations": ["douyin", "wechat_channels"],
            "duplicate_byte_identical_platform_files_forbidden": True,
            "human_aesthetic_review_required": True,
        },
    }
    contract["integrity_sha256"] = _stable_hash(contract)
    return contract


def validate_contract(
    contract: dict[str, Any],
    *,
    project: dict[str, Any],
    source_path: Path,
    transcript_path: Path,
    edl_path: Path,
    semantic_brief_path: Path,
    input_mode: str,
) -> list[str]:
    """Recompute bindings and reject weakened or stale production promises."""
    errors: list[str] = []
    if contract.get("schema_version") != 1:
        errors.append("production contract schema_version must be 1")
    if contract.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in contract.items() if key != "integrity_sha256"}
    ):
        errors.append("production contract integrity hash is stale")
    if contract.get("project_schema_version") != project.get(
        "schema_version", project.get("version")
    ):
        errors.append("production contract project schema version is stale")
    if contract.get("project_config_sha256") != _stable_hash(project):
        errors.append("production contract project configuration hash is stale")
    expected_inputs = {
        "source": source_path,
        "transcript": transcript_path,
        "edl": edl_path,
        "semantic_brief": semantic_brief_path,
    }
    for name, path in expected_inputs.items():
        row = (contract.get("inputs") or {}).get(name) or {}
        resolved = path.resolve()
        if row.get("path") != str(resolved):
            errors.append(f"production contract {name} path is stale")
        if not resolved.is_file() or row.get("sha256") != (
            sha256_file(resolved) if resolved.is_file() else None
        ):
            errors.append(f"production contract {name} hash is stale")
    if contract.get("project_mode") != input_mode:
        errors.append("production contract project mode is stale")
    identity = contract.get("identity") or {}
    expected_identity_mode = str(project.get("identity", {}).get("mode") or "generic")
    if identity.get("mode") != expected_identity_mode:
        errors.append("production contract identity mode is stale")
    personal_identity_allowed = expected_identity_mode == "self"
    for field in (
        "hongrun_assets_allowed",
        "personal_intro_outro_allowed",
        "first_person_brand_expression_allowed",
    ):
        if identity.get(field) is not personal_identity_allowed:
            errors.append(f"production contract identity.{field} is unsafe")
    promise = contract.get("delivery_promise") or {}
    if promise.get("type") not in PROMISE_TYPES:
        errors.append("production contract has an unsupported delivery promise")
    if promise.get("silent_downgrade_forbidden") is not True:
        errors.append("production contract must forbid silent delivery downgrade")
    preservation = contract.get("preservation") or {}
    for field in (
        "source_meaning_required", "source_tail_required",
        "semantic_deletion_requires_review", "reorder_or_duplicate_requires_approval",
    ):
        if preservation.get(field) is not True:
            errors.append(f"production contract preservation.{field} must be true")
    try:
        retained = float(preservation.get("minimum_retained_ratio"))
    except (TypeError, ValueError):
        retained = 0.0
    if retained < (0.98 if input_mode == "polish_existing" else 0.95):
        errors.append("production contract retention floor is too low")
    motion = contract.get("motion_policy") or {}
    if motion.get("fixed_event_quota_forbidden") is not True:
        errors.append("production contract must forbid fixed motion quota")
    if FORBIDDEN_QUOTA_FIELDS.intersection(motion):
        errors.append("production contract motion quota fields are forbidden")
    required_owners = {
        "timeline": "video-use",
        "captions": "video-use",
        "creative_motion": "hyperframes",
        "final_media": "ffmpeg",
        "policy_qa_delivery": "content-preserving-video-editor",
    }
    owners = contract.get("owners") or {}
    for field, owner in required_owners.items():
        if owners.get(field) != owner:
            errors.append(f"production contract owner mismatch: {field}")
    delivery = contract.get("delivery") or {}
    if delivery.get("default_output") != "single_universal_mp4":
        errors.append("production contract must promise one universal MP4 by default")
    implementation = contract.get("implementation") or {}
    implementation_path = Path(str(implementation.get("path") or ""))
    if (
        implementation_path.resolve() != Path(__file__).resolve()
        or not implementation_path.is_file()
        or implementation.get("sha256") != sha256_file(implementation_path)
    ):
        errors.append("production contract implementation binding is stale")
    expected = build_contract(
        project=project, source_path=source_path, transcript_path=transcript_path,
        edl_path=edl_path, semantic_brief_path=semantic_brief_path, input_mode=input_mode,
    )
    if contract != expected:
        errors.append("production contract does not match the deterministic current policy")
    return errors
