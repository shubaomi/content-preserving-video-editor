#!/usr/bin/env python3
"""Build hash-bound semantic confidence reports without edit authority."""
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


LOW_CONFIDENCE_DISPOSITIONS = {
    "gather_more_evidence",
    "human_review",
    "omit_claim",
    "preserve_source",
}

LOW_INFORMATION_ANCHORS = {
    "打开", "点击", "添加", "然后", "这里", "这个", "那个", "继续", "一下",
    "open", "click", "add", "then", "next",
}
PROHIBITED_SELECTION_METHODS = {
    "keyword", "keyword_frequency", "fixed", "fixed_count", "random", "round_robin",
}
MEANING_CHANGING_EFFECTS = {
    "meaning_changing", "delete", "deletion", "reorder", "cold_open_reorder",
    "cover_claim", "replace_source",
}
SCORE_FIELDS = (
    "anchor_specificity", "claim_grounding", "explanatory_value", "asr_confidence",
    "term_confidence", "caption_duplication", "motion_duplication", "ip_duplication",
)


def _score(candidate: dict[str, Any], field: str) -> float:
    value = candidate.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"semantic candidate {field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"semantic candidate {field} must be between 0 and 1")
    return result


def _timing(candidate: dict[str, Any], field: str) -> dict[str, float]:
    value = candidate.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"semantic candidate requires {field}")
    start, end = value.get("start"), value.get("end")
    if (isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float)) or not isinstance(end, (int, float))):
        raise ValueError(f"semantic candidate {field} requires numeric start and end")
    start, end = float(start), float(end)
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError(f"semantic candidate {field} is invalid")
    return {"start": start, "end": end}


def _bound_frames(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = candidate.get("frame_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("semantic candidate requires frame_evidence")
    bound: list[dict[str, Any]] = []
    for index, row in enumerate(evidence):
        if not isinstance(row, dict):
            raise ValueError(f"semantic candidate frame_evidence[{index}] must be an object")
        path = Path(str(row.get("path") or ""))
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"semantic candidate frame_evidence[{index}] file is missing")
        expected = str(row.get("sha256") or "").lower()
        actual = sha256_file(path)
        if expected != actual:
            raise ValueError(f"semantic candidate frame_evidence[{index}] hash is stale")
        timestamp = row.get("timestamp")
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not math.isfinite(float(timestamp)) or float(timestamp) < 0):
            raise ValueError(f"semantic candidate frame_evidence[{index}] timestamp is invalid")
        bound.append({
            **row,
            "path": str(path.resolve()),
            "sha256": actual,
            "timestamp": float(timestamp),
        })
    return bound


def _is_low_information_anchor(anchor: str) -> bool:
    tokens = [
        token.casefold() for token in re.findall(r"[\w\u4e00-\u9fff]+", anchor)
        if token.strip()
    ]
    if not tokens:
        return True
    compact = "".join(tokens)
    if compact in LOW_INFORMATION_ANCHORS or all(token in LOW_INFORMATION_ANCHORS for token in tokens):
        return True
    chinese_low = sorted(
        (value for value in LOW_INFORMATION_ANCHORS if re.fullmatch(r"[\u4e00-\u9fff]+", value)),
        key=len,
        reverse=True,
    )
    remaining = compact
    while remaining:
        matched = next((value for value in chinese_low if remaining.startswith(value)), None)
        if matched is None:
            return False
        remaining = remaining[len(matched):]
    return True


