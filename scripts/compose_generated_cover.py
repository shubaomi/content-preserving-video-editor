#!/usr/bin/env python3
"""Compose exact local typography with a small, controlled cover template system."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cover_editorial import COVER_TEMPLATE_FAMILIES
from director_contracts import sha256_file


CANVAS = (1080, 1920)
SAFE_BOUNDS = [90, 110, 990, 1810]
# Kept as public compatibility anchors for existing callers and tests.
CENTER_SAFE_INSET = 104
CENTER_SAFE_TOP = 170

THEMES: dict[str, dict[str, Any]] = {
    "cinematic_editorial": {
        "title": (248, 251, 252), "highlight": (45, 212, 191),
        "subtitle": (219, 231, 239), "label_fill": (45, 212, 191, 238),
        "label_text": (3, 18, 27), "chip_fill": (5, 18, 27, 190),
        "chip_outline": (116, 230, 211, 170), "chip_text": (238, 248, 246),
        "stroke": (3, 8, 15), "title_size": 82, "decor": "cinematic",
    },
    "bright_tech_tutorial": {
        "title": (14, 25, 38), "highlight": (69, 74, 222),
        "subtitle": (54, 67, 82), "label_fill": (62, 94, 240, 242),
        "label_text": (255, 255, 255), "chip_fill": (247, 249, 255, 230),
        "chip_outline": (85, 98, 230, 190), "chip_text": (28, 37, 67),
        "stroke": (255, 255, 255), "title_size": 84, "decor": "bright",
    },
    "dark_high_energy": {
        "title": (255, 244, 219), "highlight": (255, 158, 52),
        "subtitle": (244, 224, 197), "label_fill": (255, 139, 36, 244),
        "label_text": (24, 12, 4), "chip_fill": (24, 14, 10, 220),
        "chip_outline": (255, 158, 52, 230), "chip_text": (255, 239, 214),
        "stroke": (28, 9, 2), "title_size": 90, "decor": "energy",
    },
    "thought_leadership_ip": {
        "title": (250, 250, 247), "highlight": (255, 211, 45),
        "subtitle": (236, 238, 226), "label_fill": (250, 250, 247, 242),
        "label_text": (18, 20, 18), "chip_fill": (10, 13, 11, 220),
        "chip_outline": (255, 211, 45, 190), "chip_text": (250, 250, 247),
        "stroke": (7, 8, 7), "title_size": 84, "decor": "brush",
    },
}


def font(size: int, bold: bool = False):
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def cover_crop(image: Image.Image):
    scale = max(CANVAS[0] / image.width, CANVAS[1] / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - CANVAS[0]) // 2
    top = (resized.height - CANVAS[1]) // 2
    return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1])).convert("RGBA")


def _wrap_with_offsets(
    draw: ImageDraw.ImageDraw, text: str, face, max_width: int,
    protected_terms: list[str] | None = None,
):
    lines: list[tuple[str, int]] = []
    line = ""
    line_start = 0
    terms = sorted({value for value in (protected_terms or []) if value}, key=len, reverse=True)
    index = 0
    while index < len(text):
        char = text[index]
        token = next((term for term in terms if text.startswith(term, index)), char)
        if token == "\n":
            if line:
                lines.append((line, line_start))
            line = ""
            line_start = index + 1
            index += 1
            continue
        candidate = line + token
        if line and draw.textbbox((0, 0), candidate, font=face)[2] > max_width:
            lines.append((line, line_start))
            line = token
            line_start = index
        else:
            if not line:
                line_start = index
            line = candidate
        index += len(token)
    if line:
        lines.append((line, line_start))
    return lines


def wrap(draw: ImageDraw.ImageDraw, text: str, face, max_width: int):
    """Backward-compatible plain line wrapper used by the original renderer API."""
    return [line for line, _ in _wrap_with_offsets(draw, text, face, max_width)]


def _fit_title(
    draw: ImageDraw.ImageDraw, text: str, *, start_size: int, max_width: int,
    maximum_lines: int, protected_terms: list[str] | None = None,
):
    for size in range(start_size, 55, -2):
        face = font(size, True)
        lines = _wrap_with_offsets(draw, text, face, max_width, protected_terms)
        if len(lines) <= maximum_lines:
            return face, size, lines
    raise ValueError(f"cover title cannot fit in {maximum_lines} lines without becoming unreadable")


def _highlight_indexes(text: str, terms: list[str]) -> set[int]:
    indexes: set[int] = set()
    for term in terms:
        cursor = 0
        while term and (position := text.find(term, cursor)) >= 0:
            indexes.update(range(position, position + len(term)))
            cursor = position + len(term)
    return indexes


def _union(boxes: list[list[int]]) -> list[int]:
    return [
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    ]


def _decorate(
    canvas: Image.Image, *, theme: dict[str, Any], side: str,
    subject_box: list[int] | None,
) -> tuple[Image.Image, list[int]]:
    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    decor = theme["decor"]
    if side == "top-left":
        edge = min(675, (subject_box[0] - 24) if subject_box else 675)
        edge = max(520, edge)
        decorative_bounds = [0, 0, edge, 1010]
    else:
        edge = max(405, (subject_box[2] + 24) if subject_box else 405)
        edge = min(560, edge)
        decorative_bounds = [edge, 0, CANVAS[0], 1010]
    if decor == "bright":
        panel = (55, 125, edge, 900) if side == "top-left" else (edge, 125, 1025, 900)
        draw.rounded_rectangle(panel, radius=46, fill=(249, 252, 255, 210), outline=(255, 255, 255, 235), width=3)
        for x in range(90, 620, 64):
            draw.ellipse((x, 118, x + 5, 123), fill=(69, 74, 222, 110))
    elif decor == "energy":
        if side == "top-left":
            draw.rectangle((0, 0, edge, 1010), fill=(5, 5, 8, 150))
            draw.polygon([(55, 135), (edge, 135), (edge - 70, 900), (55, 900)], fill=(10, 8, 8, 185))
            draw.line((85, 118, edge - 18, 760), fill=(255, 139, 36, 150), width=7)
        else:
            draw.rectangle((edge, 0, 1080, 1010), fill=(5, 5, 8, 150))
            draw.polygon([(edge, 135), (1025, 135), (1025, 900), (edge + 70, 900)], fill=(10, 8, 8, 185))
            draw.line((995, 118, edge + 18, 760), fill=(255, 139, 36, 150), width=7)
    elif decor == "brush":
        if side == "top-left":
            polygon = [(55, 135), (edge, 120), (edge - 35, 870), (80, 900), (45, 730)]
        else:
            polygon = [(edge, 120), (1025, 135), (1035, 730), (1000, 900), (edge + 35, 870)]
        draw.polygon(polygon, fill=(4, 6, 5, 205))
        draw.line((90, 880, edge - 35, 850) if side == "top-left" else (edge + 35, 850, 990, 880),
                  fill=(255, 211, 45, 210), width=12)
    else:
        for y in range(960):
            vertical = max(0.0, 1.0 - y / 960)
            alpha = round(190 * vertical)
            if side == "top-left":
                draw.line((0, y, edge, y), fill=(2, 8, 16, alpha), width=1)
            else:
                draw.line((edge, y, 1080, y), fill=(2, 8, 16, alpha), width=1)
        draw.line((90, 112, 176, 112), fill=(213, 240, 234, 170), width=3)
        draw.line((90, 112, 90, 176), fill=(213, 240, 234, 170), width=3)
    return Image.alpha_composite(canvas, overlay), decorative_bounds


def _draw_chips(
    draw: ImageDraw.ImageDraw, chips: list[str], anchor_x: int, y: int, side: str,
    theme: dict[str, Any], boxes: dict[str, list[int]],
) -> int:
    if not chips:
        return y
    chip_font = font(27, True)
    rows: list[list[tuple[str, int]]] = [[]]
    row_width = 0
    for value in chips[:4]:
        text_width = draw.textbbox((0, 0), value, font=chip_font)[2]
        width = text_width + 42
        gap = 14 if rows[-1] else 0
        if row_width + gap + width > 520 and rows[-1]:
            rows.append([])
            row_width = 0
            gap = 0
        rows[-1].append((value, width))
        row_width += gap + width
    chip_boxes: list[list[int]] = []
    for row in rows:
        total_width = sum(width for _, width in row) + 14 * max(0, len(row) - 1)
        x = anchor_x if side == "top-left" else anchor_x - total_width
        for value, width in row:
            box = [x, y, x + width, y + 52]
            draw.rounded_rectangle(tuple(box), radius=19, fill=theme["chip_fill"],
                                   outline=theme["chip_outline"], width=2)
            draw.ellipse((x + 14, y + 20, x + 24, y + 30), fill=theme["highlight"])
            draw.text((x + 31, y + 9), value, font=chip_font, fill=theme["chip_text"])
            chip_boxes.append(box)
            x += width + 14
        y += 66
    if chip_boxes:
        boxes["chips"] = _union(chip_boxes)
    return y


def _draw_supporting_assets(
    canvas: Image.Image, assets: list[dict[str, Any]], *, subject_box: list[int] | None,
    boxes: dict[str, list[int]], theme: dict[str, Any],
) -> None:
    if not assets:
        return
    subject_left = subject_box[0] if subject_box else 610
    place_left = subject_left >= CANVAS[0] / 2
    x = SAFE_BOUNDS[0] if place_left else SAFE_BOUNDS[2] - 250
    y = 1325
    for index, row in enumerate(assets[:2]):
        path = Path(str(row.get("path") or ""))
        if not path.is_file():
            continue
        with Image.open(path) as source:
            asset = source.convert("RGBA")
        asset.thumbnail((220, 220), Image.Resampling.LANCZOS)
        card = Image.new("RGBA", (250, 250), (248, 248, 242, 238))
        card_draw = ImageDraw.Draw(card)
        card_draw.rounded_rectangle((1, 1, 248, 248), radius=34, outline=theme["highlight"], width=4)
        card.alpha_composite(asset, ((250 - asset.width) // 2, (250 - asset.height) // 2))
        canvas.alpha_composite(card, (x, y))
        boxes[f"supporting_asset_{index}"] = [x, y, x + 250, y + 250]
        y += 270


def compose_with_layout(
    *, base: Path, title: str, label: str, subtitle: str | None, side: str,
    chips: list[str] | None = None, template_family: str = "cinematic_editorial",
    highlight_terms: list[str] | None = None, subject_box: list[int] | None = None,
    supporting_assets: list[dict[str, Any]] | None = None, maximum_lines: int = 3,
) -> tuple[Image.Image, dict[str, Any]]:
    if template_family not in COVER_TEMPLATE_FAMILIES:
        raise ValueError(f"unsupported cover template family: {template_family}")
    if side not in {"top-left", "top-right"}:
        raise ValueError("text side must be top-left or top-right")
    theme = THEMES[template_family]
    canvas, decorative_bounds = _decorate(
        cover_crop(Image.open(base).convert("RGB")), theme=theme, side=side,
        subject_box=subject_box,
    )
    draw = ImageDraw.Draw(canvas)
    boxes: dict[str, list[int]] = {}
    anchor_x = 104 if side == "top-left" else 976

    label_font = font(29, True)
    label_width = draw.textbbox((0, 0), label, font=label_font)[2] + 40
    label_x = anchor_x if side == "top-left" else anchor_x - label_width
    label_box = [label_x, 158, label_x + label_width, 217]
    draw.rounded_rectangle(tuple(label_box), radius=22, fill=theme["label_fill"])
    draw.text((label_x + 20, 169), label, font=label_font, fill=theme["label_text"])
    boxes["label"] = label_box

    if side == "top-left":
        available_width = (subject_box[0] - anchor_x - 34) if subject_box else 760
    else:
        available_width = (anchor_x - subject_box[2] - 34) if subject_box else 760
    available_width = max(330, min(760, int(available_width)))
    title_font, title_size, lines = _fit_title(
        draw, title, start_size=int(theme["title_size"]), max_width=available_width,
        maximum_lines=maximum_lines, protected_terms=highlight_terms or [],
    )
    highlight_indexes = _highlight_indexes(title, highlight_terms or [])
    line_height = round(title_size * 1.23)
    y = 258
    title_boxes: list[list[int]] = []
    for line, start_index in lines:
        line_width = draw.textbbox((0, 0), line, font=title_font)[2]
        x = anchor_x if side == "top-left" else anchor_x - line_width
        start_x = x
        for offset, char in enumerate(line):
            fill = theme["highlight"] if start_index + offset in highlight_indexes else theme["title"]
            draw.text((x, y), char, font=title_font, fill=fill, stroke_width=2, stroke_fill=theme["stroke"])
            x += draw.textlength(char, font=title_font)
        title_boxes.append([int(start_x), y, int(start_x + line_width), y + line_height])
        y += line_height
    boxes["title"] = _union(title_boxes)

    accent_width = min(250, available_width)
    accent_x = anchor_x if side == "top-left" else anchor_x - accent_width
    accent_box = [accent_x, y + 4, accent_x + accent_width, y + 13]
    draw.rounded_rectangle(tuple(accent_box), radius=4, fill=theme["highlight"])
    boxes["accent"] = accent_box
    y += 38
    if subtitle:
        subtitle_font = font(32, False)
        subtitle_lines = _wrap_with_offsets(draw, subtitle, subtitle_font, available_width)[:2]
        subtitle_boxes: list[list[int]] = []
        for line, _ in subtitle_lines:
            width = draw.textbbox((0, 0), line, font=subtitle_font)[2]
            x = anchor_x if side == "top-left" else anchor_x - width
            draw.text((x, y), line, font=subtitle_font, fill=theme["subtitle"],
                      stroke_width=1, stroke_fill=theme["stroke"])
            subtitle_boxes.append([int(x), y, int(x + width), y + 45])
            y += 47
        if subtitle_boxes:
            boxes["subtitle"] = _union(subtitle_boxes)
        y += 18
    _draw_chips(draw, chips or [], anchor_x, y, side, theme, boxes)
    _draw_supporting_assets(
        canvas, supporting_assets or [], subject_box=subject_box, boxes=boxes, theme=theme,
    )

    layout = {
        "template_family": template_family,
        "safe_bounds": SAFE_BOUNDS,
        "decorative_bounds": decorative_bounds,
        "boxes": boxes,
        "subject_box": subject_box,
        "typography": {
            "line_count": len(lines),
            "lines": [line for line, _ in lines],
            "title_font_size": title_size,
            "minimum_thumbnail_font_px": round(title_size * 180 / CANVAS[0], 2),
            "highlight_terms": highlight_terms or [],
        },
    }
    return canvas.convert("RGB"), layout


def compose(
    base: Path, title: str, label: str, subtitle: str | None, side: str,
    chips: list[str] | None = None,
):
    result, _ = compose_with_layout(
        base=base, title=title, label=label, subtitle=subtitle, side=side, chips=chips,
    )
    return result


def cover_passed(identity_reviewed: bool, expression_reviewed: bool) -> bool:
    return bool(identity_reviewed and expression_reviewed)


def _parse_box(value: str | None) -> list[int] | None:
    if not value:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, list) or len(parsed) != 4:
        raise ValueError("subject box must be a JSON array of four integers")
    return [int(item) for item in parsed]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--label", default="HONGRUN · AI 实践")
    parser.add_argument("--subtitle")
    parser.add_argument("--chip", action="append", default=[])
    parser.add_argument("--highlight-term", action="append", default=[])
    parser.add_argument("--template-family", choices=COVER_TEMPLATE_FAMILIES, default="cinematic_editorial")
    parser.add_argument("--text-side", choices=("top-left", "top-right"), default="top-left")
    parser.add_argument("--subject-box")
    parser.add_argument("--supporting-asset", action="append", default=[])
    parser.add_argument("--maximum-lines", type=int, default=3)
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--expression-reference", action="append", default=[])
    parser.add_argument("--target-expression", default="natural friendly confidence with visible warmth")
    parser.add_argument("--prompt-file")
    parser.add_argument("--generator", default="built-in imagegen")
    parser.add_argument("--generation-mode", choices=(
        "reference_regenerated", "authentic_frame_editorial", "real_person_ip_hybrid",
    ), default="reference_regenerated")
    parser.add_argument("--authentic-frame", action="append", default=[])
    parser.add_argument("--topic-evidence")
    parser.add_argument("--editorial-plan")
    parser.add_argument("--variant", choices=("A", "B"))
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--rights-basis", default="authorized personal identity references and project-owned generated output")
    parser.add_argument("--agent-identity-reviewed", action="store_true")
    parser.add_argument("--agent-expression-reviewed", action="store_true")
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.generation_mode != "authentic_frame_editorial" and len(args.reference) < 2:
        raise ValueError("Reference-guided covers require at least two authorized identity references")
    if args.generation_mode != "authentic_frame_editorial" and not args.expression_reference:
        raise ValueError("Reference-guided covers require at least one authorized expression reference")
    if args.generation_mode == "authentic_frame_editorial" and not args.authentic_frame:
        raise ValueError("Authentic-frame covers require at least one source frame")

    plan: dict[str, Any] | None = None
    plan_path = Path(args.editorial_plan).resolve() if args.editorial_plan else None
    if plan_path:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    supporting_assets = [{"path": value, "role": "supporting_visual"} for value in args.supporting_asset]
    result, layout = compose_with_layout(
        base=Path(args.base), title=args.title, label=args.label, subtitle=args.subtitle,
        side=args.text_side, chips=args.chip, template_family=args.template_family,
        highlight_terms=args.highlight_term, subject_box=_parse_box(args.subject_box),
        supporting_assets=supporting_assets, maximum_lines=args.maximum_lines,
    )
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing cover: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    result.save(out, quality=95, subsampling=0)
    event_ids = ((plan or {}).get("evidence") or {}).get("event_ids") or []
    manifest = {
        "schema_version": 4,
        "generation_mode": args.generation_mode,
        "clean_base": str(Path(args.base).resolve()),
        "output": str(out.resolve()),
        "canvas": {"width": CANVAS[0], "height": CANVAS[1], "ratio": "9:16"},
        "identity_references": [str(Path(item).resolve()) for item in args.reference],
        "expression_references": [str(Path(item).resolve()) for item in args.expression_reference],
        "authentic_frames": [str(Path(item).resolve()) for item in args.authentic_frame],
        "generator": args.generator,
        "prompt_file": str(Path(args.prompt_file).resolve()) if args.prompt_file else None,
        "topic_evidence": {"semantic_brief": args.topic_evidence, "event_ids": event_ids},
        "editorial_plan": str(plan_path) if plan_path else None,
        "editorial_plan_sha256": sha256_file(plan_path) if plan_path and plan_path.is_file() else None,
        "variant": args.variant,
        "template_family": args.template_family,
        "communication_strategy": args.strategy,
        "rights_basis": args.rights_basis,
        "typography": {
            "method": "Pillow local deterministic text", "title": args.title,
            "label": args.label, "subtitle": args.subtitle, "chips": args.chip,
            "side": args.text_side, "highlight_terms": args.highlight_term,
            **layout["typography"],
        },
        "layout": {key: value for key, value in layout.items() if key != "typography"},
        "supporting_assets": supporting_assets,
        "identity_qa": {
            "reference_guided_generation": args.generation_mode != "authentic_frame_editorial",
            "authentic_source_pixels": args.generation_mode == "authentic_frame_editorial",
            "agent_visual_review_passed": args.agent_identity_reviewed,
            "user_review_status": "pending",
        },
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
