#!/usr/bin/env python3
"""Auditable structural regression for approved editorial decisions."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    approved_by: str, output: Path,
) -> dict[str, Any]:
    if not approved_by.strip():
        raise ValueError("approved_by is required")
    storyboard = read_json(storyboard_path.resolve())
    brief = read_json(semantic_brief_path.resolve())
    audio = read_json(audio_plan_path.resolve()) if audio_plan_path and audio_plan_path.is_file() else None
    cover = read_json(cover_plan_path.resolve()) if cover_plan_path and cover_plan_path.is_file() else None
    implementation = Path(__file__).resolve()
    baseline = {
        "schema_version": 1,
        "approved_by": approved_by.strip(),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "storyboard": _binding(storyboard_path), "semantic_brief": _binding(semantic_brief_path),
            "audio_plan": _binding(audio_plan_path), "cover_plan": _binding(cover_plan_path),
        },
        "correction_ledger_at_approval": _binding(correction_ledger_path),
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "signature": _signature(storyboard, brief, audio, cover),
        "tolerances": {"maximum_family_ratio": 0.65, "new_semantic_events_allowed": True},
    }
    baseline["integrity_sha256"] = _stable_hash(baseline)
    write_json(output.resolve(), baseline)
    return baseline


def validate_baseline(baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if baseline.get("schema_version") != 1:
        errors.append("golden editorial baseline schema_version must be 1")
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