def _evaluate_candidate(candidate: dict[str, Any], *, threshold: float) -> dict[str, Any]:
    event_id = str(candidate.get("event_id") or "").strip()
    anchor = str(candidate.get("anchor") or "").strip()
    if not event_id or not anchor:
        raise ValueError("semantic candidate requires event_id and anchor")
    selection_method = str(candidate.get("selection_method") or "semantic_evidence").strip()
    if selection_method in PROHIBITED_SELECTION_METHODS:
        raise ValueError(f"prohibited selection_method: {selection_method}")
    word_ids = candidate.get("raw_word_ids")
    if (not isinstance(word_ids, list) or not word_ids
            or any(not isinstance(value, str) or not value.strip() for value in word_ids)):
        raise ValueError("semantic candidate requires raw_word_ids")
    quote = candidate.get("raw_quote")
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("semantic candidate requires raw_quote")
    source_timing = _timing(candidate, "source_timing")
    output_timing = _timing(candidate, "output_timing")
    frames = _bound_frames(candidate)
    for field in ("counterexamples", "conflicts"):
        if field not in candidate or not isinstance(candidate[field], list):
            raise ValueError(f"semantic candidate requires {field}")
        if any(not isinstance(row, (dict, str)) for row in candidate[field]):
            raise ValueError(f"semantic candidate {field} must contain objects or strings")
    scores = {field: _score(candidate, field) for field in SCORE_FIELDS}
    positive = sum(scores[field] for field in SCORE_FIELDS[:5]) / 5.0
    duplication = sum(scores[field] for field in SCORE_FIELDS[5:]) / 3.0
    total = positive - (0.35 * duplication)
    if candidate["counterexamples"]:
        total -= min(0.25, 0.10 + 0.03 * len(candidate["counterexamples"]))
    if candidate["conflicts"]:
        total -= min(0.35, 0.15 + 0.05 * len(candidate["conflicts"]))
    total = round(max(0.0, min(1.0, total)), 4)

    rejection_reasons: list[str] = []
    low_information = _is_low_information_anchor(anchor)
    if low_information:
        rejection_reasons.append("low_information_anchor")
    if total < threshold:
        rejection_reasons.append("total_confidence_below_threshold")
    if duplication >= 0.65:
        rejection_reasons.append("high_caption_motion_or_ip_duplication")
    if candidate["counterexamples"]:
        rejection_reasons.append("counterexample_requires_resolution")
    if candidate["conflicts"]:
        rejection_reasons.append("semantic_conflict_requires_resolution")

    semantic_effect = str(candidate.get("semantic_effect") or "emphasis").strip()
    meaning_changing = semantic_effect in MEANING_CHANGING_EFFECTS
    eligible = not rejection_reasons
    requested = str(candidate.get("disposition") or "").strip()
    if eligible:
        disposition = requested or "accepted_for_motion"
        if disposition not in {"accepted_for_motion", "caption_only", "preserve_source"}:
            raise ValueError(f"unsupported semantic candidate disposition: {disposition}")
    elif meaning_changing:
        disposition = "action_required"
    elif candidate.get("preserve_source_on_rejection") is True:
        disposition = "preserve_source"
    else:
        disposition = "caption_only"
    reasons = [
        f"positive_evidence={positive:.4f}",
        f"duplication_penalty={0.35 * duplication:.4f}",
        f"threshold={threshold:.4f}",
    ]
    return {
        "event_id": event_id,
        "anchor": anchor,
        "raw_word_ids": list(word_ids),
        "raw_quote": quote,
        "source_timing": source_timing,
        "output_timing": output_timing,
        "frame_evidence": frames,
        **scores,
        "counterexamples": list(candidate["counterexamples"]),
        "conflicts": list(candidate["conflicts"]),
        "semantic_effect": semantic_effect,
        "selection_method": selection_method,
        "total_confidence": total,
        "reasons": reasons,
        "rejection_reasons": rejection_reasons,
        "eligible_for_highlight": eligible,
        "disposition": disposition,
    }


def build_candidate_report(
    candidates: list[dict[str, Any]], *, low_confidence_threshold: float = 0.7,
) -> dict[str, Any]:
    """Build strict evidence-first decisions for motion candidates.

    This report has no deletion or timeline authority. Meaning-changing claims that
    cannot clear the evidence threshold are explicitly handed back for approval.
    """
    if (isinstance(low_confidence_threshold, bool)
            or not isinstance(low_confidence_threshold, (int, float))):
        raise ValueError("low_confidence_threshold must be numeric")
    threshold = float(low_confidence_threshold)
    if not math.isfinite(threshold) or not 0.0 < threshold <= 1.0:
        raise ValueError("low_confidence_threshold must be within (0, 1]")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("semantic candidate report requires at least one candidate")
    evaluated = [_evaluate_candidate(row, threshold=threshold) for row in candidates]
    action_ids = [row["event_id"] for row in evaluated if row["disposition"] == "action_required"]
    return {
        "schema_version": 2,
        "status": "action_required" if action_ids else "pass",
        "selection_policy": "evidence_weighted_no_keyword_or_random",
        "low_confidence_threshold": threshold,
        "action_required_event_ids": action_ids,
        "candidates": evaluated,
        "semantic_deletion_authority": False,
    }


