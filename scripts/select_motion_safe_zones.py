#!/usr/bin/env python3
"""Select low-occupancy motion zones from per-event source-frame evidence."""
from __future__ import annotations

import argparse
import json
import re
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
PORTRAIT_PERSON_CONTENT_TYPES = {"talking_head", "portrait_talking_head", "interview"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _valid_normalized_bbox(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value["width"])
        height = float(value["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        0 <= x <= 1
        and 0 <= y <= 1
        and 0 < width <= 1
        and 0 < height <= 1
        and x + width <= 1
        and y + height <= 1
    )


def subject_track_face_regions(
    report: dict, *, report_path: Path, report_sha256: str,
) -> list[dict]:
    """Translate verified tracked faces into normalized protected regions."""
    tracking = report.get("tracking") if isinstance(report, dict) else None
    tracking = tracking if isinstance(tracking, dict) else {}
    if tracking.get("status") != "tracked" or not SHA256_PATTERN.fullmatch(
        str(report_sha256).lower()
    ):
        return []
    detector = str(tracking.get("detector") or "unknown")
    regions: list[dict] = []
    for sample in tracking.get("series") or []:
        if not isinstance(sample, dict) or sample.get("status") != "tracked":
            continue
        face = sample.get("face")
        if not isinstance(face, dict):
            continue
        bbox = {
            "x": face.get("x"),
            "y": face.get("y"),
            "width": face.get("w"),
            "height": face.get("h"),
        }
        if not _valid_normalized_bbox(bbox):
            continue
        try:
            timestamp = float(sample["time"])
        except (KeyError, TypeError, ValueError):
            continue
        regions.append({
            "bbox": bbox,
            "timestamp_seconds": timestamp,
            "detector": detector,
            "evidence_path": str(report_path.resolve()),
            "evidence_sha256": str(report_sha256).lower(),
        })
    return regions


def build_adaptive_layout_constraints(
    evidence: dict, *, content_type: str, identity_mode: str,
) -> dict:
    """Build an evidence-bound layout contract, never inferred coordinates.

    The contract intentionally distinguishes screen recordings from portrait
    people footage. When required protected-region evidence is unavailable, it
    returns an auditable caption-only fallback instead of a guessed safe zone.
    """
    display = evidence.get("display") if isinstance(evidence, dict) else None
    protected = evidence.get("protected_regions") if isinstance(evidence, dict) else None
    display = display if isinstance(display, dict) else {}
    protected = protected if isinstance(protected, dict) else {}
    orientation = str(display.get("orientation") or "unknown")
    normalized_content_type = str(content_type or "").strip().lower()
    portrait_person = (
        orientation == "portrait"
        and normalized_content_type in PORTRAIT_PERSON_CONTENT_TYPES
    )
    layout_family = "portrait_person_safe" if portrait_person else "landscape_ui_safe"
    required_types = ("faces", "hands", "captions") if portrait_person else (
        "critical_ui", "captions",
    )
    regions: dict[str, list[dict]] = {}
    observations = protected.get("observations")
    observations = observations if isinstance(observations, dict) else {}
    invalid_types: list[str] = []
    for region_type in required_types:
        values = protected.get(region_type)
        values = values if isinstance(values, list) else []
        valid = [row for row in values if _valid_normalized_bbox(row.get("bbox") if isinstance(row, dict) else None)]
        regions[region_type] = valid
        if region_type in (("faces", "hands") if portrait_person else ("critical_ui",)) and not valid:
            observation = observations.get(region_type)
            hashes = observation.get("evidence_sha256") if isinstance(observation, dict) else None
            observed_absent = (
                isinstance(observation, dict)
                and observation.get("status") == "observed_absent"
                and isinstance(hashes, list)
                and bool(hashes)
                and all(
                    isinstance(value, str)
                    and SHA256_PATTERN.fullmatch(value.lower()) is not None
                    for value in hashes
                )
            )
            if not observed_absent:
                invalid_types.append(region_type)

    constraints = {
        "coordinate_space": "normalized_display_v1",
        "orientation": orientation,
        "display_width": display.get("width"),
        "display_height": display.get("height"),
        "rotation_degrees": display.get("rotation_degrees", 0),
        "protected_regions": regions,
        "protected_region_observations": observations,
        "placement_policy": (
            "preserve_faces_hands_and_caption_lane"
            if portrait_person else "preserve_critical_ui_and_caption_lane"
        ),
        "source_evidence_status": protected.get("status", "unknown"),
    }
    if invalid_types:
        return {
            "schema_version": "1.0.0",
            "layout_family": layout_family,
            "identity_mode": identity_mode,
            "content_type": content_type,
            "protected_region_types": list(required_types),
            "constraints": constraints,
            "status": "action_required",
            "fallback": "caption_only",
            "missing_evidence": invalid_types,
            "guessed_coordinates_allowed": False,
        }
    return {
        "schema_version": "1.0.0",
        "layout_family": layout_family,
        "identity_mode": identity_mode,
        "content_type": content_type,
        "protected_region_types": list(required_types),
        "constraints": constraints,
        "status": "resolved",
        "fallback": None,
        "missing_evidence": [],
        "guessed_coordinates_allowed": False,
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
