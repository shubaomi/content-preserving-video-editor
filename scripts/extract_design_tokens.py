#!/usr/bin/env python3
"""Extract deterministic visual design tokens from representative video frames."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def rgb_hex(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{value:02x}" for value in color)


def luminance(color: tuple[int, int, int]) -> float:
    values = []
    for channel in color:
        value = channel / 255
        values.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def contrast_text(background: tuple[int, int, int]) -> str:
    return "#f8fafc" if luminance(background) < 0.35 else "#172033"


def palette_from_images(images: list[Image.Image], colors: int = 8) -> list[dict]:
    strips = [image.convert("RGB").resize((160, max(1, round(160 * image.height / image.width))), Image.Resampling.BILINEAR) for image in images]
    canvas = Image.new("RGB", (160, sum(image.height for image in strips)))
    y = 0
    for image in strips:
        canvas.paste(image, (0, y))
        y += image.height
    quantized = canvas.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    raw = quantized.getpalette() or []
    pixel_indexes = quantized.get_flattened_data() if hasattr(quantized, "get_flattened_data") else quantized.getdata()
    counts = Counter(pixel_indexes)
    total = sum(counts.values())
    result = []
    for index, count in counts.most_common(colors):
        color = tuple(raw[index * 3:index * 3 + 3])
        result.append({"hex": rgb_hex(color), "rgb": list(color), "share": round(count / total, 4)})
    return result


def css_value(text: str, property_name: str) -> list[str]:
    return re.findall(rf"{re.escape(property_name)}\s*:\s*([^;}}]+)", text, flags=re.IGNORECASE)


def median_px(values: list[str]) -> float | None:
    numbers = []
    for value in values:
        match = re.search(r"(-?[0-9.]+)px", value)
        if match:
            numbers.append(float(match.group(1)))
    return float(np.median(numbers)) if numbers else None


def safe_zones(width: int, height: int) -> dict:
    portrait = height > width * 1.2
    if portrait:
        return {
            "content": {"x0": 0.06, "y0": 0.08, "x1": 0.94, "y1": 0.72},
            "caption": {"x0": 0.08, "y0": 0.72, "x1": 0.92, "y1": 0.88},
            "platform_ui_avoid": {"x0": 0.78, "y0": 0.18, "x1": 1.0, "y1": 0.92},
        }
    return {
        "content": {"x0": 0.04, "y0": 0.06, "x1": 0.96, "y1": 0.78},
        "caption": {"x0": 0.12, "y0": 0.78, "x1": 0.88, "y1": 0.94},
        "platform_ui_avoid": {"x0": 0.88, "y0": 0.1, "x1": 1.0, "y1": 0.92},
    }


def extract_tokens(images: list[Image.Image], html_text: str | None = None) -> dict:
    if not images:
        raise ValueError("At least one representative image is required")
    palette = palette_from_images(images)
    width, height = images[0].size
    # Overlays usually occupy the upper content area. In portrait footage this
    # avoids treating a large dark desk/keyboard foreground as the card theme.
    surface_images = [image.crop((0, 0, image.width, round(image.height * 0.7))) for image in images]
    surface_palette = palette_from_images(surface_images, colors=5)
    dominant = tuple(surface_palette[0]["rgb"])
    arrays = [np.asarray(image.convert("RGB").resize((64, 64)), dtype=np.float32) for image in images]
    mean_rgb = np.concatenate([array.reshape(-1, 3) for array in arrays]).mean(axis=0)
    temperature_value = float((mean_rgb[0] - mean_rgb[2]) / 255.0)
    temperature = "warm" if temperature_value > 0.035 else "cool" if temperature_value < -0.035 else "neutral"
    css = html_text or ""
    radius = median_px(css_value(css, "border-radius"))
    border_width = median_px(css_value(css, "border-width"))
    shadows = css_value(css, "box-shadow")
    fonts = css_value(css, "font-family")
    surface = dominant
    accent = tuple(surface_palette[1]["rgb"]) if len(surface_palette) > 1 else (53, 214, 166)
    return {
        "schema_version": 1,
        "sampling": {"frame_count": len(images), "dimensions": {"width": width, "height": height}},
        "palette": palette,
        "color_temperature": {"value": temperature, "score": round(temperature_value, 4), "confidence": 0.72 if len(images) >= 3 else 0.45},
        "surface": {"color": rgb_hex(surface), "text_color": contrast_text(surface), "confidence": 0.74, "source": "dominant multi-frame palette"},
        "accent": {"color": rgb_hex(accent), "confidence": 0.55, "source": "secondary multi-frame palette"},
        "shape": {
            "border_radius_px": radius if radius is not None else 18,
            "border_radius_confidence": 0.9 if radius is not None else 0.2,
            "border_radius_source": "hyperframes_css" if radius is not None else "explicit_fallback",
            "line_width_px": border_width if border_width is not None else 1,
            "line_width_confidence": 0.9 if border_width is not None else 0.2,
        },
        "shadow": {
            "css": shadows[0].strip() if shadows else "0 12px 30px rgba(15, 23, 42, 0.16)",
            "confidence": 0.9 if shadows else 0.2,
            "source": "hyperframes_css" if shadows else "explicit_fallback",
        },
        "typography": {
            "font_family": fonts[0].strip() if fonts else "system-ui, sans-serif",
            "confidence": 0.9 if fonts else 0.25,
            "source": "hyperframes_css" if fonts else "explicit_fallback_no_ocr",
        },
        "safe_zones": safe_zones(width, height),
        "fallback_policy": "fields below 0.5 confidence must use the declared fallback and must not be described as inferred brand identity",
    }


def extract_frame(media: Path, timestamp: float, output: Path) -> None:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.3f}", "-i", str(media),
        "-frames:v", "1", "-vf", "scale='min(960,iw)':-2", str(output),
    ], check=True)


def contact_sheet(frame: Image.Image, tokens: dict, output: Path) -> None:
    frame = frame.convert("RGB").resize((640, round(640 * frame.height / frame.width)), Image.Resampling.LANCZOS)
    panel_h = frame.height
    sheet = Image.new("RGB", (640 * 3, panel_h + 42), "#e5e7eb")
    draw = ImageDraw.Draw(sheet)
    labels = ("SOURCE", "GENERIC DEFAULT", "EXTRACTED TOKENS")
    for index, label in enumerate(labels):
        draw.text((index * 640 + 14, 12), label, fill="#111827")
        sheet.paste(frame, (index * 640, 42))
    generic = {"surface": "#ffffff", "text": "#111827", "accent": "#8b5cf6", "radius": 18}
    extracted = {
        "surface": tokens["surface"]["color"], "text": tokens["surface"]["text_color"],
        "accent": tokens["accent"]["color"], "radius": int(tokens["shape"]["border_radius_px"]),
    }
    for index, style in ((1, generic), (2, extracted)):
        x = index * 640 + 55
        y = 42 + round(panel_h * 0.16)
        draw.rounded_rectangle((x, y, x + 310, y + 145), radius=style["radius"], fill=style["surface"], outline=style["accent"], width=3)
        draw.rectangle((x + 24, y + 28, x + 140, y + 35), fill=style["accent"])
        draw.text((x + 24, y + 55), "DESIGN TOKEN CARD", fill=style["text"])
        draw.text((x + 24, y + 91), "visual match preview", fill=style["text"])
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True)
    parser.add_argument("--timestamps", default="5,30,60,120,180")
    parser.add_argument("--hyperframes")
    parser.add_argument("--out", required=True)
    parser.add_argument("--evidence-dir")
    args = parser.parse_args()
    media = Path(args.media).resolve()
    output = Path(args.out).resolve()
    evidence = Path(args.evidence_dir).resolve() if args.evidence_dir else output.parent / "design-token-evidence"
    timestamps = [float(value) for value in args.timestamps.split(",") if value.strip()]
    html_text = Path(args.hyperframes).read_text(encoding="utf-8") if args.hyperframes else None
    evidence.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    evidence_files = []
    for index, timestamp in enumerate(timestamps, 1):
        path = evidence / f"token-frame-{index:02d}-{timestamp:.2f}s.jpg"
        extract_frame(media, timestamp, path)
        frames.append(Image.open(path).convert("RGB"))
        evidence_files.append({"timestamp": timestamp, "file": path.name})
    tokens = extract_tokens(frames, html_text)
    tokens["sampling"]["evidence"] = evidence_files
    sheet = evidence / "design-token-comparison.jpg"
    contact_sheet(frames[0], tokens, sheet)
    tokens["comparison_contact_sheet"] = str(sheet)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(tokens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
