#!/usr/bin/env python3
"""Compare bound metric snapshots and emit advisory candidates, never edits."""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from action_required_contract import sha256_file, write_json


REQUIRED_BINDINGS = ("publication_id", "release_manifest_sha256", "video_sha256")
COUNT_FIELDS = {"views", "likes", "comments", "shares", "favorites", "followers_gained"}
RATIO_FIELDS = {"completion_rate", "two_second_hold_rate", "five_second_hold_rate",
                "average_watch_ratio"}


def _parse_time(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"snapshot requires {field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"snapshot {field} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"snapshot {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _load_snapshot(path: Path) -> dict[str, Any]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError(f"unsupported metric snapshot: {path}")
    binding = snapshot.get("binding")
    if not isinstance(binding, dict) or any(not str(binding.get(name) or "").strip()
                                            for name in REQUIRED_BINDINGS):
        raise ValueError(f"snapshot binding is incomplete: {path}")
    for field in ("release_manifest_sha256", "video_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", str(binding[field])) is None:
            raise ValueError(f"snapshot binding {field} must be a lowercase SHA-256")
    metrics = snapshot.get("metrics")
    if not isinstance(metrics, dict) or "views" not in metrics:
        raise ValueError(f"snapshot metrics require views: {path}")
    unknown = set(metrics) - COUNT_FIELDS - RATIO_FIELDS - {"average_watch_seconds"}
    if unknown:
        raise ValueError(f"unsupported metrics fields: {sorted(unknown)}")
    for name, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"metric {name} must be a non-negative number")
        if name in COUNT_FIELDS and int(value) != value:
            raise ValueError(f"metric {name} must be an integer")
        if name in RATIO_FIELDS and value > 1:
            raise ValueError(f"metric {name} must be between 0 and 1")
    published_at = _parse_time(snapshot.get("published_at"), "published_at")
    observed_at = _parse_time(snapshot.get("observed_at") or snapshot.get("imported_at"), "observed_at")
    if observed_at < published_at:
        raise ValueError("snapshot observation cannot precede publication")
    return {**snapshot, "_path": path, "_published_at": published_at, "_observed_at": observed_at}


def _suggestions(first: dict[str, Any], latest: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = latest["metrics"]
    candidates: list[dict[str, Any]] = []
    completion = metrics.get("completion_rate")
    if completion is not None and completion < 0.3:
        candidates.append({
            "id": "review_opening_and_pacing",
            "evidence": {"latest_completion_rate": completion},
            "suggestion": "Review the opening and chapter pacing in the next editorial cycle.",
            "causal_claim": False,
        })
    first_views = int(first["metrics"]["views"])
    latest_views = int(metrics["views"])
    shares = int(metrics.get("shares", 0))
    if latest_views and shares / latest_views >= 0.02:
        candidates.append({
            "id": "inspect_shareable_structure",
            "evidence": {"shares_per_view": shares / latest_views, "view_delta": latest_views - first_views},
            "suggestion": "Inspect whether a specific demonstrated step is worth preserving as a pattern.",
            "causal_claim": False,
        })
    return candidates


def analyze_feedback_snapshots(
    snapshot_paths: Iterable[Path],
    output: Path,
    *,
    min_views: int = 200,
    min_elapsed_hours: float = 24.0,
) -> dict[str, Any]:
    if min_views < 1 or min_elapsed_hours < 0:
        raise ValueError("minimum sample thresholds are invalid")
    paths = [Path(path).resolve() for path in snapshot_paths]
    if len(paths) < 2:
        raise ValueError("feedback analysis requires at least two snapshots")
    snapshots = sorted((_load_snapshot(path) for path in paths), key=lambda row: row["_observed_at"])
    first = snapshots[0]
    expected_binding = {name: first["binding"][name] for name in REQUIRED_BINDINGS}
    expected_platform = str(first.get("platform") or "")
    expected_published = first["_published_at"]
    previous_views = -1
    for snapshot in snapshots:
        binding = {name: snapshot["binding"][name] for name in REQUIRED_BINDINGS}
        if binding != expected_binding:
            raise ValueError("metric snapshot binding does not match the same publication and release")
        if snapshot.get("platform") != expected_platform or snapshot["_published_at"] != expected_published:
            raise ValueError("metric snapshots must describe the same platform publication time")
        views = int(snapshot["metrics"]["views"])
        if views < previous_views:
            raise ValueError("cumulative views must not decrease across snapshots")
        previous_views = views
    if len({snapshot["_observed_at"] for snapshot in snapshots}) != len(snapshots):
        raise ValueError("metric snapshots require distinct observation times")

    latest = snapshots[-1]
    elapsed_hours = (latest["_observed_at"] - expected_published).total_seconds() / 3600
    latest_views = int(latest["metrics"]["views"])
    meets_minimum = latest_views >= min_views and elapsed_hours >= min_elapsed_hours
    candidates = _suggestions(first, latest) if meets_minimum else [{
        "id": "collect_more_observations",
        "evidence": {"latest_views": latest_views, "elapsed_hours": elapsed_hours},
        "suggestion": "Collect another bound snapshot before considering editorial changes.",
        "causal_claim": False,
    }]
    report = {
        "schema": "content-preserving-video-editor/feedback-loop",
        "schema_version": 1,
        "status": "ready_for_review" if meets_minimum else "insufficient_evidence",
        "binding": expected_binding,
        "platform": expected_platform,
        "published_at": first["published_at"],
        "snapshots": [{
            "source_name": snapshot["_path"].name,
            "sha256": sha256_file(snapshot["_path"]),
            "observed_at": snapshot.get("observed_at") or snapshot.get("imported_at"),
            "metrics": snapshot["metrics"],
        } for snapshot in snapshots],
        "sample_assessment": {
            "meets_minimum": meets_minimum,
            "minimum_views": min_views,
            "minimum_elapsed_hours": min_elapsed_hours,
            "latest_views": latest_views,
            "elapsed_hours": elapsed_hours,
        },
        "suggestion_candidates": candidates,
        "preference_candidates": [],
        "cross_video_sample_count": 1,
        "eligible_for_preference_learning": False,
        "preference_learning_reason": (
            "multiple observations of one publication are not multiple independent videos"
        ),
        "recommendation_mode": "suggestion_candidates_only",
        "automatic_changes": [],
        "interpretation_policy": "observational evidence only; no causal performance claim",
    }
    write_json(Path(output), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-views", type=int, default=200)
    parser.add_argument("--min-elapsed-hours", type=float, default=24.0)
    parser.add_argument("snapshots", nargs="+")
    args = parser.parse_args()
    report = analyze_feedback_snapshots(
        [Path(path) for path in args.snapshots], Path(args.out), min_views=args.min_views,
        min_elapsed_hours=args.min_elapsed_hours,
    )
    print(json.dumps({"status": report["status"], "output": str(Path(args.out).resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
