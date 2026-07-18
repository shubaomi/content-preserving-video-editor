#!/usr/bin/env python3
"""Verify that a polish variant preserves the baseline timeline and audio."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,duration,sample_rate,channels,width,height",
        "-of", "json", str(path),
    ], text=True, encoding="utf-8"))


def audio_hash(path: Path) -> str | None:
    if not any(item.get("codec_type") == "audio" for item in probe(path).get("streams", [])):
        return None
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-map", "0:a:0", "-vn", "-f", "hash", "-hash", "sha256", "-",
    ], text=True, encoding="utf-8", capture_output=True, check=True)
    return result.stdout.strip().split("=", 1)[-1]


def decode_check(path: Path, timestamp: float) -> bool:
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}",
        "-i", str(path), "-frames:v", "1", "-f", "null", "-",
    ], capture_output=True)
    return result.returncode == 0


def verify(baseline: Path, variant: Path, tolerance: float, audio_mode: str) -> dict:
    base = probe(baseline)
    polished = probe(variant)
    base_duration = float(base["format"]["duration"])
    variant_duration = float(polished["format"]["duration"])
    delta = abs(base_duration - variant_duration)
    base_audio = any(item.get("codec_type") == "audio" for item in base.get("streams", []))
    variant_audio = any(item.get("codec_type") == "audio" for item in polished.get("streams", []))
    exact_hash = None
    if audio_mode == "exact" and base_audio and variant_audio:
        exact_hash = audio_hash(baseline) == audio_hash(variant)
    checks = {
        "different_output_path": baseline.resolve() != variant.resolve(),
        "duration_within_tolerance": delta <= tolerance,
        "audio_stream_presence_preserved": base_audio == variant_audio,
        "audio_exactly_preserved": exact_hash,
        "first_frame_decodes": decode_check(variant, 0.0),
        "last_frame_decodes": decode_check(variant, max(0.0, variant_duration - 0.2)),
    }
    required = [
        checks["different_output_path"], checks["duration_within_tolerance"],
        checks["audio_stream_presence_preserved"], checks["first_frame_decodes"], checks["last_frame_decodes"],
    ]
    if audio_mode == "exact":
        required.append(exact_hash is True)
    return {
        "schema_version": 1,
        "baseline": str(baseline),
        "variant": str(variant),
        "baseline_duration": round(base_duration, 3),
        "variant_duration": round(variant_duration, 3),
        "duration_delta": round(delta, 4),
        "audio_verification_mode": audio_mode,
        "checks": checks,
        "passed": all(required),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration-tolerance", type=float, default=0.12)
    parser.add_argument("--audio-mode", choices=("exact", "presence", "repair"), default="exact")
    args = parser.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    report = verify(Path(args.baseline), Path(args.variant), args.duration_tolerance, args.audio_mode)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.resolve())
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
