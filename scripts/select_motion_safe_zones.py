#!/usr/bin/env python3
"""Select low-occupancy motion zones from per-event source-frame evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat


ZONE_ORIGINS = {
    "top_left": (0.035, 0.14),
    "top_right": (None, 0.14),
    "side_left": (0.035, 0.34),
    "side_right": (None, 0.34),
    "lower_left": (0.035, 0.60),
    "lower_right": (None, 0.60),
}
ZONE_SIZE_BY_TIER = {
    "micro": (0.24, 0.14),
    "meso": (0.30, 0.18),
    "macro": (0.30, 0.16),
}


def zone_box(name: str, tier: str, width: int, height: int) -> tuple[int, int, int, int]:
    rel_width, rel_height = ZONE_SIZE_BY_TIER.get(tier, ZONE_SIZE_BY_TIER["meso"])
    x, y = ZONE_ORIGINS[name]
    if x is None:
        x = 1.0 - rel_width - 0.035
    return (
        round(x * width), round(y * height),
        round((x + rel_width) * width), round((y + rel_height) * height),
    )


def occupancy(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = image.crop(box).convert("L")
    histogram = crop.histogram()
    pixels = max(1, crop.width * crop.height)
    dark_ratio = sum(histogram[:220]) / pixels
    edges = crop.filter(ImageFilter.FIND_EDGES)
    edge_histogram = edges.histogram()
    edge_ratio = sum(edge_histogram[28:]) / pixels
    contrast = min(1.0, ImageStat.Stat(crop).stddev[0] / 72.0)
    return round(edge_ratio * 0.62 + dark_ratio * 0.28 + contrast * 0.10, 6)


def select_zone(image: Image.Image, tier: str, previous: str | None = None) -> tuple[str, dict[str, float]]:
    scores: dict[str, float] = {}
    for name in ZONE_ORIGINS:
        score = occupancy(image, zone_box(name, tier, *image.size))
        if name == previous:
            score += 0.035
        if name == "lower_right":
            score += 0.06  # common talking-head/PIP and platform-UI region
        scores[name] = round(score, 6)
    return min(scores, key=scores.get), scores


def apply(plan: dict, project_root: Path) -> dict:
    previous = None
    for event in sorted(plan.get("attention_events", plan.get("events", [])), key=lambda row: float(row["start"])):
        evidence_value = event.get("collision_check", {}).get("evidence")
        if isinstance(evidence_value, dict):
            evidence_value = evidence_value.get("frame")
        evidence_path = project_root / str(evidence_value)
        if not evidence_path.is_file():
            raise FileNotFoundError(f"{event['id']}: missing layout evidence {evidence_path}")
        with Image.open(evidence_path) as source:
            image = source.convert("RGB")
            selected, scores = select_zone(image, str(event.get("tier", "meso")), previous)
        event["safe_zone"] = selected
        event["collision_check"] = {
            **event.get("collision_check", {}),
            "status": "approved_safe_zone",
            "evidence": {
                "frame": str(evidence_path.relative_to(project_root)).replace("\\", "/"),
                "method": "source-frame edge, contrast, and dark-pixel occupancy",
                "scores": scores,
                "selected": selected,
            },
            "decision": "lowest-occupancy eligible edge zone; lower-right carries a PIP/platform-UI penalty",
        }
        previous = selected
    plan["layout_selection"] = {
        "method": "source_frame_occupancy_v1",
        "fixed_avoid_regions": ["browser_navigation", "footer_captions", "lower_right_pip"],
    }
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    plan_path = Path(args.plan)
    plan = apply(json.loads(plan_path.read_text(encoding="utf-8")), Path(args.project_root).resolve())
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
