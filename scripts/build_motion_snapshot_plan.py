#!/usr/bin/env python3
"""Build and optionally execute entrance/mid/exit snapshot QA for motion beats."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def load_beats(storyboard: dict) -> list[dict]:
    result = []
    for key in ("cards", "topicVisuals", "visuals", "beats", "scenes", "events", "attention_events"):
        for item in storyboard.get(key, []) or []:
            start = item.get("startSec", item.get("start"))
            end = item.get("endSec", item.get("end"))
            if start is None or end is None or float(end) <= float(start):
                continue
            event_start = float(start)
            event_end = float(end)
            target_contract = (
                (item.get("geometry_contract") or {}).get("target_region_contract") or {}
            )
            active_start = target_contract.get("active_output_start", event_start)
            active_end = target_contract.get("active_output_end", event_end)
            try:
                active_start = float(active_start)
                active_end = float(active_end)
            except (TypeError, ValueError):
                active_start, active_end = event_start, event_end
            if not event_start <= active_start < active_end <= event_end:
                active_start, active_end = event_start, event_end
            treatment = str(item.get("treatment") or "")
            if treatment == "quiet_source":
                continue
            result.append({
                "id": str(item.get("id") or f"{key}-{len(result) + 1}"),
                "selector": str(
                    target_contract.get("active_selector")
                    or item.get("editableLayer")
                    or item.get("layout_selector")
                    or f"#{item.get('id') or key}"
                ),
                "event_start": event_start,
                "event_end": event_end,
                "start": active_start,
                "end": active_end,
                "safe_zone": str(item.get("safeZone") or item.get("safe_zone") or item.get("side") or item.get("zone") or "full"),
                "kind": key,
                "tier": str(item.get("tier") or "unknown"),
                "visual_family": str(item.get("visual_family") or item.get("type") or "unknown"),
                "treatment": treatment,
                "intent": item.get("purpose") or item.get("intent") or item.get("title"),
                "target_ids": [
                    str(value) for value in (target_contract.get("target_ids") or [])
                    if str(value).strip()
                ],
            })
    return sorted(result, key=lambda item: item["start"])


def snapshot_points(beat: dict, composition_duration: float | None = None) -> dict:
    start, end = beat["start"], beat["end"]
    duration = end - start
    edge = min(0.18, max(0.06, duration * 0.025))
    post = end + edge
    if composition_duration is not None:
        # Keep a small media-tail guard. Container and audio durations may be a
        # few frames longer than the extracted video stream, so sampling only
        # 20ms before composition end can still yield a black/stale video frame.
        post = min(post, max(0.0, composition_duration - 0.12))
    return {
        "entrance": round(start + edge, 3),
        "midpoint": round(start + duration / 2, 3),
        "pre_exit": round(end - edge, 3),
        "post_exit": round(post, 3),
    }


def build_plan(storyboard: dict) -> dict:
    composition = storyboard.get("composition") or {}
    duration = composition.get(
        "durationSeconds", composition.get("duration", storyboard.get("duration"))
    )
    all_beats = load_beats(storyboard)
    # Capture every meso/macro phase, but sample micro beats by family. This
    # preserves actual transition evidence without emitting a redundant sheet
    # for every short keyword emphasis.
    selected = [beat for beat in all_beats if beat["tier"] in {"meso", "macro", "unknown"}]
    seen_micro_families = {beat["visual_family"] for beat in selected if beat["tier"] == "micro"}
    for beat in all_beats:
        if beat["tier"] == "micro" and beat["visual_family"] not in seen_micro_families:
            selected.append(beat)
            seen_micro_families.add(beat["visual_family"])
    beats = []
    for beat in sorted(selected, key=lambda item: item["start"]):
        beats.append({**beat, "snapshots": snapshot_points(beat, float(duration) if duration else None)})
    return {
        "schema_version": 1,
        "composition": {
            "width": composition.get("width", storyboard.get("width")), "height": composition.get("height", storyboard.get("height")),
            "fps": composition.get("fps", storyboard.get("fps")), "duration": duration,
        },
        "beats": beats,
        "snapshot_timestamps": [value for beat in beats for value in beat["snapshots"].values()],
        "required_phases": ["entrance", "midpoint", "pre_exit", "post_exit"],
        "strategy": {"all_meso_macro": True, "micro": "one representative beat per visual family", "all_event_dom_checks": "HyperFrames check"},
    }


def build_motion_sidecar(plan: dict) -> dict:
    assertions = []
    prior = None
    for beat in plan["beats"]:
        selectors = [
            f'#{beat["id"]} [data-hf-id="{target_id}"]'
            for target_id in beat.get("target_ids") or []
        ] or [beat["selector"]]
        by_sec = min(beat["start"] + 1.5, beat["start"] + (beat["end"] - beat["start"]) / 2)
        for selector in selectors:
            assertions.append({"kind": "appearsBy", "selector": selector, "bySec": round(by_sec, 3)})
            assertions.append({"kind": "staysInFrame", "selector": selector})
        if prior:
            assertions.append({"kind": "before", "a": prior, "b": selectors[0]})
        prior = selectors[0]
    return {"duration": plan["composition"].get("duration"), "assertions": assertions}


def timestamp_from_name(path: Path) -> float | None:
    match = re.search(r"-at-([0-9.]+)s", path.name)
    return float(match.group(1)) if match else None


def image_delta(left: Image.Image, right: Image.Image, zone: str) -> float:
    left = left.convert("RGB").resize((320, 180), Image.Resampling.BILINEAR)
    right = right.convert("RGB").resize((320, 180), Image.Resampling.BILINEAR)
    x0, x1 = (0, 190) if "left" in zone else (130, 320) if "right" in zone else (0, 320)
    a = np.asarray(left)[:, x0:x1].astype(np.float32) / 255
    b = np.asarray(right)[:, x0:x1].astype(np.float32) / 255
    return float(np.mean(np.abs(a - b)))


def evaluate(plan: dict, snapshot_dir: Path, contact_sheet: Path) -> dict:
    indexed = [(timestamp_from_name(path), path) for path in snapshot_dir.glob("*.png")]
    indexed = [(timestamp, path) for timestamp, path in indexed if timestamp is not None]
    if not indexed:
        raise FileNotFoundError(f"No timestamped snapshots found in {snapshot_dir}")

    def closest(timestamp: float) -> Path:
        value, path = min(indexed, key=lambda item: abs(item[0] - timestamp))
        if abs(value - timestamp) > 0.08:
            raise ValueError(f"No snapshot close to {timestamp:.3f}s; nearest is {value:.3f}s")
        return path

    thumb_w, thumb_h, label_h = 320, 180, 28
    sheet = Image.new("RGB", (thumb_w * 4, (thumb_h + label_h) * len(plan["beats"])), "#e5e7eb")
    draw = ImageDraw.Draw(sheet)
    findings = []
    beat_results = []
    for row, beat in enumerate(plan["beats"]):
        paths = {phase: closest(timestamp) for phase, timestamp in beat["snapshots"].items()}
        images = {phase: Image.open(path).convert("RGB") for phase, path in paths.items()}
        for column, phase in enumerate(("entrance", "midpoint", "pre_exit", "post_exit")):
            x, y = column * thumb_w, row * (thumb_h + label_h)
            sheet.paste(images[phase].resize((thumb_w, thumb_h), Image.Resampling.LANCZOS), (x, y + label_h))
            draw.text((x + 6, y + 7), f"{beat['id']} | {phase} | {beat['snapshots'][phase]:.3f}s", fill="#111827")
        mid_post = image_delta(images["midpoint"], images["post_exit"], beat["safe_zone"])
        pre_post = image_delta(images["pre_exit"], images["post_exit"], beat["safe_zone"])
        entrance_mid = image_delta(images["entrance"], images["midpoint"], beat["safe_zone"])
        beat_findings = []
        if mid_post < 0.006:
            beat_findings.append({"code": "possible_missing_element", "repair_dimension": "visibility_or_timing", "severity": "review"})
        if pre_post < 0.0045:
            beat_findings.append({"code": "possible_lingering_overlay", "repair_dimension": "exit_timing_or_opacity", "severity": "review"})
        if entrance_mid > 0.34:
            beat_findings.append({"code": "possible_source_or_geometry_discontinuity", "repair_dimension": "inspect_source_cut_then_position_scale_or_easing", "severity": "review"})
        for finding in beat_findings:
            finding.setdefault("severity", "error")
            finding.update({"selector": beat["selector"], "beat_id": beat["id"], "timestamp": beat["snapshots"]["midpoint"]})
            findings.append(finding)
        beat_results.append({
            "id": beat["id"], "selector": beat["selector"],
            "deltas": {"entrance_to_mid": round(entrance_mid, 5), "mid_to_post": round(mid_post, 5), "pre_to_post": round(pre_post, 5)},
            "findings": beat_findings,
        })
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_sheet, quality=92)
    return {
        "schema_version": 1,
        "contact_sheet": str(contact_sheet),
        "beats": beat_results,
        "findings": findings,
        "passed": not any(item["severity"] == "error" for item in findings),
        "caveat": "pixel-delta findings are conservative candidates; HyperFrames check JSON remains authoritative for DOM layout, contrast, selectors, and caption collisions",
    }


def capture(project: Path, plan: dict, output: Path) -> None:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise RuntimeError("npx is not available on PATH")
    timestamps = ",".join(f"{value:.3f}" for value in plan["snapshot_timestamps"])
    subprocess.run([
        npx, "hyperframes", "snapshot", str(project), "--at", timestamps,
        "--output", str(output), "--no-end", "--describe", "false",
    ], check=True)


def hyperframes_check(project: Path, output: Path) -> dict:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise RuntimeError("npx is not available on PATH")
    result = subprocess.run([
        npx, "hyperframes", "check", str(project), "--json", "--samples", "7", "--at-transitions", "--frame-check",
    ], text=True, encoding="utf-8", errors="replace", capture_output=True)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"HyperFrames check returned non-JSON output: {result.stdout[-1000:]} {result.stderr[-1000:]}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--out", required=True, help="Snapshot plan JSON")
    parser.add_argument("--project")
    parser.add_argument("--snapshot-dir")
    parser.add_argument("--qa-out")
    parser.add_argument("--contact-sheet")
    parser.add_argument("--motion-sidecar")
    parser.add_argument("--check-out")
    parser.add_argument("--hyperframes-check", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--reuse-snapshots", action="store_true")
    args = parser.parse_args()
    storyboard = json.loads(Path(args.storyboard).read_text(encoding="utf-8"))
    plan = build_plan(storyboard)
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.motion_sidecar:
        sidecar = Path(args.motion_sidecar).resolve()
        sidecar.write_text(json.dumps(build_motion_sidecar(plan), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.capture:
        if not args.project:
            raise ValueError("--project is required with --capture")
        snapshot_dir = Path(args.snapshot_dir).resolve() if args.snapshot_dir else output.parent / "motion-snapshots"
        if not args.reuse_snapshots:
            capture(Path(args.project).resolve(), plan, snapshot_dir)
        qa = evaluate(plan, snapshot_dir, Path(args.contact_sheet).resolve() if args.contact_sheet else snapshot_dir / "motion-contact-sheet.jpg")
        if args.hyperframes_check:
            check_out = Path(args.check_out).resolve() if args.check_out else output.parent / "hyperframes-check.json"
            check = hyperframes_check(Path(args.project).resolve(), check_out)
            qa["hyperframes_check"] = {"report": str(check_out), "ok": bool(check.get("ok"))}
            qa["passed"] = bool(qa["passed"] and check.get("ok"))
        qa_out = Path(args.qa_out).resolve() if args.qa_out else output.parent / "motion-snapshot-qa.json"
        qa_out.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(qa_out)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
