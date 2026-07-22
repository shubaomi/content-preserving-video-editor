#!/usr/bin/env python3
"""Hash-bound FFmpeg technical QA for the exact delivery bytes."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from director_contracts import sha256_file, write_json
from validate_platform_export import loudness


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def parse_black_freeze_silence(log: str) -> dict[str, list[dict[str, float]]]:
    black = [
        {"start": float(start), "end": float(end), "duration": float(duration)}
        for start, end, duration in re.findall(
            r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)", log
        )
    ]
    freeze: list[dict[str, float]] = []
    starts = [_float(value) for value in re.findall(r"freeze_start:\s*([\d.]+)", log)]
    durations = [_float(value) for value in re.findall(r"freeze_duration:\s*([\d.]+)", log)]
    ends = [_float(value) for value in re.findall(r"freeze_end:\s*([\d.]+)", log)]
    for index, start in enumerate(starts):
        if start is None:
            continue
        duration = durations[index] if index < len(durations) else None
        end = ends[index] if index < len(ends) else (start + duration if duration is not None else None)
        if end is not None:
            freeze.append({"start": start, "end": end, "duration": duration if duration is not None else end - start})
    silence = [
        {"start": float(start), "end": float(end), "duration": float(duration)}
        for start, end, duration in re.findall(
            r"silence_start:\s*([\d.]+).*?silence_end:\s*([\d.]+).*?silence_duration:\s*([\d.]+)",
            log, re.S,
        )
    ]
    return {"black": black, "freeze": freeze, "silence": silence}


def _probe(media: Path) -> dict[str, Any]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _detectors(media: Path) -> tuple[dict[str, list[dict[str, float]]], list[str]]:
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(media),
        "-vf", "blackdetect=d=0.5:pix_th=0.1,freezedetect=n=-50dB:d=2",
        "-af", "silencedetect=noise=-50dB:d=0.5", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    warnings = []
    if result.returncode != 0:
        warnings.append("one or more FFmpeg detector filters were unavailable or failed")
    return parse_black_freeze_silence(result.stderr), warnings


def _snapshot(media: Path, timestamp: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-ss", f"{timestamp:.3f}", "-i", str(media),
        "-frames:v", "1", str(output),
    ], check=True, capture_output=True)


def validate_report(report: dict[str, Any], media: Path) -> list[str]:
    media = media.resolve()
    errors: list[str] = []
    samples = report.get("samples") or []
    try:
        video_streams = int((report.get("media") or {}).get("video_streams", 0))
        audio_streams = int((report.get("media") or {}).get("audio_streams", 0))
    except (TypeError, ValueError):
        video_streams = audio_streams = 0
    if (
        not media.is_file()
        or report.get("schema_version") != 1
        or report.get("status") != "pass"
        or report.get("decode_status") != "pass"
        or report.get("file_sha256") != (sha256_file(media) if media.is_file() else None)
        or report.get("sha256") != (sha256_file(media) if media.is_file() else None)
        or (report.get("decode") or {}).get("status") != "pass"
        or video_streams < 1 or audio_streams < 1
        or (report.get("audio") or {}).get("measured") is not True
        or report.get("blocking_errors")
        or len(samples) < 3
    ):
        errors.append("technical media report structure or measurements did not pass")
    for sample in samples:
        path = Path(str(sample.get("path", "")))
        if not path.is_file() or sample.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append("technical media sample evidence is missing or stale")
    if media.is_file():
        try:
            current_probe = _probe(media)
            current_streams = current_probe.get("streams") or []
            current_decode = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(media), "-map", "0:v:0", "-map", "0:a?",
                "-f", "null", "-",
            ], capture_output=True).returncode == 0
            current_audio = loudness(media)
            recorded_audio = report.get("audio") or {}
            measurements_match = (
                current_audio.get("measured") is True
                and recorded_audio.get("measured") is True
                and abs(float(current_audio["integrated_lufs"])
                        - float(recorded_audio["integrated_lufs"])) <= 0.05
                and abs(float(current_audio["true_peak_dbtp"])
                        - float(recorded_audio["true_peak_dbtp"])) <= 0.05
            )
            if (
                not current_decode
                or (report.get("media") or {}).get("probe") != current_probe
                or video_streams != sum(row.get("codec_type") == "video" for row in current_streams)
                or audio_streams != sum(row.get("codec_type") == "audio" for row in current_streams)
                or not measurements_match
            ):
                errors.append("technical media report does not match fresh probe/decode/audio measurements")
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
            errors.append("technical media report could not be independently remeasured")
    return errors


def run_technical_qa(
    media: Path,
    *,
    output: Path,
    evidence_dir: Path,
    cut_boundaries: list[float] | None = None,
    true_peak_ceiling: float = -1.0,
) -> dict[str, Any]:
    media = media.resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    probe = _probe(media)
    streams = probe.get("streams") or []
    video_streams = [row for row in streams if row.get("codec_type") == "video"]
    audio_streams = [row for row in streams if row.get("codec_type") == "audio"]
    duration = float(probe.get("format", {}).get("duration") or 0.0)
    decode = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(media), "-map", "0:v:0", "-map", "0:a?",
        "-f", "null", "-",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    detector_results, warnings = _detectors(media)
    measured_audio = loudness(media)
    timestamps: list[tuple[str, float]] = [
        ("first", min(0.2, max(0.0, duration - 0.05))),
        ("middle", max(0.0, duration / 2)),
        ("final", max(0.0, duration - 0.1)),
    ]
    for index, boundary in enumerate(cut_boundaries or []):
        timestamps.append((f"cut-{index:03d}", min(max(0.0, float(boundary)), max(0.0, duration - 0.05))))
    samples: list[dict[str, Any]] = []
    for label, timestamp in timestamps:
        frame = evidence_dir / f"{label}-{timestamp:08.3f}.png"
        _snapshot(media, timestamp, frame)
        samples.append({"label": label, "time_seconds": timestamp, "path": str(frame.resolve()),
                        "sha256": sha256_file(frame)})
    blocking: list[str] = []
    if decode.returncode != 0:
        blocking.append("full decode failed")
    if not video_streams:
        blocking.append("video stream is missing")
    if not audio_streams:
        blocking.append("audio stream is missing")
    if not measured_audio.get("measured"):
        blocking.append("audio loudness could not be measured")
    elif float(measured_audio.get("true_peak_dbtp", 99)) > true_peak_ceiling:
        blocking.append("true peak exceeds configured ceiling")
    long_black = [row for row in detector_results["black"] if row["duration"] >= 2.0]
    long_freeze = [row for row in detector_results["freeze"] if row["duration"] >= 3.0]
    internal_silence = [
        row for row in detector_results["silence"]
        if row["duration"] >= 2.0 and row["start"] > 0.5 and row["end"] < duration - 0.5
    ]
    if long_black:
        warnings.append("long black-frame interval requires visual review")
    if long_freeze:
        warnings.append("long freeze interval requires visual review")
    if internal_silence:
        warnings.append("internal audio interruption requires review")
    report = {
        "schema_version": 1,
        "status": "pass" if not blocking else "failed",
        "file": str(media),
        "file_sha256": sha256_file(media),
        "sha256": sha256_file(media),
        "decode_status": "pass" if decode.returncode == 0 else "failed",
        "media": {
            "duration_seconds": duration,
            "size_bytes": media.stat().st_size,
            "video_streams": len(video_streams),
            "audio_streams": len(audio_streams),
            "probe": probe,
        },
        "decode": {"status": "pass" if decode.returncode == 0 else "failed", "errors": decode.stderr.strip()},
        "detectors": {**detector_results, "long_black": long_black, "long_freeze": long_freeze,
                      "internal_audio_interruptions": internal_silence},
        "audio": measured_audio,
        "true_peak_ceiling_dbtp": true_peak_ceiling,
        "samples": samples,
        "blocking_errors": blocking,
        "warnings": warnings,
    }
    write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--true-peak-ceiling", type=float, default=-1.0)
    parser.add_argument("--cut-boundary", action="append", type=float, default=[])
    args = parser.parse_args()
    report = run_technical_qa(
        Path(args.media), output=Path(args.out), evidence_dir=Path(args.evidence_dir),
        cut_boundaries=args.cut_boundary, true_peak_ceiling=args.true_peak_ceiling,
    )
    print(Path(args.out).resolve())
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
