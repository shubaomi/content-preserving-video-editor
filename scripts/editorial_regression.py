#!/usr/bin/env python3
"""Auditable structural regression for approved editorial decisions."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, UnidentifiedImageError

from correction_ledger import validate_ledger
from director_contracts import LOW_INFORMATION_ANCHORS, normalized_anchor, read_json, sha256_file, write_json


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _binding(path: Path | None) -> dict[str, Any]:
    if path is None or not path.resolve().is_file():
        return {"status": "unavailable"}
    path = path.resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def _normalized_bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        return {name: round(float(value[name]), 2) for name in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None


def _perceptual_image_hash(path: Path, bbox: dict[str, float] | None) -> str:
    try:
        with Image.open(path) as image:
            image = image.convert("L")
            if bbox and bbox["width"] > 0 and bbox["height"] > 0:
                width, height = image.size
                image = image.crop((
                    max(0, round(bbox["x"] * width)),
                    max(0, round(bbox["y"] * height)),
                    min(width, round((bbox["x"] + bbox["width"]) * width)),
                    min(height, round((bbox["y"] + bbox["height"]) * height)),
                ))
            resized = image.resize((16, 16))
            pixels = list(
                resized.get_flattened_data()
                if hasattr(resized, "get_flattened_data") else resized.getdata()
            )
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError(f"Golden representative snapshot is not decodable: {path}") from error
    mean = sum(pixels) / len(pixels)
    bits = "".join("1" if value >= mean else "0" for value in pixels)
    return f"{int(bits, 2):064x}"


def _runtime_signature(
    renderer_export_path: Path | None, keyframe_receipt_paths: Sequence[Path],
    motion_audio_decisions_path: Path | None,
) -> dict[str, Any] | None:
    if renderer_export_path is None:
        return None
    renderer_export_path = renderer_export_path.resolve()
    if not renderer_export_path.is_file():
        raise ValueError("Golden renderer export is missing")
    renderer = read_json(renderer_export_path)
    if not isinstance(renderer, dict) or not isinstance(renderer.get("events"), list):
        raise ValueError("Golden renderer export is invalid")
    receipts: dict[str, dict[str, Any]] = {}
    receipt_bindings: list[dict[str, Any]] = []
    for path in keyframe_receipt_paths:
        resolved = path.resolve()
        payload = read_json(resolved)
        if not isinstance(payload, dict) or not payload.get("event_id"):
            raise ValueError(f"Golden keyframe receipt is invalid: {resolved}")
        event_id = str(payload["event_id"])
        if event_id in receipts:
            raise ValueError(f"Golden keyframe receipt duplicates event {event_id}")
        receipts[event_id] = payload
        receipt_bindings.append(_binding(resolved))
    events: dict[str, Any] = {}
    for row in renderer["events"]:
        if not isinstance(row, dict) or not row.get("event_id"):
            raise ValueError("Golden renderer export contains an invalid event")
        event_id = str(row["event_id"])
        receipt = receipts.get(event_id)
        if receipt is None:
            raise ValueError(f"Golden keyframe receipt is missing for {event_id}")
        phases = receipt.get("phase_observations") or row.get("phases") or []
        if not isinstance(phases, list) or not phases:
            raise ValueError(f"Golden runtime phases are missing for {event_id}")
        dom_structure = row.get("dom_structure") or {
            "animation_targets": sorted(str(value) for value in row.get("animation_targets") or []),
            "visible_text_slots": len(row.get("visible_text") or []),
            "recipe_id": row.get("recipe_id"),
        }
        motion = [{
            "phase": phase.get("phase"),
            "animation_phase": phase.get("animation_phase"),
            "visible": phase.get("visible"),
        } for phase in phases if isinstance(phase, dict)]
        geometry = [{
            "phase": phase.get("phase"),
            "overlay_bbox": _normalized_bbox(phase.get("overlay_bbox")),
            "connectors": phase.get("connectors") or [],
            "targets": phase.get("target_observations") or [],
            "crop_status": phase.get("crop_status"),
        } for phase in phases if isinstance(phase, dict)]
        perceptual: dict[str, str] = {}
        for phase in phases:
            snapshot = (phase or {}).get("snapshot") if isinstance(phase, dict) else None
            if not isinstance(snapshot, dict) or not snapshot.get("path"):
                continue
            snapshot_path = Path(str(snapshot["path"])).resolve()
            if not snapshot_path.is_file() or snapshot.get("sha256") != sha256_file(snapshot_path):
                raise ValueError(f"Golden snapshot is missing or stale: {event_id}")
            bbox = _normalized_bbox(phase.get("overlay_bbox"))
            if bbox and bbox["width"] > 0 and bbox["height"] > 0:
                perceptual[str(phase.get("phase"))] = _perceptual_image_hash(
                    snapshot_path, bbox,
                )
        events[event_id] = {
            "dom_fingerprint_sha256": _stable_hash(dom_structure),
            "motion_fingerprint_sha256": _stable_hash(motion),
            "geometry_fingerprint_sha256": _stable_hash(geometry),
            "perceptual_hashes": perceptual,
        }
    audio_signature: dict[str, Any] | None = None
    if motion_audio_decisions_path is not None:
        manifest_path = motion_audio_decisions_path.resolve()
        if not manifest_path.is_file():
            raise ValueError("Golden motion-audio decision manifest is missing")
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("decisions"), list):
            raise ValueError("Golden motion-audio manifest must be an object with decisions")
        if not all(isinstance(record, dict) for record in manifest["decisions"]):
            raise ValueError("Golden motion-audio decisions must be objects")
        decisions = []
        for record in manifest.get("decisions") or []:
            path = Path(str(record.get("path") or "")).resolve()
            if not path.is_file() or record.get("sha256") != sha256_file(path):
                raise ValueError("Golden motion-audio decision is missing or stale")
            decision = read_json(path)
            if not isinstance(decision, dict):
                raise ValueError("Golden motion-audio decision must be an object")
            cue_value = decision.get("cue")
            mix_value = decision.get("mix_evidence")
            if cue_value is not None and not isinstance(cue_value, dict):
                raise ValueError("Golden motion-audio cue must be an object")
            if mix_value is not None and not isinstance(mix_value, dict):
                raise ValueError("Golden motion-audio mix evidence must be an object")
            cue = cue_value or {}
            mix = mix_value or {}
            decisions.append({
                "event_id": decision.get("event_id"), "decision": decision.get("decision"),
                "family": cue.get("family"),
                "motif_fingerprint_sha256": cue.get("motif_fingerprint_sha256"),
                "audibility_status": mix.get("audibility_status"),
            })
        audio_signature = {"fingerprint_sha256": _stable_hash(decisions), "decisions": decisions}
    return {
        "renderer_export": _binding(renderer_export_path),
        "keyframe_receipts": receipt_bindings,
        "motion_audio_decisions": _binding(motion_audio_decisions_path),
        "events": events,
        "audio": audio_signature,
    }


def _signature(storyboard: dict[str, Any], brief: dict[str, Any], audio: dict[str, Any] | None,
               cover: dict[str, Any] | None) -> dict[str, Any]:
    brief_events = {str(row.get("id")): row for row in brief.get("events") or []
                    if isinstance(row, dict)}
    events: dict[str, Any] = {}
    for index, row in enumerate(storyboard.get("events") or []):
        event_id = str(row.get("id") or f"event-{index}")
        semantic_row = brief_events.get(event_id)
        semantic = semantic_row or row
        visual = row.get("visual_structure") or {}
        connector = (row.get("geometry_contract") or {}).get("connector_contract") or {}
        audio_decision = semantic.get("audio_decision") or row.get("audio_decision") or {}
        storyboard_ip = row.get("treatment") == "ip_asset"
        semantic_ip = (semantic_row or {}).get("form") == "ip_asset"
        events[event_id] = {
            "anchor": str(semantic.get("anchor") or row.get("anchor") or ""),
            "family": str(visual.get("layout_archetype") or row.get("treatment") or "unknown"),
            "quiet": row.get("treatment") == "quiet_source",
            "ip_visual": storyboard_ip or semantic_ip,
            "connector_relations": connector.get("relations") or [],
            "sfx": audio_decision,
            "rejected": semantic.get("rejected") or [],
            "sources": {
                "anchor": "semantic_brief" if semantic_row and semantic_row.get("anchor") else "storyboard",
                "family": "storyboard", "quiet": "storyboard",
                "ip_visual": (
                    (["storyboard"] if storyboard_ip else [])
                    + (["semantic_brief"] if semantic_ip else [])
                    or ["storyboard", "semantic_brief"]
                ),
                "connector_relations": "storyboard",
                "sfx": "semantic_brief" if semantic_row and semantic_row.get("audio_decision") else "storyboard",
                "rejected": "semantic_brief" if semantic_row and "rejected" in semantic_row else "storyboard",
            },
        }
    return {
        "events": events,
        "families": dict(Counter(row["family"] for row in events.values() if not row["quiet"])),
        "quiet_event_ids": [event_id for event_id, row in events.items() if row["quiet"]],
        "ip_event_ids": [event_id for event_id, row in events.items() if row["ip_visual"]],
        "bgm": (audio or {}).get("bgm") or (audio or {}).get("audio_mix") or {},
        "cover_route": (cover or {}).get("route") or (cover or {}).get("mode"),
    }


def create_baseline(
    *, storyboard_path: Path, semantic_brief_path: Path, audio_plan_path: Path | None,
    cover_plan_path: Path | None, correction_ledger_path: Path | None,
    approved_by: str, output: Path, renderer_export_path: Path | None = None,
    keyframe_receipt_paths: Sequence[Path] = (),
    motion_audio_decisions_path: Path | None = None,
) -> dict[str, Any]:
    if not approved_by.strip():
        raise ValueError("approved_by is required")
    storyboard = read_json(storyboard_path.resolve())
    brief = read_json(semantic_brief_path.resolve())
    audio = read_json(audio_plan_path.resolve()) if audio_plan_path and audio_plan_path.is_file() else None
    cover = read_json(cover_plan_path.resolve()) if cover_plan_path and cover_plan_path.is_file() else None
    implementation = Path(__file__).resolve()
    runtime = _runtime_signature(
        renderer_export_path, keyframe_receipt_paths, motion_audio_decisions_path,
    )
    baseline = {
        "schema_version": 2 if runtime is not None else 1,
        "approved_by": approved_by.strip(),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "storyboard": _binding(storyboard_path), "semantic_brief": _binding(semantic_brief_path),
            "audio_plan": _binding(audio_plan_path), "cover_plan": _binding(cover_plan_path),
        },
        "correction_ledger_at_approval": _binding(correction_ledger_path),
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "signature": _signature(storyboard, brief, audio, cover),
        "tolerances": {
            "maximum_family_ratio": 0.65,
            "maximum_perceptual_hamming_distance": 24,
            "new_semantic_events_allowed": True,
        },
    }
    if runtime is not None:
        baseline["runtime_signature"] = runtime
    baseline["integrity_sha256"] = _stable_hash(baseline)
    write_json(output.resolve(), baseline)
    return baseline


def validate_baseline(baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if baseline.get("schema_version") not in {1, 2}:
        errors.append("golden editorial baseline schema_version must be 1 or 2")
    if not str(baseline.get("approved_by") or "").strip() or not baseline.get("approved_at"):
        errors.append("golden editorial baseline approval evidence is missing")
    for label, row in (baseline.get("inputs") or {}).items():
        if row.get("status") == "unavailable":
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or row.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append(f"golden editorial baseline input {label} is stale")
    runtime = baseline.get("runtime_signature")
    if baseline.get("schema_version") == 2:
        if not isinstance(runtime, dict) or not (runtime.get("events") or {}):
            errors.append("golden editorial runtime signature is missing")
        else:
            bindings = [runtime.get("renderer_export"), *(runtime.get("keyframe_receipts") or [])]
            audio_binding = runtime.get("motion_audio_decisions")
            if isinstance(audio_binding, dict) and audio_binding.get("status") != "unavailable":
                bindings.append(audio_binding)
            for index, row in enumerate(bindings):
                if not isinstance(row, dict) or not row.get("path"):
                    errors.append(f"golden runtime evidence[{index}] binding is invalid")
                    continue
                path = Path(str(row["path"])).resolve()
                if not path.is_file() or row.get("sha256") != sha256_file(path):
                    errors.append(f"golden runtime evidence[{index}] is stale")
    implementation = baseline.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("golden editorial baseline implementation binding is stale")
    if baseline.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in baseline.items() if key != "integrity_sha256"}
    ):
        errors.append("golden editorial baseline integrity hash is stale")
    return errors


PROPERTY_ALIASES = {
    "anchor": "anchor",
    "visual_structure.layout_archetype": "family",
    "family": "family",
    "quiet": "quiet",
    "ip_visual": "ip_visual",
    "geometry_contract.connector_contract.relations": "connector_relations",
    "connector_relations": "connector_relations",
    "audio_decision": "sfx",
    "sfx": "sfx",
    "rejected": "rejected",
    "event.removed": "event_removed",
    "bgm": "bgm",
    "cover_route": "cover_route",
}


def _approved_changes(
    ledger_path: Path | None, baseline: dict[str, Any], *,
    storyboard_path: Path, semantic_brief_path: Path,
    audio_plan_path: Path | None, cover_plan_path: Path | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    if ledger_path is None or not ledger_path.is_file():
        return {}
    ledger = validate_ledger(ledger_path)
    allowed: dict[tuple[str, str], dict[str, Any]] = {}
    signature = baseline.get("signature") or {}
    baseline_events = signature.get("events") or {}
    baseline_inputs = baseline.get("inputs") or {}
    for row in ledger.get("entries") or []:
        event_id = str(row["event_id"]); property_name = str(row["property"])
        field = PROPERTY_ALIASES.get(property_name)
        if field is None:
            continue
        if field == "event_removed":
            baseline_value = False if event_id in baseline_events else None
            expected_selector = event_id
            input_label = "storyboard"
            current_path = storyboard_path
        elif field in {"bgm", "cover_route"}:
            baseline_value = signature.get(field)
            expected_selector = field
            input_label = "audio_plan" if field == "bgm" else "cover_plan"
            current_path = audio_plan_path if field == "bgm" else cover_plan_path
        else:
            baseline_value = (baseline_events.get(event_id) or {}).get(field)
            expected_selector = event_id
            source_value = ((baseline_events.get(event_id) or {}).get("sources") or {}).get(
                field, "storyboard",
            )
            input_labels = source_value if isinstance(source_value, list) else [str(source_value)]
            current_paths = [
                semantic_brief_path if label == "semantic_brief" else storyboard_path
                for label in input_labels
            ]
        target = row.get("target") or {}
        target_file = str(target.get("file") or "")
        selector = str(target.get("selector") or "")
        if field in {"event_removed", "bgm", "cover_route"}:
            input_labels = [input_label]
            current_paths = [current_path]
        allowed_files = {
            str(Path(value).resolve())
            for label, path_value in zip(input_labels, current_paths)
            for value in (
                (baseline_inputs.get(label) or {}).get("path"),
                str(path_value.resolve()) if path_value is not None else None,
            ) if value
        }
        related_files = {
            str(Path(str(item.get("path"))).resolve())
            for item in row.get("related_files") or [] if item.get("path")
        }
        guarded_files = {str(Path(target_file).resolve())} if target_file else allowed_files
        if (
            row.get("before_value") == baseline_value
            and (not target_file or str(Path(target_file).resolve()) in allowed_files)
            and (not selector or expected_selector in selector)
            and bool(related_files & guarded_files)
        ):
            allowed[(event_id, field)] = row
    return allowed


def evaluate_regression(
    *, baseline: dict[str, Any], storyboard_path: Path, semantic_brief_path: Path,
    correction_ledger_path: Path | None, baseline_path: Path | None = None,
    audio_plan_path: Path | None = None, cover_plan_path: Path | None = None,
    renderer_export_path: Path | None = None,
    keyframe_receipt_paths: Sequence[Path] = (),
    motion_audio_decisions_path: Path | None = None,
) -> dict[str, Any]:
    baseline_errors = validate_baseline(baseline)
    if baseline_errors:
        raise ValueError("invalid golden editorial baseline: " + "; ".join(baseline_errors))
    storyboard_path = storyboard_path.resolve()
    semantic_brief_path = semantic_brief_path.resolve()
    audio = read_json(audio_plan_path) if audio_plan_path and audio_plan_path.is_file() else None
    cover = read_json(cover_plan_path) if cover_plan_path and cover_plan_path.is_file() else None
    signature = _signature(
        read_json(storyboard_path), read_json(semantic_brief_path), audio, cover,
    )
    findings: list[dict[str, Any]] = []
    runtime_signature: dict[str, Any] | None = None
    baseline_runtime = baseline.get("runtime_signature")
    if isinstance(baseline_runtime, dict):
        if renderer_export_path is None:
            findings.append({"code": "runtime_evidence_missing"})
        else:
            try:
                runtime_signature = _runtime_signature(
                    renderer_export_path, keyframe_receipt_paths,
                    motion_audio_decisions_path,
                )
            except ValueError as error:
                findings.append({"code": "runtime_evidence_invalid", "reason": str(error)})
            if runtime_signature is not None:
                baseline_events_runtime = baseline_runtime.get("events") or {}
                current_events_runtime = runtime_signature.get("events") or {}
                baseline_event_ids = set(baseline_events_runtime)
                current_event_ids = set(current_events_runtime)
                if baseline_event_ids != current_event_ids:
                    findings.append({
                        "code": "runtime_event_inventory_drift",
                        "missing_event_ids": sorted(baseline_event_ids - current_event_ids),
                        "extra_event_ids": sorted(current_event_ids - baseline_event_ids),
                    })
                for event_id in sorted(set(baseline_events_runtime) & set(current_events_runtime)):
                    before = baseline_events_runtime[event_id]
                    after = current_events_runtime[event_id]
                    for field, code in (
                        ("dom_fingerprint_sha256", "runtime_dom_drift"),
                        ("motion_fingerprint_sha256", "runtime_motion_drift"),
                        ("geometry_fingerprint_sha256", "runtime_geometry_drift"),
                    ):
                        if before.get(field) != after.get(field):
                            findings.append({
                                "code": code, "event_id": event_id,
                                "before": before.get(field), "after": after.get(field),
                            })
                    threshold = int((baseline.get("tolerances") or {}).get(
                        "maximum_perceptual_hamming_distance", 24
                    ))
                    baseline_hashes = before.get("perceptual_hashes") or {}
                    current_hashes = after.get("perceptual_hashes") or {}
                    if set(baseline_hashes) != set(current_hashes):
                        findings.append({
                            "code": "runtime_phase_inventory_drift",
                            "event_id": event_id,
                            "missing_phases": sorted(set(baseline_hashes) - set(current_hashes)),
                            "extra_phases": sorted(set(current_hashes) - set(baseline_hashes)),
                        })
                    for phase in sorted(set(baseline_hashes) & set(current_hashes)):
                        distance = (
                            int(baseline_hashes[phase], 16)
                            ^ int(current_hashes[phase], 16)
                        ).bit_count()
                        if distance > threshold:
                            findings.append({
                                "code": "runtime_perceptual_drift",
                                "event_id": event_id, "phase": phase,
                                "hamming_distance": distance, "maximum": threshold,
                            })
                if baseline_runtime.get("audio") != runtime_signature.get("audio"):
                    findings.append({"code": "runtime_audio_drift"})
    approved = _approved_changes(
        correction_ledger_path, baseline, storyboard_path=storyboard_path,
        semantic_brief_path=semantic_brief_path,
        audio_plan_path=audio_plan_path, cover_plan_path=cover_plan_path,
    )
    applied: list[str] = []
    low = {normalized_anchor(value) for value in LOW_INFORMATION_ANCHORS}
    events = signature["events"]
    for event_id, row in events.items():
        if normalized_anchor(row["anchor"]) in low:
            findings.append({"code": "low_information_anchor", "event_id": event_id})
    nonquiet_count = sum(signature["families"].values())
    if nonquiet_count >= 4 and signature["families"]:
        family, count = max(signature["families"].items(), key=lambda item: item[1])
        if count / nonquiet_count > float((baseline.get("tolerances") or {}).get(
            "maximum_family_ratio", 0.65
        )):
            findings.append({"code": "repeated_motion_family", "family": family,
                             "count": count, "total": nonquiet_count})
    baseline_events = (baseline.get("signature") or {}).get("events") or {}
    for event_id in sorted(set(baseline_events) - set(events)):
        correction = approved.get((event_id, "event_removed"))
        if correction and correction.get("after_value") is True:
            applied.append(f"{event_id}:event_removed")
        else:
            findings.append({"code": "approved_event_removed", "event_id": event_id})
    for event_id in sorted(set(baseline_events) & set(events)):
        for field in (
            "anchor", "family", "quiet", "ip_visual", "connector_relations", "sfx", "rejected",
        ):
            before = baseline_events[event_id].get(field)
            after = events[event_id].get(field)
            if before == after:
                continue
            property_name = field
            correction = approved.get((event_id, property_name))
            if correction and correction.get("after_value") == after:
                applied.append(f"{event_id}:{property_name}")
            else:
                findings.append({"code": "unapproved_editorial_drift", "event_id": event_id,
                                 "property": property_name, "before": before, "after": after})
    baseline_signature = baseline.get("signature") or {}
    for field in ("bgm", "cover_route"):
        before = baseline_signature.get(field); after = signature.get(field)
        if before != after:
            correction = approved.get(("__global__", field))
            if correction and correction.get("after_value") == after:
                applied.append(f"__global__:{field}")
                continue
            findings.append({"code": "unapproved_editorial_drift", "property": field,
                             "before": before, "after": after})
    implementation = Path(__file__).resolve()
    report = {
        "schema_version": 1,
        "status": "failed" if findings else "pass",
        "baseline_sha256": _stable_hash(baseline),
        "inputs": {
            "baseline": _binding(baseline_path),
            "storyboard": _binding(storyboard_path), "semantic_brief": _binding(semantic_brief_path),
            "audio_plan": _binding(audio_plan_path), "cover_plan": _binding(cover_plan_path),
            "correction_ledger": _binding(correction_ledger_path),
        },
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "signature": signature,
        "runtime_signature": runtime_signature,
        "approved_corrections_applied": applied,
        "findings": findings,
    }
    report["integrity_sha256"] = _stable_hash(report)
    return report


def validate_regression(
    report: dict[str, Any], baseline: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("editorial regression schema_version must be 1")
    if baseline is not None:
        errors.extend(validate_baseline(baseline))
        if report.get("baseline_sha256") != _stable_hash(baseline):
            errors.append("editorial regression baseline binding is stale")
    for label, row in (report.get("inputs") or {}).items():
        if row.get("status") == "unavailable":
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or row.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append(f"editorial regression input {label} is stale")
    expected = "failed" if report.get("findings") else "pass"
    if report.get("status") != expected:
        errors.append("editorial regression status does not match findings")
    if report.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in report.items() if key != "integrity_sha256"}
    ):
        errors.append("editorial regression integrity hash is stale")
    implementation = report.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("editorial regression implementation binding is stale")
    return errors
