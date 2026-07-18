#!/usr/bin/env python3
"""Single resumable entry point for the preservation-first professional workflow.

This program is deliberately an orchestrator. It delegates editing semantics to
video-use, motion design/rendering to HyperFrames, and final media mechanics to
FFmpeg. Agent-authored semantic and aesthetic decisions are represented as
versioned artifacts rather than hidden in per-project scripts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aesthetic_qa import validate as validate_aesthetic_review
from audio_qa import validate as validate_audio_plan
from correction_ledger import new_ledger, validate_ledger
from director_contracts import (
    STAGES,
    DirectorContractError,
    ProjectContext,
    assert_valid,
    load_project_context,
    read_json,
    sha256_file,
    validate_semantic_brief,
    validate_storyboard,
    validate_video_use_edl,
    validate_video_use_edit_preflight,
    validate_video_use_final_correctness,
    validate_video_use_media_analysis,
    validate_visual_vocabulary_audit,
    write_json,
)
from manual_finish import (
    build_handoff_manifest,
    validate_returned_final_qa,
)
from preview_render_parity import validate as validate_preview_render_parity
from video_use_bridge import render_command, render_helper_path


STATE_VERSION = 3
DIRECTOR_VERSION = "1.2.0"

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


def _ffprobe_duration(path: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def _stage_template() -> dict[str, Any]:
    return {"status": "pending", "attempts": 0, "updated_at": None, "artifacts": [], "error": None}


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
        self.state = self._load_or_create_state()

    def _load_or_create_state(self) -> dict[str, Any]:
        if self.state_path.is_file():
            state = read_json(self.state_path)
            if state.get("project_file") != str(self.context.project_file):
                raise DirectorContractError("director state belongs to a different project")
            stages = state.setdefault("stages", {})
            for name in STAGES:
                stages.setdefault(name, _stage_template())
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
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "current_stage": None,
            "status": "active",
            "stages": {name: _stage_template() for name in STAGES},
        }
        write_json(self.state_path, state)
        return state

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
                stat = returned.stat()
                if (
                    receipt.get("returned_final_size") != stat.st_size
                    or receipt.get("returned_final_mtime_ns") != stat.st_mtime_ns
                ):
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
        row.update({"status": "complete", "updated_at": utc_now(), "error": None,
                    "artifacts": [str(path.resolve()) for path in (artifacts or [])]})
        _reconcile_state(self.state)
        self._save()

    def _action_required(self, stage: str, reason: str, actions: list[dict[str, Any]]) -> None:
        packet = {
            "schema_version": 1,
            "stage": stage,
            "reason": reason,
            "actions": actions,
            "resume_command": f'python "{Path(__file__).resolve()}" run --project "{self.context.project_file}" --resume',
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
                ):
                    return evidence_path
            return None
        evidence_dir = self.root / "input-mode-evidence"
        command = [
            "python", str(Path(__file__).with_name("analyze_existing_edit.py")),
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
        }
        path = self.root / "workflow-contract.json"
        write_json(path, report)
        artifacts = [path, legacy_audit]
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
                    ["python", str(timeline_helper), str(self.context.source_video),
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
                "python", str(Path(__file__).with_name("video_use_bridge.py")),
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
                                               self.video_use_dir / "master.srt", sync_report])

    def stage_semantic_brief(self) -> None:
        if not self.semantic_brief_path.is_file():
            transcript = next((self.video_use_dir / "transcripts").glob("*.json"), None)
            packet = self.root / "semantic-brief-request.json"
            write_json(packet, {
                "schema_version": 1,
                "owner": "director_with_llm",
                "required_content_reading": "raw_word_transcript_and_evidence_frames",
                "transcript": str(transcript) if transcript else None,
                "evidence_frames_dir": str(self.root / "evidence-frames"),
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
        self._complete("semantic_brief", [self.semantic_brief_path])

    def stage_hyperframes_storyboard(self) -> None:
        project = self.sample_hyperframes_project
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
        self._complete("hyperframes_storyboard", [storyboard_path, vocabulary_path, index_path, command_path])

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
        self._complete("audio", [path])

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
        self._complete("cover", [path])

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
        write_json(report_path, {"schema_version": 2, "passed": True, "review": str(review_path),
                                 "audio_plan": str(audio_plan_path), "errors": []})
        self._complete("sample_qa", [review_path, audio_plan_path, report_path])

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
                  "command": ["python", str(Path(__file__).resolve()), "approve-sample",
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
        if not transcript_path.is_file() or full_brief.get("transcript_sha256") != sha256_file(transcript_path):
            raise DirectorContractError("full semantic brief transcript hash does not match video-use")
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
        self._complete("full_hyperframes_storyboard", [full_brief_path, *required, command_path])

    def stage_full_hyperframes_qa(self) -> None:
        qa_dir = self.root / "full-qa"
        check_path = qa_dir / "hyperframes-check.json"
        snapshot_review_path = qa_dir / "snapshot-review.json"
        parity_path = qa_dir / "preview-render-parity.json"
        commands_path = self.root / "full-hyperframes-commands.json"
        commands = read_json(commands_path)
        if not check_path.is_file() or not snapshot_review_path.is_file() or not parity_path.is_file():
            self._action_required(
                "full_hyperframes_qa",
                "The full HyperFrames project requires strict checks, reviewed snapshots, and preview/render parity before render",
                [{
                    "owner": "hyperframes_with_director_review",
                    "check_command": commands["check"],
                    "snapshot_command": commands["snapshots"],
                    "expected_artifacts": [str(check_path), str(snapshot_review_path), str(parity_path)],
                    "parity_scope": (
                        "Compare representative Studio/snapshot and short render evidence at identical times; "
                        "do not run the complete long render for this gate."
                    ),
                }],
            )
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
            "snapshot_review_sha256": sha256_file(snapshot_review_path),
            "preview_render_parity_sha256": sha256_file(parity_path),
            "strict_check_passed": True,
            "snapshot_review_passed": True,
            "preview_render_parity_passed": True,
        })
        self._complete("full_hyperframes_qa", [check_path, snapshot_review_path, parity_path, evidence_path])

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
                  "command": ["python", str(Path(__file__).resolve()), "authorize-final-render",
                              "--project", str(self.context.project_file)]}],
            )
        command_record = read_json(self.root / "full-hyperframes-commands.json")["final_motion_render"]
        command = list(command_record["argv"])
        output = Path(command_record["expected_artifact"])
        if self.execute_external:
            output.parent.mkdir(parents=True, exist_ok=True)
            resolved_executable = shutil.which(command[0])
            if resolved_executable:
                command[0] = resolved_executable
            subprocess.run(command, cwd=command_record["cwd"], check=True)
        if not output.is_file():
            self._action_required("final_render", "HyperFrames render output is not present",
                                  [{"owner": "hyperframes", "command": command_record,
                                    "expected_artifact": str(output)}])
        self._complete("final_render", [output, authorization])

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
        bgm_config = self.project.get("audio", {}).get("bgm", {})
        bgm_value = bgm_config.get("asset")
        bgm_asset = Path(str(bgm_value)) if bgm_value else None
        if bgm_asset and not bgm_asset.is_absolute():
            bgm_asset = (self.context.root / bgm_asset).resolve()
        bgm_enabled = (
            bgm_asset is not None
            and bgm_config.get("enabled", bgm_config.get("enabled_by_default", False)) is True
        )
        if bgm_enabled and not bgm_asset.is_file():
            self._action_required(
                "final_compose",
                "Configured authorized BGM asset is not present",
                [{"owner": "director", "expected_artifact": str(bgm_asset)}],
            )
        audio_mix: dict[str, Any] = {"bgm_enabled": False}
        if bgm_enabled and bgm_asset:
            storyboard = read_json(self.full_hyperframes_project / "storyboard.json")
            duration = float(storyboard.get("composition", {}).get("duration", 0.0))
            if duration <= 0:
                duration = _ffprobe_duration(motion)
            preview_volume = float(bgm_config.get("preview_volume", 0.1))
            ducking = bgm_config.get("ducking", {})
            threshold = float(ducking.get("threshold", 0.03))
            ratio = float(ducking.get("ratio", 8))
            attack = int(ducking.get("attack_ms", 200))
            release = int(ducking.get("release_ms", 400))
            fade_out = max(0.0, duration - 2.0)
            filter_graph = (
                f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume={preview_volume:.3f},"
                f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out:.3f}:d=2[bgm];"
                f"[bgm][0:a]sidechaincompress=threshold={threshold}:ratio={ratio}:"
                f"attack={attack}:release={release}[ducked];"
                "[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
                "loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            )
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(motion),
                "-stream_loop", "-1", "-i", str(bgm_asset), "-filter_complex", filter_graph,
                "-map", "0:v:0", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium",
                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(output),
            ]
            audio_mix = {
                "bgm_enabled": True,
                "bgm_asset": str(bgm_asset),
                "preview_volume": preview_volume,
                "ducking": {"method": "sidechaincompress", "threshold": threshold,
                            "ratio": ratio, "attack_ms": attack, "release_ms": release},
            }
        else:
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(motion),
                "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
                "-crf", "18", "-pix_fmt", "yuv420p",
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(output),
            ]
        command_path = self.root / "final-compose-command.json"
        write_json(command_path, {
            "schema_version": 1,
            "owner": "ffmpeg",
            "input": str(motion),
            "output": str(output),
            "single_universal_output": True,
            "audio_mix": audio_mix,
            "argv": command,
        })
        if self.execute_external and not output.is_file():
            output.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(command, cwd=self.context.root, check=True)
        if not output.is_file():
            self._action_required(
                "final_compose",
                "FFmpeg universal composition/encode output is not present",
                [{"owner": "ffmpeg", "capability": "final composition, mix and encode",
                  "command": command, "expected_artifact": str(output)}],
            )
        decode = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(output), "-f", "null", "-"],
            capture_output=True,
            text=True,
        )
        if decode.returncode:
            raise DirectorContractError("full decode validation failed: " + decode.stderr.strip())
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
        media_report = self.root / "final-media-report.json"
        write_json(media_report, {
            "schema_version": 1,
            "output": str(output),
            "sha256": sha256_file(output),
            "decode_status": "pass",
            "ffprobe": json.loads(probe.stdout),
        })
        self._complete("final_compose", [output, command_path, media_report])

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
        decode = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(returned), "-f", "null", "-"],
            capture_output=True,
            text=True,
        )
        if decode.returncode:
            raise DirectorContractError(
                "manual returned final failed full decode validation: " + decode.stderr.strip()
            )
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(returned)],
            check=True,
            capture_output=True,
            text=True,
        )
        write_json(path, {
            "schema_version": 1,
            "output": str(returned),
            "sha256": returned_hash,
            "decode_status": "pass",
            "ffprobe": json.loads(probe.stdout),
        })
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
            media_report_path, returned_qa_path, final_correctness_path,
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
        if self.manual_finish_active and final_review.get("reviewed_output_sha256") != output_hash:
            raise DirectorContractError(
                "manual returned final requires a fresh aesthetic review bound to its exact hash"
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
        if media_report.get("decode_status") != "pass" or media_report.get("sha256") != output_hash:
            raise DirectorContractError("final media decode report is missing or stale")
        for name, path in platform_paths.items():
            platform = read_json(path)
            if platform.get("status") != "pass" or platform.get("file_sha256") != output_hash:
                raise DirectorContractError(f"{name} must validate the same universal output bytes")
        report = self.root / "delivery-contract.json"
        write_json(report, {"schema_version": 1, "universal_video": str(output),
                            "file_sha256": output_hash, "duplicate_platform_mp4s": False,
                            "validated_same_file_for": list(platform_paths),
                            "cover": str(cover_path), "audio_plan": str(audio_plan_path),
                            "automatic_master": str(self.delivery_output),
                            "manual_finish": self.manual_finish_active})
        self._complete("delivery_qa", [output, cover_path, report, *required])
        self.state.update({"status": "complete", "current_stage": None})
        self._save()

    def run(self, until: str | None = None) -> int:
        handlers: dict[str, Callable[[], None]] = {
            "inspect": self.stage_inspect,
            "video_use_timeline": self.stage_video_use_timeline,
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
    return ["python", str(helper), str(source_video), "--edit-dir", str(edit_dir)]


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
    status = sub.add_parser("status", help="print current resumable state")
    status.add_argument("--project", required=True)
    approve = sub.add_parser("approve-sample", help="approve the exact current sample evidence")
    approve.add_argument("--project", required=True)
    approve.add_argument("--approved-by", default="user")
    authorize = sub.add_parser("authorize-final-render", help="authorize the exact full project that passed QA")
    authorize.add_argument("--project", required=True)
    authorize.add_argument("--authorized-by", default="user")
    reset = sub.add_parser("reset-stage", help="invalidate a stage and all downstream stages")
    reset.add_argument("--project", required=True)
    reset.add_argument("--stage", required=True, choices=STAGES)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        director = Director(Path(args.project),
                            approve_final_render=getattr(args, "approve_final_render", False),
                            execute_external=getattr(args, "execute_external", False))
        if args.command == "status":
            print(json.dumps(director.state, ensure_ascii=False, indent=2))
            return 0
        if args.command == "reset-stage":
            reset_stage(director.state_path, args.stage)
            print(director.state_path)
            return 0
        if args.command == "approve-sample":
            print(approve_sample(director, args.approved_by))
            return 0
        if args.command == "authorize-final-render":
            print(authorize_final_render(director, args.authorized_by))
            return 0
        return director.run(args.until)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, yaml_error()) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def yaml_error():
    # Imported lazily to keep the entry's top-level dependency surface explicit.
    import yaml
    return yaml.YAMLError


if __name__ == "__main__":
    raise SystemExit(main())
