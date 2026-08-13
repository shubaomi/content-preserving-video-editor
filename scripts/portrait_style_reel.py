#!/usr/bin/env python3
"""Plan, validate, and review an isolated HongRun portrait Style Reel.

This module never renders media and never approves brand taste.  It binds an
already-produced source-aligned A/B/C comparison to current files and emits a
read-only/pending-only review surface.
"""
from __future__ import annotations

import html
import ipaddress
import json
import math
import os
import shutil
import subprocess
import sys
from array import array
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

from director_contracts import read_json, sha256_file, write_json
from portrait_brand_contracts import validate_portrait_contract_schema
from portrait_sonic import (
    PortraitSonicError,
    authorized_portrait_sfx_root,
    portrait_sonic_plan_artifacts,
    validate_portrait_sonic_projection,
)


DIRECTIONS = (
    "luminous_intelligence",
    "high_energy_creator",
    "humanist_cinema",
)
PHASES = ("entrance", "mid", "pre_exit", "post_exit")
USER_QUESTIONS = (
    ("format_fit", "这种表达方式适合我的个人口播吗？"),
    ("person_primary", "人物是否始终是画面第一主体？"),
    ("expressive_not_noisy", "动效是否更有表现力但不过度喧闹？"),
    ("semantic_help", "动效是否真正帮助理解，而不是复述字幕？"),
    ("sonic_fit", "声音语言是否契合且没有压住口播？"),
    ("repeat_use_willingness", "是否愿意反复使用这套品牌动效语言？"),
)
AUTHORITY_NAMES = (
    "source", "edl", "transcript", "output_transcript", "semantic_brief",
    "captions", "audio_policy", "voice_stem", "subject_evidence", "profile",
    "audio_plan", "sonic_plan",
    "motion_contracts", "storyboard",
)
EVIDENCE_CLASSES = {"synthetic_fixture", "real_project"}

# These five-dimensional specifications are the authority behind each frozen
# structural fingerprint.  Labels, colors, easing, or entrance direction alone
# cannot change the fingerprint.
DIRECTION_SPECS: dict[str, dict[str, Any]] = {
    "luminous_intelligence": {
        "hierarchy": "person_meaning_luminous_relation_ambient_depth",
        "layout": "face_safe_asymmetric_orbit",
        "camera": "shallow_depth_gentle_release",
        "choreography": "calm_base_decisive_burst_warm_resolve",
        "sonic": "PBM-S01_PBM-S03_PBM-S05",
        "recipe_ids": ["PBM-01", "PBM-02", "PBM-04", "PBM-08"],
        "energy_tiers": ["micro", "meso"],
        "macro_capable": True,
    },
    "high_energy_creator": {
        "hierarchy": "person_gesture_kinetic_phrase_camera_trace",
        "layout": "gesture_led_split_energy_field",
        "camera": "controlled_punch_and_settle",
        "choreography": "micro_bursts_fast_settle_quiet_reset",
        "sonic": "PBM-S01_PBM-S02_PBM-S04",
        "recipe_ids": ["PBM-01", "PBM-03", "PBM-05", "PBM-07"],
        "energy_tiers": ["micro", "meso", "macro"],
        "macro_capable": True,
    },
    "humanist_cinema": {
        "hierarchy": "person_emotion_light_phrase_evidence",
        "layout": "cinematic_negative_space_cutaway",
        "camera": "slow_focus_warm_depth",
        "choreography": "evolving_meso_deliberate_silence",
        "sonic": "PBM-S02_PBM-S05_intentional_silence",
        "recipe_ids": ["PBM-02", "PBM-05", "PBM-06", "PBM-08"],
        "energy_tiers": ["micro", "meso"],
        "macro_capable": False,
    },
}


class StyleReelError(ValueError):
    """Raised when a Style Reel action would violate the frozen contract."""


