#!/usr/bin/env python3
"""Finalize a polish render while reusing the untouched baseline audio stream."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def has_audio(path: Path) -> bool:
    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(path)
    ], text=True, encoding="utf-8"))
    return bool(data.get("streams"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Immutable source of the original audio mix")
    parser.add_argument("--rendered-video", required=True, help="Rendered visual polish; its audio is ignored")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    baseline = Path(args.baseline).resolve()
    rendered = Path(args.rendered_video).resolve()
    output = Path(args.out).resolve()
    for path in (baseline, rendered):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not has_audio(baseline):
        raise ValueError("Baseline has no audio stream to preserve")
    if output in (baseline, rendered):
        raise ValueError("Output must not overwrite the baseline or rendered input")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial" + output.suffix)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(rendered), "-i", str(baseline),
        "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "1",
        "-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart", str(temporary),
    ]
    try:
        subprocess.run(command, check=True)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
