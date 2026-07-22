#!/usr/bin/env python3
"""Truthful capability and toolchain inventory for the video director.

The registry describes routing contracts.  It never installs dependencies and
does not imply that a utility is part of the one-shot director until its
``maturity`` is explicitly promoted to ``director_integrated`` or beyond.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any


CAPABILITY_LEVELS = (
    "documented",
    "utility_implemented",
    "director_integrated",
    "fixture_validated",
    "real_project_validated",
    "production_default",
)


def _implementation_binding() -> dict[str, str]:
    path = Path(__file__).resolve()
    return {
        "registry_implementation": str(path),
        "registry_implementation_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _capability(
    name: str,
    owner: str,
    *,
    dependencies: list[str],
    inputs: list[str],
    outputs: list[str],
    optional: bool = True,
    maturity: str = "documented",
    failure_fallback: str = "record_unavailable_and_continue",
    compatibility: str = "adapter_contract_v1",
) -> dict[str, Any]:
    if maturity not in CAPABILITY_LEVELS:
        raise ValueError(f"invalid capability maturity: {maturity}")
    return {
        "name": name,
        "owner": owner,
        "dependencies": dependencies,
        "compatibility": compatibility,
        "capability_version": "1.0.0",
        "inputs": inputs,
        "outputs": outputs,
        "optional": optional,
        "cache_key_fields": ["source_sha256", "project_schema_version", "capability_version", *inputs],
        "failure_fallback": failure_fallback,
        "maturity": maturity,
    }


_REGISTRY = (
    _capability("input_mode_analysis", "director", dependencies=["ffprobe"],
                inputs=["source_video"], outputs=["input-mode-evidence.json"], optional=False,
                maturity="director_integrated", failure_fallback="select_preserve"),
    _capability("video_use_timeline", "video-use", dependencies=["video-use", "ffmpeg", "ffprobe"],
                inputs=["source_video", "editing_policy"], outputs=["edl.json", "captions.json"],
                optional=False, maturity="director_integrated", failure_fallback="action_required"),
    _capability("existing_edit_polish", "director", dependencies=["ffmpeg", "ffprobe"],
                inputs=["source_video", "word_transcript"], outputs=["enhancement-plan.json"],
                maturity="director_integrated"),
    _capability("existing_edit_polish_plan", "director", dependencies=["word_transcript"],
                inputs=["existing_edit_analysis", "word_transcript"], outputs=["enhancement-plan.json"],
                maturity="director_integrated"),
    _capability("evidence_acquisition", "director", dependencies=["ffmpeg", "ffprobe"],
                inputs=["source_video", "word_transcript"], outputs=["evidence-bundle.json"],
                optional=False, maturity="director_integrated", failure_fallback="action_required"),
    _capability("scene_detection", "director", dependencies=["PySceneDetect"],
                inputs=["source_video"], outputs=["scene-boundaries.json"], maturity="director_integrated"),
    _capability("ocr", "director", dependencies=["PaddleOCR"],
                inputs=["representative_frames"], outputs=["ocr-evidence.json"], maturity="director_integrated"),
    _capability("design_tokens", "director", dependencies=["ffmpeg", "Pillow"],
                inputs=["representative_frames", "hyperframes_project"], outputs=["design-tokens.json"],
                optional=False, maturity="director_integrated", failure_fallback="action_required"),
    _capability("subject_tracking", "director", dependencies=["OpenCV"],
                inputs=["source_video", "orientation"], outputs=["subject-track.json"],
                maturity="director_integrated"),
    _capability("mediapipe_tracking", "director", dependencies=["MediaPipe"],
                inputs=["source_video", "word_transcript"], outputs=["mediapipe-evidence.json"],
                maturity="director_integrated"),
    _capability("semantic_visual_plan", "director_with_llm", dependencies=["word_transcript", "evidence_bundle"],
                inputs=["word_transcript", "evidence_bundle"], outputs=["semantic-brief.json"],
                optional=False, maturity="director_integrated", failure_fallback="action_required"),
    _capability("hyperframes_router", "hyperframes", dependencies=["HyperFrames"],
                inputs=["visual_beat_plan", "content_type"], outputs=["renderer-route.json"],
                maturity="director_integrated", failure_fallback="action_required"),
    _capability("motion_snapshot_plan", "hyperframes", dependencies=["HyperFrames"],
                inputs=["storyboard", "composition"], outputs=["motion-snapshot-qa.json"],
                maturity="director_integrated", failure_fallback="block_render"),
    _capability("preview_render_parity", "hyperframes", dependencies=["HyperFrames"],
                inputs=["studio_snapshots", "render_snapshots"], outputs=["preview-render-parity.json"],
                optional=False, maturity="director_integrated", failure_fallback="block_render"),
    _capability("ip_components", "director", dependencies=["Pillow", "image_generator_optional"],
                inputs=["semantic_chapter", "identity_references", "design_tokens"],
                outputs=["asset-components.json"], maturity="director_integrated",
                failure_fallback="omit_with_evidence"),
    _capability("cover_generation", "director", dependencies=["image_generator_optional", "Pillow"],
                inputs=["identity_references", "topic_evidence"], outputs=["cover-manifest.json"],
                maturity="director_integrated", failure_fallback="action_required"),
    _capability("bgm_pipeline", "director", dependencies=["media-use_optional", "MiniMax_optional", "MusicGen_optional"],
                inputs=["semantic_chapters", "authorized_audio_assets"], outputs=["bgm-stem.wav", "bgm-provenance.json"],
                maturity="director_integrated"),
    _capability("sfx_pipeline", "director", dependencies=["authorized_sfx_assets", "ffmpeg"],
                inputs=["visual_beat_plan"], outputs=["sfx-stems", "audio-plan.json"],
                maturity="director_integrated"),
    _capability("audio_normalization", "ffmpeg", dependencies=["ffmpeg", "ffprobe"],
                inputs=["composed_audio"], outputs=["audio-qa.json"], maturity="director_integrated"),
    _capability("platform_occlusion", "director", dependencies=["representative_frames"],
                inputs=["element_boxes", "platform_template"], outputs=["platform-occlusion.json"],
                maturity="director_integrated"),
    _capability("platform_export_validation", "director", dependencies=["ffmpeg", "ffprobe"],
                inputs=["universal_mp4", "cover"], outputs=["platform-validation.json"],
                optional=False, maturity="director_integrated", failure_fallback="block_delivery"),
    _capability("render_cache", "director", dependencies=["filesystem"],
                inputs=["render_inputs", "dependency_signature"], outputs=["render-cache-status.json"],
                maturity="director_integrated", failure_fallback="clean_rebuild"),
    _capability("manual_finish_handoff", "human-editor", dependencies=[],
                inputs=["automatic_master", "editable_assets"], outputs=["handoff-manifest.json"],
                maturity="director_integrated", failure_fallback="action_required"),
    _capability("motion_preferences", "director", dependencies=["correction-ledger.json"],
                inputs=["approved_corrections"], outputs=["motion-preferences.json"],
                maturity="director_integrated"),
    _capability("hook_pacing", "director", dependencies=["word_transcript", "representative_frames"],
                inputs=["word_transcript", "chapters"], outputs=["hook-pacing-audit.json"],
                maturity="director_integrated"),
    _capability("publishing_copy", "director", dependencies=["verified_glossary"],
                inputs=["semantic_brief", "verified_glossary"], outputs=["publish-metadata.json"],
                maturity="director_integrated"),
    _capability("asr_router", "video-use", dependencies=["faster-whisper", "FunASR_optional", "WhisperX_optional"],
                inputs=["source_audio", "hotwords", "speaker_task"], outputs=["word-transcript.json"],
                maturity="director_integrated", failure_fallback="action_required"),
    _capability("otio_timeline", "video-use", dependencies=["OpenTimelineIO"],
                inputs=["edl.json"], outputs=["timeline.otio"], maturity="director_integrated"),
    _capability("b_roll", "director", dependencies=["media-use_optional"],
                inputs=["visual_beat_plan", "candidate_assets"], outputs=["b-roll-plan.json"], maturity="director_integrated"),
    _capability("multicam", "video-use", dependencies=["ffmpeg"],
                inputs=["camera_sources", "audio_tracks"], outputs=["multicam-edl.json"], maturity="director_integrated"),
    _capability("voice_isolation", "director", dependencies=["isolation_backend_optional"],
                inputs=["source_audio", "noise_evidence"], outputs=["isolated-speech.wav"], maturity="director_integrated"),
    _capability("localization", "director", dependencies=["translation_backend_optional", "tts_backend_optional"],
                inputs=["word_transcript", "glossary"], outputs=["localized-timeline.json"], maturity="director_integrated"),
    _capability("remotion_renderer", "remotion", dependencies=["Remotion_optional"],
                inputs=["visual_beat_plan", "react_brand_components"], outputs=["motion-render.mov"], maturity="director_integrated"),
    _capability("post_publish_metrics", "director", dependencies=[],
                inputs=["user_imported_metrics"], outputs=["post-publish-metrics.json"], maturity="director_integrated"),
    _capability("media_catalog", "media-use", dependencies=["media-use_optional", "HyperFrames_Catalog_optional"],
                inputs=["evidence_backed_asset_requests"], outputs=["catalog-results.json"],
                maturity="director_integrated"),
)


_CANONICAL_CONFIG_PATHS = {
    "scene_detection": ("analysis", "adapters", "pyscenedetect"),
    "mediapipe_tracking": ("analysis", "adapters", "mediapipe"),
    "ocr": ("analysis", "adapters", "paddleocr"),
    "asr_router": ("transcription", "router"),
    "otio_timeline": ("timeline", "otio"),
    "render_cache": ("render", "cache"),
    "b_roll": ("extensions", "b_roll"),
    "multicam": ("extensions", "multicam"),
    "voice_isolation": ("extensions", "voice_isolation"),
    "localization": ("extensions", "localization"),
    "remotion_renderer": ("renderer", "remotion"),
    "post_publish_metrics": ("feedback", "metrics_import"),
    "ip_components": ("visuals", "ip_production"),
    "cover_generation": ("cover", "production"),
    "bgm_pipeline": ("audio", "production"),
    "sfx_pipeline": ("audio", "production"),
    "audio_normalization": ("audio", "normalization"),
    "motion_preferences": ("preferences",),
    "subject_tracking": ("analysis", "subject_tracking"),
    "hook_pacing": ("analysis", "hook_pacing"),
    "publishing_copy": ("publishing", "copy"),
    "media_catalog": ("assets", "media_catalog"),
}


def capability_config(project: dict[str, Any], name: str) -> dict[str, Any]:
    path = _CANONICAL_CONFIG_PATHS.get(name)
    if path:
        configured: Any = project
        for part in path:
            configured = configured.get(part, {}) if isinstance(configured, dict) else {}
        if isinstance(configured, bool):
            return {"enabled": configured}
        if isinstance(configured, dict):
            if name == "media_catalog" and project.get("assets", {}).get("use_media_catalog") is True:
                return {**configured, "enabled": True}
            return configured
    if name == "media_catalog" and project.get("assets", {}).get("use_media_catalog") is True:
        return {"enabled": True}
    configured = project.get("workflow", {}).get("capabilities", {}).get(name, {})
    if isinstance(configured, bool):
        return {"enabled": configured}
    return configured if isinstance(configured, dict) else {}


def build_capability_inventory(project: dict[str, Any]) -> dict[str, Any]:
    capabilities: list[dict[str, Any]] = []
    for declared in _REGISTRY:
        row = deepcopy(declared)
        config = capability_config(project, row["name"])
        route = _CANONICAL_CONFIG_PATHS.get(
            row["name"], ("workflow", "capabilities", row["name"]),
        )
        row["configuration_route"] = ".".join(route)
        if row["optional"]:
            enabled = config.get("enabled") is True
            reason = "explicit_project_enable" if enabled else "optional_default_off"
        else:
            enabled = config.get("enabled", True) is not False
            reason = "required_core" if enabled else "invalid_required_disable"
        row["enabled"] = enabled
        row["route_reason"] = reason
        capabilities.append(row)
    return {
        "schema_version": 1,
        **_implementation_binding(),
        "status_vocabulary": list(CAPABILITY_LEVELS),
        "capabilities": capabilities,
        "claims_policy": "Only director_integrated or higher may be described as part of the one-shot workflow.",
    }


def _command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0][:240] if output else None


def _tool(name: str, argv: list[str], supported_range: str, *, probe_version: bool) -> dict[str, Any]:
    executable = shutil.which(name)
    return {
        "available": executable is not None,
        "path": executable,
        "detected_version": _command_version([executable, *argv]) if executable and probe_version else None,
        "supported_range": supported_range,
    }


def build_toolchain_report(*, probe_versions: bool = False) -> dict[str, Any]:
    video_use_root = Path(os.environ.get("VIDEO_USE_SKILL_ROOT", Path.home() / ".codex" / "skills" / "video-use"))
    hyperframes_roots = [
        Path.home() / ".agents" / "skills" / "hyperframes",
        Path.home() / ".codex" / "skills" / "hyperframes",
    ]
    required_hyperframes = (
        "hyperframes", "hyperframes-core", "hyperframes-creative",
        "hyperframes-animation", "hyperframes-cli",
    )
    plugin_skill_root = (
        Path.home() / ".codex" / "plugins" / "cache" / "openai-curated-remote"
        / "hyperframes" / "0.1.2" / "skills"
    )
    required_skill_records: dict[str, dict[str, Any]] = {}
    for skill_name in required_hyperframes:
        candidates = [
            Path.home() / ".agents" / "skills" / skill_name,
            Path.home() / ".codex" / "skills" / skill_name,
            plugin_skill_root / skill_name,
        ]
        selected = next((path for path in candidates if (path / "SKILL.md").is_file()), candidates[0])
        skill_file = selected / "SKILL.md"
        required_skill_records[skill_name] = {
            "path": str(selected.resolve()),
            "available": skill_file.is_file(),
            "skill_md_sha256": (
                hashlib.sha256(skill_file.read_bytes()).hexdigest() if skill_file.is_file() else None
            ),
            "candidates": [str(path.resolve()) for path in candidates],
        }
    return {
        "schema_version": 1,
        **_implementation_binding(),
        "mutates_toolchain": False,
        "update_policy": "never_silent",
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "tools": {
            "ffmpeg": _tool("ffmpeg", ["-version"], ">=5", probe_version=probe_versions),
            "ffprobe": _tool("ffprobe", ["-version"], ">=5", probe_version=probe_versions),
            "hyperframes": {
                **_tool("hyperframes", ["--version"], "adapter_contract_v1", probe_version=probe_versions),
                "invocation_fallback": "npx hyperframes",
            },
            "npx": _tool("npx", ["--version"], ">=8", probe_version=probe_versions),
            "node": _tool("node", ["--version"], ">=18", probe_version=probe_versions),
        },
        "skill_roots": {
            "video-use": {"path": str(video_use_root.resolve()), "available": (video_use_root / "SKILL.md").is_file()},
            "hyperframes": [
                {"path": str(path.resolve()), "available": (path / "SKILL.md").is_file()}
                for path in hyperframes_roots
            ],
        },
        "required_hyperframes_skills": required_skill_records,
    }
