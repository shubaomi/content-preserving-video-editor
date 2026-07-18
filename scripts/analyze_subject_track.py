#!/usr/bin/env python3
"""Track portrait-video faces and emit smoothed platform-safe crop boxes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def choose_primary(boxes: list[tuple[int, int, int, int]], previous: tuple[float, float] | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not boxes:
        return None
    if previous is None:
        return max(boxes, key=lambda box: box[2] * box[3])
    px, py = previous
    return min(boxes, key=lambda box: ((box[0] + box[2] / 2) / width - px) ** 2 + ((box[1] + box[3] / 2) / height - py) ** 2 - box[2] * box[3] / (width * height) * 0.15)


def smooth_point(previous: tuple[float, float] | None, current: tuple[float, float], alpha: float = 0.28) -> tuple[float, float]:
    if previous is None:
        return current
    return previous[0] * (1 - alpha) + current[0] * alpha, previous[1] * (1 - alpha) + current[1] * alpha


def crop_box(center: tuple[float, float], source_width: int, source_height: int, target_ratio: float = 9 / 16) -> dict:
    source_ratio = source_width / source_height
    if source_ratio <= target_ratio:
        crop_width, crop_height = source_width, min(source_height, source_width / target_ratio)
    else:
        crop_height, crop_width = source_height, source_height * target_ratio
    cx = center[0] * source_width
    # Keep extra room above the tracked face and do not chase vertical jitter aggressively.
    cy = max(crop_height / 2, min(source_height - crop_height / 2, center[1] * source_height + crop_height * 0.12))
    x0 = max(0.0, min(source_width - crop_width, cx - crop_width / 2))
    y0 = max(0.0, min(source_height - crop_height, cy - crop_height / 2))
    return {
        "x0": round(x0 / source_width, 6), "y0": round(y0 / source_height, 6),
        "x1": round((x0 + crop_width) / source_width, 6), "y1": round((y0 + crop_height) / source_height, 6),
    }


def analyze(video: Path, sample_interval: float, target_ratio: float) -> dict:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {video}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frames / fps if frames else 0.0
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    step = max(1, round(sample_interval * fps))
    previous = None
    series = []
    multi_person_samples = 0
    lost = []
    lost_start = None
    for frame_index in range(0, frames, step):
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        scale = min(1.0, 720 / max(width, height))
        sampled = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
        found = cascade.detectMultiScale(sampled, scaleFactor=1.1, minNeighbors=5, minSize=(36, 36))
        boxes = [(round(x / scale), round(y / scale), round(w / scale), round(h / scale)) for x, y, w, h in found]
        if len(boxes) > 1:
            multi_person_samples += 1
        primary = choose_primary(boxes, previous, width, height)
        timestamp = frame_index / fps
        if primary:
            center = ((primary[0] + primary[2] / 2) / width, (primary[1] + primary[3] / 2) / height)
            previous = smooth_point(previous, center)
            if lost_start is not None:
                lost.append({"start": round(lost_start, 3), "end": round(timestamp, 3)})
                lost_start = None
            face = {"x": round(primary[0] / width, 6), "y": round(primary[1] / height, 6), "w": round(primary[2] / width, 6), "h": round(primary[3] / height, 6)}
            status = "tracked"
        else:
            if lost_start is None:
                lost_start = timestamp
            previous = previous or (0.5, 0.38)
            face, status = None, "fallback_center"
        series.append({"time": round(timestamp, 3), "status": status, "face": face, "smoothed_center": [round(previous[0], 6), round(previous[1], 6)], "crop": crop_box(previous, width, height, target_ratio), "faces_detected": len(boxes)})
    capture.release()
    if lost_start is not None:
        lost.append({"start": round(lost_start, 3), "end": round(duration, 3)})
    tracked = sum(item["status"] == "tracked" for item in series)
    tracked_ratio = tracked / max(len(series), 1)
    multi_ratio = multi_person_samples / max(len(series), 1)
    return {
        "schema_version": 1,
        "input": {"video": str(video), "width": width, "height": height, "fps": round(fps, 3), "duration": round(duration, 3)},
        "tracking": {
            "detector": "opencv_haar_frontalface",
            "sample_interval": sample_interval,
            "tracked_ratio": round(tracked_ratio, 4),
            "status": "tracked" if tracked_ratio >= 0.25 else "insufficient_faces_center_fallback",
            "multi_person_samples": multi_person_samples,
            "multi_person_detected": multi_ratio >= 0.2,
            "lost_spans": lost,
            "series": series,
        },
        "reframe": {"target_ratio": round(target_ratio, 6), "smoothing_alpha": 0.28, "maximum_zoom": "source-bounded", "do_not_crop_secondary_speaker_without_review": multi_ratio >= 0.2},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sample-interval", type=float, default=0.4)
    parser.add_argument("--target-ratio", default="9:16")
    args = parser.parse_args()
    left, right = (float(value) for value in args.target_ratio.split(":"))
    report = analyze(Path(args.video).resolve(), args.sample_interval, left / right)
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
