#!/usr/bin/env python3
"""In-memory project configuration migrations for the video director."""
from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any


CURRENT_PROJECT_SCHEMA_VERSION = 12
IDENTITY_MODES = {"self", "third_party", "generic"}
REQUIRED_ASSET_APPLICABILITY = {"required", "optional", "not_applicable"}
DELIVERABLE_READINESS = {"ready", "asset_ready", "not_applicable"}
MANUAL_FINISH_BACKENDS = {"opencut", "other_nle", "none"}
MANUAL_FINISH_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "backend": "none",
    "returned_final": None,
    "modifications": [],
    "assets": {},
    "nle_package": {
        "enabled": False,
        "profile": "jianying_desktop_compatible_v1",
        "level": "balanced",
        "include": {
            "motion_layers": True,
            "ip_assets": True,
            "modular_outro": True,
            "event_sfx": True,
        },
    },
}
PREVIEW_RENDER_PARITY_TOLERANCE_DEFAULTS: dict[str, float] = {
    "position_px": 4.0,
    "size_px": 4.0,
    "time_seconds": 0.05,
}
COVER_EDITORIAL_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "mode": "auto",
    "prefer_authentic_frame": False,
    "headline_max_characters": 26,
    "headline_max_lines": 3,
    "template_families": [
        "cinematic_editorial",
        "bright_tech_tutorial",
        "dark_high_energy",
        "thought_leadership_ip",
    ],
    "authentic_frames": [],
    "supporting_assets": [],
}
COVER_EDITORIAL_MODES = {
    "auto", "reference_regenerated", "authentic_frame_editorial", "real_person_ip_hybrid",
}
COVER_TEMPLATE_FAMILIES = {
    "cinematic_editorial", "bright_tech_tutorial", "dark_high_energy", "thought_leadership_ip",
}
VISUAL_DYNAMICS_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "blocking": True,
    "maximum_family_ratio": 0.65,
    "maximum_unexplained_gap_seconds": 30.0,
    "minimum_useful_content_ratio": 0.2,
}
OPENMONTAGE_HANDOFF_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "backend": "openmontage",
    "returned_final": None,
    "modifications": [],
    "assets": {},
}
SEMANTIC_CONFIDENCE_DEFAULTS = {
    "enabled": False,
    "low_confidence_threshold": 0.7,
    "second_provider": {"enabled": False},
}
PROTECTED_REGION_REVIEW_DEFAULTS = {
    "enabled": False,
    "manifest": None,
}
INTERACTIVE_REVIEW_DEFAULTS = {
    "enabled": False,
    "host": "127.0.0.1",
    "port": 8765,
    "max_body_bytes": 65536,
}
EVENT_CACHE_DEFAULTS = {
    "enabled": False,
    "fallback_to_full_render": True,
}
REFERENCE_PACK_DEFAULTS = {
    "enabled": False,
    "manifest": None,
    "required_roles": ["front", "smiling", "explaining"],
}
PREFERENCE_LEARNING_DEFAULTS = {
    "enabled": False,
    "minimum_samples": 2,
    "default_scope": "video",
}
EDITORIAL_INTENT_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "mode": "neutral_education",
    "audience": None,
    "viewer_job": None,
    "single_promise": None,
    "proof_event_ids": [],
    "cta": None,
    "tone": "neutral_educational",
    "prohibited_claims": [],
}
FEEDBACK_LOOP_DEFAULTS = {
    "enabled": False,
    "minimum_snapshots": 2,
    "minimum_views": 200,
    "minimum_elapsed_hours": 24.0,
}
AUDIT_BUNDLE_DEFAULTS = {
    "enabled": False,
    "output_dir": "work/director/portable-audit-bundle",
}
RELEASE_PACK_DEFAULTS = {
    "enabled": False,
    "require_privacy_audit": True,
    "require_rights_authorization": True,
    "require_publication_authorization": True,
    "privacy_manifest": None,
    "rights_manifest": None,
    "publication_authorization": None,
    "output_dir": "exports/release-pack",
}
PORTRAIT_BRAND_DIRECTIONS = [
    "luminous_intelligence",
    "high_energy_creator",
    "humanist_cinema",
]
PORTRAIT_BRAND_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "profile_path": None,
    "grammar_version": 2,
    "style_direction": None,
    "require_user_brand_approval": True,
    "style_reel": {
        "enabled": False,
        "target_duration_seconds": 38.0,
        "directions": PORTRAIT_BRAND_DIRECTIONS,
    },
}
CAPTION_TREATMENT_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "mode": "plain",
    "font_family": "Microsoft YaHei UI",
    "base_color": "#F7F8FA",
    "accent_colors": ["#51E3C2", "#FFD166"],
    "max_emphasis_terms_per_caption": 2,
    "max_scale_percent": 116,
}


def _required_asset_defaults(caption_delivery: str) -> dict[str, dict[str, str]]:
    captions = {
        "stage": "video_use_timeline",
        "applicability": "required",
        "required_readiness": "ready",
    }
    if caption_delivery == "none":
        captions = {
            "stage": "video_use_timeline",
            "applicability": "not_applicable",
            "required_readiness": "not_applicable",
            "reason": "editing.caption_delivery is explicitly none",
        }
    return {
        "captions": captions,
        "audio": {
            "stage": "audio",
            "applicability": "optional",
            "required_readiness": "asset_ready",
        },
        "cover": {
            "stage": "cover",
            "applicability": "optional",
            "required_readiness": "asset_ready",
        },
        "identity": {
            "stage": "production_contract",
            "applicability": "required",
            "required_readiness": "ready",
        },
        "universal_video": {
            "stage": "final_compose",
            "applicability": "required",
            "required_readiness": "ready",
        },
    }


