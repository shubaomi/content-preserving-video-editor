#!/usr/bin/env python3
"""Build and validate one evidence-bound editorial promise across publishing surfaces."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any


SURFACES = {"hook", "title", "cover", "description", "cta", "motion_copy"}


def _meaning_tokens(value: Any) -> set[str]:
    text = str(value or "").strip().lower()
    latin = set(re.findall(r"[a-z0-9]{2,}", text))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    return latin | {chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))}


def _claim_tokens(value: Any) -> set[str]:
    text = str(value or "").lower()
    return set(re.findall(
        r"(?:[$¥￥€£]\s*\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*\s*(?:%|％|倍|万|亿|元|美元)?|"
        r"guarantee(?:d)?|always|never|必然|保证|稳赚|翻倍|零风险)", text,
    ))


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def build_promise_ledger(semantic_brief: dict[str, Any]) -> dict[str, Any]:
    events = {
        str(row.get("id") or ""): row for row in (semantic_brief.get("events") or [])
        if isinstance(row, dict) and row.get("id")
    }
    intent = semantic_brief.get("editorial_intent")
    explicit = isinstance(intent, dict)
    if explicit:
        required = (
            "audience", "viewer_job", "single_promise", "proof_event_ids",
            "cta", "tone", "prohibited_claims",
        )
        missing = [field for field in required if not intent.get(field)]
        if missing:
            raise ValueError("editorial intent is incomplete: " + ", ".join(missing))
        proof_ids = [str(value) for value in intent["proof_event_ids"]]
        promise_text = str(intent["single_promise"]).strip()
        audience = str(intent["audience"]).strip()
        viewer_job = str(intent["viewer_job"]).strip()
        cta = str(intent["cta"]).strip()
        tone = str(intent["tone"]).strip()
        prohibited = [str(value).strip() for value in intent["prohibited_claims"] if str(value).strip()]
    else:
        usable = [row for row in events.values() if row.get("decision") != "action_required"]
        if not usable:
            raise ValueError("neutral education promise requires at least one resolved semantic event")
        primary = usable[0]
        proof_ids = [str(primary["id"])]
        promise_text = str(primary.get("viewer_takeaway") or "understand the documented topic").strip()
        audience = "interested_viewer"
        viewer_job = "understand_the_evidence_backed_topic"
        cta = "continue_learning"
        tone = "neutral_educational"
        prohibited = []
    unknown = [event_id for event_id in proof_ids if event_id not in events]
    if unknown:
        raise ValueError("editorial promise references unknown proof events: " + ", ".join(unknown))
    transcript_word_ids: list[str] = []
    frame_evidence: list[str] = []
    for event_id in proof_ids:
        transcript_word_ids.extend(str(value) for value in events[event_id].get("transcript_word_ids") or [])
        frame_evidence.extend(str(value) for value in events[event_id].get("target_frame_evidence") or [])
    authority = {
        "text": promise_text,
        "proof_event_ids": proof_ids,
        "transcript_word_ids": list(dict.fromkeys(transcript_word_ids)),
        "frame_evidence": list(dict.fromkeys(frame_evidence)),
    }
    promise_id = "promise-" + _stable_hash(authority)[:16]
    return {
        "schema_version": 1,
        "promise_id": promise_id,
        "mode": "explicit_intent" if explicit else "neutral_education",
        "audience": audience,
        "viewer_job": viewer_job,
        "single_promise": authority,
        "cta": cta,
        "tone": tone,
        "prohibited_claims": prohibited,
        "commercial_goal_invented": False,
        "surface_policy": {
            "allowed": sorted(SURFACES),
            "wording_may_vary": True,
            "mechanical_repetition_forbidden": True,
            "every_claim_requires_promise_id_and_proof_event_ids": True,
        },
    }


def validate_promise_bindings(
    ledger: dict[str, Any], outputs: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    promise_id = str(ledger.get("promise_id") or "")
    approved_proof = set((ledger.get("single_promise") or {}).get("proof_event_ids") or [])
    promise_tokens = _meaning_tokens((ledger.get("single_promise") or {}).get("text"))
    approved_claims = _claim_tokens((ledger.get("single_promise") or {}).get("text"))
    copies: list[str] = []
    for index, row in enumerate(outputs):
        if not isinstance(row, dict):
            errors.append(f"promise output {index} is not an object")
            continue
        surface = str(row.get("surface") or "")
        copy = str(row.get("copy") or "").strip()
        copies.append(copy)
        if not copy:
            errors.append(f"promise output {surface or index} copy is empty")
        elif promise_tokens and not (_meaning_tokens(copy) & promise_tokens):
            errors.append(f"promise output {surface or index} has no semantic overlap with the approved promise")
        unapproved_claims = _claim_tokens(copy) - approved_claims
        if unapproved_claims:
            errors.append(
                f"promise output {surface or index} adds unapproved claim tokens: "
                + ", ".join(sorted(unapproved_claims))
            )
        if surface not in SURFACES:
            errors.append(f"promise output {index} has unsupported surface {surface!r}")
        if row.get("promise_id") != promise_id:
            errors.append(f"promise output {surface} is not bound to the current promise")
        proof = set(str(value) for value in row.get("proof_event_ids") or [])
        if not proof or not proof.issubset(approved_proof):
            errors.append(f"promise output {surface} lacks approved proof events")
        for prohibited in ledger.get("prohibited_claims") or []:
            if str(prohibited) and str(prohibited) in copy:
                errors.append(f"promise output {surface} contains prohibited claim: {prohibited}")
    for copy, count in Counter(value for value in copies if value).items():
        if count >= 3:
            errors.append(f"promise wording is mechanically repeated across {count} surfaces: {copy}")
    return errors


def build_promise_closure(
    ledger: dict[str, Any], outputs: list[dict[str, Any]],
    *, required_surfaces: set[str] | None = None,
) -> dict[str, Any]:
    """Validate all enabled editorial surfaces as one evidence-bound promise."""
    required = set(required_surfaces or SURFACES)
    present = {
        str(row.get("surface") or "") for row in outputs if isinstance(row, dict)
    }
    missing = sorted(required - present)
    errors = validate_promise_bindings(ledger, outputs)
    counts = Counter(
        str(row.get("surface") or "") for row in outputs
        if isinstance(row, dict) and str(row.get("surface") or "") in required
    )
    for surface, count in sorted(counts.items()):
        if count != 1:
            errors.append(f"promise closure requires exactly one {surface} surface; found {count}")
    if missing:
        errors.append("editorial promise closure is missing surfaces: " + ", ".join(missing))
    normalized = [{
        "surface": str(row.get("surface") or ""),
        "copy": str(row.get("copy") or "").strip(),
        "promise_id": str(row.get("promise_id") or ""),
        "proof_event_ids": [str(value) for value in row.get("proof_event_ids") or []],
    } for row in outputs if isinstance(row, dict)]
    return {
        "schema_version": 1,
        "status": "failed" if errors else "pass",
        "promise_id": str(ledger.get("promise_id") or ""),
        "promise_ledger_sha256": _stable_hash(ledger),
        "required_surfaces": sorted(required),
        "covered_surfaces": sorted(present),
        "missing_surfaces": missing,
        "surface_bindings": normalized,
        "errors": errors,
        "commercial_goal_invented": bool(ledger.get("commercial_goal_invented")),
    }
