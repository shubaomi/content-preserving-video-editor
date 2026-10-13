"""Explicit same-frame pixel parity; does not claim rendered DOM measurements."""
from __future__ import annotations

import math
import json
import re
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity

from director_contracts import read_json, sha256_file, write_json
from renderer_project_manifest import validate_manifest
from motion_editorial import RECIPES

PHASES = ("entrance", "mid", "pre_exit", "post_exit")
PROFILE_LIMITS = {
    "software_rgb_3_0035": {"source_rgb_mae_max": 3.0, "source_fraction_any_channel_gt20_max": .035},
    "portrait_ssim_095": {"full_rgb_ssim_min": .95},
}
SSIM_ALGORITHMS = {"software_rgb_3_0035": "skimage_rgb_default_7x7", "portrait_ssim_095": "ffmpeg_ssim_all_rgb"}


def expected_profile(storyboard: Mapping[str, Any]) -> str | None:
    families = {event.get("editorial_recipe_id") for event in storyboard.get("events") or []}
    if families and families.issubset(RECIPES["professional_software_demo"]):
        return "software_rgb_3_0035"
    if families and families.issubset(RECIPES["authentic_product_editorial"]):
        return "portrait_ssim_095"
    return None


def probe_render(path: Path) -> dict[str, Any]:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=30)
    stream = json.loads(result.stdout)["streams"][0]
    numerator, denominator = map(int, stream["r_frame_rate"].split("/"))
    return {"width": int(stream["width"]), "height": int(stream["height"]), "fps": numerator/denominator}


def ffmpeg_ssim(studio: Path, rendered: Path) -> float:
    """Retain portrait's existing FFmpeg RGB PNG SSIM All measurement."""
    result = subprocess.run(["ffmpeg", "-nostdin", "-xerror", "-i", str(studio), "-i", str(rendered),
                             "-lavfi", "ssim", "-f", "null", "-"], capture_output=True, text=True, check=True, timeout=30)
    matches = re.findall(r"All:([0-9]+(?:\.[0-9]+)?)", result.stderr)
    if len(matches) != 1:
        raise ValueError("FFmpeg SSIM did not return exactly one All metric")
    return float(matches[0])


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _ref_errors(ref: Any, label: str, expected: Path | None = None) -> list[str]:
    if not isinstance(ref, dict):
        return [f"{label}: missing artifact reference"]
    path = Path(str(ref.get("path") or ""))
    if not path.is_absolute() or not path.is_file():
        return [f"{label}: artifact missing or path not absolute"]
    if expected is not None and path.resolve() != expected.resolve():
        return [f"{label}: unexpected artifact path"]
    if ref.get("sha256") != sha256_file(path):
        return [f"{label}: stale artifact hash"]
    return []


def _pixels(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        image.load()
        return np.asarray(image.convert("RGB"))


def decode_selected_frames(raw_render: Path, frames: list[int]) -> dict[int, np.ndarray]:
    """One real decode per validation, never an unbound persistent PNG cache."""
    selected = sorted(set(frames))
    if not selected or any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in selected):
        raise ValueError("invalid selected frame numbers")
    with tempfile.TemporaryDirectory(prefix="cpve-parity-") as folder:
        root = Path(folder)
        expression = "+".join(f"eq(n\\,{n})" for n in selected)
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-xerror", "-v", "error", "-i", str(raw_render),
             "-vf", "select=" + expression, "-vsync", "0", "-frames:v", str(len(selected)),
             str(root / "%06d.png")], capture_output=True, text=True, timeout=180, check=False,
        )
        if result.returncode != 0 or result.stderr.strip():
            raise ValueError("raw render frame decode failed: " + result.stderr.strip())
        images = sorted(root.glob("*.png"))
        if len(images) != len(selected):
            raise ValueError("raw render lacks requested exact frames")
        return {frame: _pixels(path) for frame, path in zip(selected, images)}


