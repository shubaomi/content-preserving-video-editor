#!/usr/bin/env python3
"""Deterministic technical and editorial contract checks for cover candidates."""
from __future__ import annotations

import json
import argparse
from pathlib import Path
from typing import Any

from PIL import Image

from director_contracts import sha256_file, write_json


def _inside(box: list[float], bounds: list[float]) -> bool:
    if len(box) != 4 or len(bounds) != 4:
        return False
    x1, y1, x2, y2 = box
    bx1, by1, bx2, by2 = bounds
    return x1 >= bx1 and y1 >= by1 and x2 <= bx2 and y2 <= by2 and x2 > x1 and y2 > y1


def _intersection_ratio(first: list[float], second: list[float]) -> float:
    if len(first) != 4 or len(second) != 4:
        return 1.0
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(1.0, (first[2] - first[0]) * (first[3] - first[1]))
    return intersection / area


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return value


def evaluate_cover_candidate(
    *, image: Path, manifest_path: Path, plan_path: Path, variant: str,
    output: Path, thumbnail: Path,
) -> dict[str, Any]:
    """Write a hash-bound cover QA report; likeness remains a human gate."""
    manifest = _load(manifest_path)
    plan = _load(plan_path)
    with Image.open(image) as source:
        dimensions = source.size
        preview = source.convert("RGB")
        preview.thumbnail((180, 320), Image.Resampling.LANCZOS)
        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        preview.save(thumbnail, quality=92, subsampling=0)

    expected_variant = (plan.get("variants") or {}).get(variant) or {}
    expected_headline = (plan.get("headline") or {}).get("text")
    expected_highlights = (plan.get("headline") or {}).get("highlight_terms") or []
    typography = manifest.get("typography") or {}
    layout = manifest.get("layout") or {}
    bounds = layout.get("safe_bounds") or []
    boxes = layout.get("boxes") or {}
    title_box = boxes.get("title") or []
    subject_box = layout.get("subject_box") or []
    decorative_bounds = layout.get("decorative_bounds") or []
    assets = plan.get("supporting_assets") or []

    checks = {
        "native_9_16": dimensions == (1080, 1920),
        "plan_hash_matches": manifest.get("editorial_plan_sha256") == sha256_file(plan_path),
        "variant_matches": manifest.get("variant") == variant,
        "template_matches_plan": manifest.get("template_family") == expected_variant.get("template_family"),
        "exact_local_typography": typography.get("method") == "Pillow local deterministic text",
        "headline_matches_plan": typography.get("title") == expected_headline,
        "highlights_match_plan": typography.get("highlight_terms") == expected_highlights,
        "highlight_terms_are_not_split": all(
            any(term in line for line in (typography.get("lines") or []))
            for term in expected_highlights
        ),
        "headline_line_limit": 0 < int(typography.get("line_count") or 0) <= int(
            (plan.get("headline") or {}).get("maximum_lines", 3)
        ),
        "thumbnail_title_size": float(typography.get("minimum_thumbnail_font_px") or 0.0) >= 10.0,
        "topic_evidence_bound": bool((manifest.get("topic_evidence") or {}).get("event_ids")),
        "all_layout_boxes_inside_safe_bounds": bool(boxes) and all(
            _inside([float(value) for value in box], [float(value) for value in bounds])
            for box in boxes.values()
        ),
        "title_avoids_subject": bool(subject_box) and _intersection_ratio(
            [float(value) for value in title_box], [float(value) for value in subject_box]
        ) <= 0.05,
        "decoration_avoids_subject": bool(subject_box) and bool(decorative_bounds) and
        _intersection_ratio(
            [float(value) for value in decorative_bounds],
            [float(value) for value in subject_box],
        ) <= 0.01,
        "supporting_assets_have_provenance": all(
            (not row.get("available")) or (
                bool(row.get("sha256")) and bool(row.get("purpose")) and bool(row.get("rights_basis"))
            )
            for row in assets if isinstance(row, dict)
        ),
        "thumbnail_written": thumbnail.is_file(),
    }
    report = {
        "schema_version": 1,
        "candidate": str(image.resolve()),
        "candidate_sha256": sha256_file(image),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "editorial_plan": str(plan_path.resolve()),
        "editorial_plan_sha256": sha256_file(plan_path),
        "variant": variant,
        "dimensions": {"width": dimensions[0], "height": dimensions[1]},
        "thumbnail": str(thumbnail.resolve()),
        "thumbnail_sha256": sha256_file(thumbnail),
        "checks": checks,
        "automated_passed": all(checks.values()),
        "identity_user_approval": "pending",
        "identity_gate_note": "Automated checks cannot approve personal likeness on the user's behalf.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--variant", choices=("A", "B"), required=True)
    parser.add_argument("--thumbnail", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate_cover_candidate(
        image=Path(args.image), manifest_path=Path(args.manifest),
        plan_path=Path(args.plan), variant=args.variant,
        output=Path(args.out), thumbnail=Path(args.thumbnail),
    )
    print(args.out)
    return 0 if report["automated_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
