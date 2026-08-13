#!/usr/bin/env python3
"""Build source-preserving semantic emphasis captions as an ASS subtitle asset."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from director_contracts import sha256_file
from safe_generated_output import atomic_write_text, safe_generated_target


HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class CaptionTreatmentError(ValueError):
    """A caption treatment input cannot be rendered without weakening provenance."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptionTreatmentError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise CaptionTreatmentError(f"{label} must be finite")
    return result


SRT_TIMING = re.compile(
    r"^(\d+):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+"
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?$"
)


def _srt_seconds(groups: Sequence[str]) -> float:
    hours, minutes, seconds, milliseconds = (int(value) for value in groups)
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def _ass_centiseconds(seconds: float) -> int:
    return max(0, round(seconds * 100))


def parse_srt(path: Path) -> list[dict[str, Any]]:
    """Parse the authoritative SRT without silently repairing malformed segments."""
    if not path.is_file():
        raise CaptionTreatmentError("master.srt is missing")
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block for block in re.split(r"\n{2,}", text.strip()) if block.strip()]
    rows: list[dict[str, Any]] = []
    previous_end = 0.0
    previous_ass_end = 0
    for index, block in enumerate(blocks):
        lines = block.split("\n")
        if len(lines) < 3 or lines[0].strip() != str(index + 1):
            raise CaptionTreatmentError(f"master.srt segment {index} is malformed")
        match = SRT_TIMING.fullmatch(lines[1].strip())
        if match is None:
            raise CaptionTreatmentError(f"master.srt segment {index} timing is malformed")
        start = _srt_seconds(match.groups()[:4])
        end = _srt_seconds(match.groups()[4:])
        start_minutes, start_seconds = int(match.group(2)), int(match.group(3))
        end_minutes, end_seconds = int(match.group(6)), int(match.group(7))
        caption_text = "\n".join(lines[2:])
        if (
            start_minutes > 59 or start_seconds > 59
            or end_minutes > 59 or end_seconds > 59
            or not caption_text or end <= start or start < previous_end
            or _ass_centiseconds(end) <= _ass_centiseconds(start)
            or _ass_centiseconds(start) < previous_ass_end
        ):
            raise CaptionTreatmentError(f"master.srt segment {index} is invalid")
        rows.append({"start": start, "end": end, "text": caption_text})
        previous_end = end
        previous_ass_end = _ass_centiseconds(end)
    if not rows:
        raise CaptionTreatmentError("master.srt contains no caption segments")
    return rows


