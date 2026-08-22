#!/usr/bin/env python3
"""Path-neutral synthetic projection of the canonical Jianying draft plan."""
from __future__ import annotations

from typing import Any, Mapping

from jianying_native_common import _valid_sha


def _sanitize_fixture_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if set(value) == {"path", "sha256"} and _valid_sha(value.get("sha256")):
            return {
                "uri": f"asset://sha256/{value['sha256']}",
                "sha256": value["sha256"],
            }
        return {
            str(key): _sanitize_fixture_value(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_fixture_value(child) for child in value]
    return value


def sanitize_fixture_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Project a validated plan without leaking machine-specific paths."""
    tracks: list[dict[str, Any]] = []
    for track in plan.get("tracks", []):
        clean_track = {
            "track_id": track["track_id"],
            "order": track["order"],
            "kind": track["kind"],
            "clips": [],
        }
        for clip in track.get("clips", []):
            clean_clip = _sanitize_fixture_value(dict(clip))
            # Clean A-roll is conformed to output time, while event-local
            # assets start at their own source frame zero.
            clean_clip["source_start_frame"] = (
                int(clip["start_frame"])
                if plan.get("profile") == "layered_reconstruction"
                and clip.get("role") == "base"
                else 0
            )
            clean_clip["source_duration_frames"] = int(clip["duration_frames"])
            clean_track["clips"].append(clean_clip)
        tracks.append(clean_track)
    return {
        "schema_version": 1,
        "kind": "jianying_synthetic_contract_fixture",
        "synthetic_fixture_only": True,
        "real_jianying_compatibility_claimed": False,
        "draft_id": plan.get("draft_id"),
        "profile": plan.get("profile"),
        "asset_mode": plan.get("asset_mode"),
        "timebase": plan.get("timebase"),
        "tracks": tracks,
    }
