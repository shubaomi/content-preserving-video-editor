#!/usr/bin/env python3
"""Generate and verify public 30-second landscape/portrait media evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = (Path("scripts/representative_short_media.py"),)
SPECS = {
    "landscape": {"size": "320x180", "color": "0x102030", "tone": 440},
    "portrait": {"size": "180x320", "color": "0x415a77", "tone": 220},
}


def _probe(path: Path) -> dict[str, Any]:
    run = subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
    ], check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(run.stdout)


def generate(output_dir: Path, manifest_path: Path, *, duration: float = 30.0) -> dict[str, Any]:
    if not 30.0 <= duration <= 90.0:
        raise ValueError("representative duration must be 30-90 seconds")
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = []
    for orientation, spec in SPECS.items():
        media = output_dir / f"{orientation}-representative.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={spec['color']}:s={spec['size']}:r=24:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency={spec['tone']}:sample_rate=48000:duration={duration}",
            "-vf", "drawbox=x=18:y=36:w=72:h=32:color=0x2dd4bf:t=fill,drawbox=x=100:y=82:w=160:h=56:color=0xe8eef5:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", str(media),
        ], check=True)
        probe = _probe(media)
        video = next(row for row in probe["streams"] if row.get("codec_type") == "video")
        audio = next(row for row in probe["streams"] if row.get("codec_type") == "audio")
        frames = []
        for label, timestamp in (("entrance", 3.0), ("midpoint", duration / 2), ("exit", duration - 3.0)):
            frame = output_dir / f"{orientation}-{label}.png"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(timestamp),
                "-i", str(media), "-frames:v", "1", str(frame),
            ], check=True)
            frames.append({"phase": label, "timestamp": timestamp,
                           "path": frame.name, "sha256": sha256_file(frame)})
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(media),
            "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        ], check=True)
        scenarios.append({
            "orientation": orientation,
            "rights_basis": "generated deterministic synthetic fixture",
            "media": media.name,
            "sha256": sha256_file(media),
            "duration_seconds": float(probe["format"]["duration"]),
            "width": int(video["width"]), "height": int(video["height"]),
            "video_codec": video["codec_name"], "audio_codec": audio["codec_name"],
            "audio_sample_rate": int(audio["sample_rate"]),
            "full_decode": "pass", "representative_frames": frames,
        })
    report = {
        "schema_version": 1,
        "status": "pass",
        "evidence_boundary": "synthetic technical media; not human aesthetic or provider validation",
        "scenarios": scenarios,
        "implementation_sha256": {
            path.as_posix(): sha256_file(ROOT / path) for path in IMPLEMENTATION
        },
    }
    write_json(manifest_path, report)
    return report


def validate(manifest_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        report = read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"representative media manifest is unreadable: {error}"]
    if report.get("schema_version") != 1 or report.get("status") != "pass":
        errors.append("representative media manifest status/schema is invalid")
    expected_impl = {path.as_posix(): sha256_file(ROOT / path) for path in IMPLEMENTATION}
    if report.get("implementation_sha256") != expected_impl:
        errors.append("representative media implementation binding is stale")
    rows = {row.get("orientation"): row for row in report.get("scenarios") or []}
    if set(rows) != set(SPECS):
        errors.append("representative media must contain landscape and portrait")
        return errors
    for orientation, row in rows.items():
        media = manifest_path.parent / str(row.get("media") or "")
        if not media.is_file() or row.get("sha256") != sha256_file(media):
            errors.append(f"{orientation} media hash is missing or stale")
            continue
        try:
            probe = _probe(media)
            duration = float(probe["format"]["duration"])
            video = next(item for item in probe["streams"] if item.get("codec_type") == "video")
            audio = next(item for item in probe["streams"] if item.get("codec_type") == "audio")
            if not 30 <= duration <= 90:
                errors.append(f"{orientation} duration is outside 30-90 seconds")
            if orientation == "landscape" and int(video["width"]) <= int(video["height"]):
                errors.append("landscape orientation is invalid")
            if orientation == "portrait" and int(video["height"]) <= int(video["width"]):
                errors.append("portrait orientation is invalid")
            if int(audio.get("sample_rate", 0)) <= 0:
                errors.append(f"{orientation} audio stream is invalid")
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(media),
                "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
            ], check=True, capture_output=True)
        except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
            errors.append(f"{orientation} probe/decode failed: {error}")
        frames = row.get("representative_frames") or []
        if [item.get("phase") for item in frames] != ["entrance", "midpoint", "exit"]:
            errors.append(f"{orientation} representative phases are incomplete")
        for frame in frames:
            path = manifest_path.parent / str(frame.get("path") or "")
            if not path.is_file() or frame.get("sha256") != sha256_file(path):
                errors.append(f"{orientation} representative frame is missing or stale")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    manifest = Path(args.manifest).resolve()
    if not args.validate_only:
        generate(Path(args.out_dir).resolve(), manifest, duration=args.duration)
    errors = validate(manifest)
    print(json.dumps({"status": "pass" if not errors else "failed", "errors": errors}))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
