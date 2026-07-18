#!/usr/bin/env python3
"""Validate Studio/snapshot and representative render parity at matching times."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from director_contracts import read_json, write_json


def _number(value: Any, default: float = float("inf")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate(
    report: dict[str, Any],
    storyboard: dict[str, Any],
    *,
    configured_tolerances: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("preview/render parity schema_version must be 1")
    if report.get("status") != "pass":
        errors.append("preview/render parity status must be pass")
    tolerances = report.get("tolerances") or {}
    position_tolerance = _number(tolerances.get("position_px"), -1)
    size_tolerance = _number(tolerances.get("size_px"), -1)
    time_tolerance = _number(tolerances.get("time_seconds"), -1)
    if min(position_tolerance, size_tolerance, time_tolerance) < 0:
        errors.append("preview/render parity requires non-negative position, size, and time tolerances")
    if configured_tolerances is not None:
        for name, report_value in (
            ("position_px", position_tolerance),
            ("size_px", size_tolerance),
            ("time_seconds", time_tolerance),
        ):
            configured_value = _number(configured_tolerances.get(name), -1)
            if configured_value < 0:
                errors.append(f"configured preview/render parity {name} tolerance is invalid")
            elif report_value > configured_value:
                errors.append(f"preview/render parity report exceeds configured {name} tolerance")
    event_ids = {str(event.get("id", "")) for event in (storyboard.get("events") or [])}
    samples = report.get("samples") or []
    if not samples:
        return [*errors, "preview/render parity requires representative event samples"]
    seen: set[str] = set()
    for index, sample in enumerate(samples):
        prefix = f"samples[{index}]"
        event_id = str(sample.get("event_id", ""))
        if event_id not in event_ids:
            errors.append(f"{prefix} references unknown event: {event_id}")
        if event_id in seen:
            errors.append(f"{prefix} duplicates an event parity sample: {event_id}")
        seen.add(event_id)
        shared_time = _number(sample.get("time_seconds"), -1)
        if shared_time < 0:
            errors.append(f"{prefix} requires a non-negative shared time_seconds")
        studio_time = _number(sample.get("studio_time_seconds", shared_time), -1)
        render_time = _number(sample.get("render_time_seconds", shared_time), -1)
        if min(studio_time, render_time) < 0:
            errors.append(f"{prefix} requires non-negative Studio and render sample times")
        elif max(
            abs(studio_time - shared_time),
            abs(render_time - shared_time),
            abs(studio_time - render_time),
        ) > time_tolerance:
            errors.append(f"{prefix} sampling time parity exceeded tolerance")
        for field in ("studio_snapshot", "render_snapshot"):
            path = Path(str(sample.get(field, "")))
            if not path.is_file():
                errors.append(f"{prefix} {field} is missing")
        phase = sample.get("animation_phase") or {}
        if not phase.get("studio") or phase.get("studio") != phase.get("render"):
            errors.append(f"{prefix} animation phase parity failed")
        elements = sample.get("elements") or []
        if not elements:
            errors.append(f"{prefix} requires compared elements")
        for element_index, element in enumerate(elements):
            element_prefix = f"{prefix}.elements[{element_index}]"
            if not str(element.get("selector", "")).strip():
                errors.append(f"{element_prefix} requires selector")
            studio = element.get("studio") or {}
            rendered = element.get("render") or {}
            if studio.get("visible") is not rendered.get("visible"):
                errors.append(f"{element_prefix} visibility parity failed")
            position_delta = max(
                abs(_number(studio.get("x")) - _number(rendered.get("x"))),
                abs(_number(studio.get("y")) - _number(rendered.get("y"))),
            )
            size_delta = max(
                abs(_number(studio.get("width")) - _number(rendered.get("width"))),
                abs(_number(studio.get("height")) - _number(rendered.get("height"))),
            )
            if position_delta > position_tolerance:
                errors.append(f"{element_prefix} position parity exceeded tolerance")
            if size_delta > size_tolerance:
                errors.append(f"{element_prefix} size parity exceeded tolerance")
        connectors = sample.get("connectors") or {}
        expected = int(connectors.get("expected_count", -1))
        studio_count = int(connectors.get("studio_count", -1))
        render_count = int(connectors.get("render_count", -1))
        if expected < 0 or studio_count != expected or render_count != expected:
            errors.append(f"{prefix} connector count parity failed")
        if connectors.get("all_endpoints_attached") is not True or connectors.get("clipped") is True:
            errors.append(f"{prefix} connector attachment or clipping parity failed")
        cropping = sample.get("cropping") or {}
        if cropping.get("studio_clipped") is True or cropping.get("render_clipped") is True:
            errors.append(f"{prefix} cropping parity failed")
        captions = sample.get("caption_occlusion") or {}
        if captions.get("studio") is True or captions.get("render") is True:
            errors.append(f"{prefix} caption occlusion parity failed")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    report_path = Path(args.report).resolve()
    storyboard_path = Path(args.storyboard).resolve()
    errors = validate(read_json(report_path), read_json(storyboard_path))
    result = {"schema_version": 1, "passed": not errors, "errors": errors}
    if args.output:
        write_json(Path(args.output).resolve(), result)
    print(args.output or report_path)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
