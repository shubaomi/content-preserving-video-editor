#!/usr/bin/env python3
"""Blocking aesthetic QA for a HyperFrames sample or final composition."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from director_contracts import REQUIRED_VISUAL_FIELDS, sha256_file, visual_signature, write_json


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

MIN_REVIEW_IMAGE_SHORT_EDGE_PX = 180
MIN_REVIEW_IMAGE_LONG_EDGE_PX = 320
MIN_ANATOMY_IMAGE_EDGE_PX = 256
REQUIRED_ANATOMY_EVIDENCE_ROLES = ("full_frame", "left_hand", "right_hand")


def _image_evidence_errors(
    value: Any,
    label: str,
    *,
    minimum_short_edge: int = MIN_REVIEW_IMAGE_SHORT_EDGE_PX,
    minimum_long_edge: int = MIN_REVIEW_IMAGE_LONG_EDGE_PX,
) -> list[str]:
    """Reject placeholder files while accepting legacy paths and hash-bound records."""
    record = value if isinstance(value, dict) else {"path": value}
    path_value = record.get("path")
    if not path_value:
        return [f"{label} is missing"]
    path = Path(str(path_value))
    if not path.is_file():
        return [f"{label} is missing"]
    declared_hash = record.get("sha256")
    if isinstance(value, dict):
        if not re.fullmatch(r"[0-9a-f]{64}", str(declared_hash or "")):
            return [f"{label} structured record requires sha256"]
        if declared_hash != sha256_file(path):
            return [f"{label} hash does not match"]
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError, ValueError):
        return [f"{label} is not a decodable image"]
    if min(width, height) < minimum_short_edge or max(width, height) < minimum_long_edge:
        return [f"{label} is too small for full-size visual review"]
    return []


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
            anatomy_errors: list[str] = []
            role_records: dict[str, list[tuple[str, str]]] = {
                role: [] for role in REQUIRED_ANATOMY_EVIDENCE_ROLES
            }
            for index, item in enumerate(evidence):
                record = item if isinstance(item, dict) else {"path": item}
                role_value = record.get("role") if isinstance(item, dict) else (
                    REQUIRED_ANATOMY_EVIDENCE_ROLES[index]
                    if index < len(REQUIRED_ANATOMY_EVIDENCE_ROLES) else ""
                )
                role = str(role_value or "").strip()
                path_value = record.get("path")
                path = Path(str(path_value)).resolve() if path_value else None
                if role in role_records and path is not None and path.is_file():
                    role_records[role].append((str(path), sha256_file(path)))
                anatomy_errors.extend(_image_evidence_errors(
                    item,
                    f"generated human anatomy evidence[{index}]",
                    minimum_short_edge=MIN_ANATOMY_IMAGE_EDGE_PX,
                    minimum_long_edge=MIN_ANATOMY_IMAGE_EDGE_PX,
                ))
            if any(len(role_records[role]) != 1 for role in REQUIRED_ANATOMY_EVIDENCE_ROLES):
                anatomy_errors.append(
                    "generated human anatomy evidence roles must include exactly one full_frame, "
                    "left_hand, and right_hand"
                )
            required_records = [
                role_records[role][0]
                for role in REQUIRED_ANATOMY_EVIDENCE_ROLES
                if len(role_records[role]) == 1
            ]
            if (
                len(required_records) != len(REQUIRED_ANATOMY_EVIDENCE_ROLES)
                or len({path for path, _ in required_records}) != 3
                or len({digest for _, digest in required_records}) != 3
            ):
                anatomy_errors.append(
                    "generated human anatomy requires three unique role-specific evidence images"
                )
            if len(evidence) < 3 or anatomy_errors:
                errors.append(
                    "generated human anatomy requires existing full-resolution, left-hand, and right-hand evidence"
                )
                errors.extend(anatomy_errors)
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
            if not evidence:
                errors.append(f"event {event_id} missing {phase} snapshot evidence")
            else:
                errors.extend(_image_evidence_errors(
                    evidence, f"event {event_id} {phase} snapshot evidence",
                ))
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
            if not evidence:
                errors.append(f"event {event_id} connector geometry evidence is missing")
            else:
                errors.extend(_image_evidence_errors(
                    evidence, f"event {event_id} connector geometry evidence",
                ))
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
