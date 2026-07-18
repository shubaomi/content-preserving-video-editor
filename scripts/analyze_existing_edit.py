#!/usr/bin/env python3
"""Analyze an already edited video before adding nondestructive polish.

The detector is deliberately conservative: an embedded audio mix is never
called "music" from energy alone. A user declaration wins, while an unknown
mix blocks a second BGM bed until a human or a stronger detector proves that
none exists.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


SCHEMA_VERSION = 1


def run_json(command: list[str]) -> dict:
    return json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))


def probe_media(path: Path) -> dict:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is not available on PATH")
    data = run_json([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels:stream_tags=language,title",
        "-of", "json", str(path),
    ])
    video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), None)
    if not video:
        raise ValueError(f"No video stream found: {path}")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    data["display"] = {
        "width": width,
        "height": height,
        "orientation": "portrait" if height > width * 1.2 else "landscape" if width > height * 1.2 else "square",
    }
    return data


def extract_samples(media: Path, directory: Path, duration: float, count: int) -> list[tuple[float, Path]]:
    directory.mkdir(parents=True, exist_ok=True)
    count = max(6, min(count, 120))
    fps = count / max(duration, 1.0)
    pattern = directory / "sample-%04d.jpg"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(media),
        "-vf", f"fps={fps:.10f},scale=480:-2:flags=area", "-frames:v", str(count),
        "-q:v", "3", str(pattern),
    ]
    subprocess.run(command, check=True)
    files = sorted(directory.glob("sample-*.jpg"))
    step = duration / max(len(files), 1)
    return [((index + 0.5) * step, path) for index, path in enumerate(files)]


def caption_score(image: Image.Image) -> float:
    """Return a 0..1 score for high-contrast caption-like pixels in lower frame."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    height = rgb.shape[0]
    band = rgb[int(height * 0.62):int(height * 0.94)]
    if band.size == 0:
        return 0.0
    max_channel = band.max(axis=2)
    min_channel = band.min(axis=2)
    bright_neutral = (min_channel > 190) & ((max_channel - min_channel) < 50)
    gray = band.mean(axis=2)
    edge_x = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1])) > 38
    edge_y = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :])) > 38
    glyph = bright_neutral & (edge_x | edge_y)
    row_density = glyph.mean(axis=1)
    active_rows = float(np.mean(row_density > 0.004))
    pixel_density = float(glyph.mean())
    # Captions occupy a few dense rows, not the whole lower frame.
    return float(np.clip(active_rows * 2.2 + pixel_density * 18.0, 0.0, 1.0))


def perceptual_signature(image: Image.Image) -> np.ndarray:
    small = image.convert("RGB").resize((32, 18), Image.Resampling.BILINEAR)
    array = np.asarray(small, dtype=np.float32) / 255.0
    return array


def frame_delta(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.mean(np.abs(left - right)))


def analyze_visuals(samples: list[tuple[float, Path]], evidence_dir: Path) -> dict:
    caption_rows: list[dict] = []
    signatures: list[np.ndarray] = []
    for timestamp, path in samples:
        with Image.open(path) as image:
            score = caption_score(image)
            signatures.append(perceptual_signature(image))
        caption_rows.append({"timestamp": round(timestamp, 3), "score": round(score, 4), "sample": path.name})

    positive = [row for row in caption_rows if row["score"] >= 0.22]
    positive_ratio = len(positive) / max(len(caption_rows), 1)
    hard_caption_confidence = float(np.clip(positive_ratio * 1.25, 0.0, 1.0))
    top_caption = sorted(caption_rows, key=lambda item: item["score"], reverse=True)[:3]
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for rank, row in enumerate(top_caption, 1):
        source = next(path for ts, path in samples if abs(ts - row["timestamp"]) < 0.01)
        target = evidence_dir / f"caption-evidence-{rank:02d}-{row['timestamp']:.2f}s.jpg"
        shutil.copy2(source, target)
        row["evidence"] = target.name

    deltas = [frame_delta(signatures[index - 1], signatures[index]) for index in range(1, len(signatures))]
    median = float(np.median(deltas)) if deltas else 0.0
    monotony_threshold = max(0.018, median * 0.72)
    chapter_threshold = max(0.055, median * 1.8)
    monotony = []
    chapters = []
    for index, delta in enumerate(deltas, 1):
        timestamp = samples[index][0]
        if delta <= monotony_threshold:
            monotony.append({"timestamp": round(timestamp, 3), "delta": round(delta, 5)})
        if delta >= chapter_threshold:
            chapters.append({"timestamp": round(timestamp, 3), "delta": round(delta, 5)})
    return {
        "burned_caption": {
            "detected": hard_caption_confidence >= 0.52,
            "confidence": round(hard_caption_confidence, 4),
            "positive_sample_ratio": round(positive_ratio, 4),
            "decision": "do_not_add_caption_layer" if hard_caption_confidence >= 0.52 else "review_before_adding_captions",
            "evidence": top_caption,
        },
        "frame_change": {
            "median_delta": round(median, 5),
            "monotony_threshold": round(monotony_threshold, 5),
            "chapter_threshold": round(chapter_threshold, 5),
            "monotony_candidates": monotony,
            "chapter_candidates": sorted(chapters, key=lambda item: item["delta"], reverse=True)[:12],
        },
    }


