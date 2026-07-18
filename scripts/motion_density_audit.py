#!/usr/bin/env python3
"""Audit an adaptive motion plan before rendering or release."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


LOW_INFORMATION_ANCHORS = {
    "首先", "接下来", "然后", "最后", "总结", "点击", "打开", "添加", "选择", "切换", "输入",
    "保存", "删除", "刷新", "验证", "但是", "因为", "所以", "结果", "关键", "核心", "建议",
    "first", "next", "finally", "summary", "click", "open", "add", "select", "switch", "type",
    "save", "delete", "remove", "refresh", "verify", "validate", "because", "therefore", "key",
}
GENERIC_ANCHORS = {"插件", "功能", "页面", "浏览器", "网址", "列表", "数据", "流程", "步骤", "方法", "问题", "结果"}
RESOLVED_COLLISION_STATUSES = {"clear", "resolved", "approved_safe_zone", "not_applicable"}
RESOLVED_REDUNDANCY_STATUSES = {"clear", "resolved", "complement", "replaced", "demoted", "not_applicable"}
SAFE_ZONES = {"top_left", "top_right", "side_left", "side_right", "lower_left", "lower_right"}
VERIFIED_QUIET_KINDS = {
    "source_visual_activity", "dense_ui_demonstration", "speaker_emotion_hold",
    "intentional_focus_hold", "chapter_breathing_room",
}


def _windows(duration: float, width: float) -> list[tuple[float, float]]:
    return [(float(start), min(duration, start + width)) for start in range(0, max(1, int(duration) + 1), int(width)) if start < duration]


def _groups(items):
    current = []
    for item in items:
        if not current or current[-1] == item:
            current.append(item)
        else:
            yield current
            current = [item]
    if current:
        yield current


def _quiet_gaps(events: list[dict], duration: float) -> list[dict]:
    """Return the actual empty timeline intervals, not gaps between event ends."""
    cursor = 0.0
    gaps = []
    for event in events:
        start = float(event["start"])
        end = float(event.get("end", start))
        if start > cursor:
            gaps.append({"start": round(cursor, 3), "end": round(start, 3), "duration": round(start - cursor, 3)})
        cursor = max(cursor, end)
    if duration > cursor:
        gaps.append({"start": round(cursor, 3), "end": round(duration, 3), "duration": round(duration - cursor, 3)})
    return gaps


def _quiet_is_explained(gap: dict, records: list[dict]) -> bool:
    """A quiet exception must cover the gap and carry reviewable visual evidence."""
    for record in records:
        reason = str(record.get("reason", "")).strip()
        if not reason:
            continue
        left = float(record.get("start", -1))
        right = float(record.get("end", -1))
        evidence = record.get("evidence", {})
        kind = str(evidence.get("kind", "")).strip()
        samples = evidence.get("samples", [])
        verified = evidence.get("verified") is True
        if (
            left <= float(gap["start"]) + 0.02
            and right >= float(gap["end"]) - 0.02
            and kind in VERIFIED_QUIET_KINDS
            and verified
            and isinstance(samples, list)
            and len(samples) >= 1
        ):
            return True
    return False


def _concurrency(events: list[dict]) -> dict:
    points = sorted({float(event["start"]) for event in events} | {float(event.get("end", event["start"])) for event in events})
    rows = []
    for left, right in zip(points, points[1:]):
        active = [event["id"] for event in events if float(event["start"]) < right and float(event.get("end", event["start"])) > left]
        if active:
            rows.append({"start": round(left, 3), "end": round(right, 3), "layers": len(active), "event_ids": active})
    return {"max_layers": max((row["layers"] for row in rows), default=0), "intervals": rows}


def audit(plan: dict) -> dict:
    events = sorted(plan.get("attention_events", plan.get("events", [])), key=lambda item: float(item["start"]))
    duration = float(plan.get("duration") or max((float(item.get("end", 0)) for item in events), default=0))
    constraints = plan.get("constraints", {})
    min_families = int(constraints.get("normal_window_min_families", 3)); max_share = float(constraints.get("family_max_share", 0.35)); max_quiet = float(constraints.get("maximum_visual_quiet_gap_seconds", 12))
    checks: list[dict] = []
    events_per_minute = len(events) / max(duration / 60, 0.001)
    minimum_rate = constraints.get("minimum_events_per_minute")
    density_override = plan.get("density_override", {})
    minimum_passed = minimum_rate is None or events_per_minute >= float(minimum_rate)
    if not minimum_passed:
        minimum_passed = (
            density_override.get("approved_by_user") is True
            and bool(str(density_override.get("reason", "")).strip())
            and bool(density_override.get("evidence"))
        )
    if minimum_rate is not None:
        checks.append({"name": "attention_event_rate_floor", "passed": minimum_passed,
                       "blocking": True, "value": round(events_per_minute, 3), "minimum": float(minimum_rate),
                       "policy": constraints.get("event_rate_policy", "quality_bounded_target"),
                       "override": density_override or None})
    maximum_rate = constraints.get("maximum_events_per_minute")
    if maximum_rate is None:
        recommended = plan.get("recommended_events_per_minute", plan.get("target_events_per_minute"))
        maximum_rate = recommended[1] if isinstance(recommended, list) and len(recommended) == 2 else None
    if maximum_rate is not None:
        checks.append({"name": "attention_event_rate", "passed": events_per_minute <= float(maximum_rate),
                       "blocking": True, "value": round(events_per_minute, 3), "maximum": float(maximum_rate),
                       "policy": constraints.get("event_rate_policy", "advisory_ceiling")})
    quiet_reasons = plan.get("intentional_quiet_sections", [])
    quiet_gaps = _quiet_gaps(events, duration)
    long_quiet = [gap for gap in quiet_gaps if gap["duration"] > max_quiet]
    longest_quiet = max((gap["duration"] for gap in quiet_gaps), default=0.0)
    unexplained = [gap for gap in long_quiet if not _quiet_is_explained(gap, quiet_reasons)]
    checks.append({"name": "maximum_visual_quiet_gap", "passed": not unexplained, "blocking": True,
                   "value": round(longest_quiet, 3), "limit": max_quiet,
                   "policy": constraints.get("quiet_gap_policy", "explain_long_quiet"),
                   "evidence": {"gaps": long_quiet, "intentional_quiet_sections": quiet_reasons, "unexplained": unexplained}})
    families = [event.get("visual_family") for event in events]; repeated = max((len(group) for group in _groups(families)), default=0)
    checks.append({"name": "same_family_consecutive", "passed": repeated <= int(constraints.get("same_family_max_consecutive", 3)), "blocking": False, "value": repeated})
    counts = Counter(families); total = max(len(events), 1)
    checks.append({"name": "family_share", "passed": all(value / total <= max_share + 1e-9 for value in counts.values()), "blocking": False,
                   "value": {key: round(value / total, 3) for key, value in counts.items()}, "limit": max_share,
                   "reason": "family variety is advisory; semantic fit takes priority"})
    variants = [event.get("motion_variant") for event in events]
    consecutive_variants = [variant for left, variant in zip(variants, variants[1:]) if left == variant]
    checks.append({"name": "repeated_entrance", "passed": not consecutive_variants, "blocking": False,
                   "value": {"consecutive_repeats": consecutive_variants, "distribution": dict(Counter(variants))}})
    window_evidence = {}
    for width in (15.0, 60.0):
        rows = []
        for left, right in _windows(duration, width):
            active = [event for event in events if left <= float(event["start"]) < right]
            rows.append({"start": left, "end": right, "events": len(active), "families": sorted({item.get("visual_family") for item in active})})
        window_evidence[str(int(width))] = rows
        checks.append({"name": f"{int(width)}s_windows", "passed": width < 60 or all(len(row["families"]) >= min_families or row["events"] < min_families for row in rows), "blocking": False, "evidence": rows})
    sfx = [event["sfx"] | {"start": event["start"]} for event in events if event.get("sfx", {}).get("enabled")]
    cooldown = float(constraints.get("same_sfx_file_cooldown_seconds", 20))
    cooldown_ok = all(float(later["start"]) - float(earlier["start"]) >= cooldown for index, earlier in enumerate(sfx) for later in sfx[index + 1:] if earlier.get("variant") == later.get("variant"))
    ratio = len(sfx) / total
    sfx_families = Counter(item.get("family") for item in sfx)
    max_sfx_per_minute = float(constraints.get("sfx_max_per_minute", 6))
    max_sfx_ratio = float(constraints.get("sfx_max_event_ratio", 0.45))
    sfx_per_minute = len(sfx) / max(duration / 60, 0.001)
    checks.append({"name": "sfx_selectivity_and_cooldown", "passed": ratio <= max_sfx_ratio and cooldown_ok and sfx_per_minute <= max_sfx_per_minute,
                   "blocking": True,
                   "value": {"ratio": round(ratio, 3), "count": len(sfx), "per_minute": round(sfx_per_minute, 3), "family_count": len(sfx_families), "families": dict(sfx_families), "cooldown_ok": cooldown_ok},
                   "limits": {"maximum_ratio": max_sfx_ratio, "maximum_per_minute": max_sfx_per_minute, "cooldown": cooldown}})
    concurrency = _concurrency(events)
    checks.append({"name": "concurrent_visual_layers", "passed": concurrency["max_layers"] <= int(constraints.get("max_concurrent_layers", 1)), "blocking": True,
                   "value": concurrency["max_layers"], "limit": int(constraints.get("max_concurrent_layers", 1)),
                   "evidence": [row for row in concurrency["intervals"] if row["layers"] > 1]})

    missing_evidence = []
    low_information = []
    generic_only = []
    malformed_fragment = []
    overlong = []
    low_score = []
    anchor_times: dict[str, list[tuple[str, float]]] = {}
    for event in events:
        event_id = event["id"]
        anchors = [str(item).strip() for item in event.get("semantic_anchor", []) if str(item).strip()]
        if not str(event.get("transcript_evidence", {}).get("text", "")).strip() or not anchors:
            missing_evidence.append(event_id)
        if any(anchor.lower() in LOW_INFORMATION_ANCHORS for anchor in anchors):
            low_information.append(event_id)
        if anchors and all(anchor in GENERIC_ANCHORS for anchor in anchors):
            generic_only.append(event_id)
        if any(re.search(r"^(?:了|的|的是|一个|这个|那个)|(?:的话|这个|那个|一下|进去|出来)$|(.{2,})\1$", anchor) for anchor in anchors):
            malformed_fragment.append(event_id)
        if any(len(anchor) > 16 for anchor in anchors):
            overlong.append(event_id)
        if event.get("semantic_score") is not None and float(event["semantic_score"]) < 2.6:
            low_score.append(event_id)
        for anchor in anchors:
            anchor_times.setdefault(anchor.lower(), []).append((event_id, float(event["start"])))
    cooldown = float(constraints.get("anchor_repeat_cooldown_seconds", 40))
    max_occurrences = int(constraints.get("max_exact_anchor_occurrences", 2))
    repeated_anchors = []
    for key, rows in anchor_times.items():
        starts = [row[1] for row in rows]
        if len(rows) > max_occurrences or any(right - left < cooldown for left, right in zip(starts, starts[1:])):
            repeated_anchors.append({"anchor": key, "event_ids": [row[0] for row in rows], "starts": starts})
    checks.append({"name": "semantic_anchor_quality", "passed": not missing_evidence and not low_information and not generic_only and not malformed_fragment and not overlong and not low_score and not repeated_anchors,
                   "blocking": True,
                   "value": {"missing_transcript_evidence": missing_evidence, "low_information_anchor": low_information,
                             "generic_only_anchor": generic_only, "malformed_fragment": malformed_fragment, "overlong_anchor": overlong,
                             "low_semantic_score": low_score, "repeated_anchor": repeated_anchors}})

    unresolved_collisions = []
    unresolved_redundancy = []
    unresolved_zones = []
    for event in events:
        collision = str(event.get("collision_check", {}).get("status", "")).strip().lower()
        redundancy = str(event.get("redundancy_check", {}).get("status", "")).strip().lower()
        if collision not in RESOLVED_COLLISION_STATUSES:
            unresolved_collisions.append({"id": event["id"], "status": collision or "missing"})
        if redundancy not in RESOLVED_REDUNDANCY_STATUSES:
            unresolved_redundancy.append({"id": event["id"], "status": redundancy or "missing"})
        if event.get("safe_zone") not in SAFE_ZONES:
            unresolved_zones.append({"id": event["id"], "safe_zone": event.get("safe_zone", "missing")})
    checks.append({"name": "resolved_layout_and_redundancy",
                   "passed": not unresolved_collisions and not unresolved_redundancy and not unresolved_zones,
                   "blocking": True,
                   "value": {"unresolved_collision": unresolved_collisions, "unresolved_redundancy": unresolved_redundancy,
                              "unresolved_safe_zone": unresolved_zones}})
    if constraints.get("require_distinct_render_contract"):
        missing_contract = []
        signatures: dict[tuple[str, tuple[str, ...]], set[str]] = {}
        for event in events:
            contract = event.get("render_contract", {})
            markup = str(contract.get("markup_family", "")).strip()
            animation = tuple(str(item) for item in contract.get("animation_signature", []) if str(item).strip())
            if not markup or not animation:
                missing_contract.append(event["id"])
                continue
            signatures.setdefault((markup, animation), set()).add(str(event.get("motion_variant", "")))
        aliased_variants = [
            {"markup_family": key[0], "animation_signature": list(key[1]), "variants": sorted(variants)}
            for key, variants in signatures.items() if len(variants) > 1
        ]
        checks.append({"name": "distinct_render_contract", "passed": not missing_contract and not aliased_variants,
                       "blocking": True,
                       "value": {"missing": missing_contract, "aliased_variants": aliased_variants}})
    tiers = Counter(event.get("tier", "unknown") for event in events)
    blocking_failures = [check["name"] for check in checks if check.get("blocking", True) and not check["passed"]]
    warnings = [check["name"] for check in checks if not check.get("blocking", True) and not check["passed"]]
    return {"schema_version": 3, "duration": duration, "event_count": len(events), "events_per_minute": round(events_per_minute, 3),
            "family_counts": dict(counts), "tier_counts": dict(tiers), "tier_ratios": {key: round(value / total, 3) for key, value in tiers.items()},
            "sfx_count": len(sfx), "quiet_gaps": quiet_gaps, "concurrency": concurrency, "checks": checks,
            "passed": not blocking_failures, "blocking_failures": blocking_failures, "warnings": warnings,
            "snapshot_plan": {"all_meso_macro": [event["id"] for event in events if event.get("tier") in {"meso", "macro"}],
                              "micro_by_family": sorted({event.get("visual_family") for event in events if event.get("tier") == "micro"}),
                              "densest_15s": max(window_evidence["15"], key=lambda row: row["events"], default=None),
                              "longest_quiet_bounds": max(quiet_gaps, key=lambda gap: gap["duration"], default=None),
                              "geometry_checks": ["DOM selector/timing", "caption", "face", "cursor", "platform UI", "important source UI", "overlap"]}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--plan", required=True); parser.add_argument("--out", required=True); args = parser.parse_args()
    report = audit(json.loads(Path(args.plan).read_text(encoding="utf-8")))
    output = Path(args.out); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(output.resolve())
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
