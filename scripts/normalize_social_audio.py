#!/usr/bin/env python3
"""Two-pass EBU R128 normalization while copying the video stream."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure(path: Path, target_i: float, target_tp: float, lra: float) -> dict[str, Any]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
         f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:print_format=json",
         "-f", "null", "-"],
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=True,
    )
    blocks = re.findall(r'\{\s*"input_i".*?\}', result.stderr, re.S)
    if not blocks:
        raise RuntimeError("loudnorm did not return measurement JSON")
    return json.loads(blocks[-1])


def _measurement_errors(
    measurement: dict[str, Any], target_i: float, target_tp: float, lra: float,
) -> list[str]:
    try:
        measured_i = float(measurement["input_i"])
        measured_tp = float(measurement["input_tp"])
        measured_lra = float(measurement["input_lra"])
    except (KeyError, TypeError, ValueError):
        return ["post-normalization measurement lacks numeric input_i/input_tp/input_lra"]
    if not all(math.isfinite(value) for value in (measured_i, measured_tp, measured_lra)):
        return ["post-normalization measurement contains non-finite values"]
    errors: list[str] = []
    if abs(measured_i - target_i) > 1.0:
        errors.append(f"integrated loudness {measured_i:.2f} LUFS is outside ±1 LU of {target_i:.2f}")
    if measured_tp > target_tp + 0.1:
        errors.append(f"true peak {measured_tp:.2f} dBTP exceeds {target_tp + 0.1:.2f}")
    if measured_lra > lra + 1.0:
        errors.append(f"loudness range {measured_lra:.2f} exceeds {lra + 1.0:.2f}")
    return errors


def validate_report(
    report: dict[str, Any], source: Path, output: Path,
    target_i: float, target_tp: float, lra: float,
) -> list[str]:
    errors: list[str] = []
    if report.get("status") != "pass":
        errors.append("normalization status is not pass")
    if report.get("source_sha256") != sha256_file(source):
        errors.append("normalization source hash is stale")
    if report.get("output_sha256") != sha256_file(output):
        errors.append("normalization output hash is stale")
    target = report.get("target") or {}
    try:
        target_matches = (
            abs(float(target["integrated_lufs"]) - target_i) < 1e-9
            and abs(float(target["true_peak_dbtp"]) - target_tp) < 1e-9
            and abs(float(target["lra"]) - lra) < 1e-9
        )
    except (KeyError, TypeError, ValueError):
        target_matches = False
    if not target_matches:
        errors.append("normalization target parameters are missing or stale")
    first_pass = report.get("first_pass")
    if not isinstance(first_pass, dict):
        errors.append("normalization first-pass measurement is missing")
    else:
        required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        try:
            values = [float(first_pass[field]) for field in required]
        except (KeyError, TypeError, ValueError):
            errors.append("normalization first-pass measurement is incomplete or non-numeric")
        else:
            if not all(math.isfinite(value) for value in values):
                errors.append("normalization first-pass measurement contains non-finite values")
    post = report.get("post_measurement")
    if not isinstance(post, dict):
        errors.append("normalization post measurement is missing")
    else:
        errors.extend(_measurement_errors(post, target_i, target_tp, lra))
    return errors


@contextmanager
def _target_lock(output: Path, timeout_seconds: float = 30.0) -> Iterator[None]:
    lock = output.with_suffix(output.suffix + ".normalize.lock")
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"timed out waiting for normalization lock: {lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def normalize(
    source: Path, output: Path, target_i: float = -14.0,
    target_tp: float = -1.5, lra: float = 11.0,
) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with _target_lock(output):
        first = measure(source, target_i, target_tp, lra)
        filter_graph = (
            f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:"
            f"measured_I={first['input_i']}:measured_TP={first['input_tp']}:"
            f"measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}:"
            f"offset={first['target_offset']}:linear=true:print_format=json"
        )
        descriptor, temporary_name = tempfile.mkstemp(
            dir=output.parent, prefix=output.stem + ".", suffix=".partial" + output.suffix,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(source),
                 "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", filter_graph,
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(temporary)],
                text=True, encoding="utf-8", errors="replace", capture_output=True, check=True,
            )
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        post = measure(output, target_i, target_tp, lra)
        blocking_errors = _measurement_errors(post, target_i, target_tp, lra)
        return {
            "status": "failed" if blocking_errors else "pass",
            "blocking_errors": blocking_errors,
            "source": str(source), "source_sha256": sha256_file(source),
            "output": str(output), "output_sha256": sha256_file(output),
            "target": {"integrated_lufs": target_i, "true_peak_dbtp": target_tp, "lra": lra},
            "first_pass": first, "post_measurement": post,
            "method": "ffmpeg_two_pass_loudnorm", "video_stream": "copied",
            "audio_change": "documented_loudness_repair",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--lufs", type=float, default=-14)
    parser.add_argument("--true-peak", type=float, default=-1.5)
    parser.add_argument("--lra", type=float, default=11)
    args = parser.parse_args()
    report = normalize(
        Path(args.source), Path(args.out), args.lufs, args.true_peak, args.lra,
    )
    manifest = Path(args.manifest).resolve()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report["output"])
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
