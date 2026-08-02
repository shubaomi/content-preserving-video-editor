#!/usr/bin/env python3
"""Build authorized, non-duplicated cover reference packs with safe projection."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


def _valid_time(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return True


def _time(value: Any) -> datetime:
    if not _valid_time(value):
        raise ValueError(f"invalid timestamp: {value}")
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _values(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        return []
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _normalize_reference(row: dict[str, Any], index: int) -> dict[str, Any]:
    ref_id = str(row.get("reference_id") or "").strip()
    if not ref_id:
        raise ValueError(f"reference[{index}] requires reference_id")
    path = Path(str(row.get("path") or ""))
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"reference {ref_id} file is missing")
    actual_hash = sha256_file(path)
    if str(row.get("sha256") or "").lower() != actual_hash:
        raise ValueError(f"reference {ref_id} hash is stale")
    roles = _values(row.get("roles"))
    if not roles:
        raise ValueError(f"reference {ref_id} requires at least one role")
    purposes = _values(row.get("purposes")) or ["identity_generation"]
    try:
        quality = float(row.get("quality", 0.75))
    except (TypeError, ValueError) as error:
        raise ValueError(f"reference {ref_id} quality must be numeric") from error
    if not 0.0 <= quality <= 1.0:
        raise ValueError(f"reference {ref_id} quality must be between 0 and 1")
    pose = str(row.get("pose") or "").strip().lower() or None
    expression = str(row.get("expression") or "").strip().lower() or None
    authorization = row.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError(f"reference {ref_id} requires authorization evidence")
    if authorization.get("authorized") is not True:
        raise ValueError(f"reference {ref_id} is not authorized")
    if not str(authorization.get("authorized_by") or "").strip():
        raise ValueError(f"reference {ref_id} authorization requires authorized_by")
    if not _valid_time(authorization.get("authorized_at")):
        raise ValueError(f"reference {ref_id} authorization time is invalid")
    scopes = authorization.get("scope")
    scopes = [scopes] if isinstance(scopes, str) else scopes
    if not isinstance(scopes, list) or "cover_reference" not in scopes:
        raise ValueError(f"reference {ref_id} is not authorized for cover_reference")
    if row.get("revoked") is True or row.get("revoked_at"):
        raise ValueError(f"reference {ref_id} authorization has been revoked")
    return {
        "reference_id": ref_id,
        "path": str(path.resolve()),
        "sha256": actual_hash,
        "roles": roles,
        "purposes": purposes,
        "quality": quality,
        "pose": pose,
        "expression": expression,
        "subject_id": str(row.get("subject_id") or "").strip() or None,
        "authorization": {
            "authorized": True,
            "authorized_by": str(authorization["authorized_by"]).strip(),
            "authorized_at": str(authorization["authorized_at"]),
            "scope": sorted({str(value) for value in scopes}),
        },
        "revoked": False,
    }


def privacy_projection(pack: dict[str, Any]) -> dict[str, Any]:
    """Return the pack data safe to expose to render/review providers."""
    return {
        "schema_version": 1,
        "required_roles": list(pack.get("required_roles") or []),
        "covered_roles": list(pack.get("covered_roles") or []),
        "references": [
            {
                "reference_id": row["reference_id"],
                "sha256": row["sha256"],
                "roles": list(row["roles"]),
                "authorized_for": ["cover_reference"],
                "revoked": False,
            }
            for row in pack.get("references") or []
        ],
        "privacy": {
            "local_paths_excluded": True,
            "authorization_identity_excluded": True,
            "sensitive_reference_attributes_excluded": True,
        },
    }


def build_reference_pack(
    references: list[dict[str, Any]], *, required_roles: list[str],
) -> dict[str, Any]:
    if not isinstance(references, list) or not references:
        raise ValueError("cover reference pack requires references")
    required = sorted({str(role).strip() for role in required_roles if str(role).strip()})
    if not required:
        raise ValueError("cover reference pack requires role coverage requirements")
    normalized = [_normalize_reference(row, index) for index, row in enumerate(references)]
    ids = [row["reference_id"] for row in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("cover references require distinct reference_ids")
    hashes = [row["sha256"] for row in normalized]
    if len(hashes) != len(set(hashes)):
        raise ValueError("cover references require distinct content hashes")
    covered = sorted({role for row in normalized for role in row["roles"]})
    missing = sorted(set(required) - set(covered))
    if missing:
        raise ValueError(f"cover reference role coverage is missing: {', '.join(missing)}")
    pack = {
        "schema_version": 1,
        "required_roles": required,
        "covered_roles": covered,
        "references": normalized,
    }
    pack["privacy_projection"] = privacy_projection(pack)
    return pack


def validate_reference_pack(pack: dict[str, Any]) -> dict[str, Any]:
    if pack.get("schema_version") != 1:
        raise ValueError("cover reference pack schema_version must be 1")
    rebuilt = build_reference_pack(
        pack.get("references"), required_roles=pack.get("required_roles") or [],
    )
    if pack.get("privacy_projection") not in (None, rebuilt["privacy_projection"]):
        raise ValueError("cover reference privacy projection is stale")
    return rebuilt


def _match_score(row: dict[str, Any], *, topic: str, direction: str, expression: str) -> float:
    searchable = " ".join([
        *row.get("roles", []), *row.get("purposes", []),
        str(row.get("pose") or ""), str(row.get("expression") or ""),
    ]).lower()
    terms = {term for term in f"{topic} {direction}".lower().replace("_", " ").split() if term}
    score = float(row.get("quality") or 0.0) * 10.0
    score += 20.0 if "identity" in row.get("roles", []) else 0.0
    score += sum(2.0 for term in terms if term in searchable)
    if expression and (
        str(row.get("expression") or "").lower() == expression
        or expression in {str(role).lower() for role in row.get("roles", [])}
    ):
        score += 15.0
    return score


def select_references(
    pack: dict[str, Any], *, topic: str, direction: str,
    target_expression: str, minimum_identity_references: int = 2,
    maximum_references: int = 4, expected_subject_id: str | None = None,
) -> dict[str, Any]:
    """Deterministically select an authorized multi-photo generation set.

    Selection is deliberately strict: references define a regenerated subject;
    they are never treated as pixels to cut out and paste into the cover.
    """
    current = validate_reference_pack(pack)
    rows = current["references"]
    identity = [
        row for row in rows
        if "identity" in row["roles"] and "identity_generation" in row["purposes"]
    ]
    minimum = max(2, int(minimum_identity_references))
    if len(identity) < minimum:
        raise ValueError(f"cover generation requires at least {minimum} distinct authorized identity references")
    if expected_subject_id:
        wrong = [
            row["reference_id"] for row in identity
            if row.get("subject_id") and row["subject_id"] != expected_subject_id
        ]
        if wrong:
            raise ValueError(f"cover reference pack contains mixed or wrong subject: {', '.join(wrong)}")
    target = str(target_expression or "").strip().lower()
    matching_expression = [
        row for row in identity
        if target and (
            row.get("expression") == target
            or target in {str(role).lower() for role in row.get("roles", [])}
        )
    ]
    if target and not matching_expression:
        raise ValueError(f"cover reference expression mismatch: no authorized {target} reference")
    ranked = sorted(
        identity,
        key=lambda row: (
            -_match_score(row, topic=topic, direction=direction, expression=target),
            row["reference_id"],
        ),
    )
    limit = max(minimum, min(int(maximum_references), len(ranked)))
    selected = ranked[:limit]
    return {
        "schema_version": 1,
        "generation_mode": "reference_guided_regeneration",
        "literal_cutout_forbidden": True,
        "topic": str(topic).strip(),
        "direction": str(direction).strip(),
        "target_expression": target,
        "selection_policy": "quality-plus-topic-direction-role-match; deterministic-reference-id-tiebreak",
        "selected_references": [
            {
                "reference_id": row["reference_id"],
                "path": row["path"],
                "sha256": row["sha256"],
                "roles": list(row["roles"]),
                "purposes": list(row["purposes"]),
                "pose": row.get("pose"),
                "expression": row.get("expression"),
                "quality": row["quality"],
            }
            for row in selected
        ],
    }


def build_candidate_specs(
    selection: dict[str, Any], *, topic: str, direction: str,
) -> list[dict[str, Any]]:
    """Create two meaningfully different reference-guided generation specs."""
    references = selection.get("selected_references") or []
    if len(references) < 2:
        raise ValueError("candidate specifications require at least 2 selected references")
    if selection.get("generation_mode") != "reference_guided_regeneration":
        raise ValueError("candidate specifications require reference-guided regeneration")
    shared = {
        "generation_mode": "reference_guided_regeneration",
        "forbid_literal_cutout": True,
        "topic": str(topic).strip(),
        "direction": str(direction).strip(),
        "target_expression": selection.get("target_expression"),
        "reference_ids": [row["reference_id"] for row in references],
        "reference_sha256": [row["sha256"] for row in references],
        "clean_base_has_no_text": True,
    }
    return [
        {
            **shared,
            "candidate_id": "A",
            "communication_strategy": "creator demonstrates the topic in a coherent real environment",
            "structure": {
                "template_family": "bright_tech_tutorial",
                "subject_side": "right",
                "camera": "medium action portrait",
                "negative_space": "upper-left",
            },
        },
        {
            **shared,
            "candidate_id": "B",
            "communication_strategy": "cinematic result-first poster with one integrated topic prop",
            "structure": {
                "template_family": "cinematic_editorial",
                "subject_side": "left",
                "camera": "three-quarter environmental portrait",
                "negative_space": "upper-right",
            },
        },
    ]


_EVALUATION_THRESHOLDS = {
    "identity": 0.82,
    "expression": 0.72,
    "gaze": 0.68,
    "vitality": 0.68,
    "face_proportions": 0.78,
    "hands_body": 0.78,
    "topic_relevance": 0.72,
    "thumbnail_composition": 0.72,
}


def evaluate_candidate(
    *, candidate_id: str, assessment: dict[str, Any],
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate independent semantic/anatomy dimensions without claiming likeness approval."""
    limits = {**_EVALUATION_THRESHOLDS, **(thresholds or {})}
    scores: dict[str, float] = {}
    for name in _EVALUATION_THRESHOLDS:
        try:
            score = float(assessment[name])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"candidate assessment requires numeric {name}") from error
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"candidate assessment {name} must be between 0 and 1")
        scores[name] = score
    failed = [name for name, limit in limits.items() if scores[name] < float(limit)]
    hard = [
        flag for flag in ("hand_anomaly", "body_anomaly", "wrong_identity", "pasted_cutout")
        if assessment.get(flag) is True
    ]
    return {
        "schema_version": 1,
        "candidate_id": str(candidate_id),
        "scores": scores,
        "thresholds": limits,
        "failed_dimensions": failed,
        "hard_failures": hard,
        "automated_passed": not failed and not hard,
        "identity_user_approval": "pending",
        "identity_gate_note": "Automated review cannot approve the creator's likeness.",
    }


