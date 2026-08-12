#!/usr/bin/env python3
"""Execute only explicit, equivalence-proven HyperFrames event render commands."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from dependency_graph import DependencyGraph
from director_contracts import sha256_file
from event_cache import EventCache, EventCacheError, build_event_key, plan_event_rebuild


class EventRenderUnavailable(ValueError):
    """Raised when a safe event-level HyperFrames render contract is unavailable."""


def _hash_or_disabled(path: Path | None) -> str:
    return sha256_file(path) if path is not None and path.is_file() else "disabled"


def _event_id(row: dict[str, Any]) -> str:
    return str(row.get("event_id") or row.get("id") or "").strip()


def _run_command(
    argv: list[str], *, cwd: Path, expected: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    temporary = expected.with_name(
        f".{expected.stem}.{uuid.uuid4().hex}.event-rendering{expected.suffix}"
    )
    command = [str(temporary) if str(value) == str(expected) else str(value) for value in argv]
    try:
        result = runner(
            command, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise EventRenderUnavailable("HyperFrames event command failed")
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise EventRenderUnavailable("HyperFrames event command did not create its output")
        expected.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, expected)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_equivalence(row: dict[str, Any], label: str) -> None:
    evidence = row.get("equivalence_evidence") or {}
    if not isinstance(evidence, dict):
        raise EventRenderUnavailable(f"{label} equivalence evidence is invalid")
    required = ("frame_accurate", "audio_sample_accurate", "visual_equivalent")
    missing = [name for name in required if evidence.get(name) is not True]
    if missing:
        raise EventRenderUnavailable(
            f"{label} lacks equivalence evidence: {', '.join(missing)}"
        )
    receipt_path = Path(str(evidence.get("path") or ""))
    if not receipt_path.is_absolute() or not receipt_path.is_file() \
            or evidence.get("sha256") != sha256_file(receipt_path):
        raise EventRenderUnavailable(f"{label} equivalence receipt is missing or stale")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise EventRenderUnavailable(f"{label} equivalence receipt is unreadable") from error
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("status") != "pass"
        or receipt.get("kind") != "hyperframes_event_equivalence"
        or receipt.get("scope") != evidence.get("scope")
        or not all(receipt.get(name) is True for name in required)
    ):
        raise EventRenderUnavailable(f"{label} equivalence receipt is invalid")
    if evidence.get("scope") == "assembly" and receipt.get("ordered_segment_hash_binding") is not True:
        raise EventRenderUnavailable("event assembly lacks ordered segment hash binding")
    reference = Path(str(receipt.get("reference_artifact") or ""))
    observed = Path(str(receipt.get("observed_artifact") or ""))
    expected_artifact = Path(str(row.get("expected_artifact") or "")).resolve()
    if (
        not reference.is_absolute() or not observed.is_absolute()
        or not reference.is_file() or not observed.is_file()
        or observed.resolve() != expected_artifact
        or receipt.get("reference_sha256") != sha256_file(reference)
        or receipt.get("observed_sha256") != sha256_file(observed)
        or receipt.get("reference_sha256") != receipt.get("observed_sha256")
        or receipt.get("full_decode") is not True
    ):
        raise EventRenderUnavailable(f"{label} equivalence media binding is invalid")
    for media in (reference, observed):
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(media), "-map", "0:v:0", "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        )
        if decoded.returncode != 0:
            raise EventRenderUnavailable(f"{label} equivalence media does not fully decode")


def _validate_equivalence_after_render(row: dict[str, Any], label: str) -> None:
    evidence = row.get("equivalence_evidence") or {}
    receipt = json.loads(Path(str(evidence["path"])).read_text(encoding="utf-8"))
    observed = Path(str(receipt["observed_artifact"]))
    reference = Path(str(receipt["reference_artifact"]))
    if not observed.is_file() or sha256_file(observed) != receipt.get("observed_sha256") \
            or sha256_file(observed) != sha256_file(reference):
        raise EventRenderUnavailable(f"{label} rendered bytes differ from equivalence reference")


def _snapshot_hashes(paths: dict[str, Path | None]) -> dict[str, str]:
    return {name: _hash_or_disabled(path) for name, path in sorted(paths.items())}


def _assert_snapshot_unchanged(
    paths: dict[str, Path | None], expected: dict[str, str], label: str,
) -> None:
    if _snapshot_hashes(paths) != expected:
        raise EventRenderUnavailable(f"{label} changed during event rendering")


def execute_event_render_pipeline(
    *, command_record: dict[str, Any], storyboard_path: Path,
    captions_path: Path, safe_zones_path: Path, design_tokens_path: Path,
    provider_evidence_path: Path | None, rights_evidence_path: Path,
    implementation_paths: list[Path], cache_root: Path, output: Path,
    previous_fingerprints: dict[str, dict[str, Any]] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Render/cache explicit HyperFrames event windows; never synthesize substitutes."""
    rows = command_record.get("event_motion_renders")
    assembly = command_record.get("event_motion_assembly")
    if not isinstance(rows, list) or not rows or not isinstance(assembly, dict):
        raise EventRenderUnavailable("HyperFrames event render/assembly commands are not declared")
    if assembly.get("owner") != "hyperframes":
        raise EventRenderUnavailable("event assembly owner must be hyperframes")

    try:
        storyboard_bytes = storyboard_path.read_bytes()
        storyboard = json.loads(storyboard_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EventRenderUnavailable("storyboard is unreadable") from error
    storyboard_sha256 = hashlib.sha256(storyboard_bytes).hexdigest()
    expected_ids = [_event_id(row) for row in storyboard.get("events") or []]
    expected_ids = [value for value in expected_ids if value]
    records = {_event_id(row): row for row in rows if isinstance(row, dict) and _event_id(row)}
    if len(records) != len(rows) or set(records) != set(expected_ids):
        raise EventRenderUnavailable("event render commands must exactly cover storyboard events")

    common_sources: dict[str, Path | None] = {
        "storyboard": storyboard_path,
        "captions": captions_path,
        "safe_zones": safe_zones_path,
        "design_tokens": design_tokens_path,
        "provider_evidence": provider_evidence_path,
        "rights_evidence": rights_evidence_path,
        **{f"implementation:{index}": path for index, path in enumerate(implementation_paths)},
    }
    common_snapshot = _snapshot_hashes(common_sources)
    if common_snapshot["storyboard"] != storyboard_sha256:
        raise EventRenderUnavailable("storyboard changed while being inspected")
    missing_required = [
        name for name in ("captions", "safe_zones", "rights_evidence")
        if common_snapshot[name] == "disabled"
    ]
    if missing_required:
        raise EventRenderUnavailable(
            "required render inputs are missing: " + ", ".join(missing_required)
        )
    implementation_hashes = {
        str(path.resolve()): common_snapshot[f"implementation:{index}"]
        for index, path in enumerate(implementation_paths)
        if common_snapshot[f"implementation:{index}"] != "disabled"
    }
    implementation_sha = hashlib.sha256(json.dumps(
        implementation_hashes, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    common = {
        "renderer": "hyperframes",
        "captions_sha256": common_snapshot["captions"],
        "safe_zones_sha256": common_snapshot["safe_zones"],
        "design_tokens_sha256": common_snapshot["design_tokens"],
        "provider_evidence_sha256": common_snapshot["provider_evidence"],
        "rights_evidence_sha256": common_snapshot["rights_evidence"],
        "implementation_sha256": implementation_sha,
    }
    fingerprints: dict[str, dict[str, Any]] = {}
    event_sources: dict[str, dict[str, Path | None]] = {}
    event_snapshots: dict[str, dict[str, str]] = {}
    nodes: list[dict[str, Any]] = []
    for event_id in expected_ids:
        record = records[event_id]
        if record.get("owner") != "hyperframes":
            raise EventRenderUnavailable(f"event {event_id} owner must be hyperframes")
        # Structural receipt validation is deferred until the command has produced
        # the exact observed artifact; this prevents a sidecar file proving a bystander.
        expected = Path(str(record.get("expected_artifact") or "")).resolve()
        cwd = Path(str(record.get("cwd") or "")).resolve()
        argv = record.get("argv")
        if not expected.is_relative_to(cwd) or not isinstance(argv, list) or not argv:
            raise EventRenderUnavailable(f"event {event_id} command is unsafe")
        asset_sources: dict[str, Path | None] = {}
        for value in record.get("assets") or []:
            asset = Path(str(value)).resolve()
            if not asset.is_file():
                raise EventRenderUnavailable(f"event {event_id} asset is missing")
            asset_sources[f"asset:{len(asset_sources)}"] = asset
        event_sources[event_id] = asset_sources
        event_snapshots[event_id] = _snapshot_hashes(asset_sources)
        fingerprints[event_id] = {
            "event_id": event_id,
            **common,
            "owner_artifact_sha256": hashlib.sha256(json.dumps(
                next(row for row in storyboard["events"] if _event_id(row) == event_id),
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "renderer_version": str(record.get("renderer_version") or "unknown"),
            "event_payload": next(
                row for row in storyboard["events"] if _event_id(row) == event_id
            ),
            "asset_hashes": sorted(event_snapshots[event_id].values()),
        }
        nodes.append({"id": event_id, "depends_on": list(record.get("depends_on") or [])})

    graph = DependencyGraph(nodes)
    render_order = graph.topological_order()
    for event_id in render_order:
        fingerprints[event_id]["dependency_event_keys"] = [
            build_event_key(fingerprints[dependency])
            for dependency in records[event_id].get("depends_on") or []
        ]
    plan = plan_event_rebuild(previous_fingerprints or {}, fingerprints, nodes)
    cache = EventCache(cache_root)
    segment_by_id: dict[str, dict[str, Any]] = {}
    cache_hits: list[str] = []
    executed: list[str] = []
    render_wall_seconds = 0.0
    for event_id in render_order:
        record = records[event_id]
        expected = Path(str(record["expected_artifact"])).resolve()
        key = build_event_key(fingerprints[event_id])
        cached = cache.lookup(key) if event_id in plan["reuse"] else None
        if cached is not None:
            source = Path(str(cached["outputs"][0]["cache_path"]))
            expected.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, expected)
            _validate_equivalence(record, f"event {event_id}")
            _validate_equivalence_after_render(record, f"event {event_id}")
            cache_hits.append(event_id)
        else:
            started = time.monotonic()
            _run_command(
                [str(value) for value in record["argv"]],
                cwd=Path(str(record["cwd"])).resolve(), expected=expected, runner=runner,
            )
            _validate_equivalence(record, f"event {event_id}")
            _validate_equivalence_after_render(record, f"event {event_id}")
            render_wall_seconds += time.monotonic() - started
            _assert_snapshot_unchanged(common_sources, common_snapshot, "shared render input")
            _assert_snapshot_unchanged(
                event_sources[event_id], event_snapshots[event_id], f"event {event_id} asset",
            )
            cache.store(key, {expected.name: expected})
            executed.append(event_id)
        _assert_snapshot_unchanged(common_sources, common_snapshot, "shared render input")
        segment_by_id[event_id] = {
            "event_id": event_id, "event_key": key,
            "path": str(expected), "sha256": sha256_file(expected),
        }
    segments = [segment_by_id[event_id] for event_id in expected_ids]

    assembly_expected = Path(str(assembly.get("expected_artifact") or "")).resolve()
    if assembly_expected != output.resolve():
        raise EventRenderUnavailable("event assembly output does not match full render output")
    assembly_fingerprint = {
        "event_id": "__assembly__",
        **common,
        "owner_artifact_sha256": storyboard_sha256,
        "renderer_version": str(assembly.get("renderer_version") or "unknown"),
        "event_payload": {
            "ordered_segments": [
                {"event_id": row["event_id"], "sha256": row["sha256"]} for row in segments
            ],
            "assembly_command": assembly.get("argv"),
        },
        "asset_hashes": [row["sha256"] for row in segments],
    }
    assembly_key = build_event_key(assembly_fingerprint)
    cached_assembly = cache.lookup(assembly_key)
    assembly_reused = cached_assembly is not None
    if cached_assembly is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(str(cached_assembly["outputs"][0]["cache_path"])), output)
        _validate_equivalence(assembly, "event assembly")
        _validate_equivalence_after_render(assembly, "event assembly")
    else:
        assembly_started = time.monotonic()
        _run_command(
            [str(value) for value in assembly.get("argv") or []],
            cwd=Path(str(assembly.get("cwd") or "")).resolve(),
            expected=output.resolve(), runner=runner,
        )
        _validate_equivalence(assembly, "event assembly")
        _validate_equivalence_after_render(assembly, "event assembly")
        render_wall_seconds += time.monotonic() - assembly_started
        _assert_snapshot_unchanged(common_sources, common_snapshot, "shared render input")
        cache.store(assembly_key, {output.name: output})
    _assert_snapshot_unchanged(common_sources, common_snapshot, "shared render input")
    estimated_by_event = {
        event_id: max(0.0, float(records[event_id].get("estimated_render_seconds") or 0.0))
        for event_id in expected_ids
    }
    provider_reservations = list(command_record.get("provider_reservations") or [])
    provider_actuals = list(command_record.get("provider_actuals") or [])
    return {
        "schema_version": 1,
        "mode": "hyperframes_event_cache",
        "plan": plan,
        "fingerprints": fingerprints,
        "segments": segments,
        "cache_hits": cache_hits,
        "executed_events": executed,
        "assembly_key": assembly_key,
        "assembly_reused": assembly_reused,
        "cost_accounting": {
            "executed_event_count": len(executed),
            "cache_hit_count": len(cache_hits),
            "retry_count": 0,
            "render_wall_seconds": round(render_wall_seconds, 6),
            "cache_saved_event_seconds": round(sum(
                estimated_by_event[event_id] for event_id in cache_hits
            ), 6),
            "provider_reservations": provider_reservations,
            "provider_actuals": provider_actuals,
            "provider_actual_cost": round(sum(
                float(row.get("actual_cost") or 0.0)
                for row in provider_actuals if isinstance(row, dict)
            ), 6),
            "unknown_costs_invented": False,
        },
        "output": str(output.resolve()),
        "output_sha256": sha256_file(output.resolve()),
        "equivalence": "explicit HyperFrames evidence required; no FFmpeg/PIL substitute",
    }
