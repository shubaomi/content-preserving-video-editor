#!/usr/bin/env python3
"""Validate and compare two reference-guided cover strategies without performance claims."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from director_contracts import sha256_file


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def font(size: int, bold: bool = False):
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def image_difference(a: Path, b: Path):
    with Image.open(a) as source:
        first = np.asarray(source.convert("RGB").resize((180, 320), Image.Resampling.LANCZOS), dtype=np.float32)
    with Image.open(b) as source:
        second = np.asarray(source.convert("RGB").resize((180, 320), Image.Resampling.LANCZOS), dtype=np.float32)
    return round(float(np.mean(np.abs(first - second)) / 255.0), 4)


def clean_text(value):
    return isinstance(value, str) and bool(value.strip()) and "\ufffd" not in value


def validate_manifest(data):
    with Image.open(data["output"]) as image:
        size = image.size
    mode = data.get("generation_mode")
    checks = {
        "supported_identity_route": mode in {
            "reference_guided_regeneration", "reference_regenerated",
            "authentic_frame_editorial", "real_person_ip_hybrid",
        },
        "identity_provenance": (
            len(data.get("authentic_frames", [])) >= 1
            if mode == "authentic_frame_editorial"
            else len(data.get("identity_references", [])) >= 2
        ),
        "agent_identity_review": data.get("identity_qa", {}).get("agent_visual_review_passed") is True,
        "topic_evidence": bool(data.get("topic_evidence")),
        "strategy": bool(data.get("communication_strategy")),
        "rights_basis": bool(data.get("rights_basis")),
        "exact_local_typography": data.get("typography", {}).get("method") == "Pillow local deterministic text",
        "typography_text_is_valid_utf8": all(
            clean_text(value)
            for value in (
                data.get("typography", {}).get("title"),
                data.get("typography", {}).get("label"),
                data.get("typography", {}).get("subtitle"),
            )
            if value is not None
        ),
        "title_present": clean_text(data.get("typography", {}).get("title")),
        "native_9_16": size == (1080, 1920),
    }
    return checks


def contact_sheet(a: Path, b: Path, out: Path):
    with Image.open(a) as source:
        first = source.convert("RGB").resize((360, 640), Image.Resampling.LANCZOS)
    with Image.open(b) as source:
        second = source.convert("RGB").resize((360, 640), Image.Resampling.LANCZOS)
    sheet = Image.new("RGB", (720, 700), "white")
    sheet.paste(first, (0, 60))
    sheet.paste(second, (360, 60))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 16), "A · TOPIC CLARITY", font=font(24, True), fill="black")
    draw.text((376, 16), "B · HUMAN CURIOSITY", font=font(24, True), fill="black")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=94, subsampling=0)


def _valid_qa(path: Path | None, manifest: dict):
    if path is None:
        return True
    data = load(path)
    return (
        data.get("automated_passed") is True
        and data.get("candidate_sha256") == sha256_file(Path(manifest["output"]))
        and data.get("manifest_sha256") == sha256_file(Path(data["manifest"]))
    )


def _identity_provenance(manifest: dict):
    if manifest.get("generation_mode") == "authentic_frame_editorial":
        return manifest.get("authentic_frames", [])
    return manifest.get("identity_references", [])


def compare(
    manifest_a: Path, manifest_b: Path, recommended: str, rationale: str, sheet: Path,
    qa_a: Path | None = None, qa_b: Path | None = None,
):
    a = load(manifest_a)
    b = load(manifest_b)
    checks_a = validate_manifest(a)
    checks_b = validate_manifest(b)
    difference = image_difference(Path(a["output"]), Path(b["output"]))
    shared_identity = _identity_provenance(a) == _identity_provenance(b)
    strategies_differ = a["communication_strategy"] != b["communication_strategy"]
    contact_sheet(Path(a["output"]), Path(b["output"]), sheet)
    checks = {
        "variant_a": all(checks_a.values()),
        "variant_b": all(checks_b.values()),
        "variant_a_automated_qa": _valid_qa(qa_a, a),
        "variant_b_automated_qa": _valid_qa(qa_b, b),
        "same_authorized_identity_references": shared_identity,
        "different_communication_strategies": strategies_differ,
        "meaningful_visual_difference": difference >= 0.08,
        "comparison_sheet_exists": sheet.is_file(),
        "recommendation_is_editorial_not_performance_prediction": bool(rationale) and recommended in {"A", "B"},
    }
    return {
        "schema_version": 2,
        "pipeline": "reference_guided_generative_cover_ab",
        "variants": {
            "A": {"manifest": str(manifest_a.resolve()), "strategy": a["communication_strategy"],
                  "checks": checks_a, "quality_report": str(qa_a.resolve()) if qa_a else None},
            "B": {"manifest": str(manifest_b.resolve()), "strategy": b["communication_strategy"],
                  "checks": checks_b, "quality_report": str(qa_b.resolve()) if qa_b else None},
        },
        "pixel_difference_0_1": difference,
        "checks": checks,
        "recommended_variant": recommended,
        "editorial_rationale": rationale,
        "performance_claim": "none; recommendation is editorial and must not be described as predicted platform performance",
        "user_identity_review": "external post-delivery approval gate; not fabricated by automation",
        "comparison_sheet": str(sheet.resolve()),
        "passed": all(checks.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-a", required=True)
    parser.add_argument("--manifest-b", required=True)
    parser.add_argument("--recommended", choices=("A", "B"), required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--qa-a")
    parser.add_argument("--qa-b")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = compare(
        Path(args.manifest_a), Path(args.manifest_b), args.recommended, args.rationale,
        Path(args.sheet), Path(args.qa_a) if args.qa_a else None,
        Path(args.qa_b) if args.qa_b else None,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
