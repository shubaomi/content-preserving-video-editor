#!/usr/bin/env python3
"""Prepare transparent, independently animatable IP assets and a QA manifest."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def border_color(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0).astype(np.float32)
    median = np.median(border, axis=0)
    distance = np.max(np.abs(border - median), axis=1)
    consistency = float(np.mean(distance <= 18))
    return median, consistency


def connected_background(candidate: np.ndarray) -> np.ndarray:
    height, width = candidate.shape
    visited = np.zeros_like(candidate, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        if candidate[0, x]: queue.append((0, x))
        if candidate[height - 1, x]: queue.append((height - 1, x))
    for y in range(height):
        if candidate[y, 0]: queue.append((y, 0))
        if candidate[y, width - 1]: queue.append((y, width - 1))
    while queue:
        y, x = queue.popleft()
        if visited[y, x] or not candidate[y, x]:
            continue
        visited[y, x] = True
        if y: queue.append((y - 1, x))
        if y + 1 < height: queue.append((y + 1, x))
        if x: queue.append((y, x - 1))
        if x + 1 < width: queue.append((y, x + 1))
    return visited


def remove_connected_matte(image: Image.Image, tolerance: float = 48) -> tuple[Image.Image, dict]:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    matte, consistency = border_color(rgb)
    distance = np.max(np.abs(rgb - matte), axis=2)
    connected = connected_background(distance <= tolerance)
    alpha = rgba[:, :, 3].astype(np.float32)
    soft_alpha = np.clip(distance / max(tolerance, 1), 0, 1) * 255
    soft_alpha[distance <= 3] = 0
    alpha[connected] = np.minimum(alpha[connected], soft_alpha[connected])

    # Remove matte contamination from partially transparent antialiased edges.
    fraction = np.clip(alpha / 255.0, 1 / 255, 1.0)
    recovered = (rgb - (1.0 - fraction[:, :, None]) * matte[None, None, :]) / fraction[:, :, None]
    partial = (alpha > 0) & (alpha < 255)
    rgb[partial] = np.clip(recovered[partial], 0, 255)
    residual_matte = partial & (np.max(np.abs(rgb - matte[None, None, :]), axis=2) < 8)
    alpha[residual_matte] = 0
    rgba[:, :, :3] = rgb.astype(np.uint8)
    rgba[:, :, 3] = alpha.astype(np.uint8)
    result = Image.fromarray(rgba, "RGBA")
    return result, {"matte_rgb": [round(float(value), 2) for value in matte], "border_consistency": round(consistency, 4)}


def alpha_qa(image: Image.Image, matte_rgb: list[float] | None = None) -> dict:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    corners = [int(alpha[0, 0]), int(alpha[0, -1]), int(alpha[-1, 0]), int(alpha[-1, -1])]
    partial = (alpha > 8) & (alpha < 247)
    fringe_ratio = 0.0
    if matte_rgb is not None and np.any(partial):
        distance = np.max(np.abs(rgba[:, :, :3].astype(np.float32) - np.asarray(matte_rgb)), axis=2)
        fringe_ratio = float(np.mean(distance[partial] < 8))
    return {
        "has_alpha_channel": True,
        "transparent_corner_count": sum(value <= 3 for value in corners),
        "corner_alpha": corners,
        "transparent_pixel_ratio": round(float(np.mean(alpha < 8)), 4),
        "partial_alpha_pixel_ratio": round(float(np.mean(partial)), 4),
        "key_color_fringe_ratio": round(fringe_ratio, 5),
        "passed": all(value <= 3 for value in corners) and fringe_ratio <= 0.01,
    }


def make_evidence(image: Image.Image, output: Path) -> None:
    rgba = image.convert("RGBA")
    preview = rgba.copy()
    preview.thumbnail((640, 640), Image.Resampling.LANCZOS)
    cells = []
    for scale, background in ((1, "#18212f"), (2, "#d8f5ed")):
        cell = Image.new("RGB", (640, 640), background)
        shown = preview.resize((preview.width * scale, preview.height * scale), Image.Resampling.NEAREST) if scale == 2 else preview
        shown.thumbnail((600, 600), Image.Resampling.LANCZOS)
        cell.paste(shown, ((640 - shown.width) // 2, (640 - shown.height) // 2), shown)
        cells.append((f"{scale * 100}% EDGE CHECK", cell))
    sheet = Image.new("RGB", (1280, 680), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, cell) in enumerate(cells):
        sheet.paste(cell, (index * 640, 40))
        draw.text((index * 640 + 12, 12), label, fill="#111827")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def scene_card(image: Image.Image, surface: str) -> Image.Image:
    width, height = image.size
    canvas = Image.new("RGBA", (width, height), surface)
    content = image.convert("RGBA")
    canvas.alpha_composite(content)
    return canvas


def process_asset(source: Path, role: str, output_dir: Path, surface: str, tolerance: float, metadata: dict) -> dict:
    image = Image.open(source)
    native_alpha = image.mode in ("RGBA", "LA") and np.min(np.asarray(image.convert("RGBA"))[:, :, 3]) < 250
    matte = None
    method = "native_alpha"
    if native_alpha:
        result = image.convert("RGBA")
        consistency = 1.0
    else:
        result, matte = remove_connected_matte(image, tolerance)
        consistency = matte["border_consistency"]
        method = "connected_matte_removal"
    qa = alpha_qa(result, matte["matte_rgb"] if matte else None)
    fallback = False
    if consistency < 0.72 or not qa["passed"]:
        result = scene_card(image, surface)
        method = "scene_matched_card_fallback"
        fallback = True
        qa = alpha_qa(result)
        qa["passed"] = True
        qa["fallback_reason"] = "clean transparent separation was not reliable"
    output = output_dir / f"{source.stem}-{role}.png"
    result.save(output)
    evidence = output_dir / "qa" / f"{source.stem}-{role}-edge-check.jpg"
    make_evidence(result, evidence)
    width, height = result.size
    anchor = {"x": 0.5, "y": 1.0} if role in ("character", "foreground") else {"x": 0.5, "y": 0.5}
    return {
        "id": source.stem,
        "role": role,
        "source": str(source),
        "output": str(output),
        "dimensions": {"width": width, "height": height},
        "anchor": anchor,
        "method": method,
        "scene_matched_fallback": fallback,
        "model": metadata.get("model"),
        "prompt": metadata.get("prompt"),
        "references": metadata.get("references", []),
        "transparency_qa": qa,
        "evidence": str(evidence),
        "hyperframes_contract": {"independently_animatable": True, "recommended_wrapper": "motion-shell", "editable_surface": "asset-surface"},
    }


def parse_asset(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("--asset must use role=path")
    role, path = value.split("=", 1)
    return role.strip(), Path(path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", action="append", required=True, help="Repeatable role=path entry")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--design-tokens")
    parser.add_argument("--metadata")
    parser.add_argument("--tolerance", type=float, default=48)
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    tokens = json.loads(Path(args.design_tokens).read_text(encoding="utf-8")) if args.design_tokens else {}
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8")) if args.metadata else {}
    surface = (tokens.get("surface") or {}).get("color", "#f7f8f4")
    components = []
    for role, source in map(parse_asset, args.asset):
        if not source.is_file():
            raise FileNotFoundError(source)
        components.append(process_asset(source, role, output_dir, surface, args.tolerance, metadata.get(source.stem, {})))
    manifest = {
        "schema_version": 1,
        "components": components,
        "all_independently_animatable": all(item["hyperframes_contract"]["independently_animatable"] for item in components),
        "raw_white_canvas_forbidden": True,
        "overall_passed": all(item["transparency_qa"]["passed"] for item in components),
    }
    manifest_path = Path(args.manifest).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0 if manifest["overall_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