def pixel_metrics(studio: np.ndarray, rendered: np.ndarray, source_area: list[int]) -> dict[str, float]:
    if studio.shape != rendered.shape or studio.ndim != 3 or studio.shape[2] != 3 or min(studio.shape[:2]) < 7:
        raise ValueError("pixel pair dimensions differ or are too small for SSIM")
    x, y, width, height = source_area
    if min(x, y) < 0 or min(width, height) <= 0 or x+width > studio.shape[1] or y+height > studio.shape[0]:
        raise ValueError("source area escapes pixel canvas")
    diff = np.abs(studio.astype(np.float64)-rendered.astype(np.float64))
    source = diff[y:y+height, x:x+width]
    return {"full_rgb_mae": float(diff.mean()), "source_rgb_mae": float(source.mean()),
            "source_fraction_any_channel_gt20": float((source.max(axis=2)>20).mean()),
            "full_rgb_ssim": float(structural_similarity(studio, rendered, channel_axis=2, data_range=255))}


def validate_pixel_parity(report: dict[str, Any], storyboard: dict[str, Any],
                          expected_bindings: Mapping[str, Path] | None,
                          keyframe_receipt_paths: Mapping[str, Path] | None) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 2 or report.get("measurement_method") != "same_frame_pixels_v1":
        errors.append("pixel parity requires explicit schema2 same_frame_pixels_v1")
    if report.get("status") != "pass":
        errors.append("pixel parity status must be pass")
    profile = report.get("profile")
    if profile not in PROFILE_LIMITS or report.get("limits") != PROFILE_LIMITS.get(profile):
        errors.append("pixel parity fixed profile/limits missing or altered")
    if report.get("ssim_algorithm") != SSIM_ALGORITHMS.get(profile):
        errors.append("pixel parity SSIM algorithm differs from fixed profile")
    if expected_bindings is None or keyframe_receipt_paths is None:
        return [*errors, "pixel parity requires current inputs and keyframe receipts"]
    if "raw_render" not in expected_bindings:
        errors.append("pixel parity requires caller-bound actual raw_render")
    for key in ("project_artifact", "motion_design_contract", "source_media"):
        if key not in expected_bindings:
            errors.append(f"missing expected {key}")
        else:
            errors.extend(_ref_errors((report.get("inputs") or {}).get(key), key, Path(expected_bindings[key])))
    errors.extend(_ref_errors(report.get("renderer_export"), "renderer export"))
    errors.extend(_ref_errors(report.get("raw_render"), "raw render", expected_bindings.get("raw_render")))
    fps = report.get("fps")
    composition = storyboard.get("composition") or {}
    if not _number(fps) or fps <= 0 or fps != composition.get("fps"):
        errors.append("pixel parity fps differs from current composition")
    area = report.get("source_area")
    if not isinstance(area, list) or len(area) != 4 or any(not isinstance(v, int) or isinstance(v, bool) for v in area) or min(area[:2]) < 0 or min(area[2:]) <= 0:
        errors.append("pixel parity requires integer source area")
    if errors:
        return errors
    try:
        manifest_path = Path(report["inputs"]["project_artifact"]["path"])
        manifest = read_json(manifest_path)
        errors.extend(validate_manifest(manifest, manifest_path))
        current_storyboard = read_json(Path(manifest["project_root"]) / "storyboard.json")
        if current_storyboard != storyboard:
            errors.append("pixel parity Storyboard is not current manifest-owned source")
        if expected_profile(current_storyboard) is None or profile != expected_profile(current_storyboard):
            errors.append("pixel parity profile differs from approved editorial recipe family")
    except (OSError, ValueError):
        errors.append("pixel parity project manifest unreadable")
    if errors:
        return errors
    try:
        exported = read_json(Path(report["renderer_export"]["path"]))
    except (OSError, ValueError) as exc:
        return [f"renderer export unreadable: {exc}"]
    inputs = report["inputs"]
    if exported.get("project_artifact") != inputs["project_artifact"] or exported.get("motion_design_contract_sha256") != inputs["motion_design_contract"]["sha256"] or exported.get("source_media_sha256") != inputs["source_media"]["sha256"]:
        errors.append("pixel parity renderer export input bindings differ")
    event_ids = [str(e.get("semantic_event_id") or e.get("id") or "") for e in storyboard.get("events") or []]
    exported_events = exported.get("events") or []
    if not event_ids or len(set(event_ids)) != len(event_ids) or [e.get("event_id") for e in exported_events] != event_ids or set(keyframe_receipt_paths) != set(event_ids):
        errors.append("pixel parity event/receipt/export inventory mismatch")
    samples = report.get("samples") or []
    expected_keys = [(ident, phase) for ident in event_ids for phase in PHASES]
    if [(s.get("event_id"), s.get("phase")) for s in samples] != expected_keys:
        errors.append("pixel parity requires ordered four phases for every event")
    if errors:
        return errors
    phases = {(event["event_id"], p["phase"]): p for event in exported_events for p in event.get("phases") or []}
    receipts: dict[str, Any] = {}
    for ident, path in keyframe_receipt_paths.items():
        try:
            receipt = read_json(Path(path))
        except (OSError, ValueError):
            errors.append(f"{ident}: keyframe receipt unreadable")
            continue
        receipts[ident] = receipt
        if receipt.get("event_id") != ident or receipt.get("project_artifact") != inputs["project_artifact"] or (receipt.get("input_hashes") or {}).get("motion_design_contract_sha256") != inputs["motion_design_contract"]["sha256"]:
            errors.append(f"{ident}: receipt input binding mismatch")
        if [p.get("phase") for p in receipt.get("phase_observations") or []] != list(PHASES):
            errors.append(f"{ident}: receipt phase inventory mismatch")
    for sample in samples:
        ident, phase = sample["event_id"], sample["phase"]
        key = f"{ident}/{phase}"
        expected = phases.get((ident, phase))
        observations = {p.get("phase"): p for p in receipts.get(ident, {}).get("phase_observations") or []}
        observation = observations.get(phase)
        if expected is None or observation is None:
            errors.append(key + ": phase absent from export/receipt")
            continue
        frame, timestamp = sample.get("frame"), sample.get("timestamp_seconds")
        if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0 or not _number(timestamp) or abs(frame/fps-timestamp) > 1e-9 or timestamp != expected.get("timestamp_seconds") or timestamp != observation.get("timestamp_seconds"):
            errors.append(key + ": exact integer frame/export/receipt time mismatch")
        for field in ("studio_snapshot", "render_snapshot"):
            errors.extend(_ref_errors(sample.get(field), key + " " + field))
        errors.extend(_ref_errors(sample.get("keyframe_receipt"), key + " receipt", Path(keyframe_receipt_paths[ident])))
        if sample.get("studio_snapshot") != expected.get("snapshot") or sample.get("studio_snapshot") != observation.get("snapshot"):
            errors.append(key + ": Studio snapshot differs from export/receipt")
        if profile == "software_rgb_3_0035":
            source = (expected.get("actual_DOM_detail") or {}).get("source") or {}
            if [source.get(k) for k in ("x", "y", "width", "height")] != area:
                errors.append(key + ": source ROI differs from measured export source DOM")
        elif area != [0, 0, composition.get("width"), composition.get("height")]:
            errors.append(key + ": portrait SSIM must cover the full canvas")
    if errors:
        return errors
    raw = Path(report["raw_render"]["path"])
    try:
        probe = probe_render(raw)
        if any(probe[key] != composition.get(key) for key in ("width", "height", "fps")):
            return ["raw render probe differs from composition dimensions/fps"]
        decoded = decode_selected_frames(raw, [s["frame"] for s in samples])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return ["pixel parity cannot verify actual raw frames: " + str(exc)]
    for sample in samples:
        label = sample["event_id"] + "/" + sample["phase"]
        try:
            studio, rendered = _pixels(Path(sample["studio_snapshot"]["path"])), _pixels(Path(sample["render_snapshot"]["path"]))
            expected_shape = (composition.get("height"), composition.get("width"), 3)
            if studio.shape != expected_shape or rendered.shape != expected_shape:
                errors.append(label + ": image size differs from composition")
                continue
            if sample["frame"] not in decoded or not np.array_equal(rendered, decoded[sample["frame"]]):
                errors.append(label + ": render PNG is not raw video's exact selected frame")
                continue
            metrics = pixel_metrics(studio, rendered, area)
            if profile == "portrait_ssim_095":
                metrics["full_rgb_ssim"] = ffmpeg_ssim(Path(sample["studio_snapshot"]["path"]), Path(sample["render_snapshot"]["path"]))
            for name, actual in metrics.items():
                if not _number(sample.get(name)) or abs(sample[name]-actual) > 1e-6:
                    errors.append(label + ": declared metric differs from recomputed " + name)
            if profile == "software_rgb_3_0035" and (metrics["source_rgb_mae"] > 3 or metrics["source_fraction_any_channel_gt20"] > .035):
                errors.append(label + ": software pixel threshold exceeded")
            if profile == "portrait_ssim_095" and metrics["full_rgb_ssim"] < .95:
                errors.append(label + ": portrait same-frame SSIM below .95")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            errors.append(label + ": pixel comparison failed: " + str(exc))
    # Long video decode must not permit mutable inputs to drift during validation.
    for key, value in report["inputs"].items():
        errors.extend(_ref_errors(value, key))
    errors.extend(_ref_errors(report["raw_render"], "raw render after decode"))
    errors.extend(_ref_errors(report["renderer_export"], "renderer export after decode"))
    for sample in samples:
        for key in ("studio_snapshot", "render_snapshot", "keyframe_receipt"):
            errors.extend(_ref_errors(sample[key], key + " after decode"))
    return errors


