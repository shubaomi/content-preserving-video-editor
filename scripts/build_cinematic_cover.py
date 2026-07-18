#!/usr/bin/env python3
"""Build a 9:16 cinematic cover while preserving authorized subject pixels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


CANVAS = (1080, 1920)


def detect_face(image: Image.Image) -> tuple[int, int, int, int] | None:
    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    scale = min(1.0, 900 / max(image.size))
    sampled = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(sampled, 1.1, 5, minSize=(45, 45))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
    return round(x / scale), round(y / scale), round(w / scale), round(h / scale)


def auto_mask(image: Image.Image, face: tuple[int, int, int, int] | None) -> tuple[Image.Image, str]:
    rgb = np.asarray(image.convert("RGB"))
    max_dim = 1200
    scale = min(1.0, max_dim / max(image.size))
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb.copy()
    height, width = small.shape[:2]
    if face:
        fx, fy, fw, fh = [round(value * scale) for value in face]
        center = fx + fw / 2
        x0 = max(1, round(center - fw * 2.1))
        x1 = min(width - 1, round(center + fw * 2.1))
        y0 = max(1, round(fy - fh * 0.5))
        rect = (x0, y0, max(2, x1 - x0), max(2, height - y0 - 1))
    else:
        rect = (round(width * 0.05), round(height * 0.03), round(width * 0.9), round(height * 0.94))
    mask = np.zeros((height, width), np.uint8)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv2.grabCut(cv2.cvtColor(small, cv2.COLOR_RGB2BGR), mask, rect, background, foreground, 5, cv2.GC_INIT_WITH_RECT)
    binary = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    if face:
        fx, fy, fw, fh = [round(value * scale) for value in face]
        count, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
        center_x = min(width - 1, max(0, fx + fw // 2))
        center_y = min(height - 1, max(0, fy + fh // 2))
        subject_label = int(labels[center_y, center_x])
        if subject_label > 0:
            binary = np.where(labels == subject_label, 255, 0).astype(np.uint8)
    coverage = float(np.mean(binary > 0))
    if coverage < 0.07 or coverage > 0.82:
        return Image.new("L", image.size, 255), "full_photo_nongenerative_fallback"
    binary = cv2.GaussianBlur(binary, (0, 0), 1.2)
    if scale < 1:
        binary = cv2.resize(binary, image.size, interpolation=cv2.INTER_LINEAR)
    return Image.fromarray(binary, "L"), "opencv_grabcut"


def portrait_model_mask(image: Image.Image) -> tuple[Image.Image, str]:
    from rembg import new_session, remove
    session = new_session("u2net_human_seg")
    mask = remove(image, session=session, only_mask=True, post_process_mask=True)
    return mask.convert("L").resize(image.size, Image.Resampling.LANCZOS), "rembg_u2net_human_seg_local"


def mask_quality(mask: Image.Image, face: tuple[int, int, int, int] | None) -> dict:
    array = np.asarray(mask, dtype=np.uint8)
    coverage = float(np.mean(array > 32))
    face_coverage = None
    if face:
        x, y, w, h = face
        face_coverage = float(np.mean(array[y:y + h, x:x + w] > 128))
    passed = 0.05 <= coverage <= 0.75 and (face_coverage is None or face_coverage >= 0.82)
    return {"foreground_coverage": round(coverage, 4), "face_coverage": round(face_coverage, 4) if face_coverage is not None else None, "passed": passed}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf")]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def background_layer(background: Image.Image | None, accent: str) -> Image.Image:
    if background:
        image = background.convert("RGB")
        ratio = max(CANVAS[0] / image.width, CANVAS[1] / image.height)
        image = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
        left, top = (image.width - CANVAS[0]) // 2, (image.height - CANVAS[1]) // 2
        return image.crop((left, top, left + CANVAS[0], top + CANVAS[1])).filter(ImageFilter.GaussianBlur(8))
    base = Image.new("RGB", CANVAS, "#07131f")
    draw = ImageDraw.Draw(base)
    color = accent
    for radius, opacity in ((850, 36), (520, 44), (280, 60)):
        overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).ellipse((700 - radius, 580 - radius, 700 + radius, 580 + radius), fill=color + f"{opacity:02x}")
        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    return base.filter(ImageFilter.GaussianBlur(70))


def fit_subject(photo: Image.Image, mask: Image.Image) -> tuple[Image.Image, dict]:
    rgba = photo.convert("RGBA")
    rgba.putalpha(mask)
    bbox = mask.getbbox() or (0, 0, photo.width, photo.height)
    subject = rgba.crop(bbox)
    scale = min(1000 / subject.width, 1680 / subject.height)
    size = (max(1, round(subject.width * scale)), max(1, round(subject.height * scale)))
    subject = subject.resize(size, Image.Resampling.LANCZOS)
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    x = CANVAS[0] - subject.width + 90
    y = CANVAS[1] - subject.height
    layer.alpha_composite(subject, (x, y))
    return layer, {"source_bbox": list(bbox), "scale": round(scale, 6), "canvas_position": [x, y], "size": list(size)}


def add_typography(composite: Image.Image, title: str, label: str) -> Image.Image:
    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    label_font = font(30, True)
    label_width = draw.textbbox((0, 0), label, font=label_font)[2]
    draw.rounded_rectangle((72, 132, 72 + label_width + 48, 194), radius=22, fill="#2dd4bfdd")
    draw.text((96, 145), label, font=label_font, fill="#07131f")
    lines = []
    current = ""
    for character in title:
        candidate = current + character
        if draw.textbbox((0, 0), candidate, font=font(82, True))[2] > 760 and current:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    y = 245
    for line in lines[:4]:
        draw.text((72, y), line, font=font(82, True), fill="white", stroke_width=2, stroke_fill="#07131f")
        y += 108
    draw.rectangle((72, y + 18, 350, y + 24), fill="#2dd4bf")
    return Image.alpha_composite(composite.convert("RGBA"), overlay)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", required=True)
    parser.add_argument("--mask")
    parser.add_argument("--background")
    parser.add_argument("--design-tokens")
    parser.add_argument("--title", required=True)
    parser.add_argument("--label", default="HONGRUN · AI 实践")
    parser.add_argument("--out", required=True)
    parser.add_argument("--layers-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--segmentation", choices=("auto", "rembg", "grabcut"), default="auto")
    args = parser.parse_args()
    photo_path = Path(args.photo).resolve()
    photo = Image.open(photo_path).convert("RGB")
    face = detect_face(photo)
    if args.mask:
        mask = Image.open(args.mask).convert("L").resize(photo.size, Image.Resampling.LANCZOS)
        segmentation = "authorized_supplied_mask"
    else:
        if args.segmentation in ("auto", "rembg"):
            try:
                mask, segmentation = portrait_model_mask(photo)
            except Exception:
                if args.segmentation == "rembg":
                    raise
                mask, segmentation = auto_mask(photo, face)
        else:
            mask, segmentation = auto_mask(photo, face)
    quality = mask_quality(mask, face)
    if not quality["passed"] and segmentation != "authorized_supplied_mask":
        mask, segmentation = auto_mask(photo, face)
        quality = mask_quality(mask, face)
    tokens = json.loads(Path(args.design_tokens).read_text(encoding="utf-8")) if args.design_tokens else {}
    accent = (tokens.get("accent") or {}).get("color", "#2dd4bf")
    background_source = Image.open(args.background) if args.background else None
    background = background_layer(background_source, accent)
    subject, transform = fit_subject(photo, mask)
    # Darken the title side on the background before compositing the subject,
    # so the authorized face/subject layer is never color-redrawn.
    shade = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(0, 680, 8):
        alpha = round(150 * (1 - x / 680))
        sd.rectangle((x, 0, x + 8, CANVAS[1]), fill=(3, 10, 18, alpha))
    shaded_background = Image.alpha_composite(background.convert("RGBA"), shade)
    composite = Image.alpha_composite(shaded_background, subject)
    final = add_typography(composite, args.title, args.label)
    output = Path(args.out).resolve()
    layers = Path(args.layers_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    layers.mkdir(parents=True, exist_ok=True)
    background.save(layers / "background.png")
    mask.save(layers / "subject-mask.png")
    subject.save(layers / "subject.png")
    composite.save(layers / "composite-before-type.png")
    final.convert("RGB").save(output, quality=95)
    preview = final.copy().convert("RGB")
    pd = ImageDraw.Draw(preview)
    pd.rectangle((90, 80, 990, 1840), outline="#2dd4bf", width=4)
    pd.rectangle((0, 420, 1080, 1500), outline="#f59e0b", width=4)
    preview.save(layers / "platform-safe-preview.jpg", quality=92)
    manifest = {
        "schema_version": 1,
        "output": str(output), "canvas": {"width": 1080, "height": 1920, "ratio": "9:16"},
        "source_photo": str(photo_path), "face_box": list(face) if face else None,
        "identity_qa": {"authorized_source_pixels_used": True, "generative_face_alteration": False, "eyes_nose_mouth_jaw_age_structure_redrawn": False, "passed": face is not None},
        "segmentation": segmentation, "segmentation_qa": quality, "mask": str(layers / "subject-mask.png"),
        "background": {"source": str(Path(args.background).resolve()) if args.background else "deterministic_gradient", "generated_separately_from_subject": True},
        "transform": transform, "layers": ["background.png", "subject-mask.png", "subject.png", "composite-before-type.png"],
        "safe_preview": str(layers / "platform-safe-preview.jpg"), "font": "Microsoft YaHei or Arial fallback", "compositing_method": "Pillow alpha composite",
        "passed": face is not None and quality["passed"],
    }
    manifest_path = Path(args.manifest).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0 if manifest["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
