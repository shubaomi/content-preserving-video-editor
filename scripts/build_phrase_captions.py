#!/usr/bin/env python3
"""Build traceable phrase-level SRT from a word-timed transcript.

The caller supplies ordered ending word IDs. Text is never rewritten: each cue
is the exact concatenation of its source words, and the output sidecar retains
the source IDs for audit and replay.
"""

from __future__ import annotations

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


_SPOKEN_PUNCTUATION_RE = re.compile(r"[，。！？；：、,.!?;:…—\-]+")


def _display_text(source_text: str, punctuation_style: str) -> str:
    if punctuation_style == "preserve":
        return source_text
    if punctuation_style == "spoken_clean":
        return _SPOKEN_PUNCTUATION_RE.sub("", source_text)
    raise ValueError(f"unsupported punctuation style: {punctuation_style}")


def build_phrase_rows(
    transcript: dict[str, Any],
    end_word_ids: list[str],
    *,
    punctuation_style: str = "preserve",
) -> list[dict[str, Any]]:
    words = transcript.get("words")
    if not isinstance(words, list) or not words or not all(isinstance(row, dict) for row in words):
        raise ValueError("word transcript must contain word records")
    ids = [str(row.get("id") or row.get("source_word_id") or "") for row in words]
    if len(set(ids)) != len(ids) or any(not word_id for word_id in ids):
        raise ValueError("word IDs must be non-empty and unique")
    if not end_word_ids or len(set(end_word_ids)) != len(end_word_ids):
        raise ValueError("caption boundary IDs must be non-empty and unique")
    try:
        end_indexes = [ids.index(word_id) for word_id in end_word_ids]
    except ValueError as error:
        raise ValueError("caption boundary references an unknown word ID") from error
    if end_indexes != sorted(end_indexes) or end_indexes[-1] != len(words) - 1:
        raise ValueError("caption boundaries must be ordered and cover the final word")

    rows: list[dict[str, Any]] = []
    first = 0
    for last in end_indexes:
        group = words[first:last + 1]
        source_text = "".join(str(row.get("text") or "") for row in group).strip()
        text = _display_text(source_text, punctuation_style).strip()
        start = float(group[0]["start"])
        end = float(group[-1]["end"])
        if not text or end <= start:
            raise ValueError("caption phrase has empty text or invalid timing")
        rows.append({
            "index": len(rows) + 1,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "source_text": source_text,
            "word_ids": [str(row.get("id") or row.get("source_word_id")) for row in group],
        })
        first = last + 1
    return rows


def write_outputs(
    transcript_path: Path,
    end_word_ids: list[str],
    srt_path: Path,
    plan_path: Path,
    *,
    punctuation_style: str = "preserve",
) -> dict[str, Any]:
    transcript_path = transcript_path.resolve()
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    rows = build_phrase_rows(payload, end_word_ids, punctuation_style=punctuation_style)
    srt = "\n\n".join(
        f"{row['index']}\n{_timestamp(row['start'])} --> {_timestamp(row['end'])}\n{row['text']}"
        for row in rows
    ) + "\n"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text(srt, encoding="utf-8", newline="\n")
    transcript_hash = sha256(transcript_path.read_bytes()).hexdigest()
    srt_hash = sha256(srt_path.read_bytes()).hexdigest()
    plan = {
        "schema_version": 1,
        "artifact_type": "word_bound_phrase_caption_plan",
        "source_transcript": {"path": str(transcript_path), "sha256": transcript_hash},
        "caption_srt": {"path": str(srt_path.resolve()), "sha256": srt_hash},
        "punctuation_style": punctuation_style,
        "phrases": rows,
        "source_text_preserved": "".join(row["source_text"] for row in rows) == "".join(
            str(word.get("text") or "") for word in payload["words"]
        ),
    }
    plan["text_preserved"] = plan["source_text_preserved"] and punctuation_style == "preserve"
    if not plan["source_text_preserved"]:
        raise ValueError("caption segmentation changed transcript text")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--end-word-ids", required=True, help="comma-separated ordered word IDs")
    parser.add_argument("--srt", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--punctuation-style", choices=("preserve", "spoken_clean"), default="preserve")
    args = parser.parse_args()
    plan = write_outputs(
        Path(args.transcript), [row.strip() for row in args.end_word_ids.split(",") if row.strip()],
        Path(args.srt), Path(args.plan), punctuation_style=args.punctuation_style,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
