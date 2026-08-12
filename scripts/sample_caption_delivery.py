#!/usr/bin/env python3
"""Burn one caption track into both sides of a paired sample review.

The HyperFrames sample is an intermediate motion render.  A preservation-first
review must not compare a captioned candidate with an uncaptioned baseline, and
it must not ask the user to approve media that omits a required final layer.
This module therefore applies the same hash-bound SRT to both review videos and
records the exact FFmpeg commands and decoded outputs.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from director_contracts import sha256_file, write_json


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _replace_with_retry(
    source: Path, destination: Path, *, timeout_seconds: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def build_caption_filter(captions: Path) -> str:
    value = captions.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")
    return f"subtitles=filename='{value}':charenc=UTF-8"


def _artifact_errors(record: Mapping[str, Any], label: str) -> list[str]:
    path = Path(str(record.get("path") or "")).resolve()
    if not path.is_file():
        return [f"{label} file is missing: {path}"]
    if record.get("sha256") != sha256_file(path):
        return [f"{label} hash is stale"]
    return []


def validate_receipt(receipt: Mapping[str, Any]) -> list[str]:
    if not isinstance(receipt, Mapping):
        return ["sample caption delivery receipt must be an object"]
    errors: list[str] = []
    if receipt.get("schema_version") != 1:
        errors.append("sample caption delivery schema_version must be 1")
    if receipt.get("mode") != "burned_in_last_for_paired_review":
        errors.append("sample caption delivery mode is invalid")
    caption = receipt.get("caption_source")
    if not isinstance(caption, Mapping):
        return [*errors, "sample caption source record is missing"]
    errors.extend(_artifact_errors(caption, "caption source"))

    durations: dict[str, float] = {}
    caption_hash = str(caption.get("sha256") or "")
    expected_filter = build_caption_filter(Path(str(caption.get("path") or "")))
    for role in ("baseline", "candidate"):
        row = receipt.get(role)
        if not isinstance(row, Mapping):
            errors.append(f"sample caption {role} record is missing")
            continue
        input_record = row.get("input")
        output_record = row.get("output")
        if not isinstance(input_record, Mapping) or not isinstance(output_record, Mapping):
            errors.append(f"sample caption {role} input/output record is missing")
            continue
        errors.extend(_artifact_errors(input_record, f"{role} input"))
        errors.extend(_artifact_errors(output_record, f"{role} output"))
        if Path(str(input_record.get("path") or "")).resolve() == Path(
            str(output_record.get("path") or "")
        ).resolve():
            errors.append(f"sample caption {role} must not overwrite its raw input")
        argv = [str(value) for value in row.get("argv") or []]
        if expected_filter not in argv or not any("subtitles=" in value for value in argv):
            errors.append(f"sample caption {role} command lacks the exact subtitles filter")
        if str(Path(str(output_record.get("path") or "")).resolve()) not in argv:
            errors.append(f"sample caption {role} command does not name its output")
        if row.get("full_decode") is not True:
            errors.append(f"sample caption {role} output lacks a successful full decode")
        if str(row.get("caption_sha256") or caption_hash) != caption_hash:
            errors.append(f"sample caption {role} uses a different caption hash")
        try:
            duration = float(output_record.get("duration_seconds"))
        except (TypeError, ValueError):
            errors.append(f"sample caption {role} output duration is invalid")
        else:
            if not math.isfinite(duration) or duration <= 0:
                errors.append(f"sample caption {role} output duration is invalid")
            else:
                durations[role] = duration

    if set(durations) == {"baseline", "candidate"} and not math.isclose(
        durations["baseline"], durations["candidate"], abs_tol=0.25,
    ):
        errors.append("captioned baseline and candidate durations are not aligned")
    return errors


def _probe_duration(path: Path, runner: Runner) -> float:
    completed = runner(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path.resolve()),
        ],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return float(completed.stdout.strip())


def _full_decode(path: Path, runner: Runner) -> None:
    runner(
        ["ffmpeg", "-v", "error", "-i", str(path.resolve()),
         "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )


def _render_captioned(
    source: Path, captions: Path, output: Path, *, runner: Runner,
) -> tuple[list[str], float]:
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(
        f".{output.stem}.{uuid.uuid4().hex}.captioning{output.suffix}"
    )
    temporary.unlink(missing_ok=True)
    argv = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vf", build_caption_filter(captions),
        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264",
        "-preset", "medium", "-crf", "18", "-c:a", "copy",
        "-movflags", "+faststart", str(temporary),
    ]
    try:
        runner(argv, check=True, capture_output=True, text=True, encoding="utf-8")
        _full_decode(temporary, runner)
        duration = _probe_duration(temporary, runner)
        _replace_with_retry(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    recorded = [str(output) if value == str(temporary) else value for value in argv]
    return recorded, duration


def materialize_pair(
    *,
    baseline_input: Path,
    candidate_input: Path,
    captions: Path,
    baseline_output: Path,
    candidate_output: Path,
    receipt_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    inputs = {
        "baseline": baseline_input.resolve(),
        "candidate": candidate_input.resolve(),
    }
    outputs = {
        "baseline": baseline_output.resolve(),
        "candidate": candidate_output.resolve(),
    }
    captions = captions.resolve()
    for label, path in {**inputs, "captions": captions}.items():
        if not path.is_file():
            raise FileNotFoundError(f"sample caption {label} is missing: {path}")

    rendered: dict[str, tuple[list[str], float]] = {}
    for role in ("baseline", "candidate"):
        rendered[role] = _render_captioned(
            inputs[role], captions, outputs[role], runner=runner,
        )

    caption_record = {"path": str(captions), "sha256": sha256_file(captions)}
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "burned_in_last_for_paired_review",
        "caption_source": caption_record,
    }
    for role in ("baseline", "candidate"):
        argv, duration = rendered[role]
        receipt[role] = {
            "input": {"path": str(inputs[role]), "sha256": sha256_file(inputs[role])},
            "output": {
                "path": str(outputs[role]), "sha256": sha256_file(outputs[role]),
                "duration_seconds": round(duration, 6),
            },
            "caption_sha256": caption_record["sha256"],
            "argv": argv,
            "full_decode": True,
        }
    errors = validate_receipt(receipt)
    if errors:
        raise ValueError("; ".join(errors))
    receipt_path = receipt_path.resolve()
    write_json(receipt_path, receipt)
    return receipt
