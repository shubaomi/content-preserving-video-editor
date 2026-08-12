#!/usr/bin/env python3
"""Validate Studio/snapshot and representative render parity at matching times."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from director_contracts import read_json, sha256_file, write_json


def _number(value: Any, default: float = float("inf")) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def validate(
    report: dict[str, Any],
    storyboard: dict[str, Any],
    *,
    configured_tolerances: dict[str, Any] | None = None,
    expected_bindings: Mapping[str, Path] | None = None,
    keyframe_receipt_paths: Mapping[str, Path] | None = None,
) -> list[str]:
    errors: list[str] = []
    expected_schema = 2 if expected_bindings is not None else 1
    if report.get("schema_version") != expected_schema:
        errors.append(f"preview/render parity schema_version must be {expected_schema}")
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
    if expected_bindings is not None:
        inputs = report.get("inputs") or {}
        for name in ("project_artifact", "motion_design_contract", "source_media"):
            expected_path = Path(expected_bindings.get(name, Path(""))).resolve()
            row = inputs.get(name) or {}
            path = Path(str(row.get("path") or ""))
            if path.resolve() != expected_path:
                errors.append(f"preview/render parity {name} path is stale")
            if not expected_path.is_file() or row.get("sha256") != (
                sha256_file(expected_path) if expected_path.is_file() else None
            ):
                errors.append(f"preview/render parity {name} hash is stale")
    event_ids = {
        str(event.get("semantic_event_id") or event.get("id", ""))
        for event in (storyboard.get("events") or []) if isinstance(event, dict)
    }
    samples = report.get("samples") or []
    if not samples:
        return [*errors, "preview/render parity requires representative event samples"]
    seen: set[str | tuple[str, str]] = set()
    samples_by_event: dict[str, list[dict[str, Any]]] = {}
    for index, sample in enumerate(samples):
        prefix = f"samples[{index}]"
        event_id = str(sample.get("event_id", ""))
        if event_id not in event_ids:
            errors.append(f"{prefix} references unknown event: {event_id}")
        phase_name = str(sample.get("phase") or "")
        seen_key: str | tuple[str, str] = (
            (event_id, phase_name) if expected_bindings is not None else event_id
        )
        if seen_key in seen:
            errors.append(f"{prefix} duplicates an event parity sample: {event_id}")
        seen.add(seen_key)
        samples_by_event.setdefault(event_id, []).append(sample)
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
            elif sample.get(f"{field}_sha256") != sha256_file(path):
                errors.append(f"{prefix} {field} hash is missing or stale")
            elif expected_bindings is not None:
                try:
                    with Image.open(path) as image:
                        image.load()
                except (OSError, UnidentifiedImageError):
                    errors.append(f"{prefix} {field} is not a decodable image")
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
    if expected_bindings is not None:
        receipt_paths = keyframe_receipt_paths or {}
        if set(receipt_paths) != event_ids:
            errors.append("preview/render parity keyframe receipt set differs from Storyboard events")
        for event_id in sorted(event_ids):
            path = Path(receipt_paths.get(event_id, Path(""))).resolve()
            if not path.is_file():
                errors.append(f"preview/render parity keyframe receipt is missing for {event_id}")
                continue
            try:
                receipt = read_json(path)
            except (OSError, ValueError):
                errors.append(f"preview/render parity keyframe receipt is invalid for {event_id}")
                continue
            event_samples = samples_by_event.get(event_id) or []
            phases = [str(row.get("phase") or "") for row in event_samples]
            if phases != ["entrance", "mid", "pre_exit", "post_exit"]:
                errors.append(f"preview/render parity requires all four phases for {event_id}")
            observations = receipt.get("phase_observations") or []
            if [row.get("phase") for row in observations if isinstance(row, dict)] != [
                "entrance", "mid", "pre_exit", "post_exit",
            ]:
                errors.append(f"preview/render parity keyframe receipt lacks four phases for {event_id}")
                continue
            for sample, observation in zip(event_samples, observations):
                artifact = sample.get("keyframe_receipt") or {}
                if Path(str(artifact.get("path") or "")).resolve() != path:
                    errors.append(f"preview/render parity keyframe receipt path is stale for {event_id}")
                if artifact.get("sha256") != sha256_file(path):
                    errors.append(f"preview/render parity keyframe receipt hash is stale for {event_id}")
                if sample.get("phase") != observation.get("phase"):
                    errors.append(f"preview/render parity phase differs from keyframe receipt for {event_id}")
                sample_time = _number(sample.get("time_seconds"), -1)
                receipt_time = _number(observation.get("timestamp_seconds"), -1)
                if min(sample_time, receipt_time) < 0 or abs(sample_time - receipt_time) > time_tolerance:
                    errors.append(f"preview/render parity time differs from keyframe receipt for {event_id}")
            project = (receipt.get("project_artifact") or {})
            contract_hash = (receipt.get("input_hashes") or {}).get(
                "motion_design_contract_sha256",
            )
            if project.get("sha256") != sha256_file(expected_bindings["project_artifact"]):
                errors.append(f"preview/render parity receipt project binding is stale for {event_id}")
            if contract_hash != sha256_file(expected_bindings["motion_design_contract"]):
                errors.append(f"preview/render parity receipt contract binding is stale for {event_id}")
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
