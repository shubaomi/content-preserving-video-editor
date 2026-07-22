#!/usr/bin/env python3
"""Import user-supplied post-publication metrics without pretending to call platform APIs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


COUNT_FIELDS = {"views", "likes", "comments", "shares", "favorites", "followers_gained"}
RATIO_FIELDS = {"completion_rate", "two_second_hold_rate", "five_second_hold_rate",
                "average_watch_ratio"}
SECONDS_FIELDS = {"average_watch_seconds"}


def import_metrics(source: Path, output: Path) -> dict[str, Any]:
    source = source.resolve()
    payload = read_json(source)
    if not isinstance(payload, dict):
        raise ValueError("metrics import must be a JSON object")
    platform = str(payload.get("platform") or "")
    if platform not in {"douyin", "wechat_channels", "other"}:
        raise ValueError("metrics platform must be douyin, wechat_channels, or other")
    if not str(payload.get("published_at") or "").strip():
        raise ValueError("metrics import requires published_at")
    metrics = payload.get("metrics") or {}
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("metrics import requires a non-empty metrics mapping")
    unknown = set(metrics) - COUNT_FIELDS - RATIO_FIELDS - SECONDS_FIELDS
    if unknown:
        raise ValueError(f"unsupported metrics fields: {sorted(unknown)}")
    normalized: dict[str, float | int] = {}
    for name, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric {name} must be numeric")
        if name in COUNT_FIELDS:
            if value < 0 or int(value) != value:
                raise ValueError(f"metric {name} must be a non-negative integer")
            normalized[name] = int(value)
        elif name in RATIO_FIELDS:
            if not 0 <= float(value) <= 1:
                raise ValueError(f"metric {name} must be between 0 and 1")
            normalized[name] = float(value)
        else:
            if float(value) < 0:
                raise ValueError(f"metric {name} must be non-negative")
            normalized[name] = float(value)
    report = {
        "schema_version": 1, "platform": platform,
        "published_at": payload["published_at"], "metrics": normalized,
        "source": str(source), "source_sha256": sha256_file(source),
        "acquisition": "user_supplied_export", "platform_api_claimed": False,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "interpretation_policy": "observed metrics only; no causal performance claim",
    }
    write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    import_metrics(Path(args.input), Path(args.out))
    print(Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
