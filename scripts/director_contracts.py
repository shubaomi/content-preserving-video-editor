#!/usr/bin/env python3
"""Contracts shared by the content-preserving director and its QA gates."""
from __future__ import annotations

import hashlib
import json
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

STAGES = (
    "inspect",
    "video_use_timeline",
    "semantic_brief",
    "hyperframes_storyboard",
    "audio",
    "cover",
    "sample_qa",
    "preview_approval",
    "full_hyperframes_storyboard",
    "full_hyperframes_qa",
    "final_render",
    "final_compose",
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
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    if project.get("workflow", {}).get("input_mode") == "polish_existing":
        return "polish_existing"
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
    if int(brief.get("schema_version", 0)) < 1:
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
        signature = visual_signature(event)
        if any(not value for value in signature):
            errors.append(f"{prefix} visual_structure requires all five distinctness fields")
        elif signature in signatures:
            errors.append(f"{prefix} duplicates a previous visual structure contract")
        signatures.add(signature)
    if require_sample_variety and (visual_events < 4 or len(signatures) < 4):
        errors.append("sample requires at least four genuinely different visual structures")
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
    events = storyboard.get("events") or []
    if brief is not None and len(events) != len(brief.get("events") or []):
        errors.append("storyboard event count must match the approved semantic brief")
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
