#!/usr/bin/env python3
"""Build renderer-bound keyframe receipts from real HyperFrames diagnostics."""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from director_contracts import read_json, sha256_file, write_json
from keyframe_receipt import (
    PHASES,
    recipe_sha256,
    validate_keyframe_receipt,
    validate_renderer_export,
)
from motion_contracts import DEFAULT_RECIPE_REGISTRY, load_recipe_registry


CommandRunner = Callable[[Sequence[str], Path, int], tuple[int, str, str]]
PHASE_FIELDS = (
    "phase", "timestamp_seconds", "snapshot", "visible", "overlay_bbox",
    "animation_phase", "source_state_sha256", "target_observations",
    "crop_status", "caption_overlap_ratio", "composite_contrast_ratio",
)


def _default_runner(command: Sequence[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, str]:
    resolved_command = list(command)
    resolved_command[0] = shutil.which(resolved_command[0]) or resolved_command[0]
    completed = subprocess.run(
        resolved_command, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout_seconds, check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _run_json_tool(
    command: Sequence[str], *, cwd: Path, timeout_seconds: int, runner: CommandRunner,
) -> tuple[dict[str, Any], int, str]:
    exit_code, stdout, stderr = runner(command, cwd, timeout_seconds)
    if exit_code != 0:
        raise RuntimeError(
            f"HyperFrames command failed ({exit_code}): {' '.join(command)}; {stderr.strip()}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"HyperFrames command did not return JSON: {' '.join(command)}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"HyperFrames command returned a non-object: {' '.join(command)}")
    return payload, exit_code, stderr


def _composition_metadata(index_path: Path) -> dict[str, int]:
    text = index_path.read_text(encoding="utf-8")
    values: dict[str, int] = {}
    for key in ("width", "height", "fps"):
        match = re.search(rf'\bdata-{key}=["\'](\d+)["\']', text)
        if match is None or int(match.group(1)) <= 0:
            raise RuntimeError(f"HyperFrames composition is missing positive data-{key}")
        values[key] = int(match.group(1))
    return values


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _animation_coverage(
    animation_map: Mapping[str, Any], opportunities: Sequence[Mapping[str, Any]],
    renderer_events: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    tweens = [
        tween
        for composition in animation_map.get("compositions") or []
        if isinstance(composition, Mapping)
        for tween in composition.get("tweens") or []
        if isinstance(tween, Mapping)
    ]
    coverage: dict[str, list[str]] = {}
    for opportunity in opportunities:
        event_id = str(opportunity.get("semantic_event_id") or "")
        renderer_event = renderer_events.get(event_id) or {}
        allowed_targets = {
            str(value).strip()
            for value in renderer_event.get("animation_targets") or []
            if isinstance(value, str) and value.strip()
        }
        window = opportunity.get("output_window") or {}
        start = _finite(window.get("start_seconds"))
        end = _finite(window.get("end_seconds"))
        if not event_id or start is None or end is None or end <= start:
            raise RuntimeError("render opportunity has an invalid ID or output window")
        if not allowed_targets:
            raise RuntimeError(
                f"renderer export has no animation targets for render event {event_id}"
            )
        matches: list[str] = []
        for tween in tweens:
            tween_start = _finite(tween.get("start"))
            tween_end = _finite(tween.get("end"))
            raw_targets = tween.get("target")
            if isinstance(raw_targets, str):
                tween_targets = {
                    value.strip() for value in raw_targets.split(",") if value.strip()
                }
            elif isinstance(raw_targets, Sequence) and not isinstance(
                raw_targets, (str, bytes)
            ):
                tween_targets = {
                    str(value).strip() for value in raw_targets if str(value).strip()
                }
            else:
                tween_targets = set()
            if (
                tween_start is not None and tween_end is not None
                and tween_end > tween_start
                and min(end, tween_end) > max(start, tween_start)
                and not allowed_targets.isdisjoint(tween_targets)
            ):
                matches.append(str(tween.get("id") or tween.get("target") or "unnamed"))
        if not matches:
            raise RuntimeError(f"HyperFrames keyframes do not cover render event {event_id}")
        coverage[event_id] = matches
    return coverage


def _tool_artifact(
    *, kind: str, raw_output: Mapping[str, Any], project_sha256: str,
    motion_contract_sha256: str, renderer_export_sha256: str,
    event_coverage: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": kind,
        "status": "pass",
        "project_artifact_sha256": project_sha256,
        "motion_design_contract_sha256": motion_contract_sha256,
        "renderer_export_sha256": renderer_export_sha256,
        "event_coverage": dict(event_coverage or {}),
        "raw_output": dict(raw_output),
    }


def build_receipts(
    *, project: Path, motion_design_contract_path: Path,
    renderer_project_manifest_path: Path, renderer_export_path: Path,
    target_binding_dir: Path, parity_path: Path | None = None, output_dir: Path,
    recipe_registry_path: Path = DEFAULT_RECIPE_REGISTRY,
    npx_command: str = "npx", timeout_seconds: int = 120,
    runner: CommandRunner = _default_runner,
) -> list[Path]:
    project = project.resolve()
    index_path = project / "index.html"
    for path, label in (
        (index_path, "HyperFrames index"),
        (motion_design_contract_path, "motion-design contract"),
        (renderer_project_manifest_path, "renderer project manifest"),
        (renderer_export_path, "renderer export"),
    ):
        if not path.resolve().is_file():
            raise RuntimeError(f"{label} is missing: {path}")

    contract = read_json(motion_design_contract_path.resolve())
    renderer_export = read_json(renderer_export_path.resolve())
    export_errors = validate_renderer_export(
        renderer_export,
        project_artifact=renderer_project_manifest_path.resolve(),
        motion_design_contract_path=motion_design_contract_path.resolve(),
    )
    if export_errors:
        raise RuntimeError("renderer export is invalid: " + "; ".join(export_errors))
    opportunities = [
        row for row in contract.get("opportunities") or []
        if isinstance(row, Mapping) and row.get("decision") == "render"
    ]
    if not opportunities:
        raise RuntimeError("motion-design contract has no render opportunities")

    strict_command = [npx_command, "hyperframes", "check", ".", "--strict", "--json"]
    keyframes_command = [npx_command, "hyperframes", "keyframes", ".", "--json"]
    strict_output, strict_exit, _ = _run_json_tool(
        strict_command, cwd=project, timeout_seconds=timeout_seconds, runner=runner,
    )
    if strict_output.get("ok") is not True:
        raise RuntimeError("HyperFrames strict check did not pass")
    keyframes_output, keyframes_exit, _ = _run_json_tool(
        keyframes_command, cwd=project, timeout_seconds=timeout_seconds, runner=runner,
    )
    exported = {
        str(row.get("event_id") or ""): row
        for row in renderer_export.get("events") or [] if isinstance(row, Mapping)
    }
    event_coverage = _animation_coverage(
        keyframes_output, opportunities, exported,
    )

    project_sha = sha256_file(renderer_project_manifest_path.resolve())
    contract_sha = sha256_file(motion_design_contract_path.resolve())
    export_sha = sha256_file(renderer_export_path.resolve())
    tool_dir = output_dir.resolve() / "tool-evidence"
    strict_artifact_path = tool_dir / "strict-check.json"
    animation_artifact_path = tool_dir / "animation-map.json"
    write_json(strict_artifact_path, _tool_artifact(
        kind="strict_check", raw_output=strict_output,
        project_sha256=project_sha, motion_contract_sha256=contract_sha,
        renderer_export_sha256=export_sha,
    ))
    write_json(animation_artifact_path, _tool_artifact(
        kind="animation_map", raw_output=keyframes_output,
        project_sha256=project_sha, motion_contract_sha256=contract_sha,
        renderer_export_sha256=export_sha, event_coverage=event_coverage,
    ))

    registry = load_recipe_registry(recipe_registry_path.resolve())
    recipes = {
        str(row.get("recipe_id") or ""): row
        for row in registry.get("recipes") or [] if isinstance(row, Mapping)
    }
    dimensions = _composition_metadata(index_path)
    renderer_version = str(
        (strict_output.get("_meta") or {}).get("version")
        or (keyframes_output.get("_meta") or {}).get("version") or "unknown"
    )
    created_at = datetime.now(timezone.utc).isoformat()
    output_dir.resolve().mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for opportunity in opportunities:
        event_id = str(opportunity["semantic_event_id"])
        recipe_id = str(opportunity["recipe_id"])
        recipe = recipes.get(recipe_id)
        event_export = exported.get(event_id)
        if recipe is None or event_export is None:
            raise RuntimeError(f"missing recipe or renderer export for {event_id}")
        phases = event_export.get("phases") or []
        if [row.get("phase") for row in phases if isinstance(row, Mapping)] != list(PHASES):
            raise RuntimeError(f"renderer export has invalid phase order for {event_id}")
        binding_paths = [
            (target_binding_dir.resolve() / f"{binding_id}.json")
            for binding_id in opportunity.get("target_binding_ids") or []
        ]
        missing_bindings = [str(path) for path in binding_paths if not path.is_file()]
        if missing_bindings:
            raise RuntimeError(f"target bindings are missing for {event_id}: {missing_bindings}")
        receipt = {
            "schema_version": "1.0.0",
            "receipt_id": f"receipt-{event_id}",
            "event_id": event_id,
            "recipe_id": recipe_id,
            "created_at": created_at,
            "producer": "content-preserving-video-editor-keyframe-builder",
            "renderer": {
                "name": "hyperframes", "version": renderer_version,
                "fps": dimensions["fps"], "width": dimensions["width"],
                "height": dimensions["height"],
            },
            "project_artifact": {
                "path": str(renderer_project_manifest_path.resolve()),
                "sha256": project_sha,
            },
            "input_hashes": {
                "motion_design_contract_sha256": contract_sha,
                "motion_recipe_sha256": recipe_sha256(recipe),
                "target_binding_sha256s": [sha256_file(path) for path in binding_paths],
            },
            "phase_observations": [
                {key: phase[key] for key in PHASE_FIELDS if key in phase}
                for phase in phases
            ],
            "strict_check": {
                "command": strict_command, "exit_code": strict_exit,
                "artifact": {
                    "path": str(strict_artifact_path),
                    "sha256": sha256_file(strict_artifact_path),
                },
            },
            "animation_map": {
                "command": keyframes_command, "exit_code": keyframes_exit,
                "artifact": {
                    "path": str(animation_artifact_path),
                    "sha256": sha256_file(animation_artifact_path),
                },
            },
            "status": "pass",
        }
        errors = validate_keyframe_receipt(
            receipt, motion_design_contract_path=motion_design_contract_path.resolve(),
            recipe_registry_path=recipe_registry_path.resolve(),
            target_binding_paths=binding_paths,
            renderer_export_path=renderer_export_path.resolve(),
        )
        if errors:
            raise RuntimeError(f"keyframe receipt {event_id} is invalid: {'; '.join(errors)}")
        path = output_dir.resolve() / f"{event_id}.json"
        write_json(path, receipt)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--motion-design-contract", required=True, type=Path)
    parser.add_argument("--project-artifact", required=True, type=Path)
    parser.add_argument("--renderer-export", required=True, type=Path)
    parser.add_argument("--target-binding-dir", required=True, type=Path)
    parser.add_argument(
        "--parity", type=Path,
        help="Deprecated compatibility option; parity is a downstream gate over receipts.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--recipe-registry", type=Path, default=DEFAULT_RECIPE_REGISTRY)
    parser.add_argument("--npx-command", default="npx")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    written = build_receipts(
        project=args.project, motion_design_contract_path=args.motion_design_contract,
        renderer_project_manifest_path=args.project_artifact,
        renderer_export_path=args.renderer_export,
        target_binding_dir=args.target_binding_dir, parity_path=args.parity,
        output_dir=args.output_dir, recipe_registry_path=args.recipe_registry,
        npx_command=args.npx_command, timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({"status": "pass", "receipts": [str(path) for path in written]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
