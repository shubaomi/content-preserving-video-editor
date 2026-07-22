#!/usr/bin/env python3
"""Acquire lightweight, hash-bound evidence before semantic visual planning."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from director_contracts import read_json, sha256_file, write_json
from extract_design_tokens import extract_tokens


OPTIONAL_ADAPTERS = ("pyscenedetect", "mediapipe", "paddleocr")


def _rotation(video_stream: dict[str, Any]) -> int:
    values: list[Any] = [video_stream.get("tags", {}).get("rotate")]
    values.extend(item.get("rotation") for item in (video_stream.get("side_data_list") or []))
    for value in values:
        try:
            return int(round(float(value))) % 360
        except (TypeError, ValueError):
            continue
    return 0


def _display(probe: dict[str, Any]) -> dict[str, Any]:
    stream = next((row for row in probe.get("streams", []) if row.get("codec_type") == "video"), {})
    encoded_width = int(stream.get("width") or 0)
    encoded_height = int(stream.get("height") or 0)
    rotation = _rotation(stream)
    width, height = (encoded_height, encoded_width) if rotation in {90, 270} else (encoded_width, encoded_height)
    if width <= 0 or height <= 0:
        orientation = "unknown"
        ratio = None
    else:
        ratio = width / height
        orientation = "portrait" if ratio < 0.9 else "landscape" if ratio > 1.1 else "square"
    return {
        "encoded_width": encoded_width,
        "encoded_height": encoded_height,
        "rotation_degrees": rotation,
        "width": width,
        "height": height,
        "aspect_ratio": ratio,
        "orientation": orientation,
    }


def build_evidence_bundle(
    media: Path,
    transcript_path: Path,
    probe: dict[str, Any],
    frames: list[Path],
    *,
    optional_adapters: dict[str, dict[str, Any]] | None = None,
    existing_assets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transcript = read_json(transcript_path)
    words = transcript.get("words") or []
    images: list[Image.Image] = []
    try:
        for path in frames:
            with Image.open(path) as source:
                images.append(source.convert("RGB"))
        design_tokens = extract_tokens(images) if images else {
            "status": "unavailable", "reason": "no representative frames",
        }
    finally:
        for image in images:
            image.close()
    adapter_rows = {
        name: {"status": "disabled", "reason": "optional adapter not enabled"}
        for name in OPTIONAL_ADAPTERS
    }
    for name, value in (optional_adapters or {}).items():
        if name in adapter_rows:
            adapter_rows[name] = value
    video_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "video"]
    audio_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "audio"]
    subtitle_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "subtitle"]
    return {
        "schema_version": 1,
        "status": "pass" if frames else "partial",
        "source": {"path": str(media.resolve()), "sha256": sha256_file(media)},
        "transcript": {
            "path": str(transcript_path.resolve()),
            "sha256": sha256_file(transcript_path),
            "word_count": len(words),
            "term_evidence": [
                {"word_id": row.get("id", index), "text": row.get("text"),
                 "start": row.get("start"), "end": row.get("end")}
                for index, row in enumerate(words)
            ],
        },
        "duration_seconds": float(probe.get("format", {}).get("duration") or 0.0),
        "display": _display(probe),
        "streams": {
            "video": video_streams, "audio": audio_streams, "subtitles": subtitle_streams,
        },
        "representative_frames": [
            {"path": str(path.resolve()), "sha256": sha256_file(path)} for path in frames
        ],
        "scene_evidence": {"status": "lightweight_samples", "boundaries": []},
        "protected_regions": {
            "faces": [], "poses": [], "hands": [], "cursor": [], "critical_ui": [],
            "captions": [], "platform_safe_zones": [],
            "status": "candidate_only_until_optional_detectors_or_visual_review",
        },
        "ocr": {"status": "not_run", "visible_text": []},
        "design_tokens": design_tokens,
        "existing_assets": existing_assets or {
            "burned_captions": "unknown", "bgm": "unverified", "cover": "unverified",
            "existing_edit": "unverified",
        },
        "optional_adapters": adapter_rows,
        "semantic_policy": "evidence supplies candidates and protected regions; it cannot approve deletion",
    }


def probe_media(media: Path) -> dict[str, Any]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def representative_timestamps(duration: float) -> list[float]:
    if duration <= 0:
        return [0.0]
    candidates = [min(0.5, duration * 0.05), duration * 0.25, duration * 0.5, duration * 0.75,
                  max(0.0, duration - 0.5)]
    return sorted({round(min(max(0.0, value), max(0.0, duration - 0.05)), 3) for value in candidates})


def extract_frames(media: Path, timestamps: list[float], output_dir: Path) -> list[Path]:
    frame_dir = output_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for stale in frame_dir.glob("frame-*.png"):
        stale.unlink()
    frames: list[Path] = []
    for index, timestamp in enumerate(timestamps):
        output = frame_dir / f"frame-{index:02d}-{timestamp:08.3f}.png"
        subprocess.run([
            "ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(media),
            "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", str(output),
        ], check=True, capture_output=True)
        if output.is_file():
            frames.append(output)
    return frames


def acquire(
    *,
    media: Path,
    transcript_path: Path,
    output_dir: Path,
    optional_adapters: dict[str, Any] | None = None,
    existing_assets: dict[str, Any] | None = None,
) -> Path:
    probe = probe_media(media)
    duration = float(probe.get("format", {}).get("duration") or 0.0)
    frames = extract_frames(media, representative_timestamps(duration), output_dir)
    adapter_status = {
        name: {
            "status": "unavailable" if config.get("enabled") else "disabled",
            "reason": "adapter execution is not configured" if config.get("enabled") else "optional adapter not enabled",
        }
        for name, config in (optional_adapters or {}).items()
        if name in OPTIONAL_ADAPTERS and isinstance(config, dict)
    }
    bundle = build_evidence_bundle(
        media, transcript_path, probe, frames,
        optional_adapters=adapter_status,
        existing_assets=existing_assets,
    )
    output = output_dir / "evidence-bundle.json"
    write_json(output, bundle)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = acquire(
        media=Path(args.media).resolve(),
        transcript_path=Path(args.transcript).resolve(),
        output_dir=Path(args.output_dir).resolve(),
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
