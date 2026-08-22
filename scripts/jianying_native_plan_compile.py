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

from jianying_native_plan_validate import validate_draft_plan

def _asset_path(row: Mapping[str, Any], package_root: Path) -> Path:
    value = row.get("path")
    if not isinstance(value, str):
        raise JianyingNativeDraftError("available NLE asset has no path")
    path = Path(value)
    if not path.is_absolute():
        path = package_root / path
    path = _lexical_child(path, package_root, label="NLE package asset")
    if not path.is_file() or row.get("sha256") != sha256_file(path):
        raise JianyingNativeDraftError("available NLE asset is missing or stale")
    return path

def _neutral_transform() -> dict[str, float]:
    return {
        "x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0,
        "rotation_degrees": 0.0, "opacity": 1.0,
    }

def _clip(
    *, clip_id: str, role: str, start: int, duration: int, source: Path,
    payload: Mapping[str, Any], editable: bool, fidelity: str,
    semantic_event_id: str | None = None, render_event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "clip_id": clip_id,
        "role": role,
        "semantic_event_id": semantic_event_id,
        "render_event_id": render_event_id,
        "start_frame": start,
        "duration_frames": duration,
        "source": _file_ref(source),
        "editable": editable,
        "fidelity": fidelity,
        "payload": dict(payload),
    }

