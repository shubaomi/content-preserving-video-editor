#!/usr/bin/env python3
"""Truthful capability and toolchain inventory for the video director.

The registry describes routing contracts.  It never installs dependencies and
does not imply that a utility is part of the one-shot director until its
``maturity`` is explicitly promoted to ``director_integrated`` or beyond.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


CAPABILITY_LEVELS = (
    "documented",
    "director_integrated",
    "fixture_validated",
    "real_project_validated",
    "production_default",
)


def validate_maturity_transition(
    current: str, requested: str, *, evidence: dict[str, Any],
) -> list[str]:
    """Validate one evidence-backed capability maturity promotion."""
    errors: list[str] = []
    if current not in CAPABILITY_LEVELS or requested not in CAPABILITY_LEVELS:
        return ["capability maturity state is unsupported"]
    current_index = CAPABILITY_LEVELS.index(current)
    requested_index = CAPABILITY_LEVELS.index(requested)
    if requested_index < current_index:
        return ["capability maturity downgrade requires a separate rollback record"]
    if requested_index == current_index:
        return []
    if requested_index != current_index + 1:
        return [f"capability maturity jump from {current} to {requested} is forbidden"]
    if requested == "director_integrated":
        integration = evidence.get("director_integration") or {}
        required = ("route", "state", "invalidation", "failure_contract")
        if not all(integration.get(field) is True for field in required):
            errors.append(
                "director integration requires route, state, invalidation, and failure-contract evidence"
            )
    elif requested == "fixture_validated":
        receipt = evidence.get("fixture_validation") or {}
        source_hash = str(receipt.get("source_tree_sha256") or "")
        test_count = receipt.get("test_count")
        if (
            receipt.get("status") != "pass"
            or isinstance(test_count, bool)
            or not isinstance(test_count, int)
            or test_count < 1
            or receipt.get("failures") != 0
            or receipt.get("skipped") != 0
            or len(source_hash) != 64
            or any(character not in "0123456789abcdef" for character in source_hash.lower())
        ):
            errors.append("fixture maturity requires a zero-failure, zero-skip, hash-bound test receipt")
    elif requested == "real_project_validated":
        validations = evidence.get("real_project_validations") or []
        passing = [
            row for row in validations
            if isinstance(row, dict) and row.get("status") == "pass"
            and row.get("user_review_status") == "approved"
        ]
        roles = {
            row.get("canary_role") for row in passing
        }
        hashes = {
            str(row.get("implementation_sha256") or "") for row in passing
        }
        if len(passing) != 2 or roles != {"landscape_screen", "portrait_talking_head"}:
            errors.append("real-project maturity requires both passing canaries and user review")
        implementation_hash = next(iter(hashes), "")
        if (
            len(hashes) != 1
            or len(implementation_hash) != 64
            or any(character not in "0123456789abcdef" for character in implementation_hash.lower())
        ):
            errors.append("real-project canaries must bind the same implementation hash")
    elif requested == "production_default":
        errors.append(
            "production default promotion is not implemented; a separately trusted "
            "HongRun approval authority must be designed and validated first"
        )
    return errors


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
    _capability("project_initializer", "director", dependencies=["ffprobe"],
                inputs=["source_video", "preset", "optional_profile"],
                outputs=["project.yaml", "initialization-manifest.json", "INITIALIZATION.md"],
                maturity="fixture_validated", failure_fallback="action_required"),
    _capability("doctor_preflight", "director", dependencies=[],
                inputs=["toolchain", "optional_project"],
                outputs=["doctor-report.json", "preflight-report.json"],
                maturity="fixture_validated", failure_fallback="report_unavailable_only"),
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
                optional=False, maturity="fixture_validated", failure_fallback="action_required"),
    _capability("semantic_confidence", "director", dependencies=["semantic_visual_plan"],
                inputs=["word_ids", "screen_evidence", "counterexamples", "asr_confidence"],
                outputs=["semantic-confidence.json"], maturity="fixture_validated",
                failure_fallback="caption_only_or_action_required"),
    _capability("production_contract", "director", dependencies=[],
                inputs=["source_video", "word_transcript", "edl", "semantic_brief"],
                outputs=["production-contract.json"], optional=False,
                maturity="director_integrated", failure_fallback="block_workflow"),
    _capability("provider_governance", "director", dependencies=[],
                inputs=["project_config", "provider_candidates", "user_plan_costs"],
                outputs=["provider-decision.json", "cost-ledger.json"], optional=False,
                maturity="director_integrated", failure_fallback="action_required"),
    _capability("local_semantic_corpus", "director", dependencies=["embedding_backend_optional"],
                inputs=["authorized_local_assets", "semantic_asset_requests"],
                outputs=["semantic-corpus-index.json", "catalog-results.json"],
                maturity="director_integrated", failure_fallback="record_unavailable_and_continue"),
    _capability("brand_motion_playbook", "director", dependencies=["design_tokens"],
                inputs=["design_tokens", "profile", "semantic_brief", "orientation"],
                outputs=["brand-motion-playbook.json", "brand-motion-tokens.css", "DESIGN.md"],
                optional=False, maturity="director_integrated", failure_fallback="action_required"),
    _capability("adaptive_layout", "director", dependencies=["evidence_acquisition"],
                inputs=["display_metadata", "protected_regions", "identity_mode"],
                outputs=["adaptive-layout-constraints.json"], maturity="fixture_validated",
                failure_fallback="caption_only_or_action_required"),
    _capability("stateful_target_binding", "director", dependencies=["adaptive_layout"],
                inputs=["semantic_render_event", "source_state_evidence", "adaptive_layout"],
                outputs=["target-bindings/*.json", "target-binding-geometry-qa.json"],
                maturity="fixture_validated", failure_fallback="do_not_render_or_action_required"),
    _capability("motion_quality_engine", "director",
                dependencies=["semantic_brief", "production_contract", "adaptive_layout"],
                inputs=["decision_complete_opportunities", "evidence_hashes", "target_bindings"],
                outputs=["motion-design-contract.json", "hyperframes-choreography.json"],
                maturity="fixture_validated", failure_fallback="declared_recipe_fallback_or_action_required"),
    _capability("hyperframes_keyframe_evidence", "director",
                dependencies=["motion_quality_engine", "HyperFrames"],
                inputs=["renderer_project_manifest", "motion_design_contract", "renderer_export"],
                outputs=["keyframe-receipts/*.json", "preview-render-parity.json"],
                maturity="fixture_validated", failure_fallback="action_required_and_block_render"),
    _capability("paired_creative_review", "director",
                dependencies=["motion_quality_engine", "hyperframes_keyframe_evidence"],
                inputs=["baseline_media", "candidate_media", "four_phase_receipts",
                        "motion_audio_decisions", "automated_gate_reports"],
                outputs=["creative-review.json", "creative-review.html", "pending-proposals"],
                maturity="fixture_validated", failure_fallback="action_required_and_block_render"),
    _capability("content_format_motion_grammar", "director",
                dependencies=["motion_quality_engine", "adaptive_layout"],
                inputs=["content_type", "semantic_role", "protected_regions"],
                outputs=["motion-design-contract.json", "hyperframes-choreography.json"],
                maturity="fixture_validated", failure_fallback="caption_only_or_action_required"),
    _capability("portrait_brand_motion_v2", "director",
                dependencies=["content_format_motion_grammar", "HyperFrames", "ffmpeg"],
                inputs=["hongrun_profile", "portrait_energy_map", "portrait_motion_contracts",
                        "portrait_sonic_plan", "named_user_approval"],
                outputs=["portrait_hyperframes_project", "portrait_audio_plan",
                         "portrait_style_reel", "portrait_real_project_validation"],
                maturity="real_project_validated",
                failure_fallback="existing_portrait_typography_or_action_required"),
    _capability("perceptual_motion_audio", "director",
                dependencies=["motion_quality_engine", "ffmpeg", "ffprobe"],
                inputs=["motion_design_contract", "authorized_sfx", "delivered_sample_mix"],
                outputs=["motion-audio-decisions/manifest.json", "mix-audibility.json"],
                maturity="fixture_validated", failure_fallback="intentionally_silent_or_action_required"),
    _capability("caption_sync_closure", "director",
                dependencies=["video-use", "ffmpeg", "ffprobe"],
                inputs=["word_transcript", "edl", "master_srt", "final_universal_mp4"],
                outputs=["caption-sync-closure.json"],
                maturity="fixture_validated", failure_fallback="action_required_and_block_delivery"),
    _capability("editorial_promise_closure", "director",
                dependencies=["semantic_visual_plan"],
                inputs=["editorial_intent", "proof_ids", "hook", "title", "cover",
                        "description", "cta", "motion_copy"],
                outputs=["editorial-promise-ledger.json", "editorial-promise-closure.json"],
                maturity="fixture_validated", failure_fallback="action_required_and_block_delivery"),
    _capability("current_golden_runtime_evidence", "director",
                dependencies=["approved_sample", "hyperframes_keyframe_evidence"],
                inputs=["renderer_export", "keyframe_receipts", "cropped_overlay_snapshots"],
                outputs=["golden-baseline.json", "editorial-regression.json"],
                maturity="fixture_validated", failure_fallback="block_render"),
    _capability("advanced_runtime_gate", "director",
                dependencies=["motion_quality_engine", "HyperFrames"],
                inputs=["seek_safe", "deterministic_2d_fallback", "preview_render_parity",
                        "device_support", "license", "cost"],
                outputs=["motion-design-contract.json"],
                maturity="fixture_validated", failure_fallback="deterministic_2d_fallback"),
    _capability("typed_nle_handoff", "human-editor",
                dependencies=["video_use_timeline"],
                inputs=["authoritative_edl", "immutable_automatic_master", "correction_ledger"],
                outputs=["typed-nle-handoff.json", "handoff-manifest.json"],
                maturity="fixture_validated", failure_fallback="action_required"),
    _capability("manual_nle_package_v2", "human-editor",
                dependencies=["video_use_timeline", "manual_finish_handoff"],
                inputs=["automatic_master", "clean_a_roll", "caption_assets",
                        "optional_layer_assets", "authoritative_edl"],
                outputs=["nle-package-v2/10-evidence/nle-handoff-package.json"],
                maturity="documented", failure_fallback="action_required",
                compatibility="editor_neutral_package_v2"),
    _capability("optional_media_adapters", "director",
                dependencies=["provider_governance"],
                inputs=["provider", "rights", "privacy", "provenance", "budget",
                        "human_review_contract"],
                outputs=["optional-media-adapters.json"],
                maturity="fixture_validated", failure_fallback="unavailable_or_action_required"),
    _capability("visual_dynamics_qa", "director", dependencies=["semantic_brief", "storyboard"],
                inputs=["semantic_brief", "storyboard", "production_contract"],
                outputs=["visual-dynamics-qa.json"], optional=False,
                maturity="fixture_validated", failure_fallback="block_render"),
    _capability("editorial_regression", "director", dependencies=["approved_sample"],
                inputs=["golden_baseline", "storyboard", "correction_ledger"],
                outputs=["editorial-regression.json"], maturity="director_integrated",
                failure_fallback="block_render"),
    _capability("review_dashboard", "director", dependencies=[],
                inputs=["director_artifacts"], outputs=["review/index.html"],
                maturity="director_integrated", failure_fallback="record_unavailable_and_continue"),
    _capability("interactive_review", "director", dependencies=["localhost_http"],
                inputs=["hash_bound_artifacts", "explicit_auth_and_csrf"],
                outputs=["pending-proposals", "correction-ledger.json"],
                maturity="fixture_validated", failure_fallback="read_only_dashboard"),
    _capability("clip_factory", "director", dependencies=["video-use", "HyperFrames", "ffmpeg"],
                inputs=["word_transcript", "edl", "semantic_brief", "production_contract"],
                outputs=["clip-factory-manifest.json"], maturity="director_integrated"),
    _capability("podcast_pipeline", "director", dependencies=["ffmpeg_optional"],
                inputs=["clean_audio", "word_transcript", "chapters"],
                outputs=["podcast-manifest.json"], maturity="director_integrated",
                failure_fallback="action_required"),
    _capability("localization_pipeline", "director", dependencies=["translation_provider_optional"],
                inputs=["word_transcript", "glossary", "provider"],
                outputs=["localization-manifest.json"], maturity="director_integrated",
                failure_fallback="action_required"),
    _capability("openmontage_handoff", "human-editor", dependencies=[],
                inputs=["automatic_master", "editable_assets", "production_contract"],
                outputs=["openmontage-handoff-manifest.json"], maturity="director_integrated",
                failure_fallback="action_required"),
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
                inputs=["identity_references", "semantic_cover_direction", "supporting_assets"],
                outputs=["cover-editorial-plan.json", "cover-manifest.json", "cover-qa.json"],
                maturity="director_integrated", failure_fallback="action_required"),
    _capability("cover_reference_pack", "director", dependencies=["authorized_private_photos"],
                inputs=["reference_manifest", "semantic_cover_direction"],
                outputs=["cover-reference-selection.json", "cover-reference-candidate-specs.json"],
                maturity="fixture_validated", failure_fallback="action_required"),
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
    _capability("event_render_cache", "hyperframes", dependencies=["HyperFrames", "filesystem"],
                inputs=["event_render_commands", "equivalence_evidence", "ordered_segment_hashes"],
                outputs=["event-render-cache-report.json", "universal_motion_render"],
                maturity="fixture_validated", failure_fallback="full_hyperframes_render"),
    _capability("manual_finish_handoff", "human-editor", dependencies=[],
                inputs=["automatic_master", "editable_assets"], outputs=["handoff-manifest.json"],
                maturity="director_integrated", failure_fallback="action_required"),
    _capability("motion_preferences", "director", dependencies=["correction-ledger.json"],
                inputs=["approved_corrections"], outputs=["motion-preferences.json"],
                maturity="director_integrated"),
    _capability("preference_learning", "director", dependencies=["correction-ledger.json"],
                inputs=["explicitly_approved_corrections"], outputs=["preference-candidates.json"],
                maturity="fixture_validated", failure_fallback="never_auto_apply"),
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
    _capability("feedback_learning_loop", "director", dependencies=["release_delivery_pack"],
                inputs=["multiple_hash_bound_metric_snapshots"], outputs=["feedback/analysis.json"],
                maturity="fixture_validated", failure_fallback="collect_more_evidence"),
    _capability("portable_audit_bundle", "director", dependencies=[],
                inputs=["configuration", "state", "logs", "non_sensitive_diagnostics"],
                outputs=["portable-audit-bundle/audit-bundle.json"],
                maturity="fixture_validated", failure_fallback="action_required"),
    _capability("release_delivery_pack", "director", dependencies=["privacy_review", "rights_review"],
                inputs=["universal_mp4", "cover", "publishing_copy", "publication_authorization"],
                outputs=["release-pack/release-pack.json"], maturity="fixture_validated",
                failure_fallback="action_required"),
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
    "local_semantic_corpus": ("assets", "local_semantic_corpus"),
    "provider_governance": ("provider_governance",),
    "brand_motion_playbook": ("brand", "motion_playbook"),
    "adaptive_layout": ("motion_quality",),
    "stateful_target_binding": ("motion_quality",),
    "motion_quality_engine": ("motion_quality",),
    "hyperframes_keyframe_evidence": ("motion_quality",),
    "paired_creative_review": ("motion_quality",),
    "content_format_motion_grammar": ("motion_quality",),
    "portrait_brand_motion_v2": ("motion_quality", "portrait_brand"),
    "perceptual_motion_audio": ("audio", "sfx", "perceptual"),
    "caption_sync_closure": ("editing", "caption_sync_closure"),
    "editorial_promise_closure": ("editorial_intent",),
    "current_golden_runtime_evidence": ("editorial_regression",),
    "advanced_runtime_gate": ("motion_quality", "advanced_runtimes"),
    "typed_nle_handoff": ("delivery", "manual_finish"),
    "manual_nle_package_v2": ("delivery", "manual_finish", "nle_package"),
    "optional_media_adapters": ("extensions", "optional_media_adapters"),
    "visual_dynamics_qa": ("qa", "visual_dynamics"),
    "editorial_regression": ("editorial_regression",),
    "review_dashboard": ("review", "dashboard"),
    "interactive_review": ("review", "interactive"),
    "semantic_confidence": ("analysis", "semantic_confidence"),
    "event_render_cache": ("render", "cache", "event_level"),
    "cover_reference_pack": ("cover", "reference_pack"),
    "preference_learning": ("preferences", "learning"),
    "feedback_learning_loop": ("feedback", "learning_loop"),
    "portable_audit_bundle": ("delivery", "audit_bundle"),
    "release_delivery_pack": ("delivery", "release_pack"),
    "clip_factory": ("derived_content", "clip_factory"),
    "podcast_pipeline": ("derived_content", "podcast"),
    "localization_pipeline": ("derived_content", "localization"),
    "openmontage_handoff": ("delivery", "openmontage_handoff"),
}


def capability_config(project: dict[str, Any], name: str) -> dict[str, Any]:
    path = _CANONICAL_CONFIG_PATHS.get(name)
    if path:
        configured: Any = project
        for part in path:
            configured = configured.get(part, {}) if isinstance(configured, dict) else {}
        if name == "optional_media_adapters" and isinstance(configured, list):
            return {"enabled": any(
                isinstance(row, dict) and row.get("enabled") is True
                for row in configured
            )}
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
    repository_root = Path(__file__).parents[1]
    fixture_receipt = repository_root / "references" / "validation" / "test-suite-report.json"
    fixture_evidence: dict[str, Any] | None = None
    if fixture_receipt.is_file():
        try:
            candidate = json.loads(fixture_receipt.read_text(encoding="utf-8"))
            from test_acceptance_report import validate_report
            if not validate_report(candidate, Path(__file__).parents[1], fixture_receipt):
                fixture_evidence = candidate
        except (OSError, ValueError, json.JSONDecodeError):
            fixture_evidence = None
    portrait_receipt = (
        repository_root / "references" / "validation"
        / "portrait-brand-motion-v2-real-project-validation.json"
    )
    portrait_evidence: dict[str, Any] | None = None
    if portrait_receipt.is_file():
        try:
            candidate = json.loads(portrait_receipt.read_text(encoding="utf-8"))
            if (
                isinstance(candidate, dict)
                and candidate.get("schema_version") == 1
                and candidate.get("kind")
                == "hongrun_portrait_brand_retained_real_project_validation"
                and candidate.get("status") == "pass"
                and candidate.get("maturity") == "real_project_validated"
            ):
                from portrait_golden import validate_retained_real_project_portrait_validation
                if not validate_retained_real_project_portrait_validation(
                    candidate, repository_root=repository_root,
                ):
                    portrait_evidence = candidate
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            portrait_evidence = None
    capabilities: list[dict[str, Any]] = []
    for declared in _REGISTRY:
        row = deepcopy(declared)
        row["declared_maturity"] = row["maturity"]
        if row["name"] == "portrait_brand_motion_v2":
            if portrait_evidence is not None and fixture_evidence is not None:
                row["maturity_evidence"] = {
                    "path": str(portrait_receipt.resolve()),
                    "sha256": hashlib.sha256(portrait_receipt.read_bytes()).hexdigest(),
                    "validation_id": portrait_evidence.get("validation_id"),
                    "production_default": False,
                }
            elif fixture_evidence is not None:
                row["maturity"] = "fixture_validated"
                row["maturity_reason"] = "current two-topic named-user receipt is missing or stale"
            else:
                row["maturity"] = "director_integrated"
                row["maturity_reason"] = "current fixture and two-topic receipts are missing or stale"
        elif row["maturity"] == "fixture_validated" and fixture_evidence is None:
            row["maturity"] = "director_integrated"
            row["maturity_reason"] = "current zero-skip fixture receipt is missing or stale"
        elif row["maturity"] == "fixture_validated":
            row["maturity_evidence"] = {
                "path": str(fixture_receipt.resolve()),
                "sha256": hashlib.sha256(fixture_receipt.read_bytes()).hexdigest(),
                "source_tree_sha256": fixture_evidence.get("source_tree_sha256"),
            }
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
            "python": {
                "available": bool(sys.executable and Path(sys.executable).is_file()),
                "path": str(Path(sys.executable).resolve()),
                "constraint": ">=3.11",
                "version": platform.python_version(),
            },
            "ffmpeg": _tool("ffmpeg", ["-version"], ">=5", probe_version=probe_versions),
            "ffprobe": _tool("ffprobe", ["-version"], ">=5", probe_version=probe_versions),
            "hyperframes": {
                **_tool("hyperframes", ["--version"], "adapter_contract_v1", probe_version=probe_versions),
                "invocation_fallback": "npx hyperframes",
            },
            "npx": _tool("npx", ["--version"], ">=8", probe_version=probe_versions),
            "npm": _tool("npm", ["--version"], ">=8", probe_version=probe_versions),
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
