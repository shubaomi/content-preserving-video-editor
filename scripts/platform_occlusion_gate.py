#!/usr/bin/env python3
"""Blocking geometry gate for platform UI, protected regions, crop, and caption overlap."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from detect_platform_occlusion import analyze, area, overlap
from director_contracts import read_json, write_json


SOFT_PRODUCT_FOCUS_REGION_KINDS = {"face", "hand", "hands"}


def _region_kind(region: dict[str, Any]) -> str:
    value = str(region.get("kind") or region.get("id") or "").strip().lower()
    if value.startswith("hand"):
        return "hands"
    if value.startswith("caption"):
        return "captions"
    if value.startswith("product"):
        return "product"
    if value.startswith("face"):
        return "face"
    return value


def _rectangle_valid(row: Any) -> bool:
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
        return False
    values: list[float] = []
    for key in ("x0", "y0", "x1", "y1"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        number = float(value)
        if not math.isfinite(number) or not 0 <= number <= 1:
            return False
        values.append(number)
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0:
        return False
    for key in ("z", "opacity"):
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        number = float(value)
        if not math.isfinite(number):
            return False
        if key == "opacity" and not 0 <= number <= 1:
            return False
    return True


def _rectangle_gap(first: dict[str, Any], second: dict[str, Any]) -> float:
    horizontal = max(
        0.0,
        float(second.get("x0", 0)) - float(first.get("x1", 0)),
        float(first.get("x0", 0)) - float(second.get("x1", 0)),
    )
    vertical = max(
        0.0,
        float(second.get("y0", 0)) - float(first.get("y1", 0)),
        float(first.get("y0", 0)) - float(second.get("y1", 0)),
    )
    return (horizontal ** 2 + vertical ** 2) ** 0.5


def _soft_occlusion_errors(
    event: dict[str, Any], element: dict[str, Any], protected: dict[str, Any], ratio: float,
    *, semantic_events: dict[str, dict[str, Any]], storyboard_events: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    focus = event.get("semantic_focus")
    policy = event.get("occlusion_policy")
    if not isinstance(focus, dict) or not isinstance(policy, dict):
        return []
    if policy.get("mode") != "semantic_priority" or policy.get("intent") != "product_emphasis":
        return []
    findings: list[dict[str, Any]] = []
    evidence_event_id = str(focus.get("evidence_event_id") or "").strip()
    event_id = str(event.get("event_id") or "").strip()
    semantic = semantic_events.get(evidence_event_id)
    storyboard = storyboard_events.get(event_id)
    semantic_focus = semantic.get("occlusion_focus") if isinstance(semantic, dict) else None
    authority_ready = (
        focus.get("primary") == "product"
        and focus.get("status") == "approved"
        and isinstance(semantic, dict)
        and semantic.get("decision") == "render"
        and isinstance(semantic_focus, dict)
        and semantic_focus.get("primary") == "product"
        and semantic_focus.get("status") == "approved"
        and isinstance(storyboard, dict)
        and storyboard.get("semantic_event_id") == evidence_event_id
    )
    if not authority_ready:
        findings.append({"code": "soft_occlusion_authority_missing", "severity": "error"})
    maximum_ratio = policy.get("maximum_soft_overlap_ratio")
    if (
        isinstance(maximum_ratio, bool) or not isinstance(maximum_ratio, (int, float))
        or not math.isfinite(float(maximum_ratio)) or not 0.05 <= float(maximum_ratio) <= 0.2
    ):
        findings.append({"code": "soft_occlusion_ratio_policy_invalid", "severity": "error"})
    elif ratio > float(maximum_ratio):
        findings.append({"code": "soft_occlusion_overlap_exceeded", "severity": "error"})
    semantic_start = semantic.get("output_start") if isinstance(semantic, dict) else None
    semantic_end = semantic.get("output_end") if isinstance(semantic, dict) else None
    storyboard_start = storyboard.get("output_start") if isinstance(storyboard, dict) else None
    storyboard_end = storyboard.get("output_end") if isinstance(storyboard, dict) else None
    maximum_duration = policy.get("maximum_soft_occlusion_seconds")
    if (
        any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (
            semantic_start, semantic_end, storyboard_start, storyboard_end, maximum_duration,
        ))
        or any(not math.isfinite(float(value)) for value in (
            semantic_start, semantic_end, storyboard_start, storyboard_end, maximum_duration,
        ))
        or float(semantic_end) <= float(semantic_start)
        or abs(float(semantic_start) - float(storyboard_start)) > 0.001
        or abs(float(semantic_end) - float(storyboard_end)) > 0.001
        or not 0.3 <= float(maximum_duration) <= 1.5
        or float(semantic_end) - float(semantic_start) > float(maximum_duration)
    ):
        findings.append({"code": "soft_occlusion_duration_exceeded", "severity": "error"})
    phases = event.get("phases")
    post_exit = phases.get("post_exit") if isinstance(phases, dict) else None
    post_elements = post_exit.get("elements") if isinstance(post_exit, dict) else None
    actual_clean_exit = (
        isinstance(post_elements, list)
        and all(_rectangle_valid(row) for row in post_elements)
        and all(
            overlap(post_element, protected_zone)
            / max(area(post_element), 1e-9) <= 0.05
            for post_element in post_elements
            for protected_zone in event.get("protected_zones") or []
            if isinstance(protected_zone, dict) and _rectangle_valid(protected_zone)
        )
    )
    if not actual_clean_exit:
        findings.append({"code": "soft_occlusion_clean_exit_missing", "severity": "error"})
    target_id = str(element.get("target_region_id") or "")
    targets = [row for row in event.get("protected_zones") or []
               if isinstance(row, dict) and _rectangle_valid(row)
               and str(row.get("id") or "") == target_id and _region_kind(row) == "product"]
    maximum_gap = policy.get("maximum_product_gap")
    if (
        not targets
        or isinstance(maximum_gap, bool)
        or not isinstance(maximum_gap, (int, float))
        or not math.isfinite(float(maximum_gap)) or not 0 <= float(maximum_gap) <= 0.15
        or _rectangle_gap(element, targets[0]) > float(maximum_gap)
    ):
        findings.append({"code": "soft_occlusion_product_proximity_missing", "severity": "error"})
    return findings


def _canonical_sha256(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _event_inventory(payload: Any, *, storyboard: bool = False) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        return {}
    inventory: dict[str, dict[str, Any]] = {}
    for row in payload["events"]:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("id") or "").strip()
        if storyboard and not event_id:
            event_id = str(row.get("event_id") or "").strip()
        if event_id and event_id not in inventory:
            inventory[event_id] = row
    return inventory


def _authority_inventory_errors(
    semantic_brief: Any, storyboard: Any, raw_geometry_events: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Validate the complete semantic -> Storyboard -> geometry event inventory."""
    errors: list[dict[str, Any]] = []
    if not isinstance(semantic_brief, dict) or not isinstance(semantic_brief.get("events"), list):
        return {}, {}, [{"code": "semantic_authority_invalid", "severity": "error"}]
    if not isinstance(storyboard, dict) or not isinstance(storyboard.get("events"), list):
        return {}, {}, [{"code": "storyboard_authority_invalid", "severity": "error"}]

    def collect(payload: dict[str, Any], *, storyboard_rows: bool) -> tuple[dict[str, dict[str, Any]], list[str]]:
        inventory: dict[str, dict[str, Any]] = {}
        ordered: list[str] = []
        for row in payload["events"]:
            if not isinstance(row, dict):
                errors.append({"code": "storyboard_authority_invalid" if storyboard_rows
                               else "semantic_authority_invalid", "severity": "error"})
                continue
            event_id = row.get("id")
            if not isinstance(event_id, str) or not event_id.strip() or event_id.strip() in inventory:
                errors.append({"code": "storyboard_event_id_invalid" if storyboard_rows
                               else "semantic_event_id_invalid", "severity": "error"})
                continue
            event_id = event_id.strip()
            inventory[event_id] = row
            ordered.append(event_id)
        return inventory, ordered

    semantic_events, _ = collect(semantic_brief, storyboard_rows=False)
    storyboard_events, storyboard_ids = collect(storyboard, storyboard_rows=True)
    semantic_render_ids = [
        event_id for event_id, row in semantic_events.items() if row.get("decision") == "render"
    ]
    storyboard_semantic_ids: list[str] = []
    for event_id, row in storyboard_events.items():
        semantic_id = row.get("semantic_event_id")
        if not isinstance(semantic_id, str) or semantic_id not in semantic_events:
            errors.append({"code": "storyboard_semantic_binding_invalid", "event_id": event_id,
                           "severity": "error"})
        else:
            storyboard_semantic_ids.append(semantic_id)
    if (
        len(set(storyboard_semantic_ids)) != len(storyboard_semantic_ids)
        or storyboard_semantic_ids != semantic_render_ids
    ):
        errors.append({
            "code": "storyboard_render_inventory_mismatch", "severity": "error",
            "expected_semantic_event_ids": semantic_render_ids,
            "observed_semantic_event_ids": storyboard_semantic_ids,
        })

    geometry_ids: list[str] = []
    if not isinstance(raw_geometry_events, list):
        errors.append({"code": "geometry_event_inventory_mismatch", "severity": "error"})
    else:
        seen: set[str] = set()
        for row in raw_geometry_events:
            if not isinstance(row, dict):
                continue
            event_id = row.get("event_id")
            if not isinstance(event_id, str) or not event_id.strip() or event_id.strip() in seen:
                errors.append({"code": "geometry_event_id_invalid", "severity": "error"})
                continue
            event_id = event_id.strip()
            seen.add(event_id)
            geometry_ids.append(event_id)
    if geometry_ids != storyboard_ids:
        errors.append({
            "code": "geometry_event_inventory_mismatch", "severity": "error",
            "expected_event_ids": storyboard_ids, "observed_event_ids": geometry_ids,
        })
    return semantic_events, storyboard_events, errors


