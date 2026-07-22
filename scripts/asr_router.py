#!/usr/bin/env python3
"""Select an optional ASR backend and normalize its output to video-use words."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from director_contracts import read_json, write_json


BACKENDS = ("local_faster_whisper", "funasr", "whisperx")


def _available(config: dict[str, Any], name: str) -> bool:
    row = config.get("backends", {}).get(name, {})
    return isinstance(row, dict) and row.get("available") is True


def choose_backend(config: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    language = str(evidence.get("language") or "unknown").lower()
    hotwords = [str(value) for value in (evidence.get("hotwords") or []) if str(value).strip()]
    speaker_count = int(evidence.get("speaker_count") or 1)
    precise = evidence.get("precise_word_alignment") is True
    speaker_labels = evidence.get("speaker_labels") is True
    candidates: list[tuple[str, str]] = []
    if speaker_count > 1 or precise:
        candidates.append(("whisperx", "multiple speakers or precise word alignment requested"))
    if language.startswith("zh") and (hotwords or speaker_labels):
        candidates.append(("funasr", "Chinese hotwords or speaker labels requested"))
    candidates.append(("local_faster_whisper", "stable local default"))
    fallbacks: list[str] = []
    selected = None
    reason = None
    for name, candidate_reason in candidates:
        if _available(config, name):
            selected, reason = name, candidate_reason
            break
        fallbacks.append(f"{name}_unavailable")
    if selected is None:
        selected, reason = "none", "no configured ASR backend is available"
    return {
        "schema_version": 1,
        "selected_backend": selected,
        "reason": reason,
        "fallbacks": fallbacks,
        "evidence": {
            "language": language, "hotwords": hotwords, "speaker_count": speaker_count,
            "precise_word_alignment": precise, "speaker_labels": speaker_labels,
        },
        "semantic_deletion_authority": False,
        "output_contract": "video-use top-level word timestamps",
    }


def _word_rows(raw: dict[str, Any]) -> list[tuple[dict[str, Any], Any]]:
    if isinstance(raw.get("words"), list):
        return [(row, row.get("speaker_id", row.get("speaker"))) for row in raw["words"]]
    rows: list[tuple[dict[str, Any], Any]] = []
    for segment in raw.get("segments") or []:
        speaker = segment.get("speaker_id", segment.get("speaker"))
        for word in segment.get("words") or []:
            rows.append((word, word.get("speaker_id", word.get("speaker", speaker))))
    return rows


def normalize_transcript(raw: dict[str, Any], *, backend: str) -> dict[str, Any]:
    words: list[dict[str, Any]] = []
    for index, (row, speaker) in enumerate(_word_rows(raw)):
        raw_text = row.get("text", row.get("word"))
        if not isinstance(raw_text, str) or not raw_text or row.get("start") is None or row.get("end") is None:
            raise ValueError(f"missing text or timing at ASR word index {index}")
        text = raw_text
        try:
            start = float(row["start"])
            end = float(row["end"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid ASR word timing at index {index}") from error
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"invalid ASR word timing at index {index}")
        confidence = row.get("confidence", row.get("score", row.get("probability")))
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid ASR word confidence at index {index}") from error
            if not math.isfinite(confidence):
                raise ValueError(f"invalid ASR word confidence at index {index}")
        words.append({
            "id": row.get("id", f"w{len(words):06d}"),
            "type": "word",
            "text": text,
            "start": start,
            "end": end,
            "speaker_id": speaker,
            "confidence": confidence,
        })
    if not words:
        raise ValueError("ASR result contains no valid word timestamps")
    return {
        "schema_version": 1,
        "language_code": raw.get("language_code", raw.get("language", "unknown")),
        "words": words,
        "normalization": {
            "backend": backend,
            "text_or_timing_modified": False,
            "semantic_deletion_authority": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    route = sub.add_parser("route")
    route.add_argument("--config", required=True)
    route.add_argument("--evidence", required=True)
    route.add_argument("--out", required=True)
    normalize = sub.add_parser("normalize")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--backend", required=True, choices=BACKENDS)
    normalize.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "route":
        result = choose_backend(read_json(Path(args.config)), read_json(Path(args.evidence)))
    else:
        result = normalize_transcript(read_json(Path(args.input)), backend=args.backend)
    write_json(Path(args.out), result)
    print(Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