def record_identity_approval(
    *, candidate_id: str, candidate_sha256: str, approved_by: str,
    approved_at: str, expires_at: str | None = None,
) -> dict[str, Any]:
    if len(candidate_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in candidate_sha256.lower()):
        raise ValueError("identity approval requires candidate SHA-256")
    if not str(approved_by).strip():
        raise ValueError("identity approval requires approved_by")
    approved_time = _time(approved_at)
    if expires_at and _time(expires_at) <= approved_time:
        raise ValueError("identity approval expires_at must be after approved_at")
    return {
        "schema_version": 1,
        "candidate_id": str(candidate_id),
        "candidate_sha256": candidate_sha256.lower(),
        "approved": True,
        "approved_by": str(approved_by).strip(),
        "approved_at": str(approved_at),
        "expires_at": str(expires_at) if expires_at else None,
    }


def validate_identity_approval(
    approval: dict[str, Any] | None, *, candidate_id: str,
    candidate_sha256: str, now: str | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not isinstance(approval, dict) or approval.get("approved") is not True:
        reasons.append("explicit user identity approval is missing")
    else:
        if approval.get("candidate_id") != candidate_id:
            reasons.append("candidate identity changed")
        if str(approval.get("candidate_sha256") or "").lower() != candidate_sha256.lower():
            reasons.append("candidate hash changed")
        if not _valid_time(approval.get("approved_at")):
            reasons.append("approval timestamp is invalid")
        expires_at = approval.get("expires_at")
        if expires_at:
            if not _valid_time(expires_at):
                reasons.append("approval expiry is invalid")
            else:
                current = _time(now) if now else datetime.now(timezone.utc)
                if current >= _time(expires_at):
                    reasons.append("identity approval expired")
    if reasons:
        return {
            "approved": False,
            "status": "action_required",
            "action": "review the exact current candidate and record explicit identity approval",
            "candidate_id": candidate_id,
            "candidate_sha256": candidate_sha256.lower(),
            "reasons": reasons,
        }
    return {
        "approved": True,
        "status": "complete",
        "candidate_id": candidate_id,
        "candidate_sha256": candidate_sha256.lower(),
        "approved_by": approval["approved_by"],
        "approved_at": approval["approved_at"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--references", required=True)
    build.add_argument("--required-role", action="append", required=True)
    build.add_argument("--out", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--pack", required=True)
    args = parser.parse_args()
    if args.command == "build":
        source = read_json(Path(args.references).resolve())
        rows = source.get("references") if isinstance(source, dict) else source
        result = build_reference_pack(rows, required_roles=args.required_role)
        write_json(Path(args.out).resolve(), result)
        print(Path(args.out).resolve())
    else:
        validate_reference_pack(read_json(Path(args.pack).resolve()))
        print(Path(args.pack).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
