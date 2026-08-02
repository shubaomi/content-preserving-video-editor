#!/usr/bin/env python3
"""Propose scoped preferences from approved, hash-bound corrections only."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


ALLOWED_SOURCE_TYPES = {"correction_ledger", "cover_choice", "motion_choice"}
SENSITIVE_FIELD_PARTS = {
    "secret", "token", "password", "api_key", "credential", "private_source",
    "raw_transcript", "source_content",
}
LEARNABLE_FIELDS = {
    "anchor", "animation_preset", "caption_emphasis", "caption_treatment", "color",
    "cover_layout", "cover_strategy", "cover_tone", "density",
    "density_target_per_minute", "duration", "easing", "framing", "motion_family",
    "palette", "position", "profile", "rejected_patterns", "scale", "sfx",
    "sfx_cues_per_minute", "sfx_family", "typography", "variant",
    "visual_family_rotation",
}


def correction_id(entry: dict[str, Any]) -> str:
    """Return the correction-ledger compatible ID for an entry."""
    content = {key: value for key, value in entry.items() if key != "correction_id"}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _approved_entry(entry: dict[str, Any], index: int) -> dict[str, Any]:
    prefix = f"entries[{index}]"
    if entry.get("approved") is False or not str(entry.get("approved_by") or "").strip():
        raise ValueError(f"{prefix} is not an approved correction")
    try:
        datetime.fromisoformat(str(entry.get("approved_at") or "").replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{prefix} is not an approved correction") from error
    expected_id = correction_id(entry)
    if entry.get("correction_id") != expected_id:
        raise ValueError(f"{prefix} correction hash binding is stale")
    related = entry.get("related_files")
    if not isinstance(related, list) or not related:
        raise ValueError(f"{prefix} requires related file hashes")
    normalized_related: list[dict[str, str]] = []
    for related_index, row in enumerate(related):
        path = Path(str(row.get("path") or ""))
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"{prefix}.related_files[{related_index}] file is missing")
        digest = sha256_file(path)
        if row.get("sha256") != digest:
            raise ValueError(f"{prefix}.related_files[{related_index}] related file hash is stale")
        normalized_related.append({"path": str(path.resolve()), "sha256": digest})
    if not str(entry.get("property") or "").strip() or "after_value" not in entry:
        raise ValueError(f"{prefix} correction does not describe a preference")
    field = str(entry["property"]).strip()
    lowered = field.lower()
    if any(part in lowered for part in SENSITIVE_FIELD_PARTS):
        raise ValueError(f"{prefix} sensitive or private source content cannot be learned")
    leaf_field = lowered.rsplit(".", 1)[-1]
    if leaf_field not in LEARNABLE_FIELDS:
        raise ValueError(f"{prefix} preference field is not safely learnable")
    if _contains_sensitive_content(entry["after_value"]):
        raise ValueError(f"{prefix} sensitive or private source content cannot be learned")
    source_type = str(entry.get("source_type") or "correction_ledger").strip()
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(f"{prefix} preference source type is not approved")
    return {
        **entry, "property": field, "source_type": source_type,
        "related_files": normalized_related,
    }


def _parse_approval_time(value: str, *, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} requires a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} requires a timezone-aware timestamp")
    return value


def _canonical_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _contains_sensitive_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SENSITIVE_FIELD_PARTS):
                return True
            if _contains_sensitive_content(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_content(item) for item in value)
    if isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()
        return (
            len(stripped) > 4096
            or lowered.startswith(("sk-", "bearer "))
            or "-----begin private key-----" in lowered
            or "-----begin rsa private key-----" in lowered
        )
    return False


def build_preference_candidates(
    ledger: dict[str, Any], *, video_id: str, scope: str = "video",
    scope_key: str | None = None, cross_project_approved_by: str | None = None,
) -> dict[str, Any]:
    """Create pending candidates; this function never applies a preference."""
    if ledger.get("schema_version") != 1 or not isinstance(ledger.get("entries"), list):
        raise ValueError("correction ledger schema is invalid")
    video_id = video_id.strip()
    if not video_id:
        raise ValueError("video_id is required")
    if scope not in {"video", "project", "content_type", "profile", "global"}:
        raise ValueError(
            "preference scope must be video, project, content_type, profile, or global"
        )
    if scope in {"video", "project"}:
        key = scope_key or video_id
    else:
        if not str(cross_project_approved_by or "").strip():
            raise ValueError("cross-project preference scope requires explicit approval")
        key = scope_key if scope in {"content_type", "profile"} else None
        if scope in {"content_type", "profile"} and not str(key or "").strip():
            raise ValueError(f"{scope} scope requires scope_key")
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for index, raw in enumerate(ledger["entries"]):
        entry = _approved_entry(raw, index)
        group_key = (
            entry["property"], _canonical_value(entry["after_value"]), entry["source_type"],
        )
        grouped.setdefault(group_key, []).append(entry)

    candidates: list[dict[str, Any]] = []
    for (field, _, _), entries in grouped.items():
        entry = entries[0]
        correction_ids = sorted(str(row["correction_id"]) for row in entries)
        seed = json.dumps(
            {
                "correction_ids": correction_ids, "scope": scope, "key": key,
                "field": field, "value": entry["after_value"],
            },
            sort_keys=True, separators=(",", ":"),
        )
        sample_count = len(entries)
        candidates.append({
            "candidate_id": hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20],
            "status": "pending",
            "scope": {"type": scope, "key": key},
            "preference": {
                "field": field,
                "value": entry["after_value"],
            },
            "source_correction_id": entry["correction_id"],
            "source_correction_ids": correction_ids,
            "source": {
                "type": entry["source_type"],
                "entries": sample_count,
            },
            "sample_count": sample_count,
            "confidence": round(min(0.95, 0.5 + sample_count * 0.1), 2),
            "conflicts": [],
            "stale_evidence": False,
            "source_approval": {
                "approved_by": entry["approved_by"],
                "approved_at": entry["approved_at"],
            },
            "related_files": [
                row for item in entries for row in item["related_files"]
            ],
            "cross_project_approval": (
                str(cross_project_approved_by).strip()
                if scope not in {"video", "project"} else None
            ),
        })
    for candidate in candidates:
        field = candidate["preference"]["field"]
        candidate["conflicts"] = [
            {
                "candidate_id": other["candidate_id"],
                "value": other["preference"]["value"],
            }
            for other in candidates
            if other["candidate_id"] != candidate["candidate_id"]
            and other["preference"]["field"] == field
        ]
        if candidate["conflicts"]:
            candidate["confidence"] = round(max(0.0, candidate["confidence"] - 0.1), 2)
    return {
        "schema_version": 1,
        "status": "pending_review",
        "default_scope": "video",
        "video_id": video_id,
        "candidates": candidates,
        "auto_applied": False,
    }


def _validate_candidate_evidence(candidate: dict[str, Any]) -> None:
    related = candidate.get("related_files")
    if not isinstance(related, list) or not related:
        raise ValueError("preference candidate requires hash evidence")
    for index, row in enumerate(related):
        path = Path(str(row.get("path") or ""))
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"candidate related_files[{index}] file is missing")
        if row.get("sha256") != sha256_file(path):
            raise ValueError(f"candidate related_files[{index}] hash evidence is stale")


def approve_preference_candidate(
    report: dict[str, Any], *, candidate_id: str, approved_by: str,
    approved_at: str, profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Explicitly promote one pending candidate into an auditable profile record."""
    approver = approved_by.strip()
    if not approver or not approved_at.strip():
        raise ValueError("explicit preference approval requires approved_by and approved_at")
    approved_at = _parse_approval_time(approved_at.strip(), label="explicit preference approval")
    updated_report = copy.deepcopy(report)
    _validate_candidate_report_for_approval(updated_report)
    matches = [
        row for row in updated_report["candidates"] if row.get("candidate_id") == candidate_id
    ]
    if len(matches) != 1:
        raise ValueError("preference candidate_id must identify one pending candidate")
    candidate = matches[0]
    if candidate.get("status") != "pending":
        raise ValueError("preference candidate is not pending")
    _validate_candidate_evidence(candidate)
    if candidate.get("stale_evidence") is not False:
        raise ValueError("preference candidate evidence is stale")

    updated_profile = copy.deepcopy(profile) if profile is not None else {
        "schema_version": 1, "records": [], "history": [],
    }
    if updated_profile.get("schema_version") != 1:
        raise ValueError("preference profile schema is invalid")
    if not isinstance(updated_profile.get("records"), list):
        raise ValueError("preference profile records must be a list")
    seed = json.dumps(
        {
            "candidate_id": candidate_id, "approved_by": approver,
            "approved_at": approved_at,
        }, sort_keys=True, separators=(",", ":"),
    )
    preference_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    record = {
        "preference_id": preference_id,
        "status": "active",
        "scope": candidate["scope"],
        "preference": candidate["preference"],
        "sample_count": candidate["sample_count"],
        "confidence": candidate["confidence"],
        "source": candidate["source"],
        "source_candidate_id": candidate_id,
        "source_correction_ids": candidate["source_correction_ids"],
        "approved_by": approver,
        "approved_at": approved_at,
        "related_files": candidate["related_files"],
        "revocation": None,
    }
    updated_profile["records"].append(record)
    updated_profile.setdefault("history", []).append({
        "action": "approve", "preference_id": preference_id,
        "actor": approver, "timestamp": approved_at,
    })
    candidate["status"] = "approved"
    candidate["profile_preference_id"] = preference_id
    conflict_ids = {
        str(row.get("candidate_id")) for row in candidate.get("conflicts") or []
    }
    for other in updated_report["candidates"]:
        if other.get("candidate_id") in conflict_ids and other.get("status") == "pending":
            other["status"] = "rejected_conflict"
            other["rejected_by_candidate_id"] = candidate_id
    return {"report": updated_report, "profile": updated_profile}