def subtitle_streams(probe: dict) -> list[dict]:
    return [
        {
            "index": stream.get("index"),
            "codec": stream.get("codec_name"),
            "language": (stream.get("tags") or {}).get("language"),
            "title": (stream.get("tags") or {}).get("title"),
        }
        for stream in probe.get("streams", []) if stream.get("codec_type") == "subtitle"
    ]


def detect_silence(media: Path, duration: float) -> dict:
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(media), "-vn",
        "-af", "silencedetect=n=-42dB:d=0.8", "-f", "null", "-",
    ]
    result = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True)
    spans: list[tuple[float, float]] = []
    starts = [float(value) for value in re.findall(r"silence_start: ([0-9.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: ([0-9.]+)", result.stderr)]
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration
        spans.append((start, min(end, duration)))
    silent = sum(max(0.0, end - start) for start, end in spans)
    return {
        "threshold_db": -42,
        "silent_seconds": round(silent, 3),
        "longest_silence_seconds": round(max((end - start for start, end in spans), default=0.0), 3),
        "silence_spans": [{"start": round(start, 3), "end": round(end, 3)} for start, end in spans],
        "active_ratio": round(max(0.0, 1.0 - silent / max(duration, 0.001)), 4),
    }


def transient_candidates(samples: np.ndarray, sample_rate: int = 8000) -> list[dict]:
    """Find short onset candidates; they may be SFX or speech and stay labeled as such."""
    window = max(1, int(sample_rate * 0.05))
    usable = samples[: len(samples) // window * window]
    if usable.size == 0:
        return []
    rms = np.sqrt(np.mean(usable.reshape(-1, window) ** 2, axis=1) + 1e-12)
    candidates = []
    radius = 20
    for index in range(1, len(rms)):
        left = rms[max(0, index - radius):index]
        local = float(np.median(left)) if left.size else 0.0
        ratio = float(rms[index] / max(local, 0.004))
        if rms[index] >= 0.08 and ratio >= 3.2 and rms[index] > rms[index - 1] * 1.8:
            timestamp = index * window / sample_rate
            if not candidates or timestamp - candidates[-1]["timestamp"] >= 0.35:
                candidates.append({"timestamp": round(timestamp, 3), "onset_ratio": round(ratio, 2)})
    return candidates[:80]


def analyze_transients(media: Path) -> dict:
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(media), "-vn",
        "-ac", "1", "-ar", "8000", "-f", "f32le", "-",
    ], capture_output=True, check=True)
    samples = np.frombuffer(result.stdout, dtype="<f4")
    candidates = transient_candidates(samples)
    return {
        "state": "candidate_events_present" if candidates else "no_strong_candidates",
        "count": len(candidates),
        "candidates": candidates,
        "caveat": "onset analysis cannot reliably distinguish SFX from speech consonants without source separation",
    }


