#!/usr/bin/env python3
"""Build and validate a hash-bound paired creative-review contract."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file, write_json
from motion_contracts import validate_contract_schema


PHASES = ("entrance", "mid", "pre_exit", "post_exit")
NON_USER_REVIEWER_IDENTITIES = {
    "user", "agent", "director", "renderer", "multimodal-agent", "multimodal_agent",
}
SAMPLE_DURATION_RANGE_SECONDS = (60.0, 90.0)
SAMPLE_DURATION_ALIGNMENT_TOLERANCE_SECONDS = 0.5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_sample_pair_durations(
    baseline_duration_seconds: float, candidate_duration_seconds: float,
) -> list[str]:
    """Validate the Director's continuous paired-review sample boundary."""
    errors: list[str] = []
    try:
        baseline = float(baseline_duration_seconds)
        candidate = float(candidate_duration_seconds)
    except (TypeError, ValueError):
        return ["creative review sample durations must be numeric"]
    minimum, maximum = SAMPLE_DURATION_RANGE_SECONDS
    if not minimum <= baseline <= maximum or not minimum <= candidate <= maximum:
        errors.append("creative review baseline and candidate must each be 60-90 seconds")
    if abs(baseline - candidate) > SAMPLE_DURATION_ALIGNMENT_TOLERANCE_SECONDS:
        errors.append("creative review baseline and candidate durations are not aligned")
    return errors


def _artifact(path: Path, artifact_id: str, purpose: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"creative review artifact is missing: {path}")
    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": sha256_file(path),
        "purpose": purpose,
    }


def _media_artifact(
    path: Path, artifact_id: str, purpose: str, duration_seconds: float,
) -> dict[str, Any]:
    if isinstance(duration_seconds, bool) or float(duration_seconds) <= 0:
        raise ValueError(f"{artifact_id} duration must be positive")
    return {
        **_artifact(path, artifact_id, purpose),
        "duration_seconds": float(duration_seconds),
    }


def keyframe_receipts_sha256(paths: Mapping[str, Path]) -> str:
    rows = [
        {"event_id": str(event_id), "sha256": sha256_file(Path(path).resolve())}
        for event_id, path in sorted(paths.items())
    ]
    return _stable_hash(rows)


def _gate_passes(payload: Any) -> bool:
    return isinstance(payload, dict) and (
        payload.get("passed") is True
        or payload.get("status") == "pass"
        or payload.get("verdict") == "pass"
    )


