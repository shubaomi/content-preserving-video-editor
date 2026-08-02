#!/usr/bin/env python3
"""Contracts for optional human-facing NLE finishing handoff and return QA."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from director_contracts import sha256_file, write_json


def _asset(
    path: Path | None,
    *,
    asset_type: str,
    purpose: str,
    provenance: str,
    authorization_status: str = "project_authorized",
) -> dict[str, Any]:
    resolved = path.resolve() if path else None
    if resolved and resolved.is_file():
        return {
            "status": "available",
            "path": str(resolved),
            "sha256": sha256_file(resolved),
            "type": asset_type,
            "purpose": purpose,
            "provenance": provenance,
            "authorization_status": authorization_status,
        }
    return {
        "status": "unavailable",
        "path": str(resolved) if resolved else None,
        "sha256": None,
        "type": asset_type,
        "purpose": purpose,
        "provenance": provenance,
        "authorization_status": "unavailable",
        "reason": "optional asset is not present; no file was synthesized",
    }


def build_handoff_manifest(
    *,
    manifest_path: Path,
    backend: str,
    source_video: Path,
    automatic_master: Path,
    clean_a_roll: Path | None,
    captions: Path | None,
    transparent_motion_layer: Path | None,
    bgm_stem: Path | None,
    sfx_stems: Iterable[Path],
    cover: Path | None,
    modifications: list[dict[str, Any]],
    transcript: Path | None = None,
    edl: Path | None = None,
    semantic_brief: Path | None = None,
    storyboard: Path | None = None,
    production_contract: Path | None = None,
) -> dict[str, Any]:
    sfx = [
        _asset(path, asset_type="audio/sfx-stem", purpose="separable motion sound effect",
               provenance="HyperFrames audio-plan cue asset")
        for path in sfx_stems
    ]
    if not sfx:
        sfx = [_asset(None, asset_type="audio/sfx-stem", purpose="separable motion sound effects",
                      provenance="not available from current project")]
    manifest = {
        "schema_version": 1,
        "handoff_mode": "human_facing_manual_finish_only",
        "backend": backend,
        "runtime_dependency_required": False,
        "automation_capabilities_claimed": [],
        "single_universal_delivery": True,
        "source_and_automatic_master_must_remain_unchanged": True,
        "assets": {
            "source_video": _asset(
                source_video, asset_type="video/source", purpose="immutable original source",
                provenance="project.source.primary_video",
            ),
            "automatic_master": _asset(
                automatic_master, asset_type="video/automatic-master",
                purpose="immutable automatic final used as the manual finish baseline",
                provenance="director final_compose",
            ),
            "clean_a_roll": _asset(
                clean_a_roll, asset_type="video/clean-a-roll",
                purpose="optional speech-first picture and audio timeline",
                provenance="video-use output when separately materialized",
            ),
            "captions": _asset(
                captions, asset_type="text/subtitles", purpose="editable output-timeline captions",
                provenance="video-use master subtitle artifact",
            ),
            "transparent_motion_layer": _asset(
                transparent_motion_layer, asset_type="video/transparent-motion",
                purpose="optional motion-only layer with alpha",
                provenance="HyperFrames only when explicitly rendered as a transparent layer",
            ),
            "bgm_stem": _asset(
                bgm_stem, asset_type="audio/bgm-stem", purpose="separable authorized background music",
                provenance="project audio plan",
            ),
            "sfx_stems": sfx,
            "cover": _asset(
                cover, asset_type="image/cover", purpose="approved social cover",
                provenance="director cover workflow",
            ),
            "transcript": _asset(
                transcript, asset_type="application/transcript+json",
                purpose="word-level source evidence", provenance="video-use transcript",
            ),
            "edl": _asset(
                edl, asset_type="application/edl+json", purpose="retained edit timeline",
                provenance="video-use EDL",
            ),
            "semantic_brief": _asset(
                semantic_brief, asset_type="application/semantic-brief+json",
                purpose="approved editorial meaning", provenance="Director semantic brief",
            ),
            "storyboard": _asset(
                storyboard, asset_type="application/storyboard+json",
                purpose="HyperFrames motion plan", provenance="HyperFrames storyboard",
            ),
            "production_contract": _asset(
                production_contract, asset_type="application/production-contract+json",
                purpose="preservation and delivery promise", provenance="Director production contract",
            ),
        },
        "modification_list": modifications,
        "return_contract": {
            "returned_file_must_differ_from_automatic_master_path": True,
            "required_revalidation": [
                "full_decode", "captions", "audio", "visuals", "video-use final-edit-correctness",
                "platform validation against the returned file hash",
            ],
        },
    }
    errors = validate_handoff_manifest(manifest)
    if errors:
        raise ValueError("handoff manifest failed:\n- " + "\n- ".join(errors))
    write_json(manifest_path.resolve(), manifest)
    return manifest


def validate_handoff_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("handoff manifest schema_version must be 1")
    if manifest.get("backend") not in {"opencut", "openmontage", "other_nle", "none"}:
        errors.append("handoff manifest backend is unsupported")
    if manifest.get("runtime_dependency_required") is not False:
        errors.append("manual handoff cannot require an NLE runtime dependency")
    if manifest.get("automation_capabilities_claimed") != []:
        errors.append("manual handoff cannot claim unavailable automation capabilities")
    assets = manifest.get("assets") or {}
    for name in (
        "source_video", "automatic_master", "clean_a_roll", "captions",
        "transparent_motion_layer", "bgm_stem", "cover", "transcript", "edl",
        "semantic_brief", "storyboard", "production_contract",
    ):
        row = assets.get(name)
        if not isinstance(row, dict):
            errors.append(f"handoff asset is missing: {name}")
            continue
        status = row.get("status")
        if status == "available":
            path = Path(str(row.get("path", "")))
            if not path.is_absolute() or not path.is_file():
                errors.append(f"handoff asset {name} available path is missing")
            elif row.get("sha256") != sha256_file(path):
                errors.append(f"handoff asset {name} hash is stale")
            if not row.get("authorization_status"):
                errors.append(f"handoff asset {name} lacks authorization status")
        elif status == "unavailable":
            if row.get("sha256") is not None:
                errors.append(f"handoff asset {name} cannot fabricate a hash when unavailable")
        else:
            errors.append(f"handoff asset {name} has invalid status")
    sfx = assets.get("sfx_stems")
    if not isinstance(sfx, list) or not sfx:
        errors.append("handoff manifest must explicitly record SFX stem availability")
    else:
        for index, row in enumerate(sfx):
            if row.get("status") == "available":
                path = Path(str(row.get("path", "")))
                if not path.is_file() or row.get("sha256") != sha256_file(path):
                    errors.append(f"handoff SFX stem {index} is missing or stale")
            elif row.get("status") != "unavailable" or row.get("sha256") is not None:
                errors.append(f"handoff SFX stem {index} has invalid unavailable state")
    if not isinstance(manifest.get("modification_list"), list):
        errors.append("handoff modification_list must be a list")
    return errors


def validate_returned_final_qa(report: dict[str, Any], output: Path) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1 or report.get("status") != "pass":
        errors.append("returned final QA must be schema version 1 with pass status")
    if report.get("output_sha256") != sha256_file(output):
        errors.append("returned final QA output hash does not match returned video")
    reviews = report.get("reviews") or {}
    for name in ("captions", "audio", "visual"):
        row = reviews.get(name) or {}
        if row.get("status") != "pass":
            errors.append(f"returned final {name} review is not pass")
        evidence = [Path(str(path)) for path in (row.get("evidence") or [])]
        if not evidence or any(not path.is_file() for path in evidence):
            errors.append(f"returned final {name} review lacks existing evidence")
    captions = reviews.get("captions") or {}
    if int(captions.get("sample_count", 0)) < 3:
        errors.append("returned final caption review requires at least three timeline samples")
    audio = reviews.get("audio") or {}
    try:
        float(audio["integrated_lufs"])
        true_peak = float(audio["true_peak_dbtp"])
    except (KeyError, TypeError, ValueError):
        errors.append("returned final audio review requires loudness and true-peak measurements")
    else:
        if true_peak > -1.0:
            errors.append("returned final true peak exceeds -1 dBTP")
    visual = reviews.get("visual") or {}
    if int(visual.get("representative_frame_count", 0)) < 3:
        errors.append("returned final visual review requires at least three representative frames")
    return errors