def _validated_caption_rows(captions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(captions, Sequence) or isinstance(captions, (str, bytes)):
        raise CaptionTreatmentError("captions must be a sequence")
    rows: list[dict[str, Any]] = []
    for index, caption in enumerate(captions):
        if not isinstance(caption, Mapping):
            raise CaptionTreatmentError(f"caption {index} must be an object")
        text = caption.get("text")
        start = _finite(caption.get("start"), f"caption {index} start")
        end = _finite(caption.get("end"), f"caption {index} end")
        if not isinstance(text, str) or not text or end <= start:
            raise CaptionTreatmentError(f"caption {index} is invalid")
        rows.append({"start": start, "end": end, "text": text})
    if not rows:
        raise CaptionTreatmentError("captions contain no segments")
    return rows


def _require_srt_equivalence(
    captions: Sequence[Mapping[str, Any]], srt_rows: Sequence[Mapping[str, Any]],
) -> None:
    caption_rows = _validated_caption_rows(captions)
    if len(caption_rows) != len(srt_rows):
        raise CaptionTreatmentError("captions.json segmentation differs from master.srt")
    for index, (caption, srt) in enumerate(zip(caption_rows, srt_rows)):
        if caption["text"] != srt.get("text"):
            raise CaptionTreatmentError(f"caption {index} text differs from master.srt")
        for field in ("start", "end"):
            # SRT is millisecond-quantized; compare the exact millisecond authority.
            if round(float(caption[field]) * 1000) != round(float(srt[field]) * 1000):
                raise CaptionTreatmentError(
                    f"caption {index} {field} differs from master.srt"
                )


def _options(options: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(options, Mapping):
        raise CaptionTreatmentError("caption treatment options must be an object")
    colors = options.get("accent_colors")
    if (
        not isinstance(colors, list) or not 1 <= len(colors) <= 3
        or any(not isinstance(value, str) or not HEX_COLOR.fullmatch(value) for value in colors)
    ):
        raise CaptionTreatmentError("accent_colors must contain one to three #RRGGBB values")
    base = options.get("base_color")
    if not isinstance(base, str) or not HEX_COLOR.fullmatch(base):
        raise CaptionTreatmentError("base_color must be #RRGGBB")
    maximum_terms = options.get("max_emphasis_terms_per_caption")
    if isinstance(maximum_terms, bool) or not isinstance(maximum_terms, int) or not 1 <= maximum_terms <= 2:
        raise CaptionTreatmentError("max_emphasis_terms_per_caption must be 1 or 2")
    scale = options.get("max_scale_percent")
    if isinstance(scale, bool) or not isinstance(scale, int) or not 105 <= scale <= 120:
        raise CaptionTreatmentError("max_scale_percent must be in [105, 120]")
    font = options.get("font_family")
    if not isinstance(font, str) or not font.strip() or any(char in font for char in "\r\n,;"):
        raise CaptionTreatmentError("font_family is invalid")
    return {
        "font_family": font.strip(), "base_color": base.upper(),
        "accent_colors": [value.upper() for value in colors],
        "max_emphasis_terms_per_caption": maximum_terms,
        "max_scale_percent": scale,
    }


def _approved_anchors(semantic_brief: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(semantic_brief, Mapping):
        raise CaptionTreatmentError("semantic brief must be an object")
    rows = semantic_brief.get("events")
    if not isinstance(rows, list):
        raise CaptionTreatmentError("semantic brief events must be a list")
    anchors: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("decision") not in {None, "render"}:
            continue
        anchor = str(row.get("anchor") or "").strip()
        word_ids = row.get("transcript_word_ids")
        event_id = str(row.get("id") or row.get("semantic_event_id") or "").strip()
        start = _finite(row.get("output_start"), f"semantic event {event_id} output_start")
        end = _finite(row.get("output_end"), f"semantic event {event_id} output_end")
        if not event_id or not anchor or end <= start:
            continue
        if not isinstance(word_ids, list) or not word_ids:
            continue
        approved = row.get("approved_visible_copy")
        if isinstance(approved, str):
            approved = [approved]
        if not isinstance(approved, list) or any(not isinstance(value, str) for value in approved):
            continue
        approved = [value.strip() for value in approved]
        if anchor not in approved:
            # Highlight text is visible copy and therefore needs explicit approval.
            continue
        anchors.append({
            "semantic_event_id": event_id, "text": anchor,
            "output_start": start, "output_end": end,
            "transcript_word_ids": [str(value) for value in word_ids],
            "approved_visible_copy": approved,
        })
    return anchors


def build_semantic_emphasis_plan(
    captions: Sequence[Mapping[str, Any]], semantic_brief: Mapping[str, Any],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic plan; caption wording and timing remain unchanged."""
    treatment = _options(options)
    anchors = _approved_anchors(semantic_brief)
    rows: list[dict[str, Any]] = []
    for index, caption in enumerate(_validated_caption_rows(captions)):
        text = caption["text"]
        start = caption["start"]
        end = caption["end"]
        emphasis: list[dict[str, Any]] = []
        occupied: list[tuple[int, int]] = []
        candidates = [row for row in anchors if row["output_start"] < end and row["output_end"] > start]
        candidates.sort(key=lambda row: (-len(row["text"]), row["semantic_event_id"]))
        for candidate in candidates:
            term = candidate["text"]
            position = text.find(term)
            if position < 0 or len(re.sub(r"\s", "", term)) < 2:
                continue
            bounds = (position, position + len(term))
            if any(bounds[0] < previous[1] and bounds[1] > previous[0] for previous in occupied):
                continue
            color = treatment["accent_colors"][len(emphasis) % len(treatment["accent_colors"])]
            emphasis.append({
                "text": term, "start_char": bounds[0], "end_char": bounds[1],
                "semantic_event_id": candidate["semantic_event_id"],
                "transcript_word_ids": candidate["transcript_word_ids"],
                "color": color, "scale_percent": treatment["max_scale_percent"],
            })
            occupied.append(bounds)
            if len(emphasis) >= treatment["max_emphasis_terms_per_caption"]:
                break
        rows.append({"index": index + 1, "start": start, "end": end, "text": text,
                     "emphasis": sorted(emphasis, key=lambda row: row["start_char"])})
    return {"schema_version": 1, "mode": "semantic_emphasis", "treatment": treatment,
            "captions": rows}


def _ass_time(seconds: float) -> str:
    centiseconds = _ass_centiseconds(seconds)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _ass_color(hex_color: str) -> str:
    red, green, blue = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H00{blue}{green}{red}&"


def _ass_escape(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _styled_text(row: Mapping[str, Any], scale: int) -> str:
    text = str(row["text"])
    output: list[str] = []
    cursor = 0
    for emphasis in row.get("emphasis") or []:
        start, end = int(emphasis["start_char"]), int(emphasis["end_char"])
        output.append(_ass_escape(text[cursor:start]))
        color = _ass_color(str(emphasis["color"]))
        output.append(
            "{\\b1\\c" + color + f"\\fscx{scale}\\fscy{scale}"
            + f"\\t(0,160,\\fscx{min(scale + 4, 120)}\\fscy{min(scale + 4, 120)})}}"
        )
        output.append(_ass_escape(text[start:end]))
        output.append("{\\rCaptionBase}")
        cursor = end
    output.append(_ass_escape(text[cursor:]))
    return "".join(output)


def render_ass(plan: Mapping[str, Any], *, width: int, height: int) -> str:
    if not isinstance(plan, Mapping) or plan.get("mode") != "semantic_emphasis":
        raise CaptionTreatmentError("caption emphasis plan is invalid")
    if (
        isinstance(width, bool) or not isinstance(width, int) or width <= 0
        or isinstance(height, bool) or not isinstance(height, int) or height <= 0
    ):
        raise CaptionTreatmentError("caption canvas dimensions are invalid")
    treatment = _options(plan.get("treatment") or {})
    captions = plan.get("captions")
    if not isinstance(captions, list) or not captions:
        raise CaptionTreatmentError("caption emphasis plan contains no captions")
    validated_rows = _validated_caption_rows(captions)
    for index, (row, validated) in enumerate(zip(captions, validated_rows)):
        emphasis = row.get("emphasis")
        if not isinstance(emphasis, list):
            raise CaptionTreatmentError(f"caption {index} emphasis must be a list")
        previous_end = 0
        for item in emphasis:
            if not isinstance(item, Mapping):
                raise CaptionTreatmentError(f"caption {index} emphasis is malformed")
            start = item.get("start_char")
            end = item.get("end_char")
            if (
                isinstance(start, bool) or not isinstance(start, int)
                or isinstance(end, bool) or not isinstance(end, int)
                or start < previous_end or end <= start or end > len(validated["text"])
                or item.get("text") != validated["text"][start:end]
                or not isinstance(item.get("semantic_event_id"), str)
                or not HEX_COLOR.fullmatch(str(item.get("color") or ""))
                or item.get("scale_percent") != treatment["max_scale_percent"]
            ):
                raise CaptionTreatmentError(f"caption {index} emphasis is invalid")
            previous_end = end
    font_size = max(38, round(height * 0.044))
    margin_v = max(52, round(height * 0.075))
    style = (
        "Style: CaptionBase," + treatment["font_family"] + f",{font_size},"
        + _ass_color(treatment["base_color"])
        + ",&H000000FF,&H00111111,&H99000000,-1,0,0,0,100,100,0,0,1,"
        "3.2,1.4,2,70,70," + str(margin_v) + ",1"
    )
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes", "WrapStyle: 0", "", "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding", style, "", "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for row in captions:
        lines.append(
            f"Dialogue: 0,{_ass_time(float(row['start']))},{_ass_time(float(row['end']))},"
            f"CaptionBase,,0,0,0,,{_styled_text(row, treatment['max_scale_percent'])}"
        )
    return "\n".join(lines) + "\n"


def materialize(
    *, captions_path: Path, semantic_brief_path: Path, master_srt_path: Path, output_ass: Path,
    output_plan: Path, options: Mapping[str, Any], width: int, height: int,
    authorized_root: Path,
) -> tuple[Path, Path]:
    captions_payload = json.loads(captions_path.read_text(encoding="utf-8"))
    semantic = json.loads(semantic_brief_path.read_text(encoding="utf-8"))
    if not isinstance(captions_payload, Mapping) or not isinstance(semantic, Mapping):
        raise CaptionTreatmentError("caption treatment inputs must be JSON objects")
    segments = captions_payload.get("segments")
    _require_srt_equivalence(segments, parse_srt(master_srt_path))
    plan = build_semantic_emphasis_plan(segments, semantic, options)
    plan["inputs"] = {
        "captions": {"path": str(captions_path.resolve()), "sha256": sha256_file(captions_path)},
        "semantic_brief": {"path": str(semantic_brief_path.resolve()),
                           "sha256": sha256_file(semantic_brief_path)},
        "master_srt": {"path": str(master_srt_path.resolve()),
                       "sha256": sha256_file(master_srt_path)},
    }
    plan["canvas"] = {"width": width, "height": height}
    lexical_root = Path(os.path.abspath(authorized_root))
    try:
        ass_relative = Path(os.path.abspath(output_ass)).relative_to(lexical_root)
        plan_relative = Path(os.path.abspath(output_plan)).relative_to(lexical_root)
    except ValueError as error:
        raise CaptionTreatmentError("caption treatment output escapes its authorized root") from error
    output_ass = safe_generated_target(lexical_root, ass_relative)
    output_plan = safe_generated_target(lexical_root, plan_relative)
    ass_text = render_ass(plan, width=width, height=height)
    atomic_write_text(output_ass, ass_text)
    plan["output"] = {"path": str(output_ass.resolve()), "sha256": sha256_file(output_ass)}
    atomic_write_text(output_plan, json.dumps(plan, ensure_ascii=False, indent=2,
                                              allow_nan=False) + "\n")
    return output_ass.resolve(), output_plan.resolve()


def validate_materialized(
    *, plan_path: Path, ass_path: Path, expected_master_srt: Path,
    expected_captions: Path, expected_semantic_brief: Path,
    expected_canvas: Mapping[str, Any],
    expected_options: Mapping[str, Any],
) -> list[str]:
    """Rebuild a styled caption asset from current authorities and compare exact bytes."""
    try:
        if not isinstance(expected_canvas, Mapping) or any(
            type(expected_canvas.get(key)) is not int or expected_canvas[key] <= 0
            for key in ("width", "height")
        ):
            return ["styled caption expected canvas is invalid"]
        if not plan_path.is_file() or not ass_path.is_file():
            return ["styled caption plan or ASS asset is missing"]
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(plan, Mapping):
            return ["styled caption plan must be an object"]
        if plan.get("treatment") != _options(expected_options):
            return ["styled caption treatment differs from current project configuration"]
        inputs = plan.get("inputs")
        if not isinstance(inputs, Mapping):
            return ["styled caption plan inputs are missing"]
        paths: dict[str, Path] = {}
        for name in ("captions", "semantic_brief", "master_srt"):
            row = inputs.get(name)
            if not isinstance(row, Mapping):
                return [f"styled caption {name} authority is missing"]
            path = Path(str(row.get("path") or "")).resolve()
            if not path.is_file() or row.get("sha256") != sha256_file(path):
                return [f"styled caption {name} authority is stale"]
            paths[name] = path
        if paths["master_srt"] != expected_master_srt.resolve():
            return ["styled caption master.srt authority is not canonical"]
        if paths["captions"] != expected_captions.resolve():
            return ["styled caption captions.json authority is not canonical"]
        if paths["semantic_brief"] != expected_semantic_brief.resolve():
            return ["styled caption semantic brief authority is not canonical"]
        output = plan.get("output")
        if (
            not isinstance(output, Mapping)
            or Path(str(output.get("path") or "")).resolve() != ass_path.resolve()
            or output.get("sha256") != sha256_file(ass_path)
        ):
            return ["styled caption output binding is stale"]
        canvas = plan.get("canvas")
        if not isinstance(canvas, Mapping):
            return ["styled caption canvas binding is missing"]
        if any(
            type(canvas.get(key)) is not int or canvas[key] <= 0
            for key in ("width", "height")
        ):
            return ["styled caption canvas binding is invalid"]
        if any(canvas[key] != expected_canvas[key] for key in ("width", "height")):
            return ["styled caption canvas differs from current media authority"]
        captions_payload = json.loads(paths["captions"].read_text(encoding="utf-8"))
        semantic = json.loads(paths["semantic_brief"].read_text(encoding="utf-8"))
        if not isinstance(captions_payload, Mapping) or not isinstance(semantic, Mapping):
            return ["styled caption input payload is malformed"]
        segments = captions_payload.get("segments")
        _require_srt_equivalence(segments, parse_srt(paths["master_srt"]))
        rebuilt = build_semantic_emphasis_plan(segments, semantic, plan.get("treatment") or {})
        rebuilt["inputs"] = dict(inputs)
        rebuilt["canvas"] = dict(canvas)
        expected_ass = render_ass(
            rebuilt, width=canvas.get("width"), height=canvas.get("height"),
        )
        if ass_path.read_bytes() != expected_ass.encode("utf-8"):
            return ["styled caption ASS differs from deterministic source authorities"]
        rebuilt["output"] = dict(output)
        if dict(plan) != rebuilt:
            return ["styled caption plan differs from deterministic source authorities"]
        expected_plan = json.dumps(
            rebuilt, ensure_ascii=False, indent=2, allow_nan=False,
        ).encode("utf-8") + b"\n"
        if plan_path.read_bytes() != expected_plan:
            return ["styled caption plan bytes are not canonical"]
        return []
    except (CaptionTreatmentError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        return [f"styled caption validation failed: {error}"]