def build_contract(
    *, project_id: str, baseline_path: Path, candidate_path: Path,
    baseline_duration_seconds: float, candidate_duration_seconds: float,
    motion_design_contract_path: Path, storyboard_path: Path,
    semantic_brief_path: Path, keyframe_receipt_paths: Mapping[str, Path],
    gate_report_paths: list[Path],
    audio_auditions: Mapping[str, Mapping[str, Path]], output: Path,
    motion_audio_decisions_path: Path | None = None,
) -> dict[str, Any]:
    """Create a pending contract from exact media, receipts, gates and auditions."""
    motion_design_contract_path = motion_design_contract_path.resolve()
    storyboard_path = storyboard_path.resolve()
    semantic_brief_path = semantic_brief_path.resolve()
    for path in (motion_design_contract_path, storyboard_path, semantic_brief_path):
        if not path.is_file():
            raise ValueError(f"creative review input is missing: {path}")
    motion = read_json(motion_design_contract_path)
    storyboard = read_json(storyboard_path)
    brief = read_json(semantic_brief_path)
    if not all(isinstance(value, dict) for value in (motion, storyboard, brief)):
        raise ValueError("creative review inputs must be JSON mappings")
    selected_ids = [str(value) for value in motion.get("selected_event_ids") or []]
    if not selected_ids:
        raise ValueError("creative review requires at least one compiled render event")
    opportunities = {
        str(row.get("semantic_event_id")): row
        for row in motion.get("opportunities") or [] if isinstance(row, dict)
    }
    brief_events = {
        str(row.get("id")): row for row in brief.get("events") or [] if isinstance(row, dict)
    }
    storyboard_ids = [
        str(row.get("semantic_event_id") or row.get("id") or "")
        for row in storyboard.get("events") or [] if isinstance(row, dict)
    ]
    if storyboard_ids != selected_ids:
        raise ValueError("creative review Storyboard differs from compiler-selected events")
    receipt_paths = {str(key): Path(value).resolve() for key, value in keyframe_receipt_paths.items()}
    if set(receipt_paths) != set(selected_ids):
        raise ValueError("creative review receipt set differs from compiler-selected events")
    comparisons: list[dict[str, Any]] = []
    for event_id in selected_ids:
        opportunity = opportunities.get(event_id) or {}
        receipt_path = receipt_paths[event_id]
        if not receipt_path.is_file():
            raise ValueError(f"creative review keyframe receipt is missing: {receipt_path}")
        receipt = read_json(receipt_path)
        phases = receipt.get("phase_observations") or []
        if [row.get("phase") for row in phases if isinstance(row, dict)] != list(PHASES):
            raise ValueError(f"creative review receipt lacks four phases: {event_id}")
        auditions = audio_auditions.get(event_id) or {}
        if not all(name in auditions for name in ("sfx_off", "sfx_on")):
            raise ValueError(f"creative review lacks SFX auditions: {event_id}")
        window = opportunity.get("output_window") or {}
        baseline_time = (
            float(window.get("start_seconds", 0)) + float(window.get("end_seconds", 0))
        ) / 2
        brief_event = brief_events.get(event_id) or {}
        source_sentence = str(
            brief_event.get("transcript_quote") or brief_event.get("anchor") or ""
        ).strip()
        if not source_sentence:
            raise ValueError(f"creative review source sentence is missing: {event_id}")
        phase_artifacts = {
            phase: _artifact(
                Path(str(row["snapshot"]["path"])), f"{event_id}-{phase}",
                f"{event_id} {phase} candidate phase",
            )
            for phase, row in zip(PHASES, phases)
        }
        audio_records = {
            name: _artifact(Path(path), f"{event_id}-{name}", f"{event_id} {name} audition")
            for name, path in auditions.items() if name in {"sfx_off", "sfx_on", "bgm_off", "bgm_on"}
        }
        comparisons.append({
            "event_id": event_id,
            "semantic_event_id": event_id,
            "source_sentence": source_sentence,
            "viewer_takeaway": str(opportunity.get("viewer_takeaway") or ""),
            "approved_visible_copy": list(opportunity.get("approved_visible_copy") or []),
            "baseline_timestamp_seconds": baseline_time,
            "candidate_timestamp_seconds": float(phases[1]["timestamp_seconds"]),
            "phase_artifacts": phase_artifacts,
            "target_binding_ids": list(opportunity.get("target_binding_ids") or []),
            "audio_auditions": audio_records,
        })
    gate_artifacts = [
        _artifact(Path(path), f"gate-{index + 1}", "automated creative prerequisite gate")
        for index, path in enumerate(gate_report_paths)
    ]
    if not gate_artifacts or not all(_gate_passes(read_json(Path(path))) for path in gate_report_paths):
        raise ValueError("creative review automated prerequisite gates are not passing")
    input_hashes = {
        "motion_design_contract_sha256": sha256_file(motion_design_contract_path),
        "storyboard_sha256": sha256_file(storyboard_path),
        "keyframe_receipts_sha256": keyframe_receipts_sha256(receipt_paths),
    }
    if motion_audio_decisions_path is not None:
        motion_audio_decisions_path = motion_audio_decisions_path.resolve()
        if not motion_audio_decisions_path.is_file():
            raise ValueError("creative review motion-audio decisions are missing")
        input_hashes["motion_audio_decisions_sha256"] = sha256_file(
            motion_audio_decisions_path,
        )
    created_at = _now()
    contract: dict[str, Any] = {
        "schema_version": "1.0.0",
        "review_id": f"creative-{_stable_hash([project_id, created_at, input_hashes])[:24]}",
        "project_id": project_id,
        "created_at": created_at,
        "producer": "content-preserving-video-editor.creative-review",
        "baseline": _media_artifact(
            baseline_path, "baseline-media", "unedited or clean A-roll comparison",
            baseline_duration_seconds,
        ),
        "candidate": _media_artifact(
            candidate_path, "candidate-media", "HyperFrames sample candidate",
            candidate_duration_seconds,
        ),
        "input_hashes": input_hashes,
        "event_comparisons": comparisons,
        "automated_status": {"status": "pass", "gate_reports": gate_artifacts},
        "multimodal_review": {
            "reviewer": "not-run", "reviewed_at": created_at,
            "recommendation": "not_run", "reasons": [], "evidence_refs": [],
        },
        "user_review": {"decision": "pending"},
        "correction_proposals": [],
        "status": "pending_user_review",
    }
    errors = validate_contract_schema("creative-review", contract)
    if errors:
        raise ValueError("creative review schema failed: " + "; ".join(errors))
    write_json(output.resolve(), contract)
    return contract


