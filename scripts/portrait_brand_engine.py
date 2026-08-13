#!/usr/bin/env python3
"""Compile explicit portrait-brand eligibility and energy contracts."""
from __future__ import annotations

import math
import re
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from portrait_brand_contracts import validate_portrait_contract_schema


class PortraitBrandCompilationError(ValueError):
    """Raised when portrait-brand intent cannot be compiled without guessing."""


ENERGY_TIERS = {"quiet", "micro", "meso", "macro"}
TRANSITION_INTENTS = {"rise", "settle", "contrast", "resolve", "sustain"}
EVIDENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def _stable_hash(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PortraitBrandCompilationError(f"{label} must be a mapping")
    return value


def _authority_map(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        raise PortraitBrandCompilationError("evidence_authorities must be a mapping")
    result: dict[str, Mapping[str, Any]] = {}
    for evidence_id, row in value.items():
        if not isinstance(evidence_id, str) or not EVIDENCE_ID_PATTERN.fullmatch(evidence_id):
            raise PortraitBrandCompilationError("evidence authority IDs must be stable strings")
        if not isinstance(row, Mapping) or row.get("evidence_id") != evidence_id:
            raise PortraitBrandCompilationError(f"{evidence_id}: authority record is malformed")
        if row.get("authority_sha256") != _stable_hash(
            {key: item for key, item in row.items() if key != "authority_sha256"}
        ):
            raise PortraitBrandCompilationError(f"{evidence_id}: authority hash is stale")
        result[evidence_id] = row
    return result


def _overlaps(row: Mapping[str, Any], start: float, end: float) -> bool:
    window = row.get("window")
    if not isinstance(window, Mapping):
        return False
    try:
        observed_start = float(window.get("start_seconds"))
        observed_end = float(window.get("end_seconds"))
    except (TypeError, ValueError):
        return False
    return math.isfinite(observed_start) and math.isfinite(observed_end) and (
        observed_end >= start and observed_start <= end
    )


def _authority_overlaps_event(
    row: Mapping[str, Any], *, source_start: float, source_end: float,
    output_start: float, output_end: float,
) -> bool:
    domain = row.get("time_domain")
    if domain == "source":
        return _overlaps(row, source_start, source_end)
    if domain == "output":
        return _overlaps(row, output_start, output_end)
    return False


def _map_source_time_to_output(edl: Mapping[str, Any] | None, source_time: float) -> float | None:
    """Map one evidenced source timestamp through the current EDL without guessing."""
    if not isinstance(edl, Mapping):
        return None
    rows = edl.get("segments", edl.get("ranges", []))
    if not isinstance(rows, list):
        raise PortraitBrandCompilationError("edl segments/ranges must be a list")
    cursor = 0.0
    matches: list[float] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise PortraitBrandCompilationError(f"edl segments[{index}] must be a mapping")
        try:
            start = float(row.get("start"))
            end = float(row.get("end"))
            timeline_start = float(row.get("timeline_start", cursor))
        except (TypeError, ValueError):
            raise PortraitBrandCompilationError(f"edl segments[{index}] timing is malformed")
        if not all(math.isfinite(value) for value in (start, end, timeline_start)) or end <= start:
            raise PortraitBrandCompilationError(f"edl segments[{index}] timing is invalid")
        if start <= source_time <= end:
            matches.append(timeline_start + source_time - start)
        cursor = max(cursor, timeline_start + end - start)
    if len(matches) > 1:
        raise PortraitBrandCompilationError("gesture apex maps to multiple EDL segments")
    return matches[0] if matches else None


def evaluate_portrait_eligibility(
    *, project: Mapping[str, Any], profile: Mapping[str, Any],
    source_media: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic eligibility decision without enabling the feature."""
    if not isinstance(project, Mapping) or not isinstance(profile, Mapping) or not isinstance(source_media, Mapping):
        return {
            "status": "not_eligible",
            "grammar_id": None,
            "reasons": ["project, profile, and source_media must be mappings"],
            "selection_owner": "content-preserving-video-editor.portrait-brand-engine",
            "automatic_brand_approval": False,
        }
    reasons: list[str] = []
    portrait = (
        (project.get("motion_quality") or {}).get("portrait_brand")
        if isinstance(project.get("motion_quality"), Mapping)
        else None
    )
    if not isinstance(portrait, Mapping) or portrait.get("enabled") is not True:
        reasons.append("motion_quality.portrait_brand is not explicitly enabled")
    if not isinstance(project.get("motion_quality"), Mapping) or (
        project["motion_quality"].get("enabled") is not True
    ):
        reasons.append("motion_quality.enabled is not true")
    identity = project.get("identity")
    if not isinstance(identity, Mapping) or identity.get("mode") != "self":
        reasons.append("identity.mode is not self")
    if profile.get("profile_id") != "hongrun" or profile.get("identity_mode") != "self":
        reasons.append("profile is not the HongRun self profile")
    if source_media.get("orientation") != "portrait":
        reasons.append("source orientation is not portrait")
    if source_media.get("source_type") != "talking_head":
        reasons.append("source type is not talking_head")
    if isinstance(portrait, Mapping) and portrait.get("grammar_version") != 2:
        reasons.append("portrait grammar version is not 2")
    if isinstance(portrait, Mapping) and portrait.get("require_user_brand_approval") is not True:
        reasons.append("named-user brand approval is not required")
    return {
        "status": "eligible" if not reasons else "not_eligible",
        "grammar_id": "hongrun-portrait-expressive-v2" if not reasons else None,
        "reasons": reasons,
        "selection_owner": "content-preserving-video-editor.portrait-brand-engine",
        "automatic_brand_approval": False,
    }


def build_portrait_energy_authorities(
    *, transcript: Mapping[str, Any], evidence_bundle: Mapping[str, Any],
    subject_track: Mapping[str, Any] | None = None,
    semantic_brief: Mapping[str, Any] | None = None,
    edl: Mapping[str, Any] | None = None,
    source_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Expose stable, current evidence IDs that an editorial brief may cite."""
    transcript = _mapping(transcript, "transcript")
    evidence_bundle = _mapping(evidence_bundle, "evidence_bundle")
    if subject_track is not None:
        subject_track = _mapping(subject_track, "subject_track")
    if semantic_brief is not None:
        semantic_brief = _mapping(semantic_brief, "semantic_brief")
    if edl is not None:
        edl = _mapping(edl, "edl")
    source_hashes = dict(source_hashes or {})
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        evidence_id: str, kind: str, payload: Mapping[str, Any], *, source: str,
        status: str = "current",
    ) -> None:
        if not EVIDENCE_ID_PATTERN.fullmatch(evidence_id) or evidence_id in seen:
            return
        seen.add(evidence_id)
        row = {
            "evidence_id": evidence_id,
            "kind": kind,
            "status": status,
            "source": source,
            "source_sha256": source_hashes.get(source) or _stable_hash(
                {"source": source, "payload": payload}
            ),
            **dict(payload),
        }
        row["authority_sha256"] = _stable_hash(row)
        rows.append(row)

    transcript_words = transcript.get("words")
    if transcript_words is None:
        transcript_words = []
    if not isinstance(transcript_words, list):
        raise PortraitBrandCompilationError("transcript.words must be a list")
    for word in transcript_words:
        if not isinstance(word, Mapping):
            continue
        word_id = str(word.get("id") or "")
        add(word_id, "transcript_word", {
            "window": {"start_seconds": word.get("start"), "end_seconds": word.get("end")},
            "time_domain": "source",
            "text": str(word.get("text") or ""),
        }, source="transcript")
    representative_frames = evidence_bundle.get("representative_frames")
    if representative_frames is None:
        representative_frames = []
    if not isinstance(representative_frames, list):
        raise PortraitBrandCompilationError("evidence_bundle.representative_frames must be a list")
    for index, frame in enumerate(representative_frames):
        if not isinstance(frame, Mapping):
            continue
        digest = str(frame.get("sha256") or "")
        frame_id = str(frame.get("id") or "")
        if not EVIDENCE_ID_PATTERN.fullmatch(frame_id):
            frame_id = f"frame:{digest[:16]}" if len(digest) >= 16 else f"frame:{index}"
        add(frame_id, "representative_frame", {
            "path": str(frame.get("path") or ""),
            "sha256": digest,
            "timestamp_seconds": frame.get("timestamp_seconds"),
            "coverage": frame.get("coverage"),
            "time_domain": "source",
        }, source="evidence_bundle")
    if isinstance(subject_track, Mapping):
        tracking = subject_track.get("tracking")
        series = tracking.get("series") if isinstance(tracking, Mapping) else None
        if series is not None and not isinstance(series, list):
            raise PortraitBrandCompilationError("subject_track.tracking.series must be a list")
        sample_interval = (
            tracking.get("sample_interval") if isinstance(tracking, Mapping) else None
        )
        try:
            radius = max(float(sample_interval or 0.4) / 2.0, 0.01)
        except (TypeError, ValueError):
            radius = 0.2
        for index, observation in enumerate(series or []):
            if not isinstance(observation, Mapping):
                continue
            timestamp = observation.get("time")
            try:
                timestamp_value = float(timestamp)
            except (TypeError, ValueError):
                continue
            observation_id = str(observation.get("id") or f"subject:{index}")
            add(observation_id, "subject_track", {
                "window": {
                    "start_seconds": max(0.0, timestamp_value - radius),
                    "end_seconds": timestamp_value + radius,
                },
                "visible": observation.get("status") == "tracked" and bool(observation.get("face")),
                "face": observation.get("face"),
                "smoothed_center": observation.get("smoothed_center"),
                "crop": observation.get("crop"),
                "time_domain": "source",
            }, source="subject_track", status=str(observation.get("status") or "unknown"))
        gesture_rows = subject_track.get("gesture_observations")
        if gesture_rows is not None and not isinstance(gesture_rows, list):
            raise PortraitBrandCompilationError(
                "subject_track.gesture_observations must be a list"
            )
        if gesture_rows is None:
            hand_tracking = subject_track.get("hand_tracking")
            gesture_rows = hand_tracking.get("series") if isinstance(hand_tracking, Mapping) else []
            if not isinstance(gesture_rows, list):
                raise PortraitBrandCompilationError(
                    "subject_track.hand_tracking.series must be a list"
                )
        for index, observation in enumerate(gesture_rows or []):
            if not isinstance(observation, Mapping):
                continue
            window = observation.get("window")
            if not isinstance(window, Mapping):
                continue
            observation_id = str(observation.get("id") or f"gesture:{index}")
            gesture_payload = {
                "window": dict(window),
                "visible": observation.get("visible") is True,
                "confidence": observation.get("confidence"),
                "points": list(observation.get("points") or []),
                "time_domain": "source",
            }
            if observation.get("apex_seconds") is not None:
                apex = _finite_number(
                    observation.get("apex_seconds"),
                    f"subject_track.gesture_observations[{index}].apex_seconds",
                    minimum=0,
                )
                gesture_payload["source_apex_seconds"] = apex
                output_apex = _map_source_time_to_output(edl, apex)
                if output_apex is not None:
                    gesture_payload["output_apex_seconds"] = round(output_apex, 6)
            add(
                observation_id, "gesture_track", gesture_payload,
                source="subject_track", status=str(observation.get("status") or "tracked"),
            )
    if isinstance(edl, Mapping):
        boundaries = edl.get("chapter_boundaries")
        if boundaries is None:
            boundaries = []
        if not isinstance(boundaries, list):
            raise PortraitBrandCompilationError("edl.chapter_boundaries must be a list")
        for index, boundary in enumerate(boundaries):
            if not isinstance(boundary, Mapping):
                raise PortraitBrandCompilationError(
                    f"edl.chapter_boundaries[{index}] must be a mapping"
                )
            boundary_id = str(boundary.get("id") or "")
            output_time = _finite_number(
                boundary.get("output_time"),
                f"edl.chapter_boundaries[{index}].output_time", minimum=0,
            )
            radius = 0.05
            add(boundary_id, "chapter_boundary", {
                "window": {
                    "start_seconds": max(0.0, output_time - radius),
                    "end_seconds": output_time + radius,
                },
                "time_domain": "output",
                "structural": True,
                "chapter_id": boundary.get("chapter_id"),
                "source_time": boundary.get("source_time"),
            }, source="edl")
    by_id = {row["evidence_id"]: row for row in rows}
    return {
        "schema_version": 1,
        "evidence": rows,
        "evidence_by_id": by_id,
        "known_evidence_ids": sorted(seen),
        "selection_policy": "current_typed_hash_bound_evidence_only",
    }


def derive_portrait_chapters(
    semantic_brief: Mapping[str, Any], *, evidence_authorities: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate explicit chapter intent and derive its exact output coverage."""
    semantic_brief = _mapping(semantic_brief, "semantic_brief")
    authority_by_id = _authority_map(evidence_authorities)
    events = semantic_brief.get("events")
    if not isinstance(events, list) or not events:
        raise PortraitBrandCompilationError("portrait chapters require semantic opportunities")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            raise PortraitBrandCompilationError("portrait chapter events must be mappings")
        intent = event.get("portrait_energy_intent")
        if not isinstance(intent, Mapping):
            raise PortraitBrandCompilationError(
                f"{event.get('id')}: explicit portrait_energy_intent is required"
            )
        chapter_id = str(intent.get("chapter_id") or "")
        if not EVIDENCE_ID_PATTERN.fullmatch(chapter_id):
            raise PortraitBrandCompilationError(
                f"{event.get('id')}: chapter_id must be a stable contract ID"
            )
        if chapter_id not in grouped:
            grouped[chapter_id] = []
            order.append(chapter_id)
        grouped[chapter_id].append(event)
    rows: list[dict[str, Any]] = []
    previous_end = 0.0
    for chapter_id in order:
        chapter_events = grouped[chapter_id]
        starts = [
            _finite_number(row.get("output_start"), f"{row.get('id')}.output_start", minimum=0)
            for row in chapter_events
        ]
        ends = [
            _finite_number(row.get("output_end"), f"{row.get('id')}.output_end", minimum=0)
            for row in chapter_events
        ]
        start, end = min(starts), max(ends)
        if start < previous_end:
            raise PortraitBrandCompilationError("portrait chapter windows overlap or regress")
        previous_end = end
        first = chapter_events[0]["portrait_energy_intent"]
        last = chapter_events[-1]["portrait_energy_intent"]
        evidence_refs: list[str] = []
        for event in chapter_events:
            for value in event["portrait_energy_intent"].get("evidence_refs") or []:
                if value in authority_by_id and value not in evidence_refs:
                    evidence_refs.append(value)
        if not evidence_refs:
            raise PortraitBrandCompilationError(f"chapter {chapter_id} has no current evidence")
        entry = _finite_number(
            (first.get("signals") or {}).get("semantic_pressure"),
            f"chapter {chapter_id}.entry_energy", minimum=0,
        )
        exit_ = _finite_number(
            (last.get("signals") or {}).get("semantic_pressure"),
            f"chapter {chapter_id}.exit_energy", minimum=0,
        )
        if entry > 1 or exit_ > 1:
            raise PortraitBrandCompilationError("chapter energy must be in [0, 1]")
        rows.append({
            "chapter_id": chapter_id,
            "output_window": {"start_seconds": start, "end_seconds": end},
            "entry_energy": entry,
            "exit_energy": exit_,
            "intent": str(last.get("transition_intent") or ""),
            "evidence_refs": evidence_refs,
        })
    return rows


def _finite_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PortraitBrandCompilationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise PortraitBrandCompilationError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise PortraitBrandCompilationError(f"{label} must be at least {minimum}")
    return result


def _window(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, Mapping):
        raise PortraitBrandCompilationError(f"{label} must be a mapping")
    start = _finite_number(value.get("start_seconds"), f"{label}.start_seconds", minimum=0)
    end = _finite_number(value.get("end_seconds"), f"{label}.end_seconds", minimum=0)
    if end <= start:
        raise PortraitBrandCompilationError(f"{label} end must be after start")
    return start, end


def compile_portrait_energy_map(
    *, project_id: str, semantic_brief: Mapping[str, Any],
    source_media: Mapping[str, Any], input_hashes: Mapping[str, str],
    chapters: Sequence[Mapping[str, Any]],
    evidence_authorities: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile explicit editorial energy intent; never infer tiers from cadence."""
    semantic_brief = _mapping(semantic_brief, "semantic_brief")
    authority_by_id = _authority_map(evidence_authorities)
    if semantic_brief.get("schema_version") != 3 or (
        semantic_brief.get("opportunity_model") != "decision_complete_v1"
    ):
        raise PortraitBrandCompilationError(
            "portrait energy requires a decision-complete semantic brief"
        )
    events = semantic_brief.get("events")
    if not isinstance(events, list) or not events:
        raise PortraitBrandCompilationError("portrait energy requires semantic opportunities")
    if not isinstance(project_id, str) or not project_id.strip():
        raise PortraitBrandCompilationError("project_id must be non-empty")
    if not isinstance(source_media, Mapping):
        raise PortraitBrandCompilationError("source_media must be a file reference")
    if not isinstance(input_hashes, Mapping) or len(input_hashes) < 4:
        raise PortraitBrandCompilationError("input_hashes requires at least four authorities")

    if not isinstance(chapters, Sequence) or isinstance(chapters, (str, bytes)):
        raise PortraitBrandCompilationError("chapters must be a sequence")
    chapter_rows: list[dict[str, Any]] = []
    chapter_windows: dict[str, tuple[float, float]] = {}
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, Mapping):
            raise PortraitBrandCompilationError(f"chapters[{index}] must be a mapping")
        chapter_id = str(chapter.get("chapter_id") or "")
        if not chapter_id or chapter_id in chapter_windows:
            raise PortraitBrandCompilationError("chapter IDs must be non-empty and unique")
        output_window = chapter.get("output_window")
        chapter_windows[chapter_id] = _window(
            output_window, f"chapters[{index}].output_window"
        )
        evidence_refs = list(chapter.get("evidence_refs") or [])
        unknown = [value for value in evidence_refs if value not in authority_by_id]
        if unknown:
            raise PortraitBrandCompilationError(
                f"chapter {chapter_id} cites unknown evidence: {', '.join(unknown)}"
            )
        chapter_rows.append(dict(chapter))
    if not chapter_rows:
        raise PortraitBrandCompilationError("portrait energy requires at least one chapter")

    opportunities: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise PortraitBrandCompilationError(f"events[{index}] must be a mapping")
        event_id = str(event.get("id") or "")
        if not event_id or event_id in observed_ids:
            raise PortraitBrandCompilationError("semantic event IDs must be non-empty and unique")
        observed_ids.add(event_id)
        intent = event.get("portrait_energy_intent")
        if not isinstance(intent, Mapping):
            raise PortraitBrandCompilationError(
                f"{event_id}: explicit portrait_energy_intent is required"
            )
        chapter_id = str(intent.get("chapter_id") or "")
        if chapter_id not in chapter_windows:
            raise PortraitBrandCompilationError(f"{event_id}: chapter_id is not authoritative")
        tier = str(intent.get("tier") or "")
        if tier not in ENERGY_TIERS:
            raise PortraitBrandCompilationError(f"{event_id}: unsupported energy tier")
        transition = str(intent.get("transition_intent") or "")
        if transition not in TRANSITION_INTENTS:
            raise PortraitBrandCompilationError(f"{event_id}: unsupported transition intent")
        rationale = str(intent.get("rationale") or "").strip()
        if len(rationale) < 8:
            raise PortraitBrandCompilationError(f"{event_id}: energy rationale is required")
        raw_evidence_refs = intent.get("evidence_refs")
        if not isinstance(raw_evidence_refs, list) or any(
            not isinstance(value, str) or not value for value in raw_evidence_refs
        ):
            raise PortraitBrandCompilationError(f"{event_id}: evidence_refs must be a list of IDs")
        evidence_refs = list(raw_evidence_refs)
        if not evidence_refs:
            raise PortraitBrandCompilationError(f"{event_id}: energy evidence is required")
        unknown = [value for value in evidence_refs if value not in authority_by_id]
        if unknown:
            raise PortraitBrandCompilationError(
                f"{event_id}: unknown energy evidence: {', '.join(unknown)}"
            )
        raw_words = event.get("transcript_word_ids")
        if not isinstance(raw_words, list) or any(
            not isinstance(value, str) or not value for value in raw_words
        ):
            raise PortraitBrandCompilationError(
                f"{event_id}: transcript_word_ids must be a list of IDs"
            )
        words = list(raw_words)
        if not words:
            raise PortraitBrandCompilationError(f"{event_id}: transcript word IDs are required")
        output_start = _finite_number(event.get("output_start"), f"{event_id}.output_start", minimum=0)
        output_end = _finite_number(event.get("output_end"), f"{event_id}.output_end", minimum=0)
        source_start = _finite_number(event.get("source_start"), f"{event_id}.source_start", minimum=0)
        source_end = _finite_number(event.get("source_end"), f"{event_id}.source_end", minimum=0)
        if output_end <= output_start:
            raise PortraitBrandCompilationError(f"{event_id}: output window is invalid")
        if source_end <= source_start:
            raise PortraitBrandCompilationError(f"{event_id}: source window is invalid")
        chapter_start, chapter_end = chapter_windows[chapter_id]
        if output_start < chapter_start or output_end > chapter_end:
            raise PortraitBrandCompilationError(f"{event_id}: output window leaves its chapter")
        signals = intent.get("signals")
        if not isinstance(signals, Mapping):
            raise PortraitBrandCompilationError(f"{event_id}: energy signals are required")
        semantic_pressure = _finite_number(
            signals.get("semantic_pressure"), f"{event_id}.semantic_pressure", minimum=0
        )
        if semantic_pressure > 1:
            raise PortraitBrandCompilationError(f"{event_id}: semantic_pressure must be <= 1")
        speech_rate = _finite_number(
            signals.get("speech_rate_wpm"), f"{event_id}.speech_rate_wpm", minimum=0
        )
        pause = _finite_number(
            signals.get("pause_seconds"), f"{event_id}.pause_seconds", minimum=0
        )
        emotional_turn = signals.get("emotional_turn")
        if not isinstance(emotional_turn, str) or not emotional_turn.strip():
            raise PortraitBrandCompilationError(f"{event_id}: emotional_turn is required")
        gesture_id = signals.get("gesture_evidence_id")
        gesture_authority = authority_by_id.get(gesture_id) if isinstance(gesture_id, str) else None
        if gesture_id is not None and (
            not isinstance(gesture_id, str)
            or gesture_id not in evidence_refs
            or not isinstance(gesture_authority, Mapping)
            or gesture_authority.get("kind") != "gesture_track"
            or gesture_authority.get("status") not in {"tracked", "visible", "current"}
            or gesture_authority.get("visible") is not True
            or not _authority_overlaps_event(
                gesture_authority, source_start=source_start, source_end=source_end,
                output_start=output_start, output_end=output_end,
            )
        ):
            raise PortraitBrandCompilationError(
                f"{event_id}: gesture evidence {gesture_id} is missing or unbound"
            )
        boundary_id = signals.get("chapter_boundary_evidence_id")
        boundary_authority = authority_by_id.get(boundary_id) if isinstance(boundary_id, str) else None
        if boundary_id is not None and (
            not isinstance(boundary_id, str)
            or boundary_id not in evidence_refs
            or not isinstance(boundary_authority, Mapping)
            or boundary_authority.get("kind") != "chapter_boundary"
            or boundary_authority.get("structural") is not True
            or boundary_authority.get("source") != "edl"
            or boundary_authority.get("chapter_id") != chapter_id
            or not _authority_overlaps_event(
                boundary_authority, source_start=source_start, source_end=source_end,
                output_start=output_start, output_end=output_end,
            )
        ):
            raise PortraitBrandCompilationError(
                f"{event_id}: chapter boundary evidence is missing or unbound"
            )
        if tier == "macro" and boundary_id is None:
            raise PortraitBrandCompilationError(
                f"{event_id}: macro energy requires structural chapter-boundary evidence"
            )
        max_layers = intent.get("max_attention_layers")
        if isinstance(max_layers, bool) or not isinstance(max_layers, int) or not 0 <= max_layers <= 2:
            raise PortraitBrandCompilationError(
                f"{event_id}: max_attention_layers must be an integer in [0, 2]"
            )
        if tier == "quiet" and max_layers != 0:
            raise PortraitBrandCompilationError(
                f"{event_id}: quiet energy must use zero attention layers"
            )
        fallback = str(intent.get("fallback_tier") or "")
        if fallback not in {"quiet", "micro", "meso"}:
            raise PortraitBrandCompilationError(f"{event_id}: fallback tier is invalid")
        row = {
            "semantic_event_id": event_id,
            "chapter_id": chapter_id,
            "tier": tier,
            "transition_intent": transition,
            "max_attention_layers": max_layers,
            "rationale": rationale,
            "evidence_refs": evidence_refs,
            "fallback_tier": fallback,
        }
        if gesture_id is not None:
            row["gesture_evidence_id"] = gesture_id
        if boundary_id is not None:
            row["chapter_boundary_evidence_id"] = boundary_id
        opportunities.append(row)
        diagnostics.append({
            "semantic_event_id": event_id,
            "source_window": {
                "start_seconds": event.get("source_start"),
                "end_seconds": event.get("source_end"),
            },
            "output_window": {
                "start_seconds": output_start,
                "end_seconds": output_end,
            },
            "transcript_word_ids": words,
            "signals": {
                "semantic_pressure": semantic_pressure,
                "emotional_turn": emotional_turn,
                "speech_rate_wpm": speech_rate,
                "pause_seconds": pause,
                "gesture_evidence_id": gesture_id,
                "chapter_boundary_evidence_id": boundary_id,
            },
            "copy_pressure": "reduce" if speech_rate >= 200 else "standard",
            "tier_source": "explicit_portrait_energy_intent",
        })

    energy_map = {
        "schema_version": 1,
        "project_id": project_id,
        "source_media": dict(source_media),
        "input_hashes": dict(input_hashes),
        "chapters": chapter_rows,
        "evidence_authorities": [
            dict(authority_by_id[evidence_id])
            for evidence_id in dict.fromkeys(
                reference
                for chapter in chapter_rows
                for reference in chapter.get("evidence_refs") or []
            )
        ] + [
            dict(authority_by_id[evidence_id])
            for evidence_id in dict.fromkeys(
                reference
                for event in opportunities
                for reference in event.get("evidence_refs") or []
            )
            if evidence_id not in {
                reference
                for chapter in chapter_rows
                for reference in chapter.get("evidence_refs") or []
            }
        ],
        "opportunities": opportunities,
        "selection_policy": {
            "fixed_cadence": False,
            "minimum_event_quota": False,
            "random_rotation": False,
            "density_is_diagnostic_only": True,
        },
    }
    schema_errors = validate_portrait_contract_schema(
        "portrait-energy-map", energy_map
    )
    if schema_errors:
        raise PortraitBrandCompilationError("; ".join(schema_errors))
    return {
        "schema_version": 1,
        "energy_map": energy_map,
        "diagnostics": diagnostics,
        "selection_inputs": "explicit_portrait_energy_intent_only",
        "fixed_cadence_used": False,
        "quota_used": False,
        "keyword_selection_used": False,
        "random_selection_used": False,
        "sfx_selection_used": False,
    }
