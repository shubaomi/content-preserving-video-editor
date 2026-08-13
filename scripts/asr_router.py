#!/usr/bin/env python3
"""Select an optional ASR backend and normalize its output to video-use words."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from director_contracts import read_json, write_json


BACKENDS = ("local_faster_whisper", "funasr", "whisperx")
BACKEND_CAPABILITIES = {
    "local_faster_whisper": {"transcription", "word_timestamps"},
    "funasr": {"hotwords", "speaker_labels", "transcription", "word_timestamps"},
    "whisperx": {
        "diarization", "speaker_labels", "transcription", "word_alignment",
        "word_timestamps",
    },
}
TERM_FIELDS = ("hotwords", "products", "urls", "commands", "english_terms", "terminology")


class AsrCapabilityError(ValueError):
    """Raised when an explicitly required ASR capability is unavailable."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_number(value: Any, *, field: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{field} must be finite and >= {minimum}")
    return result


def merge_hotwords(*sources: dict[str, Any] | None) -> list[str]:
    """Merge governed term sources deterministically, preserving first spelling."""
    merged: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source is None:
            continue
        if not isinstance(source, dict):
            raise ValueError("ASR term source must be an object")
        for field in TERM_FIELDS:
            values = source.get(field, [])
            if values is None:
                continue
            if not isinstance(values, list):
                raise ValueError(f"ASR term source {field} must be a list")
            for value in values:
                if not isinstance(value, str):
                    raise ValueError(f"ASR term source {field} values must be strings")
                term = value.strip()
                if not term:
                    continue
                key = term.casefold()
                if key not in seen:
                    seen.add(key)
                    merged.append(term)
    return merged


def _available(config: dict[str, Any], name: str) -> bool:
    row = config.get("backends", {}).get(name, {})
    return isinstance(row, dict) and row.get("available") is True


def _capabilities(config: dict[str, Any], name: str) -> set[str]:
    row = config.get("backends", {}).get(name, {})
    configured = row.get("capabilities") if isinstance(row, dict) else None
    if configured is None:
        return set(BACKEND_CAPABILITIES[name])
    if not isinstance(configured, list):
        raise ValueError(f"ASR backend {name} capabilities must be a list")
    return {str(value).strip() for value in configured if str(value).strip()}


def _backend_for_capability(
    config: dict[str, Any], capability: str, *, preferred: tuple[str, ...] = BACKENDS,
) -> str | None:
    return next((
        name for name in preferred
        if _available(config, name) and capability in _capabilities(config, name)
    ), None)


