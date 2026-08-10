#!/usr/bin/env python3
"""Preservation-aware motion quality gate that rejects decorative density."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from director_contracts import (
    LOW_INFORMATION_ANCHORS,
    normalized_anchor,
    sha256_file,
    storyboard_semantic_event_id,
    validate_storyboard_semantic_binding,
)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finding(code: str, message: str, *, event_id: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"code": code, "severity": "blocking", "message": message}
    if event_id:
        row["event_id"] = event_id
    return row


def build_report(
    *, storyboard_path: Path, semantic_brief_path: Path, config: dict[str, Any],
    production_contract_path: Path | None = None,
) -> dict[str, Any]:
    storyboard_path = storyboard_path.resolve()
    semantic_brief_path = semantic_brief_path.resolve()
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    brief = json.loads(semantic_brief_path.read_text(encoding="utf-8"))
    production_contract = (
        json.loads(production_contract_path.resolve().read_text(encoding="utf-8"))
        if production_contract_path is not None else {}
    )
    promise_type = str(
        (production_contract.get("delivery_promise") or {}).get("type") or "unknown"
    )
    events = [row for row in (storyboard.get("events") or []) if isinstance(row, dict)]
    brief_events = {
        str(row.get("id") or "").strip(): row
        for row in (brief.get("events") or []) if isinstance(row, dict)
    }
    findings = [
        _finding("semantic_binding_mismatch", error)
        for error in validate_storyboard_semantic_binding(storyboard, brief)
    ]
    low_information = {normalized_anchor(value) for value in LOW_INFORMATION_ANCHORS}
    families: list[str] = []
    anchors: Counter[str] = Counter()
    intervals: list[tuple[float, float, bool]] = []

    for index, event in enumerate(events):
        event_id = str(event.get("id") or f"event-{index}")
        semantic = brief_events.get(storyboard_semantic_event_id(event)) or {}
        treatment = str(event.get("treatment") or "unknown")
        quiet = semantic.get("treatment") == "quiet_source"
        try:
            start = float(event.get(
                "output_start", event.get("start", semantic.get("output_start", 0.0)),
            ))
            end = float(event.get(
                "output_end", event.get("end", semantic.get("output_end", start)),
            ))
        except (TypeError, ValueError):
            findings.append(_finding("invalid_event_timing", "Event timing is not numeric.", event_id=event_id))
            start, end = 0.0, 0.0
        intervals.append((start, max(start, end), quiet))
        if quiet:
            if not semantic.get("source_activity_evidence"):
                findings.append(_finding(
                    "unsupported_quiet_source", "Quiet source interval lacks stored source-activity evidence.",
                    event_id=event_id,
                ))
            continue

        visual = event.get("visual_structure") or {}
        family = str(visual.get("layout_archetype") or treatment or "unknown")
        families.append(family)
        anchor = normalized_anchor(str(semantic.get("anchor") or ""))
        if anchor:
            anchors[anchor] += 1
        if not anchor or anchor in low_information:
            findings.append(_finding(
                "low_information_anchor",
                f"Anchor {semantic.get('anchor', '')!r} cannot justify a visual event.",
                event_id=event_id,
            ))
        takeaway = str(semantic.get("viewer_takeaway") or "").strip()
        rationale = str(semantic.get("relevance_rationale") or "").strip()
        mechanism = str(semantic.get("visual_mechanism") or "").strip()
        if not takeaway or not rationale or not mechanism:
            findings.append(_finding(
                "missing_explanatory_value",
                "Visual event requires a viewer takeaway, relevance rationale, and visual mechanism.",
                event_id=event_id,
            ))
        quote = normalized_anchor(str(semantic.get("transcript_quote") or ""))
        if anchor and quote and anchor == quote and len(anchor) > 12:
            findings.append(_finding(
                "subtitle_restatement", "Visual anchor repeats the full subtitle instead of explaining it.",
                event_id=event_id,
            ))
        motion = semantic.get("motion") or {}
        missing_phases = [phase for phase in ("entrance", "reveal", "hold", "exit") if not motion.get(phase)]
        if missing_phases:
            findings.append(_finding(
                "incomplete_motion_intent",
                "Motion intent is missing phases: " + ", ".join(missing_phases),
                event_id=event_id,
            ))
        geometry = event.get("geometry_contract") or {}
        density = geometry.get("useful_content_ratio")
        if density is not None:
            try:
                density_value = float(density)
            except (TypeError, ValueError):
                density_value = 0.0
            if (
                density_value < float(config.get("minimum_useful_content_ratio", 0.2))
                and geometry.get("intentional_quiet_zone") is not True
            ):
                findings.append(_finding(
                    "low_useful_content_density",
                    "Useful content occupies too little of the declared surface without an intentional quiet zone.",
                    event_id=event_id,
                ))
        connector = geometry.get("connector_contract") or {}
        if connector:
            relations = connector.get("relations") or []
            try:
                required_count = int(connector.get("required_connector_count", -1))
            except (TypeError, ValueError):
                required_count = -1
            if required_count < 1 or len(relations) != required_count:
                findings.append(_finding(
                    "connector_semantics_incomplete",
                    "Connector contract count does not match its declared semantic relations.",
                    event_id=event_id,
                ))

    if len(families) >= 4:
        family, count = Counter(families).most_common(1)[0]
        ratio = count / len(families)
        if ratio > float(config.get("maximum_family_ratio", 0.65)):
            findings.append(_finding(
                "visual_family_repetition",
                f"Visual family {family!r} dominates {count}/{len(families)} non-quiet events.",
            ))
    for anchor, count in anchors.items():
        if count > 2:
            findings.append(_finding(
                "anchor_repetition", f"Anchor {anchor!r} is reused {count} times.",
            ))

    duration = float((storyboard.get("composition") or {}).get("duration") or 0.0)
    configured_max_gap = float(config.get("maximum_unexplained_gap_seconds", 30.0))
    promise_gap_ceiling = {
        "screen_demo": 18.0,
        "hybrid": 20.0,
        "teacher_explainer": 22.0,
        "talking_head": 24.0,
    }.get(promise_type, configured_max_gap)
    max_gap = min(configured_max_gap, promise_gap_ceiling)
    ordered = sorted(intervals)
    cursor = 0.0
    for start, end, quiet in ordered:
        if start - cursor > max_gap:
            findings.append(_finding(
                "unexplained_visual_stagnation",
                f"No event or evidenced quiet-source interval explains {start - cursor:.2f}s of the timeline.",
            ))
        cursor = max(cursor, end)
    if duration > 0 and duration - cursor > max_gap:
        findings.append(_finding(
            "unexplained_visual_stagnation",
            f"The final {duration - cursor:.2f}s lacks an event or evidenced quiet-source interval.",
        ))

    implementation = Path(__file__).resolve()
    inputs = {
        "storyboard": {"path": str(storyboard_path), "sha256": sha256_file(storyboard_path)},
        "semantic_brief": {
            "path": str(semantic_brief_path), "sha256": sha256_file(semantic_brief_path),
        },
    }
    if production_contract_path is not None:
        production_contract_path = production_contract_path.resolve()
        inputs["production_contract"] = {
            "path": str(production_contract_path),
            "sha256": sha256_file(production_contract_path),
        }
    report = {
        "schema_version": 1,
        "status": "failed" if findings else "pass",
        "inputs": inputs,
        "config": dict(config),
        "config_sha256": _stable_hash(config),
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "metrics": {
            "event_count": len(events),
            "nonquiet_event_count": len(families),
            "distinct_visual_families": len(set(families)),
            "event_count_is_not_a_quality_score": True,
            "delivery_promise_type": promise_type,
            "effective_maximum_unexplained_gap_seconds": max_gap,
        },
        "delegated_existing_gates": [
            "geometry", "overflow", "caption_occlusion", "face_cursor_ui_safety",
            "preview_render_parity",
        ],
        "findings": findings,
    }
    report["integrity_sha256"] = _stable_hash(report)
    return report


def validate_report(
    report: dict[str, Any], storyboard_path: Path, semantic_brief_path: Path,
    *, config: dict[str, Any] | None = None,
    production_contract_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("visual dynamics report schema_version must be 1")
    for name, path in (
        ("storyboard", storyboard_path.resolve()),
        ("semantic_brief", semantic_brief_path.resolve()),
    ):
        row = (report.get("inputs") or {}).get(name) or {}
        if row.get("path") != str(path):
            errors.append(f"visual dynamics {name} path is stale")
        if not path.is_file() or row.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append(f"visual dynamics {name} hash is stale")
    if production_contract_path is not None:
        path = production_contract_path.resolve()
        row = (report.get("inputs") or {}).get("production_contract") or {}
        if row.get("path") != str(path):
            errors.append("visual dynamics production_contract path is stale")
        if not path.is_file() or row.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append("visual dynamics production_contract hash is stale")
    if config is not None and (
        report.get("config") != config or report.get("config_sha256") != _stable_hash(config)
    ):
        errors.append("visual dynamics configuration binding is stale")
    if report.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in report.items() if key != "integrity_sha256"}
    ):
        errors.append("visual dynamics integrity hash is stale")
    implementation = report.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if (
        path.resolve() != Path(__file__).resolve()
        or not path.is_file()
        or implementation.get("sha256") != sha256_file(path)
    ):
        errors.append("visual dynamics implementation binding is stale")
    findings = report.get("findings")
    if not isinstance(findings, list):
        errors.append("visual dynamics findings must be a list")
        findings = []
    expected_status = "failed" if findings else "pass"
    if report.get("status") != expected_status:
        errors.append("visual dynamics status does not match blocking findings")
    if (report.get("metrics") or {}).get("event_count_is_not_a_quality_score") is not True:
        errors.append("visual dynamics report must not use event count as a quality score")
    return errors
