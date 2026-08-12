#!/usr/bin/env python3
"""Build verbatim sentence captions from ASR word timestamps and audited corrections."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TERMINAL = "。！？!?"


def _key(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:\-_'\"“”‘’]", "", text).lower()


def _text(item: dict) -> str:
    return str(item.get("word", item.get("text", ""))).strip()


def flatten_words(raw: dict) -> list[dict]:
    source = raw if isinstance(raw, list) else raw.get("segments", raw.get("words", []))
    words: list[dict] = []
    for segment in source:
        nested = segment.get("words") if isinstance(segment, dict) else None
        rows = nested if nested is not None else [segment]
        for item in rows:
            text = _text(item)
            if not text:
                continue
            words.append({
                "text": text.replace(",", "，"),
                "start": float(item["start"]),
                "end": float(item["end"]),
                "source_word_count": 1,
            })
    return words


def apply_replacements(words: list[dict], replacements: list[dict]) -> tuple[list[dict], list[dict]]:
    output = list(words)
    applied: list[dict] = []
    for replacement in sorted(replacements, key=lambda row: len(_key(str(row["from"]))), reverse=True):
        needle = _key(str(replacement["from"]))
        replacement_text = str(replacement["to"])
        if not needle or str(replacement["from"]).strip() == replacement_text.strip():
            continue
        index = 0
        while index < len(output):
            if not _key(str(output[index].get("text", ""))):
                index += 1
                continue
            combined = ""
            matched_end = None
            for right in range(index, min(len(output), index + 40)):
                combined += _key(output[right]["text"])
                if combined == needle:
                    matched_end = right
                    break
                if not needle.startswith(combined):
                    break
            if matched_end is None:
                index += 1
                continue
            selected = output[index:matched_end + 1]
            tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|[^\s]", replacement_text)
            start = float(selected[0]["start"])
            end = float(selected[-1]["end"])
            duration = max(0.001, end - start)
            source_count = sum(int(item.get("source_word_count", 1)) for item in selected)
            pieces: list[dict] = []
            for token_index, token in enumerate(tokens or [replacement_text]):
                token_start = start + duration * token_index / max(1, len(tokens))
                token_end = start + duration * (token_index + 1) / max(1, len(tokens))
                pieces.append({
                    "text": token,
                    "start": token_start,
                    "end": token_end,
                    "source_word_count": source_count if token_index == len(tokens) - 1 else 0,
                    "correction_evidence": str(replacement.get("evidence", "")),
                    "timing_note": "interpolated within audited source-word span",
                })
            output[index:matched_end + 1] = pieces
            applied.append({
                "from": replacement["from"], "to": replacement["to"],
                "start": start, "end": end,
                "evidence": str(replacement.get("evidence", "")),
            })
            index += len(pieces)
    return output, applied


def _join(words: list[dict]) -> str:
    text = ""
    for word in words:
        value = str(word["text"]).strip()
        if text and re.search(r"[A-Za-z0-9]$", text) and re.match(r"[A-Za-z0-9]", value):
            text += " "
        text += value
    text = re.sub(r"\s+([，。！？、；：,.!?;:])", r"\1", text)
    return text.strip()


def group_captions(words: list[dict], *, max_chars: int = 20, max_duration: float = 4.2,
                   pause_break: float = 0.55) -> list[dict]:
    captions: list[dict] = []
    current: list[dict] = []
    source_index = 0
    caption_start_index = 0
    for index, word in enumerate(words):
        if current:
            prospective_duration = float(word["end"]) - float(current[0]["start"])
            current_text = _join(current)
            prospective_text = _join(current + [word])
            current_visible = len(re.sub(r"[\s，。！？、；：,.!?;:]", "", current_text))
            prospective_visible = len(re.sub(r"[\s，。！？、；：,.!?;:]", "", prospective_text))
            if prospective_duration > max_duration or (prospective_visible > max_chars and current_visible >= 6):
                captions.append({
                    "start": round(float(current[0]["start"]), 3),
                    "end": round(float(current[-1]["end"]), 3),
                    "text": current_text,
                    "timeline": "source",
                    "alignment": "word_timestamp",
                    "source_word_start": caption_start_index,
                    "source_word_end": source_index - 1,
                })
                current = []
        if not current:
            caption_start_index = source_index
        current.append(word)
        text = _join(current)
        duration = float(current[-1]["end"]) - float(current[0]["start"])
        next_start = float(words[index + 1]["start"]) if index + 1 < len(words) else None
        pause = next_start - float(word["end"]) if next_start is not None else 999.0
        visible_chars = len(re.sub(r"[\s，。！？、；：,.!?;:]", "", text))
        should_break = (
            text.endswith(tuple(TERMINAL))
            or (pause >= pause_break and visible_chars >= 6)
            or (duration >= max_duration and visible_chars >= 8)
            or visible_chars >= max_chars
            or index + 1 == len(words)
        )
        source_index += int(word.get("source_word_count", 1))
        if not should_break:
            continue
        captions.append({
            "start": round(float(current[0]["start"]), 3),
            "end": round(float(current[-1]["end"]), 3),
            "text": text,
            "timeline": "source",
            "alignment": "word_timestamp",
            "source_word_start": caption_start_index,
            "source_word_end": source_index - 1,
        })
        current = []
    return captions


def srt_time(value: float) -> str:
    milliseconds = round(value * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def build(raw: dict, corrections: dict | None = None, **grouping) -> tuple[dict, str, dict]:
    words = flatten_words(raw)
    corrected, applied = apply_replacements(words, (corrections or {}).get("replacements", []))
    captions = group_captions(corrected, **grouping)
    overlaps = [index for index in range(1, len(captions)) if captions[index]["start"] < captions[index - 1]["end"]]
    blocks = [
        f"{index}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}"
        for index, item in enumerate(captions, 1)
    ]
    max_caption_duration = max((item["end"] - item["start"] for item in captions), default=0)
    max_visible_chars = max((len(_key(item["text"])) for item in captions), default=0)
    duration_limit = float(grouping.get("max_duration", 4.2))
    chars_limit = int(grouping.get("max_chars", 20))
    report = {
        "schema_version": 1,
        "timing_source": "ASR word timestamps",
        "text_policy": "verbatim words plus audited replacements; no summarization",
        "source_word_count": sum(item.get("source_word_count", 1) for item in corrected),
        "caption_count": len(captions),
        "applied_corrections": applied,
        "max_caption_duration": round(max_caption_duration, 3),
        "max_caption_chars": max((len(item["text"]) for item in captions), default=0),
        "max_caption_visible_chars": max_visible_chars,
        "duration_limit": duration_limit,
        "visible_chars_limit": chars_limit,
        "overlap_indices": overlaps,
        "passed": (
            bool(captions)
            and not overlaps
            and max_caption_duration <= duration_limit + 0.05
            and max_visible_chars <= chars_limit
            and all(item["alignment"] == "word_timestamp" for item in captions)
        ),
    }
    return {"version": 2, "segments": captions}, "\n\n".join(blocks) + "\n", report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--corrections")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-srt", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--max-chars", type=int, default=20)
    parser.add_argument("--max-duration", type=float, default=4.2)
    parser.add_argument("--pause-break", type=float, default=0.55)
    args = parser.parse_args()
    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    corrections = json.loads(Path(args.corrections).read_text(encoding="utf-8")) if args.corrections else None
    data, srt, report = build(raw, corrections, max_chars=args.max_chars,
                              max_duration=args.max_duration, pause_break=args.pause_break)
    outputs = ((Path(args.out_json), json.dumps(data, ensure_ascii=False, indent=2) + "\n"),
               (Path(args.out_srt), srt),
               (Path(args.report), json.dumps(report, ensure_ascii=False, indent=2) + "\n"))
    for path, content in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(args.report)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
