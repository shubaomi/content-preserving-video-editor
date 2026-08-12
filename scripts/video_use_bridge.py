#!/usr/bin/env python3
"""Bridge video-use word/EDL artifacts into natural, output-timeline captions.

The bridge does not transcribe or choose edits. Those remain video-use-owned.
It consumes video-use's word transcript and EDL, applies its output timeline
formula, and groups the mapped verbatim words into readable Chinese phrases.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

from build_word_aligned_captions import _join, apply_replacements, srt_time
from director_contracts import sha256_file, write_json


def video_use_root() -> Path:
    configured = os.environ.get("VIDEO_USE_SKILL_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path.home() / ".codex" / "skills" / "video-use"


def render_helper_path() -> Path:
    return video_use_root() / "helpers" / "render.py"


def _load_video_use_render():
    path = render_helper_path()
    if not path.is_file():
        raise FileNotFoundError(f"video-use render helper not found: {path}")
    spec = importlib.util.spec_from_file_location("video_use_render", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load video-use helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _segments(edl: dict[str, Any]) -> list[dict[str, Any]]:
    rows = edl.get("segments", edl.get("ranges", []))
    normalized = []
    for index, row in enumerate(rows):
        normalized.append({
            "source": row.get("source", edl.get("source")),
            "start": float(row["start"]),
            "end": float(row["end"]),
            "timeline_start": row.get("timeline_start"),
            "index": index,
        })
    return normalized


def map_words_to_output(edl: dict[str, Any], transcripts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    helper = _load_video_use_render()
    mapped: list[dict[str, Any]] = []
    output_cursor = 0.0
    for segment in _segments(edl):
        source = str(segment.get("source") or "")
        if source not in transcripts:
            raise KeyError(f"missing video-use transcript for EDL source: {source}")
        start, end = segment["start"], segment["end"]
        if end <= start:
            raise ValueError(f"invalid EDL segment: {start}-{end}")
        timeline_start = float(segment["timeline_start"]) if segment["timeline_start"] is not None else output_cursor
        selected = helper._words_in_range(transcripts[source], start, end)
        for source_word_index, word in enumerate(selected):
            source_start = max(start, float(word["start"]))
            source_end = min(end, float(word["end"]))
            mapped.append({
                "text": str(word.get("word", word.get("text", ""))).strip(),
                "start": round(source_start - start + timeline_start, 6),
                "end": round(source_end - start + timeline_start, 6),
                "source": source,
                "source_start": source_start,
                "source_end": source_end,
                "source_word_id": word.get("id", source_word_index),
                "source_word_count": 1,
            })
        output_cursor = max(output_cursor, timeline_start + end - start)
    return [word for word in mapped if word["text"] and word["end"] > word["start"]]


def _visible_chars(text: str) -> int:
    import re
    return len(re.sub(r"[\s，。！？、；：,.!?;:]", "", text))


INCOMPLETE_SUFFIXES = (
    "和", "与", "及", "的", "了", "是", "把", "给", "给你", "对", "从", "为", "而", "或",
    "或者", "以及", "其他", "一个", "这个", "某个", "去做", "通过", "不会", "不改变",
    "原", "前", "帮", "概", "意", "核", "某", "某些", "来对", "做", "具体",
)
CLAUSE_STARTS = ("但是", "然后", "所以", "因为", "另外", "而是", "或者", "以及", "通过", "它是", "让", "去")
PHRASE_PUNCTUATION = tuple("，。！？；：,.!?;:")
SENTENCE_END_PUNCTUATION = tuple("。！？.!?")
PUNCTUATION_STYLES = {"source", "spoken_clean", "none"}
SYNC_WORD_SELECTION_TOLERANCE_SECONDS = 0.001


def _display_caption_text(text: str, punctuation_style: str) -> str:
    if punctuation_style not in PUNCTUATION_STYLES:
        raise ValueError(f"unsupported punctuation style: {punctuation_style}")
    if punctuation_style == "source":
        return text
    if punctuation_style == "none":
        import re
        return re.sub(r"[，。！？、；：,.!?;:]", "", text)
    # Spoken captions use punctuation for semantic boundaries but normally do
    # not display commas, stops, semicolons, or colons. Keep ?/! for tone.
    import re
    return re.sub(r"[，。；：、,.;:]", "", text)


def _detach_incomplete_tail(words: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    left = list(words)
    tail: list[dict[str, Any]] = []
    while len(left) > 3:
        phrase = _join(left).rstrip("，。！？；：,.!?;:")
        suffix = next((item for item in sorted(INCOMPLETE_SUFFIXES, key=len, reverse=True)
                       if phrase.endswith(item)), None)
        if suffix is None:
            break
        moved_chars = 0
        while left and moved_chars < _visible_chars(suffix):
            word = left.pop()
            tail.insert(0, word)
            moved_chars += _visible_chars(str(word["text"]))
    if tail and _visible_chars(_join(left)) >= 6:
        return left, tail
    return words, []


def _phrase_units(words: list[dict[str, Any]], pause_break: float) -> list[list[dict[str, Any]]]:
    units: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        current.append(word)
        text = str(word["text"])
        next_start = float(words[index + 1]["start"]) if index + 1 < len(words) else None
        pause = next_start - float(word["end"]) if next_start is not None else 999.0
        has_phrase_punctuation = text.endswith(PHRASE_PUNCTUATION)
        phrase_text = _join(current).rstrip("，。！？；：,.!?;:")
        if (not has_phrase_punctuation
                and pause >= pause_break
                and phrase_text.endswith(INCOMPLETE_SUFFIXES)):
            left, tail = _detach_incomplete_tail(current)
            if tail:
                units.append(left)
                current = tail
                continue
        meaningful_pause_phrase = (
            pause >= pause_break
            and _visible_chars(phrase_text) >= 6
            and not phrase_text.endswith(INCOMPLETE_SUFFIXES)
        )
        if has_phrase_punctuation or meaningful_pause_phrase or index + 1 == len(words):
            units.append(current)
            current = []
    return units


def _split_long_unit(unit: list[dict[str, Any]], hard_duration: float, hard_chars: int) -> list[list[dict[str, Any]]]:
    def semantic_cut(words: list[dict[str, Any]]) -> int | None:
        candidates = []
        for index in range(4, len(words) - 3):
            lookahead = _join(words[index:index + 4]).replace(" ", "")
            if any(lookahead.startswith(marker) for marker in CLAUSE_STARTS):
                candidates.append(index)
        return candidates[-1] if candidates else None

    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in unit:
        prospective = current + [word]
        too_long = current and (
            float(prospective[-1]["end"]) - float(prospective[0]["start"]) > hard_duration
            or _visible_chars(_join(prospective)) > hard_chars
        )
        if too_long:
            cut = semantic_cut(current)
            if cut is None:
                chunks.append(current)
                current = []
            else:
                chunks.append(current[:cut])
                current = current[cut:]
        current.append(word)
    if current:
        chunks.append(current)
    for index in range(len(chunks) - 1):
        left, moved = _detach_incomplete_tail(chunks[index])
        if moved:
            chunks[index] = left
            chunks[index + 1] = moved + chunks[index + 1]
    if len(chunks) >= 2 and _visible_chars(_join(chunks[-1])) <= 4:
        combined = chunks[-2] + chunks[-1]
        combined_duration = float(combined[-1]["end"]) - float(combined[0]["start"])
        if combined_duration <= hard_duration and _visible_chars(_join(combined)) <= hard_chars + 6:
            chunks[-2:] = [combined]
    return [chunk for chunk in chunks if chunk]


def build_captions(mapped_words: list[dict[str, Any]], *, max_chars: int = 24,
                   max_duration: float = 6.5, pause_break: float = 0.5,
                   punctuation_style: str = "source") -> list[dict[str, Any]]:
    """Group verbatim mapped words at punctuation/pause boundaries first.

    The target limits guide packing but never split a short semantic phrase in
    the middle merely to hit a duration quota. Hard limits remain bounded.
    """
    hard_duration = max_duration + 6.0
    hard_chars = max_chars + 8
    units: list[list[dict[str, Any]]] = []
    for unit in _phrase_units(mapped_words, pause_break):
        if (float(unit[-1]["end"]) - float(unit[0]["start"]) > hard_duration
                or _visible_chars(_join(unit)) > hard_chars):
            units.extend(_split_long_unit(unit, hard_duration, hard_chars))
        else:
            units.append(unit)
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for unit in units:
        if current:
            current_ends_sentence = str(current[-1]["text"]).endswith(SENTENCE_END_PUNCTUATION)
            current_ends_meaningful_clause = (
                str(current[-1]["text"]).endswith(PHRASE_PUNCTUATION)
                and _visible_chars(_join(current)) >= 6
            )
            if current_ends_sentence or current_ends_meaningful_clause:
                groups.append(current)
                current = []
        prospective = current + unit
        exceeds_target = current and (
            float(prospective[-1]["end"]) - float(prospective[0]["start"]) > max_duration
            or _visible_chars(_join(prospective)) > max_chars
        )
        if exceeds_target:
            groups.append(current)
            current = []
        current.extend(unit)
    if current:
        groups.append(current)
    captions = []
    word_cursor = 0
    for group in groups:
        captions.append({
            "start": round(float(group[0]["start"]), 3),
            "end": round(float(group[-1]["end"]), 3),
            "text": _display_caption_text(_join(group), punctuation_style),
            "timeline": "output",
            "alignment": "word_timestamp",
            "mapping_owner": "video-use",
            "source_word_start": word_cursor,
            "source_word_end": word_cursor + len(group) - 1,
        })
        word_cursor += len(group)
    return captions


def apply_audited_corrections(mapped_words: list[dict[str, Any]], corrections: dict[str, Any] | None
                              ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not corrections:
        return mapped_words, []
    corrected, applied = apply_replacements(mapped_words, corrections.get("replacements", []))
    return corrected, applied


def synchronization_report(
    mapped_words: list[dict[str, Any]], captions: list[dict[str, Any]],
    sample_count: int = 8, *, cut_boundaries: list[float] | None = None,
    terminology: list[str] | None = None,
    final_composite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not captions:
        return {"passed": False, "reason": "no captions", "samples": []}
    required_indices = {0, len(captions) // 2, len(captions) - 1}
    cut_coverage = []
    for boundary in cut_boundaries or []:
        nearest_index = min(
            range(len(captions)),
            key=lambda index: min(
                abs(float(captions[index]["start"]) - float(boundary)),
                abs(float(captions[index]["end"]) - float(boundary)),
            ),
        )
        required_indices.add(nearest_index)
        cut_coverage.append({
            "time": round(float(boundary), 3),
            "caption_index": nearest_index,
        })
    terminology_coverage: dict[str, dict[str, Any]] = {}
    for term in terminology or []:
        matches = [
            index for index, caption in enumerate(captions)
            if str(term) in str(caption.get("text") or "")
        ]
        if matches:
            required_indices.add(matches[0])
            terminology_coverage[str(term)] = {
                "status": "sampled", "caption_index": matches[0],
            }
        else:
            terminology_coverage[str(term)] = {"status": "not_found"}
    target_count = max(max(1, sample_count), len(required_indices))
    if target_count > len(required_indices):
        stride = max(1, len(captions) // target_count)
        required_indices.update(range(0, len(captions), stride))
    selected_indices = sorted(required_indices)[:max(target_count, len(required_indices))]
    samples = []
    for caption_index in selected_indices:
        caption = captions[caption_index]
        caption_start = float(caption["start"])
        caption_end = float(caption["end"])
        words = [word for word in mapped_words
                 if float(word["start"]) >= (
                     caption_start - SYNC_WORD_SELECTION_TOLERANCE_SECONDS
                 )
                 and float(word["end"]) <= (
                     caption_end + SYNC_WORD_SELECTION_TOLERANCE_SECONDS
                 )]
        if not words:
            samples.append({"caption_index": caption_index, "passed": False, "reason": "no mapped words"})
        else:
            lead = abs(float(caption["start"]) - float(words[0]["start"]))
            lag = abs(float(caption["end"]) - float(words[-1]["end"]))
            samples.append({
                "caption_index": caption_index,
                "time": caption["start"],
                "text": caption["text"],
                "lead_error_s": round(lead, 4),
                "tail_error_s": round(lag, 4),
                "passed": lead <= 0.08 and lag <= 0.08,
            })
    overlaps = [index for index in range(1, len(captions))
                if float(captions[index]["start"]) < float(captions[index - 1]["end"])]
    composite = dict(final_composite or {})
    if composite.get("required") is True:
        composite["passed"] = (
            composite.get("full_av_decode") is True
            and composite.get("subtitle_filter_verified") is True
            and bool(re.fullmatch(r"[a-f0-9]{64}", str(composite.get("media_sha256") or "")))
            and bool(re.fullmatch(r"[a-f0-9]{64}", str(composite.get("caption_sha256") or "")))
        )
    else:
        composite["passed"] = True
    return {
        "schema_version": 2,
        "mapping_owner": "video-use",
        "formula": "word.start - segment.start + segment.timeline_start",
        "sample_count": len(samples),
        "samples": samples,
        "coverage": {
            "first_caption_index": 0,
            "middle_caption_index": len(captions) // 2,
            "last_caption_index": len(captions) - 1,
            "required_caption_indices": sorted(required_indices),
            "cut_boundaries": cut_coverage,
            "terminology": terminology_coverage,
        },
        "final_composite": composite,
        "overlap_indices": overlaps,
        "passed": (
            bool(samples) and all(item.get("passed") for item in samples)
            and not overlaps and composite["passed"]
            and all(row["status"] == "sampled" for row in terminology_coverage.values())
        ),
    }


def render_command(edl_path: Path, output_path: Path, *, preview: bool = False) -> list[str]:
    command = ["python", str(render_helper_path()), str(edl_path), "-o", str(output_path), "--build-subtitles"]
    if preview:
        command.append("--preview")
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edl", required=True)
    parser.add_argument("--transcript", action="append", required=True,
                        help="source-name=path-to-video-use-word-transcript.json")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--corrections", help="audited terminology/spelling replacements with evidence")
    parser.add_argument("--max-chars", type=int, default=24)
    parser.add_argument("--max-duration", type=float, default=6.5)
    parser.add_argument("--pause-break", type=float, default=0.5)
    parser.add_argument("--punctuation-style", choices=sorted(PUNCTUATION_STYLES),
                        default="spoken_clean")
    parser.add_argument("--cut-boundary", action="append", type=float, default=[])
    parser.add_argument("--terminology", action="append", default=[])
    args = parser.parse_args()
    edl_path = Path(args.edl).resolve()
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    transcripts: dict[str, dict[str, Any]] = {}
    provenance: dict[str, str] = {}
    for item in args.transcript:
        source, path_value = item.split("=", 1)
        path = Path(path_value).resolve()
        transcripts[source] = json.loads(path.read_text(encoding="utf-8"))
        provenance[source] = sha256_file(path)
    mapped = map_words_to_output(edl, transcripts)
    corrections = json.loads(Path(args.corrections).read_text(encoding="utf-8")) if args.corrections else None
    corrected, applied = apply_audited_corrections(mapped, corrections)
    captions = build_captions(corrected, max_chars=args.max_chars,
                              max_duration=args.max_duration, pause_break=args.pause_break,
                              punctuation_style=args.punctuation_style)
    report = synchronization_report(
        corrected, captions, cut_boundaries=args.cut_boundary, terminology=args.terminology,
    )
    report["applied_corrections"] = applied
    report["text_policy"] = "verbatim mapped words plus audited evidenced corrections; no summarization"
    report["punctuation_style"] = args.punctuation_style
    report["edl_sha256"] = sha256_file(edl_path)
    report["transcript_sha256"] = provenance
    report["video_use_helper"] = str(render_helper_path())
    out = Path(args.out_dir).resolve()
    write_json(out / "mapped-words.json", {"words": corrected})
    write_json(out / "captions.json", {"version": 2, "segments": captions})
    write_json(out / "caption-sync-report.json", report)
    blocks = [f"{index}\n{srt_time(row['start'])} --> {srt_time(row['end'])}\n{row['text']}"
              for index, row in enumerate(captions, 1)]
    (out / "master.srt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(out / "caption-sync-report.json")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
