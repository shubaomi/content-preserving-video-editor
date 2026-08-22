#!/usr/bin/env python3
"""Canonical EDL/SRT/layer graph to Jianying draft-plan projection."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from caption_treatment import parse_srt
from director_contracts import read_json, sha256_file
from nle_handoff_v2 import validate_nle_handoff_package
from safe_generated_output import SafeGeneratedOutputError, safe_generated_target
from jianying_native_common import (
    ASSET_MODES, PROFILES, JianyingNativeDraftError, _COLOR, _DRAFT_IDENTIFIER,
    _FIDELITIES, _IDENTIFIER, _PAYLOAD_FIELDS, _ROLE_PAYLOAD, _TRACK_ROLES,
    _canonical_hash, _file_ref, _finite, _frame, _lexical_child, _ref_errors,
    _resolve_ref, _timebase, _transform_errors, _utf16_length,
    _write_json, preflight_nle_authorities,
)

def _validate_plan_header_and_authorities(
    payload: Mapping[str, Any], *, authorized_root: Path,
    errors: list[str],
) -> dict[str, Any]:
    required = {
        "schema_version", "kind", "draft_id", "profile", "asset_mode",
        "authorities", "timebase", "tracks", "plan_sha256",
    }
    if set(payload) != required or payload.get("schema_version") != 1 or payload.get(
        "kind"
    ) != "jianying_native_draft_plan":
        errors.append("draft plan identity or shape is invalid")
    if not isinstance(payload.get("draft_id"), str) or not _DRAFT_IDENTIFIER.fullmatch(
        payload.get("draft_id", "")
    ):
        errors.append("draft plan ID is invalid")
    if payload.get("profile") not in PROFILES or payload.get("asset_mode") not in ASSET_MODES:
        errors.append("draft plan profile or asset mode is invalid")
    try:
        expected_hash = _canonical_hash(payload, omit="plan_sha256")
    except JianyingNativeDraftError as error:
        errors.append(str(error))
    else:
        if payload.get("plan_sha256") != expected_hash:
            errors.append("draft plan integrity is stale")
    authorities = payload.get("authorities")
    if not isinstance(authorities, Mapping):
        errors.append("draft plan authorities are invalid")
        authorities = {}
    elif set(authorities) != {
        "edl", "layer_timeline", "master_srt", "automatic_master", "nle_package"
    }:
        errors.append("draft plan authority inventory is incomplete or extra")
    authority_paths: dict[str, Path] = {}
    for name, ref in authorities.items():
        ref_errors = _ref_errors(
            ref, label=f"draft authority {name}", authorized_root=authorized_root
        )
        errors.extend(ref_errors)
        if not ref_errors:
            resolved = _resolve_ref(ref)
            if resolved is not None:
                authority_paths[str(name)] = resolved
    timebase = payload.get("timebase")
    if not isinstance(timebase, Mapping) or set(timebase) != {
        "numerator", "denominator", "duration_frames"
    } or any(
        isinstance(timebase.get(key), bool)
        or not isinstance(timebase.get(key), int)
        or timebase.get(key) < 1
        for key in ("numerator", "denominator", "duration_frames")
    ):
        errors.append("draft plan timebase is invalid")
        timebase = {"duration_frames": 0}
    duration = int(timebase.get("duration_frames", 0))
    return {
        "authority_paths": authority_paths,
        "timebase": timebase,
        "duration": duration,
    }


def _validate_caption_payload(
    payload_row: Mapping[str, Any], *, clip_id: Any, start: Any,
    clip_duration: Any, authorized_root: Path, state: dict[str, Any],
    errors: list[str],
) -> None:
    cue_ids = state["cue_ids"]
    caption_inventory = state["caption_inventory"]
    cue_id, text = payload_row.get("cue_id"), payload_row.get("text")
    if not isinstance(cue_id, str) or not cue_id or cue_id in cue_ids:
        errors.append("draft caption cue ID is missing or duplicate")
    else:
        cue_ids.add(cue_id)
    if not isinstance(text, str) or not text:
        errors.append("draft caption text is missing")
    if not isinstance(payload_row.get("base_style"), Mapping):
        errors.append("draft caption base style is invalid")
    if payload_row.get("fidelity") not in {"full", "degraded", "unavailable"}:
        errors.append("draft caption payload fidelity is invalid")
    emphasis = payload_row.get("emphasis")
    if not isinstance(emphasis, list):
        errors.append("draft caption emphasis inventory is invalid")
    else:
        previous_end = 0
        text_length = _utf16_length(text) if isinstance(text, str) else 0
        for row in emphasis:
            if not isinstance(row, Mapping) or set(row) != {
                "start_utf16", "end_utf16", "bold", "scale", "color"
            }:
                errors.append("draft caption emphasis span is invalid")
                continue
            start_utf16, end_utf16 = row.get("start_utf16"), row.get("end_utf16")
            if (
                isinstance(start_utf16, bool) or not isinstance(start_utf16, int)
                or isinstance(end_utf16, bool) or not isinstance(end_utf16, int)
                or start_utf16 < previous_end or end_utf16 <= start_utf16
                or end_utf16 > text_length
                or not isinstance(row.get("bold"), bool)
                or not _finite(row.get("scale"), minimum=0.000001)
                or not isinstance(row.get("color"), str)
                or not _COLOR.fullmatch(row["color"])
            ):
                errors.append("draft caption emphasis span is invalid")
            else:
                previous_end = end_utf16
    ass_reference = payload_row.get("ass_reference")
    if ass_reference is not None:
        errors.extend(_ref_errors(
            ass_reference, label=f"draft caption {clip_id} ASS reference",
            authorized_root=authorized_root,
        ))
    if isinstance(start, int) and isinstance(clip_duration, int):
        caption_inventory.append((str(text), start, start + clip_duration))


def _validate_role_payload(
    clip: Mapping[str, Any], payload_row: Mapping[str, Any], *,
    expected_type: str | None, role: Any, clip_id: Any, start: Any,
    clip_duration: Any, authorized_root: Path, state: dict[str, Any],
    errors: list[str],
) -> None:
    base_inventory = state["base_inventory"]
    event_bindings = state["event_bindings"]
    if role == "base" and isinstance(start, int) and isinstance(clip_duration, int):
        base_inventory.append((start, start + clip_duration))
    if expected_type == "audio":
        gain = payload_row.get("gain_db")
        if (
            payload_row.get("sample_rate_hz") != 48000
            or not _finite(gain) or not -96 <= float(gain) <= 24
        ):
            errors.append(f"draft audio clip {clip_id} metadata is invalid")
        channels = payload_row.get("channels")
        if isinstance(channels, bool) or not isinstance(channels, int) or not 1 <= channels <= 8:
            errors.append(f"draft audio clip {clip_id} channel count is invalid")
    if expected_type in {"video", "ip"}:
        errors.extend(_transform_errors(
            payload_row.get("transform"), label=f"draft visual clip {clip_id}"
        ))
    if expected_type == "video" and (
        payload_row.get("alpha_mode") not in {"none", "straight", "premultiplied"}
        or payload_row.get("motion_editability")
        not in {"native_clip", "baked", "unavailable"}
    ):
        errors.append(f"draft video clip {clip_id} payload enum is invalid")
    if expected_type == "ip":
        if (
            not isinstance(payload_row.get("asset_role"), str)
            or not payload_row["asset_role"]
            or not isinstance(payload_row.get("protection_window_ids"), list)
            or any(not isinstance(value, str) or not value
                   for value in payload_row.get("protection_window_ids", []))
        ):
            errors.append(f"draft IP clip {clip_id} metadata is invalid")
        errors.extend(_ref_errors(
            payload_row.get("rights_receipt"),
            label=f"draft IP clip {clip_id} rights receipt",
            authorized_root=authorized_root,
        ))
    if expected_type == "outro":
        transform = payload_row.get("transform")
        if payload_row.get("outro_role") not in {
            "background", "overlay", "icon", "cta_copy", "sfx", "baked_reference"
        } or not isinstance(payload_row.get("native_text"), (str, type(None))):
            errors.append(f"draft outro clip {clip_id} metadata is invalid")
        if transform is not None:
            errors.extend(_transform_errors(
                transform, label=f"draft outro clip {clip_id}"
            ))
    if expected_type == "reference" and (
        payload_row.get("enabled") is not False
        or payload_row.get("locked") is not True
    ):
        errors.append("draft reference track must remain disabled and locked")
    if role in {"motion", "sfx"} and any(
        not isinstance(clip.get(key), str) or not clip[key]
        for key in ("semantic_event_id", "render_event_id")
    ):
        errors.append(f"draft event clip {clip_id} lacks semantic/render binding")
    elif role in {"motion", "sfx"}:
        semantic_id = str(clip["semantic_event_id"])
        render_id = str(clip["render_event_id"])
        # Paired picture and sound intentionally share one event binding.
        # Only duplicate identity within the same role is invalid.
        binding = (str(role), semantic_id, render_id)
        if binding in event_bindings:
            errors.append("draft event semantic/render ID is duplicate")
        event_bindings.add(binding)
    if expected_type == "caption":
        _validate_caption_payload(
            payload_row, clip_id=clip_id, start=start,
            clip_duration=clip_duration, authorized_root=authorized_root,
            state=state, errors=errors,
        )


def _validate_clip_contract(
    clip: Mapping[str, Any], *, track_kind: Any, duration: int,
    authorized_root: Path, state: dict[str, Any], errors: list[str],
) -> None:
    clip_ids = state["clip_ids"]
    if set(clip) != {
        "clip_id", "role", "semantic_event_id", "render_event_id",
        "start_frame", "duration_frames", "source", "editable", "fidelity",
        "payload",
    }:
        errors.append("draft clip shape is invalid")
    clip_id = clip.get("clip_id")
    if (
        not isinstance(clip_id, str) or not _IDENTIFIER.fullmatch(clip_id)
        or clip_id in clip_ids
    ):
        errors.append("draft clip ID is missing or duplicate")
    else:
        clip_ids.add(clip_id)
    start, clip_duration = clip.get("start_frame"), clip.get("duration_frames")
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        errors.append(f"draft clip {clip_id} start_frame is invalid")
    if (
        isinstance(clip_duration, bool)
        or not isinstance(clip_duration, int)
        or clip_duration < 1
    ):
        errors.append(f"draft clip {clip_id} duration_frames is invalid")
    elif isinstance(start, int) and start + clip_duration > duration:
        errors.append(f"draft clip {clip_id} exceeds canonical duration")
    errors.extend(_ref_errors(
        clip.get("source"), label=f"draft clip {clip_id} source",
        authorized_root=authorized_root,
    ))
    role, payload_row = clip.get("role"), clip.get("payload")
    for event_key in ("semantic_event_id", "render_event_id"):
        event_value = clip.get(event_key)
        if event_value is not None and (
            not isinstance(event_value, str)
            or not _IDENTIFIER.fullmatch(event_value)
        ):
            errors.append(f"draft clip {clip_id} {event_key} is invalid")
    if not isinstance(clip.get("editable"), bool):
        errors.append(f"draft clip {clip_id} editable must be boolean")
    if clip.get("fidelity") not in _FIDELITIES:
        errors.append(f"draft clip {clip_id} fidelity is invalid")
    if track_kind in _TRACK_ROLES and role not in _TRACK_ROLES[track_kind]:
        errors.append(f"draft clip {clip_id} role does not match track kind")
    expected_type = _ROLE_PAYLOAD.get(str(role))
    if not isinstance(payload_row, Mapping) or payload_row.get("type") != expected_type:
        errors.append(f"draft clip {clip_id} payload type does not match role")
        return
    if set(payload_row) != _PAYLOAD_FIELDS.get(str(expected_type), set()):
        errors.append(f"draft clip {clip_id} payload shape is invalid")
    _validate_role_payload(
        clip, payload_row, expected_type=expected_type, role=role,
        clip_id=clip_id, start=start, clip_duration=clip_duration,
        authorized_root=authorized_root, state=state, errors=errors,
    )


def _validate_track_inventory(
    payload: Mapping[str, Any], *, authorized_root: Path,
    duration: int, errors: list[str],
) -> dict[str, Any]:
    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("draft plan requires tracks")
        return {"valid": False}
    state: dict[str, Any] = {
        "track_ids": set(),
        "orders": set(),
        "clip_ids": set(),
        "cue_ids": set(),
        "event_bindings": set(),
        "caption_inventory": [],
        "base_inventory": [],
    }
    track_ids = state["track_ids"]
    orders = state["orders"]
    for track in tracks:
        if not isinstance(track, Mapping):
            errors.append("draft track must be an object")
            continue
        if set(track) != {"track_id", "order", "kind", "clips"}:
            errors.append("draft track shape is invalid")
        track_id, order = track.get("track_id"), track.get("order")
        track_kind = track.get("kind")
        if track_kind not in _TRACK_ROLES:
            errors.append("draft track kind is invalid")
        if (
            not isinstance(track_id, str) or not _IDENTIFIER.fullmatch(track_id)
            or track_id in track_ids
        ):
            errors.append("draft track ID is missing or duplicate")
        else:
            track_ids.add(track_id)
        if isinstance(order, bool) or not isinstance(order, int) or order < 0 or order in orders:
            errors.append("draft track order is invalid or duplicate")
        else:
            orders.add(order)
        clips = track.get("clips")
        if not isinstance(clips, list):
            errors.append("draft track clips must be a list")
            continue
        for clip in clips:
            if not isinstance(clip, Mapping):
                errors.append("draft clip must be an object")
                continue
            _validate_clip_contract(
                clip, track_kind=track_kind, duration=duration,
                authorized_root=authorized_root, state=state, errors=errors,
            )
    if "video.base" not in track_ids or "text.captions" not in track_ids:
        errors.append("draft plan is missing required base or caption track")
    return {
        "valid": True,
        "track_ids": track_ids,
        "caption_inventory": state["caption_inventory"],
        "base_inventory": state["base_inventory"],
    }



def _validate_authoritative_roundtrips(
    payload: Mapping[str, Any], *, authority_paths: Mapping[str, Path],
    timebase: Mapping[str, Any], duration: int,
    caption_inventory: list[tuple[str, int, int]],
    base_inventory: list[tuple[int, int]], errors: list[str],
) -> None:
    master_srt = authority_paths.get("master_srt")
    if master_srt and master_srt.is_file() and isinstance(timebase, Mapping):
        try:
            expected_captions = [
                (
                    str(cue["text"]),
                    _frame(cue["start"], numerator=int(timebase["numerator"]), denominator=int(timebase["denominator"])),
                    _frame(cue["end"], numerator=int(timebase["numerator"]), denominator=int(timebase["denominator"])),
                )
                for cue in parse_srt(master_srt)
            ]
            if caption_inventory != expected_captions:
                errors.append("draft caption inventory differs from authoritative SRT")
        except (KeyError, TypeError, ValueError, JianyingNativeDraftError):
            errors.append("authoritative SRT caption inventory is unreadable")
    if payload.get("profile") == "layered_reconstruction":
        edl_path = authority_paths.get("edl")
        if edl_path and edl_path.is_file() and isinstance(timebase, Mapping):
            try:
                ranges = read_json(edl_path).get("ranges", [])
                if not isinstance(ranges, list) or not ranges:
                    raise JianyingNativeDraftError("authoritative EDL ranges are missing")
                expected_base: list[tuple[int, int]] = []
                cursor_seconds = 0.0
                for row in ranges:
                    if not isinstance(row, Mapping):
                        raise JianyingNativeDraftError("EDL range is malformed")
                    source_start, source_end = row.get("start"), row.get("end")
                    timeline_start = row.get("timeline_start", cursor_seconds)
                    if (
                        not _finite(source_start, minimum=0)
                        or not _finite(source_end, minimum=0)
                        or not _finite(timeline_start, minimum=0)
                        or float(source_end) <= float(source_start)
                    ):
                        raise JianyingNativeDraftError("EDL range timing is invalid")
                    output_start = _frame(
                        timeline_start,
                        numerator=int(timebase["numerator"]),
                        denominator=int(timebase["denominator"]),
                    )
                    output_end = _frame(
                        float(timeline_start) + float(source_end) - float(source_start),
                        numerator=int(timebase["numerator"]),
                        denominator=int(timebase["denominator"]),
                    )
                    expected_base.append((output_start, output_end))
                    cursor_seconds = max(
                        cursor_seconds,
                        float(timeline_start) + float(source_end) - float(source_start),
                    )
                if base_inventory != expected_base:
                    errors.append("layered draft base inventory differs from EDL output ranges")
            except (KeyError, TypeError, ValueError, JianyingNativeDraftError):
                errors.append("authoritative EDL base inventory is unreadable")
    elif payload.get("profile") == "repair_draft" and base_inventory != [(0, duration)]:
        errors.append("repair draft must contain exactly one full-duration base clip")


def validate_draft_plan(payload: Any, *, authorized_root: Path) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["draft plan must be an object"]
    errors: list[str] = []
    header = _validate_plan_header_and_authorities(
        payload, authorized_root=authorized_root, errors=errors,
    )
    inventory = _validate_track_inventory(
        payload, authorized_root=authorized_root,
        duration=header["duration"], errors=errors,
    )
    if not inventory["valid"]:
        return errors
    _validate_authoritative_roundtrips(
        payload,
        authority_paths=header["authority_paths"],
        timebase=header["timebase"],
        duration=header["duration"],
        caption_inventory=inventory["caption_inventory"],
        base_inventory=inventory["base_inventory"],
        errors=errors,
    )
    return errors
