#!/usr/bin/env python3
"""Slice output-timeline captions into a HyperFrames sample data module."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def slice_captions(data: dict, start: float, end: float) -> list[dict]:
    if end <= start:
        raise ValueError("sample end must be greater than start")
    output = []
    for row in data.get("segments", []):
        source_start = float(row["start"])
        source_end = float(row["end"])
        if source_end <= start or source_start >= end:
            continue
        local_start = max(start, source_start) - start
        local_end = min(end, source_end) - start
        output.append({
            "id": f"caption-{len(output) + 1:03d}",
            "start": round(local_start, 3),
            "duration": round(local_end - local_start, 3),
            "text": str(row["text"]),
            "mapping_owner": row.get("mapping_owner", "video-use"),
            "source_start": source_start,
            "source_end": source_end,
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captions", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    captions = json.loads(Path(args.captions).read_text(encoding="utf-8"))
    rows = slice_captions(captions, args.start, args.end)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    output.write_text(f"window.HF_CAPTIONS={payload};\n", encoding="utf-8")
    print(output)
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())

