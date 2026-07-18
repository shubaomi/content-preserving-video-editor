#!/usr/bin/env python3
"""Composite a locally rendered dynamic overlay onto an immutable baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def has_stream(path: Path, selector: str) -> bool:
    payload = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", selector,
        "-show_entries", "stream=index", "-of", "json", str(path),
    ], text=True, encoding="utf-8"))
    return bool(payload.get("streams"))


def parse_rgb(color: str) -> tuple[int, int, int]:
    value = color.removeprefix("0x").removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"Matte color must be a six-digit RGB value, got {color!r}")
    return tuple(int(value[index:index + 2], 16) for index in range(0, 6, 2))


def key_color_coverage(rgb: bytes, expected: tuple[int, int, int], tolerance: int = 20) -> float:
    """Return the fraction of RGB pixels close enough to the requested matte."""
    if len(rgb) % 3:
        raise ValueError("RGB sample length must be divisible by three")
    if not rgb:
        return 0.0
    matches = sum(
        max(abs(red - expected[0]), abs(green - expected[1]), abs(blue - expected[2])) <= tolerance
        for red, green, blue in zip(rgb[0::3], rgb[1::3], rgb[2::3])
    )
    return matches / (len(rgb) // 3)


def validate_key_matte(path: Path, color: str) -> float:
    """Reject an alpha/black fallback before it can cover the baseline video.

    HyperFrames may encode an overlay-only composition as an opaque black video
    even when CSS names a key color.  A real matte must be rendered over an
    opaque key-color baseline video, so a quiet early frame should be almost
    entirely key color.
    """
    rgb = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(path), "-frames:v", "1",
        "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    coverage = key_color_coverage(rgb, parse_rgb(color))
    if coverage < 0.70:
        raise ValueError(
            f"{path.name} is not a usable {color} key matte (early-frame coverage {coverage:.1%}). "
            "Render graphics over an opaque key-color baseline video; do not use an alpha/black overlay-only export."
        )
    return coverage


def command(baseline: Path, overlay: Path, output: Path, matte_color: str | None) -> list[str]:
    if matte_color:
        video = f"[1:v]chromakey={matte_color}:0.11:0.04[graphics];[0:v][graphics]overlay=0:0:format=auto[v]"
    else:
        video = "[0:v][1:v]overlay=0:0:format=auto[v]"
    audio = "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.98[a]"
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(baseline), "-i", str(overlay),
        "-filter_complex", f"{video};{audio}", "-map", "[v]", "-map", "[a]", "-map_metadata", "0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--matte-color", help="Rendered key color such as 0x00ff00; omit only for alpha-capable media")
    args = parser.parse_args()
    baseline, overlay, output = args.baseline.resolve(), args.overlay.resolve(), args.out.resolve()
    for path in (baseline, overlay):
        if not path.is_file():
            raise FileNotFoundError(path)
    if output in (baseline, overlay):
        raise ValueError("Output must not overwrite an input")
    if not has_stream(baseline, "a"):
        raise ValueError("Baseline must supply the original audio track")
    if not has_stream(overlay, "a"):
        raise ValueError("Overlay must supply its separately rendered SFX audio track")
    if args.matte_color:
        coverage = validate_key_matte(overlay, args.matte_color)
        print(f"Validated key-matte coverage: {coverage:.1%}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial" + output.suffix)
    try:
        subprocess.run(command(baseline, overlay, temporary, args.matte_color), check=True)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
