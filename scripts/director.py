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
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aesthetic_qa import validate as validate_aesthetic_review
from asr_router import choose_backend as choose_asr_backend, normalize_transcript
from audio_qa import validate as validate_audio_plan
from audio_production import produce_audio_assets
from build_motion_snapshot_plan import build_motion_sidecar, build_plan as build_motion_snapshot_plan
from capability_registry import build_capability_inventory, build_toolchain_report, capability_config
from correction_ledger import new_ledger, validate_ledger
from cover_production import CoverProductionActionRequired, produce_cover, write_cover_request
from conditional_extensions import route_extensions, run_extension_adapters
from director_adapters import AdapterExecutionError, AdapterRunner
from director_contracts import (
    STAGES,
    DirectorContractError,
    ProjectContext,
    assert_valid,
    load_project_context,
    read_json,
    sha256_file,
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
from hyperframes_router import route_hyperframes
from ip_production import IpProductionActionRequired, produce_ip_components
from manual_finish import (
    build_handoff_manifest,
    validate_returned_final_qa,
)
from media_catalog_adapter import run_media_catalog
from motion_preferences import apply as apply_motion_preferences, load as load_motion_preferences
from normalize_social_audio import (
    normalize as normalize_social_audio,
    validate_report as validate_audio_normalization_report,
)
from otio_adapter import edl_to_otio, otio_to_internal, validate_roundtrip as validate_otio_roundtrip
from post_publish_metrics import import_metrics as import_post_publish_metrics
from platform_occlusion_gate import evaluate_geometry as evaluate_platform_occlusion
from preview_render_parity import validate as validate_preview_render_parity
from render_with_cache import run_pipeline as run_cached_pipeline
from technical_qa import run_technical_qa, validate_report as validate_technical_report
from validate_platform_export import validate_bound_report as validate_platform_report
from video_use_bridge import render_command, render_helper_path


STATE_VERSION = 5
DIRECTOR_VERSION = "2.0.0"

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


def _review_evidence_files(review: dict[str, Any]) -> list[Path]:
    values: list[Any] = []
    for phases in (review.get("snapshots") or {}).values():
        if isinstance(phases, dict):
            values.extend(phases.values())
    for row in (review.get("criteria") or {}).values():
        if isinstance(row, dict):
            values.extend(row.get("evidence") or [])
    for row in (review.get("connector_geometry") or {}).values():
        if isinstance(row, dict):
            values.append(row.get("evidence"))
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if not value:
            continue
        path = Path(str(value)).resolve()
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
            "artifact_records": [], "error": None}


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
            state = read_json(self.state_path)
            if state.get("project_file") != str(self.context.project_file):
                raise DirectorContractError("director state belongs to a different project")
            stages = state.setdefault("stages", {})
            previous_state_version = int(state.get("schema_version") or 0)
            for name in STAGES:
                stages.setdefault(name, _stage_template())
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
                    "legacy state lacks contemporaneous v5 input and artifact fingerprints",
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
                    "updated_at": utc_now(), "error": None})
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

    def _complete(self, stage: str, artifacts: list[Path] | None = None) -> None:
        row = self.state["stages"][stage]
        resolved_artifacts = [path.resolve() for path in (artifacts or [])]
        row.update({"status": "complete", "updated_at": utc_now(), "error": None,
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
        packet = {
            "schema_version": 1,
            "stage": stage,
            "reason": reason,
            "actions": actions,
            "resume_command": f'"{sys.executable}" "{Path(__file__).resolve()}" run --project "{self.context.project_file}" --resume',
        }
        write_json(self.action_path, packet)
        row = self.state["stages"][stage]
        row.update({"status": "action_required", "updated_at": utc_now(), "error": reason,
                    "artifacts": [str(self.action_path.resolve())]})
        self.state["status"] = "action_required"
        self._save()
        raise DirectorContractError(reason)

    def _fail(self, stage: str, error: Exception) -> None:
        row = self.state["stages"][stage]
        row.update({"status": "failed", "updated_at": utc_now(), "error": str(error)})
        self.state["status"] = "failed"
        self._save()

    @property
    def video_use_dir(self) -> Path:
        return self.context.edit_dir / "video-use"

    @property
    def semantic_brief_path(self) -> Path:
        return self.root / "semantic-brief.json"

    @property
    def evidence_bundle_path(self) -> Path:
        return self.root / "evidence" / "evidence-bundle.json"

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
        return self.project.get("delivery", {}).get("manual_finish", {})

    @property
    def manual_finish_active(self) -> bool:
        return (
            self.manual_finish_config.get("enabled") is True
            and self.manual_finish_config.get("backend") in {"opencut", "other_nle"}
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
        if burned.get("detected") is True and float(burned.get("confidence", 0)) >= 0.52:
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
        if not transcript_path.is_file() and router_config.get("enabled") is True:
            route = choose_asr_backend(router_config, {
                "language": router_config.get("language", "zh"),
                "hotwords": router_config.get("hotwords", []),
                "speaker_count": router_config.get("speaker_count", 1),
                "precise_word_alignment": router_config.get("precise_word_alignment", False),
                "speaker_labels": router_config.get("speaker_labels", False),
            })
            write_json(route_path, route)
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
        self._complete("video_use_timeline", [edl_path, transcript_path, plan_path,
                                               media_analysis_path, edit_preflight_path,
                                               self.video_use_dir / "mapped-words.json",
                                               self.video_use_dir / "captions.json",
                                               self.video_use_dir / "master.srt", sync_report,
                                               *otio_artifacts, *([route_path] if route_path.is_file() else [])])

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
        design_tokens_path = self.context.edit_dir / "design-tokens.json"
        if isinstance(bundle.get("design_tokens"), dict):
            write_json(design_tokens_path, {
                "schema_version": 1,
                "source_evidence_bundle": str(output.resolve()),
                "source_evidence_bundle_sha256": sha256_file(output),
                **bundle["design_tokens"],
            })
            artifacts.append(design_tokens_path)
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
            inputs=[self.context.source_video, output],
            outputs=[subject_track],
            settings={"orientation": display.get("orientation"), "target_ratio": target_ratio},
        )
        if result.get("status") in {"complete", "reused"}:
            artifacts.append(subject_track)
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
        if not self.semantic_brief_path.is_file():
            bundle = read_json(self.evidence_bundle_path) if self.evidence_bundle_path.is_file() else {}
            packet = self.root / "semantic-brief-request.json"
            write_json(packet, {
                "schema_version": 2,
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
            })
            self._action_required(
                "semantic_brief",
                "LLM-authored semantic brief is required after reading the word transcript and evidence frames",
                [{"owner": "director_with_llm", "capability": "semantic visual direction",
                  "request": str(packet), "expected_artifact": str(self.semantic_brief_path)}],
            )
        brief = read_json(self.semantic_brief_path)
        assert_valid(validate_semantic_brief(brief, require_sample_variety=True), "semantic brief")
        assert_valid(validate_semantic_evidence_binding(
            brief, transcript_path=transcript, evidence_bundle_path=self.evidence_bundle_path,
        ), "semantic brief evidence binding")
        artifacts = [self.semantic_brief_path]
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
            hook_result = self._run_capability(
                "hook_pacing",
                command=[
                    sys.executable, str(Path(__file__).with_name("audit_hook_pacing.py")),
                    "--transcript", str(transcript), "--out", str(hook_path),
                ],
                inputs=[transcript, self.semantic_brief_path], outputs=[hook_path],
            )
            if hook_result.get("status") in {"complete", "reused"}:
                artifacts.append(hook_path)
            publishing_path = self.root / "publish-metadata.json"
            title = str(self.project.get("content", {}).get("title") or self.project.get("video_id", "video"))
            publishing_result = self._run_capability(
                "publishing_copy",
                command=[
                    sys.executable, str(Path(__file__).with_name("generate_publishing_copy.py")),
                    "--title", title, "--transcript", str(transcript), "--out", str(publishing_path),
                ],
                inputs=[transcript, self.semantic_brief_path], outputs=[publishing_path],
                settings={"title": title},
            )
            if publishing_result.get("status") in {"complete", "reused"}:
                artifacts.append(publishing_path)
        self._complete("semantic_brief", artifacts)

    def stage_hyperframes_storyboard(self) -> None:
        project = self.sample_hyperframes_project
        evidence = read_json(self.evidence_bundle_path) if self.evidence_bundle_path.is_file() else {}
        route_path = self.root / "renderer-route.json"
        route = route_hyperframes(self.project, evidence)
        renderer_artifacts: list[Path] = []
        catalog_report_path = self.root / "media-catalog-report.json"
        catalog = run_media_catalog(
            project=self.project, semantic_brief=read_json(self.semantic_brief_path),
            root=self.context.root, runner=self.adapter_runner, execute=self.execute_external,
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
            react_inputs = [self._project_path(value) for value in
                            (remotion.get("react_component_paths") or [])]
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
        write_json(route_path, route)
        ip_artifacts: list[Path] = []
        if self.project.get("visuals", {}).get("ip_production", {}).get("enabled") is True:
            try:
                ip_artifacts = produce_ip_components(
                    project=self.project, project_root=self.context.root,
                    semantic_brief=self.semantic_brief_path,
                    design_tokens=self.context.edit_dir / "design-tokens.json",
                    output_dir=self.context.edit_dir / "assets" / "ip-components",
                    runner=self.adapter_runner, execute_external=self.execute_external,
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
                "schema_version": 1,
                "owner": "hyperframes",
                "semantic_brief": str(self.semantic_brief_path),
                "scope": "60-90 second sample only",
                "project": str(project),
                "required_skills": ["hyperframes", "hyperframes-core", "hyperframes-creative",
                                    "hyperframes-animation", "hyperframes-cli"],
                "required_outputs": ["index.html", "storyboard.json", "frame.md", "visual-vocabulary-audit.json"],
                "motion_output": "hyperframes_render",
                "renderer_route": str(route_path),
                "route": route["route"],
                "route_capabilities": route["capability_skills"],
                "ip_component_artifacts": [str(path) for path in ip_artifacts],
                "optional_renderer_artifacts": [str(path) for path in renderer_artifacts],
                "minimum_distinct_sample_structures": 4,
                "forbidden": list(FORBIDDEN_NEW_PATHS[2:]),
            })
            self._action_required(
                "hyperframes_storyboard",
                "HyperFrames-authored storyboard and composition are required",
                [{"owner": "hyperframes", "capability": "creative direction, storyboard and animation",
                  "request": str(packet), "expected_project": str(project)}],
            )
        storyboard = read_json(storyboard_path)
        brief = read_json(self.semantic_brief_path)
        assert_valid(validate_storyboard(storyboard, brief), "HyperFrames storyboard")
        assert_valid(
            validate_visual_vocabulary_audit(read_json(vocabulary_path), storyboard),
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
        snapshot_plan = build_motion_snapshot_plan(storyboard)
        write_json(snapshot_plan_path, snapshot_plan)
        write_json(motion_sidecar_path, build_motion_sidecar(snapshot_plan))
        self._complete("hyperframes_storyboard", [storyboard_path, vocabulary_path, index_path,
                                                    command_path, route_path, snapshot_plan_path,
                                                    motion_sidecar_path, *ip_artifacts,
                                                    *renderer_artifacts])

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
            artifacts.extend(produce_audio_assets(
                storyboard=storyboard, project=self.project, project_root=self.context.root,
                output_dir=self.context.edit_dir / "audio", source_audio=self.context.source_video,
                runner=self.adapter_runner,
            ))
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
        if (self.root / "adapter-state.json").is_file():
            artifacts.append(self.root / "adapter-state.json")
        self._complete("audio", artifacts)

    def stage_cover(self) -> None:
        path = self.root / "cover-contract.json"
        if not path.is_file():
            write_json(path, {
                "schema_version": 1,
                "owner": "director",
                "default_aspect": "9:16",
                "identity": "multi-photo reference-guided regeneration; no pasted cutout",
                "expression": "natural eye contact, credible slight smile, open posture, visible energy",
                "topic_scene_required": True,
                "user_identity_approval_remains_distinct": True,
            })
        cover_config = self.project.get("cover", {})
        if cover_config.get("production", {}).get("enabled") is not True:
            self._complete("cover", [path])
            return
        if cover_config.get("enabled", True) is False:
            decision = self.root / "cover-decision.json"
            write_json(decision, {"schema_version": 1, "status": "disabled",
                                  "reason": "project explicitly disabled cover production"})
            self._complete("cover", [path, decision])
            return
        configured = self.project.get("delivery", {}).get("cover", "exports/cover-portrait.png")
        output = self._project_path(configured)
        try:
            artifacts = produce_cover(
                project=self.project, project_root=self.context.root,
                semantic_brief=self.semantic_brief_path, output=output,
                work_dir=self.context.edit_dir / "cover", runner=self.adapter_runner,
                execute_external=self.execute_external,
            )
        except CoverProductionActionRequired as error:
            request = write_cover_request(self.root / "cover-production-request.json", error.packet)
            self._action_required(
                "cover",
                "Reference-guided cinematic cover bases/reviews are required",
                [{"owner": "director_with_image_generation_and_visual_review",
                  "request": str(request), "expected_artifact": str(output)}],
            )
        self._complete("cover", [path, *artifacts])

    def stage_sample_qa(self) -> None:
        review_path = self.root / "sample-qa" / "aesthetic-review.json"
        storyboard_path = self.sample_hyperframes_project / "storyboard.json"
        audio_plan_path = self.sample_hyperframes_project / "audio-plan.json"
        if not review_path.is_file() or not audio_plan_path.is_file():
            packet = self.root / "sample-qa-request.json"
            write_json(packet, {
                "schema_version": 2,
                "owner": "director_with_human_level_visual_review",
                "sample_duration_seconds": [60, 90],
                "storyboard": str(storyboard_path),
                "audio_plan": str(audio_plan_path),
                "required_snapshots_per_event": ["entrance", "midpoint", "pre_exit", "post_exit"],
                "required_checks": [
                    "caption sync", "overlap", "overflow", "content relevance", "actual keyword focus",
                    "visual structure diversity", "motion rhythm", "UI/face/cursor safety",
                    "connector endpoints", "SFX event decisions", "SFX audibility", "BGM presence or provenance",
                ],
                "missing_artifacts": [str(path) for path in (review_path, audio_plan_path) if not path.is_file()],
                "output": str(review_path),
            })
            self._action_required(
                "sample_qa",
                "Evidence-backed 60-90 second sample QA is required; tests alone are not aesthetic approval",
                [{"owner": "director_with_visual_review", "request": str(packet),
                  "expected_artifact": str(review_path)}],
            )
        review = read_json(review_path)
        storyboard = read_json(storyboard_path)
        errors = validate_aesthetic_review(review, storyboard)
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
        report_path = self.root / "sample-qa" / "gate-report.json"
        write_json(report_path, {
            "schema_version": 2, "passed": True,
            "storyboard": str(storyboard_path), "storyboard_sha256": sha256_file(storyboard_path),
            "review": str(review_path), "review_sha256": sha256_file(review_path),
            "audio_plan": str(audio_plan_path), "audio_plan_sha256": sha256_file(audio_plan_path),
            "errors": [],
        })
        self._complete("sample_qa", [storyboard_path, review_path, audio_plan_path, report_path,
                                     *_review_evidence_files(review)])

    def stage_preview_approval(self) -> None:
        approval = self.root / "preview-approval.json"
        storyboard = self.sample_hyperframes_project / "storyboard.json"
        review = self.root / "sample-qa" / "aesthetic-review.json"
        gate = self.root / "sample-qa" / "gate-report.json"
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
        for field, path in evidence.items():
            if not path.is_file() or row.get(field) != sha256_file(path):
                raise DirectorContractError(
                    f"sample approval is stale: {field} does not match the current approved evidence"
                )
        self._complete("preview_approval", [approval])

    def _expected_timeline_duration(self) -> float:
        edl = read_json(self.video_use_dir / "edl.json")
        return sum(float(row["end"]) - float(row["start"]) for row in (edl.get("ranges") or []))

    def stage_full_hyperframes_storyboard(self) -> None:
        project = self.full_hyperframes_project
        full_brief_path = self.full_semantic_brief_path
        storyboard_path = project / "storyboard.json"
        vocabulary_path = project / "visual-vocabulary-audit.json"
        index_path = project / "index.html"
        frame_path = project / "frame.md"
        required = (storyboard_path, vocabulary_path, index_path, frame_path)
        if not full_brief_path.is_file() or any(not path.is_file() for path in required):
            packet = self.root / "full-hyperframes-request.json"
            write_json(packet, {
                "schema_version": 1,
                "owner": "hyperframes",
                "scope": "complete output timeline; never copy the sample duration as the final duration",
                "approved_sample_project": str(self.sample_hyperframes_project),
                "approved_sample_semantic_brief": str(self.semantic_brief_path),
                "full_semantic_brief": str(full_brief_path),
                "video_use_edl": str(self.video_use_dir / "edl.json"),
                "video_use_captions": str(self.video_use_dir / "captions.json"),
                "expected_duration_seconds": self._expected_timeline_duration(),
                "project": str(project),
                "renderer_route": str(self.root / "renderer-route.json"),
                "required_outputs": [full_brief_path.name, *[path.name for path in required]],
                "required_skills": ["hyperframes", "hyperframes-core", "hyperframes-creative",
                                    "hyperframes-animation", "hyperframes-cli"],
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
        assert_valid(validate_storyboard(storyboard), "full HyperFrames storyboard")
        assert_valid(
            validate_visual_vocabulary_audit(read_json(vocabulary_path), storyboard, full_video=True),
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
            audio_artifacts = produce_audio_assets(
                storyboard=storyboard_path, project=self.project, project_root=self.context.root,
                output_dir=self.context.edit_dir / "audio", source_audio=self.context.source_video,
                runner=self.adapter_runner,
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
        snapshot_plan = build_motion_snapshot_plan(storyboard)
        write_json(snapshot_plan_path, snapshot_plan)
        write_json(motion_sidecar_path, build_motion_sidecar(snapshot_plan))
        self._complete("full_hyperframes_storyboard", [full_brief_path, *required, command_path,
                                                        snapshot_plan_path, motion_sidecar_path,
                                                        *audio_artifacts])

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
        }
        review_checks = review.get("checks") or {}
        failed = sorted(name for name in required_checks if review_checks.get(name) != "pass")
        if failed:
            raise DirectorContractError("full HyperFrames snapshot review failed checks: " + ", ".join(failed))
        parity = read_json(parity_path)
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
            "strict_check_passed": True,
            "snapshot_review_passed": True,
            "preview_render_parity_passed": True,
            "platform_occlusion_passed": True if occlusion_artifacts else "disabled",
        })
        self._complete("full_hyperframes_qa", [check_path, check_receipt_path,
                                                snapshot_review_path, parity_path,
                                                evidence_path, *snapshot_paths,
                                                *parity_snapshots, *occlusion_artifacts])

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
            if cache_config.get("enabled") is True:
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
                        "outputs": [os.path.relpath(output, project_root)],
                        "command": command,
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
            else:
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
            for row in ranges[:-1]:
                cursor += float(row["end"]) - float(row["start"])
                boundaries.append(cursor)
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
        artifacts = [output, command_path, media_report]
        if normalize_enabled:
            artifacts.extend([compose_output, normalization_report])
        self._complete("final_compose", artifacts)

    def _optional_project_path(self, value: Any, *, base: Path | None = None) -> Path | None:
        if not value:
            return None
        candidate = Path(str(value))
        if candidate.is_absolute():
            return candidate.resolve()
        return ((base or self.context.root) / candidate).resolve()

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
        path = self.manual_finish_dir / "handoff-manifest.json"
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
        if not returned.is_file():
            self._action_required(
                "manual_finish_handoff",
                "A human manual finishing export is required before the workflow can continue",
                [{
                    "owner": "human_editor",
                    "backend": backend,
                    "handoff_manifest": str(manifest_path),
                    "correction_ledger": str(ledger_path),
                    "expected_artifact": str(returned),
                    "capability_boundary": (
                        "OpenCut is a human-facing option only; no CLI, MCP, Editor API, or headless "
                        "rendering capability is assumed."
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
        ])

    def stage_delivery_qa(self) -> None:
        output = self.delivery_qa_output
        if not output.is_file():
            self._action_required(
                "delivery_qa",
                "The single universal final video is not present",
                [{"owner": "ffmpeg", "capability": "final composition, audio mix, encoding and decode QA",
                  "expected_artifact": str(output), "platform_validations": ["douyin", "wechat_channels"]}],
            )
        storyboard_path = self.full_hyperframes_project / "storyboard.json"
        final_review_path = self.root / "final-qa" / "aesthetic-review.json"
        audio_plan_path = self.full_hyperframes_project / "audio-plan.json"
        cover_value = self.project.get("delivery", {}).get("cover", "exports/cover-portrait.png")
        cover_path = Path(str(cover_value))
        if not cover_path.is_absolute():
            cover_path = (self.context.root / cover_path).resolve()
        cover_review_path = self.root / "final-qa" / "cover-review.json"
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
            self.manual_finish_dir / "handoff-manifest.json",
            self.manual_finish_dir / "correction-ledger.json",
            self.manual_finish_dir / "return-receipt.json",
            self.manual_finish_dir / "manual-final-qa.json",
        ] if self.manual_finish_active else []
        required = [storyboard_path, final_review_path, audio_plan_path, cover_path,
                    cover_review_path, final_edit_correctness_path,
                    media_report_path, *manual_required, *platform_paths.values()]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            self._action_required(
                "delivery_qa",
                "Final delivery evidence is incomplete",
                [{"owner": "director", "capability": "blocking final aesthetic, audio, cover and platform QA",
                  "missing_artifacts": missing}],
            )
        final_review = read_json(final_review_path)
        assert_valid(validate_aesthetic_review(final_review, read_json(storyboard_path)), "final aesthetic QA")
        output_hash = sha256_file(output)
        if final_review.get("reviewed_output_sha256") != output_hash:
            raise DirectorContractError(
                "final aesthetic review must be bound to the exact universal output hash"
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
        cover_review = read_json(cover_review_path)
        cover_hash = sha256_file(cover_path)
        if cover_review.get("cover_sha256") != cover_hash:
            raise DirectorContractError("cover review must be bound to the exact cover hash")
        automated_cover_requirements = (
            int(cover_review.get("identity_reference_count", 0)) >= 2,
            cover_review.get("topic_relevant") is True,
            cover_review.get("natural_expression_and_energy") is True,
        )
        if not all(automated_cover_requirements):
            raise DirectorContractError("cover review failed identity-reference, topic, or expression gate")
        if cover_review.get("identity_approved_by_user") is not True:
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
                            "cover": str(cover_path), "cover_sha256": cover_hash,
                            "audio_plan": str(audio_plan_path),
                            "automatic_master": str(self.delivery_output),
                            "manual_finish": self.manual_finish_active})
        self._complete("delivery_qa", [output, cover_path, report, *required,
                                       *_review_evidence_files(final_review)])
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
            "video_use_timeline": self.stage_video_use_timeline,
            "evidence_acquisition": self.stage_evidence_acquisition,
            "semantic_brief": self.stage_semantic_brief,
            "hyperframes_storyboard": self.stage_hyperframes_storyboard,
            "audio": self.stage_audio,
            "cover": self.stage_cover,
            "sample_qa": self.stage_sample_qa,
            "preview_approval": self.stage_preview_approval,
            "full_hyperframes_storyboard": self.stage_full_hyperframes_storyboard,
            "full_hyperframes_qa": self.stage_full_hyperframes_qa,
            "final_render": self.stage_final_render,
            "final_compose": self.stage_final_compose,
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


def approve_sample(director: Director, approved_by: str) -> Path:
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
    path = director.root / "preview-approval.json"
    write_json(path, {
        "schema_version": 1,
        "approved": True,
        "approved_by": approver,
        "approved_at": utc_now(),
        "scope": "exact 60-90 second sample evidence only; final render remains separately gated",
        "sample_project": str(director.sample_hyperframes_project),
        "storyboard_sha256": sha256_file(storyboard),
        "aesthetic_review_sha256": sha256_file(review),
        "gate_report_sha256": sha256_file(gate),
    })
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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
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
    approve = sub.add_parser("approve-sample", help="approve the exact current sample evidence")
    approve.add_argument("--project", required=True)
    approve.add_argument("--approved-by", default="user")
    authorize = sub.add_parser("authorize-final-render", help="authorize the exact full project that passed QA")
    authorize.add_argument("--project", required=True)
    authorize.add_argument("--authorized-by", default="user")
    approve_alias = sub.add_parser("approve", help="approve the exact current sample evidence")
    approve_alias.add_argument("--project", required=True)
    approve_alias.add_argument("--approved-by", default="user")
    authorize_alias = sub.add_parser("authorize-render", help="authorize the exact checked full render")
    authorize_alias.add_argument("--project", required=True)
    authorize_alias.add_argument("--authorized-by", default="user")
    for name in ("open-preview", "open-studio"):
        open_command = sub.add_parser(name, help="open the editable HyperFrames Studio")
        open_command.add_argument("--project", required=True)
        open_command.add_argument("--full", action="store_true")
    deliver = sub.add_parser("deliver", help="run all authorized local/external stages to delivery")
    deliver.add_argument("--project", required=True)
    metrics = sub.add_parser("import-metrics", help="import a user-exported platform metrics file")
    metrics.add_argument("--project", required=True)
    metrics.add_argument("--input", required=True)
    metrics.add_argument("--out")
    reset = sub.add_parser("reset-stage", help="invalidate a stage and all downstream stages")
    reset.add_argument("--project", required=True)
    reset.add_argument("--stage", required=True, choices=STAGES)
    return root


def _dispatch(args: argparse.Namespace) -> int:
    deliver = args.command == "deliver"
    director = Director(Path(args.project),
                        approve_final_render=getattr(args, "approve_final_render", False) or deliver,
                        execute_external=getattr(args, "execute_external", False) or deliver)
    if args.command == "status":
        print(json.dumps(director.state, ensure_ascii=False, indent=2))
        return 0
    if args.command == "reset-stage":
        reset_stage(director.state_path, args.stage)
        print(director.state_path)
        return 0
    if args.command in {"approve-sample", "approve"}:
        print(approve_sample(director, args.approved_by))
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
        output = Path(args.out).resolve() if args.out else director.root / "post-publish-metrics.json"
        import_post_publish_metrics(Path(args.input), output)
        print(output)
        return 0
    return director.run(getattr(args, "until", None))


def main() -> int:
    args = parser().parse_args()
    try:
        # One CLI command owns the project transaction. This prevents concurrent
        # run/reset/approve processes from losing stage transitions.
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
