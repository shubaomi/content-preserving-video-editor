#!/usr/bin/env python3
"""Acquire lightweight, hash-bound evidence before semantic visual planning."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from director_contracts import read_json, sha256_file, write_json
from extract_design_tokens import extract_tokens


OPTIONAL_ADAPTERS = ("pyscenedetect", "mediapipe", "paddleocr")
REPRESENTATIVE_FRAME_SAMPLING_POLICY = "bounded_uniform_full_duration_v1"
REPRESENTATIVE_FRAME_TARGET_INTERVAL_SECONDS = 15.0
MIN_REPRESENTATIVE_FRAME_COUNT = 3
MAX_REPRESENTATIVE_FRAME_COUNT = 32


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


def _managed_frame_timestamp(path: Path) -> float | None:
    parts = path.stem.split("-", 2)
    if len(parts) != 3 or parts[0] != "frame" or not parts[1].isdigit():
        return None
    try:
        return round(float(parts[2]), 3)
    except ValueError:
        return None


def _sampling_bounds(duration: float) -> tuple[float, float]:
    duration = max(0.0, float(duration))
    if duration <= 0:
        return 0.0, 0.0
    edge_margin = min(0.5, duration * 0.05)
    last_decodable_time = max(0.0, duration - 0.05)
    start = min(edge_margin, last_decodable_time)
    end = max(start, min(duration - edge_margin, last_decodable_time))
    return start, end


def _sampling_policy(
    duration: float,
    requested_timestamps: list[float],
    extracted_timestamps: list[float],
) -> dict[str, Any]:
    requested = [round(float(value), 3) for value in requested_timestamps]
    extracted = [round(float(value), 3) for value in extracted_timestamps]
    gaps = [
        round(right - left, 3)
        for left, right in zip(extracted, extracted[1:])
    ]
    start, end = _sampling_bounds(duration)
    uncapped_count = (
        1 if end <= start
        else max(
            MIN_REPRESENTATIVE_FRAME_COUNT,
            math.ceil((end - start) / REPRESENTATIVE_FRAME_TARGET_INTERVAL_SECONDS) + 1,
        )
    )
    timestamps_match = requested == extracted
    full_duration = timestamps_match and len(extracted) >= 2
    if full_duration:
        coverage_start: float | None = 0.0
        coverage_end: float | None = round(max(0.0, duration), 3)
    elif extracted:
        coverage_start = extracted[0]
        coverage_end = extracted[-1]
    else:
        coverage_start = None
        coverage_end = None
    return {
        "policy": REPRESENTATIVE_FRAME_SAMPLING_POLICY,
        "strategy": "uniform_across_full_duration",
        "target_interval_seconds": REPRESENTATIVE_FRAME_TARGET_INTERVAL_SECONDS,
        "minimum_frame_count": MIN_REPRESENTATIVE_FRAME_COUNT,
        "maximum_frame_count": MAX_REPRESENTATIVE_FRAME_COUNT,
        "requested_frame_count": len(requested),
        "extracted_frame_count": len(extracted),
        "requested_timestamps": requested,
        "extracted_timestamps": extracted,
        "timestamps_match_request": timestamps_match,
        "capped": uncapped_count > MAX_REPRESENTATIVE_FRAME_COUNT,
        "coverage": {
            "status": "full_duration" if full_duration else "partial",
            "start_seconds": coverage_start,
            "end_seconds": coverage_end,
            "maximum_sample_gap_seconds": max(gaps, default=0.0),
        },
    }


def _frame_coverages(
    timestamps: list[float], duration: float, *, full_duration: bool,
) -> list[dict[str, float]]:
    if not timestamps:
        return []
    if len(timestamps) == 1:
        timestamp = round(timestamps[0], 3)
        return [{"start_seconds": timestamp, "end_seconds": timestamp}]
    boundaries = [0.0 if full_duration else round(timestamps[0], 3)]
    boundaries.extend(
        round((left + right) / 2.0, 3)
        for left, right in zip(timestamps, timestamps[1:])
    )
    boundaries.append(
        round(max(0.0, duration), 3) if full_duration else round(timestamps[-1], 3)
    )
    return [
        {"start_seconds": boundaries[index], "end_seconds": boundaries[index + 1]}
        for index in range(len(timestamps))
    ]


def build_evidence_bundle(
    media: Path,
    transcript_path: Path,
    probe: dict[str, Any],
    frames: list[Path],
    *,
    optional_adapters: dict[str, dict[str, Any]] | None = None,
    existing_assets: dict[str, Any] | None = None,
    frame_timestamps: list[float] | None = None,
    sampling_policy: dict[str, Any] | None = None,
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
    duration = float(probe.get("format", {}).get("duration") or 0.0)
    if frame_timestamps is not None:
        if len(frame_timestamps) != len(frames):
            raise ValueError("frame_timestamps must match the extracted frame count")
        resolved_timestamps = [round(float(value), 3) for value in frame_timestamps]
        if any(not math.isfinite(value) or value < 0 for value in resolved_timestamps):
            raise ValueError("frame_timestamps must contain finite non-negative values")
        if resolved_timestamps != sorted(resolved_timestamps):
            raise ValueError("frame_timestamps must be sorted")
    else:
        resolved_timestamps = [_managed_frame_timestamp(path) for path in frames]
    timestamps_known = all(value is not None for value in resolved_timestamps)
    numeric_timestamps = [float(value) for value in resolved_timestamps if value is not None]
    if sampling_policy is not None:
        frame_sampling = dict(sampling_policy)
        requested = frame_sampling.get("requested_timestamps")
        requested_timestamps_known = isinstance(requested, list)
        declared_requested_count = frame_sampling.get("requested_frame_count")
        if not requested_timestamps_known:
            requested = []
        measured_sampling = _sampling_policy(duration, requested, numeric_timestamps)
        if not requested_timestamps_known:
            try:
                measured_sampling["requested_frame_count"] = int(declared_requested_count)
            except (TypeError, ValueError):
                measured_sampling["requested_frame_count"] = 0
        frame_sampling.update({
            "requested_frame_count": measured_sampling["requested_frame_count"],
            "extracted_frame_count": measured_sampling["extracted_frame_count"],
            "requested_timestamps": measured_sampling["requested_timestamps"],
            "extracted_timestamps": measured_sampling["extracted_timestamps"],
            "timestamps_match_request": measured_sampling["timestamps_match_request"],
            "coverage": measured_sampling["coverage"],
        })
    elif timestamps_known:
        frame_sampling = _sampling_policy(
            duration, representative_timestamps(duration), numeric_timestamps,
        )
        frame_sampling["policy"] = "managed_filename_timestamps_v1"
    else:
        frame_sampling = {
            "policy": "legacy_unspecified",
            "strategy": "caller_supplied_frames_without_timestamps",
            "requested_frame_count": len(frames),
            "extracted_frame_count": len(frames),
            "coverage": {
                "status": "unknown",
                "reason": "legacy caller did not supply frame timestamps",
            },
        }
    coverages: list[dict[str, Any]] = (
        _frame_coverages(
            numeric_timestamps,
            duration,
            full_duration=(
                frame_sampling.get("coverage", {}).get("status") == "full_duration"
            ),
        ) if timestamps_known else [
            {"status": "unknown", "reason": "frame timestamp is unavailable"} for _ in frames
        ]
    )
    representative_frames = [
        {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "timestamp_seconds": resolved_timestamps[index],
            "coverage": coverages[index],
            "sampling_policy": frame_sampling["policy"],
        }
        for index, path in enumerate(frames)
    ]
    return {
        "schema_version": 1,
        "status": (
            "pass"
            if frames and (
                frame_sampling["policy"] == "legacy_unspecified"
                or frame_sampling.get("coverage", {}).get("status") == "full_duration"
            )
            else "partial"
        ),
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
        "duration_seconds": duration,
        "display": _display(probe),
        "streams": {
            "video": video_streams, "audio": audio_streams, "subtitles": subtitle_streams,
        },
        "representative_frame_sampling": frame_sampling,
        "representative_frames": representative_frames,
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
    start, end = _sampling_bounds(duration)
    if end <= start:
        return [round(start, 3)]
    frame_count = min(
        MAX_REPRESENTATIVE_FRAME_COUNT,
        max(
            MIN_REPRESENTATIVE_FRAME_COUNT,
            math.ceil((end - start) / REPRESENTATIVE_FRAME_TARGET_INTERVAL_SECONDS) + 1,
        ),
    )
    step = (end - start) / (frame_count - 1)
    return sorted({round(start + index * step, 3) for index in range(frame_count)})


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
    requested_timestamps = representative_timestamps(duration)
    frames = extract_frames(media, requested_timestamps, output_dir)
    extracted_timestamps = [_managed_frame_timestamp(path) for path in frames]
    if any(value is None for value in extracted_timestamps):
        raise RuntimeError("managed evidence frame filename is missing its timestamp")
    actual_timestamps = [float(value) for value in extracted_timestamps if value is not None]
    if len(frames) != len(requested_timestamps):
        raise RuntimeError(
            "representative frame count mismatch: "
            f"requested {len(requested_timestamps)}, extracted {len(frames)}"
        )
    if [round(value, 3) for value in actual_timestamps] != [
        round(value, 3) for value in requested_timestamps
    ]:
        raise RuntimeError("extracted frame timestamps do not match requested timestamps")
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
        frame_timestamps=actual_timestamps,
        sampling_policy=_sampling_policy(
            duration, requested_timestamps, actual_timestamps,
        ),
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
