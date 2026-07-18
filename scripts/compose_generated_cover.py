#!/usr/bin/env python3
"""Compose exact local typography onto a reference-guided 9:16 poster base."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CANVAS = (1080, 1920)
CENTER_SAFE_INSET = 104
CENTER_SAFE_TOP = 170


def font(size: int, bold: bool = False):
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def cover_crop(image: Image.Image):
    scale = max(CANVAS[0] / image.width, CANVAS[1] / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - CANVAS[0]) // 2
    top = (resized.height - CANVAS[1]) // 2
    return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1])).convert("RGBA")


def wrap(draw: ImageDraw.ImageDraw, text: str, face, max_width: int):
    lines = []
    for paragraph in text.splitlines() or [text]:
        line = ""
        for char in paragraph:
            candidate = line + char
            if line and draw.textbbox((0, 0), candidate, font=face)[2] > max_width:
                lines.append(line)
                line = char
            else:
                line = candidate
        if line:
            lines.append(line)
    return lines


def _draw_chips(draw: ImageDraw.ImageDraw, chips: list[str], anchor_x: int, y: int, side: str) -> int:
    if not chips:
        return y
    chip_font = font(27, True)
    rows: list[list[tuple[str, int]]] = [[]]
    row_width = 0
    for value in chips[:4]:
        text_width = draw.textbbox((0, 0), value, font=chip_font)[2]
        width = text_width + 42
        gap = 14 if rows[-1] else 0
        if row_width + gap + width > 760 and rows[-1]:
            rows.append([])
            row_width = 0
            gap = 0
        rows[-1].append((value, width))
        row_width += gap + width
    for row in rows:
        total_width = sum(width for _, width in row) + 14 * max(0, len(row) - 1)
        x = anchor_x if side == "top-left" else anchor_x - total_width
        for value, width in row:
            draw.rounded_rectangle(
                (x, y, x + width, y + 52), radius=19,
                fill=(5, 18, 27, 176), outline=(116, 230, 211, 150), width=2,
            )
            draw.ellipse((x + 14, y + 20, x + 24, y + 30), fill=(45, 212, 191, 255))
            draw.text((x + 31, y + 9), value, font=chip_font, fill=(238, 248, 246))
            x += width + 14
        y += 66
    return y


def compose(base: Path, title: str, label: str, subtitle: str | None, side: str, chips: list[str] | None = None):
    canvas = cover_crop(Image.open(base).convert("RGB"))
    shade = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    pixels = shade.load()
    for y in range(CANVAS[1]):
        vertical = max(0.0, 1.0 - y / 930)
        for x in range(CANVAS[0]):
            horizontal = max(0.0, 1.0 - x / 940) if side == "top-left" else max(0.0, (x - 140) / 940)
            alpha = round(178 * vertical * horizontal)
            pixels[x, y] = (2, 8, 16, alpha)
    canvas = Image.alpha_composite(canvas, shade)
    draw = ImageDraw.Draw(canvas)
    # Keep deterministic typography inside the shared 9:16 center-safe range
    # used by both Douyin and WeChat Channels (8.33% inset on a 1080px canvas),
    # with an additional 14px optical guard for CJK glyph bearings and strokes.
    anchor_x = CENTER_SAFE_INSET if side == "top-left" else CANVAS[0] - CENTER_SAFE_INSET
    label_font = font(30, True)
    title_font = font(78, True)
    subtitle_font = font(34, False)
    label_box = draw.textbbox((0, 0), label, font=label_font)
    label_width = label_box[2] - label_box[0] + 40
    label_x = anchor_x if side == "top-left" else anchor_x - label_width
    draw.rounded_rectangle((label_x, CENTER_SAFE_TOP, label_x + label_width, CENTER_SAFE_TOP + 57), radius=22, fill=(45, 212, 191, 235))
    draw.text((label_x + 20, CENTER_SAFE_TOP + 11), label, font=label_font, fill=(3, 18, 27))
    # Small cinematic framing marks add hierarchy without relying on generated text.
    frame_color = (213, 240, 234, 150)
    draw.line((CENTER_SAFE_INSET, 112, CENTER_SAFE_INSET + 86, 112), fill=frame_color, width=3)
    draw.line((CENTER_SAFE_INSET, 112, CENTER_SAFE_INSET, 176), fill=frame_color, width=3)
    draw.line((CANVAS[0] - CENTER_SAFE_INSET, 112, CANVAS[0] - CENTER_SAFE_INSET - 86, 112), fill=frame_color, width=3)
    draw.text((CANVAS[0] - CENTER_SAFE_INSET - 84, 130), "01", font=font(24, True), fill=(213, 240, 234))
    lines = wrap(draw, title, title_font, 760)
    y = CENTER_SAFE_TOP + 102
    for line in lines[:3]:
        width = draw.textbbox((0, 0), line, font=title_font)[2]
        x = anchor_x if side == "top-left" else anchor_x - width
        draw.text((x, y), line, font=title_font, fill="white", stroke_width=2, stroke_fill=(3, 8, 15))
        y += 100
    line_x = anchor_x if side == "top-left" else anchor_x - 250
    draw.rounded_rectangle((line_x, y + 5, line_x + 250, y + 13), radius=4, fill=(45, 212, 191, 255))
    if subtitle:
        width = draw.textbbox((0, 0), subtitle, font=subtitle_font)[2]
        x = anchor_x if side == "top-left" else anchor_x - width
        draw.text((x, y + 36), subtitle, font=subtitle_font, fill=(219, 231, 239), stroke_width=1, stroke_fill=(3, 8, 15))
        y += 98
    else:
        y += 42
    _draw_chips(draw, chips or [], anchor_x, y, side)
    return canvas.convert("RGB")


def cover_passed(identity_reviewed: bool, expression_reviewed: bool) -> bool:
    return bool(identity_reviewed and expression_reviewed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--label", default="HONGRUN · AI 实践")
    parser.add_argument("--subtitle")
    parser.add_argument("--chip", action="append", default=[])
    parser.add_argument("--text-side", choices=("top-left", "top-right"), default="top-left")
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--expression-reference", action="append", default=[])
    parser.add_argument("--target-expression", default="natural friendly confidence with visible warmth")
    parser.add_argument("--prompt-file")
    parser.add_argument("--generator", default="built-in imagegen")
    parser.add_argument("--topic-evidence")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--rights-basis", default="authorized personal identity references and project-owned generated output")
    parser.add_argument("--agent-identity-reviewed", action="store_true")
    parser.add_argument("--agent-expression-reviewed", action="store_true")
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if len(args.reference) < 2:
        raise ValueError("Reference-guided covers require at least two authorized identity references")
    if not args.expression_reference:
        raise ValueError("Reference-guided covers require at least one authorized expression reference")
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing cover: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    result = compose(Path(args.base), args.title, args.label, args.subtitle, args.text_side, args.chip)
    result.save(out, quality=95, subsampling=0)
    manifest = {
        "schema_version": 3,
        "generation_mode": "reference_guided_regeneration",
        "clean_base": str(Path(args.base).resolve()),
        "output": str(out.resolve()),
        "canvas": {"width": CANVAS[0], "height": CANVAS[1], "ratio": "9:16"},
        "identity_references": [str(Path(item).resolve()) for item in args.reference],
        "expression_references": [str(Path(item).resolve()) for item in args.expression_reference],
        "generator": args.generator,
        "prompt_file": str(Path(args.prompt_file).resolve()) if args.prompt_file else None,
        "topic_evidence": args.topic_evidence,
        "communication_strategy": args.strategy,
        "rights_basis": args.rights_basis,
        "typography": {"method": "Pillow local deterministic text", "title": args.title, "label": args.label, "subtitle": args.subtitle, "chips": args.chip, "side": args.text_side},
        "identity_qa": {"reference_guided_generation": True, "agent_visual_review_passed": args.agent_identity_reviewed, "user_review_status": "pending"},
        "expression_qa": {
            "target": args.target_expression,
            "agent_visual_review_passed": args.agent_expression_reviewed,
            "eye_contact_and_energy_reviewed": args.agent_expression_reviewed,
            "user_review_status": "pending",
        },
        "forbidden_default": "literal_photo_cutout_on_generic_background",
        "passed": cover_passed(args.agent_identity_reviewed, args.agent_expression_reviewed),
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
