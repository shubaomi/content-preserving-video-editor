#!/usr/bin/env python3
"""Build a hash-bound Studio/final-render parity report from paired images."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

from director_contracts import read_json, sha256_file, write_json
from preview_render_parity import validate


PHASES = ("entrance", "mid", "pre_exit", "post_exit")


def _open_rgb(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError(f"parity snapshot is not a decodable image: {path}") from error


def _similarity(left: Image.Image, right: Image.Image) -> float:
    if left.size != right.size:
        return 0.0
    difference = ImageChops.difference(left, right)
    mean_absolute = sum(ImageStat.Stat(difference).mean) / 3.0
    return max(0.0, 1.0 - mean_absolute / 255.0)


def _pixel_box(normalized: Mapping[str, Any], width: int, height: int) -> dict[str, float]:
    return {
        "x": float(normalized.get("x", 0)) * width,
        "y": float(normalized.get("y", 0)) * height,
        "width": float(normalized.get("width", 0)) * width,
        "height": float(normalized.get("height", 0)) * height,
    }


def _registered_geometry(
    studio: Image.Image,
    rendered: Image.Image,
    studio_box: Mapping[str, float],
    *,
    position_tolerance: float,
    minimum_similarity: float,
) -> tuple[dict[str, float], float, int, int]:
    if studio.size != rendered.size:
        raise ValueError("Studio/render snapshot dimensions differ")
    width, height = studio.size
    box_width = float(studio_box["width"])
    box_height = float(studio_box["height"])
    if box_width <= 0 or box_height <= 0:
        similarity = _similarity(studio, rendered)
        if similarity < minimum_similarity:
            raise ValueError("post-exit Studio/render image registration is below threshold")
        return dict(studio_box), similarity, 0, 0

    padding = 8
    left = max(0, int(math.floor(float(studio_box["x"]))) - padding)
    top = max(0, int(math.floor(float(studio_box["y"]))) - padding)
    right = min(
        width,
        int(math.ceil(float(studio_box["x"]) + box_width)) + padding,
    )
    bottom = min(
        height,
        int(math.ceil(float(studio_box["y"]) + box_height)) + padding,
    )
    studio_crop = studio.crop((left, top, right, bottom))
    search = max(1, int(math.ceil(position_tolerance)) + 1)
    best: tuple[float, int, int] | None = None
    for delta_y in range(-search, search + 1):
        for delta_x in range(-search, search + 1):
            candidate = (left + delta_x, top + delta_y, right + delta_x, bottom + delta_y)
            if candidate[0] < 0 or candidate[1] < 0 or candidate[2] > width or candidate[3] > height:
                continue
            score = _similarity(studio_crop, rendered.crop(candidate))
            if best is None or score > best[0]:
                best = (score, delta_x, delta_y)
    if best is None or best[0] < minimum_similarity:
        raise ValueError("Studio/render local image registration is below threshold")
    if max(abs(best[1]), abs(best[2])) > position_tolerance:
        raise ValueError("Studio/render image registration exceeds position tolerance")
    return {
        "x": float(studio_box["x"]) + best[1],
        "y": float(studio_box["y"]) + best[2],
        "width": box_width,
        "height": box_height,
    }, best[0], best[1], best[2]


def _artifact(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"required parity artifact is missing: {path}")
    return {"path": str(path), "sha256": sha256_file(path)}


def build_report(
    *,
    renderer_export_path: Path,
    render_snapshot_dir: Path,
    storyboard_path: Path,
    project_artifact_path: Path,
    motion_design_contract_path: Path,
    source_media_path: Path,
    keyframe_receipt_dir: Path,
    tolerances: Mapping[str, Any],
    minimum_similarity: float = 0.95,
) -> dict[str, Any]:
    position_tolerance = float(tolerances.get("position_px", -1))
    if not math.isfinite(position_tolerance) or position_tolerance < 0:
        raise ValueError("parity position tolerance must be finite and non-negative")
    if not math.isfinite(minimum_similarity) or not 0 < minimum_similarity <= 1:
        raise ValueError("minimum similarity must be finite and in (0, 1]")

    renderer_export = read_json(renderer_export_path.resolve())
    storyboard = read_json(storyboard_path.resolve())
    expected_ids = [
        str(event.get("semantic_event_id") or event.get("id") or "")
        for event in storyboard.get("events") or [] if isinstance(event, Mapping)
    ]
    exported = {
        str(event.get("event_id") or ""): event
        for event in renderer_export.get("events") or [] if isinstance(event, Mapping)
    }
    if not expected_ids or list(exported) != expected_ids:
        raise ValueError("renderer export event order differs from Storyboard")

    receipt_paths = {
        event_id: (keyframe_receipt_dir.resolve() / f"{event_id}.json")
        for event_id in expected_ids
    }
    samples: list[dict[str, Any]] = []
    for event_id in expected_ids:
        event = exported[event_id]
        phases = [row for row in event.get("phases") or [] if isinstance(row, Mapping)]
        if [str(row.get("phase") or "") for row in phases] != list(PHASES):
            raise ValueError(f"renderer export phase order is invalid for {event_id}")
        animation_targets = [str(value) for value in event.get("animation_targets") or []]
        preferred_selector = f"#{event_id}"
        selector = preferred_selector if preferred_selector in animation_targets else (
            animation_targets[0] if animation_targets else ""
        )
        if not selector:
            raise ValueError(f"renderer export lacks an event selector for {event_id}")
        receipt_path = receipt_paths[event_id]
        receipt_artifact = _artifact(receipt_path)
        for phase in phases:
            phase_name = str(phase["phase"])
            studio_path = Path(str((phase.get("snapshot") or {}).get("path") or "")).resolve()
            studio_artifact = _artifact(studio_path)
            if studio_artifact["sha256"] != (phase.get("snapshot") or {}).get("sha256"):
                raise ValueError(f"renderer export snapshot hash is stale: {studio_path}")
            render_path = (
                render_snapshot_dir.resolve() / f"{event_id}-{phase_name}.png"
            )
            render_artifact = _artifact(render_path)
            studio_image = _open_rgb(studio_path)
            render_image = _open_rgb(render_path)
            studio_box = _pixel_box(
                phase.get("overlay_bbox") or {}, studio_image.width, studio_image.height,
            )
            render_box, similarity, delta_x, delta_y = _registered_geometry(
                studio_image,
                render_image,
                studio_box,
                position_tolerance=position_tolerance,
                minimum_similarity=minimum_similarity,
            )
            visible = phase.get("visible") is True
            connectors = [
                row for row in phase.get("connectors") or [] if isinstance(row, Mapping)
            ]
            endpoints_attached = all(
                all(
                    isinstance(point, Mapping)
                    and 0 <= float(point.get("x", -1)) <= 1
                    and 0 <= float(point.get("y", -1)) <= 1
                    for point in (connector.get("from"), connector.get("to"))
                )
                for connector in connectors
            )
            timestamp = float(phase["timestamp_seconds"])
            samples.append({
                "event_id": event_id,
                "phase": phase_name,
                "time_seconds": timestamp,
                "studio_time_seconds": timestamp,
                "render_time_seconds": timestamp,
                "studio_snapshot": studio_artifact["path"],
                "render_snapshot": render_artifact["path"],
                "studio_snapshot_sha256": studio_artifact["sha256"],
                "render_snapshot_sha256": render_artifact["sha256"],
                "animation_phase": {"studio": phase_name, "render": phase_name},
                "elements": [{
                    "selector": selector,
                    "studio": {**studio_box, "visible": visible},
                    "render": {**render_box, "visible": visible},
                }],
                "connectors": {
                    "expected_count": len(connectors),
                    "studio_count": len(connectors),
                    "render_count": len(connectors),
                    "all_endpoints_attached": endpoints_attached,
                    "clipped": phase.get("crop_status") == "clipped",
                },
                "cropping": {
                    "studio_clipped": phase.get("crop_status") == "clipped",
                    "render_clipped": phase.get("crop_status") == "clipped",
                },
                "caption_occlusion": {
                    "studio": float(phase.get("caption_overlap_ratio", 0)) > 0,
                    "render": float(phase.get("caption_overlap_ratio", 0)) > 0,
                },
                "keyframe_receipt": receipt_artifact,
                "comparison_evidence": {
                    "method": "local_image_registration_v1",
                    "minimum_similarity": minimum_similarity,
                    "observed_similarity": round(similarity, 6),
                    "translation_x_px": delta_x,
                    "translation_y_px": delta_y,
                },
            })

    report = {
        "schema_version": 2,
        "status": "pass",
        "tolerances": {
            "position_px": float(tolerances["position_px"]),
            "size_px": float(tolerances["size_px"]),
            "time_seconds": float(tolerances["time_seconds"]),
        },
        "inputs": {
            "project_artifact": _artifact(project_artifact_path),
            "motion_design_contract": _artifact(motion_design_contract_path),
            "source_media": _artifact(source_media_path),
            "renderer_export": _artifact(renderer_export_path),
        },
        "samples": samples,
    }
    errors = validate(
        report,
        storyboard,
        configured_tolerances=dict(tolerances),
        expected_bindings={
            "project_artifact": project_artifact_path.resolve(),
            "motion_design_contract": motion_design_contract_path.resolve(),
            "source_media": source_media_path.resolve(),
        },
        keyframe_receipt_paths=receipt_paths,
    )
    if errors:
        raise ValueError("built preview/render parity report is invalid: " + "; ".join(errors))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer-export", required=True, type=Path)
    parser.add_argument("--render-snapshot-dir", required=True, type=Path)
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--project-artifact", required=True, type=Path)
    parser.add_argument("--motion-design-contract", required=True, type=Path)
    parser.add_argument("--source-media", required=True, type=Path)
    parser.add_argument("--keyframe-receipt-dir", required=True, type=Path)
    parser.add_argument("--position-tolerance", type=float, default=4.0)
    parser.add_argument("--size-tolerance", type=float, default=4.0)
    parser.add_argument("--time-tolerance", type=float, default=0.05)
    parser.add_argument("--minimum-similarity", type=float, default=0.95)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_report(
        renderer_export_path=args.renderer_export,
        render_snapshot_dir=args.render_snapshot_dir,
        storyboard_path=args.storyboard,
        project_artifact_path=args.project_artifact,
        motion_design_contract_path=args.motion_design_contract,
        source_media_path=args.source_media,
        keyframe_receipt_dir=args.keyframe_receipt_dir,
        tolerances={
            "position_px": args.position_tolerance,
            "size_px": args.size_tolerance,
            "time_seconds": args.time_tolerance,
        },
        minimum_similarity=args.minimum_similarity,
    )
    write_json(args.output.resolve(), report)
    print(json.dumps({"status": "pass", "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