def build_pixel_parity_report(*, storyboard_path: Path, motion_contract_path: Path, project_artifact: Path,
                              renderer_export_path: Path, raw_render: Path, keyframe_receipt_dir: Path,
                              profile: str, output_path: Path) -> dict[str, Any]:
    """Small shared owner helper; decodes real frames, validates before writing pass."""
    if profile not in PROFILE_LIMITS:
        raise ValueError("unknown fixed pixel profile")
    storyboard, contract, export = read_json(storyboard_path), read_json(motion_contract_path), read_json(renderer_export_path)
    ref = lambda p: {"path": str(p.resolve()), "sha256": sha256_file(p)}
    inputs = {"project_artifact": project_artifact, "motion_design_contract": motion_contract_path,
              "source_media": Path(contract["source_media"]["path"])}
    fps = storyboard["composition"]["fps"]
    pairs = [(event, phase) for event in export["events"] for phase in event["phases"]]
    frames = [round(phase["timestamp_seconds"]*fps) for _, phase in pairs]
    if any(abs(frame/fps-phase["timestamp_seconds"]) > 1e-9 for frame, (_, phase) in zip(frames, pairs)):
        raise ValueError("export contains non-integer-frame sampling times")
    decoded = decode_selected_frames(raw_render, frames)
    frame_dir = output_path.parent / (output_path.stem + "-frames")
    frame_dir.mkdir(parents=True, exist_ok=False)
    if profile == "software_rgb_3_0035":
        source = pairs[0][1]["actual_DOM_detail"]["source"]
        area = [int(source[key]) for key in ("x", "y", "width", "height")]
    else:
        area = [0, 0, storyboard["composition"]["width"], storyboard["composition"]["height"]]
    samples = []
    receipt_paths = {}
    for index, ((event, phase), frame) in enumerate(zip(pairs, frames)):
        rendered = frame_dir / f"{index:03d}-{frame}.png"
        Image.fromarray(decoded[frame]).save(rendered)
        studio = Path(phase["snapshot"]["path"])
        metrics = pixel_metrics(_pixels(studio), decoded[frame], area)
        if profile == "portrait_ssim_095":
            metrics["full_rgb_ssim"] = ffmpeg_ssim(studio, rendered)
        receipt = keyframe_receipt_dir / (event["event_id"] + ".json")
        receipt_paths[event["event_id"]] = receipt
        samples.append({"event_id": event["event_id"], "phase": phase["phase"], "frame": frame,
                        "timestamp_seconds": phase["timestamp_seconds"], "studio_snapshot": phase["snapshot"],
                        "render_snapshot": ref(rendered), "keyframe_receipt": ref(receipt), **metrics})
    report = {"schema_version": 2, "measurement_method": "same_frame_pixels_v1", "status": "pass",
              "profile": profile, "limits": PROFILE_LIMITS[profile].copy(), "ssim_algorithm": SSIM_ALGORITHMS[profile],
              "inputs": {key: ref(path) for key, path in inputs.items()}, "renderer_export": ref(renderer_export_path),
              "raw_render": ref(raw_render), "fps": fps, "source_area": area, "samples": samples,
              "measurement_scope": "Decoded same-frame pixels; no rendered-DOM geometry claim. Geometry/protection remain receipt/export obligations."}
    errors = validate_pixel_parity(report, storyboard, {**inputs, "raw_render": raw_render}, receipt_paths)
    if errors:
        write_json(output_path.with_suffix(".failed.json"), {**report, "status": "failed", "errors": errors})
        raise ValueError("; ".join(errors))
    write_json(output_path, report)
    return report
