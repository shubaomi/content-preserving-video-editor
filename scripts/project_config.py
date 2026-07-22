#!/usr/bin/env python3
"""In-memory project configuration migrations for the video director."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any


CURRENT_PROJECT_SCHEMA_VERSION = 7
MANUAL_FINISH_BACKENDS = {"opencut", "other_nle", "none"}
MANUAL_FINISH_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "backend": "none",
    "returned_final": None,
    "modifications": [],
    "assets": {},
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
    _source_version(project)
    migrated = deepcopy(project)
    delivery = migrated.setdefault("delivery", {})
    if not isinstance(delivery, dict):
        raise ValueError("delivery must be a mapping")
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
    workflow = migrated.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        raise ValueError("workflow must be a mapping")
    capabilities = workflow.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("workflow.capabilities must be a mapping")
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
    extensions = migrated.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("extensions must be a mapping")
    for name in ("b_roll", "multicam", "voice_isolation", "localization"):
        value = extensions.setdefault(name, {"enabled": False})
        if not isinstance(value, dict) or not isinstance(value.setdefault("enabled", False), bool):
            raise ValueError(f"extensions.{name}.enabled must be a boolean")
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
    preferences = migrated.setdefault("preferences", {"enabled": False})
    if not isinstance(preferences, dict) or not isinstance(
        preferences.setdefault("enabled", False), bool
    ):
        raise ValueError("preferences.enabled must be a boolean")
    migrated["schema_version"] = CURRENT_PROJECT_SCHEMA_VERSION
    migrated["version"] = CURRENT_PROJECT_SCHEMA_VERSION
    return migrated
