#!/usr/bin/env python3
"""Validate stateful source-target bindings without guessing geometry."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from director_contracts import event_requires_target_region_contract, read_json, sha256_file


SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "references" / "p0-p2-design" / "schemas" / "target-binding.schema.json"
)
MATERIAL_STATE_KINDS = {
    "scene", "route", "modal", "scroll", "zoom", "layout", "visibility", "rotation",
}
STATIC_GEOMETRY_TOLERANCE = 0.02
KEYFRAME_EVENT_TOLERANCE_SECONDS = 0.25
WINDOW_TOLERANCE_SECONDS = 0.05


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _window(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    start = _number(value.get("start_seconds"))
    end = _number(value.get("end_seconds"))
    if start is None or end is None or start < 0 or end <= start:
        return None
    return start, end


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, dict):
        return None
    values = tuple(_number(value.get(field)) for field in ("x", "y", "width", "height"))
    if any(item is None for item in values):
        return None
    x, y, width, height = values
    if (
        x < 0 or y < 0 or width <= 0 or height <= 0
        or x + width > 1 + 1e-9 or y + height > 1 + 1e-9
    ):
        return None
    return x, y, width, height


def _mapped_output_time(binding: dict[str, Any], source_time: float) -> float | None:
    source = _window(binding.get("source_window"))
    output = _window(binding.get("output_window"))
    if source is None or output is None:
        return None
    ratio = (output[1] - output[0]) / (source[1] - source[0])
    return output[0] + (source_time - source[0]) * ratio


def _schema_errors(binding: dict[str, Any]) -> list[str]:
    if not SCHEMA_PATH.is_file():
        return [f"target-binding schema is missing: {SCHEMA_PATH}"]
    schema = read_json(SCHEMA_PATH)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        "target-binding schema "
        + (".".join(str(value) for value in error.absolute_path) or "root")
        + f": {error.message}"
        for error in sorted(validator.iter_errors(binding), key=lambda row: list(row.absolute_path))
    ]


def validate_binding(
    binding: dict[str, Any], *, require_resolved: bool = False,
    static_geometry_tolerance: float = STATIC_GEOMETRY_TOLERANCE,
    keyframe_event_tolerance_seconds: float = KEYFRAME_EVENT_TOLERANCE_SECONDS,
) -> list[str]:
    """Validate schema, evidence, state transitions, active windows, and loss policy."""
    errors = _schema_errors(binding)
    if errors:
        return errors
    if require_resolved and binding.get("status") != "resolved":
        errors.append("target binding must be resolved before a source-bound event renders")

    source_window = _window(binding.get("source_window"))
    output_window = _window(binding.get("output_window"))
    active_windows = [_window(row) for row in binding.get("active_windows") or []]
    if output_window is not None:
        previous_end: float | None = None
        for index, active in enumerate(active_windows):
            if active is None:
                errors.append(f"active_windows[{index}] is invalid")
                continue
            if (
                active[0] < output_window[0] - WINDOW_TOLERANCE_SECONDS
                or active[1] > output_window[1] + WINDOW_TOLERANCE_SECONDS
            ):
                errors.append(f"active_windows[{index}] is outside the output window")
            if previous_end is not None and active[0] < previous_end - WINDOW_TOLERANCE_SECONDS:
                errors.append("target active windows must be ordered and non-overlapping")
            previous_end = active[1]

    observations = binding.get("observations") or []
    target_ids = set(binding.get("target_ids") or [])
    minimum_confidence = float(binding["invalidation_policy"]["minimum_confidence"])
    previous_timestamp: float | None = None
    visible_rows: list[dict[str, Any]] = []
    lost_rows: list[dict[str, Any]] = []
    for index, observation in enumerate(observations):
        timestamp = _number(observation.get("timestamp_seconds"))
        if timestamp is None:
            errors.append(f"observations[{index}] timestamp is invalid")
            continue
        if previous_timestamp is not None and timestamp < previous_timestamp:
            errors.append("target observations must be ordered by timestamp")
        previous_timestamp = timestamp
        if source_window is not None and not (
            source_window[0] - WINDOW_TOLERANCE_SECONDS
            <= timestamp
            <= source_window[1] + WINDOW_TOLERANCE_SECONDS
        ):
            errors.append(f"observations[{index}] is outside the source window")
        if observation.get("target_id") not in target_ids:
            errors.append(f"observations[{index}] references an undeclared target_id")
        visible = observation.get("visible") is True
        if visible:
            visible_rows.append(observation)
            if _bbox(observation.get("bbox")) is None:
                errors.append(f"observations[{index}] visible target bbox is outside the canvas")
            confidence = _number(observation.get("confidence"))
            if confidence is None or confidence < minimum_confidence:
                errors.append(f"observations[{index}] is below minimum target confidence")
        else:
            lost_rows.append(observation)
            if "bbox" in observation:
                errors.append(f"observations[{index}] lost target must omit bbox")
        evidence = observation.get("evidence") or {}
        path = Path(str(evidence.get("path") or ""))
        if not path.is_file():
            errors.append(f"observations[{index}] evidence file is missing")
        elif evidence.get("sha256") != sha256_file(path):
            errors.append(f"observations[{index}] evidence hash is stale")

    if binding.get("status") == "resolved":
        missing_targets = target_ids - {row.get("target_id") for row in visible_rows}
        if missing_targets:
            errors.append(
                "resolved binding lacks a visible observation for targets: "
                + ", ".join(sorted(str(value) for value in missing_targets))
            )

    state_events = binding.get("state_events") or []
    mode = binding.get("tracking_mode")
    material_events = [
        row for row in state_events
        if isinstance(row, dict) and row.get("kind") in MATERIAL_STATE_KINDS
    ]
    if mode == "static":
        for event in material_events:
            errors.append(
                f"static binding cannot cross {event.get('kind')} state change"
            )
        state_hashes = {row.get("source_state_sha256") for row in visible_rows}
        if len(state_hashes) > 1:
            errors.append("static binding requires equivalent source state signatures")
        boxes = [_bbox(row.get("bbox")) for row in visible_rows]
        boxes = [row for row in boxes if row is not None]
        if boxes:
            baseline = boxes[0]
            if any(
                max(abs(value - baseline[position]) for position, value in enumerate(box))
                > static_geometry_tolerance
                for box in boxes[1:]
            ):
                errors.append("static binding geometry changed beyond tolerance")
    elif mode == "scene_bounded":
        if not material_events:
            errors.append("scene_bounded binding requires a verified state boundary")
        elif active_windows:
            first_boundary = min(float(row["timestamp_seconds"]) for row in material_events)
            mapped_boundary = _mapped_output_time(binding, first_boundary)
            latest_active_end = max(row[1] for row in active_windows if row is not None)
            if mapped_boundary is None or latest_active_end > mapped_boundary + WINDOW_TOLERANCE_SECONDS:
                errors.append("scene_bounded active window must exit at or before the state boundary")
    elif mode == "keyframed":
        for event in material_events:
            timestamp = float(event["timestamp_seconds"])
            before = [
                row for row in observations
                if row.get("visible") is True
                and 0 <= timestamp - float(row["timestamp_seconds"]) <= keyframe_event_tolerance_seconds
                and row.get("source_state_sha256") == event.get("before_state_sha256")
            ]
            after = [
                row for row in observations
                if row.get("visible") is True
                and 0 <= float(row["timestamp_seconds"]) - timestamp <= keyframe_event_tolerance_seconds
                and row.get("source_state_sha256") == event.get("after_state_sha256")
            ]
            if not before:
                errors.append(
                    f"keyframed binding lacks a before observation for {event.get('kind')} change"
                )
            if not after:
                errors.append(
                    f"keyframed binding lacks an after observation for {event.get('kind')} change"
                )

    if observations and source_window is not None:
        timestamps = [float(row["timestamp_seconds"]) for row in observations]
        expected_end = source_window[1]
        if lost_rows:
            expected_end = min(float(row["timestamp_seconds"]) for row in lost_rows)
        elif mode == "scene_bounded" and material_events:
            expected_end = min(float(row["timestamp_seconds"]) for row in material_events)
        if min(timestamps) > source_window[0] + keyframe_event_tolerance_seconds:
            errors.append("target observations do not cover the active source-window entrance")
        if max(timestamps) < expected_end - keyframe_event_tolerance_seconds:
            errors.append("target observations do not cover the active source-window exit")

    if lost_rows:
        lost_time = min(float(row["timestamp_seconds"]) for row in lost_rows)
        lost_output_time = _mapped_output_time(binding, lost_time)
        policy = binding["invalidation_policy"].get("on_target_lost")
        if policy == "exit" and active_windows:
            latest_active_end = max(row[1] for row in active_windows if row is not None)
            if lost_output_time is None or latest_active_end > lost_output_time + WINDOW_TOLERANCE_SECONDS:
                errors.append("lost target requires the active window to exit before stale geometry")
        if policy == "fallback" and not binding["invalidation_policy"].get("fallback_recipe_id"):
            errors.append("lost-target fallback requires fallback_recipe_id")
        if policy == "action_required" and binding.get("status") == "resolved":
            errors.append("lost-target action_required policy cannot have resolved status")
    return errors


def resolve_for_render(binding: dict[str, Any]) -> dict[str, Any]:
    """Return a safe render/fallback/action decision and never fabricate coordinates."""
    errors = validate_binding(binding, require_resolved=False)
    if not errors and binding.get("status") == "resolved":
        return {"action": "render", "binding_id": binding.get("binding_id")}
    policy = binding.get("invalidation_policy") or {}
    fallback = policy.get("fallback_recipe_id")
    if policy.get("on_target_lost") == "fallback" and fallback and not errors:
        return {
            "action": "fallback",
            "binding_id": binding.get("binding_id"),
            "fallback_recipe_id": fallback,
        }
    return {
        "action": "action_required",
        "binding_id": binding.get("binding_id"),
        "errors": errors or ["target binding is unresolved"],
        "guessed_coordinates": False,
    }


def validate_storyboard_bindings(
    storyboard: dict[str, Any], binding_dir: Path,
) -> list[str]:
    """Bind every render event explicitly to resolved geometry or targetless mode."""
    errors: list[str] = []
    rows = storyboard.get("events") if isinstance(storyboard, dict) else None
    if not isinstance(rows, list):
        return ["storyboard events must be a list for target binding"]
    binding_dir = binding_dir.resolve()
    seen_binding_ids: set[str] = set()
    for index, event in enumerate(rows):
        prefix = f"events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{prefix} must be a mapping for target binding")
            continue
        required = event.get("target_binding_required")
        if not isinstance(required, bool):
            errors.append(f"{prefix} target_binding_required must be explicitly true or false")
            continue
        binding_ids = event.get("target_binding_ids")
        if not isinstance(binding_ids, list) or any(
            not isinstance(value, str) or not value.strip() for value in binding_ids
        ):
            errors.append(f"{prefix} target_binding_ids must be a list of non-empty IDs")
            continue
        if len(set(binding_ids)) != len(binding_ids):
            errors.append(f"{prefix} target_binding_ids must be unique")
        if required and not binding_ids:
            errors.append(f"{prefix} requires at least one target binding")
            continue
        if not required and binding_ids:
            errors.append(f"{prefix} targetless event cannot carry target binding IDs")
            continue
        if event_requires_target_region_contract(event) and not required:
            errors.append(f"{prefix} source-bound visual cannot declare itself targetless")
        semantic_id = str(event.get("semantic_event_id") or "")
        source_window = (
            _number(event.get("source_start")), _number(event.get("source_end")),
        )
        output_window = (
            _number(event.get("output_start", event.get("start"))),
            _number(event.get("output_end", event.get("end"))),
        )
        for binding_id in binding_ids:
            if binding_id in seen_binding_ids:
                errors.append(f"target binding {binding_id!r} is assigned to multiple events")
            seen_binding_ids.add(binding_id)
            path = (binding_dir / f"{binding_id}.json").resolve()
            if path.parent != binding_dir:
                errors.append(f"{prefix} target binding path escapes the binding directory")
                continue
            if not path.is_file():
                errors.append(f"{prefix} target binding file is missing: {path}")
                continue
            binding = read_json(path)
            binding_errors = validate_binding(binding, require_resolved=True)
            errors.extend(f"{prefix} {binding_id}: {error}" for error in binding_errors)
            if binding.get("binding_id") != binding_id:
                errors.append(f"{prefix} target binding ID does not match its filename")
            if binding.get("semantic_event_id") != semantic_id:
                errors.append(f"{prefix} target binding references the wrong semantic event")
            for label, expected, actual in (
                ("source", source_window, _window(binding.get("source_window"))),
                ("output", output_window, _window(binding.get("output_window"))),
            ):
                if (
                    None in expected
                    or actual is None
                    or abs(float(expected[0]) - actual[0]) > WINDOW_TOLERANCE_SECONDS
                    or abs(float(expected[1]) - actual[1]) > WINDOW_TOLERANCE_SECONDS
                ):
                    errors.append(f"{prefix} target binding {label} window does not match the event")
    return errors
