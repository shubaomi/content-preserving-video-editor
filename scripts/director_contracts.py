#!/usr/bin/env python3
"""Contracts shared by the content-preserving director and its QA gates."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from project_config import migrate_project_config


LOW_INFORMATION_ANCHORS = {
    "打开", "点击", "添加", "然后", "接着", "这里", "下面", "这个", "那个",
    "看一下", "可以看到", "我们来看", "就是", "进行", "完成",
}

REQUIRED_VISUAL_FIELDS = (
    "dom_structure",
    "information_hierarchy",
    "layout_archetype",
    "animation_choreography",
    "use_case",
)

STORYBOARD_SEMANTIC_FIELDS = (
    "anchor",
    "transcript_word_ids",
    "viewer_takeaway",
)

STORYBOARD_SEMANTIC_TIME_FIELDS = (
    "source_start",
    "source_end",
    "output_start",
    "output_end",
)

NON_VISIBLE_EVENT_STRING_PATHS = {
    "id", "semantic_event_id", "treatment", "anchor", "transcript_quote",
    "transcript_word_ids.[]", "viewer_takeaway", "relevance_rationale",
    "viewer_job", "visual_mechanism", "target_frame_evidence.[]",
    "target_frame_evidence.[].path", "target_frame_evidence.[].sha256",
    "source_activity_evidence.[]", "form", "placement", "size", "background",
    "asset", "visual_structure.dom_structure", "visual_structure.information_hierarchy",
    "visual_structure.layout_archetype", "visual_structure.animation_choreography",
    "visual_structure.use_case", "motion.entrance", "motion.reveal", "motion.hold",
    "motion.exit", "audio_decision.type", "audio_decision.reason",
    "audio_decision.family", "audio_decision.asset", "audio_decision.asset_path",
    "deduplication.semantic", "deduplication.visual", "protected_zones.[].id",
    "geometry_contract.complete_components.[]", "geometry_contract.cropping",
    "geometry_contract.object_fit",
    "geometry_contract.connector_contract.attachment_intent",
    "geometry_contract.connector_contract.relations.[]",
    "geometry_contract.connector_contract.relations.[].from",
    "geometry_contract.connector_contract.relations.[].to",
    "geometry_contract.connector_contract.relations.[].attachment_edge",
    "geometry_contract.target_region_contract.tracking_mode",
    "geometry_contract.target_region_contract.active_selector",
    "geometry_contract.target_region_contract.target_ids.[]",
    "geometry_contract.target_region_contract.source_state_evidence.[].phase",
    "geometry_contract.target_region_contract.source_state_evidence.[].path",
    "geometry_contract.target_region_contract.source_state_evidence.[].sha256",
}
MAX_TARGET_FRAME_DISTANCE_SECONDS = 15.0

RELATION_VISUAL_MARKERS = {
    "arrow", "brace", "branch", "connector", "dependency", "flow", "route",
}
TARGET_BOUND_VISUAL_MARKERS = {
    "brace", "callout", "cursor", "focus", "highlight", "overlay", "target",
}
TARGET_TRACKING_MODES = {"static", "scene_bounded", "keyframed"}
TARGET_EVIDENCE_PHASES = ("entrance", "midpoint", "pre_exit")

STAGES = (
    "inspect",
    "provider_governance",
    "video_use_timeline",
    "evidence_acquisition",
    "semantic_brief",
    "production_contract",
    "brand_motion_playbook",
    "hyperframes_storyboard",
    "audio",
    "cover",
    "sample_qa",
    "preview_approval",
    "full_hyperframes_storyboard",
    "full_hyperframes_qa",
    "final_render",
    "final_compose",
    "derived_content",
    "manual_finish_handoff",
    "delivery_qa",
)

VISUAL_VOCABULARY = (
    "keyword_typography",
    "ui_focus",
    "process",
    "comparison",
    "steps",
    "numeric_result",
    "chapter",
    "pip_zoom",
    "ip_asset",
    "quiet_source",
)

VISUAL_VOCABULARY_STATUS = {"selected", "not_applicable"}


class DirectorContractError(ValueError):
    """Raised when a stage artifact violates the professional workflow contract."""


@contextmanager
def exclusive_file_lock(
    target: Path, *, timeout_seconds: float = 30.0, stale_seconds: float = 3600.0,
):
    """Serialize a transaction with a bounded, crash-reclaimable lock file."""
    lock = target.with_suffix(target.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, json.dumps({"pid": os.getpid(), "created": time.time()}).encode("utf-8"))
        except (FileExistsError, PermissionError):
            try:
                stale = time.time() - lock.stat().st_mtime > stale_seconds
            except FileNotFoundError:
                stale = False
            if stale:
                try:
                    lock.unlink()
                    continue
                except (FileNotFoundError, PermissionError):
                    pass
            if time.monotonic() >= deadline:
                raise RuntimeError(f"timed out waiting for lock: {lock}")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


@dataclass(frozen=True)
class ProjectContext:
    project_file: Path
    root: Path
    source_video: Path
    input_mode: str
    work_dir: Path
    edit_dir: Path
    hyperframes_dir: Path
    exports_dir: Path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, value: str | None, default: str) -> Path:
    candidate = Path(value or default)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def detect_input_mode(
    project: dict[str, Any],
    source_video: Path,
    analysis_evidence: dict[str, Any] | None = None,
) -> str:
    declared = str(project.get("source", {}).get("input_mode", "")).lower()
    if any(token in declared for token in ("existing", "published", "polish")):
        return "polish_existing"
    if any(token in declared for token in ("source", "raw", "preserve")):
        return "preserve"
    workflow_mode = str(project.get("workflow", {}).get("input_mode") or "").lower()
    if workflow_mode == "polish_existing":
        return "polish_existing"
    if workflow_mode in {"source_first", "preserve", "raw"}:
        return "preserve"
    source = project.get("source", {})
    if any(source.get(field) is True for field in (
        "published", "previously_edited", "has_burned_captions", "has_existing_bgm"
    )):
        return "polish_existing"
    name = source_video.stem.lower()
    if any(token in name for token in ("final", "published", "剪映", "成片")):
        return "polish_existing"
    if analysis_evidence and analysis_evidence.get("selected_mode") in {"preserve", "polish_existing"}:
        return str(analysis_evidence["selected_mode"])
    return "needs_analysis"


def load_project_context(project_file: Path) -> tuple[dict[str, Any], ProjectContext]:
    project_file = project_file.resolve()
    project = migrate_project_config(
        yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
    )
    declared_root = project.get("paths", {}).get("root")
    root = _resolve(project_file.parent, declared_root, ".")
    source_value = project.get("source", {}).get("primary_video")
    if not source_value:
        raise DirectorContractError("project.source.primary_video is required")
    source_video = _resolve(root, str(source_value), "source/input.mp4")
    if not source_video.is_file():
        raise DirectorContractError(f"source video not found: {source_video}")
    paths = project.get("paths", {})
    work_dir = _resolve(root, paths.get("work"), "work")
    mode_evidence_path = work_dir / "director" / "input-mode-evidence.json"
    mode_evidence: dict[str, Any] | None = None
    if mode_evidence_path.is_file():
        try:
            candidate = read_json(mode_evidence_path)
            stat = source_video.stat()
            if (
                candidate.get("source_size") == stat.st_size
                and candidate.get("source_mtime_ns") == stat.st_mtime_ns
                and candidate.get("source_sha256") == sha256_file(source_video)
            ):
                mode_evidence = candidate
        except (OSError, json.JSONDecodeError):
            mode_evidence = None
    context = ProjectContext(
        project_file=project_file,
        root=root,
        source_video=source_video,
        input_mode=detect_input_mode(project, source_video, mode_evidence),
        work_dir=work_dir,
        edit_dir=_resolve(root, paths.get("edit"), "edit"),
        hyperframes_dir=_resolve(root, paths.get("hyperframes"), "hyperframes"),
        exports_dir=_resolve(root, paths.get("exports"), "exports"),
    )
    return project, context


def normalized_anchor(value: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’()（）\-]", "", value).lower()


def visual_signature(event: dict[str, Any]) -> tuple[str, ...]:
    visual = event.get("visual_structure", {})
    return tuple(str(visual.get(field, "")).strip() for field in REQUIRED_VISUAL_FIELDS)


def validate_semantic_brief(brief: dict[str, Any], *, require_sample_variety: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        schema_version = int(brief.get("schema_version", 0))
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version < 1:
        errors.append("semantic brief requires schema_version >= 1")
    generated_by = str(brief.get("generated_by", "")).lower()
    if "llm" not in generated_by:
        errors.append("semantic brief must be authored by an LLM reading the raw transcript and evidence frames")
    if brief.get("content_reading") != "raw_word_transcript_and_evidence_frames":
        errors.append("semantic brief must declare raw_word_transcript_and_evidence_frames content reading")
    if not re.fullmatch(r"[0-9a-f]{64}", str(brief.get("transcript_sha256", ""))):
        errors.append("semantic brief requires transcript_sha256 provenance")
    if not brief.get("evidence_frames"):
        errors.append("semantic brief requires evidence_frames")
    if schema_version >= 2:
        if not re.fullmatch(r"[0-9a-f]{64}", str(brief.get("evidence_bundle_sha256", ""))):
            errors.append("schema 2 semantic brief requires evidence_bundle_sha256 provenance")
        opening_hook = brief.get("opening_hook") or {}
        if not isinstance(opening_hook, dict):
            opening_hook = {}
        if opening_hook.get("status") not in {"selected", "not_selected"} or not opening_hook.get("evidence"):
            errors.append("schema 2 semantic brief requires an evidence-backed opening_hook decision")
    events = brief.get("events") or []
    if not events:
        errors.append("semantic brief requires events")
        return errors
    anchors: dict[str, float] = {}
    signatures: set[tuple[str, ...]] = set()
    visual_events = 0
    for index, event in enumerate(events):
        prefix = f"events[{index}]"
        if event.get("treatment") == "quiet_source":
            evidence = event.get("source_activity_evidence") or []
            if not evidence:
                errors.append(f"{prefix} quiet_source requires source_activity_evidence")
            continue
        visual_events += 1
        anchor = normalized_anchor(str(event.get("anchor", "")))
        if not anchor:
            errors.append(f"{prefix} anchor is required")
        if anchor in {normalized_anchor(item) for item in LOW_INFORMATION_ANCHORS}:
            errors.append(f"{prefix} uses low-information anchor: {event.get('anchor')}")
        transcript_quote = normalized_anchor(str(event.get("transcript_quote", "")))
        if anchor and transcript_quote and anchor == transcript_quote and len(anchor) > 12:
            errors.append(f"{prefix} repeats a subtitle-length transcript quote")
        start = float(event.get("source_start", event.get("start", 0)))
        if anchor in anchors and start - anchors[anchor] < 40:
            errors.append(f"{prefix} repeats anchor inside 40-second cooldown: {event.get('anchor')}")
        anchors[anchor] = start
        if not event.get("relevance_rationale"):
            errors.append(f"{prefix} requires relevance_rationale")
        if not event.get("transcript_word_ids"):
            errors.append(f"{prefix} requires transcript_word_ids")
        if schema_version >= 2:
            required = (
                "source_end", "output_start", "output_end", "viewer_job", "viewer_takeaway",
                "visual_mechanism", "target_frame_evidence", "protected_zones", "form",
                "placement", "size", "background", "read_time", "motion",
                "audio_decision", "deduplication",
            )
            for field in required:
                if event.get(field) in (None, "", [], {}):
                    errors.append(f"{prefix} requires {field}")
            motion = event.get("motion") or {}
            if not isinstance(motion, dict):
                motion = {}
            for phase in ("entrance", "reveal", "hold", "exit"):
                if not motion.get(phase):
                    errors.append(f"{prefix} motion requires {phase}")
            audio = event.get("audio_decision") or {}
            if not isinstance(audio, dict):
                audio = {}
            if audio.get("type") not in {"cue", "intentionally_silent"}:
                errors.append(f"{prefix} audio_decision must be cue or intentionally_silent")
            if audio.get("type") == "intentionally_silent" and not audio.get("reason"):
                errors.append(f"{prefix} intentionally_silent requires reason")
        signature = visual_signature(event)
        if any(not value for value in signature):
            errors.append(f"{prefix} visual_structure requires all five distinctness fields")
        elif signature in signatures:
            errors.append(f"{prefix} duplicates a previous visual structure contract")
        signatures.add(signature)
    if require_sample_variety and (visual_events < 4 or len(signatures) < 4):
        errors.append("sample requires at least four genuinely different visual structures")
    return errors


def validate_semantic_evidence_binding(
    brief: dict[str, Any], *, transcript_path: Path, evidence_bundle_path: Path,
) -> list[str]:
    """Bind semantic choices to the exact current transcript and captured frames."""
    errors: list[str] = []
    try:
        schema_version = int(brief.get("schema_version", 0))
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version < 2:
        errors.append("semantic brief must use schema_version >= 2 for evidence binding")
    if not transcript_path.is_file() or brief.get("transcript_sha256") != sha256_file(transcript_path):
        errors.append("semantic brief is not bound to the current transcript")
    if not evidence_bundle_path.is_file() or brief.get("evidence_bundle_sha256") != sha256_file(evidence_bundle_path):
        errors.append("semantic brief is not bound to the current evidence bundle")
        return errors
    try:
        bundle = read_json(evidence_bundle_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"evidence bundle is unreadable: {error}")
        return errors
    if not isinstance(bundle, dict):
        errors.append("evidence bundle must be a JSON object")
        return errors
    if bundle.get("transcript", {}).get("sha256") != sha256_file(transcript_path):
        errors.append("evidence bundle transcript hash does not match the current transcript")

    frame_records: dict[str, dict[str, Any]] = {}
    for row in bundle.get("representative_frames") or []:
        if not isinstance(row, dict) or not row.get("path"):
            continue
        path = Path(str(row["path"])).resolve()
        frame_records[str(path)] = row
        if not path.is_file() or row.get("sha256") != sha256_file(path):
            errors.append(f"evidence frame is missing or hash-drifted: {path}")

    def resolved_frame(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get("path")
        path = Path(str(value))
        if not path.is_absolute():
            path = evidence_bundle_path.parent / path
        return str(path.resolve())

    for value in brief.get("evidence_frames") or []:
        if resolved_frame(value) not in frame_records:
            errors.append(f"semantic brief references undeclared evidence frame: {value}")

    term_rows = bundle.get("transcript", {}).get("term_evidence") or []
    words = {str(row.get("word_id")): row for row in term_rows if isinstance(row, dict)}
    for index, event in enumerate(brief.get("events") or []):
        if not isinstance(event, dict):
            errors.append(f"events[{index}] must be a mapping")
            continue
        prefix = f"events[{index}]"
        ids = [str(value) for value in (event.get("transcript_word_ids") or [])]
        missing = [value for value in ids if value not in words]
        if missing:
            errors.append(f"{prefix} references unknown transcript word IDs: {', '.join(missing)}")
        selected = [] if missing else [words[value] for value in ids]
        try:
            source_start = float(event["source_start"])
            source_end = float(event["source_end"])
            if (
                not math.isfinite(source_start)
                or not math.isfinite(source_end)
                or source_start < 0
                or source_end < source_start
            ):
                raise ValueError
            source_window: tuple[float, float] | None = (source_start, source_end)
        except (KeyError, TypeError, ValueError):
            errors.append(f"{prefix} has invalid source timing evidence")
            source_window = None
        if selected:
            try:
                selected_start = min(float(row["start"]) for row in selected)
                selected_end = max(float(row["end"]) for row in selected)
            except (KeyError, TypeError, ValueError):
                errors.append(f"{prefix} has invalid transcript word timing evidence")
            else:
                if source_window is not None and (
                    source_window[0] > selected_start + 0.05
                    or source_window[1] < selected_end - 0.05
                ):
                    errors.append(f"{prefix} source timing does not contain its referenced words")
            expected = normalized_anchor("".join(str(row.get("text") or "") for row in selected))
            quote = normalized_anchor(str(event.get("transcript_quote") or ""))
            if not quote or (expected and quote not in expected and expected not in quote):
                errors.append(f"{prefix} transcript quote does not match its referenced words")
        target_records: list[dict[str, Any]] = []
        for value in event.get("target_frame_evidence") or []:
            record = frame_records.get(resolved_frame(value))
            if record is None:
                errors.append(f"{prefix} references undeclared target frame: {value}")
            else:
                target_records.append(record)
        for record_index, record in enumerate(target_records):
            timestamp = record.get("timestamp_seconds")
            if timestamp is not None:
                try:
                    frame_time = float(timestamp)
                except (TypeError, ValueError):
                    errors.append(f"{prefix} has malformed target frame timestamp")
                else:
                    if not math.isfinite(frame_time) or frame_time < 0:
                        errors.append(f"{prefix} has malformed target frame timestamp")
                    elif source_window is not None:
                        distance = (
                            0.0 if source_window[0] <= frame_time <= source_window[1]
                            else min(
                                abs(frame_time - source_window[0]),
                                abs(frame_time - source_window[1]),
                            )
                        )
                        if distance > MAX_TARGET_FRAME_DISTANCE_SECONDS:
                            errors.append(
                                f"{prefix} target frame timestamp[{record_index}] is too far "
                                "from its source timing"
                            )
            if "coverage" not in record:
                continue
            coverage = record["coverage"]
            if (
                isinstance(coverage, dict)
                and str(coverage.get("status") or "").lower() == "unknown"
            ):
                continue
            if not isinstance(coverage, dict):
                errors.append(f"{prefix} has malformed target frame coverage")
                continue
            try:
                coverage_start = float(coverage["start_seconds"])
                coverage_end = float(coverage["end_seconds"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{prefix} has malformed target frame coverage")
                continue
            if (
                math.isfinite(coverage_start)
                and math.isfinite(coverage_end)
                and 0 <= coverage_start <= coverage_end
            ):
                if source_window is not None and not (
                    coverage_end >= source_window[0] and coverage_start <= source_window[1]
                ):
                    errors.append(
                        f"{prefix} target frame coverage[{record_index}] does not overlap "
                        "its source timing"
                    )
            else:
                errors.append(f"{prefix} has malformed target frame coverage")
    return errors


def storyboard_semantic_event_id(event: dict[str, Any]) -> str:
    """Resolve the approved semantic event referenced by a storyboard event."""
    semantic_event_id = event.get("semantic_event_id")
    return str(semantic_event_id or "").strip()


def _visible_copy_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return [normalized] if normalized else []
    if isinstance(value, dict):
        result: list[str] = []
        for key in sorted(value):
            result.extend(_visible_copy_strings(value[key]))
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            result.extend(_visible_copy_strings(item))
        return result
    return []


def _normalized_event_path(path: tuple[str, ...]) -> str:
    return ".".join(
        "[]" if value.isdigit() else value.strip().lower().replace("-", "_")
        for value in path
    )


def _event_visual_tokens(event: dict[str, Any]) -> set[str]:
    visual = event.get("visual_structure") or {}
    values = [event.get("form"), event.get("treatment")]
    if isinstance(visual, dict):
        values.extend(visual.get(field) for field in REQUIRED_VISUAL_FIELDS)
    return {
        token
        for value in values
        if isinstance(value, str)
        for token in re.findall(r"[a-z0-9]+", value.lower())
    }


def event_requires_connector_contract(event: dict[str, Any]) -> bool:
    """Return whether the declared visual grammar makes a spatial relation claim."""
    return bool(_event_visual_tokens(event) & RELATION_VISUAL_MARKERS)


def event_requires_target_region_contract(event: dict[str, Any]) -> bool:
    """Return whether an effect claims alignment to content in the source frame."""
    return bool(_event_visual_tokens(event) & TARGET_BOUND_VISUAL_MARKERS)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _validate_connector_contract(event: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    contract = (event.get("geometry_contract") or {}).get("connector_contract")
    if not isinstance(contract, dict):
        return [f"{prefix} relation visual requires a connector contract"]
    required_count = contract.get("required_connector_count")
    if isinstance(required_count, bool) or not isinstance(required_count, int) or required_count < 1:
        errors.append(f"{prefix} connector contract requires a positive connector count")
        required_count = 0
    relations = contract.get("relations")
    if not isinstance(relations, list) or len(relations) != required_count:
        errors.append(f"{prefix} connector contract relations must match the required count")
        relations = []
    for relation_index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            errors.append(f"{prefix} connector relation[{relation_index}] must be typed metadata")
            continue
        for field in ("from", "to", "attachment_edge"):
            if not isinstance(relation.get(field), str) or not relation[field].strip():
                errors.append(
                    f"{prefix} connector relation[{relation_index}] requires {field}"
                )
    intent = contract.get("attachment_intent")
    if not isinstance(intent, str) or not intent.strip():
        errors.append(f"{prefix} connector contract requires attachment_intent")
    return errors


def _validate_target_region_contract(event: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    contract = (event.get("geometry_contract") or {}).get("target_region_contract")
    if not isinstance(contract, dict):
        return [f"{prefix} source-bound visual requires a target region contract"]
    tracking_mode = contract.get("tracking_mode")
    if tracking_mode not in TARGET_TRACKING_MODES:
        errors.append(f"{prefix} target region contract has an invalid tracking_mode")
    active_selector = contract.get("active_selector")
    if (
        not isinstance(active_selector, str)
        or not active_selector.strip()
        or not active_selector.lstrip().startswith(("#", "."))
    ):
        errors.append(f"{prefix} target region contract requires active_selector")
    required_count = contract.get("required_target_count")
    if isinstance(required_count, bool) or not isinstance(required_count, int) or required_count < 1:
        errors.append(f"{prefix} target region contract requires a positive target count")
        required_count = 0
    target_ids = contract.get("target_ids")
    if (
        not isinstance(target_ids, list)
        or len(target_ids) != required_count
        or any(not isinstance(value, str) or not value.strip() for value in target_ids)
        or len(set(target_ids)) != len(target_ids)
    ):
        errors.append(f"{prefix} target_ids must uniquely match the required target count")
    useful_ratio = _finite_number(contract.get("minimum_useful_content_ratio"))
    if useful_ratio is None or not 0.1 <= useful_ratio <= 1.0:
        errors.append(f"{prefix} minimum_useful_content_ratio must be between 0.1 and 1.0")
    state_delta = _finite_number(contract.get("maximum_static_state_delta", 0.12))
    if state_delta is None or not 0.01 <= state_delta <= 0.3:
        errors.append(f"{prefix} maximum_static_state_delta must be between 0.01 and 0.3")

    output_start = _finite_number(event.get("output_start", event.get("start")))
    output_end = _finite_number(event.get("output_end", event.get("end")))
    source_start = _finite_number(event.get("source_start"))
    source_end = _finite_number(event.get("source_end"))
    active_output_start = _finite_number(contract.get("active_output_start"))
    active_output_end = _finite_number(contract.get("active_output_end"))
    active_source_start = _finite_number(contract.get("active_source_start"))
    active_source_end = _finite_number(contract.get("active_source_end"))
    for label, start, end, outer_start, outer_end in (
        ("output", active_output_start, active_output_end, output_start, output_end),
        ("source", active_source_start, active_source_end, source_start, source_end),
    ):
        if (
            start is None or end is None or outer_start is None or outer_end is None
            or not outer_start <= start < end <= outer_end
        ):
            errors.append(
                f"{prefix} target region active {label} window must be inside the event window"
            )

    evidence = contract.get("source_state_evidence")
    if not isinstance(evidence, list):
        errors.append(f"{prefix} target region contract requires source_state_evidence")
        evidence = []
    by_phase: dict[str, dict[str, Any]] = {}
    for evidence_index, record in enumerate(evidence):
        if not isinstance(record, dict):
            errors.append(f"{prefix} source_state_evidence[{evidence_index}] must be a mapping")
            continue
        phase = str(record.get("phase") or "")
        if phase in by_phase:
            errors.append(f"{prefix} source state phase must be unique: {phase}")
        by_phase[phase] = record
        if phase not in TARGET_EVIDENCE_PHASES:
            errors.append(f"{prefix} source_state_evidence[{evidence_index}] has invalid phase")
        timestamp = _finite_number(record.get("timestamp_seconds"))
        if (
            timestamp is None or active_source_start is None or active_source_end is None
            or not active_source_start <= timestamp <= active_source_end
        ):
            errors.append(
                f"{prefix} source_state_evidence[{evidence_index}] is outside the active source window"
            )
        if not isinstance(record.get("path"), str) or not record["path"].strip():
            errors.append(f"{prefix} source_state_evidence[{evidence_index}] requires path")
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256") or "")):
            errors.append(f"{prefix} source_state_evidence[{evidence_index}] requires sha256")
    if set(by_phase) != set(TARGET_EVIDENCE_PHASES):
        errors.append(
            f"{prefix} source_state_evidence requires entrance, midpoint, and pre_exit phases"
        )
    if active_source_start is not None and active_source_end is not None and active_source_end > active_source_start:
        duration = active_source_end - active_source_start
        expected_ranges = {
            "entrance": (active_source_start, active_source_start + duration * 0.35),
            "midpoint": (active_source_start + duration * 0.25, active_source_start + duration * 0.75),
            "pre_exit": (active_source_start + duration * 0.65, active_source_end),
        }
        for phase, (low, high) in expected_ranges.items():
            timestamp = _finite_number((by_phase.get(phase) or {}).get("timestamp_seconds"))
            if timestamp is not None and not low <= timestamp <= high:
                errors.append(f"{prefix} source state {phase} evidence is not in its phase window")
    return errors


def _event_visible_text_fields(
    value: Any,
    path: tuple[str, ...] = (),
    *,
    approved_copy: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    """Fail closed on event strings not declared as metadata or approved copy."""
    findings: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            raw_key_text = str(raw_key)
            key = raw_key_text.strip().lower().replace("-", "_")
            child_path = (*path, raw_key_text)
            if (
                not path
                and raw_key_text in {"approved_visible_copy", "visible_copy_manifest"}
            ):
                continue
            if key in {"approved_visible_copy", "visible_copy_manifest"}:
                nested_copy = _visible_copy_strings(child) or ["<nested authoritative field>"]
                findings.extend((".".join(child_path), text) for text in nested_copy)
                continue
            findings.extend(_event_visible_text_fields(
                child, child_path, approved_copy=approved_copy,
            ))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_event_visible_text_fields(
                child, (*path, str(index)), approved_copy=approved_copy,
            ))
    elif isinstance(value, str):
        text = " ".join(value.split())
        if (
            text
            and _normalized_event_path(path) not in NON_VISIBLE_EVENT_STRING_PATHS
            and text not in approved_copy
        ):
            findings.append((".".join(path), text))
    return findings


def validate_storyboard_semantic_binding(
    storyboard: dict[str, Any], brief: dict[str, Any],
) -> list[str]:
    """Require every storyboard event to be an exact copy of approved semantics."""
    errors: list[str] = []
    storyboard_rows = storyboard.get("events") or []
    brief_rows = brief.get("events") or []
    if not isinstance(storyboard_rows, list):
        return ["storyboard events must be a list for semantic binding"]
    if not isinstance(brief_rows, list):
        return ["semantic brief events must be a list for storyboard binding"]

    storyboard_events: list[dict[str, Any]] = []
    for index, event in enumerate(storyboard_rows):
        if not isinstance(event, dict):
            errors.append(f"events[{index}] must be a mapping for semantic binding")
            storyboard_events.append({})
        else:
            storyboard_events.append(event)

    brief_events: list[dict[str, Any]] = []
    for index, event in enumerate(brief_rows):
        if not isinstance(event, dict):
            errors.append(f"semantic brief events[{index}] must be a mapping")
            brief_events.append({})
        else:
            brief_events.append(event)

    brief_ids = [str(event.get("id") or "").strip() for event in brief_events]
    render_ids = [str(event.get("id") or "").strip() for event in storyboard_events]
    semantic_ids = [storyboard_semantic_event_id(event) for event in storyboard_events]
    if any(not event_id for event_id in brief_ids):
        errors.append("approved semantic brief events require non-empty IDs")
    if len(set(brief_ids)) != len(brief_ids):
        errors.append("approved semantic brief event IDs must be unique")
    if any(not event_id for event_id in render_ids):
        errors.append("storyboard events require non-empty IDs")
    if len(set(render_ids)) != len(render_ids):
        errors.append("storyboard event IDs must be unique")
    if any(not event_id for event_id in semantic_ids):
        errors.append("storyboard events require an explicit semantic_event_id")
    if len(storyboard_events) != len(brief_events):
        errors.append("storyboard event count must match the approved semantic brief")
    if Counter(semantic_ids) != Counter(brief_ids):
        errors.append("storyboard semantic event set must exactly match the approved semantic brief")
    elif semantic_ids != brief_ids:
        errors.append("storyboard semantic event order must match the approved semantic brief")

    brief_by_id = {
        event_id: event for event_id, event in zip(brief_ids, brief_events) if event_id
    }
    for index, (semantic_id, storyboard_event) in enumerate(
        zip(semantic_ids, storyboard_events)
    ):
        semantic_event = brief_by_id.get(semantic_id)
        if semantic_event is None:
            errors.append(
                f"events[{index}] references unknown semantic event ID: {semantic_id or '<missing>'}"
            )
            continue
        semantic_quiet = semantic_event.get("treatment") == "quiet_source"
        storyboard_quiet = storyboard_event.get("treatment") == "quiet_source"
        if semantic_quiet != storyboard_quiet:
            errors.append(
                f"events[{index}] quiet_source classification must match "
                f"approved semantic event {semantic_id!r}"
            )
        fields = STORYBOARD_SEMANTIC_TIME_FIELDS
        if not semantic_quiet:
            fields += STORYBOARD_SEMANTIC_FIELDS
        if "treatment" in semantic_event:
            fields += ("treatment",)
        elif "treatment" in storyboard_event:
            errors.append(
                f"events[{index}] contains unapproved treatment for semantic event {semantic_id!r}"
            )
        if "approved_visible_copy" in semantic_event:
            fields += ("approved_visible_copy",)
        elif "approved_visible_copy" in storyboard_event:
            errors.append(
                f"events[{index}] contains unapproved visible copy for semantic event {semantic_id!r}"
            )
        approved_copy = _visible_copy_strings(semantic_event.get("approved_visible_copy"))
        manifest_value = storyboard_event.get("visible_copy_manifest")
        if not isinstance(manifest_value, list) or any(
            not isinstance(value, str) or not value.strip() for value in manifest_value
        ):
            errors.append(
                f"events[{index}] visible_copy_manifest must be an explicit list of non-empty strings"
            )
            manifest_copy: list[str] = []
        else:
            manifest_copy = _visible_copy_strings(manifest_value)
        if manifest_copy != approved_copy:
            errors.append(
                f"events[{index}] visible_copy_manifest must exactly match approved visible copy "
                f"for semantic event {semantic_id!r}"
            )
        for field_path, text in _event_visible_text_fields(
            storyboard_event, approved_copy=tuple(manifest_copy),
        ):
            if text not in manifest_copy:
                errors.append(
                    f"events[{index}] contains unapproved visible copy at {field_path}: {text!r}"
                )
        for field in fields:
            if field not in semantic_event:
                errors.append(
                    f"approved semantic event {semantic_id!r} requires {field} for storyboard binding"
                )
            elif field not in storyboard_event:
                errors.append(
                    f"events[{index}] must copy {field} from approved semantic event {semantic_id!r}"
                )
            elif storyboard_event[field] != semantic_event[field]:
                errors.append(
                    f"events[{index}] {field} must match approved semantic event {semantic_id!r}"
                )
        for storyboard_field, semantic_field in (
            ("start", "output_start"), ("end", "output_end"),
        ):
            if (
                storyboard_field in storyboard_event
                and semantic_field in semantic_event
                and storyboard_event[storyboard_field] != semantic_event[semantic_field]
            ):
                errors.append(
                    f"events[{index}] {storyboard_field} must match approved {semantic_field} "
                    f"for semantic event {semantic_id!r}"
                )
    return errors


def validate_storyboard(storyboard: dict[str, Any], brief: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    if storyboard.get("renderer") != "hyperframes":
        errors.append("storyboard renderer must be hyperframes")
    skills = set(storyboard.get("capability_skills") or [])
    required = {"hyperframes", "hyperframes-core", "hyperframes-creative", "hyperframes-animation", "hyperframes-cli"}
    missing = sorted(required - skills)
    if missing:
        errors.append(f"storyboard missing HyperFrames capability skills: {', '.join(missing)}")
    if storyboard.get("motion_output") != "hyperframes_render":
        errors.append("motion_output must be hyperframes_render; preview-only or FFmpeg card motion is forbidden")
    raw_events = storyboard.get("events")
    if raw_events is None:
        events: list[dict[str, Any]] = []
    elif not isinstance(raw_events, list):
        errors.append("storyboard events must be a list")
        events = []
    else:
        events = []
        for index, event in enumerate(raw_events):
            if not isinstance(event, dict):
                errors.append(f"events[{index}] must be a mapping")
            else:
                events.append(event)
    if brief is not None:
        errors.extend(validate_storyboard_semantic_binding(storyboard, brief))
    signatures: set[tuple[str, ...]] = set()
    for index, event in enumerate(events):
        if event.get("treatment") == "quiet_source":
            continue
        signature = visual_signature(event)
        if any(not value for value in signature):
            errors.append(f"events[{index}] missing distinct visual structure fields")
        elif signature in signatures:
            errors.append(f"events[{index}] repeats an existing DOM/layout/choreography contract")
        signatures.add(signature)
        if event_requires_connector_contract(event):
            errors.extend(_validate_connector_contract(event, f"events[{index}]"))
        if event_requires_target_region_contract(event):
            errors.extend(_validate_target_region_contract(event, f"events[{index}]"))
    return errors


def validate_video_use_edl(
    edl: dict[str, Any],
    *,
    source_name: str,
    source_duration: float,
    input_mode: str,
) -> list[str]:
    """Validate an EDL owned by video-use without authoring edit decisions."""
    errors: list[str] = []
    if edl.get("owner") != "video-use":
        errors.append("EDL owner must be video-use")
    sources = edl.get("sources") or {}
    if source_name not in sources:
        errors.append(f"EDL sources must include {source_name}")
    ranges = edl.get("ranges") or []
    if not ranges:
        errors.append("EDL requires at least one retained range")
        return errors
    retained = 0.0
    last_end = 0.0
    for index, row in enumerate(ranges):
        prefix = f"ranges[{index}]"
        if row.get("source") != source_name:
            errors.append(f"{prefix} references an unknown or unsupported source")
        try:
            start = float(row["start"])
            end = float(row["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{prefix} requires numeric start and end")
            continue
        if start < 0 or end <= start or end > source_duration + 0.1:
            errors.append(f"{prefix} is outside the source duration or has invalid order")
        retained += max(0.0, end - start)
        last_end = max(last_end, end)
    cut_policy = edl.get("cut_policy") or {}
    if not cut_policy.get("word_boundary_padding_ms") or cut_policy.get("audio_fade_ms") is None:
        errors.append("EDL requires video-use word-boundary padding and audio-fade policy")
    deletion_review = edl.get("deletion_review") or {}
    tail_review = edl.get("tail_review") or deletion_review
    if last_end < source_duration - 0.25 and tail_review.get("approved") is not True:
        errors.append("EDL removes the source tail without an explicit approved tail review")
    if input_mode == "polish_existing" and retained < source_duration * 0.98:
        if deletion_review.get("approved") is not True:
            errors.append("polish_existing EDL removes established timeline content without approval")
    return errors


def validate_video_use_media_analysis(
    report: dict[str, Any],
    *,
    source_path: Path,
    source_duration: float,
) -> list[str]:
    errors: list[str] = []
    if report.get("owner") != "video-use":
        errors.append("media analysis owner must be video-use")
    if report.get("source_sha256") != sha256_file(source_path):
        errors.append("media analysis source hash does not match")
    try:
        measured = float(report.get("duration_seconds"))
    except (TypeError, ValueError):
        errors.append("media analysis requires duration_seconds")
    else:
        if abs(measured - source_duration) > 0.1:
            errors.append("media analysis duration does not match ffprobe")
    if not report.get("video_stream"):
        errors.append("media analysis requires video_stream evidence")
    if not report.get("audio_stream"):
        errors.append("media analysis requires audio_stream evidence")
    views = [Path(str(path)) for path in (report.get("timeline_views") or [])]
    if len(views) < 3 or any(not path.is_file() for path in views):
        errors.append("media analysis requires at least three existing timeline_view images")
    return errors


def validate_video_use_edit_preflight(
    report: dict[str, Any],
    *,
    edl_path: Path,
    transcript_path: Path,
    edl: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if report.get("owner") != "video-use":
        errors.append("edit correctness preflight owner must be video-use")
    if report.get("status") != "pass":
        errors.append("edit correctness preflight status must be pass")
    if report.get("edl_sha256") != sha256_file(edl_path):
        errors.append("edit correctness preflight EDL hash does not match")
    if report.get("transcript_sha256") != sha256_file(transcript_path):
        errors.append("edit correctness preflight transcript hash does not match")
    ranges = edl.get("ranges") or []
    expected_boundaries = max(0, len(ranges) - 1)
    boundaries = report.get("boundaries") or []
    if int(report.get("boundary_count", -1)) != expected_boundaries or len(boundaries) != expected_boundaries:
        errors.append("edit correctness preflight boundary count does not match EDL")
    if expected_boundaries == 0:
        if report.get("identity_timeline") is not True:
            errors.append("single-range EDL must declare identity_timeline")
    else:
        for index, boundary in enumerate(boundaries):
            if boundary.get("word_boundary_safe") is not True:
                errors.append(f"boundaries[{index}] is not word-boundary safe")
            if boundary.get("audio_fade_configured") is not True:
                errors.append(f"boundaries[{index}] lacks configured audio fade")
            if not boundary.get("evidence"):
                errors.append(f"boundaries[{index}] lacks transcript or timeline evidence")
    if report.get("tail_covered") is not True:
        errors.append("edit correctness preflight must confirm tail coverage")
    try:
        expected_duration = sum(float(row["end"]) - float(row["start"]) for row in ranges)
        measured_duration = float(report.get("expected_output_duration"))
    except (KeyError, TypeError, ValueError):
        errors.append("edit correctness preflight requires expected_output_duration")
    else:
        if abs(expected_duration - measured_duration) > 0.1:
            errors.append("edit correctness preflight duration does not match EDL")
    return errors


def validate_video_use_final_correctness(
    report: dict[str, Any],
    *,
    output_path: Path,
    edl: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if report.get("owner") != "video-use" or report.get("status") != "pass":
        errors.append("final edit correctness must be a passing video-use report")
    if report.get("output_sha256") != sha256_file(output_path):
        errors.append("final edit correctness output hash does not match universal video")
    try:
        expected = sum(float(row["end"]) - float(row["start"]) for row in (edl.get("ranges") or []))
        declared_expected = float(report.get("expected_output_duration"))
        actual = float(report.get("actual_output_duration"))
    except (KeyError, TypeError, ValueError):
        errors.append("final edit correctness requires expected and actual output durations")
    else:
        if abs(expected - declared_expected) > 0.1 or abs(actual - expected) > 0.5:
            errors.append("final edit correctness duration does not match EDL expectation")
    expected_boundaries = max(0, len(edl.get("ranges") or []) - 1)
    boundaries = report.get("boundary_reviews") or []
    if len(boundaries) != expected_boundaries:
        errors.append("final edit correctness must review every actual cut boundary")
    for index, boundary in enumerate(boundaries):
        if boundary.get("visual_continuity") != "pass" or boundary.get("audio_boundary") != "pass":
            errors.append(f"boundary_reviews[{index}] did not pass visual and audio checks")
        evidence = Path(str(boundary.get("timeline_view", "")))
        if not evidence.is_file():
            errors.append(f"boundary_reviews[{index}] lacks timeline_view evidence")
    overview = [Path(str(path)) for path in (report.get("overview_timeline_views") or [])]
    if len(overview) < 3 or any(not path.is_file() for path in overview):
        errors.append("final edit correctness requires first, midpoint, and final timeline views")
    return errors


def validate_visual_vocabulary_audit(
    audit: dict[str, Any],
    storyboard: dict[str, Any],
    *,
    full_video: bool = False,
) -> list[str]:
    """Validate deliberate selection or rejection of the complete visual vocabulary.

    The contract does not force irrelevant treatments into a video. It does force
    every category to be considered with evidence, which prevents an author from
    silently collapsing the design into one recurring card template.
    """
    errors: list[str] = []
    categories = audit.get("categories") or {}
    event_ids = {str(event.get("id", "")) for event in (storyboard.get("events") or [])}
    selected_count = 0
    selected_event_ids: set[str] = set()
    for name in VISUAL_VOCABULARY:
        row = categories.get(name)
        if not isinstance(row, dict):
            errors.append(f"visual vocabulary category missing: {name}")
            continue
        status = row.get("status")
        if status not in VISUAL_VOCABULARY_STATUS:
            errors.append(f"visual vocabulary category {name} has invalid status")
            continue
        evidence = row.get("evidence") or []
        if not evidence:
            errors.append(f"visual vocabulary category {name} lacks evidence")
        if status == "selected":
            selected_count += 1
            declared = {str(item) for item in (row.get("event_ids") or [])}
            if not declared:
                errors.append(f"selected visual vocabulary category {name} requires event_ids")
            selected_event_ids.update(declared)
            unknown = sorted(declared - event_ids)
            if unknown:
                errors.append(f"visual vocabulary category {name} references unknown events: {', '.join(unknown)}")
        elif not str(row.get("rationale", "")).strip():
            errors.append(f"not-applicable visual vocabulary category {name} requires rationale")
    if selected_count < 4:
        errors.append("visual vocabulary requires at least four selected structures")
    if len(selected_event_ids) < 4:
        errors.append("visual vocabulary selections must reference at least four distinct storyboard events")
    if full_video:
        chapters = audit.get("chapter_decisions") or []
        if not chapters:
            errors.append("full-video visual vocabulary audit requires chapter_decisions")
        for index, chapter in enumerate(chapters):
            if not chapter.get("chapter_id") or not chapter.get("evidence"):
                errors.append(f"chapter_decisions[{index}] requires chapter_id and evidence")
            if not chapter.get("selected_categories") and not chapter.get("quiet_rationale"):
                errors.append(
                    f"chapter_decisions[{index}] requires selected_categories or evidence-backed quiet_rationale"
                )
            for category in chapter.get("selected_categories") or []:
                if category not in VISUAL_VOCABULARY:
                    errors.append(f"chapter_decisions[{index}] references unknown category: {category}")
                elif categories.get(category, {}).get("status") != "selected":
                    errors.append(f"chapter_decisions[{index}] references unselected category: {category}")
    return errors


def assert_valid(errors: list[str], artifact: str) -> None:
    if errors:
        raise DirectorContractError(f"{artifact} failed:\n- " + "\n- ".join(errors))