def _artifact_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} artifact is missing"]
    path = Path(str(value.get("path") or ""))
    if not path.is_absolute() or not path.is_file():
        return [f"{label} artifact is missing"]
    if value.get("sha256") != sha256_file(path):
        return [f"{label} artifact hash is stale"]
    return []


def validate_review(
    review: dict[str, Any], *, motion_design_contract_path: Path,
    storyboard_path: Path, keyframe_receipt_paths: Mapping[str, Path],
    motion_audio_decisions_path: Path | None,
    authorized_user_reviewers: set[str] | None = None,
) -> list[str]:
    """Validate schema, current hashes, paired events, receipts and actor boundary."""
    errors = validate_contract_schema("creative-review", review)
    if errors:
        return errors
    baseline = review.get("baseline") or {}
    candidate = review.get("candidate") or {}
    errors.extend(_artifact_errors(baseline, "creative review baseline"))
    errors.extend(_artifact_errors(candidate, "creative review candidate"))
    if baseline.get("sha256") == candidate.get("sha256"):
        errors.append("creative review baseline and candidate must be different media")
    motion_design_contract_path = motion_design_contract_path.resolve()
    storyboard_path = storyboard_path.resolve()
    inputs = review.get("input_hashes") or {}
    if not motion_design_contract_path.is_file() or inputs.get(
        "motion_design_contract_sha256"
    ) != (sha256_file(motion_design_contract_path) if motion_design_contract_path.is_file() else None):
        errors.append("creative review motion-design contract hash is stale")
    if not storyboard_path.is_file() or inputs.get("storyboard_sha256") != (
        sha256_file(storyboard_path) if storyboard_path.is_file() else None
    ):
        errors.append("creative review Storyboard hash is stale")
    receipt_paths = {str(key): Path(value).resolve() for key, value in keyframe_receipt_paths.items()}
    if any(not path.is_file() for path in receipt_paths.values()) or inputs.get(
        "keyframe_receipts_sha256"
    ) != keyframe_receipts_sha256(receipt_paths):
        errors.append("creative review keyframe receipt aggregate hash is stale")
    if motion_audio_decisions_path is not None:
        path = motion_audio_decisions_path.resolve()
        if not path.is_file() or inputs.get("motion_audio_decisions_sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append("creative review motion-audio decision hash is stale")
    try:
        motion = read_json(motion_design_contract_path)
        storyboard = read_json(storyboard_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return [*errors, "creative review bound JSON is unreadable"]
    selected_ids = [str(value) for value in motion.get("selected_event_ids") or []]
    storyboard_ids = [
        str(row.get("semantic_event_id") or row.get("id") or "")
        for row in storyboard.get("events") or [] if isinstance(row, dict)
    ]
    comparisons = review.get("event_comparisons") or []
    comparison_ids = [str(row.get("semantic_event_id") or "") for row in comparisons]
    if comparison_ids != selected_ids or storyboard_ids != selected_ids:
        errors.append("creative review event order differs from compiler-selected events")
    opportunities = {
        str(row.get("semantic_event_id")): row
        for row in motion.get("opportunities") or [] if isinstance(row, dict)
    }
    for comparison in comparisons:
        event_id = str(comparison.get("semantic_event_id") or "")
        opportunity = opportunities.get(event_id) or {}
        if comparison.get("event_id") != event_id:
            errors.append(f"creative review event identity differs: {event_id}")
        if comparison.get("viewer_takeaway") != opportunity.get("viewer_takeaway"):
            errors.append(f"creative review viewer takeaway is stale: {event_id}")
        if comparison.get("approved_visible_copy") != list(
            opportunity.get("approved_visible_copy") or []
        ):
            errors.append(f"creative review visible copy is stale: {event_id}")
        if comparison.get("target_binding_ids") != list(opportunity.get("target_binding_ids") or []):
            errors.append(f"creative review target bindings are stale: {event_id}")
        window = opportunity.get("output_window") or {}
        try:
            expected_baseline_time = (
                float(window["start_seconds"]) + float(window["end_seconds"])
            ) / 2
            actual_baseline_time = float(comparison.get("baseline_timestamp_seconds"))
        except (KeyError, TypeError, ValueError):
            errors.append(f"creative review baseline timestamp is invalid: {event_id}")
        else:
            if abs(actual_baseline_time - expected_baseline_time) > 1e-6:
                errors.append(f"creative review baseline timestamp is stale: {event_id}")
        receipt_path = receipt_paths.get(event_id)
        if receipt_path is None or not receipt_path.is_file():
            errors.append(f"creative review keyframe receipt is missing: {event_id}")
            continue
        try:
            receipt = read_json(receipt_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"creative review keyframe receipt is unreadable: {event_id}")
            continue
        observations = receipt.get("phase_observations") or []
        if [row.get("phase") for row in observations if isinstance(row, dict)] != list(PHASES):
            errors.append(f"creative review keyframe phases are incomplete: {event_id}")
            continue
        phase_artifacts = comparison.get("phase_artifacts") or {}
        for phase_name, observation in zip(PHASES, observations):
            actual = phase_artifacts.get(phase_name) or {}
            snapshot = observation.get("snapshot") or {}
            if (
                Path(str(actual.get("path") or "")).resolve()
                != Path(str(snapshot.get("path") or "")).resolve()
                or actual.get("sha256") != snapshot.get("sha256")
            ):
                errors.append(f"creative review phase artifact is stale: {event_id} {phase_name}")
            errors.extend(_artifact_errors(actual, f"creative review {event_id} {phase_name}"))
        if comparison.get("candidate_timestamp_seconds") != observations[1].get("timestamp_seconds"):
            errors.append(f"creative review candidate timestamp is stale: {event_id}")
        for name in ("sfx_off", "sfx_on"):
            errors.extend(_artifact_errors(
                (comparison.get("audio_auditions") or {}).get(name),
                f"creative review {event_id} {name}",
            ))
        for name in ("bgm_off", "bgm_on"):
            if name in (comparison.get("audio_auditions") or {}):
                errors.extend(_artifact_errors(
                    comparison["audio_auditions"][name],
                    f"creative review {event_id} {name}",
                ))
    gates = (review.get("automated_status") or {}).get("gate_reports") or []
    for gate in gates:
        errors.extend(_artifact_errors(gate, "creative review automated gate"))
        path = Path(str(gate.get("path") or ""))
        if path.is_file():
            try:
                gate_payload = read_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append("creative review automated gate is unreadable")
            else:
                if not _gate_passes(gate_payload):
                    errors.append("creative review automated gate is not passing")
    user = review.get("user_review") or {}
    decision = user.get("decision")
    expected_status = {
        "pending": "pending_user_review",
        "approved": "approved",
        "rejected": "rejected",
        "revision_requested": "revision_required",
        "not_applicable": "rejected",
    }.get(decision)
    if review.get("status") != expected_status and review.get("status") != "stale":
        errors.append("creative review status differs from user decision")
    if decision != "pending":
        reviewer = str(user.get("reviewer") or "")
        if reviewer.strip().lower() in NON_USER_REVIEWER_IDENTITIES:
            errors.append("creative review approval must be authored by an identified human user")
        if authorized_user_reviewers is not None and reviewer not in authorized_user_reviewers:
            errors.append("creative review was not authored by an authorized user")
        if not reviewer or not user.get("reviewed_at"):
            errors.append("creative review user decision lacks reviewer or time")
        if not str(user.get("reason") or "").strip():
            errors.append("creative review user decision lacks a reason")
    if decision == "approved" and (
        not user.get("publish_willingness") or not user.get("baseline_preference")
    ):
        errors.append("creative review approval lacks publish willingness or paired preference")
    if decision == "approved" and (review.get("automated_status") or {}).get("status") != "pass":
        errors.append("creative review cannot approve failed automated gates")
    if any(row.get("status") != "pending" for row in review.get("correction_proposals") or []):
        errors.append("creative review UI may only store a pending correction proposal")
    return errors


def record_user_decision(
    review: dict[str, Any], *, decision: str, reviewer: str,
    publish_willingness: str | None = None,
    baseline_preference: str | None = None, reason: str | None = None,
) -> dict[str, Any]:
    """Return a new contract containing an explicit human review decision."""
    if decision not in {"approved", "rejected", "revision_requested"}:
        raise ValueError("unsupported creative review user decision")
    if not reviewer.strip():
        raise ValueError("creative review user decision requires reviewer")
    if reviewer.strip().lower() in NON_USER_REVIEWER_IDENTITIES:
        raise ValueError("creative review decision requires an identified human user")
    if not reason or not reason.strip():
        raise ValueError("creative review user decision requires reason")
    if decision == "approved" and (
        publish_willingness not in {"yes", "no", "unsure"}
        or baseline_preference not in {"baseline", "candidate", "tie"}
    ):
        raise ValueError("approval requires publish willingness and paired preference")
    result = copy.deepcopy(review)
    user: dict[str, Any] = {
        "decision": decision, "reviewer": reviewer.strip(), "reviewed_at": _now(),
    }
    if publish_willingness is not None:
        user["publish_willingness"] = publish_willingness
    if baseline_preference is not None:
        user["baseline_preference"] = baseline_preference
    if reason and reason.strip():
        user["reason"] = reason.strip()
    result["user_review"] = user
    result["status"] = {
        "approved": "approved", "rejected": "rejected",
        "revision_requested": "revision_required",
    }[decision]
    return result


def mark_stale(review: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    """Invalidate prior approval without overwriting the historical input hashes."""
    result = copy.deepcopy(review)
    result["status"] = "stale"
    result["user_review"] = {"decision": "pending"}
    multimodal = result.get("multimodal_review") or {}
    multimodal["reasons"] = [*multimodal.get("reasons", []), *[str(value) for value in reasons]]
    result["multimodal_review"] = multimodal
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", type=Path, required=True)
    parser.add_argument("--motion-design-contract", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--receipt", action="append", default=[])
    parser.add_argument("--motion-audio-decisions", type=Path)
    args = parser.parse_args()
    receipt_paths: dict[str, Path] = {}
    for value in args.receipt:
        path = Path(value).resolve()
        event_id = str(read_json(path).get("event_id") or "")
        receipt_paths[event_id] = path
    errors = validate_review(
        read_json(args.validate),
        motion_design_contract_path=args.motion_design_contract,
        storyboard_path=args.storyboard,
        keyframe_receipt_paths=receipt_paths,
        motion_audio_decisions_path=args.motion_audio_decisions,
    )
    for error in errors:
        print(f"ERROR: {error}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
