#!/usr/bin/env python3
"""Blocking aesthetic QA for a HyperFrames sample or final composition."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from director_contracts import REQUIRED_VISUAL_FIELDS, visual_signature, write_json


REQUIRED_CRITERIA = (
    "directly_relevant_to_spoken_content",
    "adds_understanding_not_caption_repetition",
    "keyword_is_actual_sentence_focus",
    "layout_variety",
    "motion_matches_speech_rhythm",
    "no_caption_face_cursor_or_ui_occlusion",
    "ip_asset_integrates_with_footage",
    "connector_geometry_and_optical_alignment",
    "sfx_matches_motion",
    "cover_identity_expression_and_energy",
    "no_unexplained_long_visual_stagnation",
)

REQUIRED_PHASES = ("entrance", "midpoint", "pre_exit", "post_exit")
HUMAN_ANATOMY_CRITERION = "generated_human_anatomy"
REQUIRED_ANATOMY_CHECKS = (
    "full_resolution_reviewed",
    "left_hand_crop_reviewed",
    "right_hand_crop_reviewed",
    "intended_counts_match",
    "continuous_limb_connections",
    "no_extra_duplicated_fused_detached_or_ambiguous_limbs",
)


def _requires_human_anatomy_qa(storyboard: dict[str, Any]) -> bool:
    return any(
        isinstance((event.get("geometry_contract") or {}).get("anatomy_contract"), dict)
        for event in (storyboard.get("events") or [])
    )


def validate(review: dict[str, Any], storyboard: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    criteria = review.get("criteria") or {}
    for name in REQUIRED_CRITERIA:
        row = criteria.get(name)
        if not isinstance(row, dict):
            errors.append(f"missing aesthetic criterion: {name}")
            continue
        if row.get("status") != "pass":
            errors.append(f"aesthetic criterion is not pass: {name}")
        if not row.get("evidence"):
            errors.append(f"aesthetic criterion lacks evidence: {name}")
    if _requires_human_anatomy_qa(storyboard):
        row = criteria.get(HUMAN_ANATOMY_CRITERION)
        if not isinstance(row, dict):
            errors.append(f"missing aesthetic criterion: {HUMAN_ANATOMY_CRITERION}")
        else:
            if row.get("status") != "pass":
                errors.append(f"aesthetic criterion is not pass: {HUMAN_ANATOMY_CRITERION}")
            evidence = row.get("evidence") or []
            if len(evidence) < 3 or any(not Path(str(path)).is_file() for path in evidence):
                errors.append(
                    "generated human anatomy requires existing full-resolution, left-hand, and right-hand evidence"
                )
            checks = row.get("checks") or {}
            for name in REQUIRED_ANATOMY_CHECKS:
                if checks.get(name) is not True:
                    errors.append(f"generated human anatomy check is not pass: {name}")
    tech = review.get("technical_qa") or {}
    for name in ("hyperframes_check", "caption_sync", "overlap", "overflow", "decode"):
        if tech.get(name, {}).get("status") != "pass":
            errors.append(f"technical QA is not pass: {name}")
    events = [event for event in (storyboard.get("events") or []) if event.get("treatment") != "quiet_source"]
    signatures = {visual_signature(event) for event in events}
    if len(events) < 4 or len(signatures) < 4:
        errors.append("sample must contain at least four genuinely distinct visual structures")
    for signature in signatures:
        if len(signature) != len(REQUIRED_VISUAL_FIELDS) or any(not item for item in signature):
            errors.append("storyboard contains an incomplete visual structure signature")
    snapshots = review.get("snapshots") or {}
    connector_geometry = review.get("connector_geometry") or {}
    reviewed_event_ids = set(review.get("reviewed_event_ids") or [])
    for event in events:
        event_id = str(event.get("id", ""))
        if event_id not in reviewed_event_ids:
            errors.append(f"event not included in aesthetic review: {event_id}")
        phases = snapshots.get(event_id) or {}
        for phase in REQUIRED_PHASES:
            evidence = phases.get(phase)
            if not evidence or not Path(str(evidence)).is_file():
                errors.append(f"event {event_id} missing {phase} snapshot evidence")
        connector_contract = (event.get("geometry_contract") or {}).get("connector_contract")
        if isinstance(connector_contract, dict):
            row = connector_geometry.get(event_id)
            if not isinstance(row, dict):
                errors.append(f"event {event_id} is missing connector geometry review")
                continue
            required_count = int(connector_contract.get("required_connector_count", 0))
            if row.get("status") != "pass":
                errors.append(f"event {event_id} connector geometry review is not pass")
            if int(row.get("required_connector_count", -1)) != required_count:
                errors.append(f"event {event_id} connector required-count evidence does not match storyboard")
            if int(row.get("observed_connector_count", -1)) != required_count:
                errors.append(f"event {event_id} connector count does not match the declared contract")
            for check in ("all_endpoints_attached", "optically_aligned", "no_clipped_paths"):
                if row.get(check) is not True:
                    errors.append(f"event {event_id} connector check is not pass: {check}")
            evidence = row.get("evidence")
            if not evidence or not Path(str(evidence)).is_file():
                errors.append(f"event {event_id} connector geometry evidence is missing")
    if review.get("verdict") != "pass":
        errors.append("review verdict is not pass")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    review_path = Path(args.review).resolve()
    storyboard_path = Path(args.storyboard).resolve()
    review = json.loads(review_path.read_text(encoding="utf-8"))
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    errors = validate(review, storyboard)
    report = {
        "schema_version": 1,
        "review": str(review_path),
        "storyboard": str(storyboard_path),
        "passed": not errors,
        "errors": errors,
        "note": "Automated tests do not constitute aesthetic approval; this gate requires evidence-backed review.",
    }
    write_json(Path(args.report).resolve(), report)
    print(args.report)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
