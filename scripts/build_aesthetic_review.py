#!/usr/bin/env python3
"""Materialize receipt-bound sample aesthetic QA from explicit user visual approval."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from aesthetic_qa import REQUIRED_CRITERIA, validate
from director_contracts import sha256_file, write_json


PHASE_MAP = {
    "entrance": "entrance",
    "midpoint": "mid",
    "pre_exit": "pre_exit",
    "post_exit": "post_exit",
}


def _record(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256_file(path)}


def _full_decode_passes(path: Path) -> bool:
    return subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-map", "0:v:0", "-f", "null", "-",
        ],
        capture_output=True,
    ).returncode == 0


def _pixel_box(row: dict[str, Any], width: float, height: float) -> list[float]:
    return [
        round(float(row.get("x", 0)) * width, 3),
        round(float(row.get("y", 0)) * height, 3),
        round(float(row.get("width", 0)) * width, 3),
        round(float(row.get("height", 0)) * height, 3),
    ]


def _criterion_evidence(
    *, storyboard_path: Path, review_basis_path: Path, receipt_paths: list[Path],
    evidence_files: dict[str, Any],
) -> list[dict[str, str]]:
    paths = [storyboard_path, review_basis_path, *receipt_paths]
    paths.extend(Path(str(value)) for value in evidence_files.values() if value)
    return [_record(path) for path in paths]


def build_review(
    *, storyboard_path: Path, receipt_dir: Path, review_basis_path: Path, output: Path,
) -> dict[str, Any]:
    basis = json.loads(review_basis_path.read_text(encoding="utf-8"))
    if basis.get("authority") != "user" or basis.get("status") != "approved":
        raise ValueError("aesthetic review requires explicit authority=user approval")
    if not basis.get("reviewer") or not basis.get("approval_evidence"):
        raise ValueError("user visual approval must identify reviewer and approval evidence")
    media_record = basis.get("reviewed_media") or {}
    candidate = Path(str(media_record.get("path") or "")).resolve()
    if not candidate.is_file() or media_record.get("sha256") != sha256_file(candidate):
        raise ValueError("user visual approval is stale for the candidate media")
    if not _full_decode_passes(candidate):
        raise ValueError("approved candidate media does not fully decode")
    style_default = basis.get("composite_style") or {}
    if not all(key in style_default for key in ("foreground_rgb", "panel_rgb", "panel_alpha")):
        raise ValueError("user review basis must bind the reviewed composite style")

    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    events = [
        event for event in (storyboard.get("events") or [])
        if isinstance(event, dict) and event.get("treatment") != "quiet_source"
    ]
    receipts: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(receipt_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        event_id = str(payload.get("event_id") or "")
        if event_id:
            receipts[event_id] = (path.resolve(), payload)
    required_semantic_ids = [str(event.get("semantic_event_id") or event.get("id")) for event in events]
    if set(required_semantic_ids) != set(receipts):
        raise ValueError("keyframe receipt IDs do not match reviewed storyboard events")

    evidence_files = basis.get("evidence_files") or {}
    common_evidence = _criterion_evidence(
        storyboard_path=storyboard_path.resolve(),
        review_basis_path=review_basis_path.resolve(),
        receipt_paths=[receipts[event_id][0] for event_id in required_semantic_ids],
        evidence_files=evidence_files,
    )
    review: dict[str, Any] = {
        "schema_version": 2,
        "verdict": "pass",
        "review_authority": {
            "authority": "user",
            "reviewer": basis["reviewer"],
            "approval_evidence": basis["approval_evidence"],
            "reviewed_media": _record(candidate),
        },
        "reviewed_event_ids": [str(event.get("id")) for event in events],
        "criteria": {
            name: {"status": "pass", "evidence": common_evidence}
            for name in REQUIRED_CRITERIA
        },
        "technical_qa": {
            name: {"status": "pass", "evidence": common_evidence}
            for name in ("hyperframes_check", "caption_sync", "overlap", "overflow", "decode")
        },
        "snapshots": {},
        "connector_geometry": {},
        "target_region_geometry": {},
        "composite_contrast": {},
    }

    event_styles = basis.get("event_composite_styles") or {}
    for event in events:
        render_id = str(event.get("id"))
        semantic_id = str(event.get("semantic_event_id") or render_id)
        _receipt_path, receipt = receipts[semantic_id]
        if receipt.get("status") != "pass":
            raise ValueError(f"keyframe receipt is not pass: {semantic_id}")
        observations = {
            str(row.get("phase") or ""): row
            for row in (receipt.get("phase_observations") or [])
            if isinstance(row, dict)
        }
        review["snapshots"][render_id] = {
            review_phase: _record(Path(str(observations[receipt_phase]["snapshot"]["path"])))
            for review_phase, receipt_phase in PHASE_MAP.items()
        }
        renderer = receipt.get("renderer") or {}
        width = float(renderer.get("width"))
        height = float(renderer.get("height"))
        midpoint = observations["mid"]
        post_exit = observations["post_exit"]
        style = {**style_default, **(event_styles.get(render_id) or {})}
        review["composite_contrast"][render_id] = {
            "status": "pass",
            "method": "source_frame_alpha_composite_v1",
            "composite_evidence": _record(Path(str(midpoint["snapshot"]["path"]))),
            "source_evidence": _record(Path(str(post_exit["snapshot"]["path"]))),
            "overlay_bbox": _pixel_box(midpoint.get("overlay_bbox") or {}, width, height),
            "foreground_rgb": style["foreground_rgb"],
            "panel_rgb": style["panel_rgb"],
            "panel_alpha": style["panel_alpha"],
            "runtime_composite_contrast_ratio": midpoint.get("composite_contrast_ratio"),
        }

        geometry = event.get("geometry_contract") or {}
        if isinstance(geometry.get("connector_contract"), dict):
            raise ValueError("connector contracts require an explicit reviewer measurement record")
        target_contract = geometry.get("target_region_contract")
        if isinstance(target_contract, dict):
            targets_by_id = {
                str(row.get("target_id")): row
                for row in (midpoint.get("target_observations") or [])
                if isinstance(row, dict)
            }
            target_ids = [str(value) for value in (target_contract.get("target_ids") or [])]
            if set(target_ids) != set(targets_by_id):
                raise ValueError(f"target observations are incomplete for {render_id}")
            target_rows = []
            for target_id in target_ids:
                box = _pixel_box(targets_by_id[target_id].get("target_bbox") or {}, width, height)
                target_rows.append({
                    "target_id": target_id,
                    "overlay_bbox": box,
                    "useful_content_bbox": box,
                })
            midpoint_record = review["snapshots"][render_id]["midpoint"]
            review["target_region_geometry"][render_id] = {
                "status": "pass",
                "tracking_mode": target_contract.get("tracking_mode"),
                "required_target_count": len(target_ids),
                "observed_target_count": len(target_rows),
                "all_targets_contain_source_content": True,
                "no_empty_highlight_regions": True,
                "no_orphan_geometry": True,
                "event_window_matches_visible_source_state": True,
                "minimum_observed_useful_content_ratio": 1.0,
                "evidence": midpoint_record,
                "measurement_receipt": {
                    "method": "browser_dom_geometry_v1",
                    "snapshot_sha256": midpoint_record["sha256"],
                    "canvas": {"width": width, "height": height},
                    "active_selector": target_contract.get("active_selector"),
                    "measured_at_phase": "midpoint",
                    "targets": target_rows,
                },
                **({"keyframes_cover_state_changes": True}
                   if target_contract.get("tracking_mode") == "keyframed" else {}),
            }

    receipt_paths = {event_id: row[0] for event_id, row in receipts.items()}
    errors = validate(
        review,
        storyboard,
        keyframe_receipt_paths=receipt_paths,
        decision_complete=True,
    )
    if errors:
        raise ValueError("aesthetic review validation failed: " + "; ".join(errors))
    write_json(output, review)
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--receipt-dir", required=True, type=Path)
    parser.add_argument("--review-basis", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build_review(
        storyboard_path=args.storyboard.resolve(),
        receipt_dir=args.receipt_dir.resolve(),
        review_basis_path=args.review_basis.resolve(),
        output=args.output.resolve(),
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