def _source_version(project: dict[str, Any]) -> int:
    for field in ("schema_version", "version"):
        if field in project and (
            isinstance(project[field], bool)
            or not isinstance(project[field], int)
        ):
            raise ValueError("project schema versions must be integers")
    if "schema_version" in project and "version" in project:
        try:
            schema_version = int(project["schema_version"])
            legacy_version = int(project["version"])
        except (TypeError, ValueError) as error:
            raise ValueError("project schema versions must be integers") from error
        if schema_version != legacy_version:
            raise ValueError("project schema_version and version must match")
    value = project.get("schema_version", project.get("version", 1))
    try:
        version = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("project schema version must be an integer") from error
    if version < 1:
        raise ValueError("project schema version must be at least 1")
    if version > CURRENT_PROJECT_SCHEMA_VERSION:
        raise ValueError(
            f"project schema version {version} is newer than supported "
            f"version {CURRENT_PROJECT_SCHEMA_VERSION}"
        )
    return version


def migrate_project_config(project: dict[str, Any]) -> dict[str, Any]:
    """Return a current in-memory copy without modifying the source mapping/YAML."""
    if not isinstance(project, dict):
        raise ValueError("project configuration must be a mapping")
    source_version = _source_version(project)
    migrated = deepcopy(project)
    source = migrated.setdefault("source", {})
    if not isinstance(source, dict):
        raise ValueError("source must be a mapping")
    if "content_type" in source and source["content_type"] not in {
        "screen_tutorial", "talking_head",
    }:
        raise ValueError("source.content_type must be screen_tutorial or talking_head")
    editing = migrated.setdefault("editing", {})
    if not isinstance(editing, dict):
        raise ValueError("editing must be a mapping")
    caption_delivery = editing.setdefault("caption_delivery", "auto")
    if caption_delivery not in {"auto", "none"}:
        raise ValueError("editing.caption_delivery must be auto or none")
    caption_treatment = editing.setdefault("caption_treatment", {})
    if not isinstance(caption_treatment, dict):
        raise ValueError("editing.caption_treatment must be a mapping")
    unknown_treatment = set(caption_treatment) - set(CAPTION_TREATMENT_DEFAULTS)
    if unknown_treatment:
        raise ValueError("editing.caption_treatment has unsupported fields")
    for key, value in CAPTION_TREATMENT_DEFAULTS.items():
        caption_treatment.setdefault(key, deepcopy(value))
    if not isinstance(caption_treatment.get("enabled"), bool):
        raise ValueError("editing.caption_treatment.enabled must be a boolean")
    if caption_treatment.get("mode") not in {"plain", "semantic_emphasis"}:
        raise ValueError("editing.caption_treatment.mode is unsupported")
    if caption_treatment["enabled"] and caption_treatment["mode"] != "semantic_emphasis":
        raise ValueError("editing.caption_treatment enabled mode must be semantic_emphasis")
    if caption_delivery == "none" and caption_treatment["enabled"]:
        raise ValueError("editing.caption_treatment cannot be enabled when caption_delivery is none")
    for color_field in ("base_color",):
        value = caption_treatment.get(color_field)
        if not isinstance(value, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None:
            raise ValueError(f"editing.caption_treatment.{color_field} must be #RRGGBB")
    colors = caption_treatment.get("accent_colors")
    if (
        not isinstance(colors, list) or not 1 <= len(colors) <= 3
        or any(not isinstance(value, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None
               for value in colors)
    ):
        raise ValueError("editing.caption_treatment.accent_colors are invalid")
    font = caption_treatment.get("font_family")
    if not isinstance(font, str) or not font.strip() or any(char in font for char in "\r\n,;"):
        raise ValueError("editing.caption_treatment.font_family is invalid")
    maximum_terms = caption_treatment.get("max_emphasis_terms_per_caption")
    if isinstance(maximum_terms, bool) or not isinstance(maximum_terms, int) or maximum_terms not in {1, 2}:
        raise ValueError("editing.caption_treatment.max_emphasis_terms_per_caption must be 1 or 2")
    maximum_scale = caption_treatment.get("max_scale_percent")
    if isinstance(maximum_scale, bool) or not isinstance(maximum_scale, int) or not 105 <= maximum_scale <= 120:
        raise ValueError("editing.caption_treatment.max_scale_percent must be in [105, 120]")
    caption_sync = editing.setdefault("caption_sync_closure", {"enabled": False})
    if not isinstance(caption_sync, dict) or not isinstance(
        caption_sync.setdefault("enabled", False), bool
    ):
        raise ValueError("editing.caption_sync_closure.enabled must be a boolean")
    terminology = editing.setdefault("caption_terminology", [])
    if not isinstance(terminology, list) or any(
        not isinstance(value, str) or not value.strip() for value in terminology
    ):
        raise ValueError("editing.caption_terminology must be a list of non-empty strings")
    delivery = migrated.setdefault("delivery", {})
    if not isinstance(delivery, dict):
        raise ValueError("delivery must be a mapping")
    identity = migrated.setdefault("identity", {"mode": "generic"})
    if not isinstance(identity, dict):
        raise ValueError("identity must be a mapping")
    identity_mode = identity.setdefault("mode", "generic")
    if not isinstance(identity_mode, str) or identity_mode not in IDENTITY_MODES:
        raise ValueError("identity.mode must be self, third_party, or generic")
    motion_quality = migrated.setdefault("motion_quality", {"enabled": False})
    if not isinstance(motion_quality, dict) or not isinstance(
        motion_quality.setdefault("enabled", False), bool
    ):
        raise ValueError("motion_quality.enabled must be a boolean")
    advanced_runtimes = motion_quality.setdefault("advanced_runtimes", {"enabled": False})
    if not isinstance(advanced_runtimes, dict) or not isinstance(
        advanced_runtimes.setdefault("enabled", False), bool
    ):
        raise ValueError("motion_quality.advanced_runtimes.enabled must be a boolean")
    advanced_evidence = advanced_runtimes.setdefault("evidence", {})
    if not isinstance(advanced_evidence, dict):
        raise ValueError("motion_quality.advanced_runtimes.evidence must be a mapping")
    if source_version < 11:
        motion_quality["portrait_brand"] = deepcopy(PORTRAIT_BRAND_DEFAULTS)
    portrait_brand = motion_quality.setdefault(
        "portrait_brand", deepcopy(PORTRAIT_BRAND_DEFAULTS)
    )
    if not isinstance(portrait_brand, dict):
        raise ValueError("motion_quality.portrait_brand must be a mapping")
    allowed_portrait_keys = set(PORTRAIT_BRAND_DEFAULTS)
    unknown_portrait_keys = set(portrait_brand) - allowed_portrait_keys
    if unknown_portrait_keys:
        raise ValueError(
            "motion_quality.portrait_brand has unsupported fields: "
            + ", ".join(sorted(unknown_portrait_keys))
        )
    for key, value in PORTRAIT_BRAND_DEFAULTS.items():
        portrait_brand.setdefault(key, deepcopy(value))
    if not isinstance(portrait_brand.get("enabled"), bool):
        raise ValueError("motion_quality.portrait_brand.enabled must be a boolean")
    profile_path = portrait_brand.get("profile_path")
    if profile_path is not None and (
        not isinstance(profile_path, str) or not profile_path.strip()
    ):
        raise ValueError("motion_quality.portrait_brand.profile_path must be a path or null")
    grammar_version = portrait_brand.get("grammar_version")
    if isinstance(grammar_version, bool) or grammar_version != 2:
        raise ValueError("motion_quality.portrait_brand.grammar_version must be 2")
    style_direction = portrait_brand.get("style_direction")
    if style_direction is not None and style_direction not in PORTRAIT_BRAND_DIRECTIONS:
        raise ValueError("motion_quality.portrait_brand.style_direction is unsupported")
    if portrait_brand.get("require_user_brand_approval") is not True:
        raise ValueError(
            "motion_quality.portrait_brand.require_user_brand_approval must be true"
        )
    style_reel = portrait_brand.get("style_reel")
    if not isinstance(style_reel, dict):
        raise ValueError("motion_quality.portrait_brand.style_reel must be a mapping")
    allowed_style_reel_keys = set(PORTRAIT_BRAND_DEFAULTS["style_reel"])
    unknown_style_reel_keys = set(style_reel) - allowed_style_reel_keys
    if unknown_style_reel_keys:
        raise ValueError(
            "motion_quality.portrait_brand.style_reel has unsupported fields: "
            + ", ".join(sorted(unknown_style_reel_keys))
        )
    for key, value in PORTRAIT_BRAND_DEFAULTS["style_reel"].items():
        style_reel.setdefault(key, deepcopy(value))
    if not isinstance(style_reel.get("enabled"), bool):
        raise ValueError("motion_quality.portrait_brand.style_reel.enabled must be a boolean")
    duration = style_reel.get("target_duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or not 30.0 <= float(duration) <= 45.0
    ):
        raise ValueError(
            "motion_quality.portrait_brand.style_reel.target_duration_seconds "
            "must be finite and in [30, 45]"
        )
    style_reel["target_duration_seconds"] = float(duration)
    if style_reel.get("directions") != PORTRAIT_BRAND_DIRECTIONS:
        raise ValueError(
            "motion_quality.portrait_brand.style_reel.directions must equal the frozen A/B/C set"
        )
    if portrait_brand["enabled"]:
        if motion_quality["enabled"] is not True:
            raise ValueError(
                "motion_quality.enabled must be true when portrait_brand is enabled"
            )
        if identity_mode != "self":
            raise ValueError(
                "motion_quality.portrait_brand requires identity.mode self"
            )
        if not isinstance(profile_path, str) or not profile_path.strip():
            raise ValueError(
                "motion_quality.portrait_brand.profile_path is required when enabled"
            )
        if source.get("content_type") not in {None, "talking_head"}:
            raise ValueError(
                "motion_quality.portrait_brand requires talking_head source content"
            )
        if style_direction is None:
            raise ValueError(
                "motion_quality.portrait_brand.style_direction is required when enabled"
            )
    required_assets = delivery.setdefault("required_assets", {})
    if not isinstance(required_assets, dict):
        raise ValueError("delivery.required_assets must be a mapping")
    for asset_name, default_rule in _required_asset_defaults(caption_delivery).items():
        rule = required_assets.setdefault(asset_name, deepcopy(default_rule))
        if not isinstance(rule, dict):
            raise ValueError(f"delivery.required_assets.{asset_name} must be a mapping")
        for key, value in default_rule.items():
            rule.setdefault(key, value)
        prefix = f"delivery.required_assets.{asset_name}"
        if not isinstance(rule.get("stage"), str) or not rule["stage"].strip():
            raise ValueError(f"{prefix}.stage must be a non-empty string")
        if rule.get("applicability") not in REQUIRED_ASSET_APPLICABILITY:
            raise ValueError(f"{prefix}.applicability is unsupported")
        if rule.get("required_readiness") not in DELIVERABLE_READINESS:
            raise ValueError(f"{prefix}.required_readiness is not deliverable")
        if rule.get("applicability") == "required" and rule.get(
            "required_readiness"
        ) == "not_applicable":
            raise ValueError(f"{prefix} cannot be required and not_applicable")
        if rule.get("applicability") == "not_applicable":
            if rule.get("required_readiness") != "not_applicable":
                raise ValueError(f"{prefix} not_applicable must require not_applicable readiness")
            if not isinstance(rule.get("reason"), str) or not rule["reason"].strip():
                raise ValueError(f"{prefix}.reason is required when not_applicable")
        if rule.get("stage") != default_rule["stage"]:
            raise ValueError(f"{prefix}.stage cannot be rebound")
        if (
            rule.get("applicability") != "not_applicable"
            and rule.get("required_readiness") != default_rule["required_readiness"]
        ):
            raise ValueError(f"{prefix}.required_readiness cannot weaken asset delivery")
        if asset_name in {"captions", "identity", "universal_video"}:
            expected_policy = (
                default_rule["stage"],
                default_rule["applicability"],
                default_rule["required_readiness"],
            )
            actual_policy = (
                rule.get("stage"),
                rule.get("applicability"),
                rule.get("required_readiness"),
            )
            if actual_policy != expected_policy:
                raise ValueError(f"{prefix} cannot weaken or rebind mandatory delivery policy")
    manual = delivery.setdefault("manual_finish", {})
    if not isinstance(manual, dict):
        raise ValueError("delivery.manual_finish must be a mapping")
    for key, value in MANUAL_FINISH_DEFAULTS.items():
        manual.setdefault(key, deepcopy(value))
    if manual.get("backend") not in MANUAL_FINISH_BACKENDS:
        raise ValueError(
            "delivery.manual_finish.backend must be one of "
            f"{sorted(MANUAL_FINISH_BACKENDS)}"
        )
    if not isinstance(manual.get("enabled"), bool):
        raise ValueError("delivery.manual_finish.enabled must be a boolean")
    if not isinstance(manual.get("modifications"), list):
        raise ValueError("delivery.manual_finish.modifications must be a list")
    if not isinstance(manual.get("assets"), dict):
        raise ValueError("delivery.manual_finish.assets must be a mapping")
    nle_package = manual.get("nle_package")
    if not isinstance(nle_package, dict):
        raise ValueError("delivery.manual_finish.nle_package must be a mapping")
    nle_defaults = MANUAL_FINISH_DEFAULTS["nle_package"]
    allowed_nle_keys = set(nle_defaults)
    unknown_nle_keys = set(nle_package) - allowed_nle_keys
    if unknown_nle_keys:
        raise ValueError(
            "delivery.manual_finish.nle_package has unsupported fields: "
            + ", ".join(sorted(unknown_nle_keys))
        )
    for key in ("enabled", "profile", "level"):
        nle_package.setdefault(key, deepcopy(nle_defaults[key]))
    nle_include = nle_package.setdefault("include", deepcopy(nle_defaults["include"]))
    if not isinstance(nle_package.get("enabled"), bool):
        raise ValueError("delivery.manual_finish.nle_package.enabled must be a boolean")
    if nle_package.get("profile") != "jianying_desktop_compatible_v1":
        raise ValueError(
            "delivery.manual_finish.nle_package.profile must be "
            "jianying_desktop_compatible_v1"
        )
    if nle_package.get("level") not in {"reference_only", "balanced", "max_editable"}:
        raise ValueError(
            "delivery.manual_finish.nle_package.level must be reference_only, balanced, "
            "or max_editable"
        )
    if not isinstance(nle_include, dict):
        raise ValueError("delivery.manual_finish.nle_package.include must be a mapping")
    for key, value in nle_defaults["include"].items():
        nle_include.setdefault(key, value)
    allowed_nle_include = {"motion_layers", "ip_assets", "modular_outro", "event_sfx"}
    if set(nle_include) != allowed_nle_include:
        raise ValueError("delivery.manual_finish.nle_package.include has unknown or missing keys")
    for key in sorted(allowed_nle_include):
        if not isinstance(nle_include.get(key), bool):
            raise ValueError(f"delivery.manual_finish.nle_package.include.{key} must be a boolean")
    openmontage = delivery.setdefault("openmontage_handoff", {})
    if not isinstance(openmontage, dict):
        raise ValueError("delivery.openmontage_handoff must be a mapping")
    for key, value in OPENMONTAGE_HANDOFF_DEFAULTS.items():
        openmontage.setdefault(key, deepcopy(value))
    if not isinstance(openmontage.get("enabled"), bool):
        raise ValueError("delivery.openmontage_handoff.enabled must be a boolean")
    if openmontage.get("backend") != "openmontage":
        raise ValueError("delivery.openmontage_handoff.backend must be openmontage")
    if not isinstance(openmontage.get("modifications"), list):
        raise ValueError("delivery.openmontage_handoff.modifications must be a list")
    if not isinstance(openmontage.get("assets"), dict):
        raise ValueError("delivery.openmontage_handoff.assets must be a mapping")
    if manual.get("enabled") is True and openmontage.get("enabled") is True:
        raise ValueError("manual_finish and openmontage_handoff cannot both be enabled")
    qa = migrated.setdefault("qa", {})
    if not isinstance(qa, dict):
        raise ValueError("qa must be a mapping")
    parity = qa.setdefault("preview_render_parity", {})
    if not isinstance(parity, dict):
        raise ValueError("qa.preview_render_parity must be a mapping")
    tolerances = parity.setdefault("tolerances", {})
    if not isinstance(tolerances, dict):
        raise ValueError("qa.preview_render_parity.tolerances must be a mapping")
    for key, value in PREVIEW_RENDER_PARITY_TOLERANCE_DEFAULTS.items():
        tolerances.setdefault(key, value)
    for key in PREVIEW_RENDER_PARITY_TOLERANCE_DEFAULTS:
        raw_tolerance = tolerances[key]
        if isinstance(raw_tolerance, bool) or not isinstance(raw_tolerance, (int, float)):
            raise ValueError(f"qa.preview_render_parity.tolerances.{key} must be numeric")
        try:
            tolerance = float(raw_tolerance)
        except (TypeError, ValueError) as error:
            raise ValueError(f"qa.preview_render_parity.tolerances.{key} must be numeric") from error
        if not math.isfinite(tolerance):
            raise ValueError(f"qa.preview_render_parity.tolerances.{key} must be finite")
        if tolerance < 0:
            raise ValueError(f"qa.preview_render_parity.tolerances.{key} must be non-negative")
        tolerances[key] = tolerance
    platform_occlusion = qa.setdefault("platform_occlusion", {"enabled": False})
    if not isinstance(platform_occlusion, dict) or not isinstance(
        platform_occlusion.setdefault("enabled", False), bool
    ):
        raise ValueError("qa.platform_occlusion.enabled must be a boolean")
    visual_dynamics = qa.setdefault("visual_dynamics", {})
    if not isinstance(visual_dynamics, dict):
        raise ValueError("qa.visual_dynamics must be a mapping")
    for key, value in VISUAL_DYNAMICS_DEFAULTS.items():
        visual_dynamics.setdefault(key, value)
    for key in ("enabled", "blocking"):
        if not isinstance(visual_dynamics.get(key), bool):
            raise ValueError(f"qa.visual_dynamics.{key} must be a boolean")
    for key in (
        "maximum_family_ratio", "maximum_unexplained_gap_seconds",
        "minimum_useful_content_ratio",
    ):
        value = visual_dynamics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"qa.visual_dynamics.{key} must be numeric")
        visual_dynamics[key] = float(value)
    if not 0 < visual_dynamics["maximum_family_ratio"] <= 1:
        raise ValueError("qa.visual_dynamics.maximum_family_ratio must be in (0, 1]")
    if visual_dynamics["maximum_unexplained_gap_seconds"] <= 0:
        raise ValueError("qa.visual_dynamics.maximum_unexplained_gap_seconds must be positive")
    if not 0 <= visual_dynamics["minimum_useful_content_ratio"] <= 1:
        raise ValueError("qa.visual_dynamics.minimum_useful_content_ratio must be in [0, 1]")
    workflow = migrated.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        raise ValueError("workflow must be a mapping")
    capabilities = workflow.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("workflow.capabilities must be a mapping")
    production_contract = workflow.setdefault("production_contract", {"enabled": True})
    if not isinstance(production_contract, dict) or not isinstance(
        production_contract.setdefault("enabled", True), bool
    ):
        raise ValueError("workflow.production_contract.enabled must be a boolean")
    analysis = migrated.setdefault("analysis", {})
    if not isinstance(analysis, dict):
        raise ValueError("analysis must be a mapping")
    adapters = analysis.setdefault("adapters", {})
    if not isinstance(adapters, dict):
        raise ValueError("analysis.adapters must be a mapping")
    for name in ("pyscenedetect", "mediapipe", "paddleocr"):
        value = adapters.setdefault(name, {"enabled": False})
        if not isinstance(value, dict) or not isinstance(value.setdefault("enabled", False), bool):
            raise ValueError(f"analysis.adapters.{name}.enabled must be a boolean")
    subject_tracking = analysis.setdefault("subject_tracking", {"enabled": False})
    if not isinstance(subject_tracking, dict) or not isinstance(
        subject_tracking.setdefault("enabled", False), bool
    ):
        raise ValueError("analysis.subject_tracking.enabled must be a boolean")
    protected_region_review = analysis.setdefault("protected_region_review", {})
    if not isinstance(protected_region_review, dict):
        raise ValueError("analysis.protected_region_review must be a mapping")
    for key, value in PROTECTED_REGION_REVIEW_DEFAULTS.items():
        protected_region_review.setdefault(key, value)
    if not isinstance(protected_region_review.get("enabled"), bool):
        raise ValueError("analysis.protected_region_review.enabled must be a boolean")
    review_manifest = protected_region_review.get("manifest")
    if review_manifest is not None and (
        not isinstance(review_manifest, str) or not review_manifest.strip()
    ):
        raise ValueError("analysis.protected_region_review.manifest must be a path or null")
    if protected_region_review["enabled"] and review_manifest is None:
        raise ValueError(
            "analysis.protected_region_review.manifest is required when enabled"
        )
    semantic_confidence = analysis.setdefault("semantic_confidence", {})
    if not isinstance(semantic_confidence, dict):
        raise ValueError("analysis.semantic_confidence must be a mapping")
    for key, value in SEMANTIC_CONFIDENCE_DEFAULTS.items():
        semantic_confidence.setdefault(key, deepcopy(value))
    if not isinstance(semantic_confidence.get("enabled"), bool):
        raise ValueError("analysis.semantic_confidence.enabled must be a boolean")
    threshold = semantic_confidence.get("low_confidence_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) \
            or not math.isfinite(float(threshold)) or not 0 < float(threshold) <= 1:
        raise ValueError("analysis.semantic_confidence.low_confidence_threshold must be in (0, 1]")
    semantic_confidence["low_confidence_threshold"] = float(threshold)
    second_provider = semantic_confidence.get("second_provider")
    if not isinstance(second_provider, dict) or not isinstance(
        second_provider.setdefault("enabled", False), bool
    ):
        raise ValueError("analysis.semantic_confidence.second_provider.enabled must be a boolean")
    transcription = migrated.setdefault("transcription", {})
    if not isinstance(transcription, dict):
        raise ValueError("transcription must be a mapping")
    router = transcription.setdefault("router", {"enabled": False})
    if not isinstance(router, dict) or not isinstance(router.setdefault("enabled", False), bool):
        raise ValueError("transcription.router.enabled must be a boolean")
    timeline = migrated.setdefault("timeline", {})
    if not isinstance(timeline, dict):
        raise ValueError("timeline must be a mapping")
    otio = timeline.setdefault("otio", {"enabled": False})
    if not isinstance(otio, dict) or not isinstance(otio.setdefault("enabled", False), bool):
        raise ValueError("timeline.otio.enabled must be a boolean")
    render = migrated.setdefault("render", {})
    if not isinstance(render, dict):
        raise ValueError("render must be a mapping")
    cache = render.setdefault("cache", {"enabled": False})
    if not isinstance(cache, dict) or not isinstance(cache.setdefault("enabled", False), bool):
        raise ValueError("render.cache.enabled must be a boolean")
    event_cache = cache.setdefault("event_level", {})
    if not isinstance(event_cache, dict):
        raise ValueError("render.cache.event_level must be a mapping")
    for key, value in EVENT_CACHE_DEFAULTS.items():
        event_cache.setdefault(key, value)
    for key in ("enabled", "fallback_to_full_render"):
        if not isinstance(event_cache.get(key), bool):
            raise ValueError(f"render.cache.event_level.{key} must be a boolean")
    extensions = migrated.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("extensions must be a mapping")
    for name in ("b_roll", "multicam", "voice_isolation", "localization"):
        value = extensions.setdefault(name, {"enabled": False})
        if not isinstance(value, dict) or not isinstance(value.setdefault("enabled", False), bool):
            raise ValueError(f"extensions.{name}.enabled must be a boolean")
    optional_media = extensions.setdefault("optional_media_adapters", [])
    if not isinstance(optional_media, list) or any(
        not isinstance(value, dict) for value in optional_media
    ):
        raise ValueError("extensions.optional_media_adapters must be a list of mappings")
    for index, value in enumerate(optional_media):
        if not isinstance(value.setdefault("enabled", False), bool):
            raise ValueError(
                f"extensions.optional_media_adapters[{index}].enabled must be a boolean"
            )
    renderer = migrated.setdefault("renderer", {})
    if not isinstance(renderer, dict):
        raise ValueError("renderer must be a mapping")
    remotion = renderer.setdefault("remotion", {"enabled": False})
    if not isinstance(remotion, dict) or not isinstance(remotion.setdefault("enabled", False), bool):
        raise ValueError("renderer.remotion.enabled must be a boolean")
    feedback = migrated.setdefault("feedback", {})
    if not isinstance(feedback, dict):
        raise ValueError("feedback must be a mapping")
    metrics = feedback.setdefault("metrics_import", {"enabled": False})
    if not isinstance(metrics, dict) or not isinstance(metrics.setdefault("enabled", False), bool):
        raise ValueError("feedback.metrics_import.enabled must be a boolean")
    feedback_loop = feedback.setdefault("learning_loop", {})
    if not isinstance(feedback_loop, dict):
        raise ValueError("feedback.learning_loop must be a mapping")
    for key, value in FEEDBACK_LOOP_DEFAULTS.items():
        feedback_loop.setdefault(key, value)
    if not isinstance(feedback_loop.get("enabled"), bool):
        raise ValueError("feedback.learning_loop.enabled must be a boolean")
    for key in ("minimum_snapshots", "minimum_views"):
        value = feedback_loop.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"feedback.learning_loop.{key} must be a positive integer")
    elapsed = feedback_loop.get("minimum_elapsed_hours")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) \
            or not math.isfinite(float(elapsed)) or float(elapsed) < 0:
        raise ValueError("feedback.learning_loop.minimum_elapsed_hours must be non-negative")
    feedback_loop["minimum_elapsed_hours"] = float(elapsed)
    audio = migrated.setdefault("audio", {})
    if not isinstance(audio, dict):
        raise ValueError("audio must be a mapping")
    audio_production = audio.setdefault("production", {"enabled": False})
    if not isinstance(audio_production, dict) or not isinstance(
        audio_production.setdefault("enabled", False), bool
    ):
        raise ValueError("audio.production.enabled must be a boolean")
    normalization = audio.setdefault("normalization", {
        "enabled": False,
        "target_lufs": -14.0,
        "true_peak_dbtp": -1.5,
        "lra": 11.0,
    })
    if not isinstance(normalization, dict) or not isinstance(
        normalization.setdefault("enabled", False), bool
    ):
        raise ValueError("audio.normalization.enabled must be a boolean")
    for name, default in (("target_lufs", -14.0), ("true_peak_dbtp", -1.5), ("lra", 11.0)):
        value = normalization.setdefault(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"audio.normalization.{name} must be numeric")
        normalization[name] = float(value)
    bgm = audio.setdefault("bgm", {})
    if not isinstance(bgm, dict):
        raise ValueError("audio.bgm must be a mapping")
    providers = bgm.setdefault("provider_chain", [])
    if not isinstance(providers, list):
        raise ValueError("audio.bgm.provider_chain must be a list")
    sfx = audio.setdefault("sfx", {})
    if not isinstance(sfx, dict):
        raise ValueError("audio.sfx must be a mapping")
    maximum_family_ratio = sfx.setdefault("maximum_family_ratio", 0.5)
    if (
        isinstance(maximum_family_ratio, bool)
        or not isinstance(maximum_family_ratio, (int, float))
        or not math.isfinite(float(maximum_family_ratio))
        or not 0 < float(maximum_family_ratio) <= 1
    ):
        raise ValueError("audio.sfx.maximum_family_ratio must be in (0, 1]")
    sfx["maximum_family_ratio"] = float(maximum_family_ratio)
    perceptual = sfx.setdefault("perceptual", {
        "enabled": False,
        "minimum_audible_ratio": 0.35,
        "maximum_audible_ratio": 0.65,
        "maximum_onset_error_ms": 80.0,
    })
    if not isinstance(perceptual, dict) or not isinstance(
        perceptual.setdefault("enabled", False), bool
    ):
        raise ValueError("audio.sfx.perceptual.enabled must be a boolean")
    for key, default in (
        ("minimum_audible_ratio", 0.35),
        ("maximum_audible_ratio", 0.65),
        ("maximum_onset_error_ms", 80.0),
    ):
        value = perceptual.setdefault(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise ValueError(f"audio.sfx.perceptual.{key} must be numeric")
        perceptual[key] = float(value)
    if not 0 <= perceptual["minimum_audible_ratio"] <= perceptual["maximum_audible_ratio"] <= 1:
        raise ValueError("audio.sfx.perceptual audible ratios must satisfy 0 <= minimum <= maximum <= 1")
    if perceptual["maximum_onset_error_ms"] <= 0:
        raise ValueError("audio.sfx.perceptual.maximum_onset_error_ms must be positive")
    cover = migrated.setdefault("cover", {})
    if not isinstance(cover, dict):
        raise ValueError("cover must be a mapping")
    cover_production = cover.setdefault("production", {"enabled": False})
    if not isinstance(cover_production, dict) or not isinstance(
        cover_production.setdefault("enabled", False), bool
    ):
        raise ValueError("cover.production.enabled must be a boolean")
    cover_editorial = cover.setdefault("editorial", {})
    if not isinstance(cover_editorial, dict):
        raise ValueError("cover.editorial must be a mapping")
    for key, value in COVER_EDITORIAL_DEFAULTS.items():
        cover_editorial.setdefault(key, deepcopy(value))
    if not isinstance(cover_editorial.get("enabled"), bool):
        raise ValueError("cover.editorial.enabled must be a boolean")
    if cover_editorial.get("mode") not in COVER_EDITORIAL_MODES:
        raise ValueError(
            "cover.editorial.mode must be one of " + str(sorted(COVER_EDITORIAL_MODES))
        )
    if not isinstance(cover_editorial.get("prefer_authentic_frame"), bool):
        raise ValueError("cover.editorial.prefer_authentic_frame must be a boolean")
    for key in ("headline_max_characters", "headline_max_lines"):
        value = cover_editorial.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"cover.editorial.{key} must be a positive integer")
    templates = cover_editorial.get("template_families")
    if not isinstance(templates, list) or not templates:
        raise ValueError("cover.editorial.template_families must be a non-empty list")
    invalid_templates = [value for value in templates if value not in COVER_TEMPLATE_FAMILIES]
    if invalid_templates:
        raise ValueError(
            "cover.editorial.template_families contains unsupported values: "
            + ", ".join(str(value) for value in invalid_templates)
        )
    for key in ("authentic_frames", "supporting_assets"):
        if not isinstance(cover_editorial.get(key), list):
            raise ValueError(f"cover.editorial.{key} must be a list")
    reference_pack = cover.setdefault("reference_pack", {})
    if not isinstance(reference_pack, dict):
        raise ValueError("cover.reference_pack must be a mapping")
    for key, value in REFERENCE_PACK_DEFAULTS.items():
        reference_pack.setdefault(key, deepcopy(value))
    if not isinstance(reference_pack.get("enabled"), bool):
        raise ValueError("cover.reference_pack.enabled must be a boolean")
    if not isinstance(reference_pack.get("required_roles"), list):
        raise ValueError("cover.reference_pack.required_roles must be a list")
    visuals = migrated.setdefault("visuals", {})
    if not isinstance(visuals, dict):
        raise ValueError("visuals must be a mapping")
    ip_production = visuals.setdefault("ip_production", {"enabled": False})
    if not isinstance(ip_production, dict) or not isinstance(
        ip_production.setdefault("enabled", False), bool
    ):
        raise ValueError("visuals.ip_production.enabled must be a boolean")
    assets = migrated.setdefault("assets", {})
    if not isinstance(assets, dict):
        raise ValueError("assets must be a mapping")
    media_catalog = assets.setdefault("media_catalog", {"enabled": False})
    if not isinstance(media_catalog, dict) or not isinstance(
        media_catalog.setdefault("enabled", False), bool
    ):
        raise ValueError("assets.media_catalog.enabled must be a boolean")
    semantic_corpus = assets.setdefault("local_semantic_corpus", {
        "enabled": False,
        "backend": "none",
        "index": "work/director/semantic-corpus/index.json",
        "embedding_model": None,
        "command": [],
    })
    if not isinstance(semantic_corpus, dict) or not isinstance(
        semantic_corpus.setdefault("enabled", False), bool
    ):
        raise ValueError("assets.local_semantic_corpus.enabled must be a boolean")
    if not isinstance(semantic_corpus.setdefault("command", []), list):
        raise ValueError("assets.local_semantic_corpus.command must be a list")
    if semantic_corpus.setdefault("backend", "none") not in {
        "none", "fixture", "precomputed", "clip", "command",
    }:
        raise ValueError("assets.local_semantic_corpus.backend is unsupported")
    hook_pacing = analysis.setdefault("hook_pacing", {"enabled": False})
    if not isinstance(hook_pacing, dict) or not isinstance(
        hook_pacing.setdefault("enabled", False), bool
    ):
        raise ValueError("analysis.hook_pacing.enabled must be a boolean")
    publishing = migrated.setdefault("publishing", {})
    if not isinstance(publishing, dict):
        raise ValueError("publishing must be a mapping")
    publishing_copy = publishing.setdefault("copy", {"enabled": False})
    if not isinstance(publishing_copy, dict) or not isinstance(
        publishing_copy.setdefault("enabled", False), bool
    ):
        raise ValueError("publishing.copy.enabled must be a boolean")
    editorial_intent = migrated.setdefault("editorial_intent", {})
    if not isinstance(editorial_intent, dict):
        raise ValueError("editorial_intent must be a mapping")
    for key, value in EDITORIAL_INTENT_DEFAULTS.items():
        editorial_intent.setdefault(key, deepcopy(value))
    if not isinstance(editorial_intent.get("enabled"), bool):
        raise ValueError("editorial_intent.enabled must be a boolean")
    if editorial_intent.get("mode") not in {"neutral_education", "explicit"}:
        raise ValueError("editorial_intent.mode must be neutral_education or explicit")
    for key in ("proof_event_ids", "prohibited_claims"):
        if not isinstance(editorial_intent.get(key), list) or any(
            not isinstance(value, str) for value in editorial_intent[key]
        ):
            raise ValueError(f"editorial_intent.{key} must be a list of strings")
    if editorial_intent.get("enabled") is True and editorial_intent.get("mode") == "explicit":
        missing = [
            key for key in ("audience", "viewer_job", "single_promise", "cta", "tone")
            if not isinstance(editorial_intent.get(key), str)
            or not editorial_intent[key].strip()
        ]
        if missing:
            raise ValueError("explicit editorial_intent is missing: " + ", ".join(missing))
    preferences = migrated.setdefault("preferences", {"enabled": False})
    if not isinstance(preferences, dict) or not isinstance(
        preferences.setdefault("enabled", False), bool
    ):
        raise ValueError("preferences.enabled must be a boolean")
    learning = preferences.setdefault("learning", {})
    if not isinstance(learning, dict):
        raise ValueError("preferences.learning must be a mapping")
    for key, value in PREFERENCE_LEARNING_DEFAULTS.items():
        learning.setdefault(key, value)
    if not isinstance(learning.get("enabled"), bool):
        raise ValueError("preferences.learning.enabled must be a boolean")
    minimum_samples = learning.get("minimum_samples")
    if isinstance(minimum_samples, bool) or not isinstance(minimum_samples, int) or minimum_samples < 1:
        raise ValueError("preferences.learning.minimum_samples must be a positive integer")
    if learning.get("default_scope") not in {"video", "content_type", "profile"}:
        raise ValueError("preferences.learning.default_scope is unsupported")
    provider_governance = migrated.setdefault("provider_governance", {
        "enabled": True,
        "mode": "observe",
        "currency": "USD",
        "budget_total": None,
        "single_action_approval": None,
        "max_evidence_age_days": 30,
        "providers": {},
    })
    if not isinstance(provider_governance, dict) or not isinstance(
        provider_governance.setdefault("enabled", True), bool
    ):
        raise ValueError("provider_governance.enabled must be a boolean")
    if provider_governance.setdefault("mode", "observe") not in {"observe", "warn", "cap"}:
        raise ValueError("provider_governance.mode must be observe, warn, or cap")
    max_evidence_age_days = provider_governance.setdefault("max_evidence_age_days", 30)
    if not isinstance(max_evidence_age_days, int) or isinstance(max_evidence_age_days, bool) or max_evidence_age_days < 1:
        raise ValueError("provider_governance.max_evidence_age_days must be a positive integer")
    if not isinstance(provider_governance.setdefault("providers", {}), dict):
        raise ValueError("provider_governance.providers must be a mapping")
    brand = migrated.setdefault("brand", {})
    if not isinstance(brand, dict):
        raise ValueError("brand must be a mapping")
    motion_playbook = brand.setdefault("motion_playbook", {"enabled": True})
    if not isinstance(motion_playbook, dict) or not isinstance(
        motion_playbook.setdefault("enabled", True), bool
    ):
        raise ValueError("brand.motion_playbook.enabled must be a boolean")
    editorial_regression = migrated.setdefault("editorial_regression", {"enabled": False})
    if not isinstance(editorial_regression, dict) or not isinstance(
        editorial_regression.setdefault("enabled", False), bool
    ):
        raise ValueError("editorial_regression.enabled must be a boolean")
    review = migrated.setdefault("review", {})
    if not isinstance(review, dict):
        raise ValueError("review must be a mapping")
    dashboard = review.setdefault("dashboard", {"enabled": True})
    if not isinstance(dashboard, dict) or not isinstance(
        dashboard.setdefault("enabled", True), bool
    ):
        raise ValueError("review.dashboard.enabled must be a boolean")
    interactive = review.setdefault("interactive", {})
    if not isinstance(interactive, dict):
        raise ValueError("review.interactive must be a mapping")
    for key, value in INTERACTIVE_REVIEW_DEFAULTS.items():
        interactive.setdefault(key, value)
    if not isinstance(interactive.get("enabled"), bool):
        raise ValueError("review.interactive.enabled must be a boolean")
    if interactive.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("review.interactive.host must be loopback")
    for key in ("port", "max_body_bytes"):
        value = interactive.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"review.interactive.{key} must be a positive integer")
    audit_bundle = delivery.setdefault("audit_bundle", {})
    if not isinstance(audit_bundle, dict):
        raise ValueError("delivery.audit_bundle must be a mapping")
    for key, value in AUDIT_BUNDLE_DEFAULTS.items():
        audit_bundle.setdefault(key, value)
    if not isinstance(audit_bundle.get("enabled"), bool):
        raise ValueError("delivery.audit_bundle.enabled must be a boolean")
    if not isinstance(audit_bundle.get("output_dir"), str) or not audit_bundle["output_dir"].strip():
        raise ValueError("delivery.audit_bundle.output_dir must be a non-empty string")
    release_pack = delivery.setdefault("release_pack", {})
    if not isinstance(release_pack, dict):
        raise ValueError("delivery.release_pack must be a mapping")
    for key, value in RELEASE_PACK_DEFAULTS.items():
        release_pack.setdefault(key, value)
    for key in (
        "enabled", "require_privacy_audit", "require_rights_authorization",
        "require_publication_authorization",
    ):
        if not isinstance(release_pack.get(key), bool):
            raise ValueError(f"delivery.release_pack.{key} must be a boolean")
    if release_pack.get("enabled") is True:
        required_release_gates = {
            "require_privacy_audit": "privacy audit",
            "require_rights_authorization": "rights authorization",
            "require_publication_authorization": "publication authorization",
        }
        for key, label in required_release_gates.items():
            if release_pack.get(key) is not True:
                raise ValueError(f"enabled release pack requires {label}")
    for key in ("privacy_manifest", "rights_manifest", "publication_authorization"):
        if release_pack.get(key) is not None and not isinstance(release_pack.get(key), str):
            raise ValueError(f"delivery.release_pack.{key} must be a string or null")
    if not isinstance(release_pack.get("output_dir"), str) or not release_pack["output_dir"].strip():
        raise ValueError("delivery.release_pack.output_dir must be a non-empty string")
    derived_content = migrated.setdefault("derived_content", {})
    if not isinstance(derived_content, dict):
        raise ValueError("derived_content must be a mapping")
    for name in ("clip_factory", "podcast", "localization"):
        value = derived_content.setdefault(name, {"enabled": False})
        if not isinstance(value, dict) or not isinstance(value.setdefault("enabled", False), bool):
            raise ValueError(f"derived_content.{name}.enabled must be a boolean")
    migrated["schema_version"] = CURRENT_PROJECT_SCHEMA_VERSION
    migrated["version"] = CURRENT_PROJECT_SCHEMA_VERSION
    return migrated
