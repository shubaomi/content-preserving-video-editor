#!/usr/bin/env python3
"""Prepare hash-bound, isolated WP6 Style Reel authorities from a user-confirmed proposal."""
from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file
from safe_generated_output import atomic_write_text, safe_generated_directory, safe_generated_target


class Wp6PreparationError(ValueError):
    """Raised before stale or unconfirmed WP6 authority data can be materialized."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Wp6PreparationError(f"{label} must be a mapping")
    return value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Wp6PreparationError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise Wp6PreparationError(f"{label} must be a finite number")
    return result


def _checked_ref(value: Any, label: str) -> Path:
    row = _mapping(value, label)
    raw = row.get("path")
    if not isinstance(raw, str) or not raw.strip():
        raise Wp6PreparationError(f"{label} path is missing")
    path = Path(raw)
    if not path.is_absolute() or not path.is_file():
        raise Wp6PreparationError(f"{label} file is missing: {path}")
    digest = row.get("sha256")
    if not isinstance(digest, str) or digest != sha256_file(path):
        raise Wp6PreparationError(f"{label} hash is stale")
    return path.resolve()


def _write_json(root: Path, relative: Path, payload: Any) -> Path:
    target = safe_generated_target(root, relative)
    atomic_write_text(target, json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False,
    ) + "\n")
    return target.resolve()


def _file_ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256_file(path.resolve())}


def _event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("semantic_event_id") or row.get("id") or "")


def prepare_wp6_authorities(
    *, proposal_path: Path, confirmed_original_start: float,
    confirmed_original_end: float, output_dir: Path, authorized_root: Path,
) -> dict[str, Any]:
    proposal_path = Path(proposal_path).resolve()
    try:
        proposal = read_json(proposal_path)
    except (OSError, json.JSONDecodeError) as error:
        raise Wp6PreparationError(f"WP6 proposal is invalid: {error}") from error
    proposal = _mapping(proposal, "WP6 proposal")
    if (
        proposal.get("artifact_type") != "portrait_style_reel_v2_window_proposal"
        or proposal.get("status") != "action_required"
    ):
        raise Wp6PreparationError("WP6 proposal is not awaiting a window confirmation")
    proposed = _mapping(proposal.get("proposed_window"), "WP6 proposed window")
    original = _mapping(proposed.get("original_source"), "WP6 original window")
    relative = _mapping(proposed.get("existing_canary_relative"), "WP6 canary window")
    proposed_original_start = _finite(original.get("start_seconds"), "proposal original start")
    proposed_original_end = _finite(original.get("end_seconds"), "proposal original end")
    if (
        abs(_finite(confirmed_original_start, "confirmed original start") - proposed_original_start) > 0.001
        or abs(_finite(confirmed_original_end, "confirmed original end") - proposed_original_end) > 0.001
    ):
        raise Wp6PreparationError("confirmed window does not equal the current proposal")
    source_start = _finite(relative.get("start_seconds"), "canary start")
    source_end = _finite(relative.get("end_seconds"), "canary end")
    duration = source_end - source_start
    if not 30.0 <= duration <= 45.0:
        raise Wp6PreparationError("confirmed WP6 window must be 30 to 45 seconds")

    authorities = _mapping(proposal.get("authorities"), "WP6 proposal authorities")
    source = _checked_ref(authorities.get("existing_canary_source"), "canary source")
    transcript_path = _checked_ref(authorities.get("transcript"), "word transcript")
    semantic_path = _checked_ref(authorities.get("semantic_brief"), "semantic brief")
    transcript = _mapping(read_json(transcript_path), "word transcript")
    brief = _mapping(read_json(semantic_path), "semantic brief")
    words = transcript.get("words")
    events = brief.get("events")
    coverage = proposal.get("semantic_coverage")
    if not isinstance(words, list) or not isinstance(events, list) or not isinstance(coverage, list):
        raise Wp6PreparationError("WP6 proposal authority collections are malformed")
    selected_ids: list[str] = []
    selected_decisions: dict[str, str] = {}
    for index, row in enumerate(coverage):
        if not isinstance(row, Mapping):
            raise Wp6PreparationError(f"semantic coverage row {index} is malformed")
        event_id = str(row.get("semantic_event_id") or "")
        decision = str(row.get("decision") or "")
        if not event_id or event_id in selected_decisions or decision not in {
            "render", "annotation", "caption_only", "reuse_source", "quiet_source",
        }:
            raise Wp6PreparationError("semantic coverage decision inventory is invalid")
        selected_ids.append(event_id)
        selected_decisions[event_id] = decision
    brief_by_id = {
        _event_id(row): row for row in events if isinstance(row, Mapping) and _event_id(row)
    }
    selected_events: list[dict[str, Any]] = []
    for event_id in selected_ids:
        row = brief_by_id.get(event_id)
        if not isinstance(row, Mapping) or row.get("decision") != selected_decisions[event_id]:
            raise Wp6PreparationError(f"semantic coverage decision is stale: {event_id}")
        start = _finite(row.get("output_start"), f"{event_id} output_start")
        end = _finite(row.get("output_end"), f"{event_id} output_end")
        if start < source_start - 0.001 or end > source_end + 0.001:
            raise Wp6PreparationError(f"semantic event lies outside the confirmed window: {event_id}")
        selected_events.append(deepcopy(dict(row)))
    if not any(value == "render" for value in selected_decisions.values()):
        raise Wp6PreparationError("confirmed WP6 window requires at least one render event")

    selected_words: list[dict[str, Any]] = []
    rebased_words: list[dict[str, Any]] = []
    for index, row in enumerate(words):
        if not isinstance(row, Mapping):
            raise Wp6PreparationError(f"transcript word {index} is malformed")
        start = _finite(row.get("start"), f"word {index} start")
        end = _finite(row.get("end"), f"word {index} end")
        if end <= source_start or start >= source_end:
            continue
        selected_words.append(deepcopy(dict(row)))
        rebased = deepcopy(dict(row))
        rebased["start"] = round(max(start, source_start) - source_start, 6)
        rebased["end"] = round(min(end, source_end) - source_start, 6)
        rebased_words.append(rebased)
    if not selected_words:
        raise Wp6PreparationError("confirmed WP6 window contains no transcript words")

    authorized_root = Path(authorized_root)
    output_dir = Path(output_dir)
    try:
        relative_output = output_dir.absolute().relative_to(authorized_root.absolute())
    except ValueError as error:
        raise Wp6PreparationError("WP6 authority output must stay under its authorized root") from error
    safe_generated_directory(authorized_root, relative_output)
    rel = relative_output
    source_ref = _file_ref(source)
    validation_edl = {
        "schema_version": 1, "owner": "video-use",
        "sources": {source.name: source_ref},
        "ranges": [{"source": source.name, "start": source_start, "end": source_end,
                    "timeline_start": source_start}],
    }
    caption_edl = {
        "schema_version": 1, "owner": "video-use",
        "sources": {source.name: source_ref},
        "ranges": [{"source": source.name, "start": source_start, "end": source_end,
                    "timeline_start": 0.0}],
    }
    outputs = {
        "validation_edl": _write_json(authorized_root, rel / "validation-edl.json", validation_edl),
        "caption_edl": _write_json(authorized_root, rel / "caption-edl.json", caption_edl),
        "source_transcript": _write_json(
            authorized_root, rel / "source-transcript.json", {"words": selected_words},
        ),
        "output_transcript": _write_json(
            authorized_root, rel / "output-transcript.json", {"words": rebased_words},
        ),
        "semantic_brief": _write_json(
            authorized_root, rel / "semantic-brief.json", {**{
                key: deepcopy(value) for key, value in brief.items() if key != "events"
            }, "events": selected_events},
        ),
    }
    manifest = {
        "schema_version": 1,
        "artifact_type": "portrait_style_reel_wp6_authority_manifest",
        "status": "prepared",
        "project_id": str(proposal.get("project_id") or ""),
        "proposal": _file_ref(proposal_path),
        "confirmed_original_window": {
            "start_seconds": proposed_original_start, "end_seconds": proposed_original_end,
        },
        "source_window": {"start_seconds": source_start, "end_seconds": source_end},
        "duration_seconds": round(duration, 6),
        "semantic_event_ids": selected_ids,
        "event_decisions": selected_decisions,
        "artifacts": {name: _file_ref(path) for name, path in outputs.items()},
        "source": source_ref,
        "input_authorities": {
            "transcript": _file_ref(transcript_path), "semantic_brief": _file_ref(semantic_path),
        },
        "render_authorization": "style_reel_only",
        "full_video_render_authorized": False,
    }
    manifest_path = _write_json(authorized_root, rel / "wp6-authority-manifest.json", manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--confirmed-original-start", required=True, type=float)
    parser.add_argument("--confirmed-original-end", required=True, type=float)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--authorized-root", required=True)
    args = parser.parse_args()
    result = prepare_wp6_authorities(
        proposal_path=Path(args.proposal),
        confirmed_original_start=args.confirmed_original_start,
        confirmed_original_end=args.confirmed_original_end,
        output_dir=Path(args.output_dir), authorized_root=Path(args.authorized_root),
    )
    print(result["manifest_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
