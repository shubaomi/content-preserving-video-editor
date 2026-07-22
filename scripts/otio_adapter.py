#!/usr/bin/env python3
"""Optional OpenTimelineIO JSON projection with video-use EDL round-trip guards."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from director_contracts import read_json, write_json


def _time(value: float, rate: float) -> dict[str, Any]:
    return {"OTIO_SCHEMA": "RationalTime.1", "value": float(value) * rate, "rate": rate}


def _range(start: float, duration: float, rate: float) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _time(start, rate),
        "duration": _time(duration, rate),
    }


def _seconds(value: dict[str, Any], *, field: str) -> float:
    try:
        rate = float(value["rate"])
        ticks = float(value["value"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid OTIO {field}") from error
    if rate <= 0:
        raise ValueError(f"invalid OTIO {field} rate")
    return ticks / rate


def edl_to_otio(edl: dict[str, Any], *, rate: float = 30.0) -> dict[str, Any]:
    if rate <= 0:
        raise ValueError("OTIO rate must be positive")
    sources = edl.get("sources") or {}
    gaps_by_clip = {str(row.get("after_clip_id")): row for row in (edl.get("gaps") or [])}
    transitions_by_pair = {
        (str(row.get("from_clip_id")), str(row.get("to_clip_id"))): row
        for row in (edl.get("transitions") or [])
    }
    children: list[dict[str, Any]] = []
    ranges = edl.get("ranges") or []
    for index, row in enumerate(ranges):
        source_name = str(row.get("source"))
        start = float(row["start"])
        end = float(row["end"])
        clip_id = str(row.get("id", f"clip-{index}"))
        children.append({
            "OTIO_SCHEMA": "Clip.2",
            "name": clip_id,
            "source_range": _range(start, end - start, rate),
            "media_reference": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "target_url": str(sources.get(source_name, source_name)),
                "metadata": {"source_name": source_name},
            },
            "metadata": {"director_internal": deepcopy(row)},
        })
        gap = gaps_by_clip.get(clip_id)
        if gap:
            children.append({
                "OTIO_SCHEMA": "Gap.1", "name": f"gap-after-{clip_id}",
                "source_range": _range(0.0, float(gap["duration"]), rate),
                "metadata": {"director_internal": deepcopy(gap)},
            })
        if index + 1 < len(ranges):
            next_id = str(ranges[index + 1].get("id", f"clip-{index + 1}"))
            transition = transitions_by_pair.get((clip_id, next_id))
            if transition:
                duration = float(transition.get("duration") or 0.0)
                children.append({
                    "OTIO_SCHEMA": "Transition.1", "name": f"{clip_id}-to-{next_id}",
                    "transition_type": transition.get("type", "dissolve"),
                    "in_offset": _time(duration / 2, rate),
                    "out_offset": _time(duration / 2, rate),
                    "metadata": {"director_internal": deepcopy(transition)},
                })
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": str(edl.get("metadata", {}).get("video_id", "video-use-edl")),
        "tracks": {
            "OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": [{
                "OTIO_SCHEMA": "Track.1", "name": "V1", "kind": "Video", "children": children,
                "metadata": {"owner": "video-use"},
            }],
        },
        "metadata": {
            "director_projection_version": 1,
            "authoritative_source": "video-use-edl",
            "sources": deepcopy(sources),
            "project": deepcopy(edl.get("metadata") or {}),
        },
    }


def otio_to_internal(timeline: dict[str, Any]) -> dict[str, Any]:
    if timeline.get("OTIO_SCHEMA") != "Timeline.1":
        raise ValueError("expected OTIO Timeline.1")
    tracks = timeline.get("tracks", {}).get("children") or []
    if not tracks:
        raise ValueError("OTIO timeline requires a track")
    ranges: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    children = tracks[0].get("children") or []
    timeline_cursor = 0.0
    previous_clip_id: str | None = None
    sources: dict[str, str] = {}
    declared_sources = deepcopy((timeline.get("metadata") or {}).get("sources") or {})
    for index, child in enumerate(children):
        internal = deepcopy(child.get("metadata", {}).get("director_internal") or {})
        schema = str(child.get("OTIO_SCHEMA", ""))
        if schema.startswith("Clip."):
            source_range = child.get("source_range") or {}
            start = _seconds(source_range.get("start_time") or {}, field="clip start")
            duration = _seconds(source_range.get("duration") or {}, field="clip duration")
            if duration <= 0:
                raise ValueError("OTIO clip duration must be positive")
            reference = child.get("media_reference") or {}
            target_url = str(reference.get("target_url") or "")
            source_name = str((reference.get("metadata") or {}).get("source_name") or internal.get("source") or target_url)
            if not source_name or not target_url:
                raise ValueError("OTIO clip lacks source reference")
            sources[source_name] = target_url
            clip_id = str(child.get("name") or internal.get("id") or f"clip-{len(ranges)}")
            preserved = {key: value for key, value in internal.items()
                         if key not in {"id", "source", "start", "end", "timeline_start"}}
            internal = {
                "id": clip_id, "source": source_name, "start": start,
                "end": start + duration, "timeline_start": timeline_cursor, **preserved,
            }
            ranges.append(internal)
            timeline_cursor += duration
            previous_clip_id = clip_id
        elif schema.startswith("Gap."):
            source_range = child.get("source_range") or {}
            duration = _seconds(source_range.get("duration") or {}, field="gap duration")
            internal = {key: value for key, value in internal.items()
                        if key not in {"after_clip_id", "duration"}}
            internal = {"after_clip_id": previous_clip_id, "duration": duration, **internal}
            gaps.append(internal)
            timeline_cursor += duration
        elif schema.startswith("Transition."):
            previous_id = previous_clip_id
            next_id = None
            for candidate in children[index + 1:]:
                if str(candidate.get("OTIO_SCHEMA", "")).startswith("Clip."):
                    next_id = str(candidate.get("name") or
                                  (candidate.get("metadata", {}).get("director_internal") or {}).get("id") or "")
                    break
            duration = _seconds(child.get("in_offset") or {}, field="transition in offset") + \
                _seconds(child.get("out_offset") or {}, field="transition out offset")
            internal = {key: value for key, value in internal.items()
                        if key not in {"from_clip_id", "to_clip_id", "type", "duration"}}
            internal = {
                "from_clip_id": previous_id, "to_clip_id": next_id,
                "type": child.get("transition_type", "dissolve"), "duration": duration, **internal,
            }
            transitions.append(internal)
    metadata = timeline.get("metadata") or {}
    return {
        "owner": "video-use",
        "sources": sources or declared_sources,
        "ranges": ranges,
        "gaps": gaps,
        "transitions": transitions,
        "metadata": deepcopy(metadata.get("project") or {}),
    }


def validate_roundtrip(authoritative: dict[str, Any], restored: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("sources", "ranges", "gaps", "transitions", "metadata"):
        if (authoritative.get(field) or ([] if field in {"ranges", "gaps", "transitions"} else {})) != (
            restored.get(field) or ([] if field in {"ranges", "gaps", "transitions"} else {})
        ):
            errors.append(f"{field} changed")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--edl", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--rate", type=float, default=30.0)
    restore = sub.add_parser("restore")
    restore.add_argument("--otio", required=True)
    restore.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "export":
        output = edl_to_otio(read_json(Path(args.edl)), rate=args.rate)
        path = Path(args.out)
    else:
        output = otio_to_internal(read_json(Path(args.otio)))
        path = Path(args.out)
    write_json(path, output)
    print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