def revoke_preference(
    profile: dict[str, Any], *, preference_id: str, revoked_by: str,
    revoked_at: str, reason: str,
) -> dict[str, Any]:
    """Reversibly revoke a learned record while retaining its full audit history."""
    actor = revoked_by.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("preference revocation requires revoked_by and reason")
    revoked_at = _parse_approval_time(revoked_at.strip(), label="preference revocation")
    updated = copy.deepcopy(profile)
    records = updated.get("records")
    if updated.get("schema_version") != 1 or not isinstance(records, list):
        raise ValueError("preference profile schema is invalid")
    matches = [row for row in records if row.get("preference_id") == preference_id]
    if len(matches) != 1 or matches[0].get("status") != "active":
        raise ValueError("active preference_id was not found")
    record = matches[0]
    record["status"] = "revoked"
    record["revocation"] = {
        "revoked_by": actor, "revoked_at": revoked_at, "reason": reason,
    }
    updated.setdefault("history", []).append({
        "action": "revoke", "preference_id": preference_id,
        "actor": actor, "timestamp": revoked_at, "reason": reason,
    })
    return updated


def restore_preference(
    profile: dict[str, Any], *, preference_id: str, restored_by: str,
    restored_at: str, reason: str,
) -> dict[str, Any]:
    """Explicitly reverse a revocation without deleting its audit evidence."""
    actor = restored_by.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("preference restoration requires restored_by and reason")
    restored_at = _parse_approval_time(restored_at.strip(), label="preference restoration")
    updated = copy.deepcopy(profile)
    records = updated.get("records")
    if updated.get("schema_version") != 1 or not isinstance(records, list):
        raise ValueError("preference profile schema is invalid")
    matches = [row for row in records if row.get("preference_id") == preference_id]
    if len(matches) != 1 or matches[0].get("status") != "revoked":
        raise ValueError("revoked preference_id was not found")
    record = matches[0]
    revocation = record.get("revocation")
    if not isinstance(revocation, dict):
        raise ValueError("revoked preference is missing revocation evidence")
    record.setdefault("revocation_history", []).append(revocation)
    record["status"] = "active"
    record["revocation"] = None
    updated.setdefault("history", []).append({
        "action": "restore", "preference_id": preference_id,
        "actor": actor, "timestamp": restored_at, "reason": reason,
    })
    return updated


