#!/usr/bin/env python3
"""Validate renderer-produced HyperFrames keyframe and DOM/geometry evidence."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, UnidentifiedImageError

from director_contracts import read_json, sha256_file
from motion_contracts import (
    DEFAULT_RECIPE_REGISTRY,
    load_recipe_registry,
    validate_contract_schema,
)
from renderer_project_manifest import validate_manifest as validate_project_manifest


PHASES = ("entrance", "mid", "pre_exit", "post_exit")
RENDERER_EXPORT_PRODUCERS = {
    "hyperframes-project-runtime",
    "hyperframes-studio-export",
    "hyperframes-render-export",
}


def recipe_sha256(recipe: Mapping[str, Any]) -> str:
    """Return the content hash used to bind one registry recipe."""
    import hashlib

    encoded = json.dumps(
        recipe, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _bbox_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} overlay_bbox is missing or invalid"]
    errors: list[str] = []
    values: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        number = _finite_number(value.get(key))
        if number is None or number < 0 or number > 1:
            errors.append(f"{label} overlay_bbox {key} must be finite within 0..1")
        else:
            values[key] = number
    if len(values) == 4 and (
        values["x"] + values["width"] > 1.000001
        or values["y"] + values["height"] > 1.000001
    ):
        errors.append(f"{label} overlay_bbox exceeds the canvas")
    return errors


def _artifact_errors(value: Any, label: str, *, expected_path: Path | None = None) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} artifact is missing"]
    path = Path(str(value.get("path") or ""))
    if expected_path is not None and path.resolve() != expected_path.resolve():
        return [f"{label} artifact path is stale"]
    if not path.is_file():
        return [f"{label} artifact is missing"]
    if value.get("sha256") != sha256_file(path):
        return [f"{label} artifact hash is stale"]
    return []


def _load_mapping(path: Path, label: str) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file():
        return {}, [f"{label} is missing"]
    try:
        payload = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}, [f"{label} is not valid JSON"]
    if not isinstance(payload, dict):
        return {}, [f"{label} must be a mapping"]
    return payload, []


def validate_renderer_export(
    payload: dict[str, Any], *, project_artifact: Path,
    motion_design_contract_path: Path,
) -> list[str]:
    """Validate the project-side export that reports actual painted DOM state."""
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("renderer export schema_version must be 1")
    if payload.get("producer") not in RENDERER_EXPORT_PRODUCERS:
        errors.append("renderer export producer must be a HyperFrames runtime export")
    errors.extend(_artifact_errors(
        payload.get("project_artifact"), "renderer export project",
        expected_path=project_artifact,
    ))
    if (
        not motion_design_contract_path.is_file()
        or payload.get("motion_design_contract_sha256")
        != sha256_file(motion_design_contract_path)
    ):
        errors.append("renderer export motion-design contract hash is stale")
    contract, contract_errors = _load_mapping(
        motion_design_contract_path, "motion-design contract",
    )
    errors.extend(contract_errors)
    source_hash = (contract.get("source_media") or {}).get("sha256")
    if not source_hash or payload.get("source_media_sha256") != source_hash:
        errors.append("renderer export source media hash is stale")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return [*errors, "renderer export requires event measurements"]
    approved_events = [
        row for row in contract.get("opportunities") or []
        if isinstance(row, dict) and row.get("decision") == "render"
    ]
    approved_ids = [str(row.get("semantic_event_id") or "") for row in approved_events]
    actual_ids = [
        str(row.get("event_id") or "") if isinstance(row, dict) else ""
        for row in events
    ]
    if actual_ids != approved_ids:
        errors.append(
            "renderer export event order differs from approved render opportunities"
        )
    approved_by_id = {
        str(row.get("semantic_event_id") or ""): row for row in approved_events
    }
    seen: set[str] = set()
    for event_index, event in enumerate(events):
        prefix = f"renderer export events[{event_index}]"
        if not isinstance(event, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        event_id = str(event.get("event_id") or "")
        if not event_id:
            errors.append(f"{prefix} requires event_id")
        elif event_id in seen:
            errors.append(f"{prefix} duplicates event_id {event_id}")
        seen.add(event_id)
        approved = approved_by_id.get(event_id)
        if not str(event.get("recipe_id") or ""):
            errors.append(f"{prefix} requires recipe_id")
        elif approved is not None and event.get("recipe_id") != approved.get("recipe_id"):
            errors.append(f"{prefix} recipe differs from the approved render opportunity")
        animation_targets = event.get("animation_targets")
        if (
            not isinstance(animation_targets, list)
            or not animation_targets
            or any(
                not isinstance(value, str)
                or not value.startswith("#")
                or not value.strip()
                for value in animation_targets
            )
            or len(set(animation_targets)) != len(animation_targets)
        ):
            errors.append(
                f"{prefix} animation_targets must be a unique non-empty selector list"
            )
        visible_text = event.get("visible_text")
        if not isinstance(visible_text, list) or any(
            not isinstance(value, str) or not value.strip() for value in visible_text
        ):
            errors.append(f"{prefix} visible_text must be an explicit string list")
        elif approved is not None and visible_text != list(
            approved.get("approved_visible_copy") or []
        ):
            errors.append(f"{prefix} visible_text differs from approved visible copy")
        phases = event.get("phases")
        if not isinstance(phases, list) or [
            row.get("phase") if isinstance(row, dict) else None for row in phases
        ] != list(PHASES):
            errors.append(f"{prefix} phases must be entrance, mid, pre_exit, post_exit")
            continue
        for phase in phases:
            label = f"{prefix} {phase['phase']}"
            if _finite_number(phase.get("timestamp_seconds")) is None:
                errors.append(f"{label} timestamp_seconds is invalid")
            errors.extend(_artifact_errors(phase.get("snapshot"), f"{label} snapshot"))
            if not isinstance(phase.get("visible"), bool):
                errors.append(f"{label} visible must be measured")
            errors.extend(_bbox_errors(phase.get("overlay_bbox"), label))
            if not str(phase.get("animation_phase") or ""):
                errors.append(f"{label} animation_phase is missing")
            if not isinstance(phase.get("source_state_sha256"), str) or len(
                phase.get("source_state_sha256") or ""
            ) != 64:
                errors.append(f"{label} source_state_sha256 is missing")
            if not isinstance(phase.get("target_observations"), list):
                errors.append(f"{label} target_observations must be a list")
            if not isinstance(phase.get("connectors"), list):
                errors.append(f"{label} connectors must be a list")
            if phase.get("crop_status") not in {"inside", "clipped", "not_applicable"}:
                errors.append(f"{label} crop_status is invalid")
            if _finite_number(phase.get("caption_overlap_ratio")) is None:
                errors.append(f"{label} caption_overlap_ratio is invalid")
    return errors


def _event_opportunity(contract: Mapping[str, Any], event_id: str) -> dict[str, Any] | None:
    for row in contract.get("opportunities") or []:
        if isinstance(row, dict) and row.get("semantic_event_id") == event_id:
            return row
    return None


def _verified_render_window(
    opportunity: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]],
) -> tuple[float | None, float | None, list[str]]:
    """Return the continuous interval where every declared target is visible."""
    output = opportunity.get("output_window") or {}
    start = _finite_number(output.get("start_seconds"))
    end = _finite_number(output.get("end_seconds"))
    if start is None or end is None or end <= start:
        return start, end, ["keyframe receipt event output window is invalid"]
    segments: list[tuple[float, float]] = [(start, end)]
    for binding in bindings:
        windows = binding.get("active_windows")
        if not isinstance(windows, list) or not windows:
            declared = binding.get("output_window")
            windows = [declared] if isinstance(declared, Mapping) else []
        verified: list[tuple[float, float]] = []
        for window in windows:
            if not isinstance(window, Mapping):
                continue
            window_start = _finite_number(window.get("start_seconds"))
            window_end = _finite_number(window.get("end_seconds"))
            if window_start is not None and window_end is not None and window_end > window_start:
                verified.append((window_start, window_end))
        intersections = sorted(
            (max(left, window_left), min(right, window_right))
            for left, right in segments
            for window_left, window_right in verified
            if min(right, window_right) > max(left, window_left)
        )
        merged: list[tuple[float, float]] = []
        for segment in intersections:
            if merged and segment[0] <= merged[-1][1] + 1e-9:
                merged[-1] = (merged[-1][0], max(merged[-1][1], segment[1]))
            else:
                merged.append(segment)
        segments = merged
    if len(segments) != 1:
        return None, None, [
            "keyframe receipt target bindings do not provide one contiguous active window"
        ]
    return segments[0][0], segments[0][1], []


def _tool_receipt_errors(
    receipt: Any, label: str, *, command_token: str, artifact_kind: str,
    project_sha256: str,
    motion_contract_sha256: str, renderer_export_sha256: str,
) -> list[str]:
    if not isinstance(receipt, dict):
        return [f"{label} receipt is missing"]
    errors = _artifact_errors(receipt.get("artifact"), label)
    if receipt.get("exit_code") != 0:
        errors.append(f"{label} exit_code must be zero")
    command = receipt.get("command")
    if not isinstance(command, list) or not any(
        str(value) == command_token for value in command
    ):
        errors.append(f"{label} command is not the required HyperFrames operation")
    artifact_path = Path(str((receipt.get("artifact") or {}).get("path") or ""))
    artifact, load_errors = _load_mapping(artifact_path, f"{label} artifact")
    errors.extend(load_errors)
    if artifact:
        if artifact.get("kind") != artifact_kind:
            errors.append(f"{label} artifact kind is invalid")
        if artifact.get("status") != "pass":
            errors.append(f"{label} artifact did not pass")
        for key, expected, description in (
            ("project_artifact_sha256", project_sha256, "project"),
            ("motion_design_contract_sha256", motion_contract_sha256, "motion contract"),
            ("renderer_export_sha256", renderer_export_sha256, "renderer export"),
        ):
            if artifact.get(key) != expected:
                errors.append(f"{label} {description} binding is stale")
    return errors


def _same_measurement(left: Any, right: Any) -> bool:
    return left == right


def validate_keyframe_receipt(
    receipt: dict[str, Any], *, motion_design_contract_path: Path,
    recipe_registry_path: Path = DEFAULT_RECIPE_REGISTRY,
    target_binding_paths: Sequence[Path] = (), renderer_export_path: Path,
    parity_path: Path | None = None, maximum_caption_overlap_ratio: float = 0.0,
    minimum_composite_contrast_ratio: float = 4.5,
    maximum_connector_error_pixels: float = 4.0,
) -> list[str]:
    """Validate frozen schema plus renderer-bound P0.5 invariants."""
    errors = validate_contract_schema("keyframe-receipt", receipt)
    if errors:
        return errors
    if receipt.get("status") != "pass":
        errors.append("keyframe receipt status must be pass")
    motion_contract_path = motion_design_contract_path.resolve()
    contract, contract_errors = _load_mapping(motion_contract_path, "motion-design contract")
    errors.extend(contract_errors)
    if contract_errors:
        return errors
    contract_sha = sha256_file(motion_contract_path)
    if receipt["input_hashes"]["motion_design_contract_sha256"] != contract_sha:
        errors.append("keyframe receipt motion-design contract hash is stale")
    event_id = str(receipt["event_id"])
    opportunity = _event_opportunity(contract, event_id)
    if opportunity is None or opportunity.get("decision") != "render":
        errors.append("keyframe receipt event is not an approved render opportunity")
        return errors
    if receipt["recipe_id"] != opportunity.get("recipe_id"):
        errors.append("keyframe receipt recipe differs from motion-design selection")
    registry = load_recipe_registry(recipe_registry_path.resolve())
    recipe = next(
        (row for row in registry.get("recipes") or [] if row.get("recipe_id") == receipt["recipe_id"]),
        None,
    )
    if recipe is None:
        errors.append("keyframe receipt recipe is missing from the registry")
        return errors
    if receipt["input_hashes"]["motion_recipe_sha256"] != recipe_sha256(recipe):
        errors.append("keyframe receipt recipe hash is stale")

    project_path = Path(receipt["project_artifact"]["path"]).resolve()
    errors.extend(_artifact_errors(
        receipt.get("project_artifact"), "keyframe project", expected_path=project_path,
    ))
    if project_path.is_file():
        project_manifest, project_manifest_errors = _load_mapping(
            project_path, "renderer project manifest",
        )
        errors.extend(project_manifest_errors)
        if project_manifest:
            errors.extend(
                f"keyframe project is stale: {error}"
                for error in validate_project_manifest(project_manifest, project_path)
            )
    project_sha = sha256_file(project_path) if project_path.is_file() else ""

    bindings: list[dict[str, Any]] = []
    binding_hashes: list[str] = []
    for path_value in target_binding_paths:
        path = Path(path_value).resolve()
        payload, load_errors = _load_mapping(path, "target binding")
        errors.extend(load_errors)
        if payload:
            bindings.append(payload)
            binding_hashes.append(sha256_file(path))
    if receipt["input_hashes"]["target_binding_sha256s"] != binding_hashes:
        errors.append("keyframe receipt target-binding hashes are stale")
    expected_binding_ids = list(opportunity.get("target_binding_ids") or [])
    if [row.get("binding_id") for row in bindings] != expected_binding_ids:
        errors.append("keyframe receipt target-binding set differs from motion-design contract")
    expected_target_ids = [
        str(target_id) for binding in bindings for target_id in binding.get("target_ids") or []
    ]
    connector_required = any(binding.get("target_kind") == "connector_nodes" for binding in bindings)

    renderer_export, renderer_load_errors = _load_mapping(
        renderer_export_path.resolve(), "renderer export",
    )
    errors.extend(renderer_load_errors)
    if renderer_export:
        errors.extend(validate_renderer_export(
            renderer_export, project_artifact=project_path,
            motion_design_contract_path=motion_contract_path,
        ))
    renderer_export_sha = (
        sha256_file(renderer_export_path.resolve()) if renderer_export_path.is_file() else ""
    )
    exported_events = [
        row for row in renderer_export.get("events") or []
        if isinstance(row, dict) and row.get("event_id") == event_id
    ]
    exported = exported_events[0] if len(exported_events) == 1 else None
    if exported is None:
        errors.append("renderer export requires exactly one matching event")
        exported_phases: list[dict[str, Any]] = []
    else:
        if exported.get("recipe_id") != receipt["recipe_id"]:
            errors.append("renderer export recipe differs from keyframe receipt")
        if exported.get("visible_text") != list(opportunity.get("approved_visible_copy") or []):
            errors.append("renderer visible text differs from approved visible copy")
        exported_phases = [row for row in exported.get("phases") or [] if isinstance(row, dict)]

    start, end, window_errors = _verified_render_window(opportunity, bindings)
    errors.extend(window_errors)
    observations = receipt["phase_observations"]
    timestamps = [_finite_number(row.get("timestamp_seconds")) for row in observations]
    if any(value is None for value in timestamps) or timestamps != sorted(timestamps):
        errors.append("keyframe receipt phase timestamps must be finite and ordered")
    elif start is None or end is None:
        pass
    else:
        if timestamps[0] < start or timestamps[2] > end:
            errors.append("keyframe receipt visible phases fall outside the event output window")
        if timestamps[3] < end or timestamps[3] > end + 1.0:
            errors.append("keyframe receipt post_exit timestamp is not adjacent to event exit")

    for index, phase in enumerate(observations):
        name = PHASES[index]
        label = f"keyframe {event_id} {name}"
        snapshot_path = Path(phase["snapshot"]["path"])
        errors.extend(_artifact_errors(phase.get("snapshot"), f"{label} snapshot"))
        if snapshot_path.is_file():
            try:
                with Image.open(snapshot_path) as image:
                    image.load()
                    if image.size != (receipt["renderer"]["width"], receipt["renderer"]["height"]):
                        errors.append(f"{label} snapshot dimensions differ from renderer")
            except (OSError, UnidentifiedImageError):
                errors.append(f"{label} snapshot is not a decodable image")
        if name != "post_exit":
            if phase.get("visible") is not True:
                errors.append(f"{label} must be visible")
            if phase.get("crop_status") == "clipped":
                errors.append(f"{label} is clipped")
            overlap = _finite_number(phase.get("caption_overlap_ratio"))
            if overlap is None or overlap > maximum_caption_overlap_ratio:
                errors.append(f"{label} caption collision exceeds tolerance")
            contrast = _finite_number(phase.get("composite_contrast_ratio"))
            if contrast is None or contrast < minimum_composite_contrast_ratio:
                errors.append(f"{label} composite contrast is below tolerance")
            observed_ids = [row.get("target_id") for row in phase.get("target_observations") or []]
            if observed_ids != expected_target_ids:
                errors.append(f"{label} target observations are incomplete")
            for target in phase.get("target_observations") or []:
                connector_error = target.get("connector_attachment_error_pixels")
                if connector_error is not None and (
                    _finite_number(connector_error) is None
                    or float(connector_error) > maximum_connector_error_pixels
                ):
                    errors.append(f"{label} connector attachment exceeds tolerance")
        else:
            bbox = phase.get("overlay_bbox") or {}
            if phase.get("visible") is not False:
                errors.append(f"{label} must not be visible after exit")
            if any(float(bbox.get(key, 0)) != 0.0 for key in ("width", "height")):
                errors.append(f"{label} retains non-zero overlay geometry")
            if phase.get("target_observations"):
                errors.append(f"{label} retains target observations")
        if index < len(exported_phases):
            exported_phase = exported_phases[index]
            for field in (
                "phase", "timestamp_seconds", "visible", "overlay_bbox", "animation_phase",
                "source_state_sha256", "target_observations", "crop_status",
                "caption_overlap_ratio", "composite_contrast_ratio",
            ):
                if not _same_measurement(phase.get(field), exported_phase.get(field)):
                    description = "source state" if field == "source_state_sha256" else field
                    errors.append(f"{label} {description} differs from renderer export")
        if connector_required and index < 3:
            connectors = exported_phases[index].get("connectors") if index < len(exported_phases) else []
            if not connectors:
                errors.append(f"{label} missing required connector evidence")

    errors.extend(_tool_receipt_errors(
        receipt.get("strict_check"), "strict_check", command_token="check",
        artifact_kind="strict_check",
        project_sha256=project_sha, motion_contract_sha256=contract_sha,
        renderer_export_sha256=renderer_export_sha,
    ))
    errors.extend(_tool_receipt_errors(
        receipt.get("animation_map"), "animation_map", command_token="keyframes",
        artifact_kind="animation_map",
        project_sha256=project_sha, motion_contract_sha256=contract_sha,
        renderer_export_sha256=renderer_export_sha,
    ))
    # Preview/render parity is the downstream gate that hash-binds these
    # receipts. Requiring a receipt to bind that same report would create a
    # cyclic hash dependency. ``parity_path`` and the optional legacy artifact
    # field remain readable for compatibility, but new receipts do not emit it.
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one renderer-produced HyperFrames keyframe receipt.",
    )
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--motion-design-contract", required=True, type=Path)
    parser.add_argument("--renderer-export", required=True, type=Path)
    parser.add_argument("--recipe-registry", type=Path, default=DEFAULT_RECIPE_REGISTRY)
    parser.add_argument("--target-binding", action="append", type=Path, default=[])
    parser.add_argument("--parity", type=Path)
    parser.add_argument("--maximum-caption-overlap-ratio", type=float, default=0.0)
    parser.add_argument("--minimum-composite-contrast-ratio", type=float, default=4.5)
    parser.add_argument("--maximum-connector-error-pixels", type=float, default=4.0)
    args = parser.parse_args()
    receipt, load_errors = _load_mapping(args.receipt.resolve(), "keyframe receipt")
    errors = list(load_errors)
    if receipt:
        errors.extend(validate_keyframe_receipt(
            receipt,
            motion_design_contract_path=args.motion_design_contract,
            recipe_registry_path=args.recipe_registry,
            target_binding_paths=args.target_binding,
            renderer_export_path=args.renderer_export,
            parity_path=args.parity,
            maximum_caption_overlap_ratio=args.maximum_caption_overlap_ratio,
            minimum_composite_contrast_ratio=args.minimum_composite_contrast_ratio,
            maximum_connector_error_pixels=args.maximum_connector_error_pixels,
        ))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(str(args.receipt.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