def _track(track_id: str, order: int, kind: str, clips: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {"track_id": track_id, "order": order, "kind": kind, "clips": list(clips)}

def _preflight_plan_inputs(
    *, nle_package_receipt: Path, output_path: Path, authorized_root: Path,
    draft_id: str, profile: str, asset_mode: str,
) -> dict[str, Any]:
    if profile not in PROFILES:
        raise JianyingNativeDraftError("Jianying draft profile is invalid")
    if asset_mode not in ASSET_MODES:
        raise JianyingNativeDraftError("Jianying draft asset mode is invalid")
    if not isinstance(draft_id, str) or not draft_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in draft_id
    ):
        raise JianyingNativeDraftError("Jianying draft ID is invalid")
    authorized_root = Path(os.path.abspath(authorized_root))
    output_path = _lexical_child(output_path, authorized_root, label="draft plan output")
    receipt_path = _lexical_child(
        nle_package_receipt, authorized_root, label="NLE package receipt"
    )
    try:
        preflight_receipt = read_json(receipt_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise JianyingNativeDraftError("NLE package receipt is unreadable") from error
    if authority_errors := preflight_nle_authorities(
        preflight_receipt, authorized_root=authorized_root
    ):
        raise JianyingNativeDraftError("\n".join(authority_errors))
    if errors := validate_nle_handoff_package(receipt_path):
        raise JianyingNativeDraftError(
            "current NLE package is invalid:\n- " + "\n- ".join(errors)
        )
    receipt = read_json(receipt_path)
    package_root = receipt_path.parent.parent
    timeline_path = _resolve_ref(receipt.get("timeline"), base=package_root)
    if timeline_path is None or not timeline_path.is_file():
        raise JianyingNativeDraftError("NLE layer timeline is missing")
    timeline_path = _lexical_child(
        timeline_path, package_root, label="NLE layer timeline"
    )
    timeline = read_json(timeline_path)
    timebase = _timebase(timeline.get("frame_rate"), timeline.get("duration_seconds"))
    numerator, denominator = timebase["numerator"], timebase["denominator"]
    assets = [
        row for row in receipt.get("assets", [])
        if isinstance(row, Mapping) and row.get("status") == "available"
    ]
    by_role: dict[str, list[Mapping[str, Any]]] = {}
    for row in assets:
        by_role.setdefault(str(row.get("role")), []).append(row)
    for role in ("motion_full_duration", "sfx_grouped"):
        if by_role.get(role):
            raise JianyingNativeDraftError(
                f"available {role} has no lossless v1 native-track projection"
            )
    caption_rows = by_role.get("caption_srt", [])
    if len(caption_rows) != 1:
        raise JianyingNativeDraftError("draft plan requires exactly one current master.srt")
    caption_path = _asset_path(caption_rows[0], package_root)
    edl_path = _resolve_ref(receipt.get("authorities", {}).get("edl"), base=package_root)
    automatic_path = _resolve_ref(
        receipt.get("authorities", {}).get("automatic_master"), base=package_root
    )
    if edl_path is None or automatic_path is None:
        raise JianyingNativeDraftError("NLE authority paths are invalid")
    edl_path = _lexical_child(edl_path, authorized_root, label="NLE EDL authority")
    automatic_path = _lexical_child(
        automatic_path, authorized_root, label="NLE automatic master authority"
    )
    edl = read_json(edl_path)
    return {
        "authorized_root": authorized_root,
        "output_path": output_path,
        "receipt_path": receipt_path,
        "package_root": package_root,
        "timeline_path": timeline_path,
        "caption_path": caption_path,
        "edl_path": edl_path,
        "automatic_path": automatic_path,
        "timebase": timebase,
        "by_role": by_role,
        "edl": edl,
    }


def _compile_base_track(
    context: Mapping[str, Any], *, profile: str,
    repair_candidate: Path | None, tracks: list[dict[str, Any]],
) -> None:
    by_role = context["by_role"]
    edl = context["edl"]
    package_root = context["package_root"]
    authorized_root = context["authorized_root"]
    timebase = context["timebase"]
    numerator, denominator = timebase["numerator"], timebase["denominator"]
    if profile == "layered_reconstruction":
        clean_rows = by_role.get("clean_a_roll", [])
        if len(clean_rows) != 1:
            raise JianyingNativeDraftError(
                "layered reconstruction requires exactly one current clean A-roll"
            )
        base_path = _asset_path(clean_rows[0], package_root)
        if not isinstance(edl.get("ranges"), list) or not edl["ranges"]:
            raise JianyingNativeDraftError("EDL ranges are missing")
        base_clips = []
        cursor_seconds = 0.0
        for index, row in enumerate(edl["ranges"]):
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
                timeline_start, numerator=numerator, denominator=denominator
            )
            output_end = _frame(
                float(timeline_start) + float(source_end) - float(source_start),
                numerator=numerator, denominator=denominator,
            )
            range_id = str(row.get("id") or f"range-{index + 1}")
            if not _IDENTIFIER.fullmatch(range_id):
                raise JianyingNativeDraftError("EDL range ID is invalid")
            base_clips.append(_clip(
                clip_id=f"base.{range_id}", role="base", start=output_start,
                duration=output_end - output_start, source=base_path,
                payload={
                    "type": "video", "alpha_mode": "none",
                    "transform": _neutral_transform(),
                    "motion_editability": "native_clip",
                }, editable=True, fidelity="full",
            ))
            cursor_seconds = max(
                cursor_seconds,
                float(timeline_start) + float(source_end) - float(source_start),
            )
    else:
        if repair_candidate is None:
            raise JianyingNativeDraftError(
                "repair_draft requires the actual pre-caption full candidate"
            )
        base_path = _lexical_child(
            repair_candidate, authorized_root, label="repair draft candidate"
        )
        if not base_path.is_file():
            raise JianyingNativeDraftError("repair draft candidate is missing")
        base_clips = [_clip(
            clip_id="base.repair-candidate", role="base", start=0,
            duration=timebase["duration_frames"], source=base_path,
            payload={
                "type": "video", "alpha_mode": "none",
                "transform": _neutral_transform(), "motion_editability": "baked",
            }, editable=False, fidelity="baked",
        )]
    tracks.append(_track("video.base", 0, "video", base_clips))


