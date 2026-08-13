#!/usr/bin/env python3
"""Create and validate a provisional HongRun portrait-brand Golden.

The first named-user Style Reel selection is intentionally provisional.  This
module snapshots exact evidence and explicit answers without enabling automatic
profile use or inferring aesthetic preferences that the user did not state.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping

from PIL import Image, ImageChops, ImageStat

from audio_production import (
    _media_decode_errors,
    validate_sample_audio_evidence,
    validate_sample_review_mix_receipt,
)

from director_contracts import (
    read_json,
    sha256_file,
    validate_semantic_brief,
    validate_storyboard_semantic_binding,
)
from motion_contracts import _probe_video_media
from portrait_brand_contracts import validate_portrait_contract_schema
from portrait_motion_recipes import (
    PortraitRecipeError,
    build_portrait_renderer_payload,
    load_portrait_recipe_registry,
    validate_storyboard_portrait_binding,
)
from portrait_sonic import validate_portrait_sonic_projection
from sample_caption_delivery import validate_receipt as validate_caption_receipt
from validate_portrait_components_runtime import _renderer_payload_errors, _serve_directory
from portrait_style_reel import (
    DIRECTIONS,
    StyleReelError,
    _integrity_errors,
    _integrity_payload,
    validate_style_reel_review,
    validate_style_reel_user_decision_receipt,
)
from safe_generated_output import atomic_write_text, safe_generated_target
from test_acceptance_report import source_tree_sha256


class PortraitGoldenError(ValueError):
    """Raised when provisional Golden evidence is incomplete or stale."""


MediaProbe = Callable[[Path], Mapping[str, Any]]


PORTRAIT_IMPLEMENTATION_FILES = (
    "SKILL.md",
    "references/hyperframes-portrait-components-v2.css",
    "references/hyperframes-portrait-components-v2.js",
    "references/portrait-motion-recipes-v2.json",
    "references/portrait-sonic-motifs-v2.json",
)


def portrait_implementation_sha256(repository_root: Path) -> str:
    """Hash executable portrait code plus its frozen runtime authorities.

    The generic test-suite source hash intentionally covers scripts/tests only.
    Portrait maturity additionally depends on runtime JS/CSS, registries,
    schemas, and the shared HongRun profile, so those bytes must invalidate it.
    Mutable checkpoints and generated validation receipts are excluded to avoid
    circular evidence hashes.
    """
    root = Path(repository_root).resolve()
    candidates: set[Path] = set()
    for folder in (root / "scripts", root / "tests"):
        if folder.is_dir():
            candidates.update(path for path in folder.rglob("*") if path.is_file())
    for raw in PORTRAIT_IMPLEMENTATION_FILES:
        candidates.add(root / raw)
    for folder in (
        root / "references" / "portrait-brand-motion-v2" / "schemas",
        root / "references" / "portrait-brand-profiles",
    ):
        if folder.is_dir():
            candidates.update(path for path in folder.rglob("*") if path.is_file())
    rows: list[tuple[str, str]] = []
    for path in sorted(candidates):
        if not path.is_file() or {"__pycache__", ".pytest_cache"}.intersection(path.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        rows.append((path.relative_to(root).as_posix(), sha256_file(path)))
    return _stable_hash(rows)


SECOND_TOPIC_REQUIRED_GATES = (
    "source_full_decode",
    "hyperframes_strict_check",
    "phase_snapshot_review",
    "render_full_decode",
    "caption_last",
    "caption_receipt",
    "portrait_sonic_projection",
    "event_audio_audibility",
    "full_sample_sfx_mix",
    "final_full_av_decode",
    "face_hand_product_caption_occlusion_review",
)


def _stable_hash(value: Any) -> str:
    return sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _integrity_matches(payload: Mapping[str, Any]) -> bool:
    try:
        return payload.get("integrity_sha256") == _stable_hash({
            key: value for key, value in payload.items() if key != "integrity_sha256"
        })
    except (TypeError, ValueError):
        return False


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PortraitGoldenError(f"{label} must be a mapping")
    return value


def _file_ref(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    if not path.is_file():
        raise PortraitGoldenError(f"required provisional Golden file is missing: {path}")
    return {"path": str(path), "sha256": sha256_file(path)}


def _file_ref_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} must be a file reference"]
    raw_path = value.get("path")
    digest = value.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return [f"{label} path is missing"]
    path = Path(raw_path)
    if not path.is_absolute() or not path.is_file():
        return [f"{label} file is missing: {path}"]
    if not isinstance(digest, str) or digest != sha256_file(path):
        return [f"{label} hash is stale: {path}"]
    return []


def _path_inventory(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.is_file():
        return {"kind": "file", "label": label, **_file_ref(path)}
    if not path.is_dir():
        raise PortraitGoldenError(f"{label} evidence is missing: {path}")
    files = [_file_ref(candidate) for candidate in sorted(path.rglob("*")) if candidate.is_file()]
    if not files:
        raise PortraitGoldenError(f"{label} evidence directory is empty: {path}")
    return {
        "kind": "directory_inventory",
        "label": label,
        "path": str(path),
        "files": files,
        "inventory_sha256": _stable_hash(files),
    }


def _path_inventory_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} must be an evidence inventory"]
    if value.get("label") != label:
        return [f"{label} identity is stale"]
    if value.get("kind") == "file":
        return _file_ref_errors(value, label)
    if value.get("kind") != "directory_inventory":
        return [f"{label} inventory kind is invalid"]
    raw_path = value.get("path")
    rows = value.get("files")
    if not isinstance(raw_path, str) or not Path(raw_path).is_dir():
        return [f"{label} directory is missing"]
    if not isinstance(rows, list) or not rows:
        return [f"{label} directory inventory is empty"]
    errors: list[str] = []
    for index, row in enumerate(rows):
        errors.extend(_file_ref_errors(row, f"{label} file {index}"))
    if value.get("inventory_sha256") != _stable_hash(rows):
        errors.append(f"{label} inventory hash is stale")
    current = [
        _file_ref(candidate)
        for candidate in sorted(Path(raw_path).resolve().rglob("*"))
        if candidate.is_file()
    ]
    if current != rows:
        errors.append(f"{label} directory inventory bytes are stale")
    return errors


def _json_mapping(path: Path, label: str, errors: list[str]) -> Mapping[str, Any]:
    try:
        payload = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"{label} is unreadable: {error}")
        return {}
    if not isinstance(payload, Mapping):
        errors.append(f"{label} must be a JSON object")
        return {}
    return payload


def _strict_hyperframes_check_errors(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["second-topic HyperFrames check must be a mapping"]
    errors: list[str] = []
    if payload.get("ok") is not True or payload.get("strict") is not True:
        errors.append("second-topic HyperFrames strict check did not pass")
    for name in ("lint", "runtime", "layout", "contrast"):
        row = payload.get(name)
        if not isinstance(row, Mapping) or row.get("ok") is not True:
            errors.append(f"second-topic HyperFrames {name} check did not pass")
            continue
        if row.get("errorCount", 0) != 0 or row.get("warningCount", 0) != 0:
            errors.append(f"second-topic HyperFrames {name} has findings")
    return errors


def _phase_snapshot_errors(path: Path, event_count: int) -> list[str]:
    if not path.is_dir():
        return ["second-topic phase snapshot directory is missing"]
    images = sorted(path.glob("frame-*-at-*.png"))
    expected = event_count * 4
    errors: list[str] = []
    if len(images) != expected or expected <= 0:
        errors.append(
            f"second-topic phase snapshots must contain four decodable phases per event; "
            f"expected {expected}, observed {len(images)}"
        )
    digests: list[str] = []
    pixel_digests: list[str] = []
    decoded_images: list[Image.Image] = []
    indices: list[int] = []
    timestamps: list[float] = []
    for image_path in images:
        match = re.fullmatch(r"frame-(\d+)-at-([0-9]+(?:\.[0-9]+)?)s\.png", image_path.name)
        if match is None:
            errors.append(f"second-topic phase snapshot name is not machine-bound: {image_path.name}")
        else:
            indices.append(int(match.group(1)))
            timestamps.append(float(match.group(2)))
        digests.append(sha256_file(image_path))
        try:
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                decoded = image.convert("RGB")
                pixel_digests.append(sha256(decoded.tobytes()).hexdigest())
                decoded_images.append(decoded.copy())
        except (OSError, ValueError, SyntaxError):
            errors.append(f"second-topic phase snapshot is not a decodable image: {image_path}")
    if indices != list(range(expected)):
        errors.append("second-topic phase snapshot indices are incomplete or reordered")
    if timestamps != sorted(timestamps):
        errors.append("second-topic phase snapshot timestamps are not monotonic")
    if len(set(digests)) != len(digests):
        errors.append("second-topic phase snapshots contain duplicated image bytes")
    if len(pixel_digests) == expected and len(set(pixel_digests)) != expected:
        errors.append("second-topic phase snapshots contain duplicated decoded pixels")
    if len(decoded_images) == expected:
        for event_index in range(event_count):
            phases = decoded_images[event_index * 4:(event_index + 1) * 4]
            for phase_index in range(3):
                difference = ImageChops.difference(phases[phase_index], phases[phase_index + 1])
                mean_error = sum(ImageStat.Stat(difference).mean) / 3.0
                if mean_error < 2.0:
                    errors.append(
                        "second-topic phase snapshots lack material visual change for event "
                        f"{event_index} phase {phase_index}"
                    )
    return errors


def _phase_storyboard_binding_errors(path: Path, storyboard: Mapping[str, Any]) -> list[str]:
    images = sorted(path.glob("frame-*-at-*.png"))
    timestamps: list[float] = []
    for image in images:
        match = re.fullmatch(r"frame-(\d+)-at-([0-9]+(?:\.[0-9]+)?)s\.png", image.name)
        if match:
            timestamps.append(float(match.group(2)))
    events = [
        row for row in storyboard.get("events") or []
        if isinstance(row, Mapping) and row.get("treatment") != "quiet_source"
    ]
    if len(timestamps) != len(events) * 4:
        return ["second-topic phase timestamps cannot bind every Storyboard event"]
    errors: list[str] = []
    for index, event in enumerate(events):
        try:
            start = float(event.get("output_start"))
            end = float(event.get("output_end"))
        except (TypeError, ValueError):
            errors.append(f"second-topic Storyboard event {index} has invalid output window")
            continue
        phase_times = timestamps[index * 4:(index + 1) * 4]
        if not (
            start - 0.2 <= phase_times[0] <= start + 0.25
            and start < phase_times[1] < end
            and start < phase_times[2] <= end
            and end <= phase_times[3] <= end + 0.25
        ):
            errors.append(
                f"second-topic phase timestamps are not entrance/mid/pre-exit/post-exit "
                f"for event {event.get('semantic_event_id') or event.get('id')}"
            )
    return errors


def _fresh_hyperframes_errors(project: Path) -> list[str]:
    index = project / "index.html"
    if not index.is_file():
        return ["second-topic HyperFrames project index is missing"]
    completed = subprocess.run(
        ["npx.cmd", "hyperframes", "check", ".", "--json", "--strict"],
        cwd=project, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120,
    )
    if completed.returncode != 0:
        return ["second-topic current HyperFrames strict check failed"]
    try:
        observed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ["second-topic current HyperFrames strict check did not return JSON"]
    return _strict_hyperframes_check_errors(observed)


def _fresh_phase_snapshot_errors(project: Path, declared_dir: Path) -> list[str]:
    """Recapture every declared phase from the current HyperFrames project."""
    declared = sorted(declared_dir.glob("frame-*-at-*.png"))
    timestamps: list[str] = []
    for path in declared:
        match = re.fullmatch(r"frame-(\d+)-at-([0-9]+(?:\.[0-9]+)?)s\.png", path.name)
        if match is None:
            return ["second-topic phase snapshot inventory cannot be recaptured"]
        timestamps.append(match.group(2))
    if not timestamps:
        return ["second-topic phase snapshot inventory cannot be recaptured"]
    with tempfile.TemporaryDirectory(prefix="portrait-hyperframes-phases-") as temp_dir:
        try:
            completed = subprocess.run(
                [
                    "npx.cmd", "hyperframes", "snapshot", ".", "--output", temp_dir,
                    "--at", ",".join(timestamps), "--no-end", "--describe", "false",
                ],
                cwd=project, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ["second-topic current HyperFrames phase recapture failed"]
        if completed.returncode != 0:
            return ["second-topic current HyperFrames phase recapture failed"]
        recaptured = sorted(Path(temp_dir).glob("frame-*-at-*.png"))
        if [path.name for path in recaptured] != [path.name for path in declared]:
            return ["second-topic current HyperFrames phase inventory differs"]
        errors: list[str] = []
        for expected, observed in zip(declared, recaptured):
            if sha256_file(expected) != sha256_file(observed):
                errors.append(
                    f"second-topic phase snapshot differs from current HyperFrames output: "
                    f"{expected.name}"
                )
        return errors


def _project_renderer_binding_errors(
    project: Path, renderer_payload: Mapping[str, Any],
) -> list[str]:
    index = project / "index.html"
    if not index.is_file():
        return ["second-topic HyperFrames index is missing"]
    try:
        html = index.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ["second-topic HyperFrames index cannot be read"]
    compact_payload = json.dumps(
        renderer_payload, ensure_ascii=False, sort_keys=False, separators=(",", ":"),
    )
    if f"const payload={compact_payload};" not in html:
        return ["second-topic HyperFrames project does not embed the current renderer payload"]
    return []


def _fresh_renderer_runtime_errors(
    project: Path, renderer_payload: Mapping[str, Any],
) -> list[str]:
    """Prove the current payload was executed into the painted project DOM."""
    index = project / "index.html"
    if not index.is_file():
        return ["second-topic HyperFrames index is missing"]
    events = renderer_payload.get("events")
    if not isinstance(events, list) or not events or any(
        not isinstance(row, Mapping) for row in events
    ):
        return ["second-topic renderer payload event inventory is invalid"]
    expected_nodes: list[dict[str, Any]] = []
    expected_visible_copy: list[list[Any]] = []
    for row in events:
        window = row.get("outputWindow")
        if not isinstance(window, Mapping):
            return ["second-topic renderer payload output window is invalid"]
        start = window.get("start_seconds")
        end = window.get("end_seconds")
        if (
            isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not math.isfinite(float(start)) or not math.isfinite(float(end))
            or float(end) <= float(start)
        ):
            return ["second-topic renderer payload output window is invalid"]
        expected_nodes.append({
            "event_id": str(row.get("eventId") or ""),
            "start": float(start),
            "duration": float(end) - float(start),
        })
        expected_visible_copy.append(list(row.get("visibleCopy") or []))
    expected = {
        "payload_sha256": renderer_payload.get("payload_sha256"),
        "event_ids": [str(row.get("semanticEventId") or "") for row in events],
        "visible_copy": expected_visible_copy,
        "nodes": expected_nodes,
    }
    try:
        from playwright.sync_api import sync_playwright
        from capture_hyperframes_runtime_evidence import resolve_browser_executable

        with sync_playwright() as playwright, _serve_directory(project) as base_url:
            browser_path = resolve_browser_executable(
                None, playwright.chromium.executable_path,
                npx_command="npx.cmd" if os.name == "nt" else "npx",
            )
            browser = playwright.chromium.launch(
                executable_path=str(browser_path), headless=True,
                args=["--allow-file-access-from-files", "--autoplay-policy=no-user-gesture-required"],
            )
            try:
                page = browser.new_page()
                # Loopback HTTP avoids Windows file-URL path limits for nested component assets.
                page.goto(f"{base_url}/index.html", wait_until="load", timeout=30_000)
                page.wait_for_function(
                    "() => window.__portraitCandidate && window.__portraitCandidate.payloadSha256",
                    timeout=30_000,
                )
                observed = page.evaluate(
                    """() => ({
                      candidate: window.__portraitCandidate,
                      nodes: [...document.querySelectorAll('[data-composition-id] .pbm-event')]
                        .map((node) => ({
                          event_id: node.id,
                          hf_id: node.dataset.hfId || null,
                          start: Number(node.dataset.start),
                          duration: Number(node.dataset.duration),
                          text: (node.innerText || '').replace(/\\s+/g, ' ').trim(),
                        })),
                    })""",
                )
            finally:
                browser.close()
    except Exception as error:  # Playwright/browser failures are a blocking evidence gap.
        return [f"second-topic renderer payload runtime observation failed: {error}"]
    return _renderer_runtime_observation_errors(expected, observed)


def _renderer_runtime_observation_errors(
    expected: Mapping[str, Any], observed: Any,
) -> list[str]:
    """Validate browser-observed renderer state without trusting JS numbers."""
    candidate = observed.get("candidate") if isinstance(observed, Mapping) else None
    nodes = observed.get("nodes") if isinstance(observed, Mapping) else None
    if not isinstance(candidate, Mapping) or not isinstance(nodes, list):
        return ["second-topic renderer payload runtime observation is malformed"]
    errors: list[str] = []
    if candidate.get("payloadSha256") != expected["payload_sha256"]:
        errors.append("second-topic runtime payload hash differs")
    if candidate.get("eventIds") != expected["event_ids"]:
        errors.append("second-topic runtime event inventory differs")
    if candidate.get("visibleCopy") != expected["visible_copy"]:
        errors.append("second-topic runtime visible copy differs")
    if len(nodes) != len(expected["nodes"]):
        errors.append("second-topic runtime painted event inventory differs")
    observed_ids = [
        row.get("event_id") if isinstance(row, Mapping) else None for row in nodes
    ]
    expected_ids = [row["event_id"] for row in expected["nodes"]]
    if observed_ids != expected_ids or len(set(observed_ids)) != len(observed_ids):
        errors.append("second-topic runtime painted event identities differ")
    for index, (expected_node, node) in enumerate(zip(expected["nodes"], nodes)):
        if not isinstance(node, Mapping):
            errors.append(f"second-topic runtime event is not painted: {expected_node['event_id']}")
            continue
        if node.get("event_id") != expected_node["event_id"] or node.get("hf_id") != expected_node["event_id"]:
            errors.append(f"second-topic runtime event identity differs: {expected_node['event_id']}")
        observed_start = node.get("start")
        observed_duration = node.get("duration")
        if (
            isinstance(observed_start, bool)
            or not isinstance(observed_start, (int, float))
            or not math.isfinite(float(observed_start))
            or abs(float(observed_start) - expected_node["start"]) > 0.001
        ):
            errors.append(f"second-topic runtime event start differs: {expected_node['event_id']}")
        if (
            isinstance(observed_duration, bool)
            or not isinstance(observed_duration, (int, float))
            or not math.isfinite(float(observed_duration))
            or abs(float(observed_duration) - expected_node["duration"]) > 0.001
        ):
            errors.append(f"second-topic runtime event duration differs: {expected_node['event_id']}")
        text = str(node.get("text") or "")
        if any(copy not in text for copy in expected["visible_copy"][index]):
            errors.append(f"second-topic runtime visible copy is not painted: {expected_node['event_id']}")
    return errors


def _phase_candidate_binding_errors(
    phase_dir: Path, final_review_dir: Path,
) -> list[str]:
    phases = sorted(phase_dir.glob("frame-*-at-*.png"))
    finals = sorted(final_review_dir.glob("at-*.png"))
    selected = [path for index, path in enumerate(phases) if index % 4 in {1, 3}]
    if len(selected) != len(finals) or not selected:
        return ["second-topic phase/final review inventories cannot be paired"]
    errors: list[str] = []
    for event_index in range(len(phases) // 4):
        mid_phase_path = phases[event_index * 4 + 1]
        post_phase_path = phases[event_index * 4 + 3]
        mid_final_path = finals[event_index * 2]
        post_final_path = finals[event_index * 2 + 1]
        try:
            with (
                Image.open(mid_phase_path) as mid_phase_image,
                Image.open(post_phase_path) as post_phase_image,
                Image.open(mid_final_path) as mid_final_image,
                Image.open(post_final_path) as post_final_image,
            ):
                mid_phase = mid_phase_image.convert("RGB")
                post_phase = post_phase_image.convert("RGB")
                mid_final = mid_final_image.convert("RGB")
                post_final = post_final_image.convert("RGB")
                if len({mid_phase.size, post_phase.size, mid_final.size, post_final.size}) != 1:
                    errors.append(
                        f"second-topic phase/final geometry differs: {mid_phase_path.name}"
                    )
                    continue
                width, height = mid_phase.size
                comparison_height = int(height * 0.85)
                phase_change = ImageChops.difference(mid_phase, post_phase).convert("L")
                mask = phase_change.point(lambda value: 255 if value >= 18 else 0)
                mask.paste(0, (0, comparison_height, width, height))
                changed_pixels = mask.histogram()[255]
                if changed_pixels < max(64, int(width * comparison_height * 0.002)):
                    errors.append(
                        f"second-topic HyperFrames event has no material phase mask: {mid_phase_path.name}"
                    )
                    continue
                for phase, final, path in (
                    (mid_phase, mid_final, mid_phase_path),
                    (post_phase, post_final, post_phase_path),
                ):
                    difference = ImageChops.difference(phase, final)
                    masked_error = sum(ImageStat.Stat(difference, mask=mask).mean) / 3.0
                    if masked_error > 8.0:
                        errors.append(
                            "second-topic HyperFrames changed region is not observable in final candidate: "
                            f"{path.name} (masked MAE {masked_error:.3f})"
                        )
        except (OSError, ValueError, SyntaxError):
            errors.append(f"second-topic phase/final comparison failed: event {event_index}")
    return errors


def _final_review_snapshot_errors(
    path: Path, *, candidate_path: Path, storyboard: Mapping[str, Any],
) -> list[str]:
    """Bind the human-review stills to exact frames in the approved candidate."""
    if not path.is_dir():
        return ["second-topic final review snapshot directory is missing"]
    images = sorted(path.glob("at-*.png"))
    events = [
        row for row in storyboard.get("events") or []
        if isinstance(row, Mapping) and row.get("treatment") != "quiet_source"
    ]
    expected = len(events) * 2
    errors: list[str] = []
    if expected <= 0 or len(images) != expected:
        errors.append(
            "second-topic final review snapshots must contain mid/post frames for every event"
        )
        return errors
    timestamps: list[float] = []
    hashes: list[str] = []
    for image_path in images:
        match = re.fullmatch(r"at-([0-9]+(?:\.[0-9]+)?)\.png", image_path.name)
        if match is None:
            errors.append(
                f"second-topic final review snapshot name is not machine-bound: {image_path.name}"
            )
            continue
        timestamps.append(float(match.group(1)))
        hashes.append(sha256_file(image_path))
        try:
            with Image.open(image_path) as image:
                image.verify()
        except (OSError, ValueError, SyntaxError):
            errors.append(
                f"second-topic final review snapshot is not a decodable image: {image_path}"
            )
    if len(set(hashes)) != len(hashes):
        errors.append("second-topic final review snapshots contain duplicated image bytes")
    if len(timestamps) != expected:
        return errors
    for index, event in enumerate(events):
        try:
            start = float(event.get("output_start"))
            end = float(event.get("output_end"))
        except (TypeError, ValueError):
            errors.append(f"second-topic Storyboard event {index} has invalid output window")
            continue
        mid, post = timestamps[index * 2:(index + 1) * 2]
        if not (start < mid < end and end <= post <= end + 0.25):
            errors.append(
                "second-topic final review timestamps are not mid/post frames for event "
                f"{event.get('semantic_event_id') or event.get('id')}"
            )
    if errors:
        return errors
    with tempfile.TemporaryDirectory(prefix="portrait-final-review-") as temp_dir:
        for image_path, timestamp in zip(images, timestamps):
            extracted = Path(temp_dir) / image_path.name
            completed = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{timestamp:.3f}", "-i", str(candidate_path),
                    "-frames:v", "1", str(extracted),
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=60,
            )
            if completed.returncode != 0 or not extracted.is_file():
                errors.append(
                    f"second-topic final review frame cannot be extracted at {timestamp:.2f}s"
                )
                continue
            try:
                with Image.open(image_path) as declared_image, Image.open(extracted) as observed_image:
                    declared = declared_image.convert("RGB")
                    observed = observed_image.convert("RGB")
                    if declared.size != observed.size:
                        errors.append(
                            f"second-topic final review geometry differs at {timestamp:.2f}s"
                        )
                        continue
                    difference = ImageChops.difference(declared, observed)
                    mean_error = sum(ImageStat.Stat(difference).mean) / 3.0
                    if mean_error > 1.0:
                        errors.append(
                            "second-topic final review pixels differ from approved candidate at "
                            f"{timestamp:.2f}s (MAE {mean_error:.3f})"
                        )
            except (OSError, ValueError, SyntaxError):
                errors.append(
                    f"second-topic final review comparison failed at {timestamp:.2f}s"
                )
    return errors


def _second_topic_technical_errors(
    qa: Mapping[str, Any], *, candidate_path: Path,
) -> list[str]:
    """Freshly revalidate the actual second-topic production evidence chain."""
    evidence = qa.get("evidence")
    if not isinstance(evidence, Mapping):
        return ["second-topic QA evidence inventory is missing"]
    errors: list[str] = []
    required = (
        "semantic_brief", "motion_contracts", "storyboard", "renderer_payload",
        "hyperframes_index", "hyperframes_check", "phase_snapshots", "final_review_snapshots",
        "audio_evidence", "mix_receipt", "caption_receipt",
    )
    paths: dict[str, Path] = {}
    for name in required:
        raw = evidence.get(name)
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"second-topic QA evidence path is missing: {name}")
            continue
        path = Path(raw)
        if not path.is_absolute() or not path.exists():
            errors.append(f"second-topic QA evidence is missing: {name}")
            continue
        paths[name] = path.resolve()
    if errors:
        return errors

    brief = _json_mapping(paths["semantic_brief"], "second-topic semantic brief", errors)
    contracts = _json_mapping(paths["motion_contracts"], "second-topic motion contracts", errors)
    storyboard = _json_mapping(paths["storyboard"], "second-topic storyboard", errors)
    renderer = _json_mapping(paths["renderer_payload"], "second-topic renderer payload", errors)
    hyperframes_check = _json_mapping(
        paths["hyperframes_check"], "second-topic HyperFrames check", errors,
    )
    audio_evidence = _json_mapping(
        paths["audio_evidence"], "second-topic audio evidence", errors,
    )
    mix_receipt = _json_mapping(paths["mix_receipt"], "second-topic mix receipt", errors)
    caption_receipt = _json_mapping(
        paths["caption_receipt"], "second-topic caption receipt", errors,
    )
    if errors:
        return errors

    errors.extend(f"second-topic semantic brief: {error}" for error in validate_semantic_brief(dict(brief)))
    portrait_metadata_keys = {
        "supporting_layers", "protected_region_ids", "reduced_motion", "seek_safe",
        "post_exit", "gesture_binding_id", "gesture_binding", "subject_binding",
        "source_target_id", "asset_request_id", "asset_ref",
        "chapter_boundary_binding", "subject_mask_ref",
    }
    semantic_storyboard = dict(storyboard)
    semantic_storyboard["events"] = [
        {
            key: value for key, value in row.items()
            if not key.startswith("portrait_") and key not in portrait_metadata_keys
        }
        if isinstance(row, Mapping) else row
        for row in storyboard.get("events") or []
    ]
    errors.extend(
        f"second-topic storyboard: {error}"
        for error in validate_storyboard_semantic_binding(semantic_storyboard, dict(brief))
    )
    errors.extend(
        f"second-topic portrait storyboard: {error}"
        for error in validate_storyboard_portrait_binding(storyboard, contracts)
    )
    hyperframes_project = (
        paths["renderer_payload"].parent / "hyperframes" / str(qa.get("direction") or "")
    )
    errors.extend(
        f"second-topic renderer payload: {error}"
        for error in _renderer_payload_errors(renderer)
    )
    try:
        expected_renderer = build_portrait_renderer_payload(
            contracts, load_portrait_recipe_registry(), project_root=hyperframes_project,
            materialize_assets=False,
        )
    except (PortraitRecipeError, OSError, TypeError, ValueError) as error:
        errors.append(f"second-topic canonical renderer payload cannot be rebuilt: {error}")
    else:
        if renderer != expected_renderer:
            errors.append("second-topic renderer payload differs from canonical motion contracts")
    errors.extend(_strict_hyperframes_check_errors(hyperframes_check))
    errors.extend(_fresh_hyperframes_errors(hyperframes_project))
    errors.extend(_project_renderer_binding_errors(hyperframes_project, renderer))
    errors.extend(_fresh_renderer_runtime_errors(hyperframes_project, renderer))

    contract_rows = contracts.get("contracts")
    if not isinstance(contract_rows, list) or not contract_rows:
        errors.append("second-topic portrait motion contract inventory is missing")
        contract_rows = []
    registry = load_portrait_recipe_registry()
    known_recipes = {
        str(row.get("recipe_id") or "")
        for row in registry.get("recipes") or [] if isinstance(row, Mapping)
    }
    contract_ids: list[str] = []
    contract_recipes: dict[str, str] = {}
    for row in contract_rows:
        if not isinstance(row, Mapping):
            errors.append("second-topic portrait motion contract row is invalid")
            continue
        event_id = str(row.get("semantic_event_id") or "")
        recipe_id = str(row.get("primary_recipe_id") or "")
        contract_ids.append(event_id)
        contract_recipes[event_id] = recipe_id
        if not event_id or recipe_id not in known_recipes:
            errors.append(f"second-topic portrait recipe is not frozen/current: {event_id}")
    qa_events = qa.get("semantic_events")
    if isinstance(qa_events, list):
        observed = [str(row.get("id") or "") for row in qa_events if isinstance(row, Mapping)]
        if observed != contract_ids:
            errors.append("second-topic QA event set/order differs from motion contracts")
        for row in qa_events:
            if isinstance(row, Mapping) and row.get("recipe") != contract_recipes.get(str(row.get("id") or "")):
                errors.append("second-topic QA recipe differs from frozen motion contract")
    errors.extend(_phase_snapshot_errors(paths["phase_snapshots"], len(contract_ids)))
    errors.extend(_phase_storyboard_binding_errors(paths["phase_snapshots"], storyboard))
    errors.extend(_fresh_phase_snapshot_errors(
        hyperframes_project, paths["phase_snapshots"],
    ))
    errors.extend(_final_review_snapshot_errors(
        paths["final_review_snapshots"], candidate_path=candidate_path,
        storyboard=storyboard,
    ))
    errors.extend(_phase_candidate_binding_errors(
        paths["phase_snapshots"], paths["final_review_snapshots"],
    ))

    audio_plan_row = mix_receipt.get("audio_plan")
    raw_candidate_row = mix_receipt.get("candidate_input")
    mixed_output_row = mix_receipt.get("output")
    if not all(isinstance(row, Mapping) for row in (audio_plan_row, raw_candidate_row, mixed_output_row)):
        errors.append("second-topic mix receipt lacks canonical media/audio-plan references")
    else:
        audio_plan_path = Path(str(audio_plan_row.get("path") or "")).resolve()
        raw_candidate_path = Path(str(raw_candidate_row.get("path") or "")).resolve()
        mixed_output_path = Path(str(mixed_output_row.get("path") or "")).resolve()
        if not audio_plan_path.is_file():
            errors.append("second-topic canonical audio plan is missing")
        else:
            audio_plan = _json_mapping(audio_plan_path, "second-topic audio plan", errors)
            sonic_path = audio_plan_path.parents[2] / "portrait-sonic-plan.json"
            sonic_plan = _json_mapping(sonic_path, "second-topic portrait sonic plan", errors)
            errors.extend(
                f"second-topic portrait sonic projection: {error}"
                for error in validate_portrait_sonic_projection(
                    sonic_plan, audio_plan, base_dir=audio_plan_path.parent,
                    motion_contracts_path=paths["motion_contracts"], storyboard=storyboard,
                )
            )
            errors.extend(validate_sample_audio_evidence(
                audio_plan=audio_plan_path, storyboard=paths["storyboard"],
                candidate_media=raw_candidate_path, evidence_path=paths["audio_evidence"],
                output_dir=paths["audio_evidence"].parent,
                expected_evidence_path=paths["audio_evidence"],
                declared_evidence_sha256=sha256_file(paths["audio_evidence"]),
            ))
            errors.extend(validate_sample_review_mix_receipt(
                dict(mix_receipt), candidate_media=raw_candidate_path,
                audio_plan=audio_plan_path, output=mixed_output_path,
            ))
    errors.extend(validate_caption_receipt(caption_receipt))
    caption_candidate = caption_receipt.get("candidate")
    caption_output = caption_candidate.get("output") if isinstance(caption_candidate, Mapping) else None
    if not isinstance(caption_output, Mapping) or Path(
        str(caption_output.get("path") or "")
    ).resolve() != candidate_path.resolve():
        errors.append("second-topic caption-last output differs from the approved candidate")
    errors.extend(_media_decode_errors(candidate_path, "second-topic final candidate"))
    return errors


def _second_topic_qa_errors(
    qa: Any, *, candidate_path: Path, media_probe: MediaProbe,
) -> list[str]:
    if not isinstance(qa, Mapping):
        return ["second-topic QA must be a mapping"]
    errors: list[str] = []
    if (
        qa.get("schema_version") != 1
        or qa.get("status") != "awaiting_named_user_repeat_use_approval"
        or qa.get("direction") not in DIRECTIONS
        or qa.get("materially_different_from_first_topic") is not True
    ):
        errors.append("second-topic QA identity or portability decision is invalid")
    if not str(qa.get("candidate_id") or "").strip() or not str(qa.get("source_topic") or "").strip():
        errors.append("second-topic QA candidate/topic identity is missing")
    gates = qa.get("gates")
    if not isinstance(gates, Mapping):
        errors.append("second-topic QA gates must be a mapping")
    else:
        allowed_gate_values = {
            "source_full_decode": {"pass"},
            "hyperframes_strict_check": {"pass_zero_findings"},
            "render_full_decode": {"pass"},
            "caption_receipt": {"pass"},
            "portrait_sonic_projection": {"pass"},
            "full_sample_sfx_mix": {"pass"},
            "final_full_av_decode": {"pass"},
            "face_hand_product_caption_occlusion_review": {"pass"},
        }
        for name in SECOND_TOPIC_REQUIRED_GATES:
            value = gates.get(name)
            if name in allowed_gate_values:
                passed = value in allowed_gate_values[name]
            elif name == "phase_snapshot_review":
                passed = isinstance(value, str) and value.startswith("pass_") and value.endswith("_frames")
            elif name == "caption_last":
                passed = isinstance(value, str) and value.startswith("pass_") and value.endswith("_source_preserving_phrases")
            elif name == "event_audio_audibility":
                passed = isinstance(value, str) and value.startswith("pass_") and "_of_" in value
            else:
                passed = False
            if not passed:
                errors.append(f"second-topic QA gate did not pass: {name}")
        if gates.get("production_default") is not False:
            errors.append("second-topic QA must not claim production default")
    events = qa.get("semantic_events")
    if not isinstance(events, list) or not events or any(
        not isinstance(row, Mapping) or not str(row.get("id") or "").strip()
        or not str(row.get("recipe") or "").startswith("PBM-")
        for row in events
    ):
        errors.append("second-topic QA semantic event inventory is invalid")
    candidate = qa.get("candidate")
    candidate_path = Path(candidate_path).resolve()
    if not isinstance(candidate, Mapping):
        errors.append("second-topic QA candidate must be a mapping")
    else:
        if Path(str(candidate.get("path") or "")).resolve() != candidate_path:
            errors.append("second-topic QA candidate path is stale")
        if not candidate_path.is_file() or candidate.get("sha256") != (
            sha256_file(candidate_path) if candidate_path.is_file() else None
        ):
            errors.append("second-topic QA candidate hash is stale")
        if candidate_path.is_file():
            try:
                observed = _probe_video_media(candidate_path)
                duration = float(observed.get("duration_seconds") or 0)
                width = int(observed.get("width") or 0)
                height = int(observed.get("height") or 0)
            except (OSError, TypeError, ValueError):
                errors.append("second-topic QA candidate cannot be probed")
            else:
                declared_duration = candidate.get("duration_seconds")
                if (
                    isinstance(declared_duration, bool)
                    or not isinstance(declared_duration, (int, float))
                    or not math.isfinite(float(declared_duration))
                ):
                    errors.append("second-topic QA candidate duration is invalid")
                elif abs(duration - float(declared_duration)) > 0.05:
                    errors.append("second-topic QA candidate duration is stale")
                if width != candidate.get("width") or height != candidate.get("height"):
                    errors.append("second-topic QA candidate geometry is stale")
    evidence = qa.get("evidence")
    if not isinstance(evidence, Mapping) or not evidence:
        errors.append("second-topic QA evidence inventory is missing")
    else:
        for name in (
            "semantic_brief", "motion_contracts", "storyboard", "renderer_payload",
            "hyperframes_index", "hyperframes_check", "phase_snapshots", "final_review_snapshots",
            "audio_evidence", "mix_receipt", "caption_receipt",
        ):
            raw = evidence.get(name)
            if not isinstance(raw, str) or not Path(raw).exists():
                errors.append(f"second-topic QA evidence is missing: {name}")
    if not errors:
        errors.extend(_second_topic_technical_errors(qa, candidate_path=candidate_path))
    return errors


def _second_topic_decision_errors(
    decision: Any, *, candidate_ref: Mapping[str, Any], qa_ref: Mapping[str, Any],
) -> list[str]:
    if not isinstance(decision, Mapping):
        return ["second-topic user decision must be a mapping"]
    errors = _integrity_errors(decision, "second-topic user decision")
    if (
        decision.get("schema_version") != 1
        or decision.get("kind") != "hongrun_portrait_second_topic_user_decision"
        or decision.get("actor") != "HongRun"
        or decision.get("confirmation_method")
        != "explicit_user_confirmation_hash_v1"
        or decision.get("repeat_use_willingness") != "yes"
        or decision.get("preference") != "candidate"
        or not str(decision.get("reason") or "").strip()
        or not str(decision.get("thread_id") or "").strip()
    ):
        errors.append("second-topic user decision identity or explicit answer is invalid")
    text = decision.get("decision_text")
    if not isinstance(text, str) or not text.strip() or decision.get(
        "decision_text_sha256"
    ) != sha256(text.strip().encode("utf-8")).hexdigest():
        errors.append("second-topic user decision statement hash is stale")
    if decision.get("candidate") != candidate_ref or decision.get("qa_report") != qa_ref:
        errors.append("second-topic user decision media/QA binding is stale")
    qa_path = Path(str(qa_ref.get("path") or ""))
    visual_review = decision.get("visual_review")
    if not isinstance(visual_review, Mapping):
        errors.append("second-topic explicit visual review is missing")
    elif qa_path.is_file():
        try:
            qa = _mapping(read_json(qa_path), "second-topic QA")
            snapshots_path = Path(_mapping(
                qa.get("evidence"), "second-topic QA evidence",
            )["final_review_snapshots"])
            expected_snapshots = _path_inventory(
                snapshots_path, "final_review_snapshots",
            )
        except (OSError, ValueError, json.JSONDecodeError, PortraitGoldenError) as error:
            errors.append(f"second-topic explicit visual review cannot be rebound: {error}")
        else:
            if (
                visual_review.get("face_hand_product_caption_occlusion") != "yes"
                or visual_review.get("snapshots") != expected_snapshots
            ):
                errors.append("second-topic explicit visual review binding is stale")
    return errors


def _first_topic_authority(golden: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(golden.get("selected_style_reel"), "first-topic selected Style Reel")
    plan_ref = _mapping(selected.get("plan"), "first-topic Style Reel plan")
    plan = _mapping(read_json(Path(str(plan_ref.get("path") or ""))), "first-topic Style Reel plan")
    basis = _mapping(plan.get("comparison_basis"), "first-topic comparison basis")
    source = _mapping(basis.get("source"), "first-topic source")
    event_ids = basis.get("semantic_event_ids")
    if not isinstance(event_ids, list) or not event_ids or any(
        not isinstance(value, str) or not value for value in event_ids
    ):
        raise PortraitGoldenError("first-topic semantic event authority is invalid")
    return {
        "source_sha256": source.get("sha256"),
        "semantic_event_ids": list(event_ids),
        "semantic_inventory_sha256": _stable_hash(event_ids),
    }


def _second_topic_authority(
    qa: Mapping[str, Any], storyboard: Mapping[str, Any],
) -> dict[str, Any]:
    events = storyboard.get("events")
    if not isinstance(events, list) or not events:
        raise PortraitGoldenError("second-topic storyboard event authority is invalid")
    ids = [
        str(row.get("semantic_event_id") or row.get("id") or "")
        for row in events if isinstance(row, Mapping) and row.get("treatment") != "quiet_source"
    ]
    source_rows = [
        row.get("portrait_source_media") for row in events
        if isinstance(row, Mapping) and row.get("treatment") != "quiet_source"
    ]
    if not ids or any(not value for value in ids) or len(set(ids)) != len(ids):
        raise PortraitGoldenError("second-topic semantic event authority is invalid")
    if not source_rows or not all(isinstance(row, Mapping) for row in source_rows):
        raise PortraitGoldenError("second-topic source-media authority is missing")
    hashes = {str(row.get("sha256") or "") for row in source_rows if isinstance(row, Mapping)}
    if len(hashes) != 1 or not next(iter(hashes), ""):
        raise PortraitGoldenError("second-topic source-media authority is inconsistent")
    qa_ids = [
        str(row.get("id") or "") for row in (qa.get("semantic_events") or [])
        if isinstance(row, Mapping)
    ]
    if qa_ids != ids:
        raise PortraitGoldenError("second-topic QA event inventory is stale")
    return {
        "source_sha256": next(iter(hashes)),
        "semantic_event_ids": ids,
        "semantic_inventory_sha256": _stable_hash(ids),
    }


def _write_json(root: Path, relative: Path, payload: Mapping[str, Any]) -> Path:
    target = safe_generated_target(root, relative)
    atomic_write_text(target, json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False,
    ) + "\n")
    return target.resolve()


def _git_head(repository_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise PortraitGoldenError(f"cannot resolve implementation Git HEAD: {result.stderr.strip()}")
    value = result.stdout.strip().lower()
    if len(value) != 40:
        raise PortraitGoldenError("implementation Git HEAD is malformed")
    return value


def _git_is_ancestor(repository_root: Path, ancestor: str, descendant: str) -> bool:
    if not all(isinstance(value, str) and len(value) == 40 for value in (ancestor, descendant)):
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository_root, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0


def _selected_reel(review: Mapping[str, Any], direction_id: str) -> Mapping[str, Any]:
    rows = [
        row for row in review.get("reels") or []
        if isinstance(row, Mapping) and row.get("direction_id") == direction_id
    ]
    if len(rows) != 1:
        raise PortraitGoldenError("approved review does not contain exactly one selected reel")
    return rows[0]


def _selected_technical(
    package: Mapping[str, Any], direction_id: str,
) -> tuple[Mapping[str, Any], Path]:
    ref = _mapping(package.get("technical_evidence"), "WP6 technical evidence ref")
    path = Path(str(ref.get("path") or "")).resolve()
    technical = _mapping(read_json(path), "WP6 technical evidence")
    rows = [
        row for row in technical.get("directions") or []
        if isinstance(row, Mapping) and row.get("direction_id") == direction_id
    ]
    if len(rows) != 1:
        raise PortraitGoldenError("WP6 technical evidence lacks the selected direction")
    return rows[0], path


def build_provisional_portrait_golden(
    *, repository_root: Path, project_id: str, project_config_path: Path,
    profile_path: Path, plan_path: Path, authority_manifest_path: Path,
    pending_review_path: Path, approved_review_path: Path,
    decision_receipt_path: Path, wp6_review_package_path: Path,
    contract_paths: Mapping[str, Path], context_path: Path,
    output_root: Path,
) -> dict[str, Path]:
    """Snapshot one approved real Style Reel without enabling production default."""
    repository_root = Path(repository_root).resolve()
    output_root = Path(os.path.abspath(output_root))
    approved_review = _mapping(read_json(Path(approved_review_path)), "approved Style Reel review")
    decision = _mapping(approved_review.get("user"), "approved Style Reel user decision")
    direction_id = str(decision.get("selected_direction_id") or "")
    if (
        approved_review.get("status") != "approved"
        or decision.get("actor") != "HongRun"
        or decision.get("decision") != "select"
        or direction_id not in DIRECTIONS
    ):
        raise PortraitGoldenError("provisional Golden requires one approved HongRun direction")
    review_errors = validate_style_reel_review(
        approved_review, plan_path=Path(plan_path),
        authority_manifest_path=Path(authority_manifest_path),
        contract_paths=contract_paths,
        decision_receipt_path=Path(decision_receipt_path),
        wp6_review_package_path=Path(wp6_review_package_path),
        pending_review_path=Path(pending_review_path),
    )
    if review_errors:
        raise PortraitGoldenError(
            "approved Style Reel is stale:\n- " + "\n- ".join(review_errors)
        )
    receipt = _mapping(read_json(Path(decision_receipt_path)), "Style Reel decision receipt")
    receipt_errors = validate_style_reel_user_decision_receipt(
        receipt, review=approved_review, plan_path=Path(plan_path),
        authority_manifest_path=Path(authority_manifest_path),
        contract_paths=contract_paths,
        wp6_review_package_path=Path(wp6_review_package_path),
    )
    if receipt_errors:
        raise PortraitGoldenError(
            "Style Reel decision receipt is stale:\n- " + "\n- ".join(receipt_errors)
        )

    profile = deepcopy(dict(_mapping(read_json(Path(profile_path)), "portrait brand profile")))
    profile_errors = validate_portrait_contract_schema("portrait-brand-profile", profile)
    if profile_errors:
        raise PortraitGoldenError("portrait profile is invalid:\n- " + "\n- ".join(profile_errors))
    if profile.get("profile_id") != "hongrun" or profile.get("direction") != direction_id:
        raise PortraitGoldenError("selected direction does not match the HongRun profile")
    profile["status"] = "provisional_golden"
    profile_snapshot_path = _write_json(
        output_root, Path("profile-snapshot.json"), profile,
    )

    package = _mapping(read_json(Path(wp6_review_package_path)), "WP6 Style Reel package")
    selected_reel = _selected_reel(approved_review, direction_id)
    selected_technical, technical_path = _selected_technical(package, direction_id)
    contract_path = Path(contract_paths[direction_id]).resolve()
    contract = _mapping(read_json(contract_path), "selected direction contract")
    if contract.get("direction_id") != direction_id:
        raise PortraitGoldenError("selected direction contract identity is stale")
    context = _mapping(read_json(Path(context_path)), "Style Reel review context")
    render_events = [
        row for row in context.get("events") or []
        if isinstance(row, Mapping) and row.get("decision") == "render"
    ]
    if not render_events:
        raise PortraitGoldenError("provisional Golden needs at least one rendered event")
    audition_refs = []
    for event in render_events:
        auditions = _mapping(event.get("audio_auditions"), "Style Reel audio auditions")
        audition_refs.append({
            "event_id": event.get("event_id"),
            "voice_sfx_off": auditions.get("voice_sfx_off"),
            "sfx_on": auditions.get("sfx_on"),
            "receipt": auditions.get("receipt"),
        })
    authorities = _mapping(
        _mapping(read_json(Path(authority_manifest_path)), "Style Reel authorities").get("authorities"),
        "Style Reel authority inventory",
    )
    source_hash = source_tree_sha256(repository_root)
    portrait_hash = portrait_implementation_sha256(repository_root)
    head = _git_head(repository_root)
    created_at = datetime.now(timezone.utc).isoformat()
    golden_body: dict[str, Any] = {
        "schema_version": 1,
        "kind": "hongrun_portrait_brand_provisional_golden",
        "status": "provisional_golden",
        "golden_id": f"{project_id}-{direction_id}-provisional-v1",
        "created_at": created_at,
        "project_id": project_id,
        "selected_direction_id": direction_id,
        "profile": {
            "source": _file_ref(Path(profile_path)),
            "snapshot": _file_ref(profile_snapshot_path),
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "status": "provisional_golden",
        },
        "configuration": _file_ref(Path(project_config_path)),
        "approval": {
            "pending_review": _file_ref(Path(pending_review_path)),
            "approved_review": _file_ref(Path(approved_review_path)),
            "decision_receipt": _file_ref(Path(decision_receipt_path)),
            "wp6_review_package": _file_ref(Path(wp6_review_package_path)),
            "actor": "HongRun",
            "answers": {
                key: decision.get(key) for key in (
                    "format_fit", "person_primary", "expressive_not_noisy",
                    "semantic_help", "sonic_fit", "repeat_use_willingness",
                )
            },
            "reason": decision.get("reason"),
            "reviewed_at": decision.get("reviewed_at"),
        },
        "selected_style_reel": {
            "plan": _file_ref(Path(plan_path)),
            "authority_manifest": _file_ref(Path(authority_manifest_path)),
            "contract": _file_ref(contract_path),
            "media": selected_reel.get("media"),
            "phase_evidence": selected_reel.get("phase_evidence"),
            "structural_fingerprint": contract.get("structural_fingerprint"),
            "observable_phase_inventory_sha256": _stable_hash(
                selected_reel.get("phase_evidence") or []
            ),
            "technical_evidence": _file_ref(technical_path),
            "hyperframes_index": selected_technical.get("hyperframes_index"),
            "hyperframes_check": selected_technical.get("hyperframes_check"),
            "visual_render": selected_technical.get("visual_render"),
            "post_exit": selected_technical.get("post_exit"),
        },
        "audio_identity": {
            "audio_plan": authorities.get("audio_plan"),
            "sonic_plan": authorities.get("sonic_plan"),
            "auditions": audition_refs,
        },
        "implementation": {
            "repository": str(repository_root),
            "base_commit": head,
            "source_tree_sha256": source_hash,
            "portrait_implementation_sha256": portrait_hash,
            "commit_contains_current_implementation": False,
            "commit_deferred_until_wp9": True,
        },
        "promotion": {
            "real_project_validation_count": 1,
            "required_real_project_count": 2,
            "production_default": False,
            "next_gate": "materially_different_hongrun_portrait_topic",
        },
        "explicit_limitations": [
            "This Golden applies only to the exact first real Style Reel evidence.",
            "The current implementation is not yet committed; source-tree hash is authoritative until WP9.",
            "Production default remains false until a second materially different topic is approved by HongRun.",
            "No full-video render, publication, deployment, commit, or push is authorized by this artifact.",
        ],
    }
    golden = {**golden_body, "integrity_sha256": _stable_hash(golden_body)}
    golden_path = _write_json(output_root, Path("portrait-golden.json"), golden)
    preference_body = {
        "schema_version": 1,
        "kind": "hongrun_portrait_brand_preference_candidate",
        "status": "pending_second_topic_validation",
        "candidate_id": f"{project_id}-{direction_id}-preference-v1",
        "created_at": created_at,
        "profile_id": profile["profile_id"],
        "profile_version": profile["profile_version"],
        "source_golden": _file_ref(golden_path),
        "explicit_user_inputs": {
            "selected_direction_id": direction_id,
            "answers": golden["approval"]["answers"],
            "reason": golden["approval"]["reason"],
            "decision_receipt": golden["approval"]["decision_receipt"],
        },
        "inferred_preferences": [],
        "auto_apply": False,
        "production_default": False,
        "next_gate": "second_topic_named_user_repeat_use_approval",
    }
    preference = {**preference_body, "integrity_sha256": _stable_hash(preference_body)}
    preference_path = _write_json(
        output_root, Path("portrait-preference-candidate.json"), preference,
    )
    return {
        "profile_snapshot": profile_snapshot_path,
        "golden": golden_path,
        "preference_candidate": preference_path,
    }


def validate_provisional_portrait_golden(
    golden: Any, *, repository_root: Path,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(golden, Mapping):
        return ["provisional portrait Golden must be a mapping"]
    required = {
        "schema_version", "kind", "status", "golden_id", "created_at", "project_id",
        "selected_direction_id", "profile", "configuration", "approval",
        "selected_style_reel", "audio_identity", "implementation", "promotion",
        "explicit_limitations", "integrity_sha256",
    }
    if set(golden) != required:
        errors.append("provisional portrait Golden fields are incomplete or unsupported")
    if not _integrity_matches(golden):
        errors.append("provisional portrait Golden integrity hash is stale")
    direction = golden.get("selected_direction_id")
    if (
        golden.get("schema_version") != 1
        or golden.get("kind") != "hongrun_portrait_brand_provisional_golden"
        or golden.get("status") != "provisional_golden"
        or direction not in DIRECTIONS
    ):
        errors.append("provisional portrait Golden identity/status is invalid")
    profile = golden.get("profile")
    if not isinstance(profile, Mapping):
        errors.append("provisional portrait Golden profile must be a mapping")
    else:
        errors.extend(_file_ref_errors(profile.get("source"), "Golden profile source"))
        errors.extend(_file_ref_errors(profile.get("snapshot"), "Golden profile snapshot"))
        snapshot_ref = profile.get("snapshot")
        if isinstance(snapshot_ref, Mapping):
            path = Path(str(snapshot_ref.get("path") or ""))
            if path.is_file():
                try:
                    snapshot = read_json(path)
                except (OSError, json.JSONDecodeError):
                    errors.append("Golden profile snapshot is invalid JSON")
                else:
                    errors.extend(validate_portrait_contract_schema(
                        "portrait-brand-profile", snapshot,
                    ))
                    if not isinstance(snapshot, Mapping) or (
                        snapshot.get("status") != "provisional_golden"
                        or snapshot.get("direction") != direction
                    ):
                        errors.append("Golden profile snapshot selection is stale")
    errors.extend(_file_ref_errors(golden.get("configuration"), "Golden project configuration"))
    approval = golden.get("approval")
    if not isinstance(approval, Mapping):
        errors.append("provisional portrait Golden approval must be a mapping")
    else:
        for field in ("pending_review", "approved_review", "decision_receipt", "wp6_review_package"):
            errors.extend(_file_ref_errors(approval.get(field), f"Golden approval {field}"))
        answers = approval.get("answers")
        if (
            approval.get("actor") != "HongRun"
            or not isinstance(answers, Mapping) or not answers
            or any(value != "yes" for value in answers.values())
        ):
            errors.append("provisional portrait Golden user approval is incomplete")
    selected = golden.get("selected_style_reel")
    if not isinstance(selected, Mapping):
        errors.append("provisional portrait Golden selected reel must be a mapping")
    else:
        for field in (
            "plan", "authority_manifest", "contract", "media", "technical_evidence",
            "hyperframes_index", "hyperframes_check", "visual_render",
        ):
            errors.extend(_file_ref_errors(selected.get(field), f"Golden selected reel {field}"))
        phases = selected.get("phase_evidence")
        if not isinstance(phases, list) or not phases:
            errors.append("Golden selected reel phase evidence is missing")
        else:
            phase_rows_valid = True
            for index, ref in enumerate(phases):
                errors.extend(_file_ref_errors(ref, f"Golden selected reel phase {index}"))
                if not isinstance(ref, Mapping):
                    phase_rows_valid = False
            if not phase_rows_valid:
                errors.append("Golden selected reel phase inventory is malformed")
            elif selected.get("observable_phase_inventory_sha256") != _stable_hash(phases):
                errors.append("Golden selected reel phase inventory is stale")
    audio = golden.get("audio_identity")
    if not isinstance(audio, Mapping):
        errors.append("provisional portrait Golden audio identity must be a mapping")
    else:
        for field in ("audio_plan", "sonic_plan"):
            errors.extend(_file_ref_errors(audio.get(field), f"Golden audio {field}"))
        auditions = audio.get("auditions")
        if not isinstance(auditions, list) or not auditions:
            errors.append("Golden audio audition inventory is missing")
        else:
            for index, row in enumerate(auditions):
                if not isinstance(row, Mapping):
                    errors.append(f"Golden audio audition {index} is malformed")
                    continue
                for field in ("voice_sfx_off", "sfx_on", "receipt"):
                    errors.extend(_file_ref_errors(
                        row.get(field), f"Golden audio audition {index} {field}",
                    ))
    implementation = golden.get("implementation")
    repository_root = Path(repository_root).resolve()
    if not isinstance(implementation, Mapping):
        errors.append("provisional portrait Golden implementation must be a mapping")
    else:
        if implementation.get("source_tree_sha256") != source_tree_sha256(repository_root):
            errors.append("provisional portrait Golden source tree is stale")
        if implementation.get("portrait_implementation_sha256") != portrait_implementation_sha256(repository_root):
            errors.append("provisional portrait Golden runtime implementation is stale")
        try:
            current_head = _git_head(repository_root)
        except PortraitGoldenError as error:
            errors.append(str(error))
        else:
            base_commit = implementation.get("base_commit")
            if not isinstance(base_commit, str) or not _git_is_ancestor(
                repository_root, base_commit, current_head,
            ):
                errors.append("provisional portrait Golden Git base is not an ancestor of current HEAD")
        if (
            implementation.get("commit_contains_current_implementation") is not False
            or implementation.get("commit_deferred_until_wp9") is not True
        ):
            errors.append("provisional portrait Golden overstates implementation commit maturity")
    promotion = golden.get("promotion")
    if not isinstance(promotion, Mapping) or (
        promotion.get("real_project_validation_count") != 1
        or promotion.get("required_real_project_count") != 2
        or promotion.get("production_default") is not False
    ):
        errors.append("provisional portrait Golden promotion boundary is invalid")
    return errors


def validate_portrait_preference_candidate(candidate: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(candidate, Mapping):
        return ["portrait preference candidate must be a mapping"]
    if not _integrity_matches(candidate):
        errors.append("portrait preference candidate integrity hash is stale")
    if (
        candidate.get("schema_version") != 1
        or candidate.get("kind") != "hongrun_portrait_brand_preference_candidate"
        or candidate.get("status") != "pending_second_topic_validation"
        or candidate.get("auto_apply") is not False
        or candidate.get("production_default") is not False
    ):
        errors.append("portrait preference candidate identity/status is invalid")
    errors.extend(_file_ref_errors(candidate.get("source_golden"), "preference source Golden"))
    explicit = candidate.get("explicit_user_inputs")
    if not isinstance(explicit, Mapping):
        errors.append("portrait preference explicit user inputs must be a mapping")
    else:
        if explicit.get("selected_direction_id") not in DIRECTIONS:
            errors.append("portrait preference selected direction is invalid")
        answers = explicit.get("answers")
        if not isinstance(answers, Mapping) or not answers or any(
            value != "yes" for value in answers.values()
        ):
            errors.append("portrait preference explicit answers are incomplete")
        errors.extend(_file_ref_errors(
            explicit.get("decision_receipt"), "preference decision receipt",
        ))
    if candidate.get("inferred_preferences") != []:
        errors.append("portrait preference candidate must not infer unstated preferences")
    return errors


def build_real_project_portrait_validation(
    *, repository_root: Path, provisional_golden_path: Path,
    preference_candidate_path: Path, second_topic_qa_path: Path,
    candidate_path: Path, actor: str, repeat_use_willingness: str,
    preference: str, reason: str, decision_text: str, thread_id: str,
    visual_review: Mapping[str, Any],
    output_root: Path, media_probe: MediaProbe | None = None,
) -> dict[str, Path]:
    """Record the second-topic user gate without enabling production default.

    The Codex task is the named-user interaction surface for WP8.  This receipt
    records the exact statement and binds it to current project bytes.  It does
    not claim a separate production-default approval.
    """
    repository_root = Path(repository_root).resolve()
    output_root = Path(output_root)
    probe = media_probe or _probe_video_media
    if actor != "HongRun":
        raise PortraitGoldenError("second-topic approval actor must be HongRun")
    if repeat_use_willingness != "yes":
        raise PortraitGoldenError("second-topic promotion requires repeat_use_willingness=yes")
    if preference != "candidate":
        raise PortraitGoldenError("second-topic promotion requires preference=candidate")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (reason, decision_text, thread_id)
    ):
        raise PortraitGoldenError("second-topic approval reason, statement, and thread are required")
    if (
        not isinstance(visual_review, Mapping)
        or visual_review.get("face_hand_product_caption_occlusion") != "yes"
    ):
        raise PortraitGoldenError(
            "second-topic promotion requires an explicit face/hand/product/caption visual review=yes"
        )

    golden = deepcopy(dict(_mapping(
        read_json(Path(provisional_golden_path)), "provisional portrait Golden",
    )))
    implementation = _mapping(golden.get("implementation"), "provisional Golden implementation")
    golden["implementation"] = {
        **dict(implementation),
        "base_commit": _git_head(repository_root),
        "source_tree_sha256": source_tree_sha256(repository_root),
        "portrait_implementation_sha256": portrait_implementation_sha256(repository_root),
        "commit_contains_current_implementation": False,
        "commit_deferred_until_wp9": True,
    }
    golden["integrity_sha256"] = _stable_hash({
        key: value for key, value in golden.items() if key != "integrity_sha256"
    })
    current_golden_path = _write_json(
        output_root, Path("first-topic-golden-current.json"), golden,
    )
    golden_errors = validate_provisional_portrait_golden(
        golden, repository_root=repository_root,
    )
    if golden_errors:
        raise PortraitGoldenError(
            "first-topic Golden is stale:\n- " + "\n- ".join(golden_errors)
        )

    preference_candidate = _mapping(
        read_json(Path(preference_candidate_path)), "portrait preference candidate",
    )
    preference_errors = validate_portrait_preference_candidate(preference_candidate)
    if preference_errors:
        raise PortraitGoldenError(
            "portrait preference candidate is stale:\n- " + "\n- ".join(preference_errors)
        )
    qa = _mapping(read_json(Path(second_topic_qa_path)), "second-topic QA")
    qa_errors = _second_topic_qa_errors(
        qa, candidate_path=Path(candidate_path), media_probe=probe,
    )
    if qa_errors:
        raise PortraitGoldenError(
            "second-topic QA is invalid:\n- " + "\n- ".join(qa_errors)
        )
    if qa.get("direction") != golden.get("selected_direction_id"):
        raise PortraitGoldenError("second-topic direction differs from the provisional Golden")

    first_authority = _first_topic_authority(golden)
    storyboard_path = Path(_mapping(qa.get("evidence"), "second-topic QA evidence")["storyboard"])
    second_authority = _second_topic_authority(
        qa, _mapping(read_json(storyboard_path), "second-topic storyboard"),
    )
    if (
        first_authority["source_sha256"] == second_authority["source_sha256"]
        or first_authority["semantic_inventory_sha256"]
        == second_authority["semantic_inventory_sha256"]
    ):
        raise PortraitGoldenError(
            "second-topic validation is not materially different in source and semantic authority"
        )

    evidence_rows = [
        _path_inventory(Path(raw_path), str(name))
        for name, raw_path in sorted(_mapping(qa.get("evidence"), "second-topic QA evidence").items())
    ]
    candidate_ref = _file_ref(Path(candidate_path))
    qa_ref = _file_ref(Path(second_topic_qa_path))
    decided_at = datetime.now(timezone.utc).isoformat()
    decision_body = {
        "schema_version": 1,
        "kind": "hongrun_portrait_second_topic_user_decision",
        "actor": "HongRun",
        "confirmation_method": "explicit_user_confirmation_hash_v1",
        "thread_id": thread_id.strip(),
        "repeat_use_willingness": "yes",
        "preference": "candidate",
        "reason": reason.strip(),
        "decision_text": decision_text.strip(),
        "decision_text_sha256": sha256(decision_text.strip().encode("utf-8")).hexdigest(),
        "candidate": candidate_ref,
        "qa_report": qa_ref,
        "visual_review": {
            "face_hand_product_caption_occlusion": visual_review[
                "face_hand_product_caption_occlusion"
            ],
            "snapshots": _path_inventory(
                Path(_mapping(qa.get("evidence"), "second-topic QA evidence")[
                    "final_review_snapshots"
                ]),
                "final_review_snapshots",
            ),
        },
        "decided_at": decided_at,
    }
    decision = _integrity_payload(decision_body)
    decision_path = _write_json(
        output_root, Path("second-topic-user-decision.json"), decision,
    )

    validation_body = {
        "schema_version": 1,
        "kind": "hongrun_portrait_brand_real_project_validation",
        "status": "pass",
        "maturity": "real_project_validated",
        "validation_id": f"{qa['candidate_id']}-repeat-use-v1",
        "created_at": decided_at,
        "profile_id": _mapping(golden.get("profile"), "Golden profile").get("profile_id"),
        "profile_version": _mapping(golden.get("profile"), "Golden profile").get("profile_version"),
        "direction": qa["direction"],
        "first_topic": {
            "topic_id": golden["project_id"],
            "golden": _file_ref(current_golden_path),
            "historical_golden": _file_ref(Path(provisional_golden_path)),
            "preference_candidate": _file_ref(Path(preference_candidate_path)),
            "named_user_status": "approved",
            "topic_authority": first_authority,
        },
        "second_topic": {
            "topic_id": qa["source_topic"],
            "candidate_id": qa["candidate_id"],
            "candidate": candidate_ref,
            "qa_report": qa_ref,
            "evidence": evidence_rows,
            "named_user_status": "approved",
            "topic_authority": second_authority,
        },
        "named_user_decision": {
            "actor": "HongRun",
            "repeat_use_willingness": "yes",
            "preference": "candidate",
            "reason": reason.strip(),
            "thread_id": thread_id.strip(),
            "decision_text_sha256": decision["decision_text_sha256"],
            "receipt": _file_ref(decision_path),
        },
        "implementation": {
            "repository": str(repository_root),
            "base_commit_before_wp9": _git_head(repository_root),
            "source_tree_sha256": source_tree_sha256(repository_root),
            "portrait_implementation_sha256": portrait_implementation_sha256(repository_root),
            "commit_deferred_until_wp9": True,
        },
        "promotion": {
            "real_project_validation_count": 2,
            "required_real_project_count": 2,
            "production_default": False,
            "next_gate": "separate_explicit_production_default_approval",
        },
        "inferred_preferences": [],
        "auto_apply": False,
    }
    validation = {
        **validation_body,
        "integrity_sha256": _stable_hash(validation_body),
    }
    validation_path = _write_json(
        output_root, Path("portrait-brand-real-project-validation.json"), validation,
    )
    validation_errors = validate_real_project_portrait_validation(
        validation, repository_root=repository_root, media_probe=probe,
    )
    if validation_errors:
        raise PortraitGoldenError(
            "real-project portrait validation is invalid:\n- "
            + "\n- ".join(validation_errors)
        )
    return {
        "first_topic_golden": current_golden_path,
        "user_decision": decision_path,
        "validation": validation_path,
    }


def validate_real_project_portrait_validation(
    receipt: Any, *, repository_root: Path,
    media_probe: MediaProbe | None = None,
) -> list[str]:
    """Revalidate the two-topic opt-in maturity receipt against current bytes."""
    if not isinstance(receipt, Mapping):
        return ["real-project portrait validation must be a mapping"]
    errors: list[str] = []
    if not _integrity_matches(receipt):
        errors.append("real-project portrait validation integrity hash is stale")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "hongrun_portrait_brand_real_project_validation"
        or receipt.get("status") != "pass"
        or receipt.get("maturity") != "real_project_validated"
        or receipt.get("direction") not in DIRECTIONS
    ):
        errors.append("real-project portrait validation identity/status is invalid")
    first = receipt.get("first_topic")
    second = receipt.get("second_topic")
    current_first_authority: Mapping[str, Any] | None = None
    current_second_authority: Mapping[str, Any] | None = None
    if not isinstance(first, Mapping):
        errors.append("first-topic validation must be a mapping")
    else:
        for field in ("golden", "historical_golden", "preference_candidate"):
            errors.extend(_file_ref_errors(first.get(field), f"first-topic {field}"))
        golden_ref = first.get("golden")
        if isinstance(golden_ref, Mapping):
            path = Path(str(golden_ref.get("path") or ""))
            if path.is_file():
                try:
                    golden = read_json(path)
                except (OSError, json.JSONDecodeError):
                    errors.append("first-topic Golden is invalid JSON")
                else:
                    errors.extend(validate_provisional_portrait_golden(
                        golden, repository_root=Path(repository_root),
                    ))
                    if isinstance(golden, Mapping):
                        try:
                            current_first_authority = _first_topic_authority(golden)
                        except (OSError, ValueError, json.JSONDecodeError, PortraitGoldenError) as error:
                            errors.append(f"first-topic authority cannot be recomputed: {error}")
                        if first.get("topic_id") != golden.get("project_id"):
                            errors.append("first-topic identity differs from current Golden")
        if first.get("named_user_status") != "approved":
            errors.append("first-topic named-user approval is incomplete")
        first_authority = first.get("topic_authority")
        if not isinstance(first_authority, Mapping):
            errors.append("first-topic material-difference authority is missing")
    if not isinstance(second, Mapping):
        errors.append("second-topic validation must be a mapping")
    else:
        for field in ("candidate", "qa_report"):
            errors.extend(_file_ref_errors(second.get(field), f"second-topic {field}"))
        evidence = second.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("second-topic evidence inventory is missing")
        else:
            labels = [
                str(row.get("label") or "") if isinstance(row, Mapping) else ""
                for row in evidence
            ]
            expected_labels = sorted((
                "semantic_brief", "motion_contracts", "storyboard", "renderer_payload",
                "hyperframes_index", "hyperframes_check", "phase_snapshots", "final_review_snapshots",
                "audio_evidence", "mix_receipt", "caption_receipt",
            ))
            if sorted(labels) != expected_labels:
                errors.append("second-topic evidence inventory is incomplete or duplicated")
            for row in evidence:
                label = str(row.get("label") or "") if isinstance(row, Mapping) else ""
                errors.extend(_path_inventory_errors(row, label or "second-topic evidence"))
        if isinstance(first, Mapping) and first.get("topic_id") == second.get("topic_id"):
            errors.append("second topic is not materially different from the first topic")
        first_authority = first.get("topic_authority") if isinstance(first, Mapping) else None
        second_authority = second.get("topic_authority")
        for label, authority in (("first", first_authority), ("second", second_authority)):
            if not isinstance(authority, Mapping):
                errors.append(f"{label}-topic material-difference authority is missing")
                continue
            ids = authority.get("semantic_event_ids")
            if (
                not isinstance(authority.get("source_sha256"), str)
                or len(authority["source_sha256"]) != 64
                or not isinstance(ids, list) or not ids
                or any(not isinstance(event_id, str) or not event_id.strip() for event_id in ids)
                or authority.get("semantic_inventory_sha256") != _stable_hash(ids)
            ):
                errors.append(f"{label}-topic material-difference authority is invalid")
        if isinstance(first_authority, Mapping) and isinstance(second_authority, Mapping) and (
            first_authority.get("source_sha256") == second_authority.get("source_sha256")
            or first_authority.get("semantic_inventory_sha256")
            == second_authority.get("semantic_inventory_sha256")
        ):
            errors.append("second topic is not materially different in source and semantic authority")
        if second.get("named_user_status") != "approved":
            errors.append("second-topic named-user approval is incomplete")
        candidate_ref = second.get("candidate")
        qa_ref = second.get("qa_report")
        if isinstance(candidate_ref, Mapping) and isinstance(qa_ref, Mapping):
            candidate_path = Path(str(candidate_ref.get("path") or ""))
            qa_path = Path(str(qa_ref.get("path") or ""))
            if qa_path.is_file():
                try:
                    qa = read_json(qa_path)
                except (OSError, json.JSONDecodeError):
                    errors.append("second-topic QA is invalid JSON")
                else:
                    errors.extend(_second_topic_qa_errors(
                        qa, candidate_path=candidate_path,
                        media_probe=media_probe or _probe_video_media,
                    ))
                    qa_evidence = qa.get("evidence") if isinstance(qa, Mapping) else None
                    if isinstance(qa_evidence, Mapping) and isinstance(evidence, list):
                        try:
                            expected_evidence = [
                                _path_inventory(Path(raw_path), str(name))
                                for name, raw_path in sorted(qa_evidence.items())
                            ]
                        except PortraitGoldenError as error:
                            errors.append(str(error))
                        else:
                            if evidence != expected_evidence:
                                errors.append("second-topic evidence inventory differs from current QA")
                    if isinstance(qa, Mapping) and qa.get("direction") != receipt.get("direction"):
                        errors.append("second-topic direction differs from validated direction")
                    if isinstance(qa, Mapping):
                        if second.get("topic_id") != qa.get("source_topic"):
                            errors.append("second-topic identity differs from current QA")
                        storyboard_raw = (
                            qa_evidence.get("storyboard")
                            if isinstance(qa_evidence, Mapping) else None
                        )
                        if isinstance(storyboard_raw, str):
                            try:
                                current_storyboard = _mapping(
                                    read_json(Path(storyboard_raw)), "second-topic storyboard",
                                )
                                current_second_authority = _second_topic_authority(
                                    qa, current_storyboard,
                                )
                            except (OSError, ValueError, json.JSONDecodeError, PortraitGoldenError) as error:
                                errors.append(f"second-topic authority cannot be recomputed: {error}")
    if isinstance(first, Mapping) and current_first_authority is not None and first.get(
        "topic_authority"
    ) != current_first_authority:
        errors.append("first-topic material-difference authority differs from current Golden")
    if isinstance(second, Mapping) and current_second_authority is not None and second.get(
        "topic_authority"
    ) != current_second_authority:
        errors.append("second-topic material-difference authority differs from current QA")
    decision = receipt.get("named_user_decision")
    if not isinstance(decision, Mapping):
        errors.append("second-topic named-user decision must be a mapping")
    else:
        if (
            decision.get("actor") != "HongRun"
            or decision.get("repeat_use_willingness") != "yes"
            or decision.get("preference") != "candidate"
            or not str(decision.get("reason") or "").strip()
            or not str(decision.get("thread_id") or "").strip()
        ):
            errors.append("second-topic named-user preference is invalid")
        errors.extend(_file_ref_errors(decision.get("receipt"), "second-topic user decision receipt"))
        decision_ref = decision.get("receipt")
        if isinstance(decision_ref, Mapping) and isinstance(second, Mapping):
            path = Path(str(decision_ref.get("path") or ""))
            candidate_ref = second.get("candidate")
            qa_ref = second.get("qa_report")
            if path.is_file() and isinstance(candidate_ref, Mapping) and isinstance(qa_ref, Mapping):
                try:
                    persisted = read_json(path)
                except (OSError, json.JSONDecodeError):
                    errors.append("second-topic user decision receipt is invalid JSON")
                else:
                    errors.extend(_second_topic_decision_errors(
                        persisted, candidate_ref=candidate_ref, qa_ref=qa_ref,
                    ))
                    if isinstance(persisted, Mapping) and any(
                        persisted.get(field) != decision.get(field)
                        for field in (
                            "actor", "repeat_use_willingness", "preference", "reason",
                            "thread_id", "decision_text_sha256",
                        )
                    ):
                        errors.append("second-topic named-user summary differs from its receipt")
    implementation = receipt.get("implementation")
    if not isinstance(implementation, Mapping) or implementation.get(
        "source_tree_sha256"
    ) != source_tree_sha256(Path(repository_root).resolve()) or implementation.get(
        "portrait_implementation_sha256"
    ) != portrait_implementation_sha256(Path(repository_root).resolve()):
        errors.append("real-project portrait validation source tree is stale")
    promotion = receipt.get("promotion")
    if not isinstance(promotion, Mapping) or (
        promotion.get("real_project_validation_count") != 2
        or promotion.get("required_real_project_count") != 2
        or promotion.get("production_default") is not False
        or promotion.get("next_gate") != "separate_explicit_production_default_approval"
    ):
        errors.append("real-project validation must not claim production default")
    if receipt.get("inferred_preferences") != [] or receipt.get("auto_apply") is not False:
        errors.append("real-project validation must not infer or auto-apply preferences")
    return errors


def build_retained_real_project_portrait_validation(
    *, live_validation_path: Path, output_path: Path, repository_root: Path,
    media_probe: MediaProbe | None = None,
) -> dict[str, Any]:
    """Retain a portable maturity receipt without copying private media."""
    live_path = Path(live_validation_path).resolve()
    live = _mapping(read_json(live_path), "live portrait validation")
    live_errors = validate_real_project_portrait_validation(
        live, repository_root=Path(repository_root),
        media_probe=media_probe or _probe_video_media,
    )
    if live_errors:
        raise PortraitGoldenError(
            "live portrait validation is stale:\n- " + "\n- ".join(live_errors)
        )
    first = _mapping(live.get("first_topic"), "live first-topic validation")
    second = _mapping(live.get("second_topic"), "live second-topic validation")
    decision = _mapping(live.get("named_user_decision"), "live named-user decision")
    candidate = _mapping(second.get("candidate"), "live second-topic candidate")
    qa = _mapping(second.get("qa_report"), "live second-topic QA")
    decision_receipt = _mapping(decision.get("receipt"), "live second-topic decision receipt")
    promotion = _mapping(live.get("promotion"), "live promotion boundary")
    body = {
        "schema_version": 1,
        "kind": "hongrun_portrait_brand_retained_real_project_validation",
        "status": "pass",
        "maturity": "real_project_validated",
        "validation_id": live.get("validation_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile_id": live.get("profile_id"),
        "profile_version": live.get("profile_version"),
        "direction": live.get("direction"),
        "topics": [first.get("topic_id"), second.get("topic_id")],
        "named_user": {
            "actor": decision.get("actor"),
            "repeat_use_willingness": decision.get("repeat_use_willingness"),
            "preference": decision.get("preference"),
            "decision_receipt_sha256": decision_receipt.get("sha256"),
        },
        "evidence_sha256": {
            "live_validation": sha256_file(live_path),
            "second_topic_candidate": candidate.get("sha256"),
            "second_topic_qa": qa.get("sha256"),
        },
        "live_validation": _file_ref(live_path),
        "implementation": {
            "source_tree_sha256": source_tree_sha256(Path(repository_root).resolve()),
            "portrait_implementation_sha256": portrait_implementation_sha256(
                Path(repository_root).resolve()
            ),
        },
        "promotion": dict(promotion),
        "production_default_approval": "not_provided",
        "limitations": [
            "Private real-project media remains in the authorized local validation projects.",
            "This retained receipt proves two-topic named-user reuse validation, not production-default approval.",
        ],
    }
    retained = {**body, "integrity_sha256": _stable_hash(body)}
    repository_root = Path(repository_root).resolve()
    target = Path(os.path.abspath(output_path))
    try:
        relative = target.relative_to(repository_root)
    except ValueError as error:
        raise PortraitGoldenError(
            "retained portrait validation must stay inside the repository"
        ) from error
    target = safe_generated_target(repository_root, relative)
    atomic_write_text(target, json.dumps(
        retained, ensure_ascii=False, indent=2, allow_nan=False,
    ) + "\n")
    return retained


def validate_retained_real_project_portrait_validation(
    receipt: Any, *, repository_root: Path,
) -> list[str]:
    """Validate the portable, source-bound two-topic maturity receipt."""
    if not isinstance(receipt, Mapping):
        return ["retained portrait validation must be a mapping"]
    errors: list[str] = []
    if not _integrity_matches(receipt):
        errors.append("retained portrait validation integrity hash is stale")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "hongrun_portrait_brand_retained_real_project_validation"
        or receipt.get("status") != "pass"
        or receipt.get("maturity") != "real_project_validated"
        or receipt.get("profile_id") != "hongrun"
        or receipt.get("direction") not in DIRECTIONS
    ):
        errors.append("retained portrait validation identity/status is invalid")
    topics = receipt.get("topics")
    valid_topics = (
        isinstance(topics, list) and len(topics) == 2
        and all(isinstance(value, str) and value.strip() for value in topics)
    )
    if not valid_topics or len(set(topics if valid_topics else [])) != 2:
        errors.append("retained portrait validation requires two distinct topics")
    named_user = receipt.get("named_user")
    if not isinstance(named_user, Mapping) or (
        named_user.get("actor") != "HongRun"
        or named_user.get("repeat_use_willingness") != "yes"
        or named_user.get("preference") != "candidate"
    ):
        errors.append("retained portrait named-user decision is invalid")
    hashes = receipt.get("evidence_sha256")
    if not isinstance(hashes, Mapping) or any(
        not isinstance(hashes.get(name), str) or len(hashes[name]) != 64
        or any(character not in "0123456789abcdef" for character in hashes[name].lower())
        for name in ("live_validation", "second_topic_candidate", "second_topic_qa")
    ):
        errors.append("retained portrait evidence hashes are incomplete")
    live_ref = receipt.get("live_validation")
    errors.extend(_file_ref_errors(live_ref, "retained live validation"))
    if isinstance(live_ref, Mapping):
        live_path = Path(str(live_ref.get("path") or ""))
        if live_path.is_file():
            try:
                live = read_json(live_path)
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append("retained live validation is invalid JSON")
            else:
                errors.extend(validate_real_project_portrait_validation(
                    live, repository_root=Path(repository_root),
                ))
                if isinstance(hashes, Mapping) and hashes.get("live_validation") != sha256_file(live_path):
                    errors.append("retained live validation digest is stale")
                if isinstance(live, Mapping):
                    expected_topics = [
                        (live.get("first_topic") or {}).get("topic_id")
                        if isinstance(live.get("first_topic"), Mapping) else None,
                        (live.get("second_topic") or {}).get("topic_id")
                        if isinstance(live.get("second_topic"), Mapping) else None,
                    ]
                    if topics != expected_topics:
                        errors.append("retained topic summary differs from live validation")
                    live_second = live.get("second_topic")
                    if isinstance(live_second, Mapping) and isinstance(hashes, Mapping):
                        live_candidate = live_second.get("candidate")
                        live_qa = live_second.get("qa_report")
                        if not isinstance(live_candidate, Mapping) or hashes.get(
                            "second_topic_candidate"
                        ) != live_candidate.get("sha256"):
                            errors.append("retained candidate digest differs from live validation")
                        if not isinstance(live_qa, Mapping) or hashes.get(
                            "second_topic_qa"
                        ) != live_qa.get("sha256"):
                            errors.append("retained QA digest differs from live validation")
    implementation = receipt.get("implementation")
    if not isinstance(implementation, Mapping) or implementation.get(
        "source_tree_sha256"
    ) != source_tree_sha256(Path(repository_root).resolve()) or implementation.get(
        "portrait_implementation_sha256"
    ) != portrait_implementation_sha256(Path(repository_root).resolve()):
        errors.append("retained portrait validation source tree is stale")
    promotion = receipt.get("promotion")
    if not isinstance(promotion, Mapping) or (
        promotion.get("real_project_validation_count") != 2
        or promotion.get("required_real_project_count") != 2
        or promotion.get("production_default") is not False
        or promotion.get("next_gate") != "separate_explicit_production_default_approval"
        or receipt.get("production_default_approval") != "not_provided"
    ):
        errors.append("retained portrait validation must not claim production default")
    return errors
