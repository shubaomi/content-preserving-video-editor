#!/usr/bin/env python3
"""Blocking audio-plan QA for event SFX coverage, audibility, and BGM provenance."""
from __future__ import annotations

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
        if not asset or not asset.is_file():
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

    coverage = len(cue_rows) / max(len(events), 1)
    target = sfx_config.get("target_event_coverage", "adaptive")
    if isinstance(target, (int, float)) and coverage + 1e-9 < float(target):
        errors.append(f"motion SFX event coverage {coverage:.3f} is below target {float(target):.3f}")
    if cue_rows:
        unique_ratio = len({str(row.get("asset")) for row in cue_rows}) / len(cue_rows)
        minimum_unique = _number(sfx_config.get("minimum_unique_asset_ratio"), 0.5)
        if unique_ratio + 1e-9 < minimum_unique:
            errors.append(
                f"motion SFX unique-asset ratio {unique_ratio:.3f} is below target {minimum_unique:.3f}"
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
    else:
        errors.append("background music plan must declare authorized_asset, embedded_source, or disabled mode")
    return errors