def _compile_motion_tracks(
    context: Mapping[str, Any], *, profile: str, tracks: list[dict[str, Any]],
) -> None:
    by_role = context["by_role"]
    package_root = context["package_root"]
    timebase = context["timebase"]
    numerator, denominator = timebase["numerator"], timebase["denominator"]
    for row in (
        by_role.get("motion_event", []) if profile == "layered_reconstruction" else []
    ):
        placement = row.get("timeline")
        if not isinstance(placement, Mapping):
            raise JianyingNativeDraftError("motion event lacks exact timeline placement")
        start = _frame(placement.get("start_seconds"), numerator=numerator, denominator=denominator)
        end = _frame(placement.get("end_seconds"), numerator=numerator, denominator=denominator)
        render_id = str(row.get("render_event_id") or row.get("asset_id"))
        video = row.get("video") if isinstance(row.get("video"), Mapping) else {}
        declared_alpha = video.get("alpha_mode")
        alpha_mode = (
            declared_alpha
            if video.get("alpha_status") == "verified"
            and declared_alpha in {"straight", "premultiplied"}
            else "none"
        )
        tracks.append(_track(
            f"video.motion.{render_id}", 10 + len(tracks), "video", [_clip(
                clip_id=f"motion.{render_id}", role="motion", start=start,
                duration=end - start, source=_asset_path(row, package_root),
                payload={
                    "type": "video", "alpha_mode": alpha_mode,
                    "transform": _neutral_transform(), "motion_editability": "native_clip",
                }, editable=True, fidelity="full" if alpha_mode != "none" else "degraded",
                semantic_event_id=str(row.get("semantic_event_id") or ""),
                render_event_id=render_id,
            )]
        ))


def _compile_ip_tracks(
    context: Mapping[str, Any], *, profile: str, tracks: list[dict[str, Any]],
) -> None:
    by_role = context["by_role"]
    package_root = context["package_root"]
    timebase = context["timebase"]
    numerator, denominator = timebase["numerator"], timebase["denominator"]
    ip_rows = (
        (by_role.get("ip_rendered", []) or by_role.get("ip_source", []))
        if profile == "layered_reconstruction" else []
    )
    for index, row in enumerate(ip_rows):
        placement = row.get("timeline")
        if not isinstance(placement, Mapping):
            raise JianyingNativeDraftError("available IP asset lacks exact timeline placement")
        rights_path = _resolve_ref(row.get("rights_evidence"), base=package_root)
        if rights_path is None or not rights_path.is_file():
            raise JianyingNativeDraftError("available IP asset lacks current rights evidence")
        rights_path = _lexical_child(
            rights_path, package_root, label="NLE IP rights evidence"
        )
        start = _frame(
            placement.get("start_seconds"), numerator=numerator, denominator=denominator
        )
        end = _frame(
            placement.get("end_seconds"), numerator=numerator, denominator=denominator
        )
        asset_id = str(row.get("asset_id") or index)
        tracks.append(_track(f"video.ip.{asset_id}", 100 + index, "video", [_clip(
            clip_id=f"ip.{asset_id}", role="ip", start=start, duration=end - start,
            source=_asset_path(row, package_root),
            payload={
                "type": "ip", "asset_role": str(row.get("role")),
                "transform": _neutral_transform(),
                "rights_receipt": _file_ref(rights_path),
                "protection_window_ids": [
                    str(value) for value in (row.get("protection_window_ids") or [])
                    if isinstance(value, str) and value
                ],
            },
            editable=True, fidelity="full",
            semantic_event_id=(
                str(row["semantic_event_id"]) if row.get("semantic_event_id") else None
            ),
        )]))


def _compile_outro_visual_tracks(
    context: Mapping[str, Any], *, profile: str, tracks: list[dict[str, Any]],
) -> None:
    by_role = context["by_role"]
    package_root = context["package_root"]
    timebase = context["timebase"]
    numerator, denominator = timebase["numerator"], timebase["denominator"]
    outro_roles = (
        ("outro_background", "background"),
        ("outro_overlay", "overlay"),
        ("outro_icon", "icon"),
    )
    outro_index = 0
    for source_role, outro_role in outro_roles:
        for row in (
            by_role.get(source_role, []) if profile == "layered_reconstruction" else []
        ):
            placement = row.get("timeline")
            if not isinstance(placement, Mapping):
                raise JianyingNativeDraftError(
                    f"available {source_role} lacks exact timeline placement"
                )
            start = _frame(
                placement.get("start_seconds"), numerator=numerator, denominator=denominator
            )
            end = _frame(
                placement.get("end_seconds"), numerator=numerator, denominator=denominator
            )
            asset_id = str(row.get("asset_id") or outro_index)
            tracks.append(_track(
                f"video.outro.{outro_role}.{asset_id}", 150 + outro_index, "video",
                [_clip(
                    clip_id=f"outro.{outro_role}.{asset_id}", role="outro",
                    start=start, duration=end - start,
                    source=_asset_path(row, package_root),
                    payload={
                        "type": "outro", "outro_role": outro_role,
                        "native_text": None, "transform": _neutral_transform(),
                    }, editable=True, fidelity="full",
                )],
            ))
            outro_index += 1