def validate_candidate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Recompute candidate decisions and recheck every bound frame hash."""
    if not isinstance(report, dict) or report.get("schema_version") != 2:
        raise ValueError("semantic candidate schema_version must be 2")
    rebuilt = build_candidate_report(
        report.get("candidates"),
        low_confidence_threshold=report.get("low_confidence_threshold", 0.7),
    )
    for field in (
        "status", "selection_policy", "action_required_event_ids",
        "semantic_deletion_authority",
    ):
        if report.get(field) != rebuilt[field]:
            raise ValueError(f"semantic candidate report {field} is stale")
    declared = report.get("candidates")
    if declared != rebuilt["candidates"]:
        raise ValueError("semantic candidate report scores or decisions are stale")
    return rebuilt


def _validate_claim(claim: dict[str, Any], *, threshold: float) -> dict[str, Any]:
    claim_id = str(claim.get("claim_id") or "").strip()
    text = str(claim.get("claim") or claim.get("text") or "").strip()
    if not claim_id or not text:
        raise ValueError("semantic claim requires claim_id and claim text")
    confidence = claim.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError(f"semantic claim {claim_id} confidence must be numeric")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError(f"semantic claim {claim_id} confidence must be between 0 and 1")

    evidence = claim.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"semantic claim {claim_id} requires evidence bindings")
    bound_evidence: list[dict[str, Any]] = []
    for index, row in enumerate(evidence):
        if not isinstance(row, dict):
            raise ValueError(f"semantic claim {claim_id} evidence[{index}] must be an object")
        path = Path(str(row.get("path") or ""))
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"semantic claim {claim_id} evidence[{index}] file is missing")
        expected = str(row.get("sha256") or "").lower()
        actual = sha256_file(path)
        if expected != actual:
            raise ValueError(f"semantic claim {claim_id} evidence[{index}] hash is stale")
        bound_evidence.append({**row, "path": str(path.resolve()), "sha256": actual})

    if "counterexamples" not in claim or not isinstance(claim["counterexamples"], list):
        raise ValueError(f"semantic claim {claim_id} requires explicit counterexamples review")
    counterexamples = claim["counterexamples"]
    if any(not isinstance(row, (dict, str)) for row in counterexamples):
        raise ValueError(f"semantic claim {claim_id} counterexamples must be objects or strings")

    disposition = str(claim.get("disposition") or "").strip()
    if confidence < threshold:
        if disposition not in LOW_CONFIDENCE_DISPOSITIONS:
            raise ValueError(
                f"low-confidence semantic claim {claim_id} requires a non-destructive disposition"
            )
    elif not disposition:
        disposition = "accepted_for_planning"
    return {
        "claim_id": claim_id,
        "claim": text,
        "confidence": confidence,
        "evidence": bound_evidence,
        "counterexamples": counterexamples,
        "disposition": disposition,
    }


def build_confidence_report(
    claims: list[dict[str, Any]], *, low_confidence_threshold: float = 0.7,
) -> dict[str, Any]:
    """Normalize semantic claims and bind every claim to current evidence hashes."""
    if isinstance(low_confidence_threshold, bool) or not isinstance(
        low_confidence_threshold, (int, float),
    ):
        raise ValueError("low_confidence_threshold must be numeric")
    threshold = float(low_confidence_threshold)
    if not math.isfinite(threshold) or not 0.0 < threshold <= 1.0:
        raise ValueError("low_confidence_threshold must be within (0, 1]")
    if not isinstance(claims, list) or not claims:
        raise ValueError("semantic confidence report requires at least one claim")
    normalized = [_validate_claim(row, threshold=threshold) for row in claims]
    low_ids = [row["claim_id"] for row in normalized if row["confidence"] < threshold]
    return {
        "schema_version": 1,
        "status": "action_required" if low_ids else "pass",
        "low_confidence_threshold": threshold,
        "low_confidence_claim_ids": low_ids,
        "claims": normalized,
        "semantic_deletion_authority": False,
    }


def validate_confidence_report(report: dict[str, Any]) -> dict[str, Any]:
    """Revalidate a report, including its on-disk evidence bindings."""
    if report.get("schema_version") == 2:
        return validate_candidate_report(report)
    if report.get("schema_version") != 1:
        raise ValueError("semantic confidence schema_version must be 1")
    rebuilt = build_confidence_report(
        report.get("claims"),
        low_confidence_threshold=report.get("low_confidence_threshold", 0.7),
    )
    if report.get("status") != rebuilt["status"]:
        raise ValueError("semantic confidence status does not match claim dispositions")
    if report.get("semantic_deletion_authority") is not False:
        raise ValueError("semantic confidence report cannot grant deletion authority")
    return rebuilt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--claims", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--threshold", type=float, default=0.7)
    check = sub.add_parser("validate")
    check.add_argument("--report", required=True)
    args = parser.parse_args()
    if args.command == "build":
        source = read_json(Path(args.claims).resolve())
        claims = source.get("claims") if isinstance(source, dict) else source
        result = build_confidence_report(claims, low_confidence_threshold=args.threshold)
        write_json(Path(args.out).resolve(), result)
        print(Path(args.out).resolve())
    else:
        validate_confidence_report(read_json(Path(args.report).resolve()))
        print(Path(args.report).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
