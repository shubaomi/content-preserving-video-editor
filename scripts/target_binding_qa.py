#!/usr/bin/env python3
"""Replayable geometry QA for stateful target bindings."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file
from target_binding import validate_binding


REQUIRED_PHASES = ("entrance", "mid_hold", "pre_exit", "post_exit")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _bbox_error(left: Any, right: Any) -> float | None:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None
    values: list[float] = []
    for field in ("x", "y", "width", "height"):
        a = _number(left.get(field))
        b = _number(right.get(field))
        if a is None or b is None:
            return None
        values.append(abs(a - b))
    return max(values)


def _point_error(left: Any, right: Any) -> float | None:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None
    lx = _number(left.get("x"))
    ly = _number(left.get("y"))
    rx = _number(right.get("x"))
    ry = _number(right.get("y"))
    if None in (lx, ly, rx, ry):
        return None
    return math.hypot(lx - rx, ly - ry)


def _window(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    start = _number(value.get("start_seconds"))
    end = _number(value.get("end_seconds"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _source_time(binding: dict[str, Any], output_time: float) -> float | None:
    source = _window(binding.get("source_window"))
    output = _window(binding.get("output_window"))
    if source is None or output is None:
        return None
    ratio = (output_time - output[0]) / (output[1] - output[0])
    return source[0] + ratio * (source[1] - source[0])


def _interpolate_bbox(
    left: dict[str, Any], right: dict[str, Any], timestamp: float,
) -> dict[str, float] | None:
    left_bbox = left.get("bbox")
    right_bbox = right.get("bbox")
    left_time = _number(left.get("timestamp_seconds"))
    right_time = _number(right.get("timestamp_seconds"))
    if (
        not isinstance(left_bbox, dict) or not isinstance(right_bbox, dict)
        or left_time is None or right_time is None
    ):
        return None
    span = right_time - left_time
    ratio = 0.0 if span <= 0 else min(1.0, max(0.0, (timestamp - left_time) / span))
    result: dict[str, float] = {}
    for field in ("x", "y", "width", "height"):
        start = _number(left_bbox.get(field))
        end = _number(right_bbox.get(field))
        if start is None or end is None:
            return None
        result[field] = start + (end - start) * ratio
    return result


def _expected_target_boxes(
    binding: dict[str, Any], output_time: float,
) -> dict[str, dict[str, float]]:
    source_time = _source_time(binding, output_time)
    if source_time is None:
        return {}
    result: dict[str, dict[str, float]] = {}
    for target_id in binding.get("target_ids") or []:
        rows = sorted(
            (
                row for row in (binding.get("observations") or [])
                if isinstance(row, dict) and row.get("target_id") == target_id
                and row.get("visible") is True and isinstance(row.get("bbox"), dict)
            ),
            key=lambda row: float(row["timestamp_seconds"]),
        )
        if not rows:
            continue
        before = [row for row in rows if float(row["timestamp_seconds"]) <= source_time]
        after = [row for row in rows if float(row["timestamp_seconds"]) >= source_time]
        left = before[-1] if before else rows[0]
        right = after[0] if after else rows[-1]
        if left.get("source_state_sha256") != right.get("source_state_sha256"):
            nearest = min(rows, key=lambda row: abs(float(row["timestamp_seconds"]) - source_time))
            box = _interpolate_bbox(nearest, nearest, source_time)
        else:
            box = _interpolate_bbox(left, right, source_time)
        if box is not None:
            result[str(target_id)] = box
    return result


def _attachment(box: dict[str, float], edge: str) -> dict[str, float] | None:
    x, y, width, height = (box[field] for field in ("x", "y", "width", "height"))
    if edge == "left":
        return {"x": x, "y": y + height / 2}
    if edge == "right":
        return {"x": x + width, "y": y + height / 2}
    if edge == "top":
        return {"x": x + width / 2, "y": y}
    if edge == "bottom":
        return {"x": x + width / 2, "y": y + height}
    return None


def build_report(
    *, binding_path: Path, phase_observations: list[dict[str, Any]],
    endpoint_tolerance: float, bbox_tolerance: float,
) -> dict[str, Any]:
    """Build a deterministic four-phase report from renderer observations."""
    binding_path = binding_path.resolve()
    binding = read_json(binding_path)
    findings: list[dict[str, str]] = []
    binding_errors = validate_binding(binding, require_resolved=True)
    findings.extend(
        {"code": "target_binding_invalid", "phase": "contract", "message": error}
        for error in binding_errors
    )
    phases = [row.get("phase") for row in phase_observations if isinstance(row, dict)]
    if phases != list(REQUIRED_PHASES):
        findings.append({
            "code": "phase_order_invalid", "phase": "contract",
            "message": f"expected {list(REQUIRED_PHASES)}, got {phases}",
        })

    declared_targets = set(binding.get("target_ids") or [])
    output_window = _window(binding.get("output_window"))
    for observation in phase_observations:
        if not isinstance(observation, dict):
            findings.append({
                "code": "phase_observation_invalid", "phase": "unknown",
                "message": "phase observation must be an object",
            })
            continue
        phase = str(observation.get("phase") or "unknown")
        timestamp = _number(observation.get("timestamp_seconds"))
        if timestamp is None:
            findings.append({
                "code": "phase_timestamp_invalid", "phase": phase,
                "message": "phase timestamp must be finite",
            })
            expected_boxes: dict[str, dict[str, float]] = {}
        else:
            expected_boxes = _expected_target_boxes(binding, timestamp)
            if output_window is not None:
                if phase == "post_exit" and timestamp < output_window[1]:
                    findings.append({
                        "code": "post_exit_too_early", "phase": phase,
                        "message": "post-exit evidence precedes the output-window end",
                    })
                if phase != "post_exit" and not output_window[0] <= timestamp <= output_window[1]:
                    findings.append({
                        "code": "active_phase_outside_window", "phase": phase,
                        "message": "active phase is outside the output window",
                    })
        target_rows = observation.get("targets")
        target_rows = target_rows if isinstance(target_rows, list) else []
        visible_ids: set[str] = set()
        for target in target_rows:
            if not isinstance(target, dict):
                findings.append({
                    "code": "target_observation_invalid", "phase": phase,
                    "message": "target observation must be an object",
                })
                continue
            target_id = str(target.get("target_id") or "")
            if target_id not in declared_targets:
                findings.append({
                    "code": "target_id_unknown", "phase": phase,
                    "message": f"undeclared target {target_id}",
                })
            if target.get("visible") is True:
                visible_ids.add(target_id)
                expected = expected_boxes.get(target_id)
                error = _bbox_error(expected, target.get("overlay_bbox"))
                if error is None or error > bbox_tolerance:
                    findings.append({
                        "code": "target_bbox_mismatch", "phase": phase,
                        "message": f"{target_id} bbox error {error!r} exceeds {bbox_tolerance}",
                    })
                for flag in ("clipped", "offscreen", "caption_collision"):
                    if target.get(flag) is True:
                        findings.append({
                            "code": f"target_{flag}", "phase": phase,
                            "message": f"{target_id} is {flag.replace('_', ' ')}",
                        })
        if phase == "post_exit":
            if visible_ids or observation.get("connectors"):
                findings.append({
                    "code": "post_exit_visibility", "phase": phase,
                    "message": "targets and connectors must be absent after exit",
                })
        elif visible_ids != declared_targets:
            findings.append({
                "code": "target_phase_coverage", "phase": phase,
                "message": "all bound targets must be observed during active phases",
            })

        connectors = observation.get("connectors")
        connectors = connectors if isinstance(connectors, list) else []
        for connector in connectors:
            if not isinstance(connector, dict):
                findings.append({
                    "code": "connector_observation_invalid", "phase": phase,
                    "message": "connector observation must be an object",
                })
                continue
            for side in ("from", "to"):
                edge_value = str(connector.get("attachment_edge") or "")
                edges = edge_value.split("-to-", 1)
                target_id = str(connector.get(f"{side}_target_id") or "")
                edge = edges[0] if side == "from" and len(edges) == 2 else (
                    edges[1] if side == "to" and len(edges) == 2 else ""
                )
                expected_attachment = _attachment(expected_boxes[target_id], edge) \
                    if target_id in expected_boxes else None
                error = _point_error(
                    connector.get(f"{side}_endpoint"),
                    expected_attachment,
                )
                if error is None or error > endpoint_tolerance:
                    findings.append({
                        "code": "connector_endpoint_mismatch", "phase": phase,
                        "message": f"{side} endpoint error {error!r} exceeds {endpoint_tolerance}",
                    })

    return {
        "schema_version": "1.0.0",
        "report_type": "target_binding_geometry_v1",
        "binding": {"path": str(binding_path), "sha256": sha256_file(binding_path)},
        "tolerances": {
            "endpoint_normalized": endpoint_tolerance,
            "bbox_component_normalized": bbox_tolerance,
        },
        "phase_observations": phase_observations,
        "findings": findings,
        "status": "pass" if not findings else "failed",
    }


def validate_report(report: dict[str, Any], binding_path: Path) -> list[str]:
    """Validate the report remains hash-bound and cannot self-declare pass."""
    errors: list[str] = []
    binding_path = binding_path.resolve()
    binding_record = report.get("binding") if isinstance(report, dict) else None
    if not isinstance(binding_record, dict):
        return ["target-binding QA report lacks binding evidence"]
    if Path(str(binding_record.get("path") or "")).resolve() != binding_path:
        errors.append("target-binding QA report references the wrong binding path")
    if not binding_path.is_file():
        errors.append("target-binding QA binding file is missing")
    elif binding_record.get("sha256") != sha256_file(binding_path):
        errors.append("target-binding QA binding hash is stale")
    findings = report.get("findings")
    if not isinstance(findings, list):
        errors.append("target-binding QA findings must be a list")
    expected_status = "pass" if isinstance(findings, list) and not findings else "failed"
    if report.get("status") != expected_status:
        errors.append("target-binding QA status does not match findings")
    if report.get("status") != "pass":
        errors.append("target-binding QA did not pass")
    if [row.get("phase") for row in report.get("phase_observations") or []] != list(REQUIRED_PHASES):
        errors.append("target-binding QA lacks the exact four review phases")
    tolerances = report.get("tolerances") if isinstance(report, dict) else None
    if isinstance(tolerances, dict) and binding_path.is_file():
        endpoint = _number(tolerances.get("endpoint_normalized"))
        bbox = _number(tolerances.get("bbox_component_normalized"))
        if endpoint is None or endpoint < 0 or bbox is None or bbox < 0:
            errors.append("target-binding QA tolerances are invalid")
        else:
            recomputed = build_report(
                binding_path=binding_path,
                phase_observations=report.get("phase_observations") or [],
                endpoint_tolerance=endpoint,
                bbox_tolerance=bbox,
            )
            if report.get("findings") != recomputed.get("findings"):
                errors.append("target-binding QA findings do not match recomputed geometry")
            if report.get("status") != recomputed.get("status"):
                errors.append("target-binding QA status does not match recomputed geometry")
    else:
        errors.append("target-binding QA tolerances are missing")
    return errors
