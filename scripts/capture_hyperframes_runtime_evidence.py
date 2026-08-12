#!/usr/bin/env python3
"""Capture renderer-owned HyperFrames DOM, geometry, text, and phase evidence."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from director_contracts import read_json, sha256_file, write_json
from keyframe_receipt import _verified_render_window


PHASE_FRACTIONS = {
    "entrance": 0.25,
    "mid": 0.5,
    "pre_exit": 0.8,
}


def compute_phase_times(
    opportunity: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]], *, fps: float,
) -> dict[str, float]:
    """Return deterministic visible phases plus the first adjacent post-exit frame."""
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be a positive finite number")
    start, end, errors = _verified_render_window(opportunity, bindings)
    if errors or start is None or end is None:
        raise ValueError("; ".join(errors) or "event render window is unresolved")
    duration = end - start
    result = {
        phase: round(start + duration * fraction, 6)
        for phase, fraction in PHASE_FRACTIONS.items()
    }
    result["post_exit"] = round(end + 1.0 / fps, 6)
    return result


def normalize_event_visible_text(phase_texts: Sequence[Sequence[str]]) -> list[str]:
    """Preserve first painted DOM order while removing repeated phase observations."""
    result: list[str] = []
    seen: set[str] = set()
    for values in phase_texts:
        for raw in values:
            value = " ".join(str(raw).split())
            if value and value not in seen:
                seen.add(value)
                result.append(value)
    return result


def select_target_observation(
    binding: Mapping[str, Any], timestamp_seconds: float,
) -> dict[str, Any] | None:
    """Select the most recent verified target state, failing closed after target loss."""
    rows = [
        row for row in binding.get("observations") or []
        if isinstance(row, dict) and isinstance(row.get("timestamp_seconds"), (int, float))
    ]
    rows.sort(key=lambda row: float(row["timestamp_seconds"]))
    prior = [row for row in rows if float(row["timestamp_seconds"]) <= timestamp_seconds]
    selected = prior[-1] if prior else next((row for row in rows if row.get("visible")), None)
    if not selected or selected.get("visible") is not True or not isinstance(selected.get("bbox"), dict):
        return None
    return selected


def measurement_overlay_distance_pixels(
    overlay_bbox: Mapping[str, Any], target_bbox: Mapping[str, Any], *,
    width: int, height: int,
) -> float:
    """Measure the largest target/overlay edge deviation in rendered pixels."""
    def edges(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
        x = float(value["x"])
        y = float(value["y"])
        return x, y, x + float(value["width"]), y + float(value["height"])

    overlay = edges(overlay_bbox)
    target = edges(target_bbox)
    deviations = (
        abs(overlay[0] - target[0]) * width,
        abs(overlay[2] - target[2]) * width,
        abs(overlay[1] - target[1]) * height,
        abs(overlay[3] - target[3]) * height,
    )
    return round(max(deviations), 3)


def resolve_browser_executable(
    requested: Path | None, playwright_chromium_path: str | Path,
    *, npx_command: str = "npx",
    runner: Callable[[Sequence[str]], tuple[int, str, str]] | None = None,
) -> Path:
    """Prefer an explicit or installed Chromium executable without fabricating one."""
    if requested is not None:
        resolved = requested.resolve()
        if not resolved.is_file():
            raise ValueError(f"browser executable is missing: {resolved}")
        return resolved
    bundled = Path(playwright_chromium_path).resolve()
    if bundled.is_file():
        return bundled
    command = [npx_command, "hyperframes", "browser", "path"]
    if runner is None:
        def runner(command: Sequence[str]) -> tuple[int, str, str]:
            resolved_command = list(command)
            resolved_command[0] = shutil.which(resolved_command[0]) or resolved_command[0]
            completed = subprocess.run(
                resolved_command, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60, check=False,
            )
            return completed.returncode, completed.stdout, completed.stderr
    exit_code, stdout, _stderr = runner(command)
    if exit_code != 0:
        raise RuntimeError(
            "HyperFrames browser resolution failed; renderer evidence is action_required"
        )
    resolved = Path(stdout.strip()).resolve()
    if not resolved.is_file():
        raise RuntimeError(
            "HyperFrames browser executable is missing; renderer evidence is action_required"
        )
    return resolved


SEEK_SCRIPT = r"""
async ({time}) => {
  const root = document.querySelector('[data-composition-id]');
  if (!root) throw new Error('composition root missing');
  const compositionId = root.dataset.compositionId;
  const timeline = window.__timelines && window.__timelines[compositionId];
  if (!timeline || typeof timeline.seek !== 'function') throw new Error('seekable timeline missing');
  document.querySelectorAll('.clip').forEach((clip) => {
    const start = Number(clip.dataset.start || 0);
    const duration = Number(clip.dataset.duration || 0);
    const active = time >= start && time <= start + duration;
    clip.style.display = active ? 'block' : 'none';
  });
  timeline.pause().seek(time, false);
  const media = [...document.querySelectorAll('video')];
  await Promise.all(media.map(async (element) => {
    const start = Number(element.dataset.start || 0);
    const desired = Math.max(0, time - start);
    if (element.readyState === 0) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('video metadata timeout')), 10000);
        element.addEventListener('loadedmetadata', () => { clearTimeout(timer); resolve(); }, {once: true});
        element.addEventListener('error', () => { clearTimeout(timer); reject(new Error('video metadata failed')); }, {once: true});
        element.load();
      });
    }
    if (Math.abs((element.currentTime || 0) - desired) >= 0.02 || element.readyState < 2) {
      element.currentTime = desired;
      await new Promise((resolve, reject) => {
        const started = performance.now();
        const verify = () => {
          if (!element.seeking && element.readyState >= 2 && Math.abs(element.currentTime - desired) < 0.04) {
            resolve();
          } else if (performance.now() - started > 10000) {
            reject(new Error(`video seek timeout: requested ${desired}, actual ${element.currentTime}`));
          } else {
            setTimeout(verify, 25);
          }
        };
        verify();
      });
    }
    if (Math.abs(element.currentTime - desired) >= 0.04) {
      throw new Error(`video seek mismatch: requested ${desired}, actual ${element.currentTime}`);
    }
    element.pause();
  }));
  const mediaTimes = media.map((element) => ({
    id: element.id || null,
    current_time_seconds: Number(element.currentTime.toFixed(6)),
    ready_state: element.readyState,
    seeking: element.seeking,
  }));
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return {
    width: Number(root.dataset.width || root.getBoundingClientRect().width),
    height: Number(root.dataset.height || root.getBoundingClientRect().height),
    media_times: mediaTimes,
  };
}
"""


MEASURE_SCRIPT = r"""
({eventId, captionLaneStart, captionLaneEnd}) => {
  const root = document.querySelector('[data-composition-id]');
  const eventRoot = document.getElementById(eventId);
  if (!root || !eventRoot) throw new Error(`event root missing: ${eventId}`);
  const rootRect = root.getBoundingClientRect();
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const rgba = (value) => {
    const match = String(value || '').match(/rgba?\(([^)]+)\)/i);
    if (!match) return [0, 0, 0, 0];
    const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
    return [parts[0] || 0, parts[1] || 0, parts[2] || 0, parts.length > 3 ? parts[3] : 1];
  };
  const luminance = (color) => {
    const channels = color.slice(0, 3).map((value) => {
      const normalized = value / 255;
      return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  };
  const contrast = (left, right) => {
    const a = luminance(left);
    const b = luminance(right);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  const effectiveOpacity = (element) => {
    let opacity = 1;
    let cursor = element;
    while (cursor && cursor instanceof Element) {
      const style = getComputedStyle(cursor);
      if (style.display === 'none' || style.visibility === 'hidden') return 0;
      opacity *= Number.parseFloat(style.opacity || '1');
      if (cursor === eventRoot) break;
      cursor = cursor.parentElement;
    }
    return opacity;
  };
  const ownText = (element) => [...element.childNodes]
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent || '')
    .join(' ').replace(/\s+/g, ' ').trim();
  const animationTargets = [eventRoot, ...eventRoot.querySelectorAll('[id]')]
    .filter((element) => Boolean(element.id))
    .map((element) => `#${CSS.escape(element.id)}`);
  const hasPaint = (element, style, text) => {
    const tag = element.tagName.toLowerCase();
    if (['rect', 'line', 'path', 'circle', 'ellipse', 'polygon', 'polyline', 'text', 'img', 'canvas', 'video'].includes(tag)) return true;
    if (text) return true;
    if (rgba(style.backgroundColor)[3] > 0.02) return true;
    return ['Top', 'Right', 'Bottom', 'Left'].some((side) => Number.parseFloat(style[`border${side}Width`] || '0') > 0);
  };
  const painted = [];
  const textRows = [];
  const ratios = [];
  [...eventRoot.querySelectorAll('*')].forEach((element) => {
    const style = getComputedStyle(element);
    const opacity = effectiveOpacity(element);
    const rect = element.getBoundingClientRect();
    const text = ownText(element);
    if (opacity <= 0.02 || rect.width <= 0.5 || rect.height <= 0.5 || !hasPaint(element, style, text)) return;
    painted.push(rect);
    if (text) {
      textRows.push(text);
      let background = [255, 255, 255, 1];
      let cursor = element;
      while (cursor && cursor instanceof Element) {
        const candidate = rgba(getComputedStyle(cursor).backgroundColor);
        if (candidate[3] > 0.5) { background = candidate; break; }
        if (cursor === eventRoot) break;
        cursor = cursor.parentElement;
      }
      ratios.push(contrast(rgba(style.color), background));
    }
  });
  const union = painted.length ? {
    left: Math.min(...painted.map((rect) => rect.left)),
    top: Math.min(...painted.map((rect) => rect.top)),
    right: Math.max(...painted.map((rect) => rect.right)),
    bottom: Math.max(...painted.map((rect) => rect.bottom)),
  } : null;
  const normalize = (rect) => rect ? {
    x: clamp((rect.left - rootRect.left) / rootRect.width, 0, 1),
    y: clamp((rect.top - rootRect.top) / rootRect.height, 0, 1),
    width: clamp((rect.right - rect.left) / rootRect.width, 0, 1),
    height: clamp((rect.bottom - rect.top) / rootRect.height, 0, 1),
  } : {x: 0, y: 0, width: 0, height: 0};
  const overlay = normalize(union);
  const focus = eventRoot.querySelector('[id*="outline"]');
  const focusRect = focus && effectiveOpacity(focus) > 0.02 ? focus.getBoundingClientRect() : null;
  const laneTop = captionLaneStart * rootRect.height;
  const laneBottom = captionLaneEnd * rootRect.height;
  let captionOverlapRatio = 0;
  if (union) {
    const overlapHeight = Math.max(0, Math.min(union.bottom - rootRect.top, laneBottom) - Math.max(union.top - rootRect.top, laneTop));
    const area = Math.max(1, (union.right - union.left) * (union.bottom - union.top));
    captionOverlapRatio = overlapHeight * (union.right - union.left) / area;
  }
  const connectors = [...eventRoot.querySelectorAll('line')].filter((element) => effectiveOpacity(element) > 0.02).map((element) => ({
    connector_id: element.id || null,
    from: {x: Number(element.getAttribute('x1')) / rootRect.width, y: Number(element.getAttribute('y1')) / rootRect.height},
    to: {x: Number(element.getAttribute('x2')) / rootRect.width, y: Number(element.getAttribute('y2')) / rootRect.height},
  }));
  const cropStatus = !union ? 'not_applicable' : (
    union.left < rootRect.left - 0.5 || union.top < rootRect.top - 0.5 ||
    union.right > rootRect.right + 0.5 || union.bottom > rootRect.bottom + 0.5
      ? 'clipped' : 'inside'
  );
  return {
    animation_targets: [...new Set(animationTargets)].sort(),
    visible: Boolean(union),
    overlay_bbox: overlay,
    focus_bbox: normalize(focusRect && {left: focusRect.left, top: focusRect.top, right: focusRect.right, bottom: focusRect.bottom}),
    visible_text: textRows,
    connectors,
    crop_status: cropStatus,
    caption_overlap_ratio: Number(captionOverlapRatio.toFixed(6)),
    composite_contrast_ratio: ratios.length ? Number(Math.min(...ratios).toFixed(3)) : 0,
  };
}
"""


def _event_bindings(
    opportunity: Mapping[str, Any], binding_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for binding_id in opportunity.get("target_binding_ids") or []:
        binding = binding_by_id.get(str(binding_id))
        if binding is None:
            raise ValueError(f"target binding is missing: {binding_id}")
        result.append(binding)
    return result


def _load_bindings(binding_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(binding_dir.glob("*.json")):
        payload = read_json(path)
        binding_id = str(payload.get("binding_id") or "")
        if not binding_id or binding_id in result:
            raise ValueError(f"invalid or duplicate target binding: {path}")
        result[binding_id] = payload
    return result


def capture_runtime_evidence(
    *, project_root: Path, storyboard_path: Path, motion_contract_path: Path,
    project_artifact: Path, binding_dir: Path, output_path: Path,
    snapshot_dir: Path, browser_path: Path | None = None,
    timeout_ms: int = 10_000, caption_lane_start: float = 0.78,
    caption_lane_end: float = 0.94,
) -> dict[str, Any]:
    """Capture actual seeked browser state for every compiler-selected event."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is required for renderer evidence; install it or mark the stage action_required"
        ) from error

    project_root = project_root.resolve()
    storyboard_path = storyboard_path.resolve()
    motion_contract_path = motion_contract_path.resolve()
    project_artifact = project_artifact.resolve()
    binding_dir = binding_dir.resolve()
    output_path = output_path.resolve()
    snapshot_dir = snapshot_dir.resolve()
    for required in (
        project_root / "index.html", storyboard_path, motion_contract_path, project_artifact,
    ):
        if not required.is_file():
            raise ValueError(f"required runtime evidence input is missing: {required}")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    storyboard = read_json(storyboard_path)
    contract = read_json(motion_contract_path)
    binding_by_id = _load_bindings(binding_dir)
    opportunities = {
        str(row.get("semantic_event_id")): row
        for row in contract.get("opportunities") or []
        if isinstance(row, dict) and row.get("decision") == "render"
    }
    storyboard_events = {
        str(row.get("semantic_event_id")): row
        for row in storyboard.get("events") or [] if isinstance(row, dict)
    }
    if list(storyboard_events) != list(opportunities):
        raise ValueError("storyboard render events differ from the motion-design contract")

    rendered_events: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        launch_args: dict[str, Any] = {
            "headless": True,
            "args": ["--allow-file-access-from-files"],
        }
        resolved_browser = resolve_browser_executable(
            browser_path, playwright.chromium.executable_path,
        )
        if resolved_browser is not None:
            launch_args["executable_path"] = str(resolved_browser)
        browser = playwright.chromium.launch(**launch_args)
        try:
            page = browser.new_page(viewport={"width": 960, "height": 624})
            # Media streams keep network activity open; DOM readiness plus the explicit
            # seekable-timeline wait is the deterministic runtime boundary.
            page.goto(
                (project_root / "index.html").as_uri(),
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            page.wait_for_function(
                "() => { const r=document.querySelector('[data-composition-id]'); "
                "return Boolean(r && window.__timelines && "
                "window.__timelines[r.dataset.compositionId]); }",
                timeout=timeout_ms,
            )
            dimensions = page.locator("[data-composition-id]").evaluate(
                "el => ({width:Number(el.dataset.width||el.getBoundingClientRect().width), height:Number(el.dataset.height||el.getBoundingClientRect().height)})"
            )
            width = int(dimensions["width"])
            height = int(dimensions["height"])
            page.set_viewport_size({"width": width, "height": height})

            for event_id, opportunity in opportunities.items():
                event = storyboard_events[event_id]
                bindings = _event_bindings(opportunity, binding_by_id)
                phases = compute_phase_times(opportunity, bindings, fps=30)
                phase_rows: list[dict[str, Any]] = []
                phase_texts: list[list[str]] = []
                animation_targets: set[str] = set()
                for phase, timestamp in phases.items():
                    seek_state = page.evaluate(SEEK_SCRIPT, {"time": timestamp})
                    measurement = page.evaluate(MEASURE_SCRIPT, {
                        "eventId": event_id,
                        "captionLaneStart": caption_lane_start,
                        "captionLaneEnd": caption_lane_end,
                    })
                    animation_targets.update(measurement.get("animation_targets") or [])
                    snapshot_path = snapshot_dir / f"{event_id}-{phase}.png"
                    page.locator("[data-composition-id]").screenshot(path=str(snapshot_path))
                    page.evaluate(
                        "() => document.querySelectorAll('.annotation').forEach((el) => { el.dataset.cpveVisibility = el.style.visibility; el.style.visibility='hidden'; })"
                    )
                    source_snapshot = snapshot_dir / f"{event_id}-{phase}-source.png"
                    page.locator("[data-composition-id]").screenshot(path=str(source_snapshot))
                    page.evaluate(
                        "() => document.querySelectorAll('.annotation').forEach((el) => { el.style.visibility=el.dataset.cpveVisibility||''; delete el.dataset.cpveVisibility; })"
                    )

                    target_rows: list[dict[str, Any]] = []
                    if phase != "post_exit":
                        for binding in bindings:
                            observation = select_target_observation(binding, timestamp)
                            if observation is None:
                                raise ValueError(
                                    f"{event_id} {phase} has no visible target observation"
                                )
                            focus_bbox = measurement.get("focus_bbox") or measurement["overlay_bbox"]
                            target_rows.append({
                                "target_id": observation["target_id"],
                                "target_bbox": observation["bbox"],
                                "overlay_distance_pixels": measurement_overlay_distance_pixels(
                                    focus_bbox, observation["bbox"], width=width, height=height,
                                ),
                            })
                    phase_texts.append(list(measurement.get("visible_text") or []))
                    phase_rows.append({
                        "phase": phase,
                        "timestamp_seconds": timestamp,
                        "media_times": seek_state["media_times"],
                        "snapshot": {
                            "path": str(snapshot_path.resolve()),
                            "sha256": sha256_file(snapshot_path),
                        },
                        "source_snapshot": {
                            "path": str(source_snapshot.resolve()),
                            "sha256": sha256_file(source_snapshot),
                        },
                        "visible": bool(measurement["visible"]),
                        "overlay_bbox": measurement["overlay_bbox"],
                        "animation_phase": phase,
                        "source_state_sha256": sha256_file(source_snapshot),
                        "target_observations": target_rows,
                        "connectors": measurement.get("connectors") or [],
                        "crop_status": measurement["crop_status"],
                        "caption_overlap_ratio": measurement["caption_overlap_ratio"],
                        "composite_contrast_ratio": measurement["composite_contrast_ratio"],
                    })
                visible_text = normalize_event_visible_text(phase_texts)
                approved_copy = list(opportunity.get("approved_visible_copy") or [])
                if visible_text != approved_copy:
                    raise ValueError(
                        f"{event_id} runtime visible text differs from approved copy: "
                        f"{visible_text!r} != {approved_copy!r}"
                    )
                rendered_events.append({
                    "event_id": event_id,
                    "recipe_id": opportunity["recipe_id"],
                    "animation_targets": sorted(animation_targets),
                    "visible_text": visible_text,
                    "phases": phase_rows,
                })
        finally:
            browser.close()

    payload = {
        "schema_version": 1,
        "producer": "hyperframes-project-runtime",
        "project_artifact": {
            "path": str(project_artifact),
            "sha256": sha256_file(project_artifact),
        },
        "motion_design_contract_sha256": sha256_file(motion_contract_path),
        "source_media_sha256": (contract.get("source_media") or {}).get("sha256"),
        "events": rendered_events,
    }
    write_json(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture renderer-owned HyperFrames text and four-phase geometry evidence.",
    )
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--motion-design-contract", required=True, type=Path)
    parser.add_argument("--project-artifact", required=True, type=Path)
    parser.add_argument("--target-binding-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--browser-path", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    parser.add_argument("--caption-lane-start", type=float, default=0.78)
    parser.add_argument("--caption-lane-end", type=float, default=0.94)
    args = parser.parse_args()
    capture_runtime_evidence(
        project_root=args.project,
        storyboard_path=args.storyboard,
        motion_contract_path=args.motion_design_contract,
        project_artifact=args.project_artifact,
        binding_dir=args.target_binding_dir,
        output_path=args.output,
        snapshot_dir=args.snapshot_dir,
        browser_path=args.browser_path,
        timeout_ms=args.timeout_ms,
        caption_lane_start=args.caption_lane_start,
        caption_lane_end=args.caption_lane_end,
    )
    print(str(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
