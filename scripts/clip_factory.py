#!/usr/bin/env python3
"""Create evidence-bound clip candidates without changing or rendering the master."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _binding(path: Path | None) -> dict[str, Any]:
    if path is None or not path.resolve().is_file():
        return {"status": "unavailable"}
    path = path.resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def _edl_rows(edl: dict[str, Any]) -> list[tuple[float, float, float]]:
    rows: list[tuple[float, float, float]] = []
    cursor = 0.0
    for row in edl.get("ranges") or []:
        start = float(row.get("source_start", row.get("start")))
        end = float(row.get("source_end", row.get("end")))
        timeline_start = float(row.get("timeline_start", cursor))
        if end > start:
            rows.append((start, end, timeline_start))
            cursor = timeline_start + end - start
    return rows


def _derive_times(word_rows: list[dict[str, Any]], edl: dict[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        source_start = min(float(row["start"]) for row in word_rows)
        source_end = max(float(row["end"]) for row in word_rows)
    except (KeyError, TypeError, ValueError):
        return None
    containing = [row for row in _edl_rows(edl)
                  if source_start >= row[0] - 1e-6 and source_end <= row[1] + 1e-6]
    if len(containing) != 1 or source_end <= source_start:
        return None
    retained_start, _retained_end, timeline_start = containing[0]
    return (
        source_start, source_end,
        timeline_start + source_start - retained_start,
        timeline_start + source_end - retained_start,
    )


def build_clip_manifest(
    *, transcript_path: Path, edl_path: Path, semantic_brief_path: Path,
    output_timeline_path: Path, hook_path: Path | None, production_contract_path: Path,
    orientation: str, output: Path,
) -> dict[str, Any]:
    transcript = read_json(transcript_path.resolve())
    edl = read_json(edl_path.resolve())
    brief = read_json(semantic_brief_path.resolve())
    words = {str(row.get("id")): row for row in transcript.get("words") or []}
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for event in brief.get("events") or []:
        event_id = str(event.get("id") or "")
        ids = [str(value) for value in event.get("transcript_word_ids") or []]
        reason = None
        if event.get("clip_candidate") is not True:
            reason = "semantic brief did not select this event as a clip candidate"
        elif not event.get("viewer_takeaway"):
            reason = "candidate lacks an independent viewer takeaway"
        elif not ids or any(value not in words for value in ids):
            reason = "candidate lacks complete word evidence"
        derived = _derive_times([words[value] for value in ids if value in words], edl) if ids else None
        if derived is None:
            source_start = source_end = output_start = output_end = 0.0
            reason = "candidate timing cannot be derived from word evidence and retained EDL"
        else:
            source_start, source_end, output_start, output_end = derived
            try:
                declared = tuple(float(event[field]) for field in (
                    "source_start", "source_end", "output_start", "output_end",
                ))
            except (KeyError, TypeError, ValueError):
                reason = "candidate timing is incomplete"
            else:
                if any(abs(left - right) > 0.05 for left, right in zip(declared, derived)):
                    reason = "candidate timing conflicts with word evidence or EDL mapping"
        if reason:
            rejected.append({"event_id": event_id, "reason": reason})
            continue
        candidates.append({
            "clip_id": f"clip-{event_id}", "event_id": event_id,
            "source_start": source_start, "source_end": source_end,
            "output_start": output_start, "output_end": output_end,
            "word_ids": ids, "transcript_quote": event.get("transcript_quote"),
            "title_suggestion": event.get("viewer_takeaway"),
            "independence_score": 1.0,
            "cut_reason": event.get("cut_reason") or "approved self-contained semantic event",
            "orientation": orientation,
            "render_contract": "video-use timeline + HyperFrames motion + FFmpeg encode",
        })
    implementation = Path(__file__).resolve()
    report = {
        "schema_version": 1,
        "status": "selected" if candidates else "not_selected",
        "master_unchanged": True,
        "reuses_existing_transcript": True,
        "orientation": orientation,
        "inputs": {
            "transcript": _binding(transcript_path), "edl": _binding(edl_path),
            "semantic_brief": _binding(semantic_brief_path),
            "output_timeline": _binding(output_timeline_path), "hook": _binding(hook_path),
            "production_contract": _binding(production_contract_path),
        },
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "candidates": candidates, "rejected": rejected,
    }
    report["integrity_sha256"] = _stable_hash(report)
    write_json(output.resolve(), report)
    return report


def validate_clip_manifest(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("clip manifest schema_version must be 1")
    if report.get("status") not in {"selected", "not_selected"}:
        errors.append("clip manifest status is invalid")
    if report.get("status") == "selected" and not report.get("candidates"):
        errors.append("selected clip manifest has no candidates")
    inputs = report.get("inputs") or {}
    for label, row in (report.get("inputs") or {}).items():
        if row.get("status") == "unavailable":
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or row.get("sha256") != (sha256_file(path) if path.is_file() else None):
            errors.append(f"clip manifest input {label} is stale")
    transcript_row = inputs.get("transcript") or {}; edl_row = inputs.get("edl") or {}
    transcript_path = Path(str(transcript_row.get("path") or ""))
    edl_path = Path(str(edl_row.get("path") or ""))
    if transcript_path.is_file() and edl_path.is_file():
        words = {str(row.get("id")): row for row in read_json(transcript_path).get("words") or []}
        edl = read_json(edl_path)
        for index, candidate in enumerate(report.get("candidates") or []):
            ids = [str(value) for value in candidate.get("word_ids") or []]
            if not ids or any(value not in words for value in ids):
                errors.append(f"clip candidate {index} word evidence is stale")
                continue
            derived = _derive_times([words[value] for value in ids], edl)
            observed = tuple(float(candidate.get(field, -1)) for field in (
                "source_start", "source_end", "output_start", "output_end",
            ))
            if derived is None or any(abs(left - right) > 0.05 for left, right in zip(observed, derived)):
                errors.append(f"clip candidate {index} timing is not derived from words and EDL")
    if report.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in report.items() if key != "integrity_sha256"}
    ):
        errors.append("clip manifest integrity hash is stale")
    implementation = report.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("clip manifest implementation binding is stale")
    return errors