def _stable_hash(value: Any) -> str:
    return sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _file_ref(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise StyleReelError(f"required Style Reel file is missing: {path}")
    return {"path": str(path), "sha256": sha256_file(path)}


def _file_ref_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} must be a file reference"]
    raw_path = value.get("path")
    digest = value.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return [f"{label} path must be a non-empty absolute path"]
    path = Path(raw_path)
    if not path.is_absolute():
        return [f"{label} path must be absolute"]
    if not path.is_file():
        return [f"{label} file is missing: {path}"]
    if not isinstance(digest, str) or digest != sha256_file(path):
        return [f"{label} hash is stale: {path}"]
    return []


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _safe_output_path(root: Path, relative: Path) -> Path:
    """Resolve one output without letting an existing link redirect a write."""
    try:
        root = Path(root).resolve()
        relative = Path(relative)
    except TypeError as error:
        raise StyleReelError("Style Reel output root/path is malformed") from error
    if relative.is_absolute() or ".." in relative.parts:
        raise StyleReelError("Style Reel output path must be a relative child")
    target = root / relative
    current = root
    for part in relative.parent.parts:
        current = current / part
        if current.exists():
            is_junction = bool(
                getattr(os.path, "isjunction", lambda _path: False)(current)
            )
            if current.is_symlink() or is_junction or not current.resolve().is_relative_to(root):
                raise StyleReelError(f"Style Reel output escaped through a link: {current}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.resolve().is_relative_to(root):
        raise StyleReelError(f"Style Reel output escaped through a link: {target.parent}")
    resolved = target.resolve()
    if target.exists() and target.is_dir():
        raise StyleReelError(f"Style Reel output target must not be a directory: {target}")
    if not resolved.is_relative_to(root):
        raise StyleReelError(f"Style Reel output escaped through a link: {target}")
    return resolved


def _safe_json_output(authorized_root: Path, output: Path) -> Path:
    """Resolve a JSON output lexically under one caller-authorized Director root."""
    try:
        root = Path(authorized_root).resolve()
        absolute_output = Path(os.path.abspath(output))
    except TypeError as error:
        raise StyleReelError("Style Reel authorized output root/path is malformed") from error
    if not root.is_dir():
        raise StyleReelError("Style Reel authorized output root must be an existing directory")
    try:
        relative = absolute_output.relative_to(Path(os.path.abspath(root)))
    except ValueError as error:
        raise StyleReelError("Style Reel output must remain inside the authorized Director root") from error
    return _safe_output_path(root, relative)


def _integrity_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bind an explicit local user decision to its exact current bytes.

    This is deliberately an integrity checksum, not encryption, a secret, or
    cryptographic proof of identity.  The interactive Codex task remains the
    user-confirmation surface; the receipt only detects later file drift.
    """
    result = deepcopy(dict(payload))
    result["integrity_sha256"] = sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return result


def _integrity_errors(payload: Any, label: str) -> list[str]:
    if not isinstance(payload, Mapping):
        return [f"{label} must be a mapping"]
    declared = payload.get("integrity_sha256")
    unsigned = {
        key: value for key, value in payload.items() if key != "integrity_sha256"
    }
    try:
        expected = _integrity_payload(unsigned)["integrity_sha256"]
    except (TypeError, ValueError) as error:
        return [str(error)]
    if not isinstance(declared, str) or declared != expected:
        return [f"{label} integrity hash is invalid"]
    return []


def _direction_fingerprint(direction_id: str) -> str:
    return _stable_hash(DIRECTION_SPECS[direction_id])


def _direction_recipe_ids(spec: Mapping[str, Any], *, macro_selected: bool) -> list[str]:
    recipes = [str(value) for value in spec["recipe_ids"] if value != "PBM-07"]
    if macro_selected:
        recipes.append("PBM-07")
    return recipes


def _read_mapping(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = read_json(path.resolve())
    except (OSError, json.JSONDecodeError) as error:
        raise StyleReelError(f"{label} is invalid JSON: {path}: {error}") from error
    if not isinstance(payload, Mapping):
        raise StyleReelError(f"{label} must be a mapping: {path}")
    return payload


def _edl_ranges(
    edl: Mapping[str, Any], *, source_path: Path, source_duration: float,
) -> list[tuple[float, float, float, float]]:
    if edl.get("owner") != "video-use":
        raise StyleReelError("Style Reel EDL owner must be video-use")
    sources = edl.get("sources")
    source_row = sources.get(source_path.name) if isinstance(sources, Mapping) else None
    if not isinstance(source_row, Mapping) or source_row.get("sha256") != sha256_file(source_path):
        raise StyleReelError("Style Reel EDL must bind the current source bytes")
    rows = edl.get("ranges")
    if not isinstance(rows, list) or not rows:
        raise StyleReelError("Style Reel EDL requires retained ranges")
    result: list[tuple[float, float, float, float]] = []
    cursor = 0.0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("source") != source_path.name:
            raise StyleReelError(f"Style Reel EDL range {index} is malformed")
        start = _finite(row.get("start"))
        end = _finite(row.get("end"))
        timeline_start = _finite(row.get("timeline_start"))
        if timeline_start is None:
            timeline_start = cursor
        if (
            start is None or end is None or start < 0 or end <= start
            or end > source_duration + 0.1 or timeline_start < 0
        ):
            raise StyleReelError(f"Style Reel EDL range {index} is outside current media")
        timeline_end = timeline_start + end - start
        result.append((start, end, timeline_start, timeline_end))
        cursor = max(cursor, timeline_end)
    return result


def _validate_window_against_edl(
    *, source_path: Path, edl_path: Path, start_seconds: float, end_seconds: float,
) -> list[tuple[float, float, float, float]]:
    source_duration = _probe_duration(source_path)
    edl = _read_mapping(edl_path, "Style Reel EDL")
    ranges = _edl_ranges(edl, source_path=source_path, source_duration=source_duration)
    cursor = start_seconds
    for _, _, output_start, output_end in sorted(ranges, key=lambda row: row[2]):
        if output_end <= cursor + 1e-6:
            continue
        if output_start > cursor + 0.05:
            break
        cursor = max(cursor, output_end)
        if cursor >= end_seconds - 1e-6:
            return ranges
    raise StyleReelError("Style Reel window is not fully covered by the current video-use EDL")


def _chapter_boundary_errors(
    payload: Any, *, path: Path, source_path: Path, edl_path: Path,
    ranges: Sequence[tuple[float, float, float, float]],
    start_seconds: float, end_seconds: float, event_ids: Sequence[str],
    semantic_rows: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["Style Reel chapter boundary must be a mapping"]
    allowed = {
        "schema_version", "kind", "status", "boundary_id", "chapter_id", "event_id",
        "structural", "source", "edl", "source_seconds", "output_seconds",
        "owner", "basis_kind",
    }
    errors: list[str] = []
    if set(payload) != allowed:
        errors.append("Style Reel chapter boundary fields are incomplete or unsupported")
    if (
        payload.get("schema_version") != 1 or payload.get("kind") != "chapter_boundary"
        or payload.get("status") != "pass" or payload.get("structural") is not True
        or payload.get("owner") != "video-use" or payload.get("basis_kind") != "edl_cut"
    ):
        errors.append("Style Reel chapter boundary type/status is invalid")
    for field in ("boundary_id", "chapter_id"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(f"Style Reel chapter boundary {field} is required")
    if payload.get("event_id") not in event_ids:
        errors.append("Style Reel chapter boundary event is outside the semantic set")
    for name, expected in (("source", source_path), ("edl", edl_path)):
        errors.extend(_file_ref_errors(payload.get(name), f"Style Reel chapter boundary {name}"))
        ref = payload.get(name) if isinstance(payload.get(name), Mapping) else {}
        if str(ref.get("path") or "") != str(expected.resolve()):
            errors.append(f"Style Reel chapter boundary {name} path is stale")
    source_time = _finite(payload.get("source_seconds"))
    output_time = _finite(payload.get("output_seconds"))
    if source_time is None or output_time is None or not start_seconds <= output_time <= end_seconds:
        errors.append("Style Reel chapter boundary is outside the selected window")
    elif not any(
        source_start - 0.05 <= source_time <= source_end + 0.05
        and abs((source_time - source_start + output_start) - output_time) <= 0.05
        for source_start, source_end, output_start, _ in ranges
    ):
        errors.append("Style Reel chapter boundary source/output mapping is stale")
    event_id = str(payload.get("event_id") or "")
    semantic_row = semantic_rows.get(event_id)
    semantic_time = _finite(semantic_row.get("output_start")) if isinstance(semantic_row, Mapping) else None
    if output_time is None or semantic_time is None or abs(output_time - semantic_time) > 0.05:
        errors.append("Style Reel chapter boundary does not bind the semantic event start")
    cut_points = {
        round(value, 6)
        for source_start, source_end, output_start, output_end in ranges
        for value in (output_start, output_end)
        if start_seconds + 0.05 < value < end_seconds - 0.05
    }
    if output_time is None or not any(abs(output_time - value) <= 0.05 for value in cut_points):
        errors.append("Style Reel chapter boundary is not a current internal video-use EDL cut")
    if path.resolve() in {source_path.resolve(), edl_path.resolve()}:
        errors.append("Style Reel chapter boundary must be an independent typed record")
    return errors


def _semantic_rows(path: Path) -> dict[str, Mapping[str, Any]]:
    payload = _read_mapping(path, "Style Reel semantic brief")
    events = payload.get("events")
    if not isinstance(events, list):
        raise StyleReelError("Style Reel semantic brief events must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(events):
        if not isinstance(row, Mapping):
            raise StyleReelError(f"Style Reel semantic event {index} must be a mapping")
        event_id = str(row.get("semantic_event_id") or row.get("id") or "")
        if not event_id or event_id in result:
            raise StyleReelError("Style Reel semantic event IDs must be unique and non-empty")
        result[event_id] = row
    return result


def _semantic_decision_inventory(
    semantic_rows: Mapping[str, Mapping[str, Any]], event_ids: Sequence[str], *,
    allow_legacy_render_default: bool,
) -> dict[str, str]:
    allowed = {
        "render", "annotation", "caption_only", "reuse_source", "quiet_source",
    }
    decisions: dict[str, str] = {}
    for event_id in event_ids:
        row = semantic_rows.get(event_id)
        if not isinstance(row, Mapping):
            raise StyleReelError(f"Style Reel semantic event is missing: {event_id}")
        decision = row.get("decision")
        if decision is None and allow_legacy_render_default:
            decision = "render"
        if decision not in allowed:
            raise StyleReelError(
                f"Style Reel semantic event {event_id} requires an explicit supported decision"
            )
        decisions[event_id] = str(decision)
    if not any(value == "render" for value in decisions.values()):
        raise StyleReelError("Style Reel comparison requires at least one approved render event")
    return decisions


def _manifest_semantic_decisions(
    manifest: Mapping[str, Any], event_ids: Sequence[str],
) -> dict[str, str]:
    authorities = manifest.get("authorities")
    if not isinstance(authorities, Mapping):
        raise StyleReelError("Style Reel authority inventory is missing")
    semantic_ref = authorities.get("semantic_brief")
    if not isinstance(semantic_ref, Mapping) or not isinstance(semantic_ref.get("path"), str):
        raise StyleReelError("Style Reel semantic brief authority is missing")
    rows = _semantic_rows(Path(str(semantic_ref["path"])).resolve())
    return _semantic_decision_inventory(
        rows, event_ids,
        allow_legacy_render_default=manifest.get("evidence_class") == "synthetic_fixture",
    )


def _semantic_projection(row: Mapping[str, Any], *, window_start: float) -> dict[str, Any]:
    intent = row.get("portrait_energy_intent")
    intent = intent if isinstance(intent, Mapping) else {}
    output_start = _finite(row.get("output_start"))
    source_sentence = row.get("source_sentence", row.get("quoted_evidence"))
    rationale = intent.get("rationale", row.get("decision_rationale", row.get("relevance_rationale")))
    return {
        "marker_seconds": None if output_start is None else round(output_start - window_start, 6),
        "source_sentence": source_sentence,
        "approved_visible_copy": row.get("approved_visible_copy"),
        "viewer_takeaway": row.get("viewer_takeaway"),
        "energy_tier": intent.get("tier", row.get("energy_tier")),
        "rationale": rationale,
    }


def create_style_reel_window_confirmation(
    *, plan_path: Path, authority_manifest_path: Path, actor: str, output: Path,
    authorized_root: Path,
) -> dict[str, Any]:
    if actor != "HongRun":
        raise StyleReelError("only HongRun can confirm the exact Style Reel window")
    plan_path = plan_path.resolve()
    authority_manifest_path = authority_manifest_path.resolve()
    plan = _read_mapping(plan_path, "Style Reel plan")
    manifest = _read_mapping(authority_manifest_path, "Style Reel authority manifest")
    errors = validate_style_reel_authority_manifest(manifest, plan_path=plan_path)
    if errors:
        raise StyleReelError("Style Reel window authorities are stale:\n- " + "\n- ".join(errors))
    if manifest.get("evidence_class") != "real_project":
        raise StyleReelError("synthetic fixture windows cannot authorize real Style Reel renders")
    basis = plan.get("comparison_basis") if isinstance(plan.get("comparison_basis"), Mapping) else {}
    receipt = _integrity_payload({
        "schema_version": 1,
        "kind": "portrait_style_reel_window_confirmation",
        "actor": "HongRun",
        "decision": "confirmed",
        "plan": _file_ref(plan_path),
        "authority_manifest": _file_ref(authority_manifest_path),
        "comparison_basis_sha256": _basis_hash(plan),
        "start_seconds": basis.get("start_seconds"),
        "end_seconds": basis.get("end_seconds"),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "confirmation_method": "explicit_user_confirmation_hash_v1",
    })
    output = _safe_json_output(authorized_root, output)
    write_json(output, receipt)
    return receipt


def validate_style_reel_window_confirmation(
    receipt: Any, *, plan_path: Path, authority_manifest_path: Path,
) -> list[str]:
    errors = _integrity_errors(receipt, "Style Reel window confirmation")
    if not isinstance(receipt, Mapping):
        return errors
    required = {
        "schema_version", "kind", "actor", "decision", "plan", "authority_manifest",
        "comparison_basis_sha256", "start_seconds", "end_seconds", "confirmed_at",
        "confirmation_method", "integrity_sha256",
    }
    if set(receipt) != required:
        errors.append("Style Reel window confirmation fields are incomplete or unsupported")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "portrait_style_reel_window_confirmation"
        or receipt.get("actor") != "HongRun" or receipt.get("decision") != "confirmed"
        or receipt.get("confirmation_method") != "explicit_user_confirmation_hash_v1"
    ):
        errors.append("Style Reel window confirmation identity or decision is invalid")
    plan_path = plan_path.resolve()
    authority_manifest_path = authority_manifest_path.resolve()
    for field, expected in (("plan", plan_path), ("authority_manifest", authority_manifest_path)):
        errors.extend(_file_ref_errors(receipt.get(field), f"Style Reel window {field}"))
        ref = receipt.get(field) if isinstance(receipt.get(field), Mapping) else {}
        if str(ref.get("path") or "") != str(expected):
            errors.append(f"Style Reel window {field} path is stale")
    if authority_manifest_path.is_file():
        try:
            manifest = _read_mapping(
                authority_manifest_path, "Style Reel window authority manifest",
            )
        except StyleReelError as error:
            errors.append(str(error))
        else:
            errors.extend(validate_style_reel_authority_manifest(
                manifest, plan_path=plan_path,
            ))
            if manifest.get("evidence_class") != "real_project":
                errors.append("Style Reel window confirmation requires real-project evidence")
    confirmed_at = receipt.get("confirmed_at")
    try:
        parsed_at = datetime.fromisoformat(str(confirmed_at).replace("Z", "+00:00"))
        if parsed_at.tzinfo is None or parsed_at > datetime.now(timezone.utc):
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Style Reel window confirmed_at is invalid")
    if plan_path.is_file():
        try:
            plan = _read_mapping(plan_path, "Style Reel plan")
        except StyleReelError as error:
            errors.append(str(error))
        else:
            basis = plan.get("comparison_basis") if isinstance(plan.get("comparison_basis"), Mapping) else {}
            if receipt.get("comparison_basis_sha256") != _basis_hash(plan):
                errors.append("Style Reel window comparison basis is stale")
            for field in ("start_seconds", "end_seconds"):
                if _finite(receipt.get(field)) != _finite(basis.get(field)):
                    errors.append(f"Style Reel window {field} is stale")
    return errors


def build_style_reel_render_requests(
    *, plan_path: Path, authority_manifest_path: Path, output_dir: Path,
    window_confirmation_receipt_path: Path | None = None,
) -> list[Path]:
    """Write isolated HyperFrames-owned requests; never execute or claim a render."""
    plan_path = plan_path.resolve()
    plan = _load_direction_contract(plan_path)
    schema_errors = validate_portrait_contract_schema("style-reel-plan", plan)
    if schema_errors:
        raise StyleReelError("Style Reel plan schema is invalid:\n- " + "\n- ".join(schema_errors))
    authority_manifest_path = authority_manifest_path.resolve()
    try:
        authority_manifest = read_json(authority_manifest_path)
    except (OSError, json.JSONDecodeError) as error:
        raise StyleReelError(f"Style Reel authority manifest is invalid: {error}") from error
    authority_errors = validate_style_reel_authority_manifest(
        authority_manifest, plan_path=plan_path,
    )
    if authority_errors:
        raise StyleReelError("Style Reel authorities are stale:\n- " + "\n- ".join(authority_errors))
    evidence_class = authority_manifest.get("evidence_class")
    if evidence_class == "real_project":
        raise StyleReelError(
            "real-project Style Reel review requires the separate WP6 HyperFrames runtime, "
            "caption-last, voice/mix, and parity evidence gate"
        )
    evidence_class = authority_manifest.get("evidence_class")
    confirmation_ref: dict[str, str] | None = None
    confirmed = False
    if window_confirmation_receipt_path is not None:
        confirmation_path = window_confirmation_receipt_path.resolve()
        confirmation = _read_mapping(confirmation_path, "Style Reel window confirmation")
        confirmation_errors = validate_style_reel_window_confirmation(
            confirmation, plan_path=plan_path, authority_manifest_path=authority_manifest_path,
        )
        if confirmation_errors:
            raise StyleReelError("Style Reel window confirmation is stale:\n- " + "\n- ".join(confirmation_errors))
        confirmation_ref = _file_ref(confirmation_path)
        confirmed = evidence_class == "real_project"
    output_dir = output_dir.resolve()
    authorized_root = plan_path.parent.resolve()
    if not output_dir.is_relative_to(authorized_root):
        raise StyleReelError("Style Reel render-request output must remain beside the plan")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.resolve().is_relative_to(authorized_root):
        raise StyleReelError("Style Reel render-request output escaped through a link")
    pending_requests: list[tuple[Path, dict[str, Any]]] = []
    for direction in plan["directions"]:
        direction_id = str(direction["direction_id"])
        request = {
            "schema_version": 1,
            "request_id": f"{plan['plan_id']}-{direction_id}",
            "owner": "hyperframes",
            "purpose": "isolated_portrait_style_reel_direction",
            "status": "action_required" if confirmed else "blocked_by_user_window_confirmation",
            "plan": _file_ref(plan_path),
            "authority_manifest": _file_ref(authority_manifest_path),
            "comparison_basis_sha256": _basis_hash(plan),
            "direction_id": direction_id,
            "structural_fingerprint": direction["structural_fingerprint"],
            "recipe_ids": list(direction["recipe_ids"]),
            "expected_outputs": {
                "media": str((output_dir / "media" / f"{direction_id}.mp4").resolve()),
                "contract": str((output_dir / "contracts" / f"{direction_id}.json").resolve()),
                "phase_evidence_dir": str((output_dir / "phases" / direction_id).resolve()),
            },
            "output_policy": dict(plan["output_policy"]),
            "exact_window_confirmation": {
                "confirmed": confirmed,
                "receipt": confirmation_ref,
            },
            "command": None,
            "note": (
                "Run the owning HyperFrames workflow only after the exact 30-45 second window is confirmed."
            ),
        }
        path = _safe_output_path(output_dir, Path("requests") / f"{direction_id}.json")
        for relative in (
            Path("media") / f"{direction_id}.mp4",
            Path("contracts") / f"{direction_id}.json",
            Path("phases") / direction_id / ".containment-check",
        ):
            _safe_output_path(output_dir, relative)
        pending_requests.append((path, request))
    manifest_path = _safe_output_path(output_dir, Path("style-reel-render-requests.json"))
    request_paths = [path.resolve() for path, _ in pending_requests]
    written: list[Path] = []
    try:
        for path, request in pending_requests:
            write_json(path, request)
            written.append(path)
        manifest = {
            "schema_version": 1,
            "plan": _file_ref(plan_path),
            "authority_manifest": _file_ref(authority_manifest_path),
            "requests": [_file_ref(path) for path in request_paths],
            "full_video_render_authorized": False,
            "automatic_execution": False,
        }
        write_json(manifest_path, manifest)
        written.append(manifest_path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return request_paths


def _require_paths(paths: Mapping[str, Path]) -> dict[str, Path]:
    if not isinstance(paths, Mapping):
        raise StyleReelError("Style Reel authority paths must be a mapping")
    required = AUTHORITY_NAMES
    missing = [name for name in required if name not in paths]
    if missing:
        raise StyleReelError("missing Style Reel authorities: " + ", ".join(missing))
    try:
        resolved = {name: Path(paths[name]).resolve() for name in required}
    except TypeError as error:
        raise StyleReelError("Style Reel authority path is malformed") from error
    if "chapter_boundary" in paths:
        try:
            resolved["chapter_boundary"] = Path(paths["chapter_boundary"]).resolve()
        except TypeError as error:
            raise StyleReelError("Style Reel chapter-boundary path is malformed") from error
    return resolved


def style_reel_authority_manifest_path(plan_path: Path) -> Path:
    return plan_path.resolve().with_name("style-reel-authorities.json")


def validate_style_reel_authority_manifest(
    manifest: Any, *, plan_path: Path,
) -> list[str]:
    if not isinstance(manifest, Mapping):
        return ["Style Reel authority manifest must be a mapping"]
    errors: list[str] = []
    allowed = {
        "schema_version", "plan", "comparison_basis_sha256", "authorities",
        "expected_event_ids", "evidence_class",
    }
    if set(manifest) != allowed:
        errors.append("Style Reel authority manifest fields are incomplete or unsupported")
    if manifest.get("schema_version") != 1:
        errors.append("Style Reel authority manifest schema_version must be 1")
    if manifest.get("evidence_class") not in EVIDENCE_CLASSES:
        errors.append("Style Reel authority evidence_class is invalid")
    plan_path = plan_path.resolve()
    errors.extend(_file_ref_errors(manifest.get("plan"), "Style Reel authority plan"))
    plan_ref = manifest.get("plan") if isinstance(manifest.get("plan"), Mapping) else {}
    if (
        not plan_path.is_file() or str(plan_ref.get("path") or "") != str(plan_path)
        or plan_ref.get("sha256") != sha256_file(plan_path)
    ):
        errors.append("Style Reel authority plan binding is stale")
        return errors
    try:
        plan = read_json(plan_path)
    except (OSError, json.JSONDecodeError):
        return errors + ["Style Reel authority plan is invalid JSON"]
    if not isinstance(plan, Mapping):
        return errors + ["Style Reel authority plan must be a mapping"]
    authorities = manifest.get("authorities")
    required_authorities = set(AUTHORITY_NAMES)
    if (
        not isinstance(authorities, Mapping)
        or not required_authorities.issubset(authorities)
        or set(authorities) - (required_authorities | {"chapter_boundary"})
    ):
        return errors + ["Style Reel authority file inventory is incomplete"]
    authority_paths: dict[str, Path] = {}
    for name, ref in authorities.items():
        errors.extend(_file_ref_errors(ref, f"Style Reel authority {name}"))
        if isinstance(ref, Mapping) and isinstance(ref.get("path"), str):
            authority_paths[name] = Path(str(ref["path"])).resolve()
    expected_ids = manifest.get("expected_event_ids")
    if not isinstance(expected_ids, list):
        errors.append("Style Reel authority expected_event_ids must be a list")
        expected_ids = []
    if manifest.get("comparison_basis_sha256") != _basis_hash(plan):
        errors.append("Style Reel authority comparison basis is stale")
    if required_authorities.issubset(authority_paths):
        errors.extend(validate_style_reel_plan(
            plan, authority_paths=authority_paths, expected_event_ids=expected_ids,
        ))
    return errors


def build_style_reel_plan(
    *, project_id: str, source_path: Path, edl_path: Path,
    transcript_path: Path, output_transcript_path: Path, semantic_brief_path: Path,
    captions_path: Path, audio_policy_path: Path, voice_stem_path: Path,
    subject_evidence_path: Path, profile_path: Path, semantic_event_ids: Sequence[str],
    audio_plan_path: Path, sonic_plan_path: Path,
    motion_contracts_path: Path, storyboard_path: Path,
    start_seconds: float, end_seconds: float, output: Path,
    chapter_boundary_evidence_path: Path | None = None, authorized_root: Path,
    evidence_class: str = "synthetic_fixture",
) -> dict[str, Any]:
    """Build the deterministic, isolated A/B/C comparison plan."""
    authorities = _require_paths({
        "source": source_path, "edl": edl_path, "transcript": transcript_path,
        "output_transcript": output_transcript_path, "semantic_brief": semantic_brief_path,
        "captions": captions_path, "audio_policy": audio_policy_path,
        "voice_stem": voice_stem_path, "subject_evidence": subject_evidence_path,
        "profile": profile_path,
        "audio_plan": audio_plan_path, "sonic_plan": sonic_plan_path,
        "motion_contracts": motion_contracts_path, "storyboard": storyboard_path,
        **({"chapter_boundary": chapter_boundary_evidence_path}
           if chapter_boundary_evidence_path is not None else {}),
    })
    for name, path in authorities.items():
        if not path.is_file():
            raise StyleReelError(f"{name} authority is missing: {path}")
    if evidence_class not in EVIDENCE_CLASSES:
        raise StyleReelError("Style Reel evidence_class must be synthetic_fixture or real_project")
    start_value = _finite(start_seconds)
    end_value = _finite(end_seconds)
    if start_value is None or end_value is None:
        raise StyleReelError("Style Reel comparison start/end must be finite numbers")
    duration = end_value - start_value
    if not math.isfinite(duration) or duration < 30.0 or duration > 45.0:
        raise StyleReelError("Style Reel comparison duration must be 30 to 45 seconds")
    if (
        not isinstance(semantic_event_ids, Sequence)
        or isinstance(semantic_event_ids, (str, bytes))
        or any(not isinstance(value, str) or not value.strip() for value in semantic_event_ids)
    ):
        raise StyleReelError("Style Reel semantic event IDs must be a sequence of non-empty strings")
    event_ids = list(semantic_event_ids)
    if len(event_ids) < 2 or len(event_ids) != len(set(event_ids)):
        raise StyleReelError("Style Reel requires at least two unique semantic event IDs")
    semantic_rows = _semantic_rows(authorities["semantic_brief"])
    if list(semantic_rows) != event_ids:
        raise StyleReelError("Style Reel semantic event set/order differs from the current brief")
    _semantic_decision_inventory(
        semantic_rows, event_ids,
        allow_legacy_render_default=evidence_class == "synthetic_fixture",
    )
    ranges = _validate_window_against_edl(
        source_path=authorities["source"], edl_path=authorities["edl"],
        start_seconds=start_value, end_seconds=end_value,
    )
    if chapter_boundary_evidence_path is not None:
        boundary = _read_mapping(authorities["chapter_boundary"], "Style Reel chapter boundary")
        boundary_errors = _chapter_boundary_errors(
            boundary, path=authorities["chapter_boundary"], source_path=authorities["source"],
            edl_path=authorities["edl"], ranges=ranges,
            start_seconds=start_value, end_seconds=end_value, event_ids=event_ids,
            semantic_rows=semantic_rows,
        )
        if boundary_errors:
            raise StyleReelError("invalid Style Reel chapter boundary:\n- " + "\n- ".join(boundary_errors))
    profile_ref = _file_ref(authorities["profile"])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "plan_id": f"{project_id}-portrait-style-reel-v2",
        "project_id": project_id,
        "comparison_basis": {
            "source": _file_ref(authorities["source"]),
            "edl_sha256": sha256_file(authorities["edl"]),
            "transcript_sha256": sha256_file(authorities["transcript"]),
            "semantic_event_ids": event_ids,
            "caption_sha256": sha256_file(authorities["captions"]),
            "start_seconds": start_value,
            "end_seconds": end_value,
            "audio_policy_sha256": sha256_file(authorities["audio_policy"]),
        },
        "directions": [],
        "output_policy": {
            "isolated": True,
            "may_replace_automatic_master": False,
            "full_video_render_authorized": False,
        },
    }
    for direction_id in DIRECTIONS:
        spec = DIRECTION_SPECS[direction_id]
        macro_selected = bool(
            spec["macro_capable"] and chapter_boundary_evidence_path is not None
        )
        payload["directions"].append({
            "direction_id": direction_id,
            "profile": dict(profile_ref),
            "structural_fingerprint": _direction_fingerprint(direction_id),
            "recipe_ids": _direction_recipe_ids(spec, macro_selected=macro_selected),
            "energy_tiers": list(spec["energy_tiers"]),
            "macro_applicability": "selected" if macro_selected else "not_applicable",
            "macro_reason": (
                "A current independent chapter-boundary authority permits this macro direction."
                if macro_selected else
                "No current independent chapter boundary applies to this direction."
            ),
            "status": "planned",
        })
    errors = validate_style_reel_plan(
        payload, authority_paths=authorities, expected_event_ids=event_ids,
    )
    if errors:
        raise StyleReelError("invalid Style Reel plan:\n- " + "\n- ".join(errors))
    output = _safe_json_output(authorized_root, output)
    manifest_output = _safe_json_output(
        authorized_root, style_reel_authority_manifest_path(output),
    )
    output_existed = output.is_file()
    old_output = output.read_bytes() if output_existed else None
    try:
        write_json(output, payload)
        manifest = {
            "schema_version": 1,
            "plan": _file_ref(output),
            "comparison_basis_sha256": _basis_hash(payload),
            "authorities": {name: _file_ref(path) for name, path in authorities.items()},
            "expected_event_ids": event_ids,
            "evidence_class": evidence_class,
        }
        write_json(manifest_output, manifest)
    except Exception:
        if output_existed and old_output is not None:
            output.write_bytes(old_output)
        else:
            output.unlink(missing_ok=True)
        raise
    return payload


def validate_style_reel_plan(
    plan: Any, *, authority_paths: Mapping[str, Path],
    expected_event_ids: Sequence[str],
) -> list[str]:
    errors = validate_portrait_contract_schema("style-reel-plan", plan)
    if not isinstance(plan, Mapping):
        return errors or ["Style Reel plan must be a mapping"]
    try:
        paths = _require_paths(authority_paths)
    except StyleReelError as error:
        return errors + [str(error)]
    basis = plan.get("comparison_basis")
    if not isinstance(basis, Mapping):
        return errors + ["Style Reel comparison basis must be a mapping"]
    errors.extend(_file_ref_errors(basis.get("source"), "Style Reel source"))
    expected_hashes = {
        "edl_sha256": ("EDL", paths["edl"]),
        "transcript_sha256": ("transcript", paths["transcript"]),
        "caption_sha256": ("caption", paths["captions"]),
        "audio_policy_sha256": ("audio policy", paths["audio_policy"]),
    }
    for field, (label, path) in expected_hashes.items():
        if not path.is_file() or basis.get(field) != sha256_file(path):
            errors.append(f"Style Reel {label} authority hash is stale")
    source_path = paths["source"]
    source_ref = basis.get("source") if isinstance(basis.get("source"), Mapping) else {}
    if str(source_ref.get("path") or "") != str(source_path):
        errors.append("Style Reel source path differs from current authority")
    event_ids = list(basis.get("semantic_event_ids") or [])
    if event_ids != list(expected_event_ids):
        errors.append("Style Reel event set or order differs from current authority")
    try:
        duration = float(basis.get("end_seconds")) - float(basis.get("start_seconds"))
    except (TypeError, ValueError):
        duration = math.nan
    if not math.isfinite(duration) or not 30.0 <= duration <= 45.0:
        errors.append("Style Reel comparison duration must be 30 to 45 seconds")
    try:
        start_seconds = float(basis.get("start_seconds"))
        end_seconds = float(basis.get("end_seconds"))
        ranges = _validate_window_against_edl(
            source_path=paths["source"], edl_path=paths["edl"],
            start_seconds=start_seconds, end_seconds=end_seconds,
        )
    except (TypeError, ValueError, StyleReelError) as error:
        errors.append(str(error))
        ranges = []
        start_seconds = end_seconds = 0.0
    semantic_rows: dict[str, Mapping[str, Any]] = {}
    try:
        semantic_rows = _semantic_rows(paths["semantic_brief"])
    except StyleReelError as error:
        errors.append(str(error))
    else:
        if list(semantic_rows) != list(expected_event_ids):
            errors.append("Style Reel semantic event set/order differs from the current brief")
    if "chapter_boundary" in paths:
        try:
            boundary = _read_mapping(paths["chapter_boundary"], "Style Reel chapter boundary")
        except StyleReelError as error:
            errors.append(str(error))
        else:
            errors.extend(_chapter_boundary_errors(
                boundary, path=paths["chapter_boundary"], source_path=paths["source"],
                edl_path=paths["edl"], ranges=ranges,
                start_seconds=start_seconds, end_seconds=end_seconds,
                event_ids=list(expected_event_ids),
                semantic_rows=semantic_rows,
            ))
    directions = plan.get("directions")
    if not isinstance(directions, list):
        return errors + ["Style Reel directions must be a list"]
    if [row.get("direction_id") for row in directions if isinstance(row, Mapping)] != list(DIRECTIONS):
        errors.append("Style Reel directions must use the frozen A/B/C order")
    profile_ref = _file_ref(paths["profile"]) if paths["profile"].is_file() else None
    fingerprints: list[Any] = []
    for index, direction_id in enumerate(DIRECTIONS):
        if index >= len(directions) or not isinstance(directions[index], Mapping):
            errors.append(f"Style Reel direction {direction_id} is missing or malformed")
            continue
        row = directions[index]
        spec = DIRECTION_SPECS[direction_id]
        fingerprints.append(row.get("structural_fingerprint"))
        if row.get("structural_fingerprint") != _direction_fingerprint(direction_id):
            errors.append(f"Style Reel {direction_id} structural fingerprint is stale")
        if list(row.get("energy_tiers") or []) != list(spec["energy_tiers"]):
            errors.append(f"Style Reel {direction_id} energy structure is stale")
        macro_selected = bool(spec["macro_capable"] and "chapter_boundary" in paths)
        if list(row.get("recipe_ids") or []) != _direction_recipe_ids(
            spec, macro_selected=macro_selected,
        ):
            errors.append(f"Style Reel {direction_id} recipe structure is stale")
        if row.get("macro_applicability") != (
            "selected" if macro_selected else "not_applicable"
        ):
            errors.append(f"Style Reel {direction_id} macro applicability is stale")
        if profile_ref is None or row.get("profile") != profile_ref:
            errors.append(f"Style Reel {direction_id} profile binding is stale")
    if len(fingerprints) != len(set(fingerprints)):
        errors.append("Style Reel structural fingerprints must be distinct")
    output_policy = plan.get("output_policy")
    if not isinstance(output_policy, Mapping) or output_policy != {
        "isolated": True,
        "may_replace_automatic_master": False,
        "full_video_render_authorized": False,
    }:
        errors.append("Style Reel output policy must remain isolated and forbid full render")
    return errors


def _probe_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        raise StyleReelError("ffprobe is required to validate Style Reel media")
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise StyleReelError(f"Style Reel media probe failed: {path}")
    try:
        duration = float(result.stdout.strip())
    except ValueError as error:
        raise StyleReelError(f"Style Reel media duration is invalid: {path}") from error
    if not math.isfinite(duration) or duration <= 0:
        raise StyleReelError(f"Style Reel media duration is invalid: {path}")
    return duration


def _probe_signature(path: Path) -> dict[str, Any]:
    """Return the comparison-critical review-media geometry/codec signature."""
    if shutil.which("ffprobe") is None:
        raise StyleReelError("ffprobe is required to validate Style Reel media")
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=index,codec_type,codec_name,width,height,avg_frame_rate,sample_rate,channels",
        "-of", "json", str(path),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise StyleReelError(f"Style Reel media signature probe failed: {path}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise StyleReelError(f"Style Reel media signature is invalid: {path}") from error
    streams = payload.get("streams") if isinstance(payload, Mapping) else None
    if not isinstance(streams, list):
        raise StyleReelError(f"Style Reel media has no stream inventory: {path}")
    videos = [row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "video"]
    audios = [row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "audio"]
    unsupported = [row for row in streams if not isinstance(row, Mapping) or row.get("codec_type") not in {"video", "audio"}]
    if len(videos) != 1 or len(audios) != 1 or unsupported:
        raise StyleReelError(
            f"Style Reel media must contain exactly one video and one audio stream: {path}"
        )
    video, audio = videos[0], audios[0]
    signature = {
        "video_codec": str(video.get("codec_name") or ""),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "frame_rate": str(video.get("avg_frame_rate") or ""),
        "audio_codec": str(audio.get("codec_name") or ""),
        "sample_rate": str(audio.get("sample_rate") or ""),
        "channels": int(audio.get("channels") or 0),
    }
    if (
        not signature["video_codec"] or signature["width"] <= 0 or signature["height"] <= 0
        or not signature["frame_rate"] or not signature["audio_codec"]
        or not signature["sample_rate"] or signature["channels"] <= 0
    ):
        raise StyleReelError(f"Style Reel media signature is incomplete: {path}")
    return signature


def _full_decode(path: Path) -> list[str]:
    if shutil.which("ffmpeg") is None:
        return ["ffmpeg is required to fully decode Style Reel media"]
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
        "-map", "0:a:0?", "-f", "null", "-",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [] if result.returncode == 0 else [
        f"Style Reel media full decode failed: {path}: {result.stderr.strip()}"
    ]


def _decode_audio_pcm(path: Path) -> bytes:
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1",
    ], capture_output=True)
    if result.returncode != 0 or not result.stdout:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise StyleReelError(f"Style Reel audition is not decodable audio: {path}: {message}")
    return result.stdout


def _pcm_samples(payload: bytes) -> list[int]:
    values = array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tolist()


def _normalized_correlation(left: Sequence[int], right: Sequence[int]) -> float:
    count = min(len(left), len(right))
    if count == 0:
        return 0.0
    lhs = left[:count]
    rhs = right[:count]
    dot = sum(float(a) * float(b) for a, b in zip(lhs, rhs))
    left_energy = sum(float(a) * float(a) for a in lhs)
    right_energy = sum(float(b) * float(b) for b in rhs)
    if left_energy <= 0 or right_energy <= 0:
        return 0.0
    return dot / math.sqrt(left_energy * right_energy)


def _expected_mixed_cue_pcm(cue_path: Path, *, volume: float, duration: float) -> bytes:
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        f"anullsrc=r=48000:cl=mono:d={duration}", "-i", str(cue_path),
        "-filter_complex", f"[1:a]volume={volume}[cue];[0:a][cue]amix=inputs=2:normalize=0",
        "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1",
    ], capture_output=True)
    if result.returncode != 0 or not result.stdout:
        raise StyleReelError("Style Reel could not reproduce the canonical cue mix")
    return result.stdout


def _audition_measurements(
    *, voice_stem: Path, off_path: Path, on_path: Path,
    output_start_seconds: float, cue_path: Path, cue_volume: float,
    cue_start_seconds: float, cue_duration_seconds: float,
) -> dict[str, Any]:
    voice_pcm = _decode_audio_pcm(voice_stem)
    off_pcm = _decode_audio_pcm(off_path)
    on_pcm = _decode_audio_pcm(on_path)
    if abs(len(off_pcm) - len(on_pcm)) > 192 or min(len(off_pcm), len(on_pcm)) < 9600:
        raise StyleReelError("Style Reel audition off/on clips must have equal non-trivial PCM duration")
    aligned_length = min(len(off_pcm), len(on_pcm))
    aligned_length -= aligned_length % 2
    off_pcm = off_pcm[:aligned_length]
    on_pcm = on_pcm[:aligned_length]
    start_byte = round(output_start_seconds * 48000) * 2
    expected_off = voice_pcm[start_byte:start_byte + len(off_pcm)]
    if len(expected_off) != len(off_pcm) or expected_off != off_pcm:
        raise StyleReelError("Style Reel audition off track is not the current voice-stem event window")
    if on_pcm == off_pcm:
        raise StyleReelError("Style Reel audition on track does not contain an observable SFX difference")
    off_samples = _pcm_samples(off_pcm)
    on_samples = _pcm_samples(on_pcm)
    residual = [max(-32768, min(32767, on - off)) for off, on in zip(off_samples, on_samples)]
    cue_pcm = _decode_audio_pcm(cue_path)
    cue_samples = _pcm_samples(cue_pcm)
    expected_samples = round(cue_duration_seconds * 48000)
    if expected_samples <= 0 or abs(len(cue_samples) - expected_samples) > 96:
        raise StyleReelError("Style Reel audition cue duration differs from the canonical decision")
    expected_residual = _pcm_samples(_expected_mixed_cue_pcm(
        cue_path, volume=cue_volume, duration=cue_duration_seconds,
    ))
    if abs(len(expected_residual) - len(cue_samples)) > 96:
        raise StyleReelError("Style Reel canonical cue mix duration is stale")
    expected_residual = expected_residual[:len(cue_samples)]
    cue_offset_samples = round((cue_start_seconds - output_start_seconds) * 48000)
    if cue_offset_samples < 0 or cue_offset_samples + len(expected_residual) > len(residual):
        raise StyleReelError("Style Reel audition cue onset is outside the event audition window")
    expected_full_residual = [0] * len(residual)
    expected_full_residual[
        cue_offset_samples:cue_offset_samples + len(expected_residual)
    ] = expected_residual
    observed_window = residual[cue_offset_samples:cue_offset_samples + len(expected_residual)]
    cue_correlation = _normalized_correlation(residual, expected_full_residual)
    cue_energy = sum(float(value) * float(value) for value in expected_residual)
    observed_gain = sum(
        float(observed) * float(expected)
        for observed, expected in zip(observed_window, expected_residual)
    ) / cue_energy if cue_energy > 0 else 0.0
    gain_error = abs(observed_gain - 1.0)
    unexpected_energy_ratio = math.sqrt(
        sum(
            float(observed - expected) * float(observed - expected)
            for observed, expected in zip(residual, expected_full_residual)
        ) / cue_energy
    ) if cue_energy > 0 else math.inf
    residual_rms = math.sqrt(sum(float(value) * float(value) for value in residual) / len(residual))
    if (
        residual_rms < 32 or cue_correlation < 0.99
        or gain_error > 0.01 or unexpected_energy_ratio > 0.01
    ):
        raise StyleReelError("Style Reel audition SFX-on does not preserve the authorized audible cue gain/onset")
    return {
        "sample_rate": 48000,
        "channels": 1,
        "sample_count": len(off_pcm) // 2,
        "duration_seconds": round(len(off_pcm) / 96000.0, 6),
        "voice_window_pcm_sha256": sha256(expected_off).hexdigest(),
        "voice_sfx_off_pcm_sha256": sha256(off_pcm).hexdigest(),
        "sfx_on_pcm_sha256": sha256(on_pcm).hexdigest(),
        "difference_sha256": sha256(bytes(a ^ b for a, b in zip(off_pcm, on_pcm))).hexdigest(),
        "cue_pcm_sha256": sha256(cue_pcm).hexdigest(),
        "cue_correlation": round(cue_correlation, 6),
        "observed_expected_mix_ratio": round(observed_gain, 6),
        "expected_mix_ratio_error": round(gain_error, 6),
        "unexpected_residual_energy_ratio": round(unexpected_energy_ratio, 6),
        "cue_offset_samples": cue_offset_samples,
        "residual_rms": round(residual_rms, 6),
    }


def _phase_errors(
    paths: Any, event_ids: Sequence[str], label: str,
    inventory: Any,
) -> list[str]:
    if not isinstance(paths, list):
        return [f"{label} phase evidence must be a list"]
    errors: list[str] = []
    expected_count = len(event_ids) * len(PHASES)
    if len(paths) != expected_count:
        errors.append(f"{label} phase evidence must contain {expected_count} event-phase images")
    expected_rows = [
        (event_id, phase) for event_id in event_ids for phase in PHASES
    ]
    if not isinstance(inventory, list):
        errors.append(f"{label} direction contract phase inventory must be a list")
        inventory = []
    observed_rows: list[tuple[str, str]] = []
    for index, ref in enumerate(paths):
        errors.extend(_file_ref_errors(ref, f"{label} phase_evidence[{index}]"))
        if not isinstance(ref, Mapping):
            continue
        path = Path(str(ref.get("path") or ""))
        if not path.is_file():
            continue
        row = inventory[index] if index < len(inventory) else None
        if not isinstance(row, Mapping):
            errors.append(f"{label} phase inventory row {index} is missing or malformed")
        else:
            event_phase = (str(row.get("event_id") or ""), str(row.get("phase") or ""))
            observed_rows.append(event_phase)
            if row.get("evidence") != ref:
                errors.append(f"{label} phase inventory evidence differs at index {index}")
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                if image.width < 320 or image.height < 180:
                    errors.append(f"{label} phase image is below 320x180: {path}")
        except (OSError, UnidentifiedImageError):
            errors.append(f"{label} phase evidence is not a decodable image: {path}")
    if observed_rows != expected_rows:
        errors.append(f"{label} phase evidence inventory is incomplete or misaligned")
    return errors


def _fixture_phase_image(
    direction_id: str, *, event_index: int, phase: str,
) -> Image.Image:
    if direction_id not in DIRECTIONS or phase not in PHASES or event_index < 0:
        raise StyleReelError("Style Reel synthetic phase identity is invalid")
    canvas = Image.new("RGB", (320, 180), (18, 24, 34))
    draw = ImageDraw.Draw(canvas)
    phase_index = PHASES.index(phase)
    if phase == "post_exit":
        return canvas
    if direction_id == "luminous_intelligence":
        draw.ellipse((35 + phase_index * 6, 30, 155, 150), outline="white", width=8)
        draw.line((155, 90, 280, 55 + event_index * 55), fill="cyan", width=8)
    elif direction_id == "high_energy_creator":
        draw.rectangle((25, 25 + phase_index * 5, 130, 155), outline="white", width=8)
        draw.polygon(((160, 150), (220, 25), (295, 150)), outline="orange")
    else:
        draw.line((25, 145, 295, 35 + phase_index * 5), fill="white", width=10)
        draw.rounded_rectangle((145, 45, 285, 135), radius=20, outline="magenta", width=8)
    return canvas


def write_style_reel_fixture_phase_image(
    path: Path, *, direction_id: str, event_index: int, phase: str,
) -> Path:
    """Write the deterministic WP4-only direction fixture; never a real-render claim."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _fixture_phase_image(direction_id, event_index=event_index, phase=phase).save(path)
    return path.resolve()


def _edge_mask(image: Image.Image) -> bytes:
    gray = ImageOps.autocontrast(image.convert("L").resize((96, 54)))
    edges = gray.filter(ImageFilter.FIND_EDGES).crop((2, 2, 94, 52))
    return bytes(255 if value >= 24 else 0 for value in edges.tobytes())


def _phase_structure_observation(
    refs: Sequence[Mapping[str, Any]], label: str, *, direction_id: str | None = None,
) -> tuple[str, list[bytes]]:
    masks: list[bytes] = []
    edge_total = 0
    for index, ref in enumerate(refs):
        path = Path(str(ref.get("path") or ""))
        try:
            with Image.open(path) as image:
                mask = _edge_mask(image)
        except (OSError, UnidentifiedImageError) as error:
            raise StyleReelError(f"{label} phase {index} is not a decodable image") from error
        edge_total += sum(1 for value in mask if value)
        masks.append(mask)
        if direction_id is not None:
            expected = _edge_mask(_fixture_phase_image(
                direction_id, event_index=index // len(PHASES), phase=PHASES[index % len(PHASES)],
            ))
            if mask != expected:
                raise StyleReelError(
                    f"{label} does not match the deterministic direction-specific WP4 fixture"
                )
    if edge_total < 80:
        raise StyleReelError(f"{label} phase evidence has no observable layout structure")
    for offset in range(0, len(masks), len(PHASES)):
        event_masks = masks[offset:offset + len(PHASES)]
        if len(event_masks) != len(PHASES) or len(set(event_masks)) < 3:
            raise StyleReelError(f"{label} phases do not show observable choreography changes")
        mid_edges = sum(1 for value in event_masks[1] if value)
        post_edges = sum(1 for value in event_masks[-1] if value)
        if mid_edges <= 0 or post_edges > max(16, mid_edges * 0.35):
            raise StyleReelError(f"{label} post-exit phase does not show a clean exit")
    return sha256(b"".join(masks)).hexdigest(), masks


def _phase_structure_fingerprint(refs: Sequence[Mapping[str, Any]], label: str) -> str:
    return _phase_structure_observation(refs, label)[0]


def _structure_difference_ratio(left: Sequence[bytes], right: Sequence[bytes]) -> float:
    lhs = b"".join(left)
    rhs = b"".join(right)
    if len(lhs) != len(rhs) or not lhs:
        return 1.0
    return sum(a != b for a, b in zip(lhs, rhs)) / len(lhs)


def _load_direction_contract(path: Path) -> Mapping[str, Any]:
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise StyleReelError(f"Style Reel direction contract is invalid: {path}: {error}") from error
    if not isinstance(payload, Mapping):
        raise StyleReelError(f"Style Reel direction contract must be an object: {path}")
    return payload


def _automated_report_errors(
    report: Any, *, plan_path: Path, inventory: Sequence[Mapping[str, Any]],
) -> list[str]:
    if not isinstance(report, Mapping):
        return ["Style Reel automated report must be a mapping"]
    errors: list[str] = []
    if set(report) != {
        "schema_version", "status", "plan", "comparison_basis_sha256",
        "directions", "checks",
    }:
        errors.append("Style Reel automated report fields are incomplete or unsupported")
    if report.get("schema_version") != 1 or report.get("status") != "pass":
        errors.append("Style Reel automated report is not a pass")
    errors.extend(_file_ref_errors(report.get("plan"), "Style Reel automated plan"))
    plan_ref = report.get("plan") if isinstance(report.get("plan"), Mapping) else {}
    if (
        str(plan_ref.get("path") or "") != str(plan_path.resolve())
        or plan_ref.get("sha256") != sha256_file(plan_path.resolve())
    ):
        errors.append("Style Reel automated plan binding is stale")
    plan = _load_direction_contract(plan_path.resolve())
    if report.get("comparison_basis_sha256") != _basis_hash(plan):
        errors.append("Style Reel automated comparison basis is stale")
    if report.get("directions") != list(inventory):
        errors.append("Style Reel automated direction inventory is stale")
    checks = report.get("checks")
    required_checks = {
        "full_decode", "duration_alignment", "stream_signature",
        "event_alignment", "phase_inventory",
    }
    if not isinstance(checks, Mapping) or set(checks) != required_checks or any(
        checks.get(name) is not True for name in required_checks
    ):
        errors.append("Style Reel automated checks are incomplete or failed")
    return errors


def _basis_hash(plan: Mapping[str, Any]) -> str:
    return _stable_hash(plan.get("comparison_basis"))


def _direction_contract_errors(
    payload: Mapping[str, Any], *, direction_id: str,
    plan: Mapping[str, Any], event_ids: Sequence[str],
    event_decisions: Mapping[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    direction_by_id = {
        str(row.get("direction_id")): row
        for row in plan.get("directions") or [] if isinstance(row, Mapping)
    }
    if payload.get("schema_version") != 1:
        errors.append(f"{direction_id} direction contract schema is invalid")
    if payload.get("direction_id") != direction_id:
        errors.append(f"{direction_id} direction contract ID is stale")
    if payload.get("comparison_basis_sha256") != _basis_hash(plan):
        errors.append(f"{direction_id} direction contract comparison basis is stale")
    if list(payload.get("event_ids") or []) != list(event_ids):
        errors.append(f"{direction_id} direction contract event set is stale")
    expected = direction_by_id.get(direction_id) or {}
    if payload.get("structural_fingerprint") != expected.get("structural_fingerprint"):
        errors.append(f"{direction_id} direction contract structural fingerprint is stale")
    expected_decisions = dict(event_decisions or {event_id: "render" for event_id in event_ids})
    if list(expected_decisions) != list(event_ids):
        errors.append(f"{direction_id} direction contract semantic decision set is stale")
    decision_rows = payload.get("event_decisions")
    if event_decisions is not None:
        expected_rows = [
            {"event_id": event_id, "decision": expected_decisions[event_id]}
            for event_id in event_ids if event_id in expected_decisions
        ]
        if decision_rows != expected_rows:
            errors.append(f"{direction_id} direction contract event decisions are stale")
    render_event_ids = [
        event_id for event_id in event_ids if expected_decisions.get(event_id) == "render"
    ]
    event_recipes = payload.get("event_recipes")
    if not isinstance(event_recipes, list):
        errors.append(f"{direction_id} direction contract event recipes are missing")
    else:
        observed_recipe_ids = [
            str(row.get("event_id") or "")
            for row in event_recipes if isinstance(row, Mapping)
        ]
        if observed_recipe_ids != render_event_ids or len(event_recipes) != len(render_event_ids):
            errors.append(f"{direction_id} direction contract event recipe set is stale")
        allowed_recipes = set(expected.get("recipe_ids") or [])
        for index, row in enumerate(event_recipes):
            if (
                not isinstance(row, Mapping)
                or set(row) != {"event_id", "recipe_id"}
                or row.get("recipe_id") not in allowed_recipes
            ):
                errors.append(f"{direction_id} direction contract event recipe {index} is invalid")
    inventory = payload.get("phase_inventory")
    if not isinstance(inventory, list):
        errors.append(f"{direction_id} direction contract phase inventory is missing")
    else:
        expected_rows = [
            (event_id, phase) for event_id in render_event_ids for phase in PHASES
        ]
        observed_rows = [
            (str(row.get("event_id") or ""), str(row.get("phase") or ""))
            for row in inventory if isinstance(row, Mapping)
        ]
        if observed_rows != expected_rows or len(inventory) != len(expected_rows):
            errors.append(f"{direction_id} direction contract phase inventory is stale")
        for index, row in enumerate(inventory):
            if not isinstance(row, Mapping) or set(row) != {"event_id", "phase", "evidence"}:
                errors.append(f"{direction_id} direction contract phase row {index} is malformed")
            elif _file_ref_errors(row.get("evidence"), f"{direction_id} contract phase[{index}]"):
                errors.append(f"{direction_id} direction contract phase row {index} is stale")
    allowed = {
        "schema_version", "direction_id", "comparison_basis_sha256",
        "event_ids", "event_decisions", "event_recipes", "structural_fingerprint",
        "phase_inventory",
    }
    extra = set(payload) - allowed
    if extra:
        errors.append(f"{direction_id} direction contract has unsupported fields: {sorted(extra)}")
    return errors


def build_style_reel_review(
    *, plan_path: Path, authority_manifest_path: Path,
    media_paths: Mapping[str, Path],
    contract_paths: Mapping[str, Path],
    phase_evidence_paths: Mapping[str, Sequence[Path]],
    automated_report_path: Path, output: Path, authorized_root: Path,
) -> dict[str, Any]:
    plan_path = plan_path.resolve()
    plan = _load_direction_contract(plan_path)
    authority_manifest_path = authority_manifest_path.resolve()
    try:
        authority_manifest = read_json(authority_manifest_path)
    except (OSError, json.JSONDecodeError) as error:
        raise StyleReelError(f"Style Reel authority manifest is invalid: {error}") from error
    authority_errors = validate_style_reel_authority_manifest(
        authority_manifest, plan_path=plan_path,
    )
    if authority_errors:
        raise StyleReelError("Style Reel authorities are stale:\n- " + "\n- ".join(authority_errors))
    basis = plan.get("comparison_basis")
    if not isinstance(basis, Mapping):
        raise StyleReelError("Style Reel plan comparison basis is invalid")
    event_ids = list(basis.get("semantic_event_ids") or [])
    event_decisions = _manifest_semantic_decisions(authority_manifest, event_ids)
    render_event_ids = [
        event_id for event_id in event_ids if event_decisions.get(event_id) == "render"
    ]
    duration = float(basis.get("end_seconds")) - float(basis.get("start_seconds"))
    reels: list[dict[str, Any]] = []
    automated_inventory: list[dict[str, Any]] = []
    comparison_signature: dict[str, Any] | None = None
    observed_structure_fingerprints: list[str] = []
    observed_structure_masks: list[list[bytes]] = []
    fixture_direction_identity = (
        authority_manifest.get("evidence_class") == "synthetic_fixture"
    )
    for direction_id in DIRECTIONS:
        if direction_id not in media_paths or direction_id not in contract_paths:
            raise StyleReelError(f"Style Reel {direction_id} media/contract is missing")
        media = Path(media_paths[direction_id]).resolve()
        contract = Path(contract_paths[direction_id]).resolve()
        observed_duration = _probe_duration(media)
        if abs(observed_duration - duration) > 0.25:
            raise StyleReelError(f"Style Reel {direction_id} duration differs from comparison basis")
        decode_errors = _full_decode(media)
        if decode_errors:
            raise StyleReelError("\n".join(decode_errors))
        signature = _probe_signature(media)
        if comparison_signature is None:
            comparison_signature = signature
        elif signature != comparison_signature:
            raise StyleReelError(
                f"Style Reel {direction_id} codec/canvas/frame-rate/audio signature differs"
            )
        contract_payload = _load_direction_contract(contract)
        contract_errors = _direction_contract_errors(
            contract_payload, direction_id=direction_id, plan=plan, event_ids=event_ids,
            event_decisions=event_decisions,
        )
        if contract_errors:
            raise StyleReelError("\n".join(contract_errors))
        phases = [_file_ref(Path(path)) for path in phase_evidence_paths.get(direction_id, [])]
        phase_errors = _phase_errors(
            phases, render_event_ids, direction_id, contract_payload.get("phase_inventory"),
        )
        if phase_errors:
            raise StyleReelError("\n".join(phase_errors))
        observed_fingerprint, observed_masks = _phase_structure_observation(
            phases, f"Style Reel {direction_id}",
            direction_id=direction_id if fixture_direction_identity else None,
        )
        observed_structure_fingerprints.append(observed_fingerprint)
        observed_structure_masks.append(observed_masks)
        reels.append({
            "direction_id": direction_id,
            "media": _file_ref(media),
            "duration_seconds": round(observed_duration, 6),
            "contract_sha256": sha256_file(contract),
            "event_ids": event_ids,
            "phase_evidence": phases,
        })
        automated_inventory.append({
            "direction_id": direction_id,
            "media": _file_ref(media),
            "contract": _file_ref(contract),
            "phase_evidence": phases,
        })
    if len(set(observed_structure_fingerprints)) != len(DIRECTIONS):
        raise StyleReelError("Style Reel directions do not have observably distinct phase structure")
    if any(
        _structure_difference_ratio(observed_structure_masks[left], observed_structure_masks[right]) < 0.03
        for left in range(len(DIRECTIONS)) for right in range(left + 1, len(DIRECTIONS))
    ):
        raise StyleReelError("Style Reel direction structure differs only by a trivial visual marker")
    report = _load_direction_contract(automated_report_path.resolve())
    report_errors = _automated_report_errors(
        report, plan_path=plan_path, inventory=automated_inventory,
    )
    if report_errors:
        raise StyleReelError("\n".join(report_errors))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "review_id": f"{plan.get('plan_id')}-review",
        "plan": _file_ref(plan_path),
        "reels": reels,
        "automated": {"status": "pass", "report": _file_ref(automated_report_path.resolve())},
        "multimodal": {
            "actor": "not_run", "recommendation": "not_run", "reason": "",
            "evidence_refs": [],
        },
        "user": {
            "actor": "HongRun", "decision": "pending", "format_fit": "pending",
            "person_primary": "pending", "expressive_not_noisy": "pending",
            "semantic_help": "pending", "sonic_fit": "pending",
            "repeat_use_willingness": "pending", "reason": "",
        },
        "status": "pending",
    }
    errors = validate_style_reel_review(
        payload, plan_path=plan_path, authority_manifest_path=authority_manifest_path,
        contract_paths=contract_paths,
    )
    if errors:
        raise StyleReelError("invalid Style Reel review:\n- " + "\n- ".join(errors))
    write_json(_safe_json_output(authorized_root, output), payload)
    return payload


def validate_style_reel_review(
    review: Any, *, plan_path: Path, authority_manifest_path: Path,
    contract_paths: Mapping[str, Path], decision_receipt_path: Path | None = None,
    wp6_review_package_path: Path | None = None,
    pending_review_path: Path | None = None,
) -> list[str]:
    errors = validate_portrait_contract_schema("style-reel-review", review)
    if not isinstance(review, Mapping):
        return errors or ["Style Reel review must be a mapping"]
    plan_path = plan_path.resolve()
    authority_manifest_path = authority_manifest_path.resolve()
    try:
        plan = read_json(plan_path)
    except (OSError, json.JSONDecodeError):
        return errors + ["Style Reel review plan is missing or invalid"]
    if not isinstance(plan, Mapping):
        return errors + ["Style Reel review plan must be a mapping"]
    plan_schema_errors = validate_portrait_contract_schema("style-reel-plan", plan)
    if plan_schema_errors:
        return errors + plan_schema_errors
    try:
        authority_manifest = read_json(authority_manifest_path)
    except (OSError, json.JSONDecodeError):
        errors.append("Style Reel authority manifest is missing or invalid")
    else:
        errors.extend(validate_style_reel_authority_manifest(
            authority_manifest, plan_path=plan_path,
        ))
    evidence_class = (
        authority_manifest.get("evidence_class")
        if isinstance(authority_manifest, Mapping) else None
    )
    try:
        event_decisions = _manifest_semantic_decisions(
            authority_manifest, list(
                (plan.get("comparison_basis") or {}).get("semantic_event_ids") or []
            ),
        ) if isinstance(authority_manifest, Mapping) else {}
    except StyleReelError as error:
        errors.append(str(error))
        event_decisions = {}
    if evidence_class == "synthetic_fixture":
        if review.get("status") != "pending":
            errors.append("synthetic Style Reel review must remain pending and cannot enter the brand gate")
        user_for_fixture = review.get("user")
        if not isinstance(user_for_fixture, Mapping) or user_for_fixture.get("decision") != "pending":
            errors.append("synthetic Style Reel review cannot contain a user decision")
    elif evidence_class == "real_project" and review.get("status") in {"awaiting_user", "approved"}:
        if wp6_review_package_path is None or pending_review_path is None:
            errors.append("real-project Style Reel requires the WP6 transitive HyperFrames evidence validator")
        else:
            errors.extend(validate_wp6_real_style_reel_review_package(
                wp6_review_package_path,
                pending_review_path=pending_review_path,
                plan_path=plan_path,
                authority_manifest_path=authority_manifest_path,
                contract_paths=contract_paths,
            ))
    errors.extend(_file_ref_errors(review.get("plan"), "Style Reel review plan"))
    plan_ref = review.get("plan") if isinstance(review.get("plan"), Mapping) else {}
    if str(plan_ref.get("path") or "") != str(plan_path) or plan_ref.get("sha256") != sha256_file(plan_path):
        errors.append("Style Reel review plan binding is stale")
    basis = plan.get("comparison_basis") if isinstance(plan.get("comparison_basis"), Mapping) else {}
    event_ids = list(basis.get("semantic_event_ids") or [])
    render_event_ids = [
        event_id for event_id in event_ids if event_decisions.get(event_id, "render") == "render"
    ]
    basis_start = _finite(basis.get("start_seconds"))
    basis_end = _finite(basis.get("end_seconds"))
    if basis_start is None or basis_end is None or basis_end <= basis_start:
        return errors + ["Style Reel context comparison basis timing is invalid"]
    expected_duration = basis_end - basis_start
    reels = review.get("reels")
    if not isinstance(reels, list):
        return errors + ["Style Reel review reels must be a list"]
    if [row.get("direction_id") for row in reels if isinstance(row, Mapping)] != list(DIRECTIONS):
        errors.append("Style Reel review direction order differs from plan")
    media_hashes: set[str] = set()
    automated_inventory: list[dict[str, Any]] = []
    comparison_signature: dict[str, Any] | None = None
    observed_structure_fingerprints: list[str] = []
    observed_structure_masks: list[list[bytes]] = []
    for index, direction_id in enumerate(DIRECTIONS):
        if index >= len(reels) or not isinstance(reels[index], Mapping):
            errors.append(f"Style Reel review {direction_id} reel is missing or malformed")
            continue
        reel = reels[index]
        errors.extend(_file_ref_errors(reel.get("media"), f"Style Reel {direction_id} media"))
        media_ref = reel.get("media") if isinstance(reel.get("media"), Mapping) else {}
        media_path = Path(str(media_ref.get("path") or ""))
        if media_path.is_file():
            try:
                observed_duration = _probe_duration(media_path)
            except StyleReelError as error:
                errors.append(str(error))
            else:
                declared_duration = _finite(reel.get("duration_seconds"))
                if (
                    declared_duration is None
                    or abs(observed_duration - expected_duration) > 0.25
                    or abs(declared_duration - observed_duration) > 0.01
                ):
                    errors.append(f"Style Reel {direction_id} media duration is stale")
                errors.extend(_full_decode(media_path))
            try:
                signature = _probe_signature(media_path)
            except StyleReelError as error:
                errors.append(str(error))
            else:
                if comparison_signature is None:
                    comparison_signature = signature
                elif signature != comparison_signature:
                    errors.append(
                        f"Style Reel {direction_id} codec/canvas/frame-rate/audio signature differs"
                    )
        digest = str(media_ref.get("sha256") or "")
        if digest in media_hashes:
            errors.append("Style Reel direction media bytes must be distinct")
        media_hashes.add(digest)
        if list(reel.get("event_ids") or []) != event_ids:
            errors.append(f"Style Reel {direction_id} event set differs from plan")
        contract_path = Path(contract_paths.get(direction_id, Path(""))).resolve()
        contract_for_phases: Mapping[str, Any] | None = None
        if not contract_path.is_file():
            errors.append(f"Style Reel {direction_id} contract is missing")
        else:
            try:
                contract = _load_direction_contract(contract_path)
            except StyleReelError as error:
                errors.append(str(error))
            else:
                contract_for_phases = contract
                errors.extend(_direction_contract_errors(
                    contract, direction_id=direction_id, plan=plan, event_ids=event_ids,
                    event_decisions=event_decisions or None,
                ))
            if reel.get("contract_sha256") != sha256_file(contract_path):
                errors.append(f"Style Reel {direction_id} contract hash is stale")
        errors.extend(_phase_errors(
            reel.get("phase_evidence"), render_event_ids, f"Style Reel {direction_id}",
            contract_for_phases.get("phase_inventory") if contract_for_phases else None,
        ))
        phase_refs = reel.get("phase_evidence")
        if isinstance(phase_refs, list) and all(isinstance(ref, Mapping) for ref in phase_refs):
            try:
                observed_fingerprint, observed_masks = _phase_structure_observation(
                    phase_refs, f"Style Reel {direction_id}",
                    direction_id=direction_id if evidence_class == "synthetic_fixture" else None,
                )
                observed_structure_fingerprints.append(observed_fingerprint)
                observed_structure_masks.append(observed_masks)
            except StyleReelError as error:
                errors.append(str(error))
        if contract_path.is_file():
            automated_inventory.append({
                "direction_id": direction_id,
                "media": dict(media_ref),
                "contract": _file_ref(contract_path),
                "phase_evidence": list(reel.get("phase_evidence") or []),
            })
    if (
        len(observed_structure_fingerprints) != len(DIRECTIONS)
        or len(set(observed_structure_fingerprints)) != len(DIRECTIONS)
    ):
        errors.append("Style Reel directions do not have observably distinct phase structure")
    elif any(
        _structure_difference_ratio(observed_structure_masks[left], observed_structure_masks[right]) < 0.03
        for left in range(len(DIRECTIONS)) for right in range(left + 1, len(DIRECTIONS))
    ):
        errors.append("Style Reel direction structure differs only by a trivial visual marker")
    automated = review.get("automated")
    if not isinstance(automated, Mapping):
        errors.append("Style Reel automated evidence must be a mapping")
    else:
        errors.extend(_file_ref_errors(automated.get("report"), "Style Reel automated report"))
        report_ref = automated.get("report") if isinstance(automated.get("report"), Mapping) else {}
        report_path = Path(str(report_ref.get("path") or ""))
        if report_path.is_file():
            try:
                report = read_json(report_path)
            except (OSError, json.JSONDecodeError):
                errors.append("Style Reel automated report is invalid JSON")
            else:
                errors.extend(_automated_report_errors(
                    report, plan_path=plan_path, inventory=automated_inventory,
                ))
        if automated.get("status") != "pass":
            errors.append("Style Reel automated status must pass before user review")
    user = review.get("user")
    if not isinstance(user, Mapping) or user.get("actor") != "HongRun":
        errors.append("Style Reel brand decision actor must be HongRun")
    if review.get("status") == "approved":
        if not isinstance(user, Mapping) or user.get("decision") != "select":
            errors.append("approved Style Reel requires HongRun selection")
        else:
            for field, _ in USER_QUESTIONS:
                accepted = {"yes", "not_applicable"} if field == "sonic_fit" else {"yes"}
                if user.get(field) not in accepted:
                    errors.append(f"approved Style Reel requires {field}=yes")
            if user.get("selected_direction_id") not in DIRECTIONS:
                errors.append("approved Style Reel selection is invalid")
            if not str(user.get("reason") or "").strip() or not str(user.get("reviewed_at") or "").strip():
                errors.append("approved Style Reel requires reason and reviewed_at")
        if decision_receipt_path is None:
            errors.append("approved Style Reel requires an explicit hash-bound user-decision receipt")
        else:
            try:
                decision_receipt = _read_mapping(
                    decision_receipt_path.resolve(), "Style Reel user-decision receipt",
                )
            except StyleReelError as error:
                errors.append(str(error))
            else:
                errors.extend(validate_style_reel_user_decision_receipt(
                    decision_receipt, review=review, plan_path=plan_path,
                    authority_manifest_path=authority_manifest_path,
                    contract_paths=contract_paths,
                    wp6_review_package_path=wp6_review_package_path,
                ))
    return errors


def validate_wp6_real_style_reel_review_package(
    package_path: Path, *, pending_review_path: Path, plan_path: Path,
    authority_manifest_path: Path, contract_paths: Mapping[str, Path],
) -> list[str]:
    """Revalidate the immutable WP6 user-review package and its transitive refs."""
    errors: list[str] = []
    try:
        package_path = Path(package_path).resolve()
        pending_review_path = Path(pending_review_path).resolve()
        package = _read_mapping(package_path, "WP6 real Style Reel review package")
    except (TypeError, StyleReelError) as error:
        return [str(error)]
    required = {
        "schema_version", "status", "kind", "window_confirmation",
        "technical_evidence", "review", "context", "dashboard",
        "dashboard_manifest", "contracts", "full_video_render_authorized",
    }
    if set(package) != required:
        errors.append("WP6 real Style Reel review package fields are incomplete or unsupported")
    if (
        package.get("schema_version") != 1
        or package.get("status") != "awaiting_user"
        or package.get("kind") != "wp6_real_style_reel_review_package"
        or package.get("full_video_render_authorized") is not False
    ):
        errors.append("WP6 real Style Reel review package identity/status is invalid")
    for field in (
        "window_confirmation", "technical_evidence", "review", "context",
        "dashboard", "dashboard_manifest",
    ):
        errors.extend(_file_ref_errors(package.get(field), f"WP6 Style Reel {field}"))
    review_ref = package.get("review") if isinstance(package.get("review"), Mapping) else {}
    if (
        str(review_ref.get("path") or "") != str(pending_review_path)
        or review_ref.get("sha256") != (
            sha256_file(pending_review_path) if pending_review_path.is_file() else None
        )
    ):
        errors.append("WP6 Style Reel pending review binding is stale")
    contracts = package.get("contracts")
    if not isinstance(contracts, Mapping):
        errors.append("WP6 Style Reel contract inventory must be a mapping")
    elif not isinstance(contract_paths, Mapping) or any(
        direction not in contract_paths for direction in DIRECTIONS
    ):
        errors.append("WP6 Style Reel expected contract inventory is incomplete")
    else:
        expected_contracts = {
            direction: _file_ref(Path(contract_paths[direction]).resolve())
            for direction in DIRECTIONS
        }
        if contracts != expected_contracts:
            errors.append("WP6 Style Reel contract inventory is stale")

    technical_ref = package.get("technical_evidence")
    if isinstance(technical_ref, Mapping):
        technical_path = Path(str(technical_ref.get("path") or ""))
        if technical_path.is_file():
            try:
                technical = _read_mapping(technical_path, "WP6 Style Reel technical evidence")
            except StyleReelError as error:
                errors.append(str(error))
            else:
                checks = technical.get("checks")
                required_checks = {
                    "full_decode": True, "duration_alignment": True,
                    "stream_signature": True, "hyperframes_checks": True,
                    "post_exit_clean": True, "caption_last": True,
                }
                if (
                    technical.get("schema_version") != 1
                    or technical.get("status") != "pass"
                    or technical.get("kind") != "wp6_real_style_reel_technical_evidence"
                    or not isinstance(checks, Mapping)
                    or any(checks.get(key) is not value for key, value in required_checks.items())
                ):
                    errors.append("WP6 Style Reel technical evidence is not a current pass")
                try:
                    pending = _read_mapping(pending_review_path, "WP6 pending Style Reel review")
                except StyleReelError as error:
                    errors.append(str(error))
                else:
                    expected_media = {
                        row.get("direction_id"): row.get("media")
                        for row in pending.get("reels") or [] if isinstance(row, Mapping)
                    }
                    observed_media = {
                        row.get("direction_id"): row.get("media")
                        for row in technical.get("directions") or [] if isinstance(row, Mapping)
                    }
                    if expected_media != observed_media:
                        errors.append("WP6 Style Reel technical media inventory differs from review")

    confirmation_ref = package.get("window_confirmation")
    if isinstance(confirmation_ref, Mapping):
        confirmation_path = Path(str(confirmation_ref.get("path") or ""))
        if confirmation_path.is_file():
            try:
                confirmation = _read_mapping(
                    confirmation_path, "WP6 Style Reel window confirmation",
                )
            except StyleReelError as error:
                errors.append(str(error))
            else:
                errors.extend(validate_style_reel_window_confirmation(
                    confirmation, plan_path=Path(plan_path).resolve(),
                    authority_manifest_path=Path(authority_manifest_path).resolve(),
                ))

    context_ref = package.get("context")
    if isinstance(context_ref, Mapping):
        context_path = Path(str(context_ref.get("path") or ""))
        if context_path.is_file():
            try:
                context = _read_mapping(context_path, "WP6 Style Reel context")
            except StyleReelError as error:
                errors.append(str(error))
            else:
                errors.extend(validate_style_reel_context(
                    context, plan_path=Path(plan_path).resolve(),
                    authority_manifest_path=Path(authority_manifest_path).resolve(),
                    review_path=pending_review_path, contract_paths=contract_paths,
                ))
    return errors


def validate_style_reel_user_decision_receipt(
    receipt: Any, *, review: Mapping[str, Any], plan_path: Path,
    authority_manifest_path: Path, contract_paths: Mapping[str, Path],
    wp6_review_package_path: Path | None = None,
) -> list[str]:
    errors = _integrity_errors(receipt, "Style Reel user-decision receipt")
    if not isinstance(receipt, Mapping):
        return errors
    if not isinstance(review, Mapping):
        return errors + ["Style Reel decision review must be a mapping"]
    if (
        not isinstance(contract_paths, Mapping)
        or any(direction not in contract_paths for direction in DIRECTIONS)
    ):
        return errors + ["Style Reel decision contract path inventory is incomplete"]
    required = {
        "schema_version", "kind", "actor", "confirmation_method", "pending_review",
        "plan", "authority_manifest", "wp6_review_package", "contracts", "reels", "user_decision",
        "decided_at", "integrity_sha256",
    }
    if set(receipt) != required:
        errors.append("Style Reel user-decision receipt fields are incomplete or unsupported")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "portrait_style_reel_user_decision"
        or receipt.get("actor") != "HongRun"
        or receipt.get("confirmation_method") != "explicit_user_confirmation_hash_v1"
    ):
        errors.append("Style Reel user-decision receipt identity is invalid")
    errors.extend(_file_ref_errors(
        receipt.get("pending_review"), "Style Reel decision pending review",
    ))
    errors.extend(_file_ref_errors(
        receipt.get("wp6_review_package"), "Style Reel decision WP6 review package",
    ))
    package_ref = (
        receipt.get("wp6_review_package")
        if isinstance(receipt.get("wp6_review_package"), Mapping) else {}
    )
    if wp6_review_package_path is None:
        errors.append("Style Reel decision requires the current WP6 review package")
    else:
        expected_package = Path(wp6_review_package_path).resolve()
        if (
            str(package_ref.get("path") or "") != str(expected_package)
            or package_ref.get("sha256") != (
                sha256_file(expected_package) if expected_package.is_file() else None
            )
        ):
            errors.append("Style Reel decision WP6 review package binding is stale")
        pending_ref = receipt.get("pending_review")
        pending_path = Path(str(
            pending_ref.get("path") if isinstance(pending_ref, Mapping) else ""
        ))
        errors.extend(validate_wp6_real_style_reel_review_package(
            expected_package, pending_review_path=pending_path,
            plan_path=plan_path, authority_manifest_path=authority_manifest_path,
            contract_paths=contract_paths,
        ))
    for field, expected in (("plan", plan_path.resolve()), ("authority_manifest", authority_manifest_path.resolve())):
        errors.extend(_file_ref_errors(receipt.get(field), f"Style Reel decision {field}"))
        ref = receipt.get(field) if isinstance(receipt.get(field), Mapping) else {}
        if str(ref.get("path") or "") != str(expected):
            errors.append(f"Style Reel decision {field} path is stale")
    if authority_manifest_path.is_file():
        try:
            manifest = _read_mapping(
                authority_manifest_path.resolve(), "Style Reel decision authority manifest",
            )
        except StyleReelError as error:
            errors.append(str(error))
        else:
            errors.extend(validate_style_reel_authority_manifest(
                manifest, plan_path=plan_path.resolve(),
            ))
            if manifest.get("evidence_class") != "real_project":
                errors.append("Style Reel decision requires real-project evidence")
    expected_contracts = {
        direction: _file_ref(Path(contract_paths[direction]).resolve()) for direction in DIRECTIONS
    }
    if receipt.get("contracts") != expected_contracts:
        errors.append("Style Reel decision contract inventory is stale")
    expected_reels = [row.get("media") for row in review.get("reels") or [] if isinstance(row, Mapping)]
    if receipt.get("reels") != expected_reels:
        errors.append("Style Reel decision media inventory is stale")
    if receipt.get("user_decision") != review.get("user"):
        errors.append("Style Reel decision answers differ from the approved review")
    return errors


def record_style_reel_user_decision(
    review: Mapping[str, Any], *, actor: str, decision: str,
    selected_direction_id: str | None, answers: Mapping[str, str], reason: str,
    pending_review_path: Path | None = None, plan_path: Path | None = None,
    authority_manifest_path: Path | None = None, contract_paths: Mapping[str, Path] | None = None,
    decision_receipt_output: Path | None = None, authorized_root: Path | None = None,
    wp6_review_package_path: Path | None = None,
) -> dict[str, Any]:
    if actor != "HongRun":
        raise StyleReelError("only HongRun can decide the portrait Style Reel brand gate")
    if decision not in {"select", "revise", "reject_all"}:
        raise StyleReelError("Style Reel decision must be select, revise, or reject_all")
    if decision == "select" and selected_direction_id not in DIRECTIONS:
        raise StyleReelError("Style Reel selection must name one frozen direction")
    if not isinstance(review, Mapping):
        raise StyleReelError("Style Reel decision review must be a mapping")
    if not isinstance(answers, Mapping):
        raise StyleReelError("Style Reel decision answers must be a mapping")
    if not isinstance(reason, str) or not reason.strip():
        raise StyleReelError("Style Reel decision requires a reason")
    if (
        pending_review_path is None or plan_path is None or authority_manifest_path is None
        or contract_paths is None or decision_receipt_output is None or authorized_root is None
    ):
        raise StyleReelError(
            "Style Reel decision requires current pending review, plan, authorities, contracts, and receipt output"
        )
    pending_review_path = pending_review_path.resolve()
    pending_on_disk = _read_mapping(pending_review_path, "Style Reel pending review")
    if dict(pending_on_disk) != dict(review):
        raise StyleReelError("Style Reel pending review bytes differ from the decision input")
    authority_manifest = _read_mapping(
        authority_manifest_path.resolve(), "Style Reel authority manifest",
    )
    if authority_manifest.get("evidence_class") != "real_project":
        raise StyleReelError("synthetic fixture reviews cannot be approved as HongRun brand taste")
    if review.get("status") not in {"pending", "awaiting_user"} or (
        not isinstance(review.get("user"), Mapping)
        or review["user"].get("decision") != "pending"
    ):
        raise StyleReelError("Style Reel decision requires a current awaiting-user review")
    current_errors = validate_style_reel_review(
        review, plan_path=plan_path, authority_manifest_path=authority_manifest_path,
        contract_paths=contract_paths,
    )
    if current_errors:
        raise StyleReelError(
            "Style Reel evidence is stale and cannot be decided:\n- "
            + "\n- ".join(current_errors)
        )
    if wp6_review_package_path is None:
        raise StyleReelError("Style Reel decision requires the current WP6 review package")
    package_errors = validate_wp6_real_style_reel_review_package(
        wp6_review_package_path,
        pending_review_path=pending_review_path,
        plan_path=plan_path,
        authority_manifest_path=authority_manifest_path,
        contract_paths=contract_paths,
    )
    if package_errors:
        raise StyleReelError(
            "Style Reel WP6 evidence is stale and cannot be decided:\n- "
            + "\n- ".join(package_errors)
        )
    payload = deepcopy(dict(review))
    user = {
        "actor": "HongRun", "decision": decision,
        **{field: str(answers.get(field) or "pending") for field, _ in USER_QUESTIONS},
        "reason": reason.strip(), "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if decision == "select":
        user["selected_direction_id"] = selected_direction_id
        for field, _ in USER_QUESTIONS:
            accepted = {"yes", "not_applicable"} if field == "sonic_fit" else {"yes"}
            if user[field] not in accepted:
                raise StyleReelError(f"Style Reel selection requires {field}=yes")
    payload["user"] = user
    payload["status"] = {
        "select": "approved", "revise": "revision_requested", "reject_all": "rejected",
    }[decision]
    payload.pop("stale_reasons", None)
    receipt = _integrity_payload({
        "schema_version": 1,
        "kind": "portrait_style_reel_user_decision",
        "actor": "HongRun",
        "confirmation_method": "explicit_user_confirmation_hash_v1",
        "pending_review": _file_ref(pending_review_path),
        "wp6_review_package": _file_ref(Path(wp6_review_package_path).resolve()),
        "plan": _file_ref(plan_path.resolve()),
        "authority_manifest": _file_ref(authority_manifest_path.resolve()),
        "contracts": {
            direction: _file_ref(Path(contract_paths[direction]).resolve())
            for direction in DIRECTIONS
        },
        "reels": [row.get("media") for row in review.get("reels") or [] if isinstance(row, Mapping)],
        "user_decision": deepcopy(user),
        "decided_at": user["reviewed_at"],
    })
    write_json(_safe_json_output(authorized_root, decision_receipt_output), receipt)
    return payload


def mark_style_reel_stale(review: Mapping[str, Any], reasons: Sequence[str]) -> dict[str, Any]:
    if not isinstance(review, Mapping):
        raise StyleReelError("Style Reel stale review must be a mapping")
    payload = deepcopy(dict(review))
    payload["status"] = "stale"
    # The frozen review schema intentionally has no free-form invalidation field.
    # Callers retain validator errors in the stage/action-required receipt; the
    # review itself remains schema-valid and only clears the subjective decision.
    del reasons
    payload["user"] = {
        "actor": "HongRun", "decision": "pending", "format_fit": "pending",
        "person_primary": "pending", "expressive_not_noisy": "pending",
        "semantic_help": "pending", "sonic_fit": "pending",
        "repeat_use_willingness": "pending", "reason": "",
    }
    return payload


def _uri(ref: Any) -> str:
    if not isinstance(ref, Mapping):
        return ""
    path = Path(str(ref.get("path") or ""))
    return path.resolve().as_uri() if path.is_file() else ""


def _validated_interactive_api_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if (
        parsed.scheme != "http" or not loopback or parsed.path != "/api/proposals"
        or parsed.query or parsed.fragment or parsed.username or parsed.password
    ):
        raise StyleReelError("Style Reel interactive API must be an http loopback /api/proposals URL")
    return value


def _canonical_style_reel_audio_decision(
    *, authorities: Mapping[str, Any], event_id: str,
) -> tuple[Mapping[str, Any], dict[str, str]]:
    required = ("audio_plan", "sonic_plan", "motion_contracts", "storyboard")
    refs = {name: authorities.get(name) for name in required}
    if any(not isinstance(refs[name], Mapping) for name in required):
        raise StyleReelError("Style Reel canonical portrait audio authorities are incomplete")
    paths = {name: Path(str(refs[name]["path"])).resolve() for name in required}
    sonic_plan = _read_mapping(paths["sonic_plan"], "Style Reel portrait sonic plan")
    audio_plan = _read_mapping(paths["audio_plan"], "Style Reel projected audio plan")
    storyboard = _read_mapping(paths["storyboard"], "Style Reel storyboard")
    schema_errors = validate_portrait_contract_schema("portrait-sonic-plan", sonic_plan)
    if schema_errors:
        raise StyleReelError("Style Reel portrait sonic plan is invalid: " + "; ".join(schema_errors))
    try:
        portrait_sonic_plan_artifacts(sonic_plan)
    except (PortraitSonicError, OSError, ValueError) as error:
        raise StyleReelError(f"Style Reel portrait sonic authority chain is stale: {error}") from error
    projection_errors = validate_portrait_sonic_projection(
        sonic_plan, audio_plan, base_dir=paths["audio_plan"].parent,
        motion_contracts_path=paths["motion_contracts"], storyboard=storyboard,
    )
    if projection_errors:
        raise StyleReelError(
            "Style Reel projected audio plan is stale:\n- " + "\n- ".join(projection_errors)
        )
    motion_sfx = audio_plan.get("motion_sfx")
    decisions = motion_sfx.get("event_decisions") if isinstance(motion_sfx, Mapping) else None
    matches = [
        row for row in decisions or []
        if isinstance(row, Mapping)
        and str(row.get("semantic_event_id") or row.get("event_id") or "") == event_id
    ] if isinstance(decisions, list) else []
    if len(matches) != 1 or matches[0].get("decision") != "cue":
        raise StyleReelError("Style Reel audition requires one canonical WP3 cue decision")
    decision = matches[0]
    raw_asset = decision.get("asset")
    if not isinstance(raw_asset, str) or not raw_asset.strip() or Path(raw_asset).is_absolute():
        raise StyleReelError("Style Reel canonical cue asset must be a project-relative path")
    cue_path = (paths["audio_plan"].parent / raw_asset).resolve()
    try:
        authorized_root = authorized_portrait_sfx_root(paths["audio_plan"].parent)
    except PortraitSonicError as error:
        raise StyleReelError(f"Style Reel canonical SFX root is unauthorized: {error}") from error
    if not cue_path.is_relative_to(authorized_root):
        raise StyleReelError("Style Reel canonical cue asset escapes the authorized SFX root")
    return decision, _file_ref(cue_path)


def validate_style_reel_audition_receipt(
    receipt: Any, *, plan_path: Path, authority_manifest_path: Path,
    event_id: str,
) -> list[str]:
    if not isinstance(receipt, Mapping):
        return ["Style Reel audition receipt must be a mapping"]
    errors: list[str] = []
    allowed = {
        "schema_version", "kind", "status", "event_id", "plan", "authority_manifest",
        "comparison_basis_sha256", "voice_stem", "audio_policy", "voice_sfx_off",
        "sfx_on", "output_start_seconds", "measurements", "audio_plan", "sonic_plan",
        "cue_decision", "cue_asset",
    }
    if set(receipt) != allowed:
        errors.append("Style Reel audition receipt fields are incomplete or unsupported")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "portrait_style_reel_event_audition"
        or receipt.get("status") != "pass"
        or receipt.get("event_id") != event_id
    ):
        errors.append("Style Reel audition receipt identity/status is invalid")
    plan_path = plan_path.resolve()
    authority_manifest_path = authority_manifest_path.resolve()
    for field, expected in (("plan", plan_path), ("authority_manifest", authority_manifest_path)):
        errors.extend(_file_ref_errors(receipt.get(field), f"Style Reel audition {field}"))
        ref = receipt.get(field) if isinstance(receipt.get(field), Mapping) else {}
        if str(ref.get("path") or "") != str(expected):
            errors.append(f"Style Reel audition {field} path is stale")
    try:
        plan = _read_mapping(plan_path, "Style Reel audition plan")
        manifest = _read_mapping(authority_manifest_path, "Style Reel audition authority manifest")
    except StyleReelError as error:
        return errors + [str(error)]
    errors.extend(validate_style_reel_authority_manifest(manifest, plan_path=plan_path))
    if receipt.get("comparison_basis_sha256") != _basis_hash(plan):
        errors.append("Style Reel audition comparison basis is stale")
    authorities = manifest.get("authorities") if isinstance(manifest.get("authorities"), Mapping) else {}
    voice_ref = authorities.get("voice_stem") if isinstance(authorities, Mapping) else None
    policy_ref = authorities.get("audio_policy") if isinstance(authorities, Mapping) else None
    audio_plan_ref = authorities.get("audio_plan") if isinstance(authorities, Mapping) else None
    sonic_plan_ref = authorities.get("sonic_plan") if isinstance(authorities, Mapping) else None
    if receipt.get("voice_stem") != voice_ref or receipt.get("audio_policy") != policy_ref:
        errors.append("Style Reel audition voice/audio policy authority is stale")
    if receipt.get("audio_plan") != audio_plan_ref or receipt.get("sonic_plan") != sonic_plan_ref:
        errors.append("Style Reel audition audio/sonic plan authority is stale")
    off_ref = receipt.get("voice_sfx_off")
    on_ref = receipt.get("sfx_on")
    errors.extend(_file_ref_errors(off_ref, "Style Reel audition voice/SFX-off"))
    errors.extend(_file_ref_errors(on_ref, "Style Reel audition SFX-on"))
    basis = plan.get("comparison_basis") if isinstance(plan.get("comparison_basis"), Mapping) else {}
    semantic_ref = authorities.get("semantic_brief") if isinstance(authorities, Mapping) else None
    semantic_path = Path(str((semantic_ref or {}).get("path") or "")) if isinstance(semantic_ref, Mapping) else Path("")
    try:
        semantic_row = _semantic_rows(semantic_path).get(event_id)
    except StyleReelError as error:
        return errors + [str(error)]
    output_start = _finite(semantic_row.get("output_start")) if isinstance(semantic_row, Mapping) else None
    declared_start = _finite(receipt.get("output_start_seconds"))
    if output_start is None or declared_start != output_start:
        errors.append("Style Reel audition event window is stale")
    decision: Mapping[str, Any] | None = None
    cue_ref: dict[str, str] | None = None
    try:
        decision, cue_ref = _canonical_style_reel_audio_decision(
            authorities=authorities, event_id=event_id,
        )
    except StyleReelError as error:
        errors.append(str(error))
    if decision is not None and receipt.get("cue_decision") != dict(decision):
        errors.append("Style Reel audition cue decision is stale")
    if (
        decision is not None
        and (decision.get("decision") != "cue" or _finite(decision.get("start")) is None)
    ):
        errors.append("Style Reel audition cue decision timing/type is stale")
    if receipt.get("cue_asset") != cue_ref:
        errors.append("Style Reel audition cue asset is stale")
    if errors:
        return errors
    try:
        observed = _audition_measurements(
            voice_stem=Path(str(voice_ref["path"])),
            off_path=Path(str(off_ref["path"])),
            on_path=Path(str(on_ref["path"])),
            output_start_seconds=float(output_start),
            cue_path=Path(str(cue_ref["path"])),
            cue_volume=float(decision["volume"]),
            cue_start_seconds=float(decision["start"]),
            cue_duration_seconds=float(decision["duration_seconds"]),
        )
    except (StyleReelError, KeyError, TypeError, ValueError) as error:
        return errors + [str(error)]
    if receipt.get("measurements") != observed:
        errors.append("Style Reel audition measurements are stale")
    basis_start = _finite(basis.get("start_seconds"))
    basis_end = _finite(basis.get("end_seconds"))
    if basis_start is None or basis_end is None or basis_end <= basis_start:
        return errors + ["Style Reel audition comparison basis timing is invalid"]
    if output_start < basis_start or output_start > basis_end:
        errors.append("Style Reel audition event is outside the comparison basis")
    return errors


def build_style_reel_audition_receipt(
    *, plan_path: Path, authority_manifest_path: Path, event_id: str,
    voice_sfx_off_path: Path, sfx_on_path: Path,
    output: Path, authorized_root: Path,
) -> dict[str, Any]:
    plan_path = plan_path.resolve()
    authority_manifest_path = authority_manifest_path.resolve()
    plan = _read_mapping(plan_path, "Style Reel audition plan")
    manifest = _read_mapping(authority_manifest_path, "Style Reel audition authority manifest")
    authority_errors = validate_style_reel_authority_manifest(manifest, plan_path=plan_path)
    if authority_errors:
        raise StyleReelError("Style Reel audition authorities are stale:\n- " + "\n- ".join(authority_errors))
    authorities = manifest.get("authorities") if isinstance(manifest.get("authorities"), Mapping) else {}
    voice_ref = authorities.get("voice_stem") if isinstance(authorities, Mapping) else None
    policy_ref = authorities.get("audio_policy") if isinstance(authorities, Mapping) else None
    audio_plan_ref = authorities.get("audio_plan") if isinstance(authorities, Mapping) else None
    sonic_plan_ref = authorities.get("sonic_plan") if isinstance(authorities, Mapping) else None
    if not all(isinstance(ref, Mapping) for ref in (voice_ref, policy_ref, audio_plan_ref, sonic_plan_ref)):
        raise StyleReelError("Style Reel audition voice/audio authorities are missing")
    decision, cue_ref = _canonical_style_reel_audio_decision(
        authorities=authorities, event_id=event_id,
    )
    semantic_ref = authorities.get("semantic_brief")
    semantic_path = Path(str((semantic_ref or {}).get("path") or "")) if isinstance(semantic_ref, Mapping) else Path("")
    semantic_row = _semantic_rows(semantic_path).get(event_id)
    output_start = _finite(semantic_row.get("output_start")) if isinstance(semantic_row, Mapping) else None
    if output_start is None or event_id not in list((plan.get("comparison_basis") or {}).get("semantic_event_ids") or []):
        raise StyleReelError("Style Reel audition event is outside the current semantic plan")
    off_path = voice_sfx_off_path.resolve()
    on_path = sfx_on_path.resolve()
    payload = {
        "schema_version": 1,
        "kind": "portrait_style_reel_event_audition",
        "status": "pass",
        "event_id": event_id,
        "plan": _file_ref(plan_path),
        "authority_manifest": _file_ref(authority_manifest_path),
        "comparison_basis_sha256": _basis_hash(plan),
        "voice_stem": dict(voice_ref),
        "audio_policy": dict(policy_ref),
        "audio_plan": dict(audio_plan_ref),
        "sonic_plan": dict(sonic_plan_ref),
        "cue_decision": dict(decision),
        "cue_asset": dict(cue_ref),
        "voice_sfx_off": _file_ref(off_path),
        "sfx_on": _file_ref(on_path),
        "output_start_seconds": output_start,
        "measurements": _audition_measurements(
            voice_stem=Path(str(voice_ref["path"])), off_path=off_path,
            on_path=on_path, output_start_seconds=output_start,
            cue_path=Path(str(cue_ref["path"])),
            cue_volume=float(decision["volume"]),
            cue_start_seconds=float(decision["start"]),
            cue_duration_seconds=float(decision["duration_seconds"]),
        ),
    }
    errors = validate_style_reel_audition_receipt(
        payload, plan_path=plan_path, authority_manifest_path=authority_manifest_path,
        event_id=event_id,
    )
    if errors:
        raise StyleReelError("invalid Style Reel audition receipt:\n- " + "\n- ".join(errors))
    write_json(_safe_json_output(authorized_root, output), payload)
    return payload


def _context_approved_copy_errors(
    copy_values: Any, *, expected_decision: str | None, event_index: int,
) -> list[str]:
    label = f"Style Reel context event {event_index}"
    if expected_decision in {"reuse_source", "quiet_source"}:
        if copy_values not in (None, []):
            return [f"{label} non-render event must not invent approved visible copy"]
        return []
    if expected_decision != "render":
        return [f"{label} visible-copy decision authority is invalid"]
    if not isinstance(copy_values, list) or not copy_values or any(
        not isinstance(value, str) or not value.strip() for value in copy_values
    ):
        return [f"{label} approved copy is invalid"]
    return []


def _context_audio_audition_errors(
    auditions: Any, *, expected_decision: str | None, event_index: int,
    plan_path: Path, authority_manifest_path: Path, event_id: str,
) -> list[str]:
    label = f"Style Reel context event {event_index}"
    if expected_decision in {"reuse_source", "quiet_source"}:
        if not isinstance(auditions, Mapping) or set(auditions) != {"status", "reason"}:
            return [f"{label} non-render audio must be explicitly not_applicable"]
        errors: list[str] = []
        if auditions.get("status") != "not_applicable":
            errors.append(f"{label} non-render audio status must be not_applicable")
        reason = auditions.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{label} non-render audio reason is required")
        return errors
    if expected_decision != "render":
        return [f"{label} audio decision authority is invalid"]

    required_auditions = {"voice_sfx_off", "sfx_on", "receipt"}
    if (
        not isinstance(auditions, Mapping)
        or not required_auditions.issubset(auditions)
        or set(auditions) - (required_auditions | {"bgm_on"})
    ):
        return [f"{label} audio auditions must be a mapping"]
    errors = []
    for name, ref in auditions.items():
        errors.extend(_file_ref_errors(ref, f"{label} audio {name}"))
    receipt_ref = auditions.get("receipt")
    receipt_path = (
        Path(str((receipt_ref or {}).get("path") or ""))
        if isinstance(receipt_ref, Mapping) else Path("")
    )
    if receipt_path.is_file():
        try:
            audition_receipt = read_json(receipt_path)
        except (OSError, json.JSONDecodeError):
            errors.append(f"{label} audition receipt is invalid")
        else:
            errors.extend(validate_style_reel_audition_receipt(
                audition_receipt, plan_path=plan_path,
                authority_manifest_path=authority_manifest_path,
                event_id=event_id,
            ))
            if isinstance(audition_receipt, Mapping):
                if auditions.get("voice_sfx_off") != audition_receipt.get("voice_sfx_off"):
                    errors.append(f"{label} displayed off audition is stale")
                if auditions.get("sfx_on") != audition_receipt.get("sfx_on"):
                    errors.append(f"{label} displayed on audition is stale")
    return errors


def validate_style_reel_context(
    context: Any, *, plan_path: Path, authority_manifest_path: Path,
    review_path: Path, contract_paths: Mapping[str, Path],
) -> list[str]:
    if not isinstance(context, Mapping):
        return ["Style Reel review context must be a mapping"]
    errors: list[str] = []
    allowed = {
        "schema_version", "plan", "authority_manifest", "review", "comparison_basis_sha256",
        "baseline_media", "baseline_duration_seconds", "events",
    }
    if set(context) - allowed:
        errors.append("Style Reel review context contains unsupported fields")
    if context.get("schema_version") != 1:
        errors.append("Style Reel review context schema_version must be 1")
    plan_path = plan_path.resolve()
    authority_manifest_path = authority_manifest_path.resolve()
    review_path = review_path.resolve()
    errors.extend(_file_ref_errors(context.get("plan"), "Style Reel context plan"))
    errors.extend(_file_ref_errors(
        context.get("authority_manifest"), "Style Reel context authority manifest",
    ))
    errors.extend(_file_ref_errors(context.get("review"), "Style Reel context review"))
    plan_ref = context.get("plan") if isinstance(context.get("plan"), Mapping) else {}
    review_ref = context.get("review") if isinstance(context.get("review"), Mapping) else {}
    authority_ref = (
        context.get("authority_manifest")
        if isinstance(context.get("authority_manifest"), Mapping) else {}
    )
    if (
        str(plan_ref.get("path") or "") != str(plan_path)
        or not plan_path.is_file() or plan_ref.get("sha256") != sha256_file(plan_path)
    ):
        errors.append("Style Reel context plan binding is stale")
    if (
        str(review_ref.get("path") or "") != str(review_path)
        or not review_path.is_file() or review_ref.get("sha256") != sha256_file(review_path)
    ):
        errors.append("Style Reel context review binding is stale")
    authority_manifest: Any = None
    if (
        str(authority_ref.get("path") or "") != str(authority_manifest_path)
        or not authority_manifest_path.is_file()
        or authority_ref.get("sha256") != sha256_file(authority_manifest_path)
    ):
        errors.append("Style Reel context authority manifest binding is stale")
    elif authority_manifest_path.is_file():
        try:
            authority_manifest = read_json(authority_manifest_path)
        except (OSError, json.JSONDecodeError):
            errors.append("Style Reel context authority manifest is invalid")
        else:
            errors.extend(validate_style_reel_authority_manifest(
                authority_manifest, plan_path=plan_path,
            ))
    if not plan_path.is_file() or not review_path.is_file():
        return errors
    try:
        plan = read_json(plan_path)
        review = read_json(review_path)
    except (OSError, json.JSONDecodeError):
        return errors + ["Style Reel context authorities are invalid JSON"]
    if not isinstance(plan, Mapping) or not isinstance(review, Mapping):
        return errors + ["Style Reel context authorities must be mappings"]
    basis = plan.get("comparison_basis") if isinstance(plan.get("comparison_basis"), Mapping) else {}
    authority_rows = (
        authority_manifest.get("authorities")
        if isinstance(authority_manifest, Mapping) and isinstance(authority_manifest.get("authorities"), Mapping)
        else {}
    )
    semantic_ref = authority_rows.get("semantic_brief") if isinstance(authority_rows, Mapping) else None
    semantic_path = Path(str((semantic_ref or {}).get("path") or "")) if isinstance(semantic_ref, Mapping) else Path("")
    try:
        semantic_by_id = _semantic_rows(semantic_path)
    except StyleReelError as error:
        errors.append(str(error))
        semantic_by_id = {}
    try:
        event_decisions = _semantic_decision_inventory(
            semantic_by_id, list(basis.get("semantic_event_ids") or []),
            allow_legacy_render_default=(
                isinstance(authority_manifest, Mapping)
                and authority_manifest.get("evidence_class") == "synthetic_fixture"
            ),
        )
    except StyleReelError as error:
        errors.append(str(error))
        event_decisions = {}
    if context.get("comparison_basis_sha256") != _basis_hash(plan):
        errors.append("Style Reel context comparison basis is stale")
    baseline_ref = context.get("baseline_media")
    errors.extend(_file_ref_errors(baseline_ref, "Style Reel baseline media"))
    baseline_path = Path(str((baseline_ref or {}).get("path") or "")) if isinstance(baseline_ref, Mapping) else Path("")
    basis_start = _finite(basis.get("start_seconds"))
    basis_end = _finite(basis.get("end_seconds"))
    if basis_start is None or basis_end is None or basis_end <= basis_start:
        return errors + ["Style Reel context comparison basis timing is invalid"]
    expected_duration = basis_end - basis_start
    direction_signatures: list[dict[str, Any]] = []
    direction_hashes = {
        str((row.get("media") or {}).get("sha256") or "")
        for row in review.get("reels") or [] if isinstance(row, Mapping)
    }
    if baseline_path.is_file():
        try:
            duration = _probe_duration(baseline_path)
            signature = _probe_signature(baseline_path)
        except StyleReelError as error:
            errors.append(str(error))
        else:
            declared_baseline_duration = _finite(context.get("baseline_duration_seconds"))
            if (
                declared_baseline_duration is None
                or abs(duration - expected_duration) > 0.25
                or abs(declared_baseline_duration - duration) > 0.01
            ):
                errors.append("Style Reel baseline duration differs from comparison basis")
            errors.extend(_full_decode(baseline_path))
            if isinstance(baseline_ref, Mapping) and baseline_ref.get("sha256") in direction_hashes:
                errors.append("Style Reel baseline bytes must differ from all direction reels")
            for row in review.get("reels") or []:
                if not isinstance(row, Mapping):
                    continue
                media_ref = row.get("media") if isinstance(row.get("media"), Mapping) else {}
                media_path = Path(str(media_ref.get("path") or ""))
                if media_path.is_file():
                    try:
                        direction_signatures.append(_probe_signature(media_path))
                    except StyleReelError as error:
                        errors.append(str(error))
            if direction_signatures and any(value != signature for value in direction_signatures):
                errors.append("Style Reel baseline codec/canvas/frame-rate/audio signature differs")
    events = context.get("events")
    if not isinstance(events, list):
        return errors + ["Style Reel context events must be a list"]
    expected_ids = list(basis.get("semantic_event_ids") or [])
    expected_recipes: dict[str, dict[str, str]] = {
        event_id: {} for event_id in expected_ids
    }
    for direction_id in DIRECTIONS:
        contract_path = Path(contract_paths.get(direction_id, Path(""))).resolve()
        if not contract_path.is_file():
            errors.append(f"Style Reel context {direction_id} direction contract is missing")
            continue
        try:
            contract = _load_direction_contract(contract_path)
        except StyleReelError as error:
            errors.append(str(error))
            continue
        errors.extend(_direction_contract_errors(
            contract, direction_id=direction_id, plan=plan, event_ids=expected_ids,
            event_decisions=event_decisions or None,
        ))
        for recipe_row in contract.get("event_recipes") or []:
            if isinstance(recipe_row, Mapping):
                event_id = str(recipe_row.get("event_id") or "")
                if event_id in expected_recipes:
                    expected_recipes[event_id][direction_id] = recipe_row.get("recipe_id")
        for event_id in expected_ids:
            if event_decisions.get(event_id) != "render":
                expected_recipes[event_id][direction_id] = None
    observed_ids = [str(row.get("event_id") or "") for row in events if isinstance(row, Mapping)]
    if observed_ids != expected_ids or len(events) != len(expected_ids):
        errors.append("Style Reel context event set/order differs from comparison basis")
    for index, row in enumerate(events):
        if not isinstance(row, Mapping):
            errors.append(f"Style Reel context event {index} must be a mapping")
            continue
        allowed_event = {
            "event_id", "marker_seconds", "source_sentence", "approved_visible_copy",
            "viewer_takeaway", "energy_tier", "rationale", "decision", "recipes",
            "audio_auditions",
        }
        if set(row) - allowed_event:
            errors.append(f"Style Reel context event {index} contains unsupported fields")
        try:
            marker = float(row.get("marker_seconds"))
        except (TypeError, ValueError):
            marker = math.nan
        if not math.isfinite(marker) or marker < 0 or marker > expected_duration:
            errors.append(f"Style Reel context event {index} marker is outside comparison media")
        for field in ("source_sentence", "viewer_takeaway", "rationale"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"Style Reel context event {index} {field} is required")
        event_id = str(row.get("event_id") or "")
        expected_decision = event_decisions.get(event_id)
        errors.extend(_context_approved_copy_errors(
            row.get("approved_visible_copy"), expected_decision=expected_decision,
            event_index=index,
        ))
        if row.get("decision") != expected_decision:
            errors.append(f"Style Reel context event {index} decision differs from semantic brief")
        recipes = row.get("recipes")
        recipe_shape_valid = isinstance(recipes, Mapping) and list(recipes) == list(DIRECTIONS)
        if recipe_shape_valid and expected_decision == "render":
            recipe_shape_valid = all(
                isinstance(recipes.get(direction), str)
                and recipes[direction].startswith("PBM-")
                for direction in DIRECTIONS
            )
        elif recipe_shape_valid:
            recipe_shape_valid = all(recipes.get(direction) is None for direction in DIRECTIONS)
        if not recipe_shape_valid:
            errors.append(f"Style Reel context event {index} recipe comparison is incomplete")
        elif dict(recipes) != expected_recipes.get(event_id):
            errors.append(f"Style Reel context event {index} recipes differ from direction contracts")
        errors.extend(_context_audio_audition_errors(
            row.get("audio_auditions"), expected_decision=expected_decision,
            event_index=index, plan_path=plan_path,
            authority_manifest_path=authority_manifest_path, event_id=event_id,
        ))
        event_id = str(row.get("event_id") or "")
        semantic_row = semantic_by_id.get(event_id)
        if not isinstance(semantic_row, Mapping):
            errors.append(f"Style Reel context event {index} lacks current semantic authority")
        else:
            expected_projection = _semantic_projection(
                semantic_row, window_start=float(basis.get("start_seconds") or 0),
            )
            observed_projection = {
                name: row.get(name) for name in (
                    "marker_seconds", "source_sentence", "approved_visible_copy",
                    "viewer_takeaway", "energy_tier", "rationale",
                )
            }
            if observed_projection != expected_projection:
                errors.append(f"Style Reel context event {index} semantic projection is stale")
    return errors


def generate_style_reel_dashboard(
    *, plan_path: Path, authority_manifest_path: Path,
    review_path: Path, context_path: Path,
    contract_paths: Mapping[str, Path], output: Path,
    interactive_api_url: str | None = None,
    interactive_session: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Generate a local read-only A/B/C taste-review surface and bound manifest."""
    plan_path = plan_path.resolve()
    review_path = review_path.resolve()
    context_path = context_path.resolve()
    plan = read_json(plan_path)
    review = read_json(review_path)
    context = read_json(context_path)
    authority_manifest = read_json(authority_manifest_path.resolve())
    context_errors = validate_style_reel_context(
        context, plan_path=plan_path, authority_manifest_path=authority_manifest_path,
        review_path=review_path, contract_paths=contract_paths,
    )
    if context_errors:
        raise StyleReelError("Style Reel review context is stale:\n- " + "\n- ".join(context_errors))
    errors = validate_style_reel_review(
        review, plan_path=plan_path, authority_manifest_path=authority_manifest_path,
        contract_paths=contract_paths,
    )
    if errors:
        raise StyleReelError("Style Reel review is stale:\n- " + "\n- ".join(errors))
    basis = plan["comparison_basis"]
    evidence_class = (
        authority_manifest.get("evidence_class")
        if isinstance(authority_manifest, Mapping) else "unknown"
    )
    reels = {row["direction_id"]: row for row in review["reels"]}
    media_cards = [
        '<article class="reel"><h3>Source / Baseline</h3>'
        f'<video id="reel-source" class="sync-reel" controls preload="metadata" '
        f'src="{html.escape(_uri(context["baseline_media"]), quote=True)}"></video></article>'
    ]
    for direction_id in DIRECTIONS:
        media_cards.append(
            f'<article class="reel"><h3>{html.escape(direction_id)}</h3>'
            f'<video id="reel-{html.escape(direction_id, quote=True)}" class="sync-reel" '
            f'controls preload="metadata" src="{html.escape(_uri(reels[direction_id]["media"]), quote=True)}"></video></article>'
        )
    interactive_api_url = _validated_interactive_api_url(interactive_api_url)
    interactive = (
        interactive_api_url is not None and isinstance(interactive_session, Mapping)
        and bool(interactive_session.get("authorization"))
        and bool(interactive_session.get("csrf"))
    )
    event_cards: list[str] = []
    events = context.get("events") or []
    for row in events:
        if not isinstance(row, Mapping):
            raise StyleReelError("Style Reel context event rows must be mappings")
        event_id = str(row.get("event_id") or "")
        if event_id not in basis["semantic_event_ids"]:
            raise StyleReelError(f"Style Reel context event is outside plan: {event_id}")
        marker = float(row.get("marker_seconds") or 0)
        copies = " / ".join(str(value) for value in row.get("approved_visible_copy") or [])
        recipes = row.get("recipes") if isinstance(row.get("recipes"), Mapping) else {}
        recipe_text = " · ".join(
            f"{direction_id}: {recipes.get(direction_id, 'N/A')}" for direction_id in DIRECTIONS
        )
        audio = row.get("audio_auditions") if isinstance(row.get("audio_auditions"), Mapping) else {}
        audio_html = "".join(
            f'<label>{html.escape(str(name))}<audio controls preload="none" src="{html.escape(_uri(ref), quote=True)}"></audio></label>'
            for name, ref in audio.items() if name in {"voice_sfx_off", "sfx_on", "bgm_on"}
        ) or "<p>本事件没有已验证的额外试听轨。</p>"
        phase_groups: list[str] = []
        for direction_id in DIRECTIONS:
            refs = reels[direction_id]["phase_evidence"]
            figures = []
            for ref in refs:
                path = Path(str(ref.get("path") or ""))
                if path.stem.startswith(f"{event_id}-"):
                    figures.append(
                        f'<figure><img loading="lazy" src="{html.escape(_uri(ref), quote=True)}" '
                        f'alt="{html.escape(path.stem, quote=True)}"><figcaption>{html.escape(path.stem)}</figcaption></figure>'
                    )
            phase_groups.append(
                f'<section class="phase-direction"><h4>{html.escape(direction_id)}</h4><div class="phase-grid">{"".join(figures)}</div></section>'
            )
        proposal_forms: list[str] = []
        for direction_id in DIRECTIONS:
            contract_path = Path(contract_paths[direction_id]).resolve()
            if interactive:
                proposal_forms.append(f"""<form class="proposal interactive" data-event="{html.escape(event_id, quote=True)}" data-target="{html.escape(str(contract_path), quote=True)}" data-target-sha256="{sha256_file(contract_path)}">
<strong>{html.escape(direction_id)} pending 修正建议</strong><label>动作<select name="action"><option value="move">move</option><option value="resize">resize</option><option value="hide">hide</option><option value="change_variant">change_variant</option><option value="change_sfx">change_sfx</option><option value="request_regeneration">request_regeneration</option></select></label>
<label>选择器<input name="selector" required value="#{html.escape(event_id, quote=True)}"></label><label>修改前<textarea name="before_value" required></textarea></label><label>修改后<textarea name="after_value" required></textarea></label><label>原因<textarea name="reason" required></textarea></label><label>提交人<input name="approver" required></label><button type="submit">仅生成 pending proposal</button><output aria-live="polite"></output></form>""")
            else:
                proposal_forms.append(f"""<form class="proposal"><strong>{html.escape(direction_id)} pending 修正建议</strong><label>建议<textarea></textarea></label><button type="button" disabled>需通过安全本地审核服务提交</button></form>""")
        event_cards.append(f"""
<article class="event" id="event-{html.escape(event_id, quote=True)}">
<header><div><p class="eyebrow">{html.escape(event_id)} · {html.escape(str(row.get('energy_tier') or ''))}</p>
<h3>{html.escape(copies or 'Source-led event')}</h3></div>
<button class="marker" type="button" data-time="{marker:.6f}">同步查看此事件</button></header>
<dl><dt>原句</dt><dd>{html.escape(str(row.get('source_sentence') or ''))}</dd>
<dt>观众收获</dt><dd>{html.escape(str(row.get('viewer_takeaway') or ''))}</dd>
<dt>选择理由</dt><dd>{html.escape(str(row.get('rationale') or ''))}</dd>
<dt>三方向配方</dt><dd>{html.escape(recipe_text)}</dd></dl>
<div class="phase-groups">{''.join(phase_groups)}</div>
<details><summary>声音试听（Voice / SFX / BGM）</summary><div class="audio-grid">{audio_html}</div></details>
<div class="proposal-grid">{''.join(proposal_forms)}</div>
</article>""")
    questions = "".join(
        f'<li data-field="{html.escape(field, quote=True)}">{html.escape(question)}</li>'
        for field, question in USER_QUESTIONS
    )
    proposal_script = ""
    if interactive:
        endpoint = json.dumps(interactive_api_url, ensure_ascii=False)
        authorization = json.dumps(interactive_session["authorization"], ensure_ascii=False)
        csrf = json.dumps(interactive_session["csrf"], ensure_ascii=False)
        proposal_script = f"""<script>const styleProposalEndpoint={endpoint};const styleProposalAuthorization={authorization};const styleProposalCsrf={csrf};document.querySelectorAll('form.proposal.interactive').forEach(form=>form.addEventListener('submit',async event=>{{event.preventDefault();const out=form.querySelector('output');const body={{status:'pending',action:form.elements.action.value,event_id:form.dataset.event,target_path:form.dataset.target,target_sha256:form.dataset.targetSha256,selector:form.elements.selector.value,before_value:form.elements.before_value.value,after_value:form.elements.after_value.value,reason:form.elements.reason.value,approver:form.elements.approver.value,timestamp:new Date().toISOString(),related_files:[{{path:form.dataset.target,sha256:form.dataset.targetSha256}}]}};try{{const response=await fetch(styleProposalEndpoint,{{method:'POST',headers:{{'Authorization':'Bearer '+styleProposalAuthorization,'X-CSRF-Token':styleProposalCsrf,'Content-Type':'application/json'}},body:JSON.stringify(body)}});const payload=await response.json();if(!response.ok)throw new Error(payload.error||('HTTP '+response.status));out.textContent='已生成 pending proposal：'+payload.proposal_id;}}catch(error){{out.textContent='提交失败：'+String(error.message||error);}}}}));</script>"""
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>HongRun Portrait Style Reel Review</title>
<style>body{{margin:0;background:#07130f;color:#eefbf5;font-family:system-ui,sans-serif}}main{{max-width:1600px;margin:auto;padding:20px}}
.notice,.event,.reel{{background:#10241d;border:1px solid #2d4b40;border-radius:16px;padding:14px}}.notice,.event{{margin-bottom:18px}}
.reels{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}video{{width:100%;background:#000;border-radius:10px}}
.event header{{display:flex;align-items:center;justify-content:space-between;gap:12px}}.eyebrow{{color:#88d8be;font-size:12px}}
.phase-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.phase-grid img{{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:8px}}figure{{margin:0}}figcaption{{font-size:11px;overflow-wrap:anywhere}}
.phase-groups{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.phase-direction{{background:#0b1b16;padding:10px;border-radius:12px}}
.audio-grid,.proposal-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}}audio{{width:100%;display:block}}dt{{font-weight:700;color:#88d8be}}dd{{margin:0 0 8px}}textarea{{width:100%;min-height:70px}}button{{padding:8px 12px}}
@media(max-width:1100px){{.reels{{grid-template-columns:repeat(2,1fr)}}.phase-groups{{grid-template-columns:1fr}}}}
@media(max-width:760px){{.reels,.phase-grid{{grid-template-columns:1fr}}.event header{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><main><section class="notice"><h1>HongRun 个人口播 Style Reel A/B/C</h1>
    <p>证据级别：<strong>{html.escape(str(evidence_class))}</strong>。桌面端是主要品牌审美门；
    synthetic_fixture 只用于验证比较界面，不能进入 HongRun 品牌批准。页面只展示当前哈希绑定证据和 pending 建议，不会直接批准或改动媒体。</p>
<p>所有画面保持同步：拖动、播放或点击事件标记会调用 <code>syncAll</code> 对齐 Source、A、B、C。</p></section>
<section class="reels">{''.join(media_cards)}</section>
<section class="notice"><h2>HongRun 必答问题</h2><ol>{questions}</ol><p>最终选择只能通过正式用户决策合同写入。</p></section>
{''.join(event_cards)}</main>
<script>const reels=[...document.querySelectorAll('.sync-reel')];let syncing=false;
function syncAll(time,play){{if(syncing)return;syncing=true;reels.forEach(v=>{{if(Math.abs(v.currentTime-time)>.08)v.currentTime=time;if(play)v.play().catch(()=>{{}});else v.pause();}});syncing=false;}}
reels.forEach(v=>{{v.addEventListener('play',()=>syncAll(v.currentTime,true));v.addEventListener('pause',()=>syncAll(v.currentTime,false));v.addEventListener('seeked',()=>syncAll(v.currentTime,false));}});
document.querySelectorAll('.marker').forEach(b=>b.addEventListener('click',()=>syncAll(Number(b.dataset.time),false)));
</script>{proposal_script}</body></html>"""
    authorized_root = plan_path.parent.parent.resolve()
    try:
        relative_output = output.resolve().relative_to(authorized_root)
    except ValueError as error:
        raise StyleReelError("Style Reel dashboard output must remain inside the Director root") from error
    output = _safe_output_path(authorized_root, relative_output)
    output.write_text(document, encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": 1,
        "status": "pending_user_review",
        "interaction_policy": "pending_proposals_only" if interactive else "pending_only",
        "interactive_api": interactive_api_url if interactive else "disabled",
        "desktop_primary_taste_gate": True,
        "plan": _file_ref(plan_path),
        "authority_manifest": _file_ref(authority_manifest_path),
        "review": _file_ref(review_path),
        "context": _file_ref(context_path),
        "contracts": {direction: _file_ref(Path(contract_paths[direction])) for direction in DIRECTIONS},
        "html": _file_ref(output),
    }
    manifest_path = _safe_output_path(
        authorized_root, output.with_suffix(".manifest.json").relative_to(authorized_root),
    )
    write_json(manifest_path, manifest)
    return manifest