def validate_preference_candidates(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != 1 or report.get("auto_applied") is not False:
        raise ValueError("preference candidate report cannot auto-apply changes")
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("preference candidates must be a list")
    if any(row.get("status") != "pending" for row in candidates):
        raise ValueError("preference learning may only write pending candidates")
    return report


def _validate_candidate_report_for_approval(report: dict[str, Any]) -> None:
    if report.get("schema_version") != 1 or report.get("auto_applied") is not False:
        raise ValueError("preference candidate report cannot auto-apply changes")
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("preference candidates must be a list")
    allowed = {"pending", "approved", "rejected_conflict"}
    if any(row.get("status") not in allowed for row in candidates):
        raise ValueError("preference candidate status is invalid")


def write_preference_candidates(path: Path, report: dict[str, Any]) -> Path:
    """Atomically persist validated pending candidates."""
    validate_preference_candidates(report)
    path = path.resolve()
    write_json(path, report)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--scope", choices=("video", "content_type", "global"), default="video")
    parser.add_argument("--scope-key")
    parser.add_argument("--cross-project-approved-by")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_preference_candidates(
        read_json(Path(args.ledger).resolve()), video_id=args.video_id, scope=args.scope,
        scope_key=args.scope_key, cross_project_approved_by=args.cross_project_approved_by,
    )
    output = write_preference_candidates(Path(args.out), report)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