def evaluate_geometry(
    report: dict[str, Any], templates: dict[str, Any],
    semantic_brief: dict[str, Any] | None = None,
    storyboard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"schema_version": 1, "orientation": "", "template_version": None,
                "template_verified_on": None, "event_count": 0, "platforms": {},
                "findings": [{"code": "geometry_report_invalid", "severity": "error"}],
                "passed": False}
    if not isinstance(templates, dict):
        templates = {}
    orientation = str(report.get("orientation") or "")
    findings: list[dict[str, Any]] = []
    raw_events = report.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    semantic_events = _event_inventory(semantic_brief)
    storyboard_events = _event_inventory(storyboard, storyboard=True)
    if semantic_brief is not None or storyboard is not None:
        semantic_events, storyboard_events, authority_errors = _authority_inventory_errors(
            semantic_brief, storyboard, raw_events,
        )
        findings.extend(authority_errors)
    if orientation not in {"portrait", "landscape"}:
        findings.append({"code": "orientation_missing", "severity": "error"})
    if not events:
        findings.append({"code": "geometry_evidence_missing", "severity": "error"})
    by_platform: dict[str, Any] = {}
    template_inventory = templates.get("templates")
    if not isinstance(template_inventory, dict):
        template_inventory = {}
        findings.append({"code": "platform_template_invalid", "severity": "error"})
    for platform in ("douyin", "wechat_channels"):
        platform_findings: list[dict[str, Any]] = []
        platform_templates = template_inventory.get(platform)
        if not isinstance(platform_templates, dict):
            platform_findings.append({"code": "platform_template_invalid", "platform": platform,
                                      "severity": "error"})
            zones = []
        else:
            zones = platform_templates.get(orientation)
        if zones is None:
            platform_findings.append({"code": "platform_template_missing", "platform": platform,
                                      "severity": "error"})
            zones = []
        elif not isinstance(zones, list):
            platform_findings.append({"code": "platform_template_invalid", "platform": platform,
                                      "severity": "error"})
            zones = []
        else:
            valid_zones = [row for row in zones if _rectangle_valid(row)]
            if len(valid_zones) != len(zones):
                platform_findings.append({"code": "platform_template_invalid", "platform": platform,
                                          "severity": "error"})
            zones = valid_zones
        for event in events:
            if not isinstance(event, dict):
                platform_findings.append({"code": "geometry_event_invalid", "platform": platform,
                                          "severity": "error"})
                continue
            if type(event.get("cropped")) is not bool or type(event.get("caption_occluded")) is not bool:
                platform_findings.append({"code": "geometry_event_invalid", "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
            raw_elements = event.get("elements")
            raw_protected = event.get("protected_zones")
            if raw_elements is None:
                raw_elements = []
            if raw_protected is None:
                raw_protected = []
            if not isinstance(raw_elements, list) or not isinstance(raw_protected, list):
                platform_findings.append({"code": "geometry_event_invalid", "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
                continue
            elements = [row for row in raw_elements if _rectangle_valid(row)]
            protected_zones = [row for row in raw_protected if _rectangle_valid(row)]
            for _ in range(len(raw_elements) - len(elements)):
                platform_findings.append({"code": "geometry_element_invalid", "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
            for _ in range(len(raw_protected) - len(protected_zones)):
                platform_findings.append({"code": "protected_region_invalid", "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
            element_ids = [str(row["id"]) for row in elements]
            if len(set(element_ids)) != len(element_ids):
                platform_findings.append({
                    "code": "geometry_element_id_duplicate", "platform": platform,
                    "event_id": event.get("event_id"), "severity": "error",
                })
            protected_ids = [str(row["id"]) for row in protected_zones]
            if len(set(protected_ids)) != len(protected_ids):
                platform_findings.append({
                    "code": "protected_region_id_duplicate", "platform": platform,
                    "event_id": event.get("event_id"), "severity": "error",
                })
            phases = event.get("phases")
            post_exit = phases.get("post_exit") if isinstance(phases, dict) else None
            post_elements = post_exit.get("elements") if isinstance(post_exit, dict) else None
            if post_elements is not None:
                if not isinstance(post_elements, list) or any(
                    not _rectangle_valid(row) for row in post_elements
                ):
                    platform_findings.append({
                        "code": "post_exit_geometry_invalid", "platform": platform,
                        "event_id": event.get("event_id"), "severity": "error",
                    })
                else:
                    post_ids = [str(row["id"]) for row in post_elements]
                    if len(set(post_ids)) != len(post_ids):
                        platform_findings.append({
                            "code": "post_exit_element_id_duplicate", "platform": platform,
                            "event_id": event.get("event_id"), "severity": "error",
                        })
            for row in analyze(elements, zones):
                platform_findings.append({**row, "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
            event_soft_regions: set[str] = set()
            for element in elements:
                for protected in protected_zones:
                    ratio = overlap(element, protected) / max(area(element), 1e-9)
                    if ratio > 0.05:
                        kind = _region_kind(protected)
                        if kind in SOFT_PRODUCT_FOCUS_REGION_KINDS:
                            soft_errors = _soft_occlusion_errors(
                                event, element, protected, ratio,
                                semantic_events=semantic_events,
                                storyboard_events=storyboard_events,
                            )
                            policy = event.get("occlusion_policy") or {}
                            focus = event.get("semantic_focus") or {}
                            semantic_product_mode = (
                                isinstance(policy, dict)
                                and isinstance(focus, dict)
                                and policy.get("mode") == "semantic_priority"
                                and policy.get("intent") == "product_emphasis"
                            )
                            if semantic_product_mode:
                                event_soft_regions.add(str(protected.get("id") or ""))
                                for finding in soft_errors:
                                    platform_findings.append({
                                        **finding, "platform": platform,
                                        "event_id": event.get("event_id"),
                                        "element": element.get("id"),
                                        "protected_region": protected.get("id"),
                                        "overlap_ratio": round(ratio, 4),
                                    })
                                if not soft_errors:
                                    continue
                        platform_findings.append({
                            "code": "protected_region_collision", "platform": platform,
                            "event_id": event.get("event_id"), "element": element.get("id"),
                            "protected_region": protected.get("id"),
                            "overlap_ratio": round(ratio, 4), "severity": "error",
                        })
            if len(event_soft_regions) > 1:
                platform_findings.append({
                    "code": "soft_occlusion_multiple_regions", "platform": platform,
                    "event_id": event.get("event_id"),
                    "protected_region_ids": sorted(event_soft_regions), "severity": "error",
                })
            if event.get("cropped") is True:
                platform_findings.append({"code": "element_cropped", "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
            if event.get("caption_occluded") is True:
                platform_findings.append({"code": "caption_occlusion", "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
        by_platform[platform] = {"finding_count": len(platform_findings),
                                 "passed": not platform_findings}
        findings.extend(platform_findings)
    return {
        "schema_version": 1, "orientation": orientation,
        "template_version": templates.get("template_version"),
        "template_verified_on": templates.get("verified_on"),
        "semantic_authority": {
            "semantic_brief_sha256": _canonical_sha256(semantic_brief),
            "storyboard_sha256": _canonical_sha256(storyboard),
        },
        "event_count": len(events), "platforms": by_platform,
        "findings": findings, "passed": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", required=True)
    parser.add_argument("--templates", default=str(Path(__file__).parents[1] / "references" /
                                                     "platform-ui-templates.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--semantic-brief")
    parser.add_argument("--storyboard")
    args = parser.parse_args()
    result = evaluate_geometry(
        read_json(Path(args.geometry)), read_json(Path(args.templates)),
        read_json(Path(args.semantic_brief)) if args.semantic_brief else None,
        read_json(Path(args.storyboard)) if args.storyboard else None,
    )
    write_json(Path(args.out), result)
    print(Path(args.out).resolve())
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