def choose_pipeline(config: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Select one or more ASR stages and fail closed for required capabilities."""
    language = str(evidence.get("language") or "unknown").lower()
    hotwords = merge_hotwords(
        {"hotwords": evidence.get("hotwords") or []},
        config.get("project_terms"),
        config.get("profile_terms"),
        evidence.get("project_terms"),
        evidence.get("profile_terms"),
    )
    raw_speaker_count = evidence.get("speaker_count", 1)
    if isinstance(raw_speaker_count, bool) or not isinstance(raw_speaker_count, int):
        raise ValueError("speaker_count must be a positive integer")
    speaker_count = raw_speaker_count
    if speaker_count < 1:
        raise ValueError("speaker_count must be a positive integer")
    precise = evidence.get("precise_word_alignment") is True
    diarization = evidence.get("diarization") is True
    speaker_labels = evidence.get("speaker_labels") is True or speaker_count > 1
    noise_score = _finite_number(
        evidence.get("noise_score", 0.0), field="noise_score",
    )
    if noise_score > 1.0:
        raise ValueError("noise_score must be between 0 and 1")
    drift = _finite_number(
        evidence.get("timing_drift_seconds", 0.0), field="timing_drift_seconds",
    )
    drift_threshold = _finite_number(
        evidence.get("drift_threshold_seconds", 0.12), field="drift_threshold_seconds",
    )
    if drift_threshold <= 0:
        raise ValueError("drift_threshold_seconds must be > 0")
    forced_alignment = drift > drift_threshold
    existing_captions = evidence.get("existing_captions") or {}
    if not isinstance(existing_captions, dict):
        raise ValueError("existing_captions must be an object")
    existing_caption_available = existing_captions.get("available") is True
    existing_caption_hash = existing_captions.get("sha256") if existing_caption_available else None
    if existing_caption_available and existing_caption_hash is None:
        raise ValueError("existing_captions sha256 is required when captions are available")
    if existing_caption_hash is not None:
        existing_caption_hash = str(existing_caption_hash).lower()
        if len(existing_caption_hash) != 64 or any(c not in "0123456789abcdef" for c in existing_caption_hash):
            raise ValueError("existing_captions sha256 must be a 64-character hex digest")
    explicit_required = {
        str(value).strip() for value in evidence.get("required_capabilities") or []
        if str(value).strip()
    }
    required = set(explicit_required)
    if precise:
        required.add("word_alignment")
    if forced_alignment:
        required.add("word_alignment")
    if diarization:
        required.add("diarization")
    if speaker_labels:
        required.add("speaker_labels")

    if language.startswith("zh") and (hotwords or noise_score >= 0.6) and _available(config, "funasr"):
        primary = "funasr"
        reason = "Chinese terminology or noisy-audio evidence requested"
    elif (speaker_labels or precise or forced_alignment or diarization) and _available(config, "whisperx"):
        primary = "whisperx"
        reason = "speaker, diarization, or alignment evidence requested"
    elif _available(config, "local_faster_whisper"):
        primary = "local_faster_whisper"
        reason = "stable local default"
    else:
        primary = next((name for name in BACKENDS if _available(config, name)), None)
        reason = "first configured ASR backend" if primary else "no configured ASR backend is available"

    pipeline: list[dict[str, str]] = []
    covered: set[str] = set()
    if primary:
        pipeline.append({"role": "transcription", "backend": primary})
        covered.update(_capabilities(config, primary))
    role_for_capability = {
        "word_alignment": "alignment",
        "speaker_labels": "speaker_labels",
        "diarization": "diarization",
    }
    for capability in sorted(required - covered):
        backend = _backend_for_capability(
            config, capability, preferred=("whisperx", "funasr", "local_faster_whisper"),
        )
        if backend is None:
            continue
        role = role_for_capability.get(capability, capability)
        stage = {"role": role, "backend": backend}
        if stage not in pipeline:
            pipeline.append(stage)
        covered.update(_capabilities(config, backend))
    if diarization and primary and "diarization" in _capabilities(config, primary):
        stage = {"role": "diarization", "backend": primary}
        if stage not in pipeline:
            pipeline.append(stage)
    missing = sorted(required - covered)
    if missing:
        raise AsrCapabilityError(
            "required ASR capabilities are unavailable: " + ", ".join(missing)
        )
    if primary is None and explicit_required:
        raise AsrCapabilityError("required ASR transcription backend is unavailable")
    normalized_evidence = {
        "language": language,
        "hotwords": hotwords,
        "speaker_count": speaker_count,
        "precise_word_alignment": precise,
        "speaker_labels": speaker_labels,
        "diarization": diarization,
        "noise_score": noise_score,
        "existing_captions_available": existing_caption_available,
        "existing_captions_sha256": existing_caption_hash,
        "timing_drift_seconds": drift,
        "drift_threshold_seconds": drift_threshold,
        "forced_alignment_triggered": forced_alignment,
    }
    result = {
        "schema_version": 1,
        "selected_backend": primary or "none",
        "reason": reason,
        "pipeline": pipeline,
        "required_capabilities": sorted(required),
        "missing_required_capabilities": missing,
        "evidence": normalized_evidence,
        "route_input_sha256": _canonical_sha256({
            "backends": config.get("backends", {}),
            "evidence": normalized_evidence,
            "required_capabilities": sorted(required),
        }),
        "ownership": {
            "routing_adapter_and_qa": "content-preserving-video-editor",
            "word_transcript": "video-use",
            "timeline_and_edl": "video-use",
            "final_edit_correctness": "video-use",
        },
        "semantic_deletion_authority": False,
        "output_contract": "video-use top-level word timestamps",
    }
    result["route_sha256"] = route_sha256(result)
    return result


def choose_backend(config: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    route = choose_pipeline(config, evidence)
    selected = route["selected_backend"]
    fallbacks: list[str] = []
    language = route["evidence"]["language"]
    if (route["evidence"]["speaker_count"] > 1 or route["evidence"]["precise_word_alignment"]):
        if selected != "whisperx":
            fallbacks.append("whisperx_unavailable")
    if language.startswith("zh") and route["evidence"]["hotwords"] and selected != "funasr":
        fallbacks.append("funasr_unavailable")
    if selected != "local_faster_whisper" and not _available(config, "local_faster_whisper"):
        fallbacks.append("local_faster_whisper_unavailable")
    result = {**route, "fallbacks": fallbacks}
    result["route_sha256"] = route_sha256(result)
    return result


def _word_rows(raw: dict[str, Any]) -> list[tuple[dict[str, Any], Any]]:
    if isinstance(raw.get("words"), list):
        return [(row, row.get("speaker_id", row.get("speaker"))) for row in raw["words"]]
    rows: list[tuple[dict[str, Any], Any]] = []
    for segment in raw.get("segments") or []:
        speaker = segment.get("speaker_id", segment.get("speaker"))
        for word in segment.get("words") or []:
            rows.append((word, word.get("speaker_id", word.get("speaker", speaker))))
    return rows


def normalize_transcript(raw: dict[str, Any], *, backend: str) -> dict[str, Any]:
    raw_rows = _word_rows(raw)
    words: list[dict[str, Any]] = []
    timing_repairs: list[dict[str, Any]] = []
    for index, (row, speaker) in enumerate(raw_rows):
        raw_text = row.get("text", row.get("word"))
        if not isinstance(raw_text, str) or not raw_text or row.get("start") is None or row.get("end") is None:
            raise ValueError(f"missing text or timing at ASR word index {index}")
        text = raw_text
        try:
            start = float(row["start"])
            end = float(row["end"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid ASR word timing at index {index}") from error
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ValueError(f"invalid ASR word timing at index {index}")
        word_id = row.get("id", f"w{len(words):06d}")
        if end == start:
            original_start = start
            original_end = end
            previous_end = float(words[-1]["end"]) if words else None
            next_start: float | None = None
            if index + 1 < len(raw_rows):
                next_row = raw_rows[index + 1][0]
                try:
                    candidate = float(next_row.get("start"))
                except (TypeError, ValueError):
                    candidate = float("nan")
                if math.isfinite(candidate):
                    next_start = candidate
            reason = ""
            if previous_end is not None and previous_end < start and (
                next_start is None or next_start <= start
            ):
                start = max(previous_end, start - 0.2)
                reason = "zero_duration_word_assigned_to_preceding_silence"
            elif next_start is not None and next_start > end:
                end = min(next_start, end + 0.2)
                reason = "zero_duration_word_assigned_to_following_silence"
            if end <= start:
                raise ValueError(f"invalid ASR word timing at index {index}")
            timing_repairs.append({
                "word_id": word_id,
                "word_index": index,
                "reason": reason,
                "original_start": original_start,
                "original_end": original_end,
                "repaired_start": start,
                "repaired_end": end,
            })
        confidence = row.get("confidence", row.get("score", row.get("probability")))
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid ASR word confidence at index {index}") from error
            if not math.isfinite(confidence):
                raise ValueError(f"invalid ASR word confidence at index {index}")
        words.append({
            "id": word_id,
            "type": "word",
            "text": text,
            "start": start,
            "end": end,
            "speaker_id": speaker,
            "confidence": confidence,
        })
    if not words:
        raise ValueError("ASR result contains no valid word timestamps")
    return {
        "schema_version": 1,
        "language_code": raw.get("language_code", raw.get("language", "unknown")),
        "words": words,
        "normalization": {
            "backend": backend,
            "text_or_timing_modified": bool(timing_repairs),
            "timing_repairs": timing_repairs,
            "semantic_deletion_authority": False,
        },
    }


def transcript_sha256(transcript: dict[str, Any]) -> str:
    canonical = json.dumps(
        transcript, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def route_sha256(route: dict[str, Any]) -> str:
    """Hash a route without trusting or recursively hashing its declared digest."""
    if not isinstance(route, dict):
        raise ValueError("ASR route must be an object")
    return _canonical_sha256({key: value for key, value in route.items() if key != "route_sha256"})


def build_asr_quality_report(
    transcript: dict[str, Any], *, route: dict[str, Any], source_media_sha256: str,
    measured_drift_seconds: float, drift_threshold_seconds: float,
) -> dict[str, Any]:
    """Create a fail-closed QA record bound to route, transcript, and source media."""
    media_hash = str(source_media_sha256).lower()
    if len(media_hash) != 64 or any(c not in "0123456789abcdef" for c in media_hash):
        raise ValueError("source_media_sha256 must be a 64-character hex digest")
    drift = _finite_number(measured_drift_seconds, field="measured_drift_seconds")
    threshold = _finite_number(drift_threshold_seconds, field="drift_threshold_seconds")
    if threshold <= 0:
        raise ValueError("drift_threshold_seconds must be > 0")
    declared_route_hash = route.get("route_sha256")
    actual_route_hash = route_sha256(route)
    if declared_route_hash is not None and declared_route_hash != actual_route_hash:
        raise ValueError("ASR route_sha256 is stale")
    words = transcript.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("ASR transcript requires normalized words")
    normalized_text = " ".join(str(row.get("text") or "") for row in words).casefold()
    hotwords = route.get("evidence", {}).get("hotwords") or []
    missing_terms = [term for term in hotwords if str(term).casefold() not in normalized_text]
    alignment_required = "word_alignment" in set(route.get("required_capabilities") or [])
    drift_pass = drift <= threshold or alignment_required
    status = "pass" if drift_pass and not missing_terms else "action_required"
    return {
        "schema_version": 1,
        "status": status,
        "route_sha256": actual_route_hash,
        "route_input_sha256": route.get("route_input_sha256"),
        "transcript_sha256": transcript_sha256(transcript),
        "source_media_sha256": media_hash,
        "word_count": len(words),
        "measured_drift_seconds": drift,
        "drift_threshold_seconds": threshold,
        "forced_alignment_required": drift > threshold,
        "alignment_routed": alignment_required,
        "missing_hotwords": missing_terms,
        "ownership": {
            "routing_adapter_and_qa": "content-preserving-video-editor",
            "transcript_and_timeline": "video-use",
            "final_edit_correctness": "video-use",
        },
    }


def _validate_bound_report(
    report: dict[str, Any] | None, *, label: str, transcript_hash: str,
    count_field: str, word_count: int,
) -> None:
    if not isinstance(report, dict) or report.get("status") != "pass":
        raise ValueError(f"{label} report with pass status is required")
    if report.get("transcript_sha256") != transcript_hash:
        raise ValueError(f"{label} report transcript hash is stale")
    count = report.get(count_field)
    if isinstance(count, bool) or count != word_count:
        raise ValueError(f"{label} report {count_field} must equal transcript word count")


def validate_pipeline_reports(
    transcript: dict[str, Any], *, route: dict[str, Any],
    speaker_report: dict[str, Any] | None = None,
    alignment_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify hash-bound speaker/alignment reports required by the selected route."""
    words = transcript.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("ASR transcript requires normalized words")
    required = set(route.get("required_capabilities") or [])
    digest = transcript_sha256(transcript)
    if "speaker_labels" in required:
        if any(row.get("speaker_id") in (None, "") for row in words):
            raise ValueError("speaker report cannot pass while transcript speaker labels are missing")
        _validate_bound_report(
            speaker_report, label="speaker", transcript_hash=digest,
            count_field="labeled_word_count", word_count=len(words),
        )
    if "word_alignment" in required:
        _validate_bound_report(
            alignment_report, label="alignment", transcript_hash=digest,
            count_field="aligned_word_count", word_count=len(words),
        )
    return {
        "schema_version": 1,
        "status": "pass",
        "transcript_sha256": digest,
        "word_count": len(words),
        "validated_reports": sorted(
            label for capability, label in (
                ("speaker_labels", "speaker"), ("word_alignment", "alignment"),
            ) if capability in required
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    route = sub.add_parser("route")
    route.add_argument("--config", required=True)
    route.add_argument("--evidence", required=True)
    route.add_argument("--out", required=True)
    pipeline = sub.add_parser("pipeline")
    pipeline.add_argument("--config", required=True)
    pipeline.add_argument("--evidence", required=True)
    pipeline.add_argument("--out", required=True)
    normalize = sub.add_parser("normalize")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--backend", required=True, choices=BACKENDS)
    normalize.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "route":
        result = choose_backend(read_json(Path(args.config)), read_json(Path(args.evidence)))
    elif args.command == "pipeline":
        result = choose_pipeline(read_json(Path(args.config)), read_json(Path(args.evidence)))
    else:
        result = normalize_transcript(read_json(Path(args.input)), backend=args.backend)
    write_json(Path(args.out), result)
    print(Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
