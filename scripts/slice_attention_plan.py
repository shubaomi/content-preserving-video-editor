#!/usr/bin/env python3
"""Create a deterministic time slice of an attention plan for low-cost QA renders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--seconds", type=float, help="Legacy shorthand for --start 0 --end N")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    left = max(0.0, float(args.start))
    right = float(args.end) if args.end is not None else (float(args.seconds) if args.seconds is not None else None)
    if right is None or right <= left:
        parser.error("provide --seconds N or a valid --start/--end range")
    duration = right - left
    event_key = "attention_events" if "attention_events" in plan else "events"
    events = []
    for source in plan.get(event_key, []):
        source_start = float(source["start"])
        source_end = float(source.get("end", source_start + float(source.get("duration", 0))))
        if source_end <= left or source_start >= right:
            continue
        event = dict(source)
        event["start"] = round(max(0.0, source_start - left), 3)
        event["end"] = round(min(duration, source_end - left), 3)
        event["duration"] = round(event["end"] - event["start"], 3)
        events.append(event)
    plan["duration"] = duration
    plan[event_key] = events
    plan["slice"] = {"source_start": left, "source_end": right, "time_offset": -left}
    plan["beats"] = [beat for beat in plan.get("beats", []) if float(beat["start"]) < right and float(beat.get("end", beat["start"])) > left]
    plan["intentional_quiet_sections"] = []
    output = Path(args.out); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(output.resolve()); return 0


if __name__ == "__main__": raise SystemExit(main())