def _compile_visual_tracks(
    context: Mapping[str, Any], *, profile: str, tracks: list[dict[str, Any]],
) -> None:
    _compile_motion_tracks(context, profile=profile, tracks=tracks)
    _compile_ip_tracks(context, profile=profile, tracks=tracks)
    _compile_outro_visual_tracks(context, profile=profile, tracks=tracks)



def _compile_caption_track(
    context: Mapping[str, Any], *, tracks: list[dict[str, Any]],
) -> None:
    by_role = context["by_role"]
    package_root = context["package_root"]
    caption_path = context["caption_path"]
    timebase = context["timebase"]
    numerator, denominator = timebase["numerator"], timebase["denominator"]
    authoritative_captions = parse_srt(caption_path)
    ass_rows = by_role.get("caption_ass_reference", [])
    style_rows = by_role.get("caption_style_plan", [])
    if len(ass_rows) > 1 or len(style_rows) > 1 or bool(ass_rows) != bool(style_rows):
        raise JianyingNativeDraftError(
            "caption ASS reference and style plan must be one matched pair"
        )
    ass_path = _asset_path(ass_rows[0], package_root) if ass_rows else None
    style_path = _asset_path(style_rows[0], package_root) if style_rows else None
    style_plan: Mapping[str, Any] = {}
    style_captions: list[Any] = []
    if style_path is not None:
        try:
            loaded_style = read_json(style_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise JianyingNativeDraftError("caption style plan is unreadable") from error
        if not isinstance(loaded_style, Mapping):
            raise JianyingNativeDraftError("caption style plan must be an object")
        style_plan = loaded_style
        candidates = style_plan.get("captions")
        if not isinstance(candidates, list) or len(candidates) != len(authoritative_captions):
            raise JianyingNativeDraftError("caption style plan inventory differs from SRT")
        style_captions = candidates

    caption_clips: list[dict[str, Any]] = []
    for index, cue in enumerate(authoritative_captions, start=1):
        start = _frame(cue["start"], numerator=numerator, denominator=denominator)
        end = _frame(cue["end"], numerator=numerator, denominator=denominator)
        emphasis: list[dict[str, Any]] = []
        base_style: dict[str, Any] = {}
        if style_path is not None and ass_path is not None:
            styled = style_captions[index - 1]
            if (
                not isinstance(styled, Mapping)
                or styled.get("text") != cue["text"]
                or abs(float(styled.get("start", -1)) - float(cue["start"])) > 0.0005
                or abs(float(styled.get("end", -1)) - float(cue["end"])) > 0.0005
            ):
                raise JianyingNativeDraftError("caption style plan differs from SRT")
            treatment = style_plan.get("treatment")
            if isinstance(treatment, Mapping):
                base_style = {
                    **dict(treatment),
                    "style_plan": _file_ref(style_path),
                }
            for span in styled.get("emphasis") or []:
                if not isinstance(span, Mapping):
                    raise JianyingNativeDraftError("caption emphasis span is invalid")
                start_char, end_char = span.get("start_char"), span.get("end_char")
                if (
                    isinstance(start_char, bool) or not isinstance(start_char, int)
                    or isinstance(end_char, bool) or not isinstance(end_char, int)
                    or start_char < 0 or end_char <= start_char
                    or end_char > len(cue["text"])
                    or span.get("text") != cue["text"][start_char:end_char]
                ):
                    raise JianyingNativeDraftError("caption emphasis span differs from text")
                emphasis.append({
                    "start_utf16": _utf16_length(cue["text"][:start_char]),
                    "end_utf16": _utf16_length(cue["text"][:end_char]),
                    "bold": True,
                    "scale": float(span.get("scale_percent", 100)) / 100.0,
                    "color": str(span.get("color") or ""),
                })
        caption_clips.append(_clip(
            clip_id=f"caption.{index:05d}", role="caption", start=start,
            duration=end - start, source=caption_path,
            payload={
                "type": "caption", "cue_id": str(cue.get("id") or index),
                "text": cue["text"], "base_style": base_style, "emphasis": emphasis,
                "fidelity": "degraded",
                "ass_reference": _file_ref(ass_path) if ass_path is not None else None,
            }, editable=True, fidelity="degraded",
        ))
    tracks.append(_track("text.captions", 200, "text", caption_clips))


def _compile_audio_and_outro_tracks(
    context: Mapping[str, Any], *, profile: str, tracks: list[dict[str, Any]],
) -> None:
    by_role = context["by_role"]
    package_root = context["package_root"]
    timebase = context["timebase"]
    numerator, denominator = timebase["numerator"], timebase["denominator"]
    for index, row in enumerate(
        by_role.get("outro_copy", []) if profile == "layered_reconstruction" else []
    ):
        source = _asset_path(row, package_root)
        try:
            copy_contract = read_json(source)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise JianyingNativeDraftError("outro copy contract is unreadable") from error
        copy = copy_contract.get("copy") if isinstance(copy_contract, Mapping) else None
        if not isinstance(copy, Mapping):
            raise JianyingNativeDraftError("outro copy contract has no native text payload")
        values = [copy.get("headline"), *(copy.get("actions") or []), copy.get("supporting")]
        native_text = "\n".join(
            value.strip() for value in values if isinstance(value, str) and value.strip()
        )
        if not native_text:
            raise JianyingNativeDraftError("outro copy contract text is empty")
        placement = row.get("timeline")
        if isinstance(placement, Mapping):
            start = _frame(
                placement.get("start_seconds"), numerator=numerator, denominator=denominator
            )
            end = _frame(
                placement.get("end_seconds"), numerator=numerator, denominator=denominator
            )
        else:
            timing = copy_contract.get("timing") or {}
            copy_duration = timing.get("duration_seconds")
            if not _finite(copy_duration, minimum=0.000001):
                raise JianyingNativeDraftError(
                    "outro copy requires exact timeline placement or duration"
                )
            end = timebase["duration_frames"]
            start = max(0, end - _frame(
                copy_duration, numerator=numerator, denominator=denominator
            ))
        tracks.append(_track(f"text.outro.{index}", 210 + index, "text", [_clip(
            clip_id=f"outro.cta-copy.{index}", role="outro", start=start,
            duration=end - start, source=source,
            payload={
                "type": "outro", "outro_role": "cta_copy",
                "native_text": native_text, "transform": _neutral_transform(),
            }, editable=True, fidelity="full",
        )]))

    if profile == "layered_reconstruction" and by_role.get("dialogue_stem"):
        raise JianyingNativeDraftError(
            "dialogue stem requires an explicit silent-base audio policy before projection"
        )
    for role, order in (("dialogue_stem", 300), ("bgm_stem", 310)):
        for row in (
            by_role.get(role, []) if profile == "layered_reconstruction" else []
        ):
            audio = row.get("audio")
            if not isinstance(audio, Mapping) or not _finite(audio.get("gain_db")):
                raise JianyingNativeDraftError(f"{role} requires current gain_db metadata")
            clip_role = "dialogue" if role == "dialogue_stem" else "bgm"
            tracks.append(_track(f"audio.{clip_role}", order, "audio", [_clip(
                clip_id=f"audio.{clip_role}", role=clip_role, start=0,
                duration=timebase["duration_frames"], source=_asset_path(row, package_root),
                payload={
                    "type": "audio", "sample_rate_hz": 48000,
                    "channels": int(audio.get("channels", 2)),
                    "gain_db": float(audio["gain_db"]),
                }, editable=True, fidelity="full",
            )]))

    for row in (
        by_role.get("sfx_event", []) if profile == "layered_reconstruction" else []
    ):
        placement, audio = row.get("timeline"), row.get("audio")
        if not isinstance(placement, Mapping) or not isinstance(audio, Mapping):
            raise JianyingNativeDraftError("event SFX requires timeline and audio metadata")
        if not _finite(audio.get("gain_db")):
            raise JianyingNativeDraftError("event SFX requires current gain_db metadata")
        start = _frame(placement.get("start_seconds"), numerator=numerator, denominator=denominator)
        end = _frame(placement.get("end_seconds"), numerator=numerator, denominator=denominator)
        render_id = str(row.get("render_event_id") or row.get("asset_id"))
        tracks.append(_track(f"audio.sfx.{render_id}", 320 + len(tracks), "audio", [_clip(
            clip_id=f"sfx.{render_id}", role="sfx", start=start, duration=end - start,
            source=_asset_path(row, package_root),
            payload={
                "type": "audio", "sample_rate_hz": 48000,
                "channels": int(audio.get("channels", 2)),
                "gain_db": float(audio["gain_db"]),
            }, editable=True, fidelity="full",
            semantic_event_id=str(row.get("semantic_event_id") or ""),
            render_event_id=render_id,
        )]))


def _finalize_plan(
    context: Mapping[str, Any], *, draft_id: str, profile: str,
    asset_mode: str, tracks: list[dict[str, Any]],
) -> dict[str, Any]:
    authorized_root = context["authorized_root"]
    output_path = context["output_path"]
    receipt_path = context["receipt_path"]
    timeline_path = context["timeline_path"]
    caption_path = context["caption_path"]
    edl_path = context["edl_path"]
    automatic_path = context["automatic_path"]
    timebase = context["timebase"]
    tracks.append(_track("reference.master", 900, "reference", [_clip(
        clip_id="reference.automatic-master", role="reference", start=0,
        duration=timebase["duration_frames"], source=automatic_path,
        payload={"type": "reference", "enabled": False, "locked": True},
        editable=False, fidelity="full",
    )]))
    tracks.sort(key=lambda row: (row["order"], row["track_id"]))
    plan = {
        "schema_version": 1,
        "kind": "jianying_native_draft_plan",
        "draft_id": draft_id,
        "profile": profile,
        "asset_mode": asset_mode,
        "authorities": {
            "edl": _file_ref(edl_path),
            "layer_timeline": _file_ref(timeline_path),
            "master_srt": _file_ref(caption_path),
            "automatic_master": _file_ref(automatic_path),
            "nle_package": _file_ref(receipt_path),
        },
        "timebase": timebase,
        "tracks": tracks,
    }
    plan["plan_sha256"] = _canonical_hash(plan, omit="plan_sha256")
    if errors := validate_draft_plan(plan, authorized_root=authorized_root):
        raise JianyingNativeDraftError("draft plan is invalid:\n- " + "\n- ".join(errors))
    try:
        safe_target = safe_generated_target(
            authorized_root, output_path.relative_to(authorized_root)
        )
    except (ValueError, SafeGeneratedOutputError) as error:
        raise JianyingNativeDraftError(str(error)) from error
    _write_json(safe_target, plan)
    return plan


def compile_draft_plan(
    *, nle_package_receipt: Path, output_path: Path, authorized_root: Path,
    draft_id: str, profile: str, asset_mode: str,
    repair_candidate: Path | None = None,
) -> dict[str, Any]:
    """Compile current editor-neutral authorities into a deterministic plan."""
    context = _preflight_plan_inputs(
        nle_package_receipt=nle_package_receipt,
        output_path=output_path,
        authorized_root=authorized_root,
        draft_id=draft_id,
        profile=profile,
        asset_mode=asset_mode,
    )
    tracks: list[dict[str, Any]] = []
    _compile_base_track(
        context, profile=profile, repair_candidate=repair_candidate, tracks=tracks,
    )
    _compile_visual_tracks(context, profile=profile, tracks=tracks)
    _compile_caption_track(context, tracks=tracks)
    _compile_audio_and_outro_tracks(context, profile=profile, tracks=tracks)
    return _finalize_plan(
        context, draft_id=draft_id, profile=profile,
        asset_mode=asset_mode, tracks=tracks,
    )


