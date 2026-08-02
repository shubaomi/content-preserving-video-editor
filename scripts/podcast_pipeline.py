#!/usr/bin/env python3
"""Validate an actually materialized clean PCM podcast asset and its source manifest."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _analyze_pcm(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels(); width = handle.getsampwidth()
            rate = handle.getframerate(); frames = handle.getnframes(); raw = handle.readframes(frames)
    except (wave.Error, EOFError) as error:
        raise ValueError("podcast audio is not a decodable PCM WAV") from error
    if width != 2 or not raw:
        raise ValueError("podcast PCM QA currently requires non-empty signed 16-bit WAV")
    values = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    peak = max(abs(value) for value in values) / 32768.0
    rms = math.sqrt(sum(value * value for value in values) / len(values)) / 32768.0
    return {
        "decode_status": "pass", "duration_seconds": frames / rate,
        "sample_rate": rate, "channels": channels,
        "loudness_dbfs": 20 * math.log10(max(rms, 1e-12)),
        "peak_dbfs": 20 * math.log10(max(peak, 1e-12)),
    }


def build_podcast_manifest(
    *, audio_path: Path, transcript_path: Path, chapters: list[dict[str, Any]],
    title: str, description: str, output: Path,
) -> dict[str, Any]:
    audio_path = audio_path.resolve(); transcript_path = transcript_path.resolve()
    transcript = read_json(transcript_path)
    word_ids = {str(row.get("id")) for row in transcript.get("words") or []}
    for chapter in chapters:
        ids = {str(value) for value in chapter.get("word_ids") or []}
        if not ids or not ids <= word_ids:
            raise ValueError("podcast chapter lacks current transcript word evidence")
    implementation = Path(__file__).resolve()
    report = {
        "schema_version": 1, "status": "pass", "title": title,
        "description": description, "clean_audio": {"path": str(audio_path),
            "sha256": sha256_file(audio_path)},
        "transcript": {"path": str(transcript_path), "sha256": sha256_file(transcript_path)},
        "chapters": chapters, "audio_qa": _analyze_pcm(audio_path),
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
    }
    report["integrity_sha256"] = _stable_hash(report)
    write_json(output.resolve(), report)
    return report


def validate_podcast_manifest(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1 or report.get("status") != "pass":
        errors.append("podcast manifest must be passing schema 1")
    for label in ("clean_audio", "transcript"):
        row = report.get(label) or {}; path = Path(str(row.get("path") or ""))
        if not path.is_file() or row.get("sha256") != (sha256_file(path) if path.is_file() else None):
            errors.append(f"podcast {label} binding is stale")
    qa = report.get("audio_qa") or {}
    if qa.get("decode_status") != "pass" or float(qa.get("duration_seconds") or 0) <= 0:
        errors.append("podcast audio decode or duration QA failed")
    if float(qa.get("peak_dbfs") or 1) > 0:
        errors.append("podcast audio peak exceeds 0 dBFS")
    if report.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in report.items() if key != "integrity_sha256"}
    ):
        errors.append("podcast manifest integrity hash is stale")
    implementation = report.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("podcast implementation binding is stale")
    return errors
