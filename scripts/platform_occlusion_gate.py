#!/usr/bin/env python3
"""Blocking geometry gate for platform UI, protected regions, crop, and caption overlap."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from detect_platform_occlusion import analyze, area, overlap
from director_contracts import read_json, write_json


def evaluate_geometry(report: dict[str, Any], templates: dict[str, Any]) -> dict[str, Any]:
    orientation = str(report.get("orientation") or "")
    findings: list[dict[str, Any]] = []
    events = report.get("events") or []
    if orientation not in {"portrait", "landscape"}:
        findings.append({"code": "orientation_missing", "severity": "error"})
    if not events:
        findings.append({"code": "geometry_evidence_missing", "severity": "error"})
    by_platform: dict[str, Any] = {}
    for platform in ("douyin", "wechat_channels"):
        zones = ((templates.get("templates") or {}).get(platform) or {}).get(orientation)
        platform_findings: list[dict[str, Any]] = []
        if zones is None:
            platform_findings.append({"code": "platform_template_missing", "platform": platform,
                                      "severity": "error"})
            zones = []
        for event in events:
            elements = event.get("elements") or []
            for row in analyze(elements, zones):
                platform_findings.append({**row, "platform": platform,
                                          "event_id": event.get("event_id"), "severity": "error"})
            for element in elements:
                for protected in event.get("protected_zones") or []:
                    ratio = overlap(element, protected) / max(area(element), 1e-9)
                    if ratio > 0.05:
                        platform_findings.append({
                            "code": "protected_region_collision", "platform": platform,
                            "event_id": event.get("event_id"), "element": element.get("id"),
                            "protected_region": protected.get("id"),
                            "overlap_ratio": round(ratio, 4), "severity": "error",
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
        "event_count": len(events), "platforms": by_platform,
        "findings": findings, "passed": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", required=True)
    parser.add_argument("--templates", default=str(Path(__file__).parents[1] / "references" /
                                                     "platform-ui-templates.json"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = evaluate_geometry(read_json(Path(args.geometry)), read_json(Path(args.templates)))
    write_json(Path(args.out), result)
    print(Path(args.out).resolve())
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
