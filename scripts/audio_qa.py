#!/usr/bin/env python3
"""Blocking audio-plan QA for event SFX coverage, audibility, and BGM provenance."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def _resolve(base_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    candidate = Path(str(value))
    return candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _perceptual_errors(
    *, sfx: dict[str, Any], decisions: list[dict[str, Any]], events: list[dict[str, Any]],
    config: dict[str, Any], base_dir: Path,
) -> list[str]:
    """Validate decision coverage and delivered-mix evidence for the P1 policy."""
    errors: list[str] = []
    by_event = {
        str(row.get("event_id") or ""): row for row in decisions if isinstance(row, dict)
    }
    event_ids = [str(row.get("id") or "") for row in events]
    if set(by_event) != set(event_ids):
        errors.append("perceptual motion SFX requires 100% explicit decision coverage")

    cue_rows = [row for row in decisions if row.get("decision") == "cue"]
    event_count = len(events)
    if event_count:
        minimum_ratio = _number(config.get("minimum_audible_ratio"), 0.35)
        maximum_ratio = _number(config.get("maximum_audible_ratio"), 0.65)
        minimum_count = math.floor(event_count * minimum_ratio)
        maximum_count = math.ceil(event_count * maximum_ratio)
        if len(cue_rows) < minimum_count or len(cue_rows) > maximum_count:
            errors.append(
                f"motion SFX audible-cue ratio {len(cue_rows) / event_count:.3f} is outside "
                f"adaptive corridor {minimum_ratio:.3f}-{maximum_ratio:.3f}"
            )

    record = sfx.get("perceptual_evidence")
    if not isinstance(record, dict):
        return [*errors, "motion SFX perceptual delivered-mix evidence is missing"]
    evidence_path = _resolve(base_dir, record.get("path"))
    if not evidence_path or not evidence_path.is_file():
        return [*errors, "motion SFX perceptual delivered-mix evidence file is missing"]
    actual_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    if record.get("sha256") != actual_hash:
        return [*errors, "motion SFX perceptual delivered-mix evidence hash is stale"]
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [*errors, f"motion SFX perceptual evidence is unreadable: {error}"]
    if not isinstance(evidence, dict) or evidence.get("status") != "pass":
        return [*errors, "motion SFX perceptual evidence status is not pass"]
    evidence_rows = {
        str(row.get("event_id") or ""): row
        for row in (evidence.get("events") or []) if isinstance(row, dict)
    }
    if set(evidence_rows) != set(event_ids):
        errors.append("motion SFX perceptual evidence event inventory is stale")
    maximum_onset_error = _number(config.get("maximum_onset_error_ms"), 80.0)
    for event_id, decision in by_event.items():
        row = evidence_rows.get(event_id) or {}
        if row.get("decision") != decision.get("decision"):
            errors.append(f"motion SFX perceptual decision is stale: {event_id}")
            continue
        if decision.get("decision") == "intentionally_silent":
            if not decision.get("reason"):
                errors.append(f"motion event {event_id} silent perceptual decision lacks rationale")
            continue
        perceptual = row.get("perceptual") if isinstance(row.get("perceptual"), dict) else row
        fingerprint = str(decision.get("motif_fingerprint_sha256") or "")
        observed_fingerprint = perceptual.get("motif_fingerprint_sha256")
        if not observed_fingerprint and isinstance(perceptual.get("motif_fingerprint"), dict):
            observed_fingerprint = perceptual["motif_fingerprint"].get("sha256")
        if len(fingerprint) != 64 or observed_fingerprint != fingerprint:
            errors.append(f"motion SFX motif fingerprint is missing or stale: {event_id}")
        onset_error = _number(perceptual.get("onset_error_ms"), float("inf"))
        if onset_error > maximum_onset_error:
            errors.append(
                f"motion SFX onset error exceeds {maximum_onset_error:.1f} ms: {event_id}"
            )
        status = perceptual.get("audibility_status")
        if status != "audible_without_masking":
            errors.append(f"motion SFX perceptual audibility is {status}: {event_id}")
        for field in (
            "dialogue_window_lufs", "cue_window_lufs", "dialogue_cue_delta_lu",
        ):
            value = perceptual.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"motion SFX perceptual evidence lacks {field}: {event_id}")
    return errors


def validate(
    plan: dict[str, Any],
    storyboard: dict[str, Any],
    project: dict[str, Any] | None = None,
    *,
    base_dir: Path,
) -> list[str]:
    errors: list[str] = []
    project = project or {}
    base_dir = base_dir.resolve()

    if plan.get("speech_track", {}).get("dominant") is not True:
        errors.append("final audio plan must keep speech dominant")
    if not plan.get("provenance"):
        errors.append("final audio plan must record asset provenance")

    events = [
        event for event in (storyboard.get("events") or [])
        if event.get("treatment") != "quiet_source"
    ]
    sfx = plan.get("motion_sfx") or {}
    decisions = sfx.get("event_decisions") or []
    by_event: dict[str, dict[str, Any]] = {}
    for row in decisions:
        event_id = str(row.get("event_id", ""))
        if not event_id:
            errors.append("motion SFX decision is missing event_id")
        elif event_id in by_event:
            errors.append(f"motion SFX event has duplicate decisions: {event_id}")
        else:
            by_event[event_id] = row

    sfx_config = project.get("audio", {}).get("sfx", {})
    perceptual_config = sfx_config.get("perceptual") or {}
    perceptual_enabled = perceptual_config.get("enabled") is True
    minimum_duration = _number(sfx_config.get("minimum_cue_duration_seconds"), 0.6)
    minimum_level = _number(sfx_config.get("minimum_post_gain_mean_dbfs"), -34.0)
    maximum_level = _number(sfx_config.get("maximum_post_gain_mean_dbfs"), -18.0)
    cue_rows: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("id", ""))
        row = by_event.get(event_id)
        if not row:
            errors.append(f"motion event {event_id} is missing an explicit SFX decision")
            continue
        decision = row.get("decision")
        if decision == "intentionally_silent":
            if not row.get("reason"):
                errors.append(f"motion event {event_id} intentionally silent decision lacks a reason")
            continue
        if decision != "cue":
            errors.append(f"motion event {event_id} has unsupported SFX decision: {decision}")
            continue
        cue_rows.append(row)
        asset = _resolve(base_dir, row.get("asset"))
        authorized_sfx_root = (base_dir / "assets" / "sfx").resolve()
        if asset and not asset.is_relative_to(authorized_sfx_root):
            errors.append(
                f"motion event {event_id} SFX asset escapes authorized SFX root: "
                f"{authorized_sfx_root}"
            )
        elif not asset or not asset.is_file():
            errors.append(f"motion event {event_id} SFX asset is missing: {row.get('asset')}")
        duration = _number(row.get("duration_seconds"), -1.0)
        if duration < minimum_duration:
            errors.append(f"motion event {event_id} SFX is shorter than {minimum_duration:.2f}s")
        event_start = _number(event.get("start"), float("-inf"))
        event_end = _number(event.get("end"), float("inf"))
        cue_start = _number(row.get("start"), float("-inf"))
        if not event_start <= cue_start <= event_end:
            errors.append(f"motion event {event_id} SFX landing is outside the event window")
        volume = _number(row.get("volume"), -1.0)
        if not 0.0 < volume <= 0.4:
            errors.append(f"motion event {event_id} SFX volume is outside the speech-safe range")
        measured_level = row.get("post_gain_mean_dbfs")
        if measured_level is None:
            errors.append(f"motion event {event_id} SFX lacks a post-gain audibility measurement")
        else:
            level = _number(measured_level, -1000.0)
            if level < minimum_level:
                errors.append(f"motion event {event_id} SFX is inaudible at {level:.1f} dBFS")
            if level > maximum_level:
                errors.append(f"motion event {event_id} SFX is too loud at {level:.1f} dBFS")

    if perceptual_enabled:
        errors.extend(_perceptual_errors(
            sfx=sfx, decisions=decisions, events=events,
            config=perceptual_config, base_dir=base_dir,
        ))
    else:
        coverage = len(cue_rows) / max(len(events), 1)
        target = sfx_config.get("target_event_coverage", "adaptive")
        if isinstance(target, (int, float)) and coverage + 1e-9 < float(target):
            errors.append(
                f"motion SFX event coverage {coverage:.3f} is below target {float(target):.3f}"
            )
    if cue_rows:
        if not perceptual_enabled:
            unique_ratio = len({str(row.get("asset")) for row in cue_rows}) / len(cue_rows)
            minimum_unique = _number(sfx_config.get("minimum_unique_asset_ratio"), 0.5)
            if unique_ratio + 1e-9 < minimum_unique:
                errors.append(
                    f"motion SFX unique-asset ratio {unique_ratio:.3f} is below target "
                    f"{minimum_unique:.3f}"
                )
        families = [str(row.get("family") or "").strip() for row in cue_rows]
        if any(not family for family in families):
            errors.append("every motion SFX cue must declare a semantic family")
        elif len(families) > 1:
            family, count = Counter(families).most_common(1)[0]
            maximum_family_ratio = _number(sfx_config.get("maximum_family_ratio"), 0.5)
            family_ratio = count / len(families)
            if family_ratio > maximum_family_ratio + 1e-9:
                errors.append(
                    f"motion SFX family {family!r} dominates {count}/{len(families)} cues; "
                    f"maximum family ratio is {maximum_family_ratio:.3f}"
                )
        cooldown = _number(sfx_config.get("same_file_cooldown_seconds"), 20.0)
        ordered = sorted(cue_rows, key=lambda row: _number(row.get("start"), 0.0))
        last_start: dict[str, float] = {}
        for row in ordered:
            asset = str(row.get("asset", ""))
            start = _number(row.get("start"), 0.0)
            if asset in last_start and start - last_start[asset] < cooldown:
                errors.append(f"motion SFX asset repeats inside {cooldown:.1f}s cooldown: {asset}")
            last_start[asset] = start
        audibility = sfx.get("mix_audibility_check") or {}
        if audibility.get("status") != "pass":
            errors.append("motion SFX mixed-preview audibility check is not pass")
        evidence = _resolve(base_dir, audibility.get("evidence"))
        if not evidence or not evidence.is_file():
            errors.append("motion SFX mixed-preview audibility evidence is missing")

    bgm = plan.get("background_music") or {}
    bgm_config = project.get("audio", {}).get("bgm", {})
    mode = bgm.get("mode")
    configured_asset = _resolve(base_dir, bgm_config.get("asset"))
    enabled_by_default = bgm_config.get("enabled_by_default") is True
    if mode == "authorized_asset":
        if bgm.get("enabled") is not True:
            errors.append("authorized BGM asset is not enabled")
        source = _resolve(base_dir, bgm.get("source"))
        if not source or not source.is_file():
            errors.append(f"authorized BGM asset is missing: {bgm.get('source')}")
        preview_volume = _number(bgm.get("preview_volume"), -1.0)
        if not 0.08 <= preview_volume <= 0.12:
            errors.append("authorized BGM preview volume must stay within 0.08-0.12")
        ducking = bgm.get("ducking") or {}
        if ducking.get("enabled") is not True or ducking.get("method") != "sidechaincompress":
            errors.append("authorized BGM must use speech-driven sidechaincompress ducking")
        if ducking.get("status") != "pass":
            errors.append("authorized BGM ducking QA is not pass")
        provenance = bgm.get("provenance") or {}
        if not provenance.get("authorization") or not provenance.get("sha256"):
            errors.append("authorized BGM lacks authorization and SHA-256 provenance")
    elif mode == "embedded_source":
        presence = bgm.get("presence_analysis") or {}
        if presence.get("status") != "present":
            errors.append("embedded BGM was not confirmed by measured presence analysis")
    elif mode == "disabled":
        if enabled_by_default and configured_asset and configured_asset.is_file() \
                and bgm.get("explicitly_disabled") is not True:
            errors.append("authorized BGM is enabled by default but was silently disabled")
        if not bgm.get("reason"):
            errors.append("disabled BGM decision lacks a reason")
    elif mode == "unavailable":
        if bgm.get("enabled") is True:
            errors.append("unavailable BGM cannot be enabled")
        if not bgm.get("reason"):
            errors.append("unavailable BGM decision lacks a reason")
        attempts = bgm.get("attempts")
        if not isinstance(attempts, list):
            errors.append("unavailable BGM decision must record provider attempts")
    else:
        errors.append(
            "background music plan must declare authorized_asset, embedded_source, disabled, "
            "or unavailable mode"
        )
    return errors