def audio_decision(probe: dict, media: Path, duration: float, declared_bgm: str) -> dict:
    audio_streams = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"]
    if not audio_streams:
        return {"has_audio": False, "existing_bgm": "no", "add_bgm": False, "reason": "no source audio stream"}
    silence = detect_silence(media, duration)
    transients = analyze_transients(media)
    requires_bgm_presence_review = False
    if declared_bgm == "yes":
        longest_silence = float(silence.get("longest_silence_seconds", 0.0))
        silent_seconds = float(silence.get("silent_seconds", 0.0))
        if longest_silence >= 2.0 or silent_seconds >= 5.0:
            state, add = "declared_unverified", False
            reason = "BGM was declared, but measured near-silent gaps conflict with a continuous audible music bed"
            requires_bgm_presence_review = True
        else:
            state, add, reason = "yes", False, "user declaration is consistent with measured source activity"
    elif declared_bgm == "no":
        state, add, reason = "no", True, "user declaration: no existing BGM"
    else:
        state, add = "unknown", False
        reason = "energy analysis cannot reliably separate speech from music; block a second bed conservatively"
    return {
        "has_audio": True,
        "streams": [{"codec": s.get("codec_name"), "channels": s.get("channels"), "sample_rate": s.get("sample_rate")} for s in audio_streams],
        "activity": silence,
        "existing_sfx_analysis": transients,
        "existing_bgm": state,
        "add_bgm": add,
        "reason": reason,
        "requires_bgm_presence_review": requires_bgm_presence_review,
        "source_separation_used": False,
    }


def enhancement_budget(duration: float, visual: dict) -> dict:
    monotony = visual["frame_change"]["monotony_candidates"]
    candidates = [float(item["timestamp"]) for item in monotony if 3 <= float(item["timestamp"]) <= duration - 3]
    return {
        "planner": "semantic_confidence_first",
        "candidate_timestamps": [round(value, 3) for value in candidates[:80]],
        "recommended_events_per_minute": {"screen_tutorial": [4, 10], "polish_existing": [3, 7]},
        "event_rate_policy": "advisory_ceiling",
        "rule": "Use transcript semantics, verified terminology, visual inventory, and resolved geometry; prefer quiet to a fixed count or low-confidence filler.",
    }


def build_report(media: Path, probe: dict, visual: dict, audio: dict) -> dict:
    duration = float(probe.get("format", {}).get("duration") or 0)
    subtitles = subtitle_streams(probe)
    burned = visual["burned_caption"]
    add_captions = not subtitles and not burned["detected"]
    budget = enhancement_budget(duration, visual)
    return {
        "schema_version": SCHEMA_VERSION,
        "input": {"media": str(media), "duration": round(duration, 3), **probe["display"]},
        "captions": {
            "subtitle_streams": subtitles,
            "burned_in": burned,
            "add_caption_layer": add_captions,
            "decision_reason": "existing subtitle stream or burned captions detected" if not add_captions else "no existing caption signal detected; review evidence before generation",
        },
        "audio": audio,
        "visual_analysis": visual["frame_change"],
        "enhancement_budget": budget,
        "comparison_plan": {
            "baseline": str(media),
            "baseline_is_immutable": True,
            "polish_variant_required": True,
            "compare": ["duration", "audio_stream_presence", "first_frame", "last_frame", "enhancement_beat_snapshots"],
        },
        "incremental_render": {
            "preferred_path": "render_alpha_overlay_then_mux_with_baseline",
            "preserve_source_timeline": True,
            "preserve_source_audio": True,
            "audio_action": "copy" if not audio.get("add_bgm") else "mix_with_ducking",
            "forbid_second_caption_layer": not add_captions,
            "forbid_second_bgm_bed": not audio.get("add_bgm", False),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--evidence-dir")
    parser.add_argument("--declared-bgm", choices=("auto", "yes", "no"), default="auto")
    parser.add_argument("--max-samples", type=int, default=48)
    args = parser.parse_args()

    media = Path(args.media).resolve()
    output = Path(args.out).resolve()
    evidence = Path(args.evidence_dir).resolve() if args.evidence_dir else output.parent / "existing-edit-evidence"
    if not media.is_file():
        raise FileNotFoundError(media)
    probe = probe_media(media)
    duration = float(probe.get("format", {}).get("duration") or 0)
    with tempfile.TemporaryDirectory(prefix="existing-edit-") as temp:
        samples = extract_samples(media, Path(temp), duration, args.max_samples)
        visual = analyze_visuals(samples, evidence)
    audio = audio_decision(probe, media, duration, args.declared_bgm)
    report = build_report(media, probe, visual, audio)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
