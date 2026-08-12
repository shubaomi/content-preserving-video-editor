#!/usr/bin/env python3
"""Single resumable entry point for the preservation-first professional workflow.

This program is deliberately an orchestrator. It delegates editing semantics to
video-use, motion design/rendering to HyperFrames, and final media mechanics to
FFmpeg. Agent-authored semantic and aesthetic decisions are represented as
versioned artifacts rather than hidden in per-project scripts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aesthetic_qa import validate as validate_aesthetic_review
from asr_router import (
    build_asr_quality_report,
    choose_backend as choose_asr_backend,
    normalize_transcript,
    validate_pipeline_reports,
)
from audio_qa import validate as validate_audio_plan
from audio_production import (
    audition_filename_stem,
    materialize_motion_audio_decisions,
    materialize_sample_audio_evidence,
    materialize_sample_review_mix,
    produce_audio_assets,
    validate_sample_audio_evidence,
    validate_sample_review_mix_receipt,
)
from brand_motion_playbook import compile_playbook, validate_playbook
from build_motion_snapshot_plan import build_motion_sidecar, build_plan as build_motion_snapshot_plan
from capability_registry import build_capability_inventory, build_toolchain_report, capability_config
from clip_factory import build_clip_manifest, validate_clip_manifest
from correction_ledger import append_correction, new_ledger, validate_ledger
from creative_review import (
    build_contract as build_creative_review_contract,
    mark_stale as mark_creative_review_stale,
    record_user_decision as record_creative_user_decision,
    validate_sample_pair_durations,
    validate_review as validate_creative_review,
)
from cover_production import CoverProductionActionRequired, produce_cover, write_cover_request
from cover_reference_pack import (
    build_candidate_specs,
    privacy_projection as cover_reference_privacy_projection,
    select_references as select_cover_references,
    validate_reference_pack,
)
from conditional_extensions import route_extensions, run_extension_adapters
from director_adapters import AdapterExecutionError, AdapterRunner
from director_contracts import (
    STAGES,
    DirectorContractError,
    ProjectContext,
    assert_valid,
    is_decision_complete_brief,
    load_project_context,
    read_json,
    sha256_file,
    selected_semantic_event_ids,
    validate_semantic_brief,
    validate_semantic_evidence_binding,
    validate_storyboard,
    validate_video_use_edl,
    validate_video_use_edit_preflight,
    validate_video_use_final_correctness,
    validate_video_use_media_analysis,
    validate_visual_vocabulary_audit,
    write_json,
    exclusive_file_lock,
)
from evidence_acquisition import acquire as acquire_evidence
from editorial_regression import (
    create_baseline, evaluate_regression, validate_baseline, validate_regression,
)
from editorial_promise import (
    build_promise_closure, build_promise_ledger, validate_promise_bindings,
)
from hyperframes_router import route_hyperframes
from ip_production import IpProductionActionRequired, produce_ip_components
from keyframe_receipt import validate_keyframe_receipt, validate_renderer_export
from manual_finish import (
    build_handoff_manifest,
    validate_returned_final_qa,
)
from media_catalog_adapter import run_media_catalog
from motion_contracts import (
    DEFAULT_RECIPE_REGISTRY,
    load_recipe_registry,
    validate_motion_design_contract,
    validate_storyboard_motion_binding,
)
from motion_quality_engine import build_hyperframes_choreography, compile_motion_design
from motion_preferences import apply as apply_motion_preferences, load as load_motion_preferences
from normalize_social_audio import (
    normalize as normalize_social_audio,
    validate_report as validate_audio_normalization_report,
)
from localization_pipeline import build_localization_manifest, validate_localization_manifest
from otio_adapter import (
    build_handoff_package as build_typed_nle_handoff,
    edl_to_otio, otio_to_internal, validate_roundtrip as validate_otio_roundtrip,
)
from optional_media_adapter import authorize_optional_adapter
from post_publish_metrics import import_metrics as import_post_publish_metrics
from feedback_loop import analyze_feedback_snapshots
from podcast_pipeline import build_podcast_manifest, validate_podcast_manifest
from platform_occlusion_gate import evaluate_geometry as evaluate_platform_occlusion
from preview_render_parity import validate as validate_preview_render_parity
from production_contract import build_contract, validate_contract
from provider_governance import (
    build_decision_report,
    create_cost_ledger,
    reconcile_selected_call,
    reserve_selected_call,
    validate_cost_ledger,
    validate_decision_report,
    write_provider_result_receipt,
)
from render_with_cache import run_pipeline as run_cached_pipeline
from renderer_project_manifest import build_manifest as build_renderer_project_manifest
from event_render_pipeline import EventRenderUnavailable, execute_event_render_pipeline
from state_migrations import CURRENT_STATE_SCHEMA_VERSION, load_and_migrate_state
from project_initializer import PRESETS as PROJECT_PRESETS, initialize_project
from doctor import run_doctor
from preflight import run_preflight
from action_required_contract import create_action_packet, validate_action_packet
from semantic_confidence import build_candidate_report, validate_candidate_report
from review_dashboard import generate_dashboard
from review_server import ReviewServerConfig, create_review_server
from sample_caption_delivery import (
    materialize_pair as materialize_sample_caption_pair,
    validate_receipt as validate_sample_caption_receipt,
)
from preference_learning import build_preference_candidates, write_preference_candidates
from technical_qa import run_technical_qa, validate_report as validate_technical_report
from portable_audit_bundle import create_portable_audit_bundle
from verify_audit_bundle import verify_audit_bundle
from prepublish_privacy_audit import create_privacy_audit
from rights_authorization_manifest import create_rights_authorization_report
from release_delivery_pack import create_release_delivery_pack, verify_release_delivery_pack
from validate_platform_export import validate_bound_report as validate_platform_report
from video_use_bridge import render_command, render_helper_path, synchronization_report
from visual_dynamics_qa import (
    build_report as build_visual_dynamics_report,
    validate_report as validate_visual_dynamics_report,
)
from delivery_readiness import asset_is_required, validate_required_asset_readiness
from select_motion_safe_zones import (
    build_adaptive_layout_constraints,
    subject_track_face_regions,
)
from target_binding import validate_binding, validate_storyboard_bindings


STATE_VERSION = CURRENT_STATE_SCHEMA_VERSION
DIRECTOR_VERSION = "2.6.0"

ROLE_CONTRACT = {
    "director": [
        "content preservation policy", "workflow orchestration", "personal IP/profile",
        "cover and publishing assets", "platform adaptation", "blocking QA", "single universal delivery",
    ],
    "video-use": [
        "media analysis", "word transcription", "EDL and edit timeline", "cut and audio boundaries",
        "output-timeline subtitle mapping", "edit correctness verification",
    ],
    "hyperframes": [
        "creative direction", "visual design system", "motion storyboard", "distinct DOM structures",
        "animation implementation", "Studio editing", "motion rendering",
    ],
    "ffmpeg": [
        "final composition", "audio mix", "encoding", "decode verification",
        "simple visually equivalent primitives only",
    ],
    "human-editor": [
        "optional visual trimming and multitrack finishing through a human-facing NLE handoff",
        "no implied OpenCut CLI, MCP, Editor API, or headless automation",
    ],
}

FORBIDDEN_NEW_PATHS = (
    "scripts/attention_planner.py",
    "scripts/materialize_dynamic_artifacts.py",
    "scripts/build_dynamic_hyperframes.py",
    "PIL static text cards as motion",
    "FFmpeg slide/translate pretending to be HyperFrames",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _semantic_inheritance_contract(
    brief: dict[str, Any], *, motion_quality_enabled: bool,
) -> dict[str, Any]:
    bind = [
        "treatment", "anchor", "transcript_word_ids", "source_start", "source_end",
        "output_start", "output_end", "viewer_takeaway", "approved_visible_copy",
    ]
    if motion_quality_enabled:
        bind.extend(("target_frame_evidence", "relevance_rationale", "visual_mechanism"))
    contract: dict[str, Any] = {
        "explicit_semantic_event_id_required": True,
        "bind": bind,
        "derived_visible_copy_manifest": (
            "exact normalized list from approved_visible_copy; empty when none"
        ),
        "other_render_text_fields_forbidden": True,
        "storyboard_semantic_fallback_forbidden": True,
    }
    if motion_quality_enabled:
        contract.update({
            "selection": "ordered render-decision subset only",
            "selected_semantic_event_ids": selected_semantic_event_ids(brief),
            "nonrender_opportunities_must_not_be_serialized": True,
            "event_or_family_quota": None,
            "fixed_cadence": None,
        })
    return contract


def _target_binding_request_contract(
    *, layout_path: Path, binding_dir: Path, schema_path: Path,
    identity_mode: str,
) -> dict[str, Any]:
    """Describe the fail-closed geometry artifacts expected from motion planning."""
    layout_path = layout_path.resolve()
    schema_path = schema_path.resolve()
    if not layout_path.is_file():
        raise DirectorContractError("adaptive layout evidence is missing")
    if not schema_path.is_file():
        raise DirectorContractError("target-binding schema is missing")
    return {
        "mode": "stateful_target_binding_v1",
        "schema": str(schema_path),
        "schema_sha256": sha256_file(schema_path),
        "binding_directory": str(binding_dir.resolve()),
        "adaptive_layout": str(layout_path),
        "adaptive_layout_sha256": sha256_file(layout_path),
        "event_declaration": {
            "target_binding_required": "explicit boolean",
            "target_binding_ids": "exact ordered binding IDs; empty only for targetless recipes",
        },
        "tracking_modes": ["static", "scene_bounded", "keyframed"],
        "material_state_changes": [
            "scene", "route", "modal", "scroll", "zoom", "layout",
            "visibility", "rotation",
        ],
        "unresolved_source_bound_event": "do_not_render",
        "allowed_safe_results": ["fallback", "action_required"],
        "guessed_coordinates_allowed": False,
        "identity_mode": identity_mode,
        "personal_assets": "forbidden" if identity_mode == "third_party" else "authorized_only",
    }


def prepare_cover_reference_pack(
    project: dict[str, Any], *, project_root: Path,
    semantic_brief: Path, work_dir: Path,
) -> tuple[dict[str, Any], list[Path]]:
    """Resolve an authorized private cover pack into production inputs and safe evidence."""
    config = project.get("cover", {}).get("reference_pack", {})
    if config.get("enabled") is not True:
        return project, []
    raw_manifest = config.get("manifest")
    if not str(raw_manifest or "").strip():
        raise ValueError("cover.reference_pack.manifest is required when enabled")
    manifest = Path(str(raw_manifest))
    if not manifest.is_absolute():
        manifest = (project_root / manifest).resolve()
    if not manifest.is_file():
        raise ValueError("cover reference pack manifest is missing")
    pack = validate_reference_pack(read_json(manifest))
    required = {str(value) for value in config.get("required_roles") or []}
    missing = sorted(required - set(pack.get("covered_roles") or []))
    if missing:
        raise ValueError("cover reference pack is missing configured roles: " + ", ".join(missing))
    brief = read_json(semantic_brief)
    topic = str(
        config.get("topic")
        or brief.get("summary")
        or project.get("content", {}).get("title")
        or project.get("video_id")
        or ""
    ).strip()
    if not topic:
        raise ValueError("cover reference selection requires a grounded topic")
    direction = str(config.get("direction") or "credible energetic topic tutorial").strip()
    target_expression = str(config.get("target_expression") or "smiling").strip().lower()
    selection = select_cover_references(
        pack, topic=topic, direction=direction, target_expression=target_expression,
        minimum_identity_references=int(config.get("minimum_identity_references", 2)),
        maximum_references=int(config.get("maximum_references", 4)),
        expected_subject_id=(
            str(config.get("expected_subject_id")).strip()
            if config.get("expected_subject_id") else None
        ),
    )
    specs = build_candidate_specs(selection, topic=topic, direction=direction)
    work_dir.mkdir(parents=True, exist_ok=True)
    private_selection = work_dir / "cover-reference-selection.json"
    public_projection = work_dir / "cover-reference-pack-public.json"
    candidate_specs = work_dir / "cover-reference-candidate-specs.json"
    write_json(private_selection, {
        **selection,
        "manifest_sha256": sha256_file(manifest),
        "privacy": "private local production artifact; do not publish or commit",
    })
    write_json(public_projection, {
        **cover_reference_privacy_projection(pack),
        "manifest_sha256": sha256_file(manifest),
    })
    write_json(candidate_specs, {
        "schema_version": 1, "topic": topic, "direction": direction,
        "candidates": specs, "identity_user_approval": "pending",
    })
    prepared = json.loads(json.dumps(project))
    cover = prepared.setdefault("cover", {})
    references = [str(row["path"]) for row in selection["selected_references"]]
    expression = [
        str(row["path"]) for row in selection["selected_references"]
        if str(row.get("expression") or "").lower() == target_expression
    ]
    cover["identity_references"] = references
    cover["expression_references"] = expression or references
    cover["target_expression"] = target_expression
    variants = cover.setdefault("variants", {})
    for spec in specs:
        row = variants.setdefault(spec["candidate_id"], {})
        row.setdefault("template_family", spec["structure"]["template_family"])
        row.setdefault("text_side", spec["structure"]["negative_space"])
        row.setdefault("strategy", spec["communication_strategy"])
    cover["reference_pack"]["resolved_selection"] = str(private_selection)
    cover["reference_pack"]["candidate_specs"] = str(candidate_specs)
    return prepared, [manifest, private_selection, public_projection, candidate_specs]


def _review_evidence_files(review: dict[str, Any]) -> list[Path]:
    values: list[Any] = []
    for phases in (review.get("snapshots") or {}).values():
        if isinstance(phases, dict):
            values.extend(phases.values())
    for row in (review.get("criteria") or {}).values():
        if isinstance(row, dict):
            values.extend(row.get("evidence") or [])
    for row in [
        *(review.get("connector_geometry") or {}).values(),
        *(review.get("target_region_geometry") or {}).values(),
    ]:
        if isinstance(row, dict):
            values.append(row.get("evidence"))
    for row in (review.get("composite_contrast") or {}).values():
        if isinstance(row, dict):
            values.extend((row.get("composite_evidence"), row.get("source_evidence")))
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if not value:
            continue
        record = value if isinstance(value, dict) else {"path": value}
        path_value = record.get("path")
        if not path_value:
            continue
        path = Path(str(path_value)).resolve()
        declared_hash = record.get("sha256")
        if isinstance(value, dict):
            if not re.fullmatch(r"[0-9a-f]{64}", str(declared_hash or "")):
                raise DirectorContractError(
                    f"structured review evidence requires sha256: {path}"
                )
            if path.is_file() and declared_hash != sha256_file(path):
                raise DirectorContractError(f"review evidence hash does not match: {path}")
        if path.is_file() and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _load_protected_region_review(
    manifest_path: Path, *, project_root: Path, source_sha256: str,
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    """Load a hash-bound observation without inventing missing geometry."""
    if not manifest_path.is_file():
        raise DirectorContractError(
            f"protected-region review manifest is missing: {manifest_path}"
        )
    review = read_json(manifest_path)
    if review.get("schema_version") != 1:
        raise DirectorContractError("protected-region review schema_version must be 1")
    if review.get("source_sha256") != source_sha256:
        raise DirectorContractError("protected-region review source hash does not match")
    reviewer = review.get("reviewer")
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise DirectorContractError("protected-region review requires a reviewer")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        raise DirectorContractError("protected-region review requires reviewed_at")
    raw_observations = review.get("observations")
    if not isinstance(raw_observations, dict) or not raw_observations:
        raise DirectorContractError("protected-region review requires observations")
    observations: dict[str, dict[str, Any]] = {}
    artifacts = [manifest_path.resolve()]
    for region_type, raw in raw_observations.items():
        if region_type not in {"faces", "hands"} or not isinstance(raw, dict):
            raise DirectorContractError(
                f"protected-region review has unsupported observation: {region_type}"
            )
        if raw.get("status") != "observed_absent":
            raise DirectorContractError(
                f"protected-region review {region_type} must use observed_absent"
            )
        evidence = raw.get("evidence")
        if not isinstance(evidence, list) or len(evidence) < 2:
            raise DirectorContractError(
                f"protected-region review {region_type} requires at least two evidence frames"
            )
        normalized_evidence: list[dict[str, str]] = []
        for item in evidence:
            if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
                raise DirectorContractError(
                    f"protected-region review {region_type} evidence is incomplete"
                )
            path = Path(str(item["path"]))
            path = path.resolve() if path.is_absolute() else (project_root / path).resolve()
            try:
                path.relative_to(project_root.resolve())
            except ValueError as error:
                raise DirectorContractError(
                    "protected-region review evidence must stay inside the project"
                ) from error
            declared_hash = str(item["sha256"]).lower()
            if not path.is_file() or sha256_file(path) != declared_hash:
                raise DirectorContractError(
                    f"protected-region review evidence hash mismatch: {path}"
                )
            normalized_evidence.append({"path": str(path), "sha256": declared_hash})
            artifacts.append(path)
        observations[region_type] = {
            "status": "observed_absent",
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "evidence": normalized_evidence,
            "evidence_sha256": [item["sha256"] for item in normalized_evidence],
        }
    return observations, artifacts


def _cover_delivery_gate(review: dict[str, Any]) -> tuple[list[str], bool]:
    """Apply identity checks only when the selected cover depicts a person."""
    identity_required = review.get("identity_applicable") is not False
    errors: list[str] = []
    if identity_required and int(review.get("identity_reference_count", 0)) < 2:
        errors.append("identity-reference gate failed")
    if review.get("topic_relevant") is not True:
        errors.append("topic-relevance gate failed")
    if review.get("natural_expression_and_energy") is not True:
        errors.append("expression-or-energy gate failed")
    return errors, identity_required


def _audio_plan_asset_files(plan: dict[str, Any], base_dir: Path) -> list[Path]:
    """Return materialized cue/BGM assets so Director state binds their bytes."""
    cue_values = [
        row.get("asset") for row in (
            (plan.get("motion_sfx") or {}).get("event_decisions") or []
        ) if isinstance(row, dict) and row.get("decision") == "cue"
    ]
    values: list[tuple[Any, Path | None]] = [
        (value, (base_dir / "assets" / "sfx").resolve()) for value in cue_values
    ]
    background = plan.get("background_music") or {}
    if background.get("mode") == "authorized_asset":
        values.append((background.get("source"), None))
    result: list[Path] = []
    seen: set[Path] = set()
    for value, allowed_root in values:
        if not value:
            continue
        path = Path(str(value))
        path = path.resolve() if path.is_absolute() else (base_dir / path).resolve()
        if allowed_root is not None and not path.is_relative_to(allowed_root):
            continue
        if path.is_file() and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _ffprobe_duration(path: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def _stage_template() -> dict[str, Any]:
    return {"status": "pending", "attempts": 0, "updated_at": None, "artifacts": [],
            "artifact_records": [], "error": None, "readiness": "pending"}


def _existing_stage_readiness(
    stage: str, row: dict[str, Any], project: dict[str, Any],
) -> str:
    status = str(row.get("status") or "pending")
    if status != "complete":
        return status
    artifact_paths = [Path(str(value)) for value in (row.get("artifacts") or [])]
    if stage == "audio":
        plan = next((path for path in artifact_paths if path.name.lower() == "audio-plan.json"), None)
        storyboard = plan.parent / "storyboard.json" if plan else None
        if plan and plan.is_file() and storyboard and storyboard.is_file():
            try:
                if not validate_audio_plan(
                    read_json(plan), read_json(storyboard), project, base_dir=plan.parent,
                ):
                    return "asset_ready"
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return "contract_ready"
    if stage == "cover":
        if project.get("cover", {}).get("enabled", True) is False:
            return "not_applicable"
        if any(path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
               for path in artifact_paths):
            return "asset_ready"
        return "contract_ready"
    return "ready"


def _file_fingerprint(path: Path, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        return {"path": str(resolved), "available": False, "size": None,
                "mtime_ns": None, "sha256": None}
    stat = resolved.stat()
    # Always re-hash: size and mtime can be preserved while bytes change, and
    # resume correctness is more important than avoiding one sequential read.
    digest = sha256_file(resolved)
    return {"path": str(resolved), "available": True, "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": digest}


def _artifact_records(paths: list[Path]) -> list[dict[str, Any]]:
    return [_file_fingerprint(path) for path in paths]


def _artifact_records_current(records: list[dict[str, Any]]) -> bool:
    return bool(records) and all(
        _file_fingerprint(Path(str(row.get("path", "")))) == row
        for row in records
    )


def _reconcile_state(state: dict[str, Any]) -> None:
    """Derive top-level status from all stages without hiding downstream blockers."""
    stages = state.get("stages") or {}
    for blocking_status in ("failed", "action_required"):
        for name in STAGES:
            if stages.get(name, {}).get("status") == blocking_status:
                state["status"] = blocking_status
                state["current_stage"] = name
                return
    if stages and all(stages.get(name, {}).get("status") == "complete" for name in STAGES):
        state["status"] = "complete"
        state["current_stage"] = None
        return
    state["status"] = "active"
    state["current_stage"] = next(
        (name for name in STAGES if stages.get(name, {}).get("status") == "running"),
        None,
    )


class Director:
    def __init__(self, project_file: Path, *, approve_final_render: bool = False,
                 execute_external: bool = False) -> None:
        self.project, self.context = load_project_context(project_file)
        self.approve_final_render = approve_final_render
        self.execute_external = execute_external
        self.root = self.context.work_dir / "director"
        self.state_path = self.root / "director-state.json"
        self.action_path = self.root / "action-required.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.adapter_runner = AdapterRunner(self.root / "adapter-state.json")
        self.state = self._load_or_create_state()

    def _load_or_create_state(self) -> dict[str, Any]:
        if self.state_path.is_file():
            state = load_and_migrate_state(self.state_path)
            if state.get("project_file") != str(self.context.project_file):
                raise DirectorContractError("director state belongs to a different project")
            stages = state.setdefault("stages", {})
            previous_state_version = int(state.get("schema_version") or 0)
            for name in STAGES:
                stages.setdefault(name, _stage_template())
                row = stages[name]
                if not str(row.get("readiness") or "").strip():
                    row["readiness"] = _existing_stage_readiness(name, row, self.project)
            previous_inputs = state.get("input_fingerprints") or {}
            current_inputs = {
                "project_file": _file_fingerprint(
                    self.context.project_file, previous_inputs.get("project_file")
                ),
                "source_video": _file_fingerprint(
                    self.context.source_video, previous_inputs.get("source_video")
                ),
            }
            if previous_state_version < STATE_VERSION or not all(
                previous_inputs.get(name, {}).get("sha256")
                for name in ("project_file", "source_video")
            ):
                self._invalidate_from(
                    state, "inspect",
                    "legacy state lacks contemporaneous v6 input and artifact fingerprints",
                )
            else:
                changed_input = next((
                    name for name in ("project_file", "source_video")
                    if previous_inputs[name].get("sha256") != current_inputs[name].get("sha256")
                ), None)
                if changed_input:
                    self._invalidate_from(state, "inspect", f"{changed_input} bytes changed")
                for name in STAGES:
                    row = stages[name]
                    if row.get("status") != "complete":
                        continue
                    records = row.get("artifact_records") or []
                    if not _artifact_records_current(records):
                        self._invalidate_from(
                            state, name, f"completed stage artifact changed or lacks hash evidence: {name}",
                        )
                        break
            state["input_fingerprints"] = current_inputs
            state["schema_version"] = STATE_VERSION
            state["director_version"] = DIRECTOR_VERSION
            self._invalidate_changed_manual_return(state)
            _reconcile_state(state)
            write_json(self.state_path, state)
            return state
        state = {
            "schema_version": STATE_VERSION,
            "director_version": DIRECTOR_VERSION,
            "project_file": str(self.context.project_file),
            "project_root": str(self.context.root),
            "input_mode": self.context.input_mode,
            "single_universal_output": True,
            "dependency_state": {
                "schema_version": 1,
                "event_fingerprints": {},
                "last_plan": None,
            },
            "input_fingerprints": {
                "project_file": _file_fingerprint(self.context.project_file),
                "source_video": _file_fingerprint(self.context.source_video),
            },
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "current_stage": None,
            "status": "active",
            "stages": {name: _stage_template() for name in STAGES},
        }
        write_json(self.state_path, state)
        return state

    def _invalidate_from(self, state: dict[str, Any], stage: str, reason: str) -> None:
        boundary = STAGES.index(stage)
        invalidated = []
        for name in STAGES[boundary:]:
            if state.get("stages", {}).get(name, {}).get("status") != "pending":
                invalidated.append(name)
            state["stages"][name] = _stage_template()
        state["last_invalidation"] = {
            "invalidated_at": utc_now(), "from_stage": stage,
            "reason": reason, "invalidated_stages": invalidated,
        }
        self.action_path.unlink(missing_ok=True)

    def _invalidate_changed_manual_return(self, state: dict[str, Any]) -> None:
        """Reopen manual and delivery QA when a returned NLE export changes."""
        if not self.manual_finish_active:
            return
        stages = state.get("stages") or {}
        if stages.get("manual_finish_handoff", {}).get("status") != "complete":
            return
        receipt_path = self.manual_finish_dir / "return-receipt.json"
        returned = self.manual_return_output
        stale_reason: str | None = None
        old_hash: str | None = None
        new_hash: str | None = None
        if not receipt_path.is_file():
            stale_reason = "manual return receipt is missing"
        else:
            receipt = read_json(receipt_path)
            old_hash = receipt.get("returned_final_sha256")
            if not returned.is_file():
                stale_reason = "returned manual final is missing"
            else:
                new_hash = sha256_file(returned)
                if new_hash != old_hash:
                    stale_reason = "returned manual final bytes changed"
        if not stale_reason:
            return
        stages["manual_finish_handoff"] = _stage_template()
        stages["delivery_qa"] = _stage_template()
        write_json(self.manual_finish_dir / "return-change-invalidation.json", {
            "schema_version": 1,
            "invalidated_at": utc_now(),
            "reason": stale_reason,
            "returned_final": str(returned),
            "previous_sha256": old_hash,
            "current_sha256": new_hash,
            "invalidated_stages": ["manual_finish_handoff", "delivery_qa"],
        })
        if self.action_path.is_file():
            self.action_path.unlink(missing_ok=True)

    def _save(self) -> None:
        self.state["updated_at"] = utc_now()
        write_json(self.state_path, self.state)

    def _start(self, stage: str) -> None:
        row = self.state["stages"][stage]
        row.update({"status": "running", "attempts": int(row.get("attempts", 0)) + 1,
                    "updated_at": utc_now(), "error": None, "readiness": "running"})
        self.state.update({"current_stage": stage, "status": "active"})
        if self.action_path.is_file():
            try:
                action_stage = read_json(self.action_path).get("stage")
            except (OSError, json.JSONDecodeError):
                action_stage = None
            action_is_still_blocking = (
                action_stage != stage
                and self.state.get("stages", {}).get(str(action_stage), {}).get("status") == "action_required"
            )
            if not action_is_still_blocking:
                self.action_path.unlink(missing_ok=True)
        self._save()

    def _complete(
        self, stage: str, artifacts: list[Path] | None = None, *, readiness: str = "ready",
    ) -> None:
        row = self.state["stages"][stage]
        resolved_artifacts = [path.resolve() for path in (artifacts or [])]
        row.update({"status": "complete", "updated_at": utc_now(), "error": None,
                    "readiness": readiness,
                    "artifacts": [str(path) for path in resolved_artifacts],
                    "artifact_records": _artifact_records(resolved_artifacts)})
        _reconcile_state(self.state)
        self._save()

    def _capability_config(self, name: str) -> dict[str, Any]:
        return capability_config(self.project, name)

    def _project_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (self.context.root / path).resolve()

    def _run_capability(
        self,
        name: str,
        *,
        command: list[str],
        inputs: list[Path],
        outputs: list[Path],
        blocking: bool = False,
        settings: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        config = self._capability_config(name)
        try:
            return self.adapter_runner.run(
                name=name,
                enabled=config.get("enabled") is True if enabled is None else enabled,
                command=command,
                inputs=inputs,
                outputs=outputs,
                blocking=blocking,
                cwd=Path(__file__).parent,
                settings={**config, **(settings or {})},
                environment_signature={"director_version": DIRECTOR_VERSION},
            )
        except AdapterExecutionError as error:
            raise DirectorContractError(f"capability {name} failed: {error}") from error

    def _action_required(self, stage: str, reason: str, actions: list[dict[str, Any]]) -> None:
        normalized: list[dict[str, Any]] = []
        for index, action in enumerate(actions):
            expected = action.get("expected_outputs", action.get("expected_artifacts"))
            if expected is None and action.get("expected_artifact") is not None:
                expected = [action.get("expected_artifact")]
            if not isinstance(expected, list):
                expected = [expected] if expected is not None else []
            inputs = action.get("inputs")
            if not isinstance(inputs, list):
                inputs = [
                    str(action[key]) for key in ("request", "route", "report")
                    if action.get(key) is not None
                ]
            normalized.append({
                **action,
                "id": str(action.get("id") or f"{stage}-{index + 1}"),
                "owner": str(action.get("owner") or "user"),
                "instruction": str(
                    action.get("instruction") or action.get("capability")
                    or action.get("note") or reason
                ),
                "command": action.get("command") or [],
                "inputs": inputs,
                "expected_outputs": [str(value) for value in expected if value is not None],
            })
        resume_command = (
            f'"{sys.executable}" "{Path(__file__).resolve()}" run '
            f'--project "{self.context.project_file}" --resume'
        )
        owners = sorted({row["owner"] for row in normalized})
        create_action_packet(
            self.action_path,
            stage=stage,
            owner=owners[0] if len(owners) == 1 else "director_coordinated",
            reason=reason,
            actions=normalized,
            reference_root=self.context.root,
            resume_command=resume_command,
        )
        row = self.state["stages"][stage]
        row.update({"status": "action_required", "updated_at": utc_now(), "error": reason,
                    "artifacts": [str(self.action_path.resolve())],
                    "readiness": "action_required"})
        self.state["status"] = "action_required"
        self._save()
        raise DirectorContractError(reason)

    def _fail(self, stage: str, error: Exception) -> None:
        row = self.state["stages"][stage]
        row.update({"status": "failed", "updated_at": utc_now(), "error": str(error),
                    "readiness": "failed"})
        self.state["status"] = "failed"
        self._save()

    @property
    def video_use_dir(self) -> Path:
        return self.context.edit_dir / "video-use"

    @property
    def semantic_brief_path(self) -> Path:
        return self.root / "semantic-brief.json"

    @property
    def production_contract_path(self) -> Path:
        return self.root / "production-contract.json"

    @property
    def evidence_bundle_path(self) -> Path:
        return self.root / "evidence" / "evidence-bundle.json"

    @property
    def adaptive_layout_path(self) -> Path:
        return self.root / "evidence" / "adaptive-layout-constraints.json"

    @property
    def sample_target_binding_dir(self) -> Path:
        return self.root / "target-bindings" / "sample"

    @property
    def full_target_binding_dir(self) -> Path:
        return self.root / "target-bindings" / "full"

    def motion_design_dir(self, scope: str) -> Path:
        if scope not in {"sample", "full"}:
            raise DirectorContractError(f"unknown motion-design scope: {scope}")
        return self.root / "motion-design" / scope

    def renderer_evidence_contract_path(self, scope: str) -> Path:
        project = (
            self.sample_hyperframes_project if scope == "sample"
            else self.full_hyperframes_project
        )
        return project / "renderer-evidence-contract.json"

    def renderer_export_path(self, scope: str) -> Path:
        project = (
            self.sample_hyperframes_project if scope == "sample"
            else self.full_hyperframes_project
        )
        return project / "renderer-export.json"

    def renderer_project_manifest_path(self, scope: str) -> Path:
        project = (
            self.sample_hyperframes_project if scope == "sample"
            else self.full_hyperframes_project
        )
        return project / "renderer-project-manifest.json"

    def _runtime_capture_request(self, scope: str) -> dict[str, Any]:
        if scope not in {"sample", "full"}:
            raise DirectorContractError(f"unknown renderer-evidence scope: {scope}")
        project = (
            self.sample_hyperframes_project if scope == "sample"
            else self.full_hyperframes_project
        )
        target_binding_dir = (
            self.sample_target_binding_dir if scope == "sample"
            else self.full_target_binding_dir
        )
        return {
            "runtime_capture_tool": str(
                (Path(__file__).resolve().parent / "capture_hyperframes_runtime_evidence.py")
            ),
            "runtime_capture_args": {
                "project": str(project),
                "storyboard": str(project / "storyboard.json"),
                "motion_design_contract": str(
                    self.motion_design_dir(scope) / "motion-design-contract.json"
                ),
                "project_artifact": str(self.renderer_project_manifest_path(scope)),
                "target_binding_dir": str(target_binding_dir),
                "output": str(self.renderer_export_path(scope)),
                "snapshot_dir": str(project / "motion-snapshots" / "runtime"),
            },
            "receipt_builder_tool": str(
                (Path(__file__).resolve().parent / "build_keyframe_receipts.py")
            ),
            "receipt_builder_args": {
                "project": str(project),
                "motion_design_contract": str(
                    self.motion_design_dir(scope) / "motion-design-contract.json"
                ),
                "project_artifact": str(self.renderer_project_manifest_path(scope)),
                "renderer_export": str(self.renderer_export_path(scope)),
                "target_binding_dir": str(target_binding_dir),
                "parity": str(self.motion_parity_path(scope)),
                "output_dir": str(self.keyframe_receipt_dir(scope)),
            },
            "browser_resolution": ["npx", "hyperframes", "browser", "path"],
            "missing_runtime_behavior": "action_required",
        }

    def keyframe_receipt_dir(self, scope: str) -> Path:
        project = (
            self.sample_hyperframes_project if scope == "sample"
            else self.full_hyperframes_project
        )
        return project / "keyframe-receipts"

    def motion_parity_path(self, scope: str) -> Path:
        qa_dir = "sample-qa" if scope == "sample" else "full-qa"
        return self.root / qa_dir / "preview-render-parity.json"

    @property
    def creative_review_path(self) -> Path:
        return self.root / "sample-qa" / "creative-review.json"

    @property
    def creative_review_dashboard_path(self) -> Path:
        return self.root / "review" / "creative-review.html"

    @property
    def sample_baseline_raw_path(self) -> Path:
        return self.video_use_dir / "base-preview.mp4"

    @property
    def sample_candidate_raw_path(self) -> Path:
        return self.sample_hyperframes_project / "sample-preview.mp4"

    @property
    def sample_candidate_sfx_path(self) -> Path:
        return self.root / "review-media" / "candidate-with-sfx.mp4"

    @property
    def sample_review_mix_receipt_path(self) -> Path:
        return self.root / "sample-qa" / "sample-review-mix.json"

    @property
    def motion_audio_decision_manifest_path(self) -> Path:
        return self.root / "sample-qa" / "motion-audio-decisions" / "manifest.json"

    @property
    def creative_review_motion_audio_path(self) -> Path:
        if self.motion_audio_decision_manifest_path.is_file():
            return self.motion_audio_decision_manifest_path
        return self.sample_hyperframes_project / "audio-plan.json"

    @property
    def sample_candidate_review_raw_path(self) -> Path:
        audio_plan = self.sample_hyperframes_project / "audio-plan.json"
        if audio_plan.is_file():
            decisions = (read_json(audio_plan).get("motion_sfx") or {}).get("event_decisions") or []
            if any(
                isinstance(row, dict) and row.get("decision") == "cue"
                for row in decisions
            ):
                return self.sample_candidate_sfx_path
        return self.sample_candidate_raw_path

    @property
    def sample_caption_receipt_path(self) -> Path:
        return self.root / "sample-qa" / "sample-caption-delivery.json"

    def _sample_requires_caption_delivery(self) -> bool:
        if self.project.get("motion_quality", {}).get("enabled") is not True:
            return False
        if self.project.get("editing", {}).get("caption_delivery") == "none":
            return False
        analysis_path = self.root / "input-mode-analysis.json"
        caption_analysis = {}
        if analysis_path.is_file():
            caption_analysis = read_json(analysis_path).get("captions") or {}
        verified_burned = caption_analysis.get("burned_in") or {}
        return not (
            bool(caption_analysis.get("subtitle_streams"))
            or (
                verified_burned.get("detected") is True
                and verified_burned.get("verification_status") == "verified"
            )
        )

    @property
    def sample_baseline_path(self) -> Path:
        if self._sample_requires_caption_delivery():
            return self.root / "review-media" / "baseline-captioned.mp4"
        return self.sample_baseline_raw_path

    @property
    def sample_candidate_path(self) -> Path:
        if self._sample_requires_caption_delivery():
            return self.root / "review-media" / "candidate-captioned.mp4"
        return self.sample_candidate_review_raw_path

    def _ensure_sample_caption_delivery(self) -> list[Path]:
        if not self._sample_requires_caption_delivery():
            return [self.sample_baseline_raw_path, self.sample_candidate_review_raw_path]

        captions = self.video_use_dir / "master.srt"
        required = [self.sample_baseline_raw_path, self.sample_candidate_review_raw_path, captions]
        missing = [str(path.resolve()) for path in required if not path.is_file()]
        expected_paths = {
            "caption_source": captions.resolve(),
            "baseline_input": self.sample_baseline_raw_path.resolve(),
            "baseline_output": self.sample_baseline_path.resolve(),
            "candidate_input": self.sample_candidate_review_raw_path.resolve(),
            "candidate_output": self.sample_candidate_path.resolve(),
        }

        def receipt_errors() -> list[str]:
            if not self.sample_caption_receipt_path.is_file():
                return ["sample caption delivery receipt is missing"]
            receipt = read_json(self.sample_caption_receipt_path)
            errors = validate_sample_caption_receipt(receipt)
            observed = {
                "caption_source": Path(str((receipt.get("caption_source") or {}).get("path") or "")).resolve(),
                "baseline_input": Path(str(((receipt.get("baseline") or {}).get("input") or {}).get("path") or "")).resolve(),
                "baseline_output": Path(str(((receipt.get("baseline") or {}).get("output") or {}).get("path") or "")).resolve(),
                "candidate_input": Path(str(((receipt.get("candidate") or {}).get("input") or {}).get("path") or "")).resolve(),
                "candidate_output": Path(str(((receipt.get("candidate") or {}).get("output") or {}).get("path") or "")).resolve(),
            }
            if observed != expected_paths:
                errors.append("sample caption delivery receipt does not bind the configured paired media")
            return errors

        errors = receipt_errors()
        if not missing and errors and self.execute_external:
            materialize_sample_caption_pair(
                baseline_input=self.sample_baseline_raw_path,
                candidate_input=self.sample_candidate_review_raw_path,
                captions=captions,
                baseline_output=self.sample_baseline_path,
                candidate_output=self.sample_candidate_path,
                receipt_path=self.sample_caption_receipt_path,
            )
            errors = receipt_errors()
        if missing or errors:
            request_path = self.root / "sample-qa" / "sample-caption-delivery-request.json"
            write_json(request_path, {
                "schema_version": 1,
                "owner": "director_ffmpeg",
                "purpose": "apply the same output-timeline captions to both paired review media",
                "missing_inputs": missing,
                "validation_errors": errors,
                "caption_source": str(captions.resolve()),
                "baseline_input": str(self.sample_baseline_raw_path.resolve()),
                "candidate_input": str(self.sample_candidate_review_raw_path.resolve()),
                "expected_outputs": [
                    str(self.sample_baseline_path.resolve()),
                    str(self.sample_candidate_path.resolve()),
                    str(self.sample_caption_receipt_path.resolve()),
                ],
                "automatic_execution": "rerun with --execute-external",
            })
            self._action_required(
                "sample_qa",
                "A hash-bound captioned paired sample is required before creative review",
                [{
                    "owner": "director_ffmpeg",
                    "request": str(request_path),
                    "expected_outputs": [
                        str(self.sample_baseline_path.resolve()),
                        str(self.sample_candidate_path.resolve()),
                        str(self.sample_caption_receipt_path.resolve()),
                    ],
                }],
            )
        return [
            self.sample_baseline_path,
            self.sample_candidate_path,
            self.sample_caption_receipt_path,
        ]

    @property
    def creative_review_audio_dir(self) -> Path:
        return self.root / "sample-qa" / "review-audio"

    @property
    def full_semantic_brief_path(self) -> Path:
        return self.root / "full-semantic-brief.json"

    @property
    def sample_hyperframes_project(self) -> Path:
        director = self.project.get("workflow", {}).get("director", {})
        configured = director.get("sample_hyperframes_project", director.get("hyperframes_project"))
        if configured:
            value = Path(str(configured))
            return value.resolve() if value.is_absolute() else (self.context.root / value).resolve()
        return self.context.root / "hyperframes-director"

    @property
    def full_hyperframes_project(self) -> Path:
        configured = self.project.get("workflow", {}).get("director", {}).get("full_hyperframes_project")
        if configured:
            value = Path(str(configured))
            return value.resolve() if value.is_absolute() else (self.context.root / value).resolve()
        return self.context.root / "hyperframes-director-full"

    @property
    def delivery_output(self) -> Path:
        """Automatic universal master produced by final_compose."""
        configured = self.project.get("delivery", {}).get("output")
        if configured:
            value = Path(str(configured))
            return value.resolve() if value.is_absolute() else (self.context.root / value).resolve()
        return self.context.exports_dir / f"{self.project.get('video_id', 'video')}-universal.mp4"

    @property
    def manual_finish_config(self) -> dict[str, Any]:
        delivery = self.project.get("delivery", {})
        manual = delivery.get("manual_finish", {})
        openmontage = delivery.get("openmontage_handoff", {})
        if openmontage.get("enabled") is True and manual.get("enabled") is not True:
            return {**openmontage, "backend": "openmontage", "handoff_kind": "openmontage"}
        return manual

    @property
    def manual_finish_active(self) -> bool:
        return (
            self.manual_finish_config.get("enabled") is True
            and self.manual_finish_config.get("backend") in {"opencut", "openmontage", "other_nle"}
        )

    @property
    def manual_return_output(self) -> Path:
        configured = self.manual_finish_config.get("returned_final")
        if configured:
            value = Path(str(configured))
            return value.resolve() if value.is_absolute() else (self.context.root / value).resolve()
        return self.context.exports_dir / f"{self.project.get('video_id', 'video')}-manual-finish.mp4"

    @property
    def delivery_qa_output(self) -> Path:
        return self.manual_return_output if self.manual_finish_active else self.delivery_output

    @property
    def manual_finish_dir(self) -> Path:
        return self.root / "manual-finish"

    @property
    def manual_handoff_manifest_path(self) -> Path:
        name = (
            "openmontage-handoff-manifest.json"
            if self.manual_finish_config.get("handoff_kind") == "openmontage"
            else "handoff-manifest.json"
        )
        return self.manual_finish_dir / name

    def _legacy_script_audit(self) -> Path:
        scripts_dir = self.context.root / str(self.project.get("paths", {}).get("scripts", "scripts"))
        patterns = {
            "hardcoded_motion_event_array": re.compile(r"\bevents\s*=\s*\[", re.IGNORECASE),
            "hardcoded_caption_array": re.compile(r"\bCAPTIONS\s*=\s*\["),
            "legacy_ffmpeg_overlay_graph": re.compile(r"overlay=.*eof_action|motion-filter", re.IGNORECASE),
        }
        findings: list[dict[str, Any]] = []
        if scripts_dir.is_dir():
            for path in sorted(scripts_dir.rglob("*")):
                if path.suffix.lower() not in {".py", ".js", ".mjs", ".ps1"} or not path.is_file():
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except UnicodeDecodeError:
                    lines = path.read_text(encoding="utf-8-sig").splitlines()
                for line_number, line in enumerate(lines, 1):
                    for kind, pattern in patterns.items():
                        if pattern.search(line):
                            findings.append({
                                "file": str(path.resolve()),
                                "line": line_number,
                                "kind": kind,
                                "disposition": "legacy_quarantined",
                            })
        report = self.root / "legacy-script-audit.json"
        write_json(report, {
            "schema_version": 1,
            "scripts_dir": str(scripts_dir.resolve()),
            "execution_allowed": False,
            "status": "legacy_quarantined" if findings else "clean",
            "findings": findings,
            "director_execution_sources": [
                str(Path(__file__).resolve()),
                str(Path(__file__).with_name("video_use_bridge.py").resolve()),
            ],
        })
        return report

    def _resolve_input_mode(self) -> Path | None:
        analysis_path = self.root / "input-mode-analysis.json"
        evidence_path = self.root / "input-mode-evidence.json"
        if self.context.input_mode != "needs_analysis":
            if evidence_path.is_file():
                evidence = read_json(evidence_path)
                stat = self.context.source_video.stat()
                if (
                    evidence.get("selected_mode") == self.context.input_mode
                    and evidence.get("source_size") == stat.st_size
                    and evidence.get("source_mtime_ns") == stat.st_mtime_ns
                    and evidence.get("source_sha256") == sha256_file(self.context.source_video)
                ):
                    return evidence_path
            return None
        evidence_dir = self.root / "input-mode-evidence"
        command = [
            sys.executable, str(Path(__file__).with_name("analyze_existing_edit.py")),
            "--media", str(self.context.source_video),
            "--out", str(analysis_path),
            "--evidence-dir", str(evidence_dir),
            "--max-samples", "24",
        ]
        subprocess.run(command, cwd=Path(__file__).parent, check=True)
        analysis = read_json(analysis_path)
        caption_info = analysis.get("captions") or {}
        burned = caption_info.get("burned_in") or {}
        subtitle_streams = caption_info.get("subtitle_streams") or []
        signals: list[str] = []
        if subtitle_streams:
            signals.append("embedded_subtitle_stream")
        if (
            burned.get("detected") is True
            and burned.get("verification_status") == "verified"
            and float(burned.get("confidence", 0)) >= 0.52
        ):
            signals.append("high_confidence_burned_captions")
        selected = "polish_existing" if signals else "preserve"
        stat = self.context.source_video.stat()
        write_json(evidence_path, {
            "schema_version": 1,
            "owner": "director",
            "source": str(self.context.source_video),
            "source_sha256": sha256_file(self.context.source_video),
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "selected_mode": selected,
            "signals": signals or ["no_strong_existing_edit_marker"],
            "analysis": str(analysis_path),
            "analysis_sha256": sha256_file(analysis_path),
            "policy": "strong existing-edit evidence selects polish_existing; otherwise preserve",
            "generated_by": command,
        })
        self.context = replace(self.context, input_mode=selected)
        self.state["input_mode"] = selected
        return evidence_path

    def stage_inspect(self) -> None:
        input_mode_evidence = self._resolve_input_mode()
        legacy_audit = self._legacy_script_audit()
        capability_inventory = self.root / "capability-inventory.json"
        toolchain_report = self.root / "toolchain-compatibility.json"
        inventory = build_capability_inventory(self.project)
        invalid_required = [
            row["name"] for row in inventory["capabilities"]
            if row.get("route_reason") == "invalid_required_disable"
        ]
        if invalid_required:
            raise DirectorContractError(
                "required capabilities cannot be disabled: " + ", ".join(invalid_required)
            )
        write_json(capability_inventory, inventory)
        write_json(toolchain_report, build_toolchain_report())
        report = {
            "schema_version": 1,
            "director_version": DIRECTOR_VERSION,
            "project": str(self.context.project_file),
            "source": str(self.context.source_video),
            "source_sha256": sha256_file(self.context.source_video),
            "input_mode": self.context.input_mode,
            "input_mode_evidence": str(input_mode_evidence) if input_mode_evidence else "explicit_project_or_filename_signal",
            "roles": ROLE_CONTRACT,
            "forbidden_new_execution_paths": list(FORBIDDEN_NEW_PATHS),
            "project_scripts_execution": "forbidden",
            "motion_renderer": "hyperframes",
            "final_media_mechanics": "ffmpeg",
            "delivery": "one universal video unless bytes must materially differ",
            "legacy_script_audit": str(legacy_audit),
            "capability_inventory": str(capability_inventory),
            "toolchain_compatibility": str(toolchain_report),
        }
        path = self.root / "workflow-contract.json"
        write_json(path, report)
        artifacts = [path, legacy_audit, capability_inventory, toolchain_report]
        if input_mode_evidence:
            artifacts.append(input_mode_evidence)
        self._complete("inspect", artifacts)

    def stage_provider_governance(self) -> None:
        config = self.project.get("provider_governance", {})
        project_hash = sha256_file(self.context.project_file)
        decision_path = self.root / "provider-decision.json"
        ledger_path = self.root / "cost-ledger.json"
        decision = build_decision_report(config=config, project_hash=project_hash)
        ledger = None
        if ledger_path.is_file():
            candidate_ledger = read_json(ledger_path)
            if not validate_cost_ledger(candidate_ledger, project_hash) and (
                candidate_ledger.get("config") == config
            ):
                ledger = candidate_ledger
        if ledger is None:
            ledger = create_cost_ledger(config=config, project_hash=project_hash)
        write_json(decision_path, decision)
        write_json(ledger_path, ledger)
        assert_valid(validate_decision_report(decision, config, project_hash), "provider decision")
        assert_valid(validate_cost_ledger(ledger, project_hash), "cost ledger")
        self._complete("provider_governance", [decision_path, ledger_path])

    def _write_cost_ledger(self, ledger: dict[str, Any]) -> Path:
        """Atomically persist the governed mutable ledger and refresh its stage receipt."""
        ledger_path = self.root / "cost-ledger.json"
        write_json(ledger_path, ledger)
        stage = self.state.get("stages", {}).get("provider_governance") or {}
        if stage.get("status") == "complete":
            artifacts = [Path(value).resolve() for value in stage.get("artifacts") or []]
            if ledger_path.resolve() not in artifacts:
                artifacts.append(ledger_path.resolve())
            stage["artifact_records"] = _artifact_records(artifacts)
            stage["updated_at"] = utc_now()
            self._save()
        return ledger_path

    def _metered_provider_call(
        self, tasks: tuple[str, ...], callback: Callable[[], Any], *, stage: str,
    ) -> Any:
        decision_path = self.root / "provider-decision.json"
        ledger_path = self.root / "cost-ledger.json"
        if not decision_path.is_file() or not ledger_path.is_file():
            self._action_required(
                stage, "External call requires current provider governance artifacts",
                [{"owner": "director", "provider_decision": str(decision_path),
                  "cost_ledger": str(ledger_path)}],
            )
        decision = read_json(decision_path)
        ledger = read_json(ledger_path)
        reservations: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        for task in tasks:
            row = (decision.get("decisions") or {}).get(task) or {}
            if row.get("status") != "selected":
                unavailable.append({
                    "task": task,
                    "status": row.get("status") or "missing",
                    "selection_reason": row.get("selection_reason"),
                })
                continue
            selected = row.get("selected") or {}
            inflight = next((
                item for item in ledger.get("reservations") or []
                if item.get("task") == task
                and item.get("provider") == selected.get("name")
                and item.get("status") == "reserved"
            ), None)
            if inflight is not None:
                self._action_required(
                    stage, "An in-flight provider reservation must be reconciled before retry",
                    [{"owner": "provider_adapter", "task": task,
                      "reservation_id": inflight.get("id"),
                      "action": "verify the provider outcome and reconcile success or failure; do not repeat the call",
                      "cost_ledger": str(ledger_path)}],
                )
            reservation = reserve_selected_call(ledger, decision, task=task)
            if reservation.get("status") == "action_required":
                self._write_cost_ledger(ledger)
                self._action_required(
                    stage, f"Provider budget cannot reserve the configured {task} call",
                    [{"owner": "user", "reservation": reservation,
                      "cost_ledger": str(ledger_path)}],
                )
            reservations.append(reservation)
        if unavailable:
            self._action_required(
                stage, "External call requires an authorized provider decision",
                [{"owner": "user", "unavailable_tasks": unavailable,
                  "provider_decision": str(decision_path)}],
            )
        self._write_cost_ledger(ledger)
        started = time.perf_counter()
        try:
            result = callback()
        except Exception as provider_error:
            elapsed = time.perf_counter() - started
            reconciliation_errors: list[str] = []
            for reservation in reservations:
                try:
                    reconcile_selected_call(
                        ledger, decision, str(reservation["id"]), status="failed",
                        elapsed_seconds=elapsed,
                    )
                except ValueError as error:
                    reconciliation_errors.append(str(error))
            self._write_cost_ledger(ledger)
            if reconciliation_errors:
                self._action_required(
                    stage, "Failed provider call requires actual-cost reconciliation",
                    [{"owner": "provider_adapter", "errors": reconciliation_errors,
                      "original_error": str(provider_error), "cost_ledger": str(ledger_path)}],
                )
            raise
        elapsed = time.perf_counter() - started
        result_evidence = result if isinstance(result, dict) else {
            "outputs": [str(value) for value in result] if isinstance(result, (list, tuple)) else str(result)
        }
        for reservation in reservations:
            try:
                receipt_path = (
                    self.root / "provider-call-results" / f"{reservation['id']}.json"
                )
                write_provider_result_receipt(receipt_path, reservation, result_evidence)
                reconcile_selected_call(
                    ledger, decision, str(reservation["id"]), status="success",
                    elapsed_seconds=elapsed, result=result_evidence,
                    result_receipt_path=receipt_path,
                )
            except ValueError as error:
                self._write_cost_ledger(ledger)
                self._action_required(
                    stage, "Successful provider call requires actual-cost reconciliation",
                    [{"owner": "provider_adapter", "error": str(error),
                      "reservation_id": reservation["id"], "cost_ledger": str(ledger_path)}],
                )
        self._write_cost_ledger(ledger)
        return result

    def _ensure_provider_reservation(
        self, task: str, *, stage: str, allow_create: bool = True,
    ) -> dict[str, Any] | None:
        decision_path = self.root / "provider-decision.json"
        ledger_path = self.root / "cost-ledger.json"
        decision = read_json(decision_path); ledger = read_json(ledger_path)
        selected = ((decision.get("decisions") or {}).get(task) or {}).get("selected")
        if not isinstance(selected, dict):
            return None
        existing = next((
            row for row in ledger.get("reservations") or []
            if row.get("task") == task and row.get("provider") == selected.get("name")
            and row.get("status") == "reserved"
        ), None)
        if existing is None and not allow_create:
            return None
        reservation = existing or reserve_selected_call(ledger, decision, task=task)
        self._write_cost_ledger(ledger)
        if reservation.get("status") == "action_required":
            self._action_required(
                stage, f"Provider budget cannot reserve the configured {task} call",
                [{"owner": "user", "reservation": reservation,
                  "cost_ledger": str(ledger_path)}],
            )
        return reservation

    def _reconcile_provider_result(
        self, task: str, reservation_id: str, result: dict[str, Any], *, status: str,
    ) -> None:
        decision_path = self.root / "provider-decision.json"
        ledger_path = self.root / "cost-ledger.json"
        decision = read_json(decision_path); ledger = read_json(ledger_path)
        reservation = next(
            (row for row in ledger.get("reservations") or []
             if row.get("id") == reservation_id), None,
        )
        receipt_path = None
        if status == "success":
            if reservation is None:
                raise ValueError("provider reservation is missing")
            receipt_path = self.root / "provider-call-results" / f"{reservation_id}.json"
            write_provider_result_receipt(receipt_path, reservation, result)
        reconcile_selected_call(
            ledger, decision, reservation_id, status=status, elapsed_seconds=0.0,
            result=result, result_receipt_path=receipt_path,
        )
        self._write_cost_ledger(ledger)

    def _valid_video_use_transcript(self, path: Path) -> tuple[bool, str | None]:
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError) as error:
            return False, str(error)
        words = data.get("words") if isinstance(data, dict) else None
        if not words:
            return False, "top-level words are required"
        for index, word in enumerate(words):
            if word.get("type") != "word" or word.get("start") is None or word.get("end") is None:
                return False, f"words[{index}] is not a video-use word-timestamp item"
        return True, None

    def _adopt_cached_word_transcript(self, target: Path) -> Path | None:
        """Adopt a cached word transcript without changing its text or timing.

        This is a schema-only bridge for an existing ASR result. It does not
        transcribe, summarize, correct, interpolate, or retime speech.
        """
        candidates: list[tuple[int, Path, list[dict[str, Any]], dict[str, Any]]] = []
        transcript_root = self.context.edit_dir / "transcripts"
        for path in transcript_root.glob("*.json"):
            try:
                raw = read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            words: list[dict[str, Any]] = []
            if isinstance(raw, dict) and isinstance(raw.get("words"), list):
                words = list(raw["words"])
            elif isinstance(raw, dict):
                for segment in raw.get("segments") or []:
                    words.extend(segment.get("words") or [])
            valid = [word for word in words
                     if word.get("start") is not None and word.get("end") is not None
                     and str(word.get("word", word.get("text", ""))).strip()]
            if valid:
                candidates.append((len(valid), path, valid, raw))
        if not candidates:
            return None
        _, source, words, raw = max(candidates, key=lambda item: (item[0], item[1].stat().st_mtime))
        adopted = []
        for index, word in enumerate(words):
            adopted.append({
                "id": word.get("id", index),
                "type": "word",
                "text": str(word.get("word", word.get("text", ""))).strip(),
                "start": float(word["start"]),
                "end": float(word["end"]),
                "speaker_id": word.get("speaker_id", word.get("speaker")),
            })
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json(target, {
            "language_code": raw.get("language", raw.get("language_code", "zh")),
            "words": adopted,
            "adoption": {
                "owner": "video-use",
                "operation": "schema-only cached word transcript adoption",
                "source": str(source.resolve()),
                "source_sha256": sha256_file(source),
                "text_or_timing_modified": False,
            },
        })
        report = self.video_use_dir / "transcript-adoption.json"
        write_json(report, {
            "schema_version": 1,
            "owner": "video-use",
            "source": str(source.resolve()),
            "target": str(target.resolve()),
            "word_count": len(adopted),
            "text_or_timing_modified": False,
            "source_sha256": sha256_file(source),
            "target_sha256": sha256_file(target),
        })
        return source

    def stage_video_use_timeline(self) -> None:
        self.video_use_dir.mkdir(parents=True, exist_ok=True)
        source_name = self.context.source_video.stem
        transcript_dir = self.video_use_dir / "transcripts"
        transcript_path = transcript_dir / f"{source_name}.json"
        edl_path = self.video_use_dir / "edl.json"
        if not transcript_path.is_file():
            self._adopt_cached_word_transcript(transcript_path)
        router_config = self.project.get("transcription", {}).get("router", {})
        route_path = self.video_use_dir / "asr-route.json"
        route: dict[str, Any] | None = None
        if router_config.get("enabled") is True:
            route = choose_asr_backend(router_config, {
                "language": router_config.get("language", "zh"),
                "hotwords": router_config.get("hotwords", []),
                "project_terms": router_config.get("project_terms", {}),
                "profile_terms": router_config.get("profile_terms", {}),
                "speaker_count": router_config.get("speaker_count", 1),
                "precise_word_alignment": router_config.get("precise_word_alignment", False),
                "speaker_labels": router_config.get("speaker_labels", False),
                "diarization": router_config.get("diarization", False),
                "noise_score": router_config.get("noise_score", 0.0),
                "timing_drift_seconds": router_config.get("timing_drift_seconds", 0.0),
                "drift_threshold_seconds": router_config.get("drift_threshold_seconds", 0.12),
                "existing_captions": router_config.get("existing_captions", {}),
                "required_capabilities": router_config.get("required_capabilities", []),
            })
            write_json(route_path, route)
        if not transcript_path.is_file() and route is not None:
            raw_result_value = router_config.get("result")
            raw_result = self._project_path(raw_result_value) if raw_result_value else None
            if raw_result and raw_result.is_file() and route.get("selected_backend") != "none":
                write_json(
                    transcript_path,
                    normalize_transcript(read_json(raw_result), backend=str(route["selected_backend"])),
                )
            else:
                self._action_required(
                    "video_use_timeline",
                    "the selected ASR backend must produce word timestamps before video-use can author the timeline",
                    [{
                        "owner": "video-use",
                        "capability": "word transcription through configured ASR adapter",
                        "backend": route.get("selected_backend"),
                        "route": str(route_path),
                        "expected_raw_result": str(raw_result) if raw_result else None,
                        "expected_artifact": str(transcript_path),
                        "semantic_deletion_authority": False,
                    }],
                )
        valid, error = self._valid_video_use_transcript(transcript_path) if transcript_path.is_file() else (False, "missing")
        if not valid:
            transcribe = video_use_root_command(self.context.source_video, self.video_use_dir)
            self._action_required(
                "video_use_timeline",
                f"A valid video-use top-level word transcript is required: {error}",
                [{
                    "owner": "video-use",
                    "capability": "word transcription",
                    "command": transcribe,
                    "expected_artifact": str(transcript_path),
                    "note": "Do not substitute summarized captions or broad ASR segment text.",
                }],
            )
        asr_artifacts: list[Path] = []
        if route is not None:
            required = set(route.get("required_capabilities") or [])
            speaker_path = self._project_path(
                router_config.get("speaker_report") or "edit/video-use/speaker-report.json"
            )
            alignment_path = self._project_path(
                router_config.get("alignment_report") or "edit/video-use/alignment-report.json"
            )
            missing_reports = [
                str(path) for capability, path in (
                    ("speaker_labels", speaker_path), ("word_alignment", alignment_path),
                ) if capability in required and not path.is_file()
            ]
            if missing_reports:
                self._action_required(
                    "video_use_timeline",
                    "selected ASR pipeline requires hash-bound speaker/alignment reports",
                    [{
                        "owner": "video-use",
                        "capability": "ASR speaker/alignment evidence",
                        "inputs": [str(transcript_path), str(route_path)],
                        "expected_outputs": missing_reports,
                    }],
                )
            pipeline_report = validate_pipeline_reports(
                read_json(transcript_path), route=route,
                speaker_report=read_json(speaker_path) if speaker_path.is_file() else None,
                alignment_report=read_json(alignment_path) if alignment_path.is_file() else None,
            )
            pipeline_path = self.video_use_dir / "asr-pipeline-qa.json"
            write_json(pipeline_path, pipeline_report)
            asr_artifacts.extend([
                pipeline_path,
                *([speaker_path] if speaker_path.is_file() else []),
                *([alignment_path] if alignment_path.is_file() else []),
            ])
        duration = _ffprobe_duration(self.context.source_video)
        if not edl_path.is_file():
            request = self.video_use_dir / "edl-request.json"
            write_json(request, {
                "schema_version": 1,
                "owner": "director",
                "delegate_to": "video-use",
                "source": str(self.context.source_video),
                "source_name": source_name,
                "source_duration": duration,
                "word_transcript": str(transcript_path),
                "input_mode": self.context.input_mode,
                "preservation_policy": {
                    "preserve_source_meaning": True,
                    "preserve_tail_by_default": True,
                    "semantic_deletion_requires_review": True,
                    "polish_existing_preserves_established_picture_and_audio": True,
                },
                "required_output": str(edl_path),
                "required_cut_policy": {
                    "word_boundary_padding_ms": [30, 100],
                    "audio_fade_ms": 30,
                },
            })
            self._action_required(
                "video_use_timeline",
                "video-use must author the EDL; the director may provide preservation policy but cannot invent edit decisions",
                [{"owner": "video-use", "capability": "EDL and edit timeline",
                  "request": str(request), "expected_artifact": str(edl_path)}],
            )
        edl = read_json(edl_path)
        assert_valid(
            validate_video_use_edl(
                edl,
                source_name=source_name,
                source_duration=duration,
                input_mode=self.context.input_mode,
            ),
            "video-use EDL",
        )
        otio_artifacts: list[Path] = []
        otio_config = self.project.get("timeline", {}).get("otio", {})
        if otio_config.get("enabled") is True:
            otio_path = self.video_use_dir / "timeline.otio"
            restored_path = self.video_use_dir / "timeline-from-otio.json"
            roundtrip_path = self.video_use_dir / "otio-roundtrip.json"
            timeline = edl_to_otio(edl, rate=float(otio_config.get("rate", 30.0)))
            write_json(otio_path, timeline)
            restored = otio_to_internal(timeline)
            write_json(restored_path, restored)
            roundtrip_errors = validate_otio_roundtrip(edl, restored)
            write_json(roundtrip_path, {
                "schema_version": 1,
                "status": "pass" if not roundtrip_errors else "failed",
                "authoritative_edl": str(edl_path.resolve()),
                "authoritative_edl_sha256": sha256_file(edl_path),
                "otio": str(otio_path.resolve()),
                "otio_sha256": sha256_file(otio_path),
                "restored": str(restored_path.resolve()),
                "errors": roundtrip_errors,
                "content_authority": "video-use-edl",
            })
            if roundtrip_errors:
                raise DirectorContractError("OTIO projection changed the authoritative EDL: " + "; ".join(roundtrip_errors))
            otio_artifacts.extend([otio_path, restored_path, roundtrip_path])
        media_analysis_path = self.video_use_dir / "media-analysis.json"
        edit_preflight_path = self.video_use_dir / "edit-correctness-preflight.json"
        if not media_analysis_path.is_file() or not edit_preflight_path.is_file():
            verify_dir = self.video_use_dir / "verify"
            timeline_helper = render_helper_path().with_name("timeline_view.py")
            windows = [
                (0.0, min(3.0, duration), verify_dir / "source-start.png"),
                (max(0.0, duration / 2 - 1.5), min(duration, duration / 2 + 1.5),
                 verify_dir / "source-middle.png"),
                (
                    max(0.0, duration - 3.0),
                    max(0.0, duration - 0.1),
                    verify_dir / "source-end.png",
                ),
            ]
            request = self.video_use_dir / "analysis-request.json"
            write_json(request, {
                "schema_version": 1,
                "owner": "director",
                "delegate_to": "video-use",
                "source": str(self.context.source_video),
                "edl": str(edl_path),
                "transcript": str(transcript_path),
                "timeline_view_commands": [
                    [sys.executable, str(timeline_helper), str(self.context.source_video),
                     f"{start:.3f}", f"{end:.3f}", "-o", str(output)]
                    for start, end, output in windows
                ],
                "expected_artifacts": [str(media_analysis_path), str(edit_preflight_path)],
                "note": "Analyze and verify; do not render a new video at this stage.",
            })
            self._action_required(
                "video_use_timeline",
                "video-use media analysis and EDL correctness preflight are required",
                [{"owner": "video-use", "capability": "media analysis and edit correctness",
                  "request": str(request),
                  "expected_artifacts": [str(media_analysis_path), str(edit_preflight_path)]}],
            )
        assert_valid(
            validate_video_use_media_analysis(
                read_json(media_analysis_path),
                source_path=self.context.source_video,
                source_duration=duration,
            ),
            "video-use media analysis",
        )
        assert_valid(
            validate_video_use_edit_preflight(
                read_json(edit_preflight_path),
                edl_path=edl_path,
                transcript_path=transcript_path,
                edl=edl,
            ),
            "video-use edit correctness preflight",
        )
        plan = {
            "schema_version": 1,
            "owner": "video-use",
            "transcript": str(transcript_path),
            "transcript_sha256": sha256_file(transcript_path),
            "edl": str(edl_path),
            "edl_sha256": sha256_file(edl_path),
            "cut_render_command": render_command(edl_path, self.video_use_dir / "base-preview.mp4", preview=True),
            "caption_bridge_command": [
                sys.executable, str(Path(__file__).with_name("video_use_bridge.py")),
                "--edl", str(edl_path), "--transcript", f"{source_name}={transcript_path}",
                "--out-dir", str(self.video_use_dir),
                "--max-chars", "24", "--max-duration", "6.5", "--pause-break", "0.5",
                "--punctuation-style", str(
                    self.project.get("editing", {}).get("caption_punctuation", "spoken_clean")
                ),
            ],
            "correctness_requirements": [
                "word-boundary cuts", "30-100ms cut padding", "30ms audio fades",
                "output timeline subtitle mapping", "caption synchronization sampling",
            ],
        }
        corrections = self.context.edit_dir / "transcripts" / "caption-corrections-v2.json"
        cursor = 0.0
        for row in (edl.get("ranges") or [])[:-1]:
            cursor += float(row["end"]) - float(row["start"])
            plan["caption_bridge_command"].extend(["--cut-boundary", f"{cursor:.6f}"])
        terminology = (
            (self.project.get("editing") or {}).get("caption_terminology") or []
        )
        for term in terminology:
            plan["caption_bridge_command"].extend(["--terminology", str(term)])
        if corrections.is_file():
            plan["caption_bridge_command"].extend(["--corrections", str(corrections)])
        plan_path = self.video_use_dir / "execution-plan.json"
        write_json(plan_path, plan)
        result = subprocess.run(plan["caption_bridge_command"], capture_output=True, text=True)
        if result.returncode:
            raise DirectorContractError(
                "video-use caption timeline bridge failed: " + (result.stderr.strip() or result.stdout.strip())
            )
        sync_report = self.video_use_dir / "caption-sync-report.json"
        sync = read_json(sync_report)
        if sync.get("passed") is not True:
            raise DirectorContractError("video-use caption synchronization sampling did not pass")
        if route is not None:
            drift = max((
                max(float(row.get("lead_error_s", 0)), float(row.get("tail_error_s", 0)))
                for row in (sync.get("samples") or []) if row.get("passed") is not None
            ), default=0.0)
            quality = build_asr_quality_report(
                read_json(transcript_path), route=route,
                source_media_sha256=sha256_file(self.context.source_video),
                measured_drift_seconds=drift,
                drift_threshold_seconds=float(router_config.get("drift_threshold_seconds", 0.12)),
            )
            quality_path = self.video_use_dir / "asr-quality-report.json"
            write_json(quality_path, quality)
            asr_artifacts.append(quality_path)
            if quality.get("status") != "pass":
                self._action_required(
                    "video_use_timeline",
                    "ASR terminology or forced-alignment quality gate requires review",
                    [{"owner": "video-use", "capability": "ASR quality remediation",
                      "report": str(quality_path), "expected_artifact": str(transcript_path)}],
                )
        self._complete("video_use_timeline", [edl_path, transcript_path, plan_path,
                                               media_analysis_path, edit_preflight_path,
                                               self.video_use_dir / "mapped-words.json",
                                               self.video_use_dir / "captions.json",
                                               self.video_use_dir / "master.srt", sync_report,
                                               *otio_artifacts, *asr_artifacts,
                                               *([route_path] if route_path.is_file() else [])])

    def stage_evidence_acquisition(self) -> None:
        transcript = self.video_use_dir / "transcripts" / f"{self.context.source_video.stem}.json"
        if not transcript.is_file():
            raise DirectorContractError("evidence acquisition requires the video-use word transcript")
        output_dir = self.evidence_bundle_path.parent
        output = acquire_evidence(
            media=self.context.source_video,
            transcript_path=transcript,
            output_dir=output_dir,
            optional_adapters=self.project.get("analysis", {}).get("adapters", {}),
            existing_assets=self.project.get("source", {}).get("existing_assets"),
        )
        bundle = read_json(output)
        if bundle.get("source", {}).get("sha256") != sha256_file(self.context.source_video):
            raise DirectorContractError("evidence bundle source hash does not match")
        if bundle.get("transcript", {}).get("sha256") != sha256_file(transcript):
            raise DirectorContractError("evidence bundle transcript hash does not match")
        analysis_artifacts: list[Path] = []
        optional = bundle.setdefault("optional_adapters", {})
        adapter_names = {
            "pyscenedetect": "scene_detection",
            "mediapipe": "mediapipe_tracking",
            "paddleocr": "ocr",
        }
        for adapter_name, capability_name in adapter_names.items():
            config = self.project.get("analysis", {}).get("adapters", {}).get(adapter_name, {})
            if config.get("enabled") is not True:
                optional[adapter_name] = {"status": "disabled", "reason": "optional_default_off"}
                continue
            command = config.get("command") or []
            outputs = [self._project_path(value) for value in (config.get("outputs") or [])]
            if not command or not outputs:
                optional[adapter_name] = {
                    "status": "unavailable", "reason": "adapter command and outputs are not configured",
                }
                continue
            try:
                result = self.adapter_runner.run(
                    name=capability_name, enabled=True, command=[str(value) for value in command],
                    inputs=[self.context.source_video, transcript], outputs=outputs,
                    blocking=config.get("required") is True, cwd=self.context.root,
                    settings={"adapter": adapter_name, "timeout_seconds": config.get("timeout_seconds", 900)},
                )
            except AdapterExecutionError as error:
                raise DirectorContractError(f"analysis adapter {adapter_name} failed: {error}") from error
            optional[adapter_name] = {
                "status": result.get("status"), "outputs": [str(path) for path in outputs],
            }
            if result.get("status") in {"complete", "reused"}:
                analysis_artifacts.extend(outputs)
                payload = read_json(outputs[0])
                if adapter_name == "pyscenedetect":
                    bundle["scene_evidence"] = payload
                elif adapter_name == "paddleocr":
                    bundle["ocr"] = payload
                else:
                    bundle.setdefault("protected_regions", {})["mediapipe"] = payload
        write_json(output, bundle)
        declared_frames = [Path(str(row.get("path"))).resolve()
                           for row in (bundle.get("representative_frames") or [])
                           if isinstance(row, dict) and row.get("path")]
        artifacts = [output, *declared_frames, *analysis_artifacts]
        display = bundle.get("display") or {}
        target_ratio = "9:16" if display.get("orientation") == "portrait" else "16:9"
        subject_track = output_dir / "subject-track.json"
        result = self._run_capability(
            "subject_tracking",
            command=[
                sys.executable, str(Path(__file__).with_name("analyze_subject_track.py")),
                "--video", str(self.context.source_video), "--out", str(subject_track),
                "--target-ratio", target_ratio,
            ],
            inputs=[self.context.source_video],
            outputs=[subject_track],
            settings={"orientation": display.get("orientation"), "target_ratio": target_ratio},
        )
        if result.get("status") in {"complete", "reused"}:
            if not subject_track.is_file():
                raise DirectorContractError(
                    "capability subject_tracking reported completion without its declared output: "
                    f"{subject_track}"
                )
            artifacts.append(subject_track)
            tracked_faces = subject_track_face_regions(
                read_json(subject_track),
                report_path=subject_track,
                report_sha256=sha256_file(subject_track),
            )
            if tracked_faces:
                protected = bundle.setdefault("protected_regions", {})
                protected["faces"] = tracked_faces
                protected.setdefault("sources", {})["faces"] = {
                    "kind": "subject_track",
                    "path": str(subject_track.resolve()),
                    "sha256": sha256_file(subject_track),
                }
                protected["status"] = "detector_evidence_available"
        protected_review = (
            (self.project.get("analysis") or {}).get("protected_region_review") or {}
        )
        if protected_review.get("enabled") is True:
            configured_manifest = protected_review.get("manifest")
            if not configured_manifest:
                raise DirectorContractError(
                    "analysis.protected_region_review.manifest is required when enabled"
                )
            review_path = self._project_path(str(configured_manifest))
            observations, review_artifacts = _load_protected_region_review(
                review_path,
                project_root=self.context.root,
                source_sha256=sha256_file(self.context.source_video),
            )
            protected = bundle.setdefault("protected_regions", {})
            protected.setdefault("observations", {}).update(observations)
            protected.setdefault("sources", {})["review"] = {
                "kind": "protected_region_review",
                "path": str(review_path.resolve()),
                "sha256": sha256_file(review_path),
            }
            protected["status"] = "detector_and_review_evidence_available"
            artifacts.extend(review_artifacts)
        write_json(output, bundle)
        if self.project.get("motion_quality", {}).get("enabled") is True:
            source_config = self.project.get("source", {})
            configured_content_type = str(source_config.get("content_type") or "").strip()
            content_type = configured_content_type or (
                "talking_head"
                if (bundle.get("display") or {}).get("orientation") == "portrait"
                else "screen_tutorial"
            )
            layout_contract = build_adaptive_layout_constraints(
                bundle,
                content_type=content_type,
                identity_mode=str((self.project.get("identity") or {}).get("mode") or "generic"),
            )
            write_json(self.adaptive_layout_path, layout_contract)
            artifacts.append(self.adaptive_layout_path)
        design_tokens_path = self.context.edit_dir / "design-tokens.json"
        if isinstance(bundle.get("design_tokens"), dict):
            write_json(design_tokens_path, {
                "schema_version": 1,
                "source_evidence_bundle": str(output.resolve()),
                "source_evidence_bundle_sha256": sha256_file(output),
                **bundle["design_tokens"],
            })
            artifacts.append(design_tokens_path)
        if self.context.input_mode == "polish_existing":
            polish_analysis = self.root / "input-mode-analysis.json"
            analysis_result = self._run_capability(
                "existing_edit_polish",
                command=[
                    sys.executable, str(Path(__file__).with_name("analyze_existing_edit.py")),
                    "--media", str(self.context.source_video), "--out", str(polish_analysis),
                    "--evidence-dir", str(self.root / "input-mode-evidence"),
                ],
                inputs=[self.context.source_video], outputs=[polish_analysis], enabled=True,
            )
            if analysis_result.get("status") in {"complete", "reused"}:
                enhancement_plan = output_dir / "enhancement-plan.json"
                plan_result = self._run_capability(
                    "existing_edit_polish_plan",
                    command=[
                        sys.executable, str(Path(__file__).with_name("build_enhancement_plan.py")),
                        "--analysis", str(polish_analysis), "--transcript", str(transcript),
                        "--out", str(enhancement_plan),
                    ],
                    inputs=[polish_analysis, transcript], outputs=[enhancement_plan], enabled=True,
                )
                if plan_result.get("status") in {"complete", "reused"}:
                    artifacts.extend([polish_analysis, enhancement_plan])
        if (self.root / "adapter-state.json").is_file():
            artifacts.append(self.root / "adapter-state.json")
        self._complete("evidence_acquisition", artifacts)

    def stage_semantic_brief(self) -> None:
        transcript = self.video_use_dir / "transcripts" / f"{self.context.source_video.stem}.json"
        motion_quality_enabled = self.project.get("motion_quality", {}).get("enabled") is True
        if not self.semantic_brief_path.is_file():
            bundle = read_json(self.evidence_bundle_path) if self.evidence_bundle_path.is_file() else {}
            packet = self.root / "semantic-brief-request.json"
            write_json(packet, {
                "schema_version": 3 if motion_quality_enabled else 2,
                "owner": "director_with_llm",
                "required_content_reading": "raw_word_transcript_and_evidence_frames",
                "transcript": str(transcript) if transcript.is_file() else None,
                "transcript_sha256": sha256_file(transcript) if transcript.is_file() else None,
                "evidence_bundle": str(self.evidence_bundle_path),
                "evidence_bundle_sha256": sha256_file(self.evidence_bundle_path)
                if self.evidence_bundle_path.is_file() else None,
                "evidence_frames": bundle.get("representative_frames") or [],
                "output": str(self.semantic_brief_path),
                "deterministic_rules_role": "reject low-information, repeats, overlap, overflow, duplication, and filler only",
                "forbidden": ["keyword score as semantic author", "project script hardcoded events", "density quota filler"],
                **({
                    "editorial_intent": self.project.get("editorial_intent"),
                    "promise_ledger_required": True,
                    "promise_binding_surfaces": [
                        "hook", "title", "cover", "description", "cta", "motion_copy",
                    ],
                    "promise_rules": [
                        "all claims bind to proof semantic event ids",
                        "wording may vary across surfaces but must not mechanically repeat",
                        "prohibited claims are forbidden",
                        "neutral education cannot invent a sales goal",
                    ],
                } if (self.project.get("editorial_intent") or {}).get("enabled") is True else {}),
                **({
                    "opportunity_model": "decision_complete_v1",
                    "allowed_decisions": [
                        "render", "annotation", "caption_only", "reuse_source",
                        "quiet_source", "action_required",
                    ],
                    "one_decision_per_opportunity": True,
                    "rendered_storyboard_is_ordered_subset": True,
                    "fixed_cadence_or_event_family_quota": False,
                    "render_requirements": [
                        "semantic parent", "approved visible copy", "word IDs",
                        "source/output window", "viewer takeaway", "frame evidence",
                    ],
                } if motion_quality_enabled else {}),
            })
            self._action_required(
                "semantic_brief",
                "LLM-authored semantic brief is required after reading the word transcript and evidence frames",
                [{"owner": "director_with_llm", "capability": "semantic visual direction",
                  "request": str(packet), "expected_artifact": str(self.semantic_brief_path)}],
            )
        brief = read_json(self.semantic_brief_path)
        if motion_quality_enabled and not is_decision_complete_brief(brief):
            raise DirectorContractError(
                "enabled motion quality requires a schema 3 decision-complete semantic brief"
            )
        assert_valid(
            validate_semantic_brief(
                brief, require_sample_variety=not motion_quality_enabled,
            ),
            "semantic brief",
        )
        assert_valid(validate_semantic_evidence_binding(
            brief, transcript_path=transcript, evidence_bundle_path=self.evidence_bundle_path,
        ), "semantic brief evidence binding")
        editorial_config = self.project.get("editorial_intent") or {}
        if editorial_config.get("enabled") is True:
            brief_for_ledger = dict(brief)
            if not isinstance(brief_for_ledger.get("editorial_intent"), dict):
                configured = {key: value for key, value in editorial_config.items() if key != "enabled"}
                if configured.get("mode") == "explicit":
                    brief_for_ledger["editorial_intent"] = configured
            promise_ledger_path = self.root / "editorial-promise-ledger.json"
            promise_ledger = build_promise_ledger(brief_for_ledger)
            promise_ledger["semantic_brief"] = {
                "path": str(self.semantic_brief_path.resolve()),
                "sha256": sha256_file(self.semantic_brief_path),
            }
            write_json(promise_ledger_path, promise_ledger)
        unresolved = [
            str(row.get("id") or "<missing>")
            for row in (brief.get("events") or [])
            if isinstance(row, dict) and row.get("decision") == "action_required"
        ]
        if unresolved:
            self._action_required(
                "semantic_brief",
                "Semantic opportunities require a material editorial decision",
                [{
                    "owner": "user_or_editorial_director",
                    "capability": "resolve semantic opportunity decisions",
                    "request": str(self.semantic_brief_path),
                    "opportunity_ids": unresolved,
                    "expected_artifact": str(self.semantic_brief_path),
                }],
            )
        artifacts = [self.semantic_brief_path]
        if editorial_config.get("enabled") is True:
            artifacts.append(self.root / "editorial-promise-ledger.json")
        artifacts.extend(self._semantic_confidence_gate(brief))
        optional_media_artifacts = self._optional_media_adapter_artifacts()
        artifacts.extend(optional_media_artifacts)
        if optional_media_artifacts:
            self._action_required(
                "semantic_brief",
                "Enabled optional media adapters require an explicit provider execution and review",
                [{
                    "owner": "configured_optional_media_provider",
                    "capability": "materialize optional media evidence or assets",
                    "report": str(optional_media_artifacts[0]),
                }],
            )
        evidence = read_json(self.evidence_bundle_path)
        extension_routes = route_extensions(self.project, evidence, brief)
        extension_report = self.root / "conditional-extensions.json"
        extension_payload = run_extension_adapters(
            project=self.project, routes=extension_routes,
            inputs=[transcript, self.evidence_bundle_path, self.semantic_brief_path],
            root=self.context.root, runner=self.adapter_runner, execute=self.execute_external,
        )
        write_json(extension_report, extension_payload)
        artifacts.append(extension_report)
        required_failures = [
            name for name, row in (extension_payload.get("extensions") or {}).items()
            if row.get("status") == "failed"
        ]
        if required_failures:
            self._action_required(
                "semantic_brief", "Required conditional extension output failed validation",
                [{"owner": "configured_extension_adapter", "capabilities": required_failures,
                  "report": str(extension_report)}],
            )
        preferences_config = self.project.get("preferences", {})
        if preferences_config.get("enabled") is True:
            profile_value = preferences_config.get("profile")
            profile_path = self._project_path(profile_value) if profile_value else None
            preference_output = self.root / "applied-motion-preferences.json"
            if profile_path and profile_path.is_file():
                content_type = str(self.project.get("content", {}).get("type") or "generic")
                applied = apply_motion_preferences(
                    load_motion_preferences(profile_path), content_type,
                    str(self.project.get("video_id") or "unknown"),
                    preferences_config.get("safety") or {},
                )
                write_json(preference_output, {
                    "schema_version": 1, "profile": str(profile_path),
                    "profile_sha256": sha256_file(profile_path), **applied,
                })
            else:
                write_json(preference_output, {
                    "schema_version": 1, "enabled": True, "status": "unavailable",
                    "reason": "configured preference profile is missing",
                })
            artifacts.append(preference_output)
        if transcript.is_file():
            hook_path = self.root / "hook-pacing-audit.json"
            promise_ledger_path = self.root / "editorial-promise-ledger.json"
            hook_command = [
                sys.executable, str(Path(__file__).with_name("audit_hook_pacing.py")),
                "--transcript", str(transcript), "--out", str(hook_path),
            ]
            if promise_ledger_path.is_file():
                hook_command.extend(["--promise-ledger", str(promise_ledger_path)])
            hook_result = self._run_capability(
                "hook_pacing",
                command=hook_command,
                inputs=[transcript, self.semantic_brief_path, *(
                    [promise_ledger_path] if promise_ledger_path.is_file() else []
                )], outputs=[hook_path],
            )
            if hook_result.get("status") in {"complete", "reused"}:
                artifacts.append(hook_path)
            publishing_path = self.root / "publish-metadata.json"
            title = str(self.project.get("content", {}).get("title") or self.project.get("video_id", "video"))
            publishing_command = [
                sys.executable, str(Path(__file__).with_name("generate_publishing_copy.py")),
                "--title", title, "--transcript", str(transcript), "--out", str(publishing_path),
            ]
            if promise_ledger_path.is_file():
                publishing_command.extend(["--promise-ledger", str(promise_ledger_path)])
            publishing_result = self._run_capability(
                "publishing_copy",
                command=publishing_command,
                inputs=[transcript, self.semantic_brief_path, *(
                    [promise_ledger_path] if promise_ledger_path.is_file() else []
                )], outputs=[publishing_path],
                settings={"title": title},
            )
            if publishing_result.get("status") in {"complete", "reused"}:
                if promise_ledger_path.is_file():
                    publishing = read_json(publishing_path)
                    binding = publishing.get("promise_binding") or {}
                    assert_valid(
                        validate_promise_bindings(
                            read_json(promise_ledger_path), binding.get("surfaces") or [],
                        ),
                        "publishing promise binding",
                    )
                artifacts.append(publishing_path)
        self._complete("semantic_brief", artifacts)

    def _optional_media_adapter_artifacts(self) -> list[Path]:
        adapters = (self.project.get("extensions") or {}).get(
            "optional_media_adapters"
        ) or []
        enabled = [row for row in adapters if isinstance(row, dict) and row.get("enabled") is True]
        if not enabled:
            return []
        decisions = [authorize_optional_adapter(row) for row in enabled]
        output = self.root / "optional-media-adapters.json"
        write_json(output, {
            "schema_version": 1,
            "status": (
                "unavailable" if any(row.get("status") == "unavailable" for row in decisions)
                else "action_required"
            ),
            "adapters": decisions,
            "automatic_execution_claimed": False,
            "aesthetic_approval_granted": False,
            "publication_authorized": False,
        })
        return [output]

    def _ensure_editorial_promise_closure(self) -> Path | None:
        ledger_path = self.root / "editorial-promise-ledger.json"
        if not ledger_path.is_file():
            return None
        ledger = read_json(ledger_path)
        rows: list[dict[str, Any]] = []
        inputs: dict[str, dict[str, str]] = {}
        hook_path = self.root / "hook-pacing-audit.json"
        if hook_path.is_file():
            hook = read_json(hook_path)
            if isinstance(hook.get("promise_binding"), dict):
                rows.append(hook["promise_binding"])
            inputs["hook"] = {"path": str(hook_path), "sha256": sha256_file(hook_path)}
        publishing_path = self.root / "publish-metadata.json"
        if publishing_path.is_file():
            publishing = read_json(publishing_path)
            for row in (publishing.get("promise_binding") or {}).get("surfaces") or []:
                if isinstance(row, dict) and row.get("surface") not in {
                    value.get("surface") for value in rows if isinstance(value, dict)
                }:
                    rows.append(row)
            inputs["publishing"] = {
                "path": str(publishing_path), "sha256": sha256_file(publishing_path),
            }
        cover_plan_path = self.context.edit_dir / "cover" / "cover-editorial-plan.json"
        if cover_plan_path.is_file():
            cover_plan = read_json(cover_plan_path)
            binding = (cover_plan.get("editorial_promise") or {}).get("binding")
            if isinstance(binding, dict):
                rows.append(binding)
            inputs["cover"] = {
                "path": str(cover_plan_path), "sha256": sha256_file(cover_plan_path),
            }
        contract_path = self.motion_design_dir("sample") / "motion-design-contract.json"
        if contract_path.is_file():
            contract = read_json(contract_path)
            promise_proof = set(
                str(value) for value in (ledger.get("single_promise") or {}).get(
                    "proof_event_ids"
                ) or []
            )
            approved = [
                row for row in contract.get("opportunities") or []
                if isinstance(row, dict) and row.get("decision") == "render"
                and str(row.get("semantic_event_id")) in promise_proof
            ]
            copy = " / ".join(
                str(value) for row in approved for value in row.get("approved_visible_copy") or []
                if str(value).strip()
            )
            proof = [str(row.get("semantic_event_id")) for row in approved]
            if copy and proof:
                rows.append({
                    "surface": "motion_copy", "copy": copy,
                    "promise_id": ledger.get("promise_id"), "proof_event_ids": proof,
                })
            inputs["motion"] = {
                "path": str(contract_path), "sha256": sha256_file(contract_path),
            }
        proof = list((ledger.get("single_promise") or {}).get("proof_event_ids") or [])
        rows.append({
            "surface": "cta", "copy": str(ledger.get("cta") or ""),
            "promise_id": ledger.get("promise_id"), "proof_event_ids": proof,
        })
        required = {"hook", "title", "description", "cta", "motion_copy"}
        if cover_plan_path.is_file():
            required.add("cover")
        closure = build_promise_closure(ledger, rows, required_surfaces=required)
        closure["inputs"] = inputs
        closure["promise_ledger"] = {
            "path": str(ledger_path), "sha256": sha256_file(ledger_path),
        }
        output = self.root / "editorial-promise-closure.json"
        write_json(output, closure)
        if closure.get("status") != "pass":
            raise DirectorContractError(
                "editorial promise closure failed: " + "; ".join(closure.get("errors") or [])
            )
        return output

    def _semantic_confidence_gate(self, brief: dict[str, Any]) -> list[Path]:
        config = self.project.get("analysis", {}).get("semantic_confidence", {})
        if config.get("enabled") is not True:
            return []
        candidates = brief.get("confidence_candidates")
        if not isinstance(candidates, list) or not candidates:
            self._action_required(
                "semantic_brief",
                "enabled semantic confidence requires evidence-complete confidence_candidates",
                [{
                    "owner": "director_with_llm",
                    "capability": "semantic confidence evidence and counterexample review",
                    "request": str(self.root / "semantic-brief-request.json"),
                    "expected_artifact": str(self.semantic_brief_path),
                }],
            )
        selected_ids = set(selected_semantic_event_ids(brief))
        event_ids = selected_ids if is_decision_complete_brief(brief) else {
            str(row.get("id")) for row in (brief.get("events") or [])
            if isinstance(row, dict) and row.get("treatment") != "quiet_source"
        }
        candidate_ids = {str(row.get("event_id")) for row in candidates if isinstance(row, dict)}
        if candidate_ids != event_ids:
            raise DirectorContractError(
                "semantic confidence candidates must cover exactly the non-quiet semantic events"
            )
        report = build_candidate_report(
            candidates,
            low_confidence_threshold=float(config.get("low_confidence_threshold", 0.7)),
        )
        validate_candidate_report(report)
        output = self.root / "semantic-confidence.json"
        write_json(output, report)
        if report.get("status") == "action_required":
            self._action_required(
                "semantic_brief",
                "meaning-changing semantic candidates require explicit review",
                [{
                    "owner": "user",
                    "capability": "review low-confidence semantic decisions",
                    "report": str(output),
                    "expected_artifact": str(output),
                }],
            )
        return [output]

    def stage_production_contract(self) -> None:
        transcript = self.video_use_dir / "transcripts" / f"{self.context.source_video.stem}.json"
        edl = self.video_use_dir / "edl.json"
        required = [transcript, edl, self.semantic_brief_path]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            self._action_required(
                "production_contract",
                "Production contract requires the current transcript, EDL, and semantic brief",
                [{"owner": "director", "missing_artifacts": missing}],
            )
        contract = build_contract(
            project=self.project,
            source_path=self.context.source_video,
            transcript_path=transcript,
            edl_path=edl,
            semantic_brief_path=self.semantic_brief_path,
            input_mode=self.context.input_mode,
        )
        write_json(self.production_contract_path, contract)
        assert_valid(validate_contract(
            contract,
            project=self.project,
            source_path=self.context.source_video,
            transcript_path=transcript,
            edl_path=edl,
            semantic_brief_path=self.semantic_brief_path,
            input_mode=self.context.input_mode,
        ), "production contract")
        self._complete("production_contract", [self.production_contract_path])

    def _validate_current_production_contract(self) -> None:
        if not self.production_contract_path.is_file():
            raise DirectorContractError("current production contract is missing")
        transcript = self.video_use_dir / "transcripts" / f"{self.context.source_video.stem}.json"
        assert_valid(validate_contract(
            read_json(self.production_contract_path),
            project=self.project,
            source_path=self.context.source_video,
            transcript_path=transcript,
            edl_path=self.video_use_dir / "edl.json",
            semantic_brief_path=self.semantic_brief_path,
            input_mode=self.context.input_mode,
        ), "production contract")

    def _validate_provider_governance(self, *, require_reconciled: bool = False) -> None:
        project_hash = sha256_file(self.context.project_file)
        decision_path = self.root / "provider-decision.json"
        ledger_path = self.root / "cost-ledger.json"
        if not decision_path.is_file() or not ledger_path.is_file():
            raise DirectorContractError("provider decision or cost ledger is missing")
        config = self.project.get("provider_governance", {})
        assert_valid(
            validate_decision_report(read_json(decision_path), config, project_hash),
            "provider decision",
        )
        ledger = read_json(ledger_path)
        assert_valid(validate_cost_ledger(ledger, project_hash), "cost ledger")
        if require_reconciled:
            pending = [row for row in ledger.get("reservations") or []
                       if row.get("status") in {"reserved", "action_required"}]
            if pending:
                raise DirectorContractError(
                    f"provider cost ledger has {len(pending)} unreconciled reservation(s)"
                )

    def stage_brand_motion_playbook(self) -> None:
        output_dir = self.root / "brand-motion"
        playbook_path = output_dir / "brand-motion-playbook.json"
        config = self.project.get("brand", {}).get("motion_playbook", {})
        if config.get("enabled", True) is not True:
            write_json(playbook_path, {
                "schema_version": 1, "status": "disabled", "reason": "project configuration",
            })
            self._complete("brand_motion_playbook", [playbook_path])
            return
        design_tokens = self.context.edit_dir / "design-tokens.json"
        if not design_tokens.is_file() or not self.semantic_brief_path.is_file():
            self._action_required(
                "brand_motion_playbook",
                "Brand Motion Playbook requires current design tokens and semantic brief",
                [{"owner": "director", "missing_artifacts": [
                    str(path) for path in (design_tokens, self.semantic_brief_path)
                    if not path.is_file()
                ]}],
            )
        profile_value = self.project.get("profile")
        profile_path = self._project_path(profile_value) if profile_value else None
        outputs = compile_playbook(
            project=self.project,
            design_tokens_path=design_tokens,
            semantic_brief_path=self.semantic_brief_path,
            profile_path=profile_path,
            output_dir=output_dir,
        )
        assert_valid(
            validate_playbook(read_json(outputs[0]), project=self.project),
            "brand motion playbook",
        )
        self._complete("brand_motion_playbook", list(outputs))

    def _motion_source_media(self) -> dict[str, Any]:
        evidence = read_json(self.evidence_bundle_path)
        display = evidence.get("display") or {}
        try:
            duration = float(evidence.get("duration_seconds"))
            width = int(display.get("width"))
            height = int(display.get("height"))
        except (TypeError, ValueError):
            raise DirectorContractError(
                "motion-design compilation requires measured duration and display dimensions"
            )
        orientation = str(display.get("orientation") or "")
        if duration <= 0 or width <= 0 or height <= 0 or orientation not in {
            "landscape", "portrait", "square", "mixed",
        }:
            raise DirectorContractError(
                "motion-design compilation requires valid source duration, dimensions, and orientation"
            )
        configured_type = str(
            (self.project.get("source") or {}).get("content_type")
            or (self.project.get("content") or {}).get("type") or ""
        ).lower()
        if configured_type in {"screen_tutorial", "screen_recording", "product_demo"}:
            source_type = "screen_recording"
        elif configured_type in {"talking_head", "portrait_talking_head", "interview"}:
            source_type = "talking_head"
        elif configured_type in {"mixed", "hybrid", "screen_plus_camera"}:
            source_type = "mixed"
        else:
            source_type = "other"
        return {
            "path": str(self.context.source_video.resolve()),
            "sha256": sha256_file(self.context.source_video),
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "orientation": orientation,
            "source_type": source_type,
        }

    def _ensure_motion_design(
        self, *, scope: str, brief_path: Path, binding_dir: Path,
    ) -> tuple[dict[str, Any], list[Path]]:
        output_dir = self.motion_design_dir(scope)
        output_dir.mkdir(parents=True, exist_ok=True)
        contract_path = output_dir / "motion-design-contract.json"
        report_path = output_dir / "motion-design-compile-report.json"
        choreography_path = output_dir / "hyperframes-choreography.json"
        brand_path = self.root / "brand-motion" / "brand-motion-playbook.json"
        artifacts = {
            "semantic_brief": brief_path,
            "production_contract": self.production_contract_path,
            "evidence_bundle": self.evidence_bundle_path,
            "brand_playbook": brand_path,
        }
        missing = [str(path) for path in artifacts.values() if not path.is_file()]
        if missing:
            raise DirectorContractError(
                "motion-design compilation requires current input artifacts: " + ", ".join(missing)
            )
        target_bindings: dict[str, dict[str, Any]] = {}
        binding_errors: list[str] = []
        for path in sorted(binding_dir.glob("*.json")):
            payload = read_json(path)
            errors = validate_binding(payload, require_resolved=True)
            if errors:
                binding_errors.extend(f"{path.name}: {error}" for error in errors)
                continue
            target_bindings[str(payload["binding_id"])] = payload
        assert_valid(binding_errors, f"{scope} motion-design target bindings")
        existing_created_at = None
        if contract_path.is_file():
            try:
                existing_created_at = read_json(contract_path).get("created_at")
            except (OSError, ValueError, json.JSONDecodeError):
                existing_created_at = None
        compiled = compile_motion_design(
            project_id=str(self.project.get("video_id") or self.context.root.name),
            semantic_brief=read_json(brief_path),
            source_media=self._motion_source_media(),
            identity_mode=str((self.project.get("identity") or {}).get("mode") or "generic"),
            input_artifacts=artifacts,
            adaptive_layout=read_json(self.adaptive_layout_path),
            target_bindings=target_bindings,
            advanced_runtimes_enabled=(
                (self.project.get("motion_quality") or {}).get("advanced_runtimes", {})
                .get("enabled") is True
            ),
            advanced_runtime_evidence=(
                (self.project.get("motion_quality") or {}).get("advanced_runtimes", {})
                .get("evidence")
            ),
            recipe_registry=load_recipe_registry(DEFAULT_RECIPE_REGISTRY),
            created_at=str(existing_created_at or utc_now()),
        )
        write_json(contract_path, compiled["contract"])
        write_json(report_path, {key: value for key, value in compiled.items() if key != "contract"})
        write_json(
            choreography_path,
            build_hyperframes_choreography(
                compiled["contract"], advanced_runtime=compiled["advanced_runtime"],
            ),
        )
        assert_valid(
            validate_motion_design_contract(
                read_json(contract_path), artifact_paths=artifacts,
                recipe_registry=load_recipe_registry(DEFAULT_RECIPE_REGISTRY),
            ),
            f"{scope} motion-design contract",
        )
        return read_json(contract_path), [
            contract_path, report_path, choreography_path, DEFAULT_RECIPE_REGISTRY,
        ]

    def _motion_design_request(
        self, scope: str, contract: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(contract, dict):
            raise DirectorContractError("motion-design request requires a compiled contract")
        output_dir = self.motion_design_dir(scope)
        contract_path = output_dir / "motion-design-contract.json"
        choreography_path = output_dir / "hyperframes-choreography.json"
        registry = load_recipe_registry(DEFAULT_RECIPE_REGISTRY)
        recipes = {row["recipe_id"]: row for row in registry["recipes"]}
        selected_recipe_ids = [
            row.get("recipe_id") for row in contract.get("opportunities") or []
            if row.get("decision") == "render"
        ]
        advanced_required = any(
            (recipes.get(str(recipe_id)) or {}).get("runtime", {}).get(
                "advanced_feature_flag_required"
            ) is True
            for recipe_id in selected_recipe_ids
        )
        choreography = read_json(choreography_path)
        return {
            "selection_owner": "director_motion_quality_engine",
            "renderer_authority": "typed_choreography_only",
            "contract": str(contract_path.resolve()),
            "contract_sha256": sha256_file(contract_path),
            "typed_choreography": str(choreography_path.resolve()),
            "typed_choreography_sha256": sha256_file(choreography_path),
            "format_grammar_id": (
                (choreography.get("format_grammar") or {}).get("grammar_id")
            ),
            "format_grammar_sha256": choreography.get("format_grammar_sha256"),
            "recipe_registry": str(DEFAULT_RECIPE_REGISTRY.resolve()),
            "recipe_registry_sha256": sha256_file(DEFAULT_RECIPE_REGISTRY),
            "selected_event_ids": list(contract.get("selected_event_ids") or []),
            "required_hyperframes_skills": [
                "hyperframes", "hyperframes-core", "hyperframes-creative",
                "hyperframes-animation", "hyperframes-cli",
                *(["hyperframes-keyframes"] if advanced_required else []),
            ],
            "forbidden": [
                "renderer-selected semantics", "renderer-selected recipe",
                "renderer-invented visible copy", "renderer-guessed target geometry",
            ],
        }

    def _write_renderer_evidence_contract(
        self, *, scope: str, motion_contract: dict[str, Any], storyboard_path: Path,
    ) -> Path:
        project = (
            self.sample_hyperframes_project if scope == "sample"
            else self.full_hyperframes_project
        )
        project_artifact = project / "index.html"
        contract_path = self.motion_design_dir(scope) / "motion-design-contract.json"
        selected = [
            {
                "event_id": row["semantic_event_id"],
                "recipe_id": row["recipe_id"],
                "approved_visible_copy": list(row.get("approved_visible_copy") or []),
                "target_binding_ids": list(row.get("target_binding_ids") or []),
                "required_phases": ["entrance", "mid", "pre_exit", "post_exit"],
            }
            for row in motion_contract.get("opportunities") or []
            if row.get("decision") == "render"
        ]
        path = self.renderer_evidence_contract_path(scope)
        write_json(path, {
            "schema_version": 1,
            "owner": "director",
            "renderer": "hyperframes",
            "scope": scope,
            "project_entrypoint": {
                "path": str(project_artifact.resolve()),
                "sha256": sha256_file(project_artifact),
            },
            "storyboard": {
                "path": str(storyboard_path.resolve()),
                "sha256": sha256_file(storyboard_path),
            },
            "motion_design_contract": {
                "path": str(contract_path.resolve()),
                "sha256": sha256_file(contract_path),
            },
            "source_media": {
                "path": str(self.context.source_video.resolve()),
                "sha256": sha256_file(self.context.source_video),
            },
            "outputs": {
                "renderer_export": str(self.renderer_export_path(scope).resolve()),
                "renderer_project_manifest": str(
                    self.renderer_project_manifest_path(scope).resolve()
                ),
                "keyframe_receipt_directory": str(self.keyframe_receipt_dir(scope).resolve()),
                "preview_render_parity": str(self.motion_parity_path(scope).resolve()),
            },
            "events": selected,
            "required_runtime_exports": [
                "actual_visible_text", "dom_geometry", "source_state", "targets",
                "connectors", "crop", "caption_overlap", "composite_contrast",
            ],
            "required_tools": ["strict_check", "animation_map"],
            **self._runtime_capture_request(scope),
            "request_metadata_is_not_render_evidence": True,
        })
        return path

    def _validate_motion_render_evidence(
        self, *, scope: str, storyboard: dict[str, Any],
    ) -> tuple[list[str], list[Path]]:
        contract_path = self.motion_design_dir(scope) / "motion-design-contract.json"
        project = (
            self.sample_hyperframes_project if scope == "sample"
            else self.full_hyperframes_project
        )
        project_artifact = self.renderer_project_manifest_path(scope)
        renderer_export_path = self.renderer_export_path(scope)
        parity_path = self.motion_parity_path(scope)
        evidence_contract_path = self.renderer_evidence_contract_path(scope)
        errors: list[str] = []
        required = [
            contract_path, project_artifact, renderer_export_path, parity_path,
            evidence_contract_path,
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            return ["motion render evidence is missing: " + ", ".join(missing)], required
        motion_contract = read_json(contract_path)
        evidence_contract = read_json(evidence_contract_path)
        expected_contract_artifacts = {
            "project_entrypoint": project / "index.html",
            "storyboard": project / "storyboard.json",
            "motion_design_contract": contract_path,
            "source_media": self.context.source_video,
        }
        if evidence_contract.get("schema_version") != 1 or evidence_contract.get("owner") != "director":
            errors.append("renderer evidence contract metadata is invalid")
        for name, expected_path in expected_contract_artifacts.items():
            row = evidence_contract.get(name) or {}
            expected_path = expected_path.resolve()
            if Path(str(row.get("path") or "")).resolve() != expected_path:
                errors.append(f"renderer evidence contract {name} path is stale")
            if not expected_path.is_file() or row.get("sha256") != (
                sha256_file(expected_path) if expected_path.is_file() else None
            ):
                errors.append(f"renderer evidence contract {name} hash is stale")
        expected_outputs = {
            "renderer_export": self.renderer_export_path(scope),
            "renderer_project_manifest": self.renderer_project_manifest_path(scope),
            "keyframe_receipt_directory": self.keyframe_receipt_dir(scope),
            "preview_render_parity": parity_path,
        }
        for name, expected_path in expected_outputs.items():
            if Path(str((evidence_contract.get("outputs") or {}).get(name) or "")).resolve() != expected_path.resolve():
                errors.append(f"renderer evidence contract {name} output is stale")
        renderer_export = read_json(renderer_export_path)
        errors.extend(validate_renderer_export(
            renderer_export, project_artifact=project_artifact,
            motion_design_contract_path=contract_path,
        ))
        expected_ids = list(motion_contract.get("selected_event_ids") or [])
        receipt_dir = self.keyframe_receipt_dir(scope)
        receipt_paths: dict[str, Path] = {}
        if receipt_dir.is_dir():
            for path in sorted(receipt_dir.glob("*.json")):
                try:
                    event_id = str(read_json(path).get("event_id") or "")
                except (OSError, ValueError, json.JSONDecodeError):
                    errors.append(f"invalid keyframe receipt JSON: {path}")
                    continue
                if not event_id or event_id in receipt_paths:
                    errors.append(f"duplicate or missing keyframe receipt event_id: {path}")
                    continue
                receipt_paths[event_id] = path.resolve()
        if set(receipt_paths) != set(expected_ids):
            errors.append("keyframe receipt event set differs from compiler-selected events")
        binding_dir = (
            self.sample_target_binding_dir if scope == "sample" else self.full_target_binding_dir
        )
        bindings_by_id: dict[str, Path] = {}
        for path in sorted(binding_dir.glob("*.json")):
            try:
                binding_id = str(read_json(path).get("binding_id") or "")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if binding_id:
                bindings_by_id[binding_id] = path.resolve()
        opportunities = {
            str(row.get("semantic_event_id")): row
            for row in motion_contract.get("opportunities") or [] if isinstance(row, dict)
        }
        for event_id in expected_ids:
            receipt_path = receipt_paths.get(event_id)
            if receipt_path is None:
                continue
            opportunity = opportunities.get(event_id) or {}
            binding_paths = [
                bindings_by_id[binding_id]
                for binding_id in opportunity.get("target_binding_ids") or []
                if binding_id in bindings_by_id
            ]
            errors.extend(
                f"{event_id}: {error}" for error in validate_keyframe_receipt(
                    read_json(receipt_path),
                    motion_design_contract_path=contract_path,
                    recipe_registry_path=DEFAULT_RECIPE_REGISTRY,
                    target_binding_paths=binding_paths,
                    renderer_export_path=renderer_export_path,
                    maximum_caption_overlap_ratio=0.0,
                    minimum_composite_contrast_ratio=4.5,
                    maximum_connector_error_pixels=4.0,
                )
            )
        parity = read_json(parity_path)
        errors.extend(validate_preview_render_parity(
            parity, storyboard,
            configured_tolerances=self.project["qa"]["preview_render_parity"]["tolerances"],
            expected_bindings={
                "project_artifact": project_artifact,
                "motion_design_contract": contract_path,
                "source_media": self.context.source_video,
            },
            keyframe_receipt_paths=receipt_paths,
        ))
        artifacts = [*required, *receipt_paths.values()]
        return errors, artifacts

    def stage_hyperframes_storyboard(self) -> None:
        project = self.sample_hyperframes_project
        brief = read_json(self.semantic_brief_path)
        motion_quality_enabled = self.project.get("motion_quality", {}).get("enabled") is True
        target_binding_contract = None
        motion_design_artifacts: list[Path] = []
        motion_contract: dict[str, Any] | None = None
        if motion_quality_enabled:
            self.sample_target_binding_dir.mkdir(parents=True, exist_ok=True)
            target_binding_contract = _target_binding_request_contract(
                layout_path=self.adaptive_layout_path,
                binding_dir=self.sample_target_binding_dir,
                schema_path=Path(__file__).parents[1] / "references" / "p0-p2-design"
                / "schemas" / "target-binding.schema.json",
                identity_mode=str((self.project.get("identity") or {}).get("mode") or "generic"),
            )
            binding_events = [
                event for event in brief.get("events") or []
                if isinstance(event, dict) and event.get("decision") == "render"
                and event.get("target_binding_ids")
            ]
            required_binding_ids = [
                str(binding_id)
                for event in binding_events
                for binding_id in event.get("target_binding_ids") or []
            ]
            if len(required_binding_ids) != len(set(required_binding_ids)):
                raise DirectorContractError(
                    "sample semantic brief assigns a target binding ID more than once"
                )
            missing_binding_ids = [
                binding_id for binding_id in required_binding_ids
                if not (self.sample_target_binding_dir / f"{binding_id}.json").is_file()
            ]
            if missing_binding_ids:
                request_path = self.root / "target-binding-request.json"
                write_json(request_path, {
                    "schema_version": 1,
                    "owner": "director",
                    "scope": "sample",
                    "source_media": str(self.context.source_video.resolve()),
                    "source_media_sha256": sha256_file(self.context.source_video),
                    "semantic_brief": str(self.semantic_brief_path.resolve()),
                    "semantic_brief_sha256": sha256_file(self.semantic_brief_path),
                    "target_binding_contract": target_binding_contract,
                    "required_binding_ids": missing_binding_ids,
                    "events": [{
                        "semantic_event_id": str(event.get("id") or ""),
                        "target_binding_ids": [
                            str(value) for value in event.get("target_binding_ids") or []
                            if str(value) in missing_binding_ids
                        ],
                        "source_window": {
                            "start_seconds": event.get("source_start"),
                            "end_seconds": event.get("source_end"),
                        },
                        "output_window": {
                            "start_seconds": event.get("output_start"),
                            "end_seconds": event.get("output_end"),
                        },
                        "target_frame_evidence": list(
                            event.get("target_frame_evidence") or []
                        ),
                        "safe_failure": "fallback_or_action_required_without_guessed_coordinates",
                    } for event in binding_events if any(
                        str(value) in missing_binding_ids
                        for value in event.get("target_binding_ids") or []
                    )],
                    "expected_outputs": [
                        str((self.sample_target_binding_dir / f"{binding_id}.json").resolve())
                        for binding_id in missing_binding_ids
                    ],
                })
                self._action_required(
                    "hyperframes_storyboard",
                    "source-bound target bindings are required before motion compilation",
                    [{
                        "owner": "director_target_binding",
                        "capability": "evidence-backed stateful target geometry",
                        "request": str(request_path),
                        "expected_outputs": [
                            str((self.sample_target_binding_dir / f"{binding_id}.json").resolve())
                            for binding_id in missing_binding_ids
                        ],
                        "guessed_coordinates_allowed": False,
                    }],
                )
            motion_contract, motion_design_artifacts = self._ensure_motion_design(
                scope="sample", brief_path=self.semantic_brief_path,
                binding_dir=self.sample_target_binding_dir,
            )
        motion_request = (
            self._motion_design_request("sample", motion_contract)
            if motion_contract is not None else None
        )
        evidence = read_json(self.evidence_bundle_path) if self.evidence_bundle_path.is_file() else {}
        route_path = self.root / "renderer-route.json"
        route = route_hyperframes(
            self.project, evidence, motion_design_contract=motion_contract,
        )
        renderer_artifacts: list[Path] = []
        catalog_report_path = self.root / "media-catalog-report.json"
        catalog_call = lambda: run_media_catalog(
            project=self.project, semantic_brief=read_json(self.semantic_brief_path),
            root=self.context.root, runner=self.adapter_runner, execute=self.execute_external,
        )
        catalog_config = self.project.get("assets", {}).get("media_catalog", {})
        catalog = (
            self._metered_provider_call(("media_catalog",), catalog_call,
                                        stage="hyperframes_storyboard")
            if self.execute_external and catalog_config.get("command") else catalog_call()
        )
        write_json(catalog_report_path, catalog)
        renderer_artifacts.append(catalog_report_path)
        route["media_catalog_status"] = catalog.get("status")
        for value in catalog.get("outputs") or []:
            path = Path(str(value))
            if path.is_file():
                renderer_artifacts.append(path)
        media_catalog_config = self.project.get("assets", {}).get("media_catalog", {})
        if media_catalog_config.get("required") is True and catalog.get("status") not in {
            "complete", "reused", "not_applicable",
        }:
            self._action_required(
                "hyperframes_storyboard", "Required media catalog adapter did not complete",
                [{"owner": "media-use", "report": str(catalog_report_path)}],
            )
        if route.get("optional_event_renderer") == "remotion":
            remotion = self.project.get("renderer", {}).get("remotion", {})
            command = remotion.get("command") or []
            outputs = [self._project_path(value) for value in (remotion.get("outputs") or [])]
            react_inputs = [Path(value).resolve() for value in
                            (route.get("remotion_component_paths") or [])]
            if command and outputs:
                result = self._run_capability(
                    "remotion_renderer", command=[str(value) for value in command],
                    inputs=[self.semantic_brief_path, *react_inputs], outputs=outputs,
                    blocking=remotion.get("required") is True,
                    settings={"selected_event_ids": route.get("remotion_event_ids")},
                )
                route["remotion_adapter_status"] = result.get("status")
                if result.get("status") in {"complete", "reused"}:
                    renderer_artifacts.extend(outputs)
            else:
                route["remotion_adapter_status"] = "unavailable"
                route["remotion_adapter_reason"] = "no adapter command and outputs configured"
            if remotion.get("required") is True and route.get("remotion_adapter_status") not in {
                "complete", "reused",
            }:
                self._action_required(
                    "hyperframes_storyboard", "Required Remotion event adapter did not complete",
                    [{"owner": "remotion", "route": str(route_path),
                      "expected_outputs": [str(value) for value in outputs]}],
                )
        else:
            remotion = self.project.get("renderer", {}).get("remotion", {})
            if isinstance(remotion, dict) and remotion.get("enabled") is True \
                    and remotion.get("required") is True:
                self._action_required(
                    "hyperframes_storyboard", "Required Remotion evidence is unavailable or stale",
                    [{"owner": "remotion", "route": str(route_path),
                      "expected_artifact": str(route_path)}],
                )
        write_json(route_path, route)
        ip_artifacts: list[Path] = []
        if self.project.get("visuals", {}).get("ip_production", {}).get("enabled") is True:
            try:
                ip_artifacts = self._metered_provider_call(
                    ("identity_reference_generation",),
                    lambda: produce_ip_components(
                        project=self.project, project_root=self.context.root,
                        semantic_brief=self.semantic_brief_path,
                        design_tokens=self.context.edit_dir / "design-tokens.json",
                        output_dir=self.context.edit_dir / "assets" / "ip-components",
                        runner=self.adapter_runner, execute_external=self.execute_external,
                    ),
                    stage="hyperframes_storyboard",
                )
            except IpProductionActionRequired as error:
                request = self.root / "ip-production-request.json"
                write_json(request, error.packet)
                self._action_required(
                    "hyperframes_storyboard",
                    "Selected IP visual events require topic-specific reviewed component assets",
                    [{"owner": "director_with_image_generation_and_visual_review",
                      "request": str(request)}],
                )
        storyboard_path = project / "storyboard.json"
        vocabulary_path = project / "visual-vocabulary-audit.json"
        index_path = project / "index.html"
        if not storyboard_path.is_file() or not index_path.is_file() or not vocabulary_path.is_file():
            packet = self.root / "hyperframes-request.json"
            write_json(packet, {
                "schema_version": 3 if motion_quality_enabled else 2,
                "owner": "hyperframes",
                "semantic_brief": str(self.semantic_brief_path),
                "semantic_inheritance": _semantic_inheritance_contract(
                    brief, motion_quality_enabled=motion_quality_enabled,
                ),
                "scope": "60-90 second sample only",
                "project": str(project),
                "required_skills": (
                    motion_request["required_hyperframes_skills"] if motion_request else
                    ["hyperframes", "hyperframes-core", "hyperframes-creative",
                     "hyperframes-animation", "hyperframes-cli"]
                ),
                "required_outputs": [
                    "index.html", "storyboard.json", "frame.md", "visual-vocabulary-audit.json",
                    *(["renderer-export.json", "keyframe-receipts/*.json"]
                      if motion_quality_enabled else []),
                ],
                "motion_output": "hyperframes_render",
                "renderer_route": str(route_path),
                "brand_motion_playbook": str(
                    self.root / "brand-motion" / "brand-motion-playbook.json"
                ),
                "brand_motion_css": str(self.root / "brand-motion" / "brand-motion-tokens.css"),
                "route": route["route"],
                "route_capabilities": route["capability_skills"],
                "ip_component_artifacts": [str(path) for path in ip_artifacts],
                "optional_renderer_artifacts": [str(path) for path in renderer_artifacts],
                **({"target_binding_contract": target_binding_contract}
                   if target_binding_contract is not None else {}),
                **({"motion_design": motion_request} if motion_request is not None else {}),
                **({"renderer_evidence": {
                    "contract_output": str(self.renderer_evidence_contract_path("sample")),
                    "project_manifest": str(self.renderer_project_manifest_path("sample")),
                    "renderer_export": str(self.renderer_export_path("sample")),
                    "keyframe_receipt_directory": str(self.keyframe_receipt_dir("sample")),
                    "preview_render_parity": str(self.motion_parity_path("sample")),
                    "required_phases": ["entrance", "mid", "pre_exit", "post_exit"],
                    "actual_runtime_export_required": True,
                    **self._runtime_capture_request("sample"),
                }} if motion_quality_enabled else {}),
                **({} if motion_quality_enabled else {"minimum_distinct_sample_structures": 4}),
                "forbidden": list(FORBIDDEN_NEW_PATHS[2:]),
            })
            self._action_required(
                "hyperframes_storyboard",
                "HyperFrames-authored storyboard and composition are required",
                [{"owner": "hyperframes", "capability": "creative direction, storyboard and animation",
                  "request": str(packet), "expected_project": str(project)}],
            )
        storyboard = read_json(storyboard_path)
        assert_valid(validate_storyboard(storyboard, brief), "HyperFrames storyboard")
        binding_artifacts: list[Path] = []
        renderer_evidence_artifacts: list[Path] = []
        if motion_quality_enabled:
            assert_valid(
                validate_storyboard_motion_binding(storyboard, motion_contract or {}),
                "sample motion-design binding",
            )
            assert_valid(
                validate_storyboard_bindings(storyboard, self.sample_target_binding_dir),
                "sample target bindings",
            )
            binding_artifacts = sorted(self.sample_target_binding_dir.glob("*.json"))
            renderer_evidence_artifacts.append(self._write_renderer_evidence_contract(
                scope="sample", motion_contract=motion_contract or {},
                storyboard_path=storyboard_path,
            ))
        assert_valid(
            validate_visual_vocabulary_audit(
                read_json(vocabulary_path), storyboard,
                decision_complete=motion_quality_enabled,
            ),
            "sample visual vocabulary audit",
        )
        commands = {
            "scope": "sample_only",
            "check": {"cwd": str(project), "argv": ["npx", "hyperframes", "check", ".", "--json"]},
            "preview": {"cwd": str(project), "argv": ["npx", "hyperframes", "preview", "."]},
            "sample_snapshots": {
                "cwd": str(project),
                "argv": ["npx", "hyperframes", "snapshot", ".", "--all-comps"],
            },
            "render_authority": "not_a_final_project",
        }
        command_path = self.root / "hyperframes-commands.json"
        write_json(command_path, commands)
        snapshot_plan_path = project / "motion-snapshot-plan.json"
        motion_sidecar_path = project / "motion.json"
        snapshot_plan = build_motion_snapshot_plan(
            storyboard,
            motion_design_contract=motion_contract if motion_quality_enabled else None,
            recipe_registry=(
                load_recipe_registry(DEFAULT_RECIPE_REGISTRY) if motion_quality_enabled else None
            ),
        )
        write_json(snapshot_plan_path, snapshot_plan)
        write_json(motion_sidecar_path, build_motion_sidecar(snapshot_plan))
        project_manifest_path = self.renderer_project_manifest_path("sample")
        if motion_quality_enabled:
            build_renderer_project_manifest(project, project_manifest_path)
        self._complete("hyperframes_storyboard", [storyboard_path, vocabulary_path, index_path,
                                                    command_path, route_path, snapshot_plan_path,
                                                    motion_sidecar_path, *ip_artifacts,
                                                    *renderer_artifacts, self.adaptive_layout_path,
                                                    *binding_artifacts, *motion_design_artifacts,
                                                    *renderer_evidence_artifacts,
                                                    *([project_manifest_path]
                                                      if motion_quality_enabled else [])])

    def stage_audio(self) -> None:
        path = self.root / "audio-contract.json"
        if not path.is_file():
            write_json(path, {
                "schema_version": 2,
                "owner": "director",
                "speech_dominant": True,
                "bgm": {"optional": True, "enabled_by_default_when_authorized_asset_exists": True,
                        "duck_under_speech": True,
                        "embedded_source_requires_measured_presence": True},
                "sfx": {"must_match_motion": True, "decision_required_per_nonquiet_event": True,
                        "audibility_measurement_required": True,
                        "silence_requires_event_specific_reason": True},
                "final_mix_owner": "ffmpeg",
            })
        artifacts = [path]
        storyboard = self.sample_hyperframes_project / "storyboard.json"
        audio_plan = self.sample_hyperframes_project / "audio-plan.json"
        production_request = self.root / "audio-production-request.json"
        if audio_plan.is_file():
            artifacts.append(audio_plan)
        elif (self.project.get("audio", {}).get("production", {}).get("enabled") is True
              and storyboard.is_file() and self.execute_external):
            producer = lambda: produce_audio_assets(
                storyboard=storyboard, project=self.project, project_root=self.context.root,
                output_dir=self.context.edit_dir / "audio", source_audio=self.context.source_video,
                runner=self.adapter_runner, semantic_brief=self.semantic_brief_path,
            )
            bgm = self.project.get("audio", {}).get("bgm", {})
            bgm_enabled = bgm.get("enabled", bgm.get("enabled_by_default", True)) is True
            bgm_asset = None
            if bgm.get("asset"):
                configured_asset = Path(str(bgm["asset"]))
                bgm_asset = (
                    configured_asset.resolve()
                    if configured_asset.is_absolute()
                    else (self.context.root / configured_asset).resolve()
                )
            external_bgm = (
                bgm_enabled
                and not (bgm_asset and bgm_asset.is_file())
                and any(
                    isinstance(row, dict) and row.get("enabled") is True
                    for row in (bgm.get("provider_chain") or [])
                )
            )
            if external_bgm:
                artifacts.extend(self._metered_provider_call(("bgm",), producer, stage="audio"))
            else:
                artifacts.extend(producer())
        else:
            write_json(production_request, {
                "schema_version": 1,
                "storyboard": str(storyboard),
                "expected_audio_plan": str(audio_plan),
                "sfx": "generate semantic-event-specific multi-note assets; preserve intentionally_silent decisions",
                "bgm": "approved local -> configured media-use/HeyGen -> MiniMax -> local MusicGen; stop after first success",
                "paid_provider_calls_require_explicit_authorization": True,
                "execute_with": "run/resume using --execute-external or the deliver command",
            })
            artifacts.append(production_request)
        if (audio_plan.is_file() and storyboard.is_file() and self.sample_candidate_raw_path.is_file()
                and self.execute_external):
            plan_payload = read_json(audio_plan)
            storyboard_payload = read_json(storyboard)
            if not isinstance(plan_payload, dict) or not isinstance(storyboard_payload, dict):
                plan_payload = {}
                storyboard_payload = {}
            decisions = (plan_payload.get("motion_sfx") or {}).get("event_decisions") or []
            mix_check = ((plan_payload.get("motion_sfx") or {}).get("mix_audibility_check") or {})
            expected_mix_evidence = self.creative_review_audio_dir.parent / "mix-audibility.json"
            declared_evidence = mix_check.get("evidence")
            declared_evidence_path = None
            if declared_evidence:
                candidate = Path(str(declared_evidence))
                declared_evidence_path = (
                    candidate.resolve()
                    if candidate.is_absolute()
                    else (audio_plan.parent / candidate).resolve()
                )
            mix_evidence_ready = False
            if (
                mix_check.get("status") == "pass"
                and declared_evidence_path == expected_mix_evidence.resolve()
                and expected_mix_evidence.is_file()
                and mix_check.get("evidence_sha256") == sha256_file(expected_mix_evidence)
            ):
                mix_evidence_ready = not validate_sample_audio_evidence(
                    audio_plan=audio_plan, storyboard=storyboard,
                    candidate_media=self.sample_candidate_raw_path,
                    evidence_path=expected_mix_evidence,
                    output_dir=self.creative_review_audio_dir,
                    expected_evidence_path=expected_mix_evidence,
                    declared_evidence_sha256=str(mix_check.get("evidence_sha256") or ""),
                )
            expected_auditions = []
            by_id = {
                str(event.get("id")): event
                for event in (storyboard_payload.get("events") or [])
                if isinstance(event, dict) and event.get("treatment") != "quiet_source"
            }
            for decision in decisions:
                event = by_id.get(str(decision.get("event_id"))) or {}
                stem = audition_filename_stem(
                    str(event.get("semantic_event_id") or decision.get("event_id"))
                )
                expected_auditions.extend([
                    self.creative_review_audio_dir / f"{stem}-sfx-off.wav",
                    self.creative_review_audio_dir / f"{stem}-sfx-on.wav",
                ])
            if decisions and (
                not mix_evidence_ready or any(not path.is_file() for path in expected_auditions)
            ):
                artifacts.extend(materialize_sample_audio_evidence(
                    storyboard=storyboard,
                    audio_plan=audio_plan,
                    candidate_media=self.sample_candidate_raw_path,
                    output_dir=self.creative_review_audio_dir,
                ))
            cue_decisions = [
                row for row in decisions
                if isinstance(row, dict) and row.get("decision") == "cue"
            ]
            if cue_decisions:
                mix_errors = ["sample review mix receipt is missing"]
                if self.sample_review_mix_receipt_path.is_file():
                    try:
                        mix_errors = validate_sample_review_mix_receipt(
                            read_json(self.sample_review_mix_receipt_path),
                            candidate_media=self.sample_candidate_raw_path,
                            audio_plan=audio_plan,
                            output=self.sample_candidate_sfx_path,
                        )
                    except (OSError, ValueError, json.JSONDecodeError) as error:
                        mix_errors = [f"sample review mix receipt cannot be validated: {error}"]
                if mix_errors:
                    materialize_sample_review_mix(
                        candidate_media=self.sample_candidate_raw_path,
                        audio_plan=audio_plan,
                        output=self.sample_candidate_sfx_path,
                        receipt_path=self.sample_review_mix_receipt_path,
                    )
                artifacts.extend([
                    self.sample_candidate_sfx_path,
                    self.sample_review_mix_receipt_path,
                ])
                perceptual = (
                    (self.project.get("audio") or {}).get("sfx", {}).get("perceptual") or {}
                )
                if perceptual.get("enabled") is True:
                    evidence_path = self.creative_review_audio_dir.parent / "mix-audibility.json"
                    license_path = self.sample_hyperframes_project / "audio-sfx-manifest.json"
                    motion_contract = self.motion_design_dir("sample") / "motion-design-contract.json"
                    required_motion_audio = [evidence_path, license_path, motion_contract]
                    if any(not item.is_file() for item in required_motion_audio):
                        self._action_required(
                            "audio",
                            "Perceptual motion-audio contracts require measured mix, license, and motion-design evidence",
                            [{"owner": "director_audio", "missing_artifacts": [
                                str(item) for item in required_motion_audio if not item.is_file()
                            ]}],
                        )
                    artifacts.extend(materialize_motion_audio_decisions(
                        motion_design_contract=motion_contract,
                        audio_plan=audio_plan,
                        source_audio=self.context.source_video,
                        final_mix=self.sample_candidate_sfx_path,
                        perceptual_evidence=evidence_path,
                        license_evidence=license_path,
                        audio_policy=perceptual,
                        output_dir=self.motion_audio_decision_manifest_path.parent,
                    ))
        if (self.root / "adapter-state.json").is_file():
            artifacts.append(self.root / "adapter-state.json")
        validation_errors: list[str] = []
        audio_assets: list[Path] = []
        if not storyboard.is_file():
            validation_errors.append("sample storyboard is missing")
        elif not audio_plan.is_file():
            validation_errors.append("sample audio plan is missing")
        else:
            try:
                audio_plan_payload = read_json(audio_plan)
                storyboard_payload = read_json(storyboard)
                if not isinstance(audio_plan_payload, dict):
                    validation_errors.append("sample audio plan must be a JSON object")
                    audio_plan_payload = {}
                if not isinstance(storyboard_payload, dict):
                    validation_errors.append("sample storyboard must be a JSON object")
                    storyboard_payload = {}
                validation_errors.extend(validate_audio_plan(
                    audio_plan_payload, storyboard_payload, self.project,
                    base_dir=self.sample_hyperframes_project,
                ))
                decisions = ((audio_plan_payload.get("motion_sfx") or {}).get(
                    "event_decisions"
                ) or [])
                if any(
                    isinstance(row, dict) and row.get("decision") == "cue"
                    for row in decisions
                ):
                    audibility = ((audio_plan_payload.get("motion_sfx") or {}).get(
                        "mix_audibility_check"
                    ) or {})
                    evidence_value = audibility.get("evidence")
                    evidence_path = Path(str(evidence_value or ""))
                    evidence_path = (
                        evidence_path.resolve() if evidence_path.is_absolute()
                        else (audio_plan.parent / evidence_path).resolve()
                    )
                    validation_errors.extend(validate_sample_audio_evidence(
                        audio_plan=audio_plan, storyboard=storyboard,
                        candidate_media=self.sample_candidate_raw_path,
                        evidence_path=evidence_path,
                        output_dir=self.creative_review_audio_dir,
                        expected_evidence_path=(
                            self.creative_review_audio_dir.parent / "mix-audibility.json"
                        ),
                        declared_evidence_sha256=str(audibility.get("evidence_sha256") or ""),
                    ))
                if not validation_errors:
                    audio_assets = _audio_plan_asset_files(
                        audio_plan_payload, self.sample_hyperframes_project,
                    )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                validation_errors.append(f"sample audio plan cannot be validated: {error}")
        readiness_path = self.root / "audio-readiness.json"
        readiness = "asset_ready" if not validation_errors else "contract_ready"
        write_json(readiness_path, {
            "schema_version": 1,
            "status": readiness,
            "storyboard": str(storyboard.resolve()),
            "storyboard_sha256": sha256_file(storyboard) if storyboard.is_file() else None,
            "audio_plan": str(audio_plan.resolve()),
            "audio_plan_sha256": sha256_file(audio_plan) if audio_plan.is_file() else None,
            "asset_records": [
                {"path": str(asset), "sha256": sha256_file(asset)} for asset in audio_assets
            ],
            "validation_errors": validation_errors,
        })
        artifacts.extend([readiness_path, self.sample_candidate_raw_path, *audio_assets])
        self._complete(
            "audio", artifacts,
            readiness=readiness,
        )

    def stage_cover(self) -> None:
        path = self.root / "cover-contract.json"
        if not path.is_file():
            write_json(path, {
                "schema_version": 2,
                "owner": "director",
                "default_aspect": "9:16",
                "routes": [
                    "reference_regenerated", "authentic_frame_editorial", "real_person_ip_hybrid",
                ],
                "default_identity": "multi-photo reference-guided regeneration; no generic pasted cutout",
                "expression": "natural eye contact, credible slight smile, open posture, visible energy",
                "topic_scene_required": True,
                "semantic_cover_direction_required_when_editorial_enabled": True,
                "deterministic_local_typography": True,
                "template_families": [
                    "cinematic_editorial", "bright_tech_tutorial",
                    "dark_high_energy", "thought_leadership_ip",
                ],
                "automated_candidate_qa": [
                    "semantic evidence", "native 9:16", "safe bounds", "subject avoidance",
                    "thumbnail text size", "supporting asset provenance",
                ],
                "user_identity_approval_remains_distinct": True,
            })
        cover_config = self.project.get("cover", {})
        if cover_config.get("enabled", True) is False:
            decision = self.root / "cover-decision.json"
            write_json(decision, {"schema_version": 1, "status": "disabled",
                                  "reason": "project explicitly disabled cover production"})
            self._complete("cover", [path, decision], readiness="not_applicable")
            return
        if cover_config.get("production", {}).get("enabled") is not True:
            self._complete("cover", [path], readiness="contract_ready")
            return
        prepared_project = self.project
        reference_artifacts: list[Path] = []
        try:
            prepared_project, reference_artifacts = prepare_cover_reference_pack(
                self.project,
                project_root=self.context.root,
                semantic_brief=self.semantic_brief_path,
                work_dir=self.context.edit_dir / "cover" / "reference-pack",
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            request = self.root / "cover-reference-pack-request.json"
            write_json(request, {
                "schema_version": 1,
                "status": "action_required",
                "reason": str(error),
                "required": [
                    "authorized non-revoked multi-photo manifest",
                    "at least two distinct identity references",
                    "target expression and role coverage",
                ],
                "privacy": "keep reference paths and photos local; only public projection may be shared",
            })
            self._action_required(
                "cover",
                "Authorized private cover reference pack requires repair",
                [{"owner": "user_or_director_asset_curator", "request": str(request)}],
            )
        configured = self.project.get("delivery", {}).get("cover", "exports/cover-portrait.png")
        output = self._project_path(configured)
        try:
            artifacts = self._metered_provider_call(
                ("image_generation",),
                lambda: produce_cover(
                    project=prepared_project, project_root=self.context.root,
                    semantic_brief=self.semantic_brief_path, output=output,
                    work_dir=self.context.edit_dir / "cover", runner=self.adapter_runner,
                    execute_external=self.execute_external,
                ),
                stage="cover",
            )
        except CoverProductionActionRequired as error:
            request = write_cover_request(self.root / "cover-production-request.json", error.packet)
            self._action_required(
                "cover",
                "Evidence-bound cover plan, clean bases, template QA, or reviews are required",
                [{"owner": "director_with_image_generation_and_visual_review",
                  "request": str(request), "expected_artifact": str(output)}],
            )
        self._complete("cover", [path, *reference_artifacts, *artifacts], readiness="asset_ready")

    def stage_sample_qa(self) -> None:
        self._validate_current_production_contract()
        caption_review_artifacts = self._ensure_sample_caption_delivery()
        promise_closure = self._ensure_editorial_promise_closure()
        review_path = self.root / "sample-qa" / "aesthetic-review.json"
        storyboard_path = self.sample_hyperframes_project / "storyboard.json"
        audio_plan_path = self.sample_hyperframes_project / "audio-plan.json"
        storyboard = read_json(storyboard_path)
        motion_quality_enabled = self.project.get("motion_quality", {}).get("enabled") is True
        motion_errors: list[str] = []
        motion_artifacts: list[Path] = []
        if motion_quality_enabled:
            motion_errors, motion_artifacts = self._validate_motion_render_evidence(
                scope="sample", storyboard=storyboard,
            )
        if not review_path.is_file() or not audio_plan_path.is_file() or motion_errors:
            packet = self.root / "sample-qa-request.json"
            write_json(packet, {
                "schema_version": 3 if motion_quality_enabled else 2,
                "owner": "director_with_human_level_visual_review",
                "sample_duration_seconds": [60, 90],
                "storyboard": str(storyboard_path),
                "audio_plan": str(audio_plan_path),
                "required_snapshots_per_event": ["entrance", "midpoint", "pre_exit", "post_exit"],
                "required_checks": [
                    "caption sync", "overlap", "overflow", "content relevance", "actual keyword focus",
                    "visual structure diversity", "motion rhythm", "UI/face/cursor safety",
                    "connector endpoints", "SFX event decisions", "SFX audibility", "BGM presence or provenance",
                    "replayable connector/target measurements", "composited overlay contrast over source footage",
                ],
                "missing_artifacts": [str(path) for path in (review_path, audio_plan_path) if not path.is_file()],
                **({
                    "renderer_evidence_errors": motion_errors,
                    "renderer_evidence_contract": str(
                        self.renderer_evidence_contract_path("sample")
                    ),
                    "renderer_export": str(self.renderer_export_path("sample")),
                    "keyframe_receipt_directory": str(self.keyframe_receipt_dir("sample")),
                    "preview_render_parity": str(self.motion_parity_path("sample")),
                } if motion_quality_enabled else {}),
                "output": str(review_path),
            })
            self._action_required(
                "sample_qa",
                "Evidence-backed 60-90 second sample QA is required; tests alone are not aesthetic approval",
                [{"owner": "director_with_visual_review", "request": str(packet),
                  "expected_artifact": str(review_path)}],
            )
        review = read_json(review_path)
        keyframe_receipts: dict[str, Path] | None = None
        if motion_quality_enabled:
            keyframe_receipts = {
                str(read_json(path).get("event_id") or ""): path.resolve()
                for path in sorted(self.keyframe_receipt_dir("sample").glob("*.json"))
            }
        errors = validate_aesthetic_review(
            review, storyboard, keyframe_receipt_paths=keyframe_receipts,
            decision_complete=motion_quality_enabled,
        )
        assert_valid(errors, "sample aesthetic QA")
        assert_valid(
            validate_audio_plan(
                read_json(audio_plan_path),
                storyboard,
                self.project,
                base_dir=self.sample_hyperframes_project,
            ),
            "sample audio QA",
        )
        dynamics_path = self.root / "sample-qa" / "visual-dynamics-qa.json"
        dynamics_config = self.project.get("qa", {}).get("visual_dynamics", {})
        dynamics = build_visual_dynamics_report(
            storyboard_path=storyboard_path,
            semantic_brief_path=self.semantic_brief_path,
            config=dynamics_config,
            production_contract_path=self.production_contract_path,
            renderer_export_path=(
                self.renderer_export_path("sample") if motion_quality_enabled else None
            ),
            keyframe_receipt_paths=keyframe_receipts,
        )
        write_json(dynamics_path, dynamics)
        assert_valid(
            validate_visual_dynamics_report(
                dynamics, storyboard_path, self.semantic_brief_path,
                config=dynamics_config,
                production_contract_path=self.production_contract_path,
                renderer_export_path=(
                    self.renderer_export_path("sample") if motion_quality_enabled else None
                ),
                keyframe_receipt_paths=keyframe_receipts,
            ),
            "sample visual dynamics QA",
        )
        if (
            dynamics_config.get("enabled", True) is True
            and dynamics_config.get("blocking", True) is True
            and dynamics.get("status") != "pass"
        ):
            raise DirectorContractError("sample visual dynamics QA failed")
        report_path = self.root / "sample-qa" / "gate-report.json"
        write_json(report_path, {
            "schema_version": 2, "passed": True,
            "storyboard": str(storyboard_path), "storyboard_sha256": sha256_file(storyboard_path),
            "review": str(review_path), "review_sha256": sha256_file(review_path),
            "audio_plan": str(audio_plan_path), "audio_plan_sha256": sha256_file(audio_plan_path),
            "visual_dynamics": str(dynamics_path),
            "visual_dynamics_sha256": sha256_file(dynamics_path),
            "motion_render_evidence": (
                {"status": "pass", "artifact_count": len(motion_artifacts)}
                if motion_quality_enabled else {"status": "disabled"}
            ),
            "errors": [],
        })
        self._complete("sample_qa", [storyboard_path, review_path, audio_plan_path, dynamics_path,
                                     report_path,
                                     *caption_review_artifacts,
                                     *([promise_closure] if promise_closure is not None else []),
                                     *_review_evidence_files(review), *motion_artifacts])

    def _creative_review_receipts(self) -> dict[str, Path]:
        receipts: dict[str, Path] = {}
        for path in sorted(self.keyframe_receipt_dir("sample").glob("*.json")):
            try:
                event_id = str(read_json(path).get("event_id") or "")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if event_id:
                receipts[event_id] = path.resolve()
        return receipts

    def _creative_review_audio_auditions(
        self, event_ids: list[str],
    ) -> tuple[dict[str, dict[str, Path]], list[str]]:
        auditions: dict[str, dict[str, Path]] = {}
        missing: list[str] = []
        for event_id in event_ids:
            rows: dict[str, Path] = {}
            file_stem = audition_filename_stem(event_id)
            for name in ("sfx_off", "sfx_on", "bgm_off", "bgm_on"):
                stem = f"{file_stem}-{name.replace('_', '-')}"
                path = next(
                    (candidate.resolve() for suffix in (".wav", ".mp3", ".m4a", ".aac")
                     if (candidate := self.creative_review_audio_dir / f"{stem}{suffix}").is_file()),
                    None,
                )
                if path is not None:
                    rows[name] = path
            if "sfx_off" not in rows or "sfx_on" not in rows:
                missing.append(
                    str(self.creative_review_audio_dir / f"{event_id}-sfx-off|sfx-on.(wav|mp3|m4a|aac)")
                )
            auditions[event_id] = rows
        return auditions, missing

    def _ensure_creative_review(self) -> list[Path]:
        motion_contract_path = self.motion_design_dir("sample") / "motion-design-contract.json"
        storyboard_path = self.sample_hyperframes_project / "storyboard.json"
        audio_plan_path = self.sample_hyperframes_project / "audio-plan.json"
        gate_paths = [
            self.root / "sample-qa" / "gate-report.json",
            self.root / "sample-qa" / "aesthetic-review.json",
            self.root / "sample-qa" / "visual-dynamics-qa.json",
            self.motion_parity_path("sample"),
        ]
        receipts = self._creative_review_receipts()
        motion_contract = read_json(motion_contract_path) if motion_contract_path.is_file() else {}
        event_ids = [str(value) for value in motion_contract.get("selected_event_ids") or []]
        auditions, missing_auditions = self._creative_review_audio_auditions(event_ids)
        required = [
            self.sample_baseline_path, self.sample_candidate_path, motion_contract_path,
            storyboard_path, self.semantic_brief_path, audio_plan_path, *gate_paths,
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if set(receipts) != set(event_ids):
            missing.append(str(self.keyframe_receipt_dir("sample") / "<every-event>.json"))
        missing.extend(missing_auditions)
        request_path = self.root / "sample-qa" / "creative-review-request.json"
        if missing:
            write_json(request_path, {
                "schema_version": 1,
                "owner": "hyperframes_audio_and_director_review",
                "purpose": "materialize a paired baseline/candidate review without a long render",
                "baseline": str(self.sample_baseline_path),
                "candidate": str(self.sample_candidate_path),
                "candidate_requirement": "actual 60-90 second HyperFrames sample render",
                "motion_design_contract": str(motion_contract_path),
                "keyframe_receipts": str(self.keyframe_receipt_dir("sample")),
                "audio_audition_directory": str(self.creative_review_audio_dir),
                "audio_audition_naming": "<event-id>-sfx-off/on and optional bgm-off/on",
                "required_event_ids": event_ids,
                "missing": missing,
                "output": str(self.creative_review_path),
                "user_decision_default": "pending",
                "request_metadata_is_not_review_evidence": True,
            })
            self._action_required(
                "preview_approval",
                "Paired baseline/candidate media, four-phase evidence, and audio auditions are required",
                [{
                    "owner": "hyperframes_audio_and_director_review",
                    "request": str(request_path),
                    "expected_outputs": [str(self.sample_candidate_path), str(self.creative_review_path)],
                }],
            )
        if not self.creative_review_path.is_file():
            try:
                baseline_duration = _ffprobe_duration(self.sample_baseline_path)
                candidate_duration = _ffprobe_duration(self.sample_candidate_path)
                duration_errors = validate_sample_pair_durations(
                    baseline_duration, candidate_duration,
                )
                if duration_errors:
                    raise ValueError("; ".join(duration_errors))
                build_creative_review_contract(
                    project_id=str(self.project.get("video_id") or self.context.root.name),
                    baseline_path=self.sample_baseline_path,
                    candidate_path=self.sample_candidate_path,
                    baseline_duration_seconds=baseline_duration,
                    candidate_duration_seconds=candidate_duration,
                    motion_design_contract_path=motion_contract_path,
                    storyboard_path=storyboard_path,
                    semantic_brief_path=self.semantic_brief_path,
                    keyframe_receipt_paths=receipts,
                    gate_report_paths=gate_paths,
                    audio_auditions=auditions,
                    motion_audio_decisions_path=self.creative_review_motion_audio_path,
                    output=self.creative_review_path,
                )
            except (
                OSError, ValueError, json.JSONDecodeError, DirectorContractError,
                subprocess.CalledProcessError,
            ) as error:
                write_json(request_path, {
                    "schema_version": 1,
                    "owner": "director_with_media_review",
                    "reason": str(error),
                    "output": str(self.creative_review_path),
                    "user_decision_default": "pending",
                })
                self._action_required(
                    "preview_approval", "Paired creative-review contract could not be built",
                    [{"owner": "director_with_media_review", "request": str(request_path)}],
                )
        review = read_json(self.creative_review_path)
        errors = validate_creative_review(
            review,
            motion_design_contract_path=motion_contract_path,
            storyboard_path=storyboard_path,
            keyframe_receipt_paths=receipts,
            motion_audio_decisions_path=self.creative_review_motion_audio_path,
        )
        if errors:
            write_json(self.creative_review_path, mark_creative_review_stale(review, errors))
            write_json(request_path, {
                "schema_version": 1, "owner": "director_with_media_review",
                "reason": "creative review is stale or invalid", "errors": errors,
                "output": str(self.creative_review_path),
            })
            self._action_required(
                "preview_approval", "Paired creative-review evidence is stale or invalid",
                [{"owner": "director_with_media_review", "request": str(request_path)}],
            )
        dashboard = generate_dashboard(
            project_root=self.context.root,
            director_root=self.root,
            output=self.creative_review_dashboard_path,
            creative_review_path=self.creative_review_path,
            motion_design_contract_path=motion_contract_path,
        )
        return [
            self.creative_review_path, dashboard, self.sample_baseline_path,
            self.sample_candidate_path, *receipts.values(),
            *[path for rows in auditions.values() for path in rows.values()],
        ]

    def stage_preview_approval(self) -> None:
        approval = self.root / "preview-approval.json"
        storyboard = self.sample_hyperframes_project / "storyboard.json"
        review = self.root / "sample-qa" / "aesthetic-review.json"
        gate = self.root / "sample-qa" / "gate-report.json"
        motion_quality_enabled = self.project.get("motion_quality", {}).get("enabled") is True
        creative_artifacts: list[Path] = []
        if motion_quality_enabled:
            creative_artifacts = self._ensure_creative_review()
            paired_review = read_json(self.creative_review_path)
            if (
                paired_review.get("status") != "approved"
                or (paired_review.get("user_review") or {}).get("decision") != "approved"
            ):
                self._action_required(
                    "preview_approval",
                    "User paired creative approval is required before any full HyperFrames render",
                    [{
                        "owner": "user",
                        "capability": "paired baseline/candidate creative approval",
                        "dashboard": str(self.creative_review_dashboard_path),
                        "expected_artifact": str(self.creative_review_path),
                        "command": [
                            sys.executable, str(Path(__file__).resolve()), "approve-sample",
                            "--project", str(self.context.project_file),
                            "--approved-by", "<human-name>",
                            "--publish-willingness", "yes|no|unsure",
                            "--preference", "baseline|candidate|tie",
                            "--review-reason", "<why-the-candidate-is-or-is-not-publishable>",
                        ],
                    }],
                )
        if not approval.is_file():
            self._action_required(
                "preview_approval",
                "User approval is required before any full HyperFrames render",
                [{"owner": "user", "capability": "sample approval", "expected_artifact": str(approval),
                  "command": [sys.executable, str(Path(__file__).resolve()), "approve-sample",
                              "--project", str(self.context.project_file)],
                  "note": "Current request explicitly pauses full video rendering."}],
            )
        row = read_json(approval)
        if row.get("approved") is not True or not str(row.get("approved_by", "")).strip():
            raise DirectorContractError("sample approval must record an explicit approver")
        evidence = {
            "storyboard_sha256": storyboard,
            "aesthetic_review_sha256": review,
            "gate_report_sha256": gate,
        }
        if motion_quality_enabled:
            evidence["creative_review_sha256"] = self.creative_review_path
        for field, path in evidence.items():
            if not path.is_file() or row.get(field) != sha256_file(path):
                raise DirectorContractError(
                    f"sample approval is stale: {field} does not match the current approved evidence"
                )
        if self.project.get("editorial_regression", {}).get("enabled") is True:
            baseline = self.root / "editorial-regression" / "golden-baseline.json"
            if (
                not baseline.is_file()
                or row.get("golden_baseline") != str(baseline)
                or row.get("golden_baseline_sha256") != sha256_file(baseline)
            ):
                raise DirectorContractError("sample approval is stale: golden editorial baseline")
            assert_valid(validate_baseline(read_json(baseline)), "golden editorial baseline")
        artifacts = [approval, *creative_artifacts]
        if self.project.get("editorial_regression", {}).get("enabled") is True:
            baseline_path = self.root / "editorial-regression" / "golden-baseline.json"
            artifacts.append(baseline_path)
            cover_input = ((read_json(baseline_path).get("inputs") or {}).get("cover_plan") or {})
            if cover_input.get("path"):
                artifacts.append(Path(str(cover_input["path"])).resolve())
        self._complete("preview_approval", artifacts)

    def _expected_timeline_duration(self) -> float:
        edl = read_json(self.video_use_dir / "edl.json")
        return sum(float(row["end"]) - float(row["start"]) for row in (edl.get("ranges") or []))

    def stage_full_hyperframes_storyboard(self) -> None:
        project = self.full_hyperframes_project
        full_brief_path = self.full_semantic_brief_path
        motion_quality_enabled = self.project.get("motion_quality", {}).get("enabled") is True
        target_binding_contract = None
        motion_design_artifacts: list[Path] = []
        motion_contract: dict[str, Any] | None = None
        if motion_quality_enabled:
            self.full_target_binding_dir.mkdir(parents=True, exist_ok=True)
            target_binding_contract = _target_binding_request_contract(
                layout_path=self.adaptive_layout_path,
                binding_dir=self.full_target_binding_dir,
                schema_path=Path(__file__).parents[1] / "references" / "p0-p2-design"
                / "schemas" / "target-binding.schema.json",
                identity_mode=str((self.project.get("identity") or {}).get("mode") or "generic"),
            )
            if not full_brief_path.is_file():
                packet = self.root / "full-semantic-brief-request.json"
                write_json(packet, {
                    "schema_version": 3,
                    "owner": "director_with_llm",
                    "scope": "complete output timeline",
                    "approved_sample_semantic_brief": str(self.semantic_brief_path),
                    "video_use_edl": str(self.video_use_dir / "edl.json"),
                    "evidence_bundle": str(self.evidence_bundle_path),
                    "required_output": str(full_brief_path),
                    "opportunity_model": "decision_complete_v1",
                    "hyperframes_authoring_allowed": False,
                })
                self._action_required(
                    "full_hyperframes_storyboard",
                    "A decision-complete full semantic brief is required before motion compilation",
                    [{"owner": "director_with_llm", "request": str(packet),
                      "expected_artifact": str(full_brief_path)}],
                )
            motion_contract, motion_design_artifacts = self._ensure_motion_design(
                scope="full", brief_path=full_brief_path,
                binding_dir=self.full_target_binding_dir,
            )
        motion_request = (
            self._motion_design_request("full", motion_contract)
            if motion_contract is not None else None
        )
        renderer_route_path = self.root / "renderer-route.json"
        if motion_contract is not None:
            renderer_route_path = self.root / "full-renderer-route.json"
            write_json(
                renderer_route_path,
                route_hyperframes(
                    self.project, read_json(self.evidence_bundle_path),
                    motion_design_contract=motion_contract,
                ),
            )
            motion_design_artifacts.append(renderer_route_path)
        storyboard_path = project / "storyboard.json"
        vocabulary_path = project / "visual-vocabulary-audit.json"
        index_path = project / "index.html"
        frame_path = project / "frame.md"
        required = (storyboard_path, vocabulary_path, index_path, frame_path)
        if not full_brief_path.is_file() or any(not path.is_file() for path in required):
            packet = self.root / "full-hyperframes-request.json"
            write_json(packet, {
                "schema_version": 3 if motion_quality_enabled else 2,
                "owner": "hyperframes",
                "scope": "complete output timeline; never copy the sample duration as the final duration",
                "approved_sample_project": str(self.sample_hyperframes_project),
                "approved_sample_semantic_brief": str(self.semantic_brief_path),
                "full_semantic_brief": str(full_brief_path),
                "semantic_inheritance": _semantic_inheritance_contract(
                    read_json(full_brief_path) if full_brief_path.is_file() else {"events": []},
                    motion_quality_enabled=motion_quality_enabled,
                ),
                "video_use_edl": str(self.video_use_dir / "edl.json"),
                "video_use_captions": str(self.video_use_dir / "captions.json"),
                "expected_duration_seconds": self._expected_timeline_duration(),
                "project": str(project),
                "renderer_route": str(renderer_route_path),
                "required_outputs": [
                    full_brief_path.name, *[path.name for path in required],
                    *(["renderer-export.json", "keyframe-receipts/*.json"]
                      if motion_quality_enabled else []),
                ],
                "required_skills": (
                    motion_request["required_hyperframes_skills"] if motion_request else
                    ["hyperframes", "hyperframes-core", "hyperframes-creative",
                     "hyperframes-animation", "hyperframes-cli"]
                ),
                **({"target_binding_contract": target_binding_contract}
                   if target_binding_contract is not None else {}),
                **({"motion_design": motion_request} if motion_request is not None else {}),
                **({"renderer_evidence": {
                    "contract_output": str(self.renderer_evidence_contract_path("full")),
                    "project_manifest": str(self.renderer_project_manifest_path("full")),
                    "renderer_export": str(self.renderer_export_path("full")),
                    "keyframe_receipt_directory": str(self.keyframe_receipt_dir("full")),
                    "preview_render_parity": str(self.motion_parity_path("full")),
                    "required_phases": ["entrance", "mid", "pre_exit", "post_exit"],
                    "actual_runtime_export_required": True,
                    **self._runtime_capture_request("full"),
                }} if motion_quality_enabled else {}),
                "forbidden": ["sample project reused as final", *FORBIDDEN_NEW_PATHS],
            })
            self._action_required(
                "full_hyperframes_storyboard",
                "A separate full-duration HyperFrames project is required after sample approval",
                [{"owner": "hyperframes", "capability": "full storyboard and composition",
                  "request": str(packet), "expected_project": str(project)}],
            )
        if project.resolve() == self.sample_hyperframes_project.resolve():
            raise DirectorContractError("sample and full HyperFrames projects must be different directories")
        full_brief = read_json(full_brief_path)
        if motion_quality_enabled and not is_decision_complete_brief(full_brief):
            raise DirectorContractError(
                "enabled motion quality requires a schema 3 decision-complete full semantic brief"
            )
        assert_valid(validate_semantic_brief(full_brief), "full semantic brief")
        expected_duration = self._expected_timeline_duration()
        scope = full_brief.get("scope") or {}
        try:
            scope_start = float(scope.get("source_start"))
            scope_end = float(scope.get("source_end"))
        except (TypeError, ValueError):
            raise DirectorContractError("full semantic brief requires numeric source_start/source_end scope")
        if scope_start > 0.1 or scope_end < expected_duration * 0.95:
            raise DirectorContractError(
                "full semantic brief does not cover at least 95% of the video-use output timeline"
            )
        transcript_path = self.video_use_dir / "transcripts" / f"{self.context.source_video.stem}.json"
        assert_valid(validate_semantic_evidence_binding(
            full_brief, transcript_path=transcript_path,
            evidence_bundle_path=self.evidence_bundle_path,
        ), "full semantic brief evidence binding")
        storyboard = read_json(storyboard_path)
        assert_valid(validate_storyboard(storyboard, full_brief), "full HyperFrames storyboard")
        binding_artifacts: list[Path] = []
        renderer_evidence_artifacts: list[Path] = []
        if motion_quality_enabled:
            assert_valid(
                validate_storyboard_motion_binding(storyboard, motion_contract or {}),
                "full motion-design binding",
            )
            assert_valid(
                validate_storyboard_bindings(storyboard, self.full_target_binding_dir),
                "full target bindings",
            )
            binding_artifacts = sorted(self.full_target_binding_dir.glob("*.json"))
            renderer_evidence_artifacts.append(self._write_renderer_evidence_contract(
                scope="full", motion_contract=motion_contract or {},
                storyboard_path=storyboard_path,
            ))
        assert_valid(
            validate_visual_vocabulary_audit(
                read_json(vocabulary_path), storyboard, full_video=True,
                decision_complete=motion_quality_enabled,
            ),
            "full-video visual vocabulary audit",
        )
        composition = storyboard.get("composition") or {}
        actual_duration = float(composition.get("duration", 0))
        if expected_duration <= 0 or actual_duration < expected_duration * 0.95:
            raise DirectorContractError(
                f"full HyperFrames duration {actual_duration:.3f}s does not cover the "
                f"video-use output timeline {expected_duration:.3f}s"
            )
        full_audio_plan = project / "audio-plan.json"
        audio_artifacts: list[Path] = []
        if not full_audio_plan.is_file() and self.execute_external:
            audio_artifacts = self._metered_provider_call(
                ("sfx", "bgm"),
                lambda: produce_audio_assets(
                    storyboard=storyboard_path, project=self.project, project_root=self.context.root,
                    output_dir=self.context.edit_dir / "audio", source_audio=self.context.source_video,
                    runner=self.adapter_runner,
                ),
                stage="full_hyperframes_storyboard",
            )
        motion_output = self.root / "render" / "full-hyperframes.mp4"
        commands = {
            "scope": "full_video_only",
            "check": {"cwd": str(project),
                      "argv": ["npx", "hyperframes", "check", ".", "--json", "--strict",
                               "--at-transitions", "--max-transition-samples=120",
                               "--frame-check=severity=error;seek=.25,.75;tol=4"]},
            "preview": {"cwd": str(project), "argv": ["npx", "hyperframes", "preview", "."]},
            "snapshots": {"cwd": str(project), "argv": ["npx", "hyperframes", "snapshot", ".", "--all-comps"]},
            "final_motion_render": {
                "cwd": str(project),
                "argv": ["npx", "hyperframes", "render", ".", "--quality", "high",
                         "--skill", "content-preserving-video-editor", "--output", str(motion_output)],
                "expected_artifact": str(motion_output),
            },
        }
        command_path = self.root / "full-hyperframes-commands.json"
        write_json(command_path, commands)
        snapshot_plan_path = project / "motion-snapshot-plan.json"
        motion_sidecar_path = project / "motion.json"
        snapshot_plan = build_motion_snapshot_plan(
            storyboard,
            motion_design_contract=motion_contract if motion_quality_enabled else None,
            recipe_registry=(
                load_recipe_registry(DEFAULT_RECIPE_REGISTRY) if motion_quality_enabled else None
            ),
        )
        write_json(snapshot_plan_path, snapshot_plan)
        write_json(motion_sidecar_path, build_motion_sidecar(snapshot_plan))
        project_manifest_path = self.renderer_project_manifest_path("full")
        if motion_quality_enabled:
            build_renderer_project_manifest(project, project_manifest_path)
        self._complete("full_hyperframes_storyboard", [full_brief_path, *required, command_path,
                                                        snapshot_plan_path, motion_sidecar_path,
                                                        *audio_artifacts, *binding_artifacts,
                                                        *motion_design_artifacts,
                                                        *renderer_evidence_artifacts,
                                                        *([project_manifest_path]
                                                          if motion_quality_enabled else [])])

    def stage_full_hyperframes_qa(self) -> None:
        qa_dir = self.root / "full-qa"
        check_path = qa_dir / "hyperframes-check.json"
        check_receipt_path = qa_dir / "hyperframes-check-receipt.json"
        snapshot_review_path = qa_dir / "snapshot-review.json"
        parity_path = qa_dir / "preview-render-parity.json"
        commands_path = self.root / "full-hyperframes-commands.json"
        commands = read_json(commands_path)
        toolchain_path = self.root / "toolchain-compatibility.json"
        storyboard_path = self.full_hyperframes_project / "storyboard.json"
        vocabulary_path = self.full_hyperframes_project / "visual-vocabulary-audit.json"
        check_command = commands["check"]
        motion_quality_enabled = self.project.get("motion_quality", {}).get("enabled") is True
        motion_evidence_artifacts: list[Path] = []
        self._validate_current_production_contract()

        def check_receipt_is_current() -> bool:
            if not check_path.is_file() or not check_receipt_path.is_file():
                return False
            try:
                candidate = read_json(check_receipt_path)
                bindings = {
                    "storyboard_sha256": storyboard_path,
                    "visual_vocabulary_sha256": vocabulary_path,
                    "commands_sha256": commands_path,
                    "toolchain_sha256": toolchain_path,
                    "check_report_sha256": check_path,
                    "stdout_sha256": Path(str(candidate.get("stdout_log", ""))),
                    "stderr_sha256": Path(str(candidate.get("stderr_log", ""))),
                }
                return (
                    candidate.get("status") == "pass"
                    and int(candidate.get("exit_code", -1)) == 0
                    and candidate.get("command_sha256") == _json_sha256(list(check_command["argv"]))
                    and candidate.get("cwd") == str(Path(check_command["cwd"]).resolve())
                    and all(path.is_file() and candidate.get(field) == sha256_file(path)
                            for field, path in bindings.items())
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return False

        if self.execute_external and not check_receipt_is_current():
            qa_dir.mkdir(parents=True, exist_ok=True)
            original_argv = list(check_command["argv"])
            resolved_argv = list(original_argv)
            resolved = shutil.which(resolved_argv[0])
            if resolved:
                resolved_argv[0] = resolved
            run = subprocess.run(
                resolved_argv, cwd=check_command["cwd"], capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            stdout_path = qa_dir / "hyperframes-check-stdout.log"
            stderr_path = qa_dir / "hyperframes-check-stderr.log"
            stdout_path.write_text(run.stdout or "", encoding="utf-8")
            stderr_path.write_text(run.stderr or "", encoding="utf-8")
            if run.returncode != 0:
                raise DirectorContractError("HyperFrames strict check command failed")
            try:
                check_payload = json.loads(run.stdout)
            except json.JSONDecodeError as error:
                raise DirectorContractError(
                    "HyperFrames strict check did not emit valid JSON"
                ) from error
            write_json(check_path, check_payload)
            if not toolchain_path.is_file():
                write_json(toolchain_path, build_toolchain_report())
            write_json(check_receipt_path, {
                "schema_version": 1, "owner": "director", "capability": "hyperframes_check",
                "status": "pass", "exit_code": run.returncode,
                "command": original_argv, "resolved_command": resolved_argv,
                "command_sha256": _json_sha256(original_argv),
                "cwd": str(Path(check_command["cwd"]).resolve()),
                "storyboard_sha256": sha256_file(storyboard_path),
                "visual_vocabulary_sha256": sha256_file(vocabulary_path),
                "commands_sha256": sha256_file(commands_path),
                "toolchain_sha256": sha256_file(toolchain_path),
                "check_report_sha256": sha256_file(check_path),
                "stdout_log": str(stdout_path), "stdout_sha256": sha256_file(stdout_path),
                "stderr_log": str(stderr_path), "stderr_sha256": sha256_file(stderr_path),
                "completed_at": utc_now(),
            })
        if (not check_path.is_file() or not check_receipt_path.is_file()
                or not snapshot_review_path.is_file() or not parity_path.is_file()):
            self._action_required(
                "full_hyperframes_qa",
                "The full HyperFrames project requires strict checks, reviewed snapshots, and preview/render parity before render",
                [{
                    "owner": "hyperframes_with_director_review",
                    "check_command": commands["check"],
                    "snapshot_command": commands["snapshots"],
                    "expected_artifacts": [str(check_path), str(check_receipt_path),
                                           str(snapshot_review_path), str(parity_path)],
                    "parity_scope": (
                        "Compare representative Studio/snapshot and short render evidence at identical times; "
                        "do not run the complete long render for this gate."
                    ),
                }],
            )
        receipt = read_json(check_receipt_path)
        receipt_bindings = {
            "storyboard_sha256": storyboard_path,
            "visual_vocabulary_sha256": vocabulary_path,
            "commands_sha256": commands_path,
            "toolchain_sha256": toolchain_path,
            "check_report_sha256": check_path,
            "stdout_sha256": Path(str(receipt.get("stdout_log", ""))),
            "stderr_sha256": Path(str(receipt.get("stderr_log", ""))),
        }
        if (
            receipt.get("schema_version") != 1
            or receipt.get("owner") != "director"
            or receipt.get("capability") != "hyperframes_check"
            or receipt.get("status") != "pass"
            or int(receipt.get("exit_code", -1)) != 0
            or receipt.get("command_sha256") != _json_sha256(list(check_command["argv"]))
            or receipt.get("cwd") != str(Path(check_command["cwd"]).resolve())
            or any(not path.is_file() or receipt.get(field) != sha256_file(path)
                   for field, path in receipt_bindings.items())
        ):
            raise DirectorContractError("HyperFrames strict-check execution receipt is missing or stale")
        check = read_json(check_path)
        if check.get("ok") is not True:
            raise DirectorContractError("full HyperFrames strict check did not pass")
        for section in ("lint", "runtime", "layout", "motion", "contrast"):
            row = check.get(section) or {}
            if row.get("ok") is not True or int(row.get("errorCount", 0)) != 0:
                raise DirectorContractError(f"full HyperFrames {section} check did not pass")
        if check.get("motion", {}).get("enabled") is not True:
            raise DirectorContractError("full HyperFrames motion-sidecar validation must be enabled")
        review = read_json(snapshot_review_path)
        if review.get("status") != "pass":
            raise DirectorContractError("full HyperFrames snapshot review did not pass")
        snapshot_paths = [Path(str(path)) for path in (review.get("reviewed_snapshots") or [])]
        if len(snapshot_paths) < 4 or any(not path.is_file() for path in snapshot_paths):
            raise DirectorContractError("full HyperFrames QA requires at least four existing reviewed snapshots")
        required_checks = {
            "content_relevance", "visual_variety", "overlap", "overflow",
            "caption_face_cursor_ui_safety", "motion_rhythm",
            "connector_target_geometry_measurement", "composite_readability",
        }
        review_checks = review.get("checks") or {}
        failed = sorted(name for name in required_checks if review_checks.get(name) != "pass")
        if failed:
            raise DirectorContractError("full HyperFrames snapshot review failed checks: " + ", ".join(failed))
        parity = read_json(parity_path)
        if motion_quality_enabled:
            motion_errors, motion_evidence_artifacts = self._validate_motion_render_evidence(
                scope="full", storyboard=read_json(storyboard_path),
            )
            if motion_errors:
                self._action_required(
                    "full_hyperframes_qa",
                    "Renderer-produced keyframe, DOM/geometry, and parity evidence must pass",
                    [{
                        "owner": "hyperframes_with_director_review",
                        "errors": motion_errors,
                        "renderer_evidence_contract": str(
                            self.renderer_evidence_contract_path("full")
                        ),
                        "expected_artifacts": [
                            str(self.renderer_export_path("full")),
                            str(self.keyframe_receipt_dir("full")),
                            str(parity_path),
                        ],
                    }],
                )
        else:
            assert_valid(
                validate_preview_render_parity(
                    parity,
                    read_json(self.full_hyperframes_project / "storyboard.json"),
                    configured_tolerances=self.project["qa"]["preview_render_parity"]["tolerances"],
                ),
                "HyperFrames preview/render parity",
            )
        parity_snapshots = [
            Path(str(sample[field])).resolve()
            for sample in parity.get("samples") or []
            for field in ("studio_snapshot", "render_snapshot")
            if sample.get(field)
        ]
        dynamics_path = qa_dir / "visual-dynamics-qa.json"
        dynamics_config = self.project.get("qa", {}).get("visual_dynamics", {})
        full_keyframe_receipts: dict[str, Path] | None = None
        if motion_quality_enabled:
            full_keyframe_receipts = {
                str(read_json(path).get("event_id") or ""): path.resolve()
                for path in sorted(self.keyframe_receipt_dir("full").glob("*.json"))
            }
        dynamics = build_visual_dynamics_report(
            storyboard_path=storyboard_path,
            semantic_brief_path=self.full_semantic_brief_path,
            config=dynamics_config,
            production_contract_path=self.production_contract_path,
            renderer_export_path=(
                self.renderer_export_path("full") if motion_quality_enabled else None
            ),
            keyframe_receipt_paths=full_keyframe_receipts,
        )
        write_json(dynamics_path, dynamics)
        assert_valid(
            validate_visual_dynamics_report(
                dynamics, storyboard_path, self.full_semantic_brief_path,
                config=dynamics_config,
                production_contract_path=self.production_contract_path,
                renderer_export_path=(
                    self.renderer_export_path("full") if motion_quality_enabled else None
                ),
                keyframe_receipt_paths=full_keyframe_receipts,
            ),
            "full visual dynamics QA",
        )
        if (
            dynamics_config.get("enabled", True) is True
            and dynamics_config.get("blocking", True) is True
            and dynamics.get("status") != "pass"
        ):
            raise DirectorContractError("full visual dynamics QA failed")
        regression_artifacts: list[Path] = []
        regression_config = self.project.get("editorial_regression", {})
        if regression_config.get("enabled") is True:
            baseline_path = self.root / "editorial-regression" / "golden-baseline.json"
            if not baseline_path.is_file():
                self._action_required(
                    "full_hyperframes_qa",
                    "Golden editorial regression requires a user-approved sample baseline",
                    [{"owner": "user", "expected_artifact": str(baseline_path),
                      "action": "approve-sample"}],
                )
            ledger_path = self.manual_finish_dir / "correction-ledger.json"
            regression_path = qa_dir / "editorial-regression.json"
            regression = evaluate_regression(
                baseline=read_json(baseline_path),
                baseline_path=baseline_path,
                storyboard_path=storyboard_path,
                semantic_brief_path=self.full_semantic_brief_path,
                audio_plan_path=self.full_hyperframes_project / "audio-plan.json",
                cover_plan_path=self.root / "cover-contract.json",
                correction_ledger_path=ledger_path if ledger_path.is_file() else None,
                renderer_export_path=(
                    self.renderer_export_path("full") if motion_quality_enabled else None
                ),
                keyframe_receipt_paths=(
                    list((full_keyframe_receipts or {}).values())
                    if motion_quality_enabled else ()
                ),
                # Sample audio decisions are not evidence for the full timeline.
                # Full delivery audio is validated by the dedicated audio gates.
                motion_audio_decisions_path=None,
            )
            write_json(regression_path, regression)
            assert_valid(
                validate_regression(regression, read_json(baseline_path)),
                "golden editorial regression",
            )
            if regression.get("status") != "pass":
                raise DirectorContractError("golden editorial regression failed")
            regression_artifacts.extend([baseline_path, regression_path])
        occlusion_artifacts: list[Path] = []
        if self.project.get("qa", {}).get("platform_occlusion", {}).get("enabled") is True:
            geometry_path = qa_dir / "element-geometry.json"
            if not geometry_path.is_file():
                self._action_required(
                    "full_hyperframes_qa",
                    "Platform occlusion QA requires per-event rendered element geometry",
                    [{"owner": "hyperframes", "expected_artifact": str(geometry_path),
                      "required": ["elements", "protected_zones", "cropped", "caption_occluded"]}],
                )
            templates_path = Path(__file__).parents[1] / "references" / "platform-ui-templates.json"
            occlusion_path = qa_dir / "platform-occlusion.json"
            occlusion = evaluate_platform_occlusion(
                read_json(geometry_path), read_json(templates_path),
            )
            write_json(occlusion_path, occlusion)
            if occlusion.get("passed") is not True:
                raise DirectorContractError("platform occlusion, crop, or protected-region QA failed")
            occlusion_artifacts.extend([geometry_path, occlusion_path])
        evidence_path = qa_dir / "verified-evidence.json"
        write_json(evidence_path, {
            "schema_version": 1,
            "owner": "director",
            "project": str(self.full_hyperframes_project),
            "storyboard_sha256": sha256_file(self.full_hyperframes_project / "storyboard.json"),
            "visual_vocabulary_sha256": sha256_file(
                self.full_hyperframes_project / "visual-vocabulary-audit.json"
            ),
            "commands_sha256": sha256_file(commands_path),
            "hyperframes_check_sha256": sha256_file(check_path),
            "hyperframes_check_receipt_sha256": sha256_file(check_receipt_path),
            "snapshot_review_sha256": sha256_file(snapshot_review_path),
            "preview_render_parity_sha256": sha256_file(parity_path),
            "production_contract_sha256": sha256_file(self.production_contract_path),
            "visual_dynamics_sha256": sha256_file(dynamics_path),
            "editorial_regression_sha256": (
                sha256_file(regression_artifacts[-1]) if regression_artifacts else "disabled"
            ),
            "strict_check_passed": True,
            "snapshot_review_passed": True,
            "preview_render_parity_passed": True,
            "motion_render_evidence": (
                "pass" if motion_quality_enabled else "disabled"
            ),
            "visual_dynamics_passed": dynamics.get("status") == "pass",
            "platform_occlusion_passed": True if occlusion_artifacts else "disabled",
        })
        self._complete("full_hyperframes_qa", [check_path, check_receipt_path,
                                                 snapshot_review_path, parity_path,
                                                 dynamics_path, self.production_contract_path,
                                                 evidence_path, *regression_artifacts, *snapshot_paths,
                                                *parity_snapshots, *occlusion_artifacts,
                                                *motion_evidence_artifacts])

    def _validate_final_render_authorization(self) -> Path:
        authorization = self.root / "final-render-authorization.json"
        if not authorization.is_file():
            raise DirectorContractError(
                "final render requires authorize-final-render after the full HyperFrames QA passes"
            )
        row = read_json(authorization)
        if row.get("authorized") is not True or not str(row.get("authorized_by", "")).strip():
            raise DirectorContractError("final render authorization must record an explicit authorizer")
        evidence = {
            "storyboard_sha256": self.full_hyperframes_project / "storyboard.json",
            "visual_vocabulary_sha256": self.full_hyperframes_project / "visual-vocabulary-audit.json",
            "commands_sha256": self.root / "full-hyperframes-commands.json",
            "full_qa_evidence_sha256": self.root / "full-qa" / "verified-evidence.json",
        }
        for field, path in evidence.items():
            if not path.is_file() or row.get(field) != sha256_file(path):
                raise DirectorContractError(f"final render authorization is stale: {field}")
        return authorization

    def stage_final_render(self) -> None:
        if not self.approve_final_render:
            command_path = self.root / "full-hyperframes-commands.json"
            command_record = (
                read_json(command_path).get("final_motion_render") if command_path.is_file() else None
            )
            self._action_required(
                "final_render",
                "Full render is disabled until --approve-final-render is explicitly supplied after sample approval",
                [{"owner": "hyperframes", "capability": "actual motion render",
                  "command": command_record}],
            )
        try:
            authorization = self._validate_final_render_authorization()
        except DirectorContractError as error:
            self._action_required(
                "final_render",
                str(error),
                [{"owner": "user", "capability": "authorize exact checked full project",
                  "command": [sys.executable, str(Path(__file__).resolve()), "authorize-final-render",
                              "--project", str(self.context.project_file)]}],
            )
        command_record = read_json(self.root / "full-hyperframes-commands.json")["final_motion_render"]
        original_command = list(command_record["argv"])
        command = list(original_command)
        output = Path(command_record["expected_artifact"])
        receipt_path = self.root / "final-render-receipt.json"
        stdout_path = self.root / "final-render-stdout.log"
        stderr_path = self.root / "final-render-stderr.log"
        toolchain_path = self.root / "toolchain-compatibility.json"
        render_artifacts: list[Path] = [output, authorization, receipt_path,
                                       stdout_path, stderr_path]
        if self.execute_external:
            output.parent.mkdir(parents=True, exist_ok=True)
            resolved_executable = shutil.which(command[0])
            if resolved_executable:
                command[0] = resolved_executable
            cache_config = self.project.get("render", {}).get("cache", {})
            event_cache_completed = False
            event_config = cache_config.get("event_level", {})
            if cache_config.get("enabled") is True and event_config.get("enabled") is True:
                event_report_path = self.root / "event-render-cache-report.json"
                previous: dict[str, dict[str, Any]] = {}
                if event_report_path.is_file():
                    try:
                        previous = read_json(event_report_path).get("fingerprints") or {}
                    except (OSError, ValueError, json.JSONDecodeError):
                        previous = {}
                all_commands = read_json(self.root / "full-hyperframes-commands.json")
                try:
                    event_report = execute_event_render_pipeline(
                        command_record=all_commands,
                        storyboard_path=self.full_hyperframes_project / "storyboard.json",
                        captions_path=self.video_use_dir / "captions.json",
                        safe_zones_path=self.production_contract_path,
                        design_tokens_path=self.context.edit_dir / "design-tokens.json",
                        provider_evidence_path=self.root / "provider-decision.json",
                        rights_evidence_path=self.production_contract_path,
                        implementation_paths=[
                            Path(__file__).resolve(),
                            Path(__file__).with_name("event_render_pipeline.py"),
                            Path(__file__).with_name("event_cache.py"),
                            self.full_hyperframes_project / "index.html",
                            self.full_hyperframes_project / "frame.md",
                        ],
                        cache_root=self.root / "event-render-cache",
                        output=output,
                        previous_fingerprints=previous,
                    )
                    write_json(event_report_path, event_report)
                    stdout_path.write_text(
                        json.dumps(event_report, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8",
                    )
                    stderr_path.write_text("", encoding="utf-8")
                    execution_mode = "hyperframes_event_cache"
                    event_cache_completed = True
                    render_artifacts.append(event_report_path)
                except EventRenderUnavailable as error:
                    fallback_path = self.root / "event-render-cache-fallback.json"
                    write_json(fallback_path, {
                        "schema_version": 1,
                        "status": "fallback_full_render",
                        "reason": str(error),
                        "fallback_is_safe": True,
                        "no_ffmpeg_or_static_motion_substitute": True,
                    })
                    render_artifacts.append(fallback_path)
                    if event_config.get("fallback_to_full_render", True) is not True:
                        raise DirectorContractError(
                            "event-level HyperFrames rendering is unavailable and full-render fallback is disabled"
                        ) from error
            if cache_config.get("enabled") is True and not event_cache_completed:
                project_root = Path(command_record["cwd"]).resolve()
                pipeline_path = self.root / "render-cache-pipeline.json"
                status_path = self.root / "render-cache-status.json"
                relative_inputs = sorted({
                    os.path.relpath(path, project_root)
                    for path in self.full_hyperframes_project.rglob("*")
                    if path.is_file()
                    and path.resolve() != output.resolve()
                    and not {"node_modules", ".git"}.intersection(path.parts)
                })
                final_relative = os.path.relpath(output, project_root)
                cache_working = output.with_name(
                    f"{output.stem}.render-cache.partial{output.suffix}"
                )
                working_relative = os.path.relpath(cache_working, project_root)
                cached_command = [
                    str(cache_working) if str(value) == str(output) else value
                    for value in command
                ]
                pipeline = {
                    "schema_version": 1,
                    "name": "hyperframes-full-render",
                    "settings": {
                        "director_version": DIRECTOR_VERSION,
                        "project_schema_version": self.project.get("schema_version"),
                    },
                    "stages": [{
                        "id": "graphics_render",
                        "inputs": relative_inputs,
                        "outputs": [final_relative],
                        "partial_outputs": [working_relative],
                        "atomic_outputs": [{
                            "working": working_relative,
                            "final": final_relative,
                        }],
                        "command": cached_command,
                    }],
                }
                write_json(pipeline_path, pipeline)
                result = run_cached_pipeline(
                    pipeline, project_root, self.root / "render-cache", status_path, None,
                )
                if result.get("state") != "completed":
                    raise DirectorContractError("cached HyperFrames render did not complete")
                stdout_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True),
                                       encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                execution_mode = "render_cache"
                render_artifacts.extend([pipeline_path, status_path])
            elif not event_cache_completed:
                temporary_output = output.with_name(
                    f".{output.stem}.{uuid.uuid4().hex}.rendering{output.suffix}"
                )
                render_command = [
                    str(temporary_output) if str(value) == str(output) else value
                    for value in command
                ]
                try:
                    run = subprocess.run(
                        render_command, cwd=command_record["cwd"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                    )
                    stdout_path.write_text(run.stdout or "", encoding="utf-8")
                    stderr_path.write_text(run.stderr or "", encoding="utf-8")
                    if run.returncode != 0:
                        raise DirectorContractError("HyperFrames final render command failed")
                    if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                        raise DirectorContractError("HyperFrames render command did not create its output")
                    os.replace(temporary_output, output)
                    command = render_command
                finally:
                    temporary_output.unlink(missing_ok=True)
                execution_mode = "direct"
            if not output.is_file():
                raise DirectorContractError("HyperFrames render command did not create its output")
            if not toolchain_path.is_file():
                write_json(toolchain_path, build_toolchain_report())
            write_json(receipt_path, {
                "schema_version": 1, "owner": "director", "capability": "hyperframes_render",
                "status": "pass", "exit_code": 0, "execution_mode": execution_mode,
                "command": original_command, "resolved_command": command,
                "command_sha256": _json_sha256(original_command),
                "cwd": str(Path(command_record["cwd"]).resolve()),
                "authorization_sha256": sha256_file(authorization),
                "full_qa_evidence_sha256": sha256_file(self.root / "full-qa" / "verified-evidence.json"),
                "storyboard_sha256": sha256_file(self.full_hyperframes_project / "storyboard.json"),
                "commands_sha256": sha256_file(self.root / "full-hyperframes-commands.json"),
                "toolchain_sha256": sha256_file(toolchain_path),
                "output": str(output.resolve()), "output_sha256": sha256_file(output),
                "stdout_log": str(stdout_path), "stdout_sha256": sha256_file(stdout_path),
                "stderr_log": str(stderr_path), "stderr_sha256": sha256_file(stderr_path),
                "completed_at": utc_now(),
            })
        if not output.is_file():
            self._action_required("final_render", "HyperFrames render output is not present",
                                  [{"owner": "hyperframes", "command": command_record,
                                    "expected_artifact": str(output)}])
        if not receipt_path.is_file():
            self._action_required(
                "final_render",
                "HyperFrames render requires a Director execution receipt; an unbound file is not accepted",
                [{"owner": "director", "command": command_record,
                  "required_flag": "--execute-external", "expected_artifact": str(receipt_path)}],
            )
        receipt = read_json(receipt_path)
        receipt_bindings = {
            "authorization_sha256": authorization,
            "full_qa_evidence_sha256": self.root / "full-qa" / "verified-evidence.json",
            "storyboard_sha256": self.full_hyperframes_project / "storyboard.json",
            "commands_sha256": self.root / "full-hyperframes-commands.json",
            "toolchain_sha256": toolchain_path,
            "output_sha256": output,
            "stdout_sha256": Path(str(receipt.get("stdout_log", ""))),
            "stderr_sha256": Path(str(receipt.get("stderr_log", ""))),
        }
        if (
            receipt.get("owner") != "director"
            or receipt.get("capability") != "hyperframes_render"
            or receipt.get("status") != "pass"
            or int(receipt.get("exit_code", -1)) != 0
            or receipt.get("command_sha256") != _json_sha256(original_command)
            or receipt.get("cwd") != str(Path(command_record["cwd"]).resolve())
            or receipt.get("output") != str(output.resolve())
            or any(not path.is_file() or receipt.get(field) != sha256_file(path)
                   for field, path in receipt_bindings.items())
        ):
            raise DirectorContractError("HyperFrames final-render execution receipt is missing or stale")
        self._complete("final_render", render_artifacts)

    def stage_final_compose(self) -> None:
        render_record = read_json(self.root / "full-hyperframes-commands.json")["final_motion_render"]
        motion = Path(render_record["expected_artifact"])
        if not motion.is_file():
            self._action_required(
                "final_compose",
                "Actual HyperFrames full render is required before FFmpeg composition",
                [{"owner": "hyperframes", "expected_artifact": str(motion)}],
            )
        output = self.delivery_output
        normalization = self.project.get("audio", {}).get("normalization", {})
        normalize_enabled = normalization.get("enabled") is True
        compose_output = self.root / "final-compose-pre-normalized.mp4" if normalize_enabled else output
        bgm_config = self.project.get("audio", {}).get("bgm", {})
        caption_delivery: dict[str, Any]
        caption_asset = self.video_use_dir / "master.srt"
        analysis_path = self.root / "input-mode-analysis.json"
        caption_analysis = {}
        if analysis_path.is_file():
            caption_analysis = read_json(analysis_path).get("captions") or {}
        verified_burned = caption_analysis.get("burned_in") or {}
        existing_caption_verified = bool(caption_analysis.get("subtitle_streams")) or (
            verified_burned.get("detected") is True
            and verified_burned.get("verification_status") == "verified"
        )
        caption_disabled = self.project.get("editing", {}).get("caption_delivery") == "none"
        burn_captions = (
            not caption_disabled
            and not existing_caption_verified
        )
        caption_sync_closure_enabled = (
            ((self.project.get("editing") or {}).get("caption_sync_closure") or {})
            .get("enabled") is True
        )
        if burn_captions:
            if not caption_asset.is_file():
                self._action_required(
                    "final_compose",
                    "Output-timeline video-use captions are required before final composition",
                    [{"owner": "video-use", "expected_artifact": str(caption_asset)}],
                )
            caption_filter_path = caption_asset.resolve().as_posix().replace(":", "\\:")
            caption_filter_path = caption_filter_path.replace("'", "\\'")
            caption_filter = f"subtitles=filename='{caption_filter_path}':charenc=UTF-8"
            caption_delivery = {
                "mode": "burned_in_last",
                "source": str(caption_asset.resolve()),
                "source_sha256": sha256_file(caption_asset),
                "owner": "video-use",
                "reason": "no verified existing caption layer; output-timeline captions are applied last",
            }
        elif caption_disabled:
            caption_filter = None
            caption_delivery = {
                "mode": "disabled_by_project",
                "reason": "editing.caption_delivery is explicitly none",
            }
        else:
            caption_filter = None
            caption_delivery = {
                "mode": "preserve_verified_existing",
                "reason": (
                    "verified existing subtitle stream or burned captions"
                ),
            }
        bgm_value = bgm_config.get("asset")
        bgm_asset = Path(str(bgm_value)) if bgm_value else None
        bgm_source = "project_config" if bgm_asset else None
        bgm_provenance: dict[str, Any] = {}
        if bgm_asset and not bgm_asset.is_absolute():
            bgm_asset = (self.context.root / bgm_asset).resolve()
        full_audio_plan_path = self.full_hyperframes_project / "audio-plan.json"
        full_audio_background: dict[str, Any] = {}
        if not bgm_asset and full_audio_plan_path.is_file():
            full_audio_background = read_json(full_audio_plan_path).get("background_music") or {}
            if (full_audio_background.get("mode") == "authorized_asset"
                    and full_audio_background.get("enabled") is True
                    and full_audio_background.get("source")):
                bgm_asset = self._optional_project_path(
                    full_audio_background.get("source"), base=self.full_hyperframes_project,
                )
                bgm_source = "full_audio_plan"
                bgm_provenance = full_audio_background.get("provenance") or {}
        bgm_enabled = (
            bgm_asset is not None
            and bgm_config.get("enabled") is not False
            and (
                bgm_config.get("enabled", bgm_config.get("enabled_by_default", False)) is True
                or full_audio_background.get("enabled") is True
            )
        )
        if bgm_enabled and not bgm_asset.is_file():
            self._action_required(
                "final_compose",
                "Configured authorized BGM asset is not present",
                [{"owner": "director", "expected_artifact": str(bgm_asset)}],
            )
        if bgm_enabled and bgm_asset and bgm_source == "full_audio_plan":
            approved_bgm_sha = bgm_provenance.get("sha256")
            if not approved_bgm_sha:
                raise DirectorContractError(
                    "BGM provenance hash is required for a full audio-plan asset"
                )
            if approved_bgm_sha != sha256_file(bgm_asset):
                raise DirectorContractError(
                    "BGM asset hash no longer matches the approved full audio plan"
                )
        audio_mix: dict[str, Any] = {"bgm_enabled": False}
        if bgm_enabled and bgm_asset:
            storyboard = read_json(self.full_hyperframes_project / "storyboard.json")
            duration = float(storyboard.get("composition", {}).get("duration", 0.0))
            if duration <= 0:
                duration = _ffprobe_duration(motion)
            preview_volume = float(
                bgm_config.get("preview_volume", full_audio_background.get("preview_volume", 0.1))
            )
            ducking = bgm_config.get("ducking", {})
            threshold = float(ducking.get("threshold", 0.03))
            ratio = float(ducking.get("ratio", 8))
            attack = int(ducking.get("attack_ms", 200))
            release = int(ducking.get("release_ms", 400))
            fade_out = max(0.0, duration - 2.0)
            mix_tail = (
                "[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0"
            )
            if not normalize_enabled:
                mix_tail += ",loudnorm=I=-14:TP=-1.5:LRA=11"
            filter_graph = (
                f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume={preview_volume:.3f},"
                f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out:.3f}:d=2[bgm];"
                f"[bgm][0:a]sidechaincompress=threshold={threshold}:ratio={ratio}:"
                f"attack={attack}:release={release}[ducked];"
                f"{mix_tail}[aout]"
            )
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(motion),
                "-stream_loop", "-1", "-i", str(bgm_asset), "-filter_complex", filter_graph,
                "-map", "0:v:0", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium",
                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(compose_output),
            ]
            if caption_filter:
                command[command.index("-map"):command.index("-map")] = ["-vf", caption_filter]
            audio_mix = {
                "bgm_enabled": True,
                "bgm_asset": str(bgm_asset),
                "source": bgm_source,
                "provider": bgm_provenance.get("provider"),
                "bgm_sha256": sha256_file(bgm_asset),
                "preview_volume": preview_volume,
                "ducking": {"method": "sidechaincompress", "threshold": threshold,
                            "ratio": ratio, "attack_ms": attack, "release_ms": release},
            }
        else:
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(motion),
                "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
                "-crf", "18", "-pix_fmt", "yuv420p",
            ]
            if caption_filter:
                command[command.index("-map"):command.index("-map")] = ["-vf", caption_filter]
            if not normalize_enabled:
                command.extend(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"])
            command.extend(["-c:a", "aac", "-b:a", "192k",
                            "-movflags", "+faststart", str(compose_output)])
        command_path = self.root / "final-compose-command.json"
        previous_plan = read_json(command_path) if command_path.is_file() else {}
        signature_payload = {
            "director_version": DIRECTOR_VERSION,
            "project_schema_version": self.project.get("schema_version"),
            "motion_sha256": sha256_file(motion),
            "audio_plan_sha256": (
                sha256_file(full_audio_plan_path) if full_audio_plan_path.is_file() else None
            ),
            "bgm_sha256": sha256_file(bgm_asset) if bgm_enabled and bgm_asset else None,
            "caption_delivery": caption_delivery,
            "normalization": {
                "enabled": normalize_enabled,
                "target_lufs": float(normalization.get("target_lufs", -14.0)),
                "true_peak_dbtp": float(normalization.get("true_peak_dbtp", -1.5)),
                "lra": float(normalization.get("lra", 11.0)),
            },
            "argv": command,
        }
        compose_signature = hashlib.sha256(json.dumps(
            signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        plan = {
            "schema_version": 1,
            "owner": "ffmpeg",
            "input": str(motion),
            "compose_input_sha256": signature_payload["motion_sha256"],
            "output": str(output),
            "compose_output": str(compose_output),
            "single_universal_output": True,
            "audio_mix": audio_mix,
            "caption_delivery": caption_delivery,
            "two_pass_normalization": {
                "enabled": normalize_enabled,
                "target_lufs": float(normalization.get("target_lufs", -14.0)),
                "true_peak_dbtp": float(normalization.get("true_peak_dbtp", -1.5)),
                "lra": float(normalization.get("lra", 11.0)),
            },
            "argv": command,
            "compose_signature": compose_signature,
        }
        normalization_report = self.root / "audio-normalization-report.json"
        reusable_compose = (
            compose_output.is_file()
            and previous_plan.get("compose_signature") == compose_signature
            and previous_plan.get("compose_output_sha256") == sha256_file(compose_output)
        )
        adopt_manual_compose = (
            compose_output.is_file()
            and previous_plan.get("compose_signature") == compose_signature
            and previous_plan.get("execution_status") == "awaiting_external_execution"
            and not previous_plan.get("compose_output_sha256")
        )
        if self.execute_external:
            compose_output.parent.mkdir(parents=True, exist_ok=True)
            if not reusable_compose:
                subprocess.run(command, cwd=self.context.root, check=True)
            if not compose_output.is_file():
                raise DirectorContractError("FFmpeg did not create the declared compose output")
            plan["compose_output_sha256"] = sha256_file(compose_output)
            plan["execution_status"] = "reused" if reusable_compose else "executed"
            write_json(command_path, plan)
            if normalize_enabled:
                current = read_json(normalization_report) if normalization_report.is_file() else {}
                fresh = output.is_file() and not validate_audio_normalization_report(
                    current, compose_output, output,
                    float(normalization.get("target_lufs", -14.0)),
                    float(normalization.get("true_peak_dbtp", -1.5)),
                    float(normalization.get("lra", 11.0)),
                )
                if not fresh:
                    report = normalize_social_audio(
                        compose_output, output,
                        float(normalization.get("target_lufs", -14.0)),
                        float(normalization.get("true_peak_dbtp", -1.5)),
                        float(normalization.get("lra", 11.0)),
                    )
                    write_json(normalization_report, report)
        else:
            if reusable_compose or adopt_manual_compose:
                plan["compose_output_sha256"] = sha256_file(compose_output)
                plan["execution_status"] = (
                    "reused" if reusable_compose else "adopted_external_output"
                )
            elif not compose_output.is_file():
                plan["execution_status"] = "awaiting_external_execution"
            else:
                plan["execution_status"] = "stale_output_rejected"
            write_json(command_path, plan)
            if compose_output.is_file() and not (reusable_compose or adopt_manual_compose):
                self._action_required(
                    "final_compose",
                    "Existing FFmpeg composition is stale or not bound to current inputs",
                    [{"owner": "ffmpeg", "command": command,
                      "expected_artifact": str(compose_output)}],
                )
        if not output.is_file():
            self._action_required(
                "final_compose",
                "FFmpeg universal composition/encode output is not present",
                [{"owner": "ffmpeg", "capability": "final composition, mix and encode",
                  "command": command, "expected_artifact": str(output)}],
            )
        if normalize_enabled:
            if not normalization_report.is_file():
                self._action_required(
                    "final_compose",
                    "Two-pass social audio normalization evidence is required",
                    [{"owner": "ffmpeg", "source": str(compose_output),
                      "expected_artifact": str(normalization_report)}],
                )
            report = read_json(normalization_report)
            normalization_errors = validate_audio_normalization_report(
                report, compose_output, output,
                float(normalization.get("target_lufs", -14.0)),
                float(normalization.get("true_peak_dbtp", -1.5)),
                float(normalization.get("lra", 11.0)),
            )
            if normalization_errors:
                raise DirectorContractError(
                    "audio normalization report is missing, failed, or stale: "
                    + "; ".join(normalization_errors)
                )
        media_report = self.root / "final-media-report.json"
        boundaries: list[float] = []
        edl_path = self.video_use_dir / "edl.json"
        if edl_path.is_file():
            cursor = 0.0
            ranges = read_json(edl_path).get("ranges") or []
            for index, row in enumerate(ranges):
                if index:
                    boundaries.append(float(row.get("timeline_start", cursor)))
                cursor = float(row.get("timeline_start", cursor)) + (
                    float(row["end"]) - float(row["start"])
                )
        technical = run_technical_qa(
            output,
            output=media_report,
            evidence_dir=self.root / "final-qa" / "technical-evidence",
            cut_boundaries=boundaries,
            true_peak_ceiling=float(self.project.get("audio", {}).get("true_peak_ceiling_dbtp", -1.0)),
        )
        if technical.get("status") != "pass":
            raise DirectorContractError(
                "final technical QA failed: " + "; ".join(technical.get("blocking_errors") or [])
            )
        sync_closure_path = self.video_use_dir / "caption-sync-final.json"
        initial_sync_path = self.video_use_dir / "caption-sync-report.json"
        mapped_words_path = self.video_use_dir / "mapped-words.json"
        captions_path = self.video_use_dir / "captions.json"
        if burn_captions and caption_sync_closure_enabled:
            required_sync = [initial_sync_path, mapped_words_path, captions_path, caption_asset]
            if any(not path.is_file() for path in required_sync):
                self._action_required(
                    "final_compose", "Final caption sync closure inputs are incomplete",
                    [{"owner": "video-use", "missing_artifacts": [
                        str(path) for path in required_sync if not path.is_file()
                    ]}],
                )
            mapped_payload = read_json(mapped_words_path)
            caption_payload = read_json(captions_path)
            terms = list((self.project.get("editing") or {}).get("caption_terminology") or [])
            sync_closure = synchronization_report(
                mapped_payload.get("words") or [], caption_payload.get("segments") or [],
                cut_boundaries=boundaries, terminology=[str(value) for value in terms],
                final_composite={
                    "required": True,
                    "path": str(output.resolve()),
                    "media_sha256": sha256_file(output),
                    "caption_path": str(caption_asset.resolve()),
                    "caption_sha256": sha256_file(caption_asset),
                    "full_av_decode": technical.get("status") == "pass",
                    "subtitle_filter_verified": (
                        caption_delivery.get("mode") == "burned_in_last"
                        and caption_filter is not None
                        and caption_filter in command
                    ),
                    "compose_command_sha256": hashlib.sha256(json.dumps(
                        command, ensure_ascii=False, separators=(",", ":"),
                    ).encode("utf-8")).hexdigest(),
                },
            )
            sync_closure["initial_sync_report"] = {
                "path": str(initial_sync_path.resolve()),
                "sha256": sha256_file(initial_sync_path),
            }
            if sync_closure.get("passed") is not True:
                raise DirectorContractError("final caption synchronization closure did not pass")
            write_json(sync_closure_path, sync_closure)
        artifacts = [output, command_path, media_report]
        if sync_closure_path.is_file() and caption_sync_closure_enabled:
            artifacts.append(sync_closure_path)
        if normalize_enabled:
            artifacts.extend([compose_output, normalization_report])
        self._complete("final_compose", artifacts)

    def stage_derived_content(self) -> None:
        config = self.project.get("derived_content", {})
        output_dir = self.root / "derived-content"
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[Path] = []
        decisions: dict[str, Any] = {}
        transcript = self.video_use_dir / "transcripts" / f"{self.context.source_video.stem}.json"
        edl = self.video_use_dir / "edl.json"
        enabled = [name for name in ("clip_factory", "podcast", "localization")
                   if config.get(name, {}).get("enabled") is True]
        if not enabled:
            decision_path = output_dir / "decision.json"
            write_json(decision_path, {"schema_version": 1, "status": "disabled",
                                       "reason": "all optional derived content is disabled"})
            self._complete("derived_content", [decision_path])
            return
        if "clip_factory" in enabled:
            required = [transcript, edl, self.full_semantic_brief_path,
                        self.production_contract_path]
            missing = [str(path) for path in required if not path.is_file()]
            if missing:
                self._action_required("derived_content", "Clip Factory evidence is incomplete",
                                      [{"owner": "director", "missing_artifacts": missing}])
            tokens_path = self.context.edit_dir / "design-tokens.json"
            orientation = "landscape"
            if tokens_path.is_file():
                dimensions = (read_json(tokens_path).get("sampling") or {}).get("dimensions") or {}
                orientation = "portrait" if float(dimensions.get("height") or 0) > float(
                    dimensions.get("width") or 1
                ) else "landscape"
            path = output_dir / "clip-factory-manifest.json"
            report = build_clip_manifest(
                transcript_path=transcript, edl_path=edl,
                semantic_brief_path=self.full_semantic_brief_path,
                output_timeline_path=edl,
                hook_path=self.root / "hook-decision.json",
                production_contract_path=self.production_contract_path,
                orientation=orientation, output=path,
            )
            assert_valid(validate_clip_manifest(report), "clip factory")
            decisions["clip_factory"] = report["status"]
            artifacts.append(path)
        if "podcast" in enabled:
            podcast = config["podcast"]
            audio_path = self._optional_project_path(podcast.get("clean_audio"))
            if not audio_path or not audio_path.is_file() or not transcript.is_file():
                self._action_required(
                    "derived_content", "Podcast requires an actually materialized clean PCM audio file",
                    [{"owner": "ffmpeg_or_audio_provider", "expected_artifact": str(audio_path)}],
                )
            path = output_dir / "podcast-manifest.json"
            report = build_podcast_manifest(
                audio_path=audio_path, transcript_path=transcript,
                chapters=list(podcast.get("chapters") or []),
                title=str(podcast.get("title") or self.project.get("video_id") or "Podcast"),
                description=str(podcast.get("description") or "Source-bound podcast export"),
                output=path,
            )
            assert_valid(validate_podcast_manifest(report), "podcast pipeline")
            decisions["podcast"] = "pass"; artifacts.append(path)
        if "localization" in enabled:
            localization = config["localization"]
            if not transcript.is_file():
                self._action_required("derived_content", "Localization requires the current transcript",
                                      [{"owner": "video-use", "expected_artifact": str(transcript)}])
            path = output_dir / "localization-manifest.json"
            provider = dict(localization.get("provider") or {})
            if provider.get("result"):
                provider["result"] = str(self._project_path(provider["result"]))
            reservation = None
            if provider.get("backend") != "fixture":
                decision = read_json(self.root / "provider-decision.json")
                selected = ((decision.get("decisions") or {}).get("translation") or {}).get("selected")
                if not isinstance(selected, dict) or selected.get("name") != provider.get("name"):
                    self._action_required(
                        "derived_content",
                        "Localization provider is not the current authorized translation decision",
                        [{"owner": "user", "provider": provider.get("name"),
                          "provider_decision": str(self.root / "provider-decision.json")}],
                    )
                result_exists = bool(provider.get("result")) and Path(
                    str(provider.get("result"))
                ).is_file()
                reservation = self._ensure_provider_reservation(
                    "translation", stage="derived_content", allow_create=not result_exists,
                )
                if result_exists and reservation is None:
                    self._action_required(
                        "derived_content",
                        "Localization result cannot be adopted without a prior cost reservation",
                        [{"owner": "user", "action": "remove stale result, resume to reserve, then rerun provider",
                          "provider_result": str(provider.get("result"))}],
                    )
            try:
                report = build_localization_manifest(
                    transcript_path=transcript,
                    target_language=str(localization.get("target_language") or "en"),
                    glossary=dict(localization.get("glossary") or {}),
                    provider=provider,
                    voice_clone_authorized=localization.get("voice_clone_authorized") is True,
                    output=path,
                )
            except Exception as error:
                if reservation is not None:
                    result_path = Path(str(provider.get("result") or "")).resolve()
                    failure_evidence = {
                        "error_type": type(error).__name__,
                        "provider_result": {
                            "path": str(result_path),
                            "sha256": sha256_file(result_path) if result_path.is_file() else None,
                        },
                    }
                    self._reconcile_provider_result(
                        "translation", str(reservation["id"]),
                        failure_evidence, status="failed",
                    )
                raise
            if reservation is not None and report.get("status") == "failed":
                raw_result = read_json(Path(str(provider["result"])).resolve())
                self._reconcile_provider_result(
                    "translation", str(reservation["id"]), raw_result, status="failed",
                )
            if report.get("status") == "action_required":
                self._action_required(
                    "derived_content", str(report.get("reason")),
                    [{"owner": "translation_or_tts_provider", "request": str(path),
                      "reservation_id": reservation.get("id") if reservation else None}],
                )
            assert_valid(validate_localization_manifest(report), "localization pipeline")
            if reservation is not None:
                raw_result = read_json(Path(str(provider["result"])).resolve())
                self._reconcile_provider_result(
                    "translation", str(reservation["id"]), raw_result, status="success",
                )
            decisions["localization"] = "complete"; artifacts.append(path)
        decision_path = output_dir / "decision.json"
        write_json(decision_path, {"schema_version": 1, "status": "complete",
                                   "capabilities": decisions})
        self._complete("derived_content", [decision_path, *artifacts])

    def _optional_project_path(self, value: Any, *, base: Path | None = None) -> Path | None:
        if not value:
            return None
        candidate = Path(str(value))
        if candidate.is_absolute():
            return candidate.resolve()
        return ((base or self.context.root) / candidate).resolve()

    def _project_output_path(self, value: Any, label: str) -> Path:
        path = self._optional_project_path(value)
        if path is None:
            raise DirectorContractError(f"{label} output path is required")
        root = self.context.root.resolve()
        if path == root or root not in path.parents:
            raise DirectorContractError(f"{label} output must stay inside the project root")
        return path

    def _manual_sfx_stems(self) -> list[Path]:
        audio_plan = self.full_hyperframes_project / "audio-plan.json"
        if not audio_plan.is_file():
            return []
        stems: list[Path] = []
        seen: set[Path] = set()
        for row in (read_json(audio_plan).get("motion_sfx") or {}).get("event_decisions") or []:
            if row.get("decision") != "cue":
                continue
            path = self._optional_project_path(row.get("asset"), base=self.full_hyperframes_project)
            if path and path not in seen:
                seen.add(path)
                stems.append(path)
        return stems

    def _write_manual_handoff_manifest(self) -> Path:
        config = self.manual_finish_config
        assets = config.get("assets") or {}
        clean_a_roll = self._optional_project_path(
            assets.get("clean_a_roll") or (self.video_use_dir / "base-preview.mp4")
        )
        captions = self._optional_project_path(
            assets.get("captions") or (self.video_use_dir / "master.srt")
        )
        transparent = self._optional_project_path(assets.get("transparent_motion_layer"))
        bgm = self._optional_project_path(
            assets.get("bgm_stem") or self.project.get("audio", {}).get("bgm", {}).get("asset")
        )
        cover = self._optional_project_path(
            assets.get("cover") or self.project.get("delivery", {}).get("cover")
        )
        sfx = [self._optional_project_path(value) for value in (assets.get("sfx_stems") or [])]
        sfx_paths = [path for path in sfx if path] or self._manual_sfx_stems()
        path = self.manual_handoff_manifest_path
        build_handoff_manifest(
            manifest_path=path,
            backend=str(config.get("backend")),
            source_video=self.context.source_video,
            automatic_master=self.delivery_output,
            clean_a_roll=clean_a_roll,
            captions=captions,
            transparent_motion_layer=transparent,
            bgm_stem=bgm,
            sfx_stems=sfx_paths,
            cover=cover,
            modifications=list(config.get("modifications") or []),
            transcript=self.video_use_dir / "transcripts" / f"{self.context.source_video.stem}.json",
            edl=self.video_use_dir / "edl.json",
            semantic_brief=self.full_semantic_brief_path,
            storyboard=self.full_hyperframes_project / "storyboard.json",
            production_contract=self.production_contract_path,
        )
        return path

    def _ensure_manual_correction_ledger(self) -> Path:
        path = self.manual_finish_dir / "correction-ledger.json"
        if not path.is_file():
            new_ledger(path, project_root=self.context.root)
        validate_ledger(path)
        return path

    def _record_manual_return(self, returned: Path) -> Path:
        receipt_path = self.manual_finish_dir / "return-receipt.json"
        returned_hash = sha256_file(returned)
        previous = read_json(receipt_path) if receipt_path.is_file() else {}
        changed = previous.get("returned_final_sha256") != returned_hash
        if changed:
            stale_paths = [
                self.root / "delivery-contract.json",
                self.root / "final-qa" / "aesthetic-review.json",
                self.root / "final-qa" / "platform-douyin.json",
                self.root / "final-qa" / "platform-wechat_channels.json",
                self.video_use_dir / "final-edit-correctness.json",
            ]
            stale = [
                {"path": str(path), "sha256": sha256_file(path)}
                for path in stale_paths if path.is_file()
            ]
            self.state["stages"]["delivery_qa"] = _stage_template()
            write_json(self.manual_finish_dir / "delivery-qa-invalidation.json", {
                "schema_version": 1,
                "invalidated_at": utc_now(),
                "reason": "a new or changed manual final requires all final delivery evidence to be rebound",
                "previous_return_sha256": previous.get("returned_final_sha256"),
                "returned_final_sha256": returned_hash,
                "stale_evidence_retained_for_audit": stale,
                "invalidated_stages": ["delivery_qa"],
            })
            self._save()
        stat = returned.stat()
        write_json(receipt_path, {
            "schema_version": 1,
            "backend": self.manual_finish_config.get("backend"),
            "automatic_master": str(self.delivery_output),
            "automatic_master_sha256": sha256_file(self.delivery_output),
            "returned_final": str(returned),
            "returned_final_sha256": returned_hash,
            "returned_final_size": stat.st_size,
            "returned_final_mtime_ns": stat.st_mtime_ns,
            "received_at": utc_now(),
        })
        return receipt_path

    def _ensure_manual_return_media_report(self, returned: Path) -> Path:
        path = self.manual_finish_dir / "manual-final-media-report.json"
        returned_hash = sha256_file(returned)
        if path.is_file():
            cached = read_json(path)
            if cached.get("sha256") == returned_hash and cached.get("decode_status") == "pass":
                return path
        report = run_technical_qa(
            returned,
            output=path,
            evidence_dir=self.manual_finish_dir / "technical-evidence",
            true_peak_ceiling=float(self.project.get("audio", {}).get("true_peak_ceiling_dbtp", -1.0)),
        )
        if report.get("status") != "pass":
            raise DirectorContractError("manual returned final failed technical QA")
        return path

    def stage_manual_finish_handoff(self) -> None:
        config = self.manual_finish_config
        enabled = config.get("enabled") is True
        backend = str(config.get("backend", "none"))
        decision_path = self.manual_finish_dir / "decision.json"
        if not enabled or backend == "none":
            write_json(decision_path, {
                "schema_version": 1,
                "enabled": enabled,
                "backend": backend,
                "decision": "disabled" if not enabled else "explicit_none",
                "automatic_master_remains_universal_output": True,
            })
            self._complete("manual_finish_handoff", [decision_path])
            return
        if not self.delivery_output.is_file():
            self._action_required(
                "manual_finish_handoff",
                "Automatic universal master is required before a human manual finishing handoff",
                [{"owner": "ffmpeg", "expected_artifact": str(self.delivery_output)}],
            )
        returned = self.manual_return_output
        if returned.resolve() == self.delivery_output.resolve():
            self._action_required(
                "manual_finish_handoff",
                "Manual returned final must use a different path so the automatic master remains unchanged",
                [{"owner": "user", "capability": "choose a distinct returned_final path"}],
            )
        manifest_path = self._write_manual_handoff_manifest()
        ledger_path = self._ensure_manual_correction_ledger()
        typed_handoff_path: Path | None = None
        if backend in {"opencut", "other_nle", "openmontage"}:
            edl_path = self.video_use_dir / "edl.json"
            if edl_path.is_file():
                typed = build_typed_nle_handoff(
                    read_json(edl_path), backend=backend,
                    authorized_capabilities=set(config.get("authorized_capabilities") or []),
                    authoritative_edl_path=edl_path,
                )
                typed_handoff_path = self.manual_finish_dir / "typed-nle-handoff.json"
                write_json(typed_handoff_path, typed)
        if not returned.is_file():
            self._action_required(
                "manual_finish_handoff",
                "A human manual finishing export is required before the workflow can continue",
                [{
                    "owner": "human_editor",
                    "backend": backend,
                    "handoff_manifest": str(manifest_path),
                    "correction_ledger": str(ledger_path),
                    "typed_nle_handoff": (
                        str(typed_handoff_path) if typed_handoff_path is not None else None
                    ),
                    "expected_artifact": str(returned),
                    "capability_boundary": (
                        "The configured NLE is a human-facing option only; no CLI, MCP, Editor API, "
                        "or headless rendering capability is assumed for OpenMontage, OpenCut, or "
                        "another editor."
                    ),
                }],
            )
        receipt_path = self._record_manual_return(returned)
        media_report_path = self._ensure_manual_return_media_report(returned)
        media_report = read_json(media_report_path)
        if (
            media_report.get("decode_status") != "pass"
            or media_report.get("sha256") != sha256_file(returned)
        ):
            raise DirectorContractError("manual returned final media report is missing or stale")
        returned_qa_path = self.manual_finish_dir / "manual-final-qa.json"
        final_correctness_path = self.video_use_dir / "final-edit-correctness.json"
        errors: list[str] = []
        if returned_qa_path.is_file():
            errors.extend(validate_returned_final_qa(read_json(returned_qa_path), returned))
        else:
            errors.append("manual-final-qa.json is missing")
        if final_correctness_path.is_file():
            errors.extend(validate_video_use_final_correctness(
                read_json(final_correctness_path),
                output_path=returned,
                edl=read_json(self.video_use_dir / "edl.json"),
            ))
        else:
            errors.append("video-use final-edit-correctness.json is missing")
        ledger = validate_ledger(ledger_path)
        if config.get("modifications") and not ledger.get("entries"):
            errors.append("requested manual modifications require approved correction-ledger entries")
        if errors:
            request_path = self.manual_finish_dir / "revalidation-request.json"
            write_json(request_path, {
                "schema_version": 1,
                "returned_final": str(returned),
                "returned_final_sha256": sha256_file(returned),
                "required": {
                    "full_decode": str(media_report_path),
                    "captions_audio_visual": str(returned_qa_path),
                    "video_use_final_correctness": str(final_correctness_path),
                    "correction_ledger": str(ledger_path),
                },
                "errors": errors,
            })
            self._action_required(
                "manual_finish_handoff",
                "Manual returned final requires fresh decode, caption, audio, visual, and final-edit-correctness revalidation",
                [
                    {"owner": "video-use", "capability": "caption timing and final edit correctness",
                     "expected_artifact": str(final_correctness_path)},
                    {"owner": "director_with_visual_audio_review",
                     "capability": "returned final caption, post-AAC audio, and representative visual QA",
                     "expected_artifact": str(returned_qa_path)},
                    {"owner": "human_editor", "capability": "auditable approved correction entries",
                     "expected_artifact": str(ledger_path)},
                ],
            )
        write_json(decision_path, {
            "schema_version": 1,
            "enabled": True,
            "backend": backend,
            "decision": "returned_final_revalidated",
            "automatic_master": str(self.delivery_output),
            "returned_final": str(returned),
            "returned_final_sha256": sha256_file(returned),
        })
        self._complete("manual_finish_handoff", [
            decision_path, manifest_path, ledger_path, receipt_path,
            media_report_path, returned_qa_path, final_correctness_path, returned,
            *([typed_handoff_path] if typed_handoff_path is not None else []),
        ])

    def _build_optional_delivery_packages(
        self, *, output: Path, cover: Path, delivery_contract: Path,
        required_evidence: list[Path],
    ) -> list[Path]:
        artifacts: list[Path] = []
        audit = self.project.get("delivery", {}).get("audit_bundle", {})
        release = self.project.get("delivery", {}).get("release_pack", {})
        if audit.get("enabled") is not True and release.get("enabled") is not True:
            return []
        doctor_path = self.root / "doctor-report.json"
        write_json(doctor_path, run_doctor())

        if audit.get("enabled") is True:
            audit_output = self._project_output_path(
                audit.get("output_dir") or "work/director/portable-audit-bundle",
                "portable audit bundle",
            )
            safe_inputs = [
                self.context.project_file, self.state_path, doctor_path,
                delivery_contract, self.root / "provider-decision.json",
                self.root / "cost-ledger.json", self.root / "toolchain-compatibility.json",
                *[path for path in required_evidence if path.suffix.lower() == ".json"],
            ]
            safe_inputs = [path for path in dict.fromkeys(safe_inputs) if path.is_file()]
            replace = (audit_output / "audit-bundle.json").is_file()
            create_portable_audit_bundle(
                self.context.root, audit_output, safe_inputs, replace=replace,
            )
            verification = verify_audit_bundle(audit_output)
            verification_path = self.root / "portable-audit-verification.json"
            write_json(verification_path, {
                "schema_version": 1,
                **verification,
                "manifest": str(audit_output / "audit-bundle.json"),
                "manifest_sha256": sha256_file(audit_output / "audit-bundle.json"),
            })
            artifacts.extend([audit_output / "audit-bundle.json", verification_path])

        if release.get("enabled") is not True:
            return [doctor_path, *artifacts]
        publishing_copy = self.root / "publish-metadata.json"
        privacy_manifest = self._optional_project_path(release.get("privacy_manifest"))
        rights_manifest = self._optional_project_path(release.get("rights_manifest"))
        authorization = self._optional_project_path(release.get("publication_authorization"))
        missing = [
            label for label, path in (
                ("publishing copy", publishing_copy),
                ("privacy review manifest", privacy_manifest),
                ("rights authorization manifest", rights_manifest),
                ("separate publication authorization", authorization),
            ) if path is None or not path.is_file()
        ]
        if missing:
            request = self.root / "release-pack-request.json"
            write_json(request, {
                "schema_version": 1,
                "status": "action_required",
                "missing": missing,
                "universal_video": str(output),
                "cover": str(cover),
                "publishing_copy": str(publishing_copy),
                "automatic_upload_or_publication": False,
            })
            self._action_required(
                "delivery_qa",
                "Release delivery pack requires explicit privacy, rights, copy, and publication evidence",
                [{"owner": "user_and_director_release_reviewer", "request": str(request)}],
            )
        assert privacy_manifest is not None and rights_manifest is not None and authorization is not None
        privacy_report = self.root / "release" / "prepublish-privacy-audit.json"
        rights_report = self.root / "release" / "rights-authorization-report.json"
        try:
            create_privacy_audit(privacy_manifest, privacy_report)
            create_rights_authorization_report(rights_manifest, rights_report)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            request = self.root / "release-evidence-repair-request.json"
            write_json(request, {"schema_version": 1, "status": "action_required",
                                 "reason": str(error)})
            self._action_required(
                "delivery_qa", "Release privacy or rights evidence failed closed",
                [{"owner": "user_and_director_release_reviewer", "request": str(request)}],
            )
        release_output = self._project_output_path(
            release.get("output_dir") or "exports/release-pack",
            "release pack",
        )
        additional = {
            "hyperframes_storyboard": self.full_hyperframes_project / "storyboard.json",
            "hyperframes_index": self.full_hyperframes_project / "index.html",
            "hyperframes_frame": self.full_hyperframes_project / "frame.md",
            "captions": self.video_use_dir / "captions.json",
            "subtitles": self.video_use_dir / "master.srt",
            "edl": self.video_use_dir / "edl.json",
            "semantic_brief": self.full_semantic_brief_path,
            "audio_plan": self.full_hyperframes_project / "audio-plan.json",
            "production_contract": self.production_contract_path,
            "delivery_qa": delivery_contract,
            "doctor_report": doctor_path,
            "provider_decision": self.root / "provider-decision.json",
            "cost_ledger": self.root / "cost-ledger.json",
        }
        additional = {name: path for name, path in additional.items() if path.is_file()}
        if release_output.exists():
            try:
                verify_release_delivery_pack(
                    release_output, video=output, cover=cover,
                    publishing_copy=publishing_copy, privacy_audit=privacy_report,
                    rights_report=rights_report, publication_authorization=authorization,
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self._action_required(
                    "delivery_qa",
                    "Existing release pack is stale, tampered, or no longer authorized",
                    [{"owner": "user", "expected_artifact": str(release_output),
                      "reason": str(error)}],
                )
        else:
            create_release_delivery_pack(
                video=output, cover=cover, publishing_copy=publishing_copy,
                privacy_audit=privacy_report, rights_report=rights_report,
                publication_authorization=authorization, output_dir=release_output,
                additional_artifacts=additional,
                project_root=self.context.root,
            )
        return [doctor_path, *artifacts, privacy_report, rights_report,
                release_output / "release-pack.json"]

    def stage_delivery_qa(self) -> None:
        output = self.delivery_qa_output
        if not output.is_file():
            self._action_required(
                "delivery_qa",
                "The single universal final video is not present",
                [{"owner": "ffmpeg", "capability": "final composition, audio mix, encoding and decode QA",
                  "expected_artifact": str(output), "platform_validations": ["douyin", "wechat_channels"]}],
            )
        readiness_errors = validate_required_asset_readiness(
            self.project, self.state.get("stages") or {},
        )
        if readiness_errors:
            self._action_required(
                "delivery_qa",
                "Required delivery assets are not deliverable",
                [{"owner": "director", "readiness_errors": readiness_errors}],
            )
        storyboard_path = self.full_hyperframes_project / "storyboard.json"
        final_review_path = self.root / "final-qa" / "aesthetic-review.json"
        audio_plan_path = self.full_hyperframes_project / "audio-plan.json"
        cover_value = self.project.get("delivery", {}).get("cover", "exports/cover-portrait.png")
        cover_path = Path(str(cover_value))
        if not cover_path.is_absolute():
            cover_path = (self.context.root / cover_path).resolve()
        cover_review_path = self.root / "final-qa" / "cover-review.json"
        cover_required = asset_is_required(self.project, "cover")
        cover_applicable = cover_required or cover_path.is_file()
        final_edit_correctness_path = self.video_use_dir / "final-edit-correctness.json"
        platform_paths = {
            name: self.root / "final-qa" / f"platform-{name}.json"
            for name in ("douyin", "wechat_channels")
        }
        self._ensure_platform_validations(output, cover_path, platform_paths)
        media_report_path = (
            self.manual_finish_dir / "manual-final-media-report.json"
            if self.manual_finish_active else self.root / "final-media-report.json"
        )
        manual_required = [
            self.manual_handoff_manifest_path,
            self.manual_finish_dir / "correction-ledger.json",
            self.manual_finish_dir / "return-receipt.json",
            self.manual_finish_dir / "manual-final-qa.json",
        ] if self.manual_finish_active else []
        sample_dynamics_path = self.root / "sample-qa" / "visual-dynamics-qa.json"
        full_dynamics_path = self.root / "full-qa" / "visual-dynamics-qa.json"
        provider_decision_path = self.root / "provider-decision.json"
        cost_ledger_path = self.root / "cost-ledger.json"
        regression_path = self.root / "full-qa" / "editorial-regression.json"
        regression_required = (
            [regression_path]
            if self.project.get("editorial_regression", {}).get("enabled") is True else []
        )
        required = [storyboard_path, final_review_path, audio_plan_path,
                     final_edit_correctness_path,
                    media_report_path, self.production_contract_path,
                    sample_dynamics_path, full_dynamics_path,
                    provider_decision_path, cost_ledger_path, *regression_required,
                     *manual_required, *platform_paths.values()]
        compose_plan_path = self.root / "final-compose-command.json"
        if compose_plan_path.is_file():
            compose_plan = read_json(compose_plan_path)
            caption_sync_closure_enabled = (
                ((self.project.get("editing") or {}).get("caption_sync_closure") or {})
                .get("enabled") is True
            )
            if (
                caption_sync_closure_enabled
                and (compose_plan.get("caption_delivery") or {}).get("mode") == "burned_in_last"
            ):
                required.append(self.video_use_dir / "caption-sync-final.json")
        if cover_applicable:
            required.extend([cover_path, cover_review_path])
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            self._action_required(
                "delivery_qa",
                "Final delivery evidence is incomplete",
                [{"owner": "director", "capability": "blocking final aesthetic, audio, cover and platform QA",
                  "missing_artifacts": missing}],
            )
        final_review = read_json(final_review_path)
        self._validate_current_production_contract()
        self._validate_provider_governance(require_reconciled=True)
        if regression_required:
            regression = read_json(regression_path)
            baseline_path = self.root / "editorial-regression" / "golden-baseline.json"
            if not baseline_path.is_file():
                raise DirectorContractError("golden editorial baseline is missing")
            assert_valid(
                validate_regression(regression, read_json(baseline_path)),
                "golden editorial regression",
            )
            if regression.get("status") != "pass":
                raise DirectorContractError("golden editorial regression did not pass")
        for label, path, scoped_storyboard, scoped_brief in (
            ("sample", sample_dynamics_path,
             self.sample_hyperframes_project / "storyboard.json", self.semantic_brief_path),
            ("full", full_dynamics_path, storyboard_path, self.full_semantic_brief_path),
        ):
            dynamics = read_json(path)
            assert_valid(
                validate_visual_dynamics_report(
                    dynamics, scoped_storyboard, scoped_brief,
                    config=self.project.get("qa", {}).get("visual_dynamics", {}),
                    production_contract_path=self.production_contract_path,
                ),
                f"{label} visual dynamics QA",
            )
            if dynamics.get("status") != "pass":
                raise DirectorContractError(f"{label} visual dynamics QA did not pass")
        assert_valid(
            validate_aesthetic_review(
                final_review, read_json(storyboard_path),
                decision_complete=self.project.get("motion_quality", {}).get("enabled") is True,
            ),
            "final aesthetic QA",
        )
        output_hash = sha256_file(output)
        if final_review.get("reviewed_output_sha256") != output_hash:
            raise DirectorContractError(
                "final aesthetic review must be bound to the exact universal output hash"
            )
        final_sync_path = self.video_use_dir / "caption-sync-final.json"
        if final_sync_path.is_file() and (
            ((self.project.get("editing") or {}).get("caption_sync_closure") or {})
            .get("enabled") is True
        ):
            final_sync = read_json(final_sync_path)
            composite = final_sync.get("final_composite") or {}
            caption_source = self.video_use_dir / "master.srt"
            if (
                final_sync.get("passed") is not True
                or composite.get("passed") is not True
                or composite.get("media_sha256") != output_hash
                or not caption_source.is_file()
                or composite.get("caption_sha256") != sha256_file(caption_source)
            ):
                raise DirectorContractError(
                    "final caption synchronization closure is missing or stale"
                )
        assert_valid(
            validate_video_use_final_correctness(
                read_json(final_edit_correctness_path),
                output_path=output,
                edl=read_json(self.video_use_dir / "edl.json"),
            ),
            "video-use final edit correctness",
        )
        audio_plan = read_json(audio_plan_path)
        assert_valid(
            validate_audio_plan(
                audio_plan,
                read_json(storyboard_path),
                self.project,
                base_dir=self.full_hyperframes_project,
            ),
            "final audio QA",
        )
        audio_assets = _audio_plan_asset_files(audio_plan, self.full_hyperframes_project)
        cover_hash = sha256_file(cover_path) if cover_path.is_file() else None
        if cover_applicable:
            cover_review = read_json(cover_review_path)
            if cover_review.get("cover_sha256") != cover_hash:
                raise DirectorContractError("cover review must be bound to the exact cover hash")
            cover_errors, identity_required = _cover_delivery_gate(cover_review)
            if cover_errors:
                raise DirectorContractError("cover review failed: " + "; ".join(cover_errors))
            if identity_required and cover_review.get("identity_approved_by_user") is not True:
                self._action_required(
                    "delivery_qa",
                    "Cover likeness requires explicit user approval",
                    [{
                        "owner": "user",
                        "capability": "approve whether the regenerated cover is sufficiently faithful to their identity",
                        "cover": str(cover_path),
                        "review": str(cover_review_path),
                    }],
                )
            if cover_review.get("status") != "pass":
                raise DirectorContractError("approved cover review must have pass status")
        media_report = read_json(media_report_path)
        assert_valid(validate_technical_report(media_report, output), "final technical media QA")
        for name, path in platform_paths.items():
            platform = read_json(path)
            assert_valid(validate_platform_report(platform, output, cover_path), f"{name} platform QA")
        report = self.root / "delivery-contract.json"
        write_json(report, {"schema_version": 1, "universal_video": str(output),
                            "file_sha256": output_hash, "duplicate_platform_mp4s": False,
                            "validated_same_file_for": list(platform_paths),
                             "cover": str(cover_path) if cover_applicable else None,
                             "cover_sha256": cover_hash,
                             "cover_applicability": (
                                 "required" if cover_required else
                                 "optional_present" if cover_applicable else "optional_unavailable"
                             ),
                             "audio_plan": str(audio_plan_path),
                             "production_contract": str(self.production_contract_path),
                             "production_contract_sha256": sha256_file(self.production_contract_path),
                             "sample_visual_dynamics_sha256": sha256_file(sample_dynamics_path),
                             "full_visual_dynamics_sha256": sha256_file(full_dynamics_path),
                             "provider_decision_sha256": sha256_file(provider_decision_path),
                             "cost_ledger_sha256": sha256_file(cost_ledger_path),
                             "editorial_regression_sha256": (
                                 sha256_file(regression_path) if regression_required else "disabled"
                             ),
                             "automatic_master": str(self.delivery_output),
                            "manual_finish": self.manual_finish_active})
        optional_delivery = self._build_optional_delivery_packages(
            output=output, cover=cover_path, delivery_contract=report,
            required_evidence=required,
        )
        delivery_artifacts = [output, report, *required,
                                       *optional_delivery,
                                       *_review_evidence_files(final_review)]
        delivery_artifacts.extend(audio_assets)
        self._complete("delivery_qa", delivery_artifacts)
        self.state.update({"status": "complete", "current_stage": None})
        self._save()

    def _ensure_platform_validations(
        self, output: Path, cover: Path, platform_paths: dict[str, Path],
    ) -> None:
        """Generate reports only when execution is authorized; never duplicate the MP4."""
        output_hash = sha256_file(output)
        cover_hash = sha256_file(cover) if cover.is_file() else None
        for platform, report_path in platform_paths.items():
            if report_path.is_file():
                existing = read_json(report_path)
                if (
                    existing.get("status") == "pass"
                    and existing.get("file_sha256") == output_hash
                    and existing.get("cover_sha256") == cover_hash
                    and not validate_platform_report(existing, output, cover)
                ):
                    continue
            if not self.execute_external:
                continue
            command = [
                sys.executable, str(Path(__file__).with_name("validate_platform_export.py")),
                "--media", str(output), "--platform", platform,
                "--out", str(report_path),
                "--evidence-dir", str(self.root / "final-qa" / "platform-evidence"),
            ]
            if cover.is_file():
                command.extend(["--cover", str(cover)])
            result = subprocess.run(command, cwd=self.context.root, capture_output=True, text=True)
            if result.returncode != 0:
                raise DirectorContractError(
                    f"{platform} validation failed: {str(result.stderr).strip()}"
                )

    def run(self, until: str | None = None) -> int:
        handlers: dict[str, Callable[[], None]] = {
            "inspect": self.stage_inspect,
            "provider_governance": self.stage_provider_governance,
            "video_use_timeline": self.stage_video_use_timeline,
            "evidence_acquisition": self.stage_evidence_acquisition,
            "semantic_brief": self.stage_semantic_brief,
            "production_contract": self.stage_production_contract,
            "brand_motion_playbook": self.stage_brand_motion_playbook,
            "hyperframes_storyboard": self.stage_hyperframes_storyboard,
            "audio": self.stage_audio,
            "cover": self.stage_cover,
            "sample_qa": self.stage_sample_qa,
            "preview_approval": self.stage_preview_approval,
            "full_hyperframes_storyboard": self.stage_full_hyperframes_storyboard,
            "full_hyperframes_qa": self.stage_full_hyperframes_qa,
            "final_render": self.stage_final_render,
            "final_compose": self.stage_final_compose,
            "derived_content": self.stage_derived_content,
            "manual_finish_handoff": self.stage_manual_finish_handoff,
            "delivery_qa": self.stage_delivery_qa,
        }
        for stage in STAGES:
            if self.state["stages"][stage]["status"] == "complete":
                if stage == until:
                    break
                continue
            self._start(stage)
            try:
                handlers[stage]()
            except DirectorContractError as error:
                if self.state["stages"][stage]["status"] == "running":
                    self._fail(stage, error)
                print(f"stage {stage}: {error}", file=sys.stderr)
                print(self.state_path)
                return 2
            except Exception as error:  # state must retain the exact failing stage
                self._fail(stage, error)
                print(f"stage {stage}: {error}", file=sys.stderr)
                print(self.state_path)
                return 1
            print(f"complete: {stage}")
            if stage == until:
                break
        print(self.state_path)
        return 0


def video_use_root_command(source_video: Path, edit_dir: Path) -> list[str]:
    helper = render_helper_path().with_name("transcribe.py")
    return [sys.executable, str(helper), str(source_video), "--edit-dir", str(edit_dir)]


def open_studio(director: Director, *, full: bool) -> Path:
    project = director.full_hyperframes_project if full else director.sample_hyperframes_project
    if not (project / "index.html").is_file():
        raise DirectorContractError(f"HyperFrames project is not ready: {project}")
    executable = shutil.which("npx") or shutil.which("npx.cmd")
    if not executable:
        raise DirectorContractError("npx is not available; HyperFrames Studio cannot be opened")
    command = [executable, "hyperframes", "preview", "."]
    process = subprocess.Popen(command, cwd=project)
    record = director.root / "studio-session.json"
    write_json(record, {
        "schema_version": 1, "scope": "full" if full else "sample",
        "project": str(project), "command": command, "pid": process.pid,
        "started_at": utc_now(),
    })
    return record


def reset_stage(state_path: Path, stage: str) -> None:
    if stage not in STAGES:
        raise DirectorContractError(f"unknown stage: {stage}")
    state = read_json(state_path)
    start = STAGES.index(stage)
    for name in STAGES[start:]:
        state["stages"][name] = _stage_template()
    state.update({"status": "active", "current_stage": None, "updated_at": utc_now()})
    write_json(state_path, state)
    action_path = state_path.with_name("action-required.json")
    if action_path.is_file():
        try:
            action_stage = read_json(action_path).get("stage")
        except (OSError, json.JSONDecodeError):
            action_stage = None
        if action_stage in STAGES and STAGES.index(str(action_stage)) >= start:
            action_path.unlink(missing_ok=True)


def approve_sample(
    director: Director, approved_by: str, *, publish_willingness: str | None = None,
    baseline_preference: str | None = None, review_reason: str | None = None,
) -> Path:
    """Record explicit approval of the exact sample evidence currently on disk."""
    if director.state.get("stages", {}).get("sample_qa", {}).get("status") != "complete":
        raise DirectorContractError("sample_qa must be complete before sample approval")
    storyboard = director.sample_hyperframes_project / "storyboard.json"
    review = director.root / "sample-qa" / "aesthetic-review.json"
    gate = director.root / "sample-qa" / "gate-report.json"
    required = (storyboard, review, gate)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise DirectorContractError("sample approval evidence is missing: " + ", ".join(missing))
    if read_json(gate).get("passed") is not True:
        raise DirectorContractError("sample aesthetic gate must pass before approval")
    approver = approved_by.strip()
    if not approver:
        raise DirectorContractError("approved_by is required")
    creative_review_path: Path | None = None
    if director.project.get("motion_quality", {}).get("enabled") is True:
        if approver.lower() in {"user", "agent", "director", "renderer", "multimodal-agent"}:
            raise DirectorContractError(
                "Motion Quality paired review requires the explicit human reviewer's identity"
            )
        director._ensure_creative_review()
        creative_review_path = director.creative_review_path
        if publish_willingness not in {"yes", "no", "unsure"}:
            raise DirectorContractError(
                "Motion Quality sample approval requires --publish-willingness yes|no|unsure"
            )
        if baseline_preference not in {"baseline", "candidate", "tie"}:
            raise DirectorContractError(
                "Motion Quality sample approval requires --preference baseline|candidate|tie"
            )
        if not review_reason or not review_reason.strip():
            raise DirectorContractError(
                "Motion Quality sample approval requires --review-reason"
            )
        paired_review = record_creative_user_decision(
            read_json(creative_review_path), decision="approved", reviewer=approver,
            publish_willingness=publish_willingness,
            baseline_preference=baseline_preference,
            reason=review_reason,
        )
        errors = validate_creative_review(
            paired_review,
            motion_design_contract_path=(
                director.motion_design_dir("sample") / "motion-design-contract.json"
            ),
            storyboard_path=storyboard,
            keyframe_receipt_paths=director._creative_review_receipts(),
            motion_audio_decisions_path=director.creative_review_motion_audio_path,
            authorized_user_reviewers={approver},
        )
        if errors:
            raise DirectorContractError(
                "paired creative review approval is invalid:\n- " + "\n- ".join(errors)
            )
        write_json(creative_review_path, paired_review)
        generate_dashboard(
            project_root=director.context.root,
            director_root=director.root,
            output=director.creative_review_dashboard_path,
            creative_review_path=creative_review_path,
            motion_design_contract_path=(
                director.motion_design_dir("sample") / "motion-design-contract.json"
            ),
        )
    baseline_path = director.root / "editorial-regression" / "golden-baseline.json"
    baseline_sha256 = "disabled"
    if director.project.get("editorial_regression", {}).get("enabled") is True:
        current_cover = director.root / "cover-contract.json"
        approved_cover = director.root / "editorial-regression" / "approved-cover-contract.json"
        cover_input = None
        if current_cover.is_file():
            approved_cover.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_cover, approved_cover)
            cover_input = approved_cover
        baseline = create_baseline(
            storyboard_path=storyboard,
            semantic_brief_path=director.semantic_brief_path,
            audio_plan_path=director.sample_hyperframes_project / "audio-plan.json",
            cover_plan_path=cover_input,
            correction_ledger_path=(
                director.manual_finish_dir / "correction-ledger.json"
                if (director.manual_finish_dir / "correction-ledger.json").is_file() else None
            ),
            approved_by=approver,
            output=baseline_path,
            renderer_export_path=(
                director.renderer_export_path("sample")
                if director.project.get("motion_quality", {}).get("enabled") is True else None
            ),
            keyframe_receipt_paths=(
                list(director._creative_review_receipts().values())
                if director.project.get("motion_quality", {}).get("enabled") is True else ()
            ),
            motion_audio_decisions_path=(
                director.motion_audio_decision_manifest_path
                if director.motion_audio_decision_manifest_path.is_file() else None
            ),
        )
        assert_valid(validate_baseline(baseline), "golden editorial baseline")
        baseline_sha256 = sha256_file(baseline_path)
    path = director.root / "preview-approval.json"
    approval_payload = {
        "schema_version": 1,
        "approved": True,
        "approved_by": approver,
        "approved_at": utc_now(),
        "scope": "exact 60-90 second sample evidence only; final render remains separately gated",
        "sample_project": str(director.sample_hyperframes_project),
        "storyboard_sha256": sha256_file(storyboard),
        "aesthetic_review_sha256": sha256_file(review),
        "gate_report_sha256": sha256_file(gate),
        "golden_baseline": str(baseline_path) if baseline_sha256 != "disabled" else None,
        "golden_baseline_sha256": baseline_sha256,
    }
    if creative_review_path is not None:
        approval_payload.update({
            "creative_review": str(creative_review_path),
            "creative_review_sha256": sha256_file(creative_review_path),
        })
    write_json(path, approval_payload)
    reset_stage(director.state_path, "preview_approval")
    director.action_path.unlink(missing_ok=True)
    return path


def authorize_final_render(director: Director, authorized_by: str) -> Path:
    """Authorize rendering only for the exact full project that passed strict QA."""
    if director.state.get("stages", {}).get("full_hyperframes_qa", {}).get("status") != "complete":
        raise DirectorContractError("full_hyperframes_qa must be complete before final render authorization")
    approver = authorized_by.strip()
    if not approver:
        raise DirectorContractError("authorized_by is required")
    storyboard = director.full_hyperframes_project / "storyboard.json"
    vocabulary = director.full_hyperframes_project / "visual-vocabulary-audit.json"
    commands = director.root / "full-hyperframes-commands.json"
    qa_evidence = director.root / "full-qa" / "verified-evidence.json"
    required = (storyboard, vocabulary, commands, qa_evidence)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise DirectorContractError("final render authorization evidence is missing: " + ", ".join(missing))
    path = director.root / "final-render-authorization.json"
    write_json(path, {
        "schema_version": 1,
        "authorized": True,
        "authorized_by": approver,
        "authorized_at": utc_now(),
        "scope": "exact strict-checked full HyperFrames project only",
        "full_project": str(director.full_hyperframes_project),
        "storyboard_sha256": sha256_file(storyboard),
        "visual_vocabulary_sha256": sha256_file(vocabulary),
        "commands_sha256": sha256_file(commands),
        "full_qa_evidence_sha256": sha256_file(qa_evidence),
    })
    reset_stage(director.state_path, "final_render")
    director.action_path.unlink(missing_ok=True)
    return path


_CORRECTION_PROPERTIES = {
    "approve": "approved",
    "reject": "approved",
    "move": "position",
    "resize": "scale",
    "hide": "visible",
    "change_variant": "variant",
    "change_anchor": "anchor",
    "change_sfx": "sfx",
    "request_regeneration": "regeneration_requested",
}


def apply_review_correction(
    director: Director, proposal_path: Path, *, approved_by: str,
) -> Path:
    """Approve one pending browser proposal into the auditable correction ledger."""
    approver = approved_by.strip()
    if not approver:
        raise DirectorContractError("approved_by is required")
    proposal_path = proposal_path.resolve()
    project_root = director.context.root.resolve()
    if not proposal_path.is_relative_to(project_root) or not proposal_path.is_file():
        raise DirectorContractError("correction proposal must be inside the project")
    proposal = read_json(proposal_path)
    if proposal.get("status") != "pending" or proposal.get("applied") is not False:
        raise DirectorContractError("correction proposal is not pending")
    action = str(proposal.get("action") or "")
    if action not in _CORRECTION_PROPERTIES:
        raise DirectorContractError("correction proposal action is unsupported")
    target = Path(str(proposal.get("target_path") or "")).resolve()
    if not target.is_relative_to(project_root) or not target.is_file():
        raise DirectorContractError("correction target must be an existing project file")
    if proposal.get("target_sha256") != sha256_file(target):
        raise DirectorContractError("correction target hash is stale")
    related_files: list[Path] = []
    for index, row in enumerate(proposal.get("related_files") or []):
        path = Path(str((row or {}).get("path") or "")).resolve()
        if not path.is_relative_to(project_root) or not path.is_file():
            raise DirectorContractError(f"correction related_files[{index}] is invalid")
        if (row or {}).get("sha256") != sha256_file(path):
            raise DirectorContractError(f"correction related_files[{index}] hash is stale")
        related_files.append(path)
    if not related_files:
        raise DirectorContractError("correction proposal requires related file hashes")
    ledger_path = director.manual_finish_dir / "correction-ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if not ledger_path.is_file():
        new_ledger(ledger_path, project_root=project_root)
    correction = append_correction(
        ledger_path,
        event_id=str(proposal.get("event_id") or "").strip(),
        target_file=target,
        selector=str(proposal.get("selector") or "").strip() or None,
        property_name=_CORRECTION_PROPERTIES[action],
        before_value=proposal.get("before_value"),
        after_value=proposal.get("after_value"),
        reason=str(proposal.get("reason") or "").strip(),
        approved_by=approver,
        approved_at=utc_now(),
        related_files=related_files,
    )
    proposal.update({
        "status": "applied", "applied": True,
        "approved_by": approver, "approved_at": correction["approved_at"],
        "correction_id": correction["correction_id"],
        "ledger": str(ledger_path), "ledger_sha256": sha256_file(ledger_path),
    })
    learning = director.project.get("preferences", {}).get("learning", {})
    if learning.get("enabled") is True:
        scope = str(learning.get("default_scope") or "video")
        report = build_preference_candidates(
            validate_ledger(ledger_path),
            video_id=str(director.project.get("video_id") or project_root.name),
            scope=scope,
            scope_key=(
                str(learning.get("scope_key") or "").strip() or None
            ),
            cross_project_approved_by=(
                str(learning.get("cross_project_approved_by") or "").strip() or None
            ),
        )
        minimum = int(learning.get("minimum_samples", 2))
        for candidate in report["candidates"]:
            candidate["minimum_samples"] = minimum
            candidate["eligible_for_approval"] = candidate["sample_count"] >= minimum
        candidate_path = director.root / "preferences" / "preference-candidates.json"
        write_preference_candidates(candidate_path, report)
        proposal["preference_candidates"] = str(candidate_path)
        proposal["preference_candidates_sha256"] = sha256_file(candidate_path)
    write_json(proposal_path, proposal)
    invalidation_path = director.root / "event-correction-invalidation.json"
    write_json(invalidation_path, {
        "schema_version": 1,
        "event_id": correction["event_id"],
        "action": action,
        "correction_id": correction["correction_id"],
        "target_sha256": sha256_file(target),
        "invalidated_stage": "audio" if action == "change_sfx" else "full_hyperframes_storyboard",
        "event_level_cache_must_recompute": True,
    })
    reset_stage(
        director.state_path,
        "audio" if action == "change_sfx" else "full_hyperframes_storyboard",
    )
    director.action_path.unlink(missing_ok=True)
    return ledger_path


def build_next_action_summary(director: Director) -> dict[str, Any]:
    """Return one creator-facing next action instead of the full internal state tree."""
    if director.action_path.is_file():
        packet = validate_action_packet(director.action_path)
        actions = packet.get("actions") or []
        first = actions[0] if actions else {}
        return {
            "status": "action_required",
            "stage": str(packet.get("stage") or director.state.get("current_stage") or "unknown"),
            "readiness": "action_required",
            "reason": str(packet.get("reason") or "human or delegated work is required"),
            "owner": str(first.get("owner") or packet.get("owner") or "user"),
            "instruction": str(first.get("instruction") or "review the action packet"),
            "command": first.get("command") or [],
            "expected_outputs": [str(value) for value in (first.get("expected_outputs") or [])],
            "additional_action_count": max(0, len(actions) - 1),
            "action_packet": str(director.action_path.resolve()),
            "resume_command": str(packet.get("resume_command") or ""),
        }
    stages = director.state.get("stages") or {}
    next_stage = next(
        (name for name in STAGES if stages.get(name, {}).get("status") != "complete"),
        None,
    )
    if next_stage is None:
        return {
            "status": "complete", "stage": None, "readiness": "delivery_ready",
            "instruction": "Workflow is complete; review the universal delivery and release evidence.",
        }
    row = stages.get(next_stage, {})
    lifecycle = str(row.get("status") or "pending")
    common = {
        "stage": next_stage,
        "readiness": str(row.get("readiness") or lifecycle),
        "owner": "director",
    }
    if lifecycle == "failed":
        return {
            **common,
            "status": "failed",
            "reason": str(row.get("error") or f"{next_stage} failed"),
            "instruction": "Resolve the reported failure, then reset or resume this stage.",
            "command": [],
        }
    if lifecycle == "action_required":
        return {
            **common,
            "status": "action_required",
            "reason": str(row.get("error") or "the action packet is missing or unavailable"),
            "instruction": "Restore or recreate the action packet before resuming.",
            "command": [],
        }
    if lifecycle == "running":
        return {
            **common,
            "status": "running",
            "instruction": f"{next_stage} is currently running; inspect status before retrying.",
            "command": [],
        }
    return {
        **common,
        "status": "ready_to_run",
        "instruction": f"Run or resume the workflow at {next_stage}.",
        "command": [
            sys.executable, str(Path(__file__).resolve()), "run",
            "--project", str(director.context.project_file), "--resume",
        ],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-project", help="initialize a project without overwriting")
    init.add_argument("--root", required=True)
    init.add_argument("--video-id", required=True)
    init.add_argument("--source", default=".")
    init.add_argument("--preset", choices=sorted(PROJECT_PRESETS), default="auto")
    init.add_argument("--title")
    init.add_argument("--profile")
    doctor = sub.add_parser("doctor", help="inspect the local toolchain without changing it")
    doctor.add_argument("--out")
    preflight = sub.add_parser("preflight", help="inspect one project without changing it")
    preflight.add_argument("--project", required=True)
    preflight.add_argument("--out")
    run = sub.add_parser("run", help="run or resume the workflow")
    run.add_argument("--project", required=True)
    run.add_argument("--resume", action="store_true", help="document intent; completed stages are always resumed")
    run.add_argument("--until", choices=STAGES)
    run.add_argument("--approve-final-render", action="store_true")
    run.add_argument("--execute-external", action="store_true",
                     help="execute approved external renderer commands; otherwise only validate artifacts")
    resume = sub.add_parser("resume", help="continue from the last verified stage")
    resume.add_argument("--project", required=True)
    resume.add_argument("--until", choices=STAGES)
    resume.add_argument("--execute-external", action="store_true")
    status = sub.add_parser("status", help="print current resumable state")
    status.add_argument("--project", required=True)
    next_action = sub.add_parser("next", help="print only the current creator-facing next action")
    next_action.add_argument("--project", required=True)
    approve = sub.add_parser("approve-sample", help="approve the exact current sample evidence")
    approve.add_argument("--project", required=True)
    approve.add_argument("--approved-by", default="user")
    approve.add_argument("--publish-willingness", choices=("yes", "no", "unsure"))
    approve.add_argument("--preference", choices=("baseline", "candidate", "tie"))
    approve.add_argument("--review-reason")
    authorize = sub.add_parser("authorize-final-render", help="authorize the exact full project that passed QA")
    authorize.add_argument("--project", required=True)
    authorize.add_argument("--authorized-by", default="user")
    approve_alias = sub.add_parser("approve", help="approve the exact current sample evidence")
    approve_alias.add_argument("--project", required=True)
    approve_alias.add_argument("--approved-by", default="user")
    approve_alias.add_argument("--publish-willingness", choices=("yes", "no", "unsure"))
    approve_alias.add_argument("--preference", choices=("baseline", "candidate", "tie"))
    approve_alias.add_argument("--review-reason")
    authorize_alias = sub.add_parser("authorize-render", help="authorize the exact checked full render")
    authorize_alias.add_argument("--project", required=True)
    authorize_alias.add_argument("--authorized-by", default="user")
    for name in ("open-preview", "open-studio"):
        open_command = sub.add_parser(name, help="open the editable HyperFrames Studio")
        open_command.add_argument("--project", required=True)
        open_command.add_argument("--full", action="store_true")
    deliver = sub.add_parser("deliver", help="run all authorized local/external stages to delivery")
    deliver.add_argument("--project", required=True)
    review = sub.add_parser("review", help="generate a local read-only Director evidence dashboard")
    review.add_argument("--project", required=True)
    review.add_argument("--output")
    review.add_argument("--interactive", action="store_true",
                        help="serve the optional localhost-only proposal API")
    review.add_argument("--host")
    review.add_argument("--port", type=int)
    apply_correction_command = sub.add_parser(
        "apply-correction", help="approve one pending review proposal into the correction ledger",
    )
    apply_correction_command.add_argument("--project", required=True)
    apply_correction_command.add_argument("--proposal", required=True)
    apply_correction_command.add_argument("--approved-by", required=True)
    metrics = sub.add_parser("import-metrics", help="import a user-exported platform metrics file")
    metrics.add_argument("--project", required=True)
    metrics.add_argument("--input", required=True)
    metrics.add_argument("--out")
    reset = sub.add_parser("reset-stage", help="invalidate a stage and all downstream stages")
    reset.add_argument("--project", required=True)
    reset.add_argument("--stage", required=True, choices=STAGES)
    return root


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init-project":
        project_file = initialize_project(
            args.root, args.video_id, args.source, preset=args.preset,
            title=args.title, profile=args.profile,
        )
        print(project_file)
        return 0
    if args.command == "doctor":
        report = run_doctor()
        if args.out:
            write_json(Path(args.out), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 2
    if args.command == "preflight":
        report = run_preflight(args.project)
        if args.out:
            write_json(Path(args.out), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 2
    deliver = args.command == "deliver"
    director = Director(Path(args.project),
                        approve_final_render=getattr(args, "approve_final_render", False) or deliver,
                        execute_external=getattr(args, "execute_external", False) or deliver)
    if args.command == "status":
        print(json.dumps(director.state, ensure_ascii=False, indent=2))
        return 0
    if args.command == "next":
        print(json.dumps(build_next_action_summary(director), ensure_ascii=False, indent=2))
        return 0
    if args.command == "review":
        configured = director.project.get("review", {}).get("dashboard", {})
        if configured.get("enabled", True) is not True:
            raise DirectorContractError("review.dashboard.enabled must be true")
        interactive = director.project.get("review", {}).get("interactive", {})
        if args.interactive and interactive.get("enabled") is not True:
            raise DirectorContractError("review.interactive.enabled must be true")
        output = Path(args.output).resolve() if args.output else director.root / "review" / "index.html"
        server = None
        interactive_api_url = None
        if args.interactive:
            host = args.host or str(interactive.get("host") or "127.0.0.1")
            port = args.port if args.port is not None else int(interactive.get("port", 8765))
            config = ReviewServerConfig(
                root=director.context.root,
                proposal_dir=director.root / "review" / "proposals",
                auth_token=os.environ.get("DIRECTOR_REVIEW_TOKEN", ""),
                csrf_token=os.environ.get("DIRECTOR_REVIEW_CSRF_TOKEN", ""),
                max_body_bytes=int(interactive.get("max_body_bytes", 64 * 1024)),
                allow_file_origin=True,
            )
            server = create_review_server(config, host=host, port=port)
            url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
            interactive_api_url = f"http://{url_host}:{server.server_port}/api/proposals"
        try:
            dashboard = generate_dashboard(
                project_root=director.context.root, director_root=director.root, output=output,
                creative_review_path=(
                    director.creative_review_path if director.creative_review_path.is_file() else None
                ),
                motion_design_contract_path=(
                    director.motion_design_dir("sample") / "motion-design-contract.json"
                    if (director.motion_design_dir("sample") / "motion-design-contract.json").is_file()
                    else None
                ),
                interactive_api_url=interactive_api_url,
            )
            print(dashboard)
            if server is not None:
                print(interactive_api_url)
                server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if server is not None:
                server.server_close()
        return 0
    if args.command == "apply-correction":
        print(apply_review_correction(
            director, Path(args.proposal), approved_by=args.approved_by,
        ))
        return 0
    if args.command == "reset-stage":
        reset_stage(director.state_path, args.stage)
        print(director.state_path)
        return 0
    if args.command in {"approve-sample", "approve"}:
        print(approve_sample(
            director, args.approved_by,
            publish_willingness=args.publish_willingness,
            baseline_preference=args.preference,
            review_reason=args.review_reason,
        ))
        return 0
    if args.command in {"authorize-final-render", "authorize-render"}:
        print(authorize_final_render(director, args.authorized_by))
        return 0
    if args.command in {"open-preview", "open-studio"}:
        print(open_studio(director, full=args.full))
        return 0
    if args.command == "import-metrics":
        configured = director.project.get("feedback", {}).get("metrics_import", {})
        if configured.get("enabled") is not True:
            raise DirectorContractError("feedback.metrics_import.enabled must be true")
        learning = director.project.get("feedback", {}).get("learning_loop", {})
        source = Path(args.input).resolve()
        if learning.get("enabled") is not True:
            output = Path(args.out).resolve() if args.out else director.root / "post-publish-metrics.json"
            import_post_publish_metrics(source, output)
            print(output)
            return 0
        release_dir = director._optional_project_path(
            director.project.get("delivery", {}).get("release_pack", {}).get("output_dir")
            or "exports/release-pack"
        )
        release_manifest = release_dir / "release-pack.json" if release_dir else None
        storyboard = director.full_hyperframes_project / "storyboard.json"
        delivery_contract = director.root / "delivery-contract.json"
        required = [path for path in (release_manifest, storyboard, delivery_contract) if path]
        if len(required) != 3 or any(not path.is_file() for path in required):
            raise DirectorContractError(
                "feedback learning requires the exact release manifest, storyboard, and delivery contract"
            )
        assert release_manifest is not None
        release = read_json(release_manifest)
        bindings = release.get("release_bindings") or {}
        publication = release.get("publication") or {}
        binding = {
            "publication_id": str(publication.get("id") or ""),
            "release_manifest_sha256": sha256_file(release_manifest),
            "video_sha256": str(bindings.get("video_sha256") or ""),
            "cover_sha256": str(bindings.get("cover_sha256") or ""),
            "publishing_copy_sha256": str(bindings.get("copy_sha256") or ""),
            "motion_structure_sha256": sha256_file(storyboard),
            "version_id": sha256_file(delivery_contract)[:16],
        }
        snapshots_dir = director.root / "feedback" / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        source_hash = sha256_file(source)
        for existing in snapshots_dir.glob("*.json"):
            try:
                if read_json(existing).get("source_sha256") == source_hash:
                    raise DirectorContractError("this exported metrics file was already imported")
            except json.JSONDecodeError:
                continue
        output = (
            Path(args.out).resolve() if args.out
            else snapshots_dir / f"{source_hash[:20]}.json"
        )
        if not output.is_relative_to(snapshots_dir.resolve()):
            raise DirectorContractError(
                "feedback learning snapshot output must remain in the project feedback/snapshots directory"
            )
        import_post_publish_metrics(source, output, binding=binding)
        snapshots = sorted(snapshots_dir.glob("*.json"))
        analysis_path = director.root / "feedback" / "analysis.json"
        minimum = int(learning.get("minimum_snapshots", 2))
        if len(snapshots) >= minimum:
            analyze_feedback_snapshots(
                snapshots, analysis_path,
                min_views=int(learning.get("minimum_views", 200)),
                min_elapsed_hours=float(learning.get("minimum_elapsed_hours", 24.0)),
            )
        else:
            write_json(analysis_path, {
                "schema": "content-preserving-video-editor/feedback-loop",
                "schema_version": 1,
                "status": "insufficient_evidence",
                "snapshots_collected": len(snapshots),
                "minimum_snapshots": minimum,
                "preference_candidates": [],
                "automatic_changes": [],
            })
        print(output)
        return 0
    return director.run(getattr(args, "until", None))


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command in {"init-project", "doctor", "preflight"}:
            return _dispatch(args)
        # One mutating CLI command owns the project transaction. This prevents
        # concurrent run/reset/approve processes from losing stage transitions.
        with exclusive_file_lock(Path(args.project).resolve(), stale_seconds=24 * 3600):
            return _dispatch(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, yaml_error()) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def yaml_error():
    # Imported lazily to keep the entry's top-level dependency surface explicit.
    import yaml
    return yaml.YAMLError


if __name__ == "__main__":
    raise SystemExit(main())
