#!/usr/bin/env python3
"""Blocking aesthetic QA for a HyperFrames sample or final composition."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

from director_contracts import (
    REQUIRED_VISUAL_FIELDS,
    event_requires_target_region_contract,
    sha256_file,
    visual_signature,
    write_json,
)


REQUIRED_CRITERIA = (
    "directly_relevant_to_spoken_content",
    "adds_understanding_not_caption_repetition",
    "keyword_is_actual_sentence_focus",
    "layout_variety",
    "motion_matches_speech_rhythm",
    "no_caption_face_cursor_or_ui_occlusion",
    "composite_readability_over_source",
    "ip_asset_integrates_with_footage",
    "connector_geometry_and_optical_alignment",
    "sfx_matches_motion",
    "cover_identity_expression_and_energy",
    "no_unexplained_long_visual_stagnation",
)

REQUIRED_PHASES = ("entrance", "midpoint", "pre_exit", "post_exit")
HUMAN_ANATOMY_CRITERION = "generated_human_anatomy"
REQUIRED_ANATOMY_CHECKS = (
    "full_resolution_reviewed",
    "left_hand_crop_reviewed",
    "right_hand_crop_reviewed",
    "intended_counts_match",
    "continuous_limb_connections",
    "no_extra_duplicated_fused_detached_or_ambiguous_limbs",
)

MIN_REVIEW_IMAGE_SHORT_EDGE_PX = 180
MIN_REVIEW_IMAGE_LONG_EDGE_PX = 320
MIN_ANATOMY_IMAGE_EDGE_PX = 256
REQUIRED_ANATOMY_EVIDENCE_ROLES = ("full_frame", "left_hand", "right_hand")
GEOMETRY_MEASUREMENT_METHOD = "browser_dom_geometry_v1"
COMPOSITE_CONTRAST_METHOD = "source_frame_alpha_composite_v1"


def _evidence_path(value: Any) -> Path | None:
    record = value if isinstance(value, dict) else {"path": value}
    path_value = record.get("path")
    return Path(str(path_value)).resolve() if path_value else None


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x, y, width, height)) or width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        point = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return point if all(math.isfinite(item) for item in point) else None


def _edge_point(box: tuple[float, float, float, float], edge: str) -> tuple[float, float] | None:
    x, y, width, height = box
    return {
        "left": (x, y + height / 2),
        "right": (x + width, y + height / 2),
        "top": (x + width / 2, y),
        "bottom": (x + width / 2, y + height),
    }.get(edge)


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _connector_measurement_errors(
    row: dict[str, Any], contract: dict[str, Any], event_id: str,
) -> list[str]:
    errors: list[str] = []
    receipt = row.get("measurement_receipt")
    if not isinstance(receipt, dict):
        return [f"event {event_id} connector geometry measurement receipt is missing"]
    if receipt.get("method") != GEOMETRY_MEASUREMENT_METHOD:
        errors.append(f"event {event_id} connector geometry measurement method is unsupported")
    evidence = _evidence_path(row.get("evidence"))
    if (
        evidence is None or not evidence.is_file()
        or receipt.get("snapshot_sha256") != sha256_file(evidence)
    ):
        errors.append(f"event {event_id} connector measurement snapshot hash is stale")
    canvas = receipt.get("canvas") or {}
    try:
        canvas_width = float(canvas.get("width"))
        canvas_height = float(canvas.get("height"))
        tolerance = float(receipt.get("maximum_endpoint_distance_px"))
    except (TypeError, ValueError):
        canvas_width = canvas_height = tolerance = -1.0
    if (
        not all(math.isfinite(value) for value in (canvas_width, canvas_height, tolerance))
        or canvas_width <= 0 or canvas_height <= 0 or not 0 <= tolerance <= 8
    ):
        errors.append(f"event {event_id} connector measurement canvas or tolerance is invalid")
    declared_relations = contract.get("relations") or []
    measured = receipt.get("relations") or []
    if not isinstance(measured, list) or len(measured) != len(declared_relations):
        return [*errors, f"event {event_id} connector measurement relation count is incomplete"]
    for index, (declared, observation) in enumerate(zip(declared_relations, measured)):
        label = f"event {event_id} connector measurement[{index}]"
        if not isinstance(observation, dict):
            errors.append(f"{label} is invalid")
            continue
        if isinstance(declared, dict):
            expected_relation = f"{declared.get('from')}->{declared.get('to')}"
            expected_edge = str(declared.get("attachment_edge") or "")
        else:
            expected_relation = str(declared)
            expected_edge = ""
        if observation.get("relation") != expected_relation:
            errors.append(f"{label} does not match the declared semantic relation")
        attachment = str(observation.get("attachment_edge") or expected_edge)
        edge_parts = attachment.split("-to-")
        if len(edge_parts) != 2:
            errors.append(f"{label} attachment edge is invalid")
            continue
        from_box = _bbox(observation.get("from_bbox"))
        to_box = _bbox(observation.get("to_bbox"))
        path_start = _point(observation.get("path_start"))
        path_end = _point(observation.get("path_end"))
        if None in (from_box, to_box, path_start, path_end):
            errors.append(f"{label} requires numeric bboxes and path endpoints")
            continue
        expected_start = _edge_point(from_box, edge_parts[0])
        expected_end = _edge_point(to_box, edge_parts[1])
        if expected_start is None or expected_end is None:
            errors.append(f"{label} attachment edge is invalid")
            continue
        if _distance(path_start, expected_start) > tolerance or _distance(path_end, expected_end) > tolerance:
            errors.append(f"{label} endpoint alignment exceeds the measured tolerance")
        if observation.get("clipped") is not False:
            errors.append(f"{label} path is clipped or clipping was not measured")
        for box in (from_box, to_box):
            x, y, width, height = box
            if x < 0 or y < 0 or x + width > canvas_width or y + height > canvas_height:
                errors.append(f"{label} node bbox leaves the canvas")
    return errors


def _target_measurement_errors(
    row: dict[str, Any], contract: dict[str, Any], event_id: str,
) -> list[str]:
    errors: list[str] = []
    receipt = row.get("measurement_receipt")
    if not isinstance(receipt, dict):
        return [f"event {event_id} target region measurement receipt is missing"]
    if receipt.get("method") != GEOMETRY_MEASUREMENT_METHOD:
        errors.append(f"event {event_id} target region measurement method is unsupported")
    evidence = _evidence_path(row.get("evidence"))
    if (
        evidence is None or not evidence.is_file()
        or receipt.get("snapshot_sha256") != sha256_file(evidence)
    ):
        errors.append(f"event {event_id} target measurement snapshot hash is stale")
    if receipt.get("active_selector") != contract.get("active_selector"):
        errors.append(f"event {event_id} target measurement selector is stale")
    if receipt.get("measured_at_phase") != "midpoint":
        errors.append(f"event {event_id} target geometry must be measured at midpoint")
    canvas = receipt.get("canvas") or {}
    try:
        canvas_width = float(canvas.get("width"))
        canvas_height = float(canvas.get("height"))
        required_ratio = float(contract.get("minimum_useful_content_ratio"))
    except (TypeError, ValueError):
        canvas_width = canvas_height = -1.0
        required_ratio = 1.0
    if (
        not all(math.isfinite(value) for value in (canvas_width, canvas_height))
        or canvas_width <= 0 or canvas_height <= 0
    ):
        errors.append(f"event {event_id} target measurement canvas is invalid")
    targets = receipt.get("targets") or []
    target_ids = [str(value) for value in (contract.get("target_ids") or [])]
    if not isinstance(targets, list) or len(targets) != len(target_ids):
        return [*errors, f"event {event_id} target measurement count is incomplete"]
    measured_ids: list[str] = []
    measured_ratios: list[float] = []
    for index, target in enumerate(targets):
        label = f"event {event_id} target measurement[{index}]"
        if not isinstance(target, dict):
            errors.append(f"{label} is invalid")
            continue
        measured_ids.append(str(target.get("target_id") or ""))
        overlay = _bbox(target.get("overlay_bbox"))
        useful = _bbox(target.get("useful_content_bbox"))
        if overlay is None or useful is None:
            errors.append(f"{label} requires numeric overlay and useful-content bboxes")
            continue
        ox, oy, ow, oh = overlay
        ux, uy, uw, uh = useful
        if ox < 0 or oy < 0 or ox + ow > canvas_width or oy + oh > canvas_height:
            errors.append(f"{label} overlay bbox leaves the canvas")
        intersection_width = max(0.0, min(ox + ow, ux + uw) - max(ox, ux))
        intersection_height = max(0.0, min(oy + oh, uy + uh) - max(oy, uy))
        ratio = intersection_width * intersection_height / (ow * oh)
        measured_ratios.append(ratio)
        if ratio + 1e-9 < required_ratio:
            errors.append(f"{label} measured useful-content ratio is too low")
    if measured_ids != target_ids:
        errors.append(f"event {event_id} target measurement IDs do not match the contract")
    if measured_ratios:
        reported = row.get("minimum_observed_useful_content_ratio")
        try:
            reported_ratio = float(reported)
        except (TypeError, ValueError):
            reported_ratio = -1.0
        if abs(reported_ratio - min(measured_ratios)) > 0.02:
            errors.append(f"event {event_id} reported useful-content ratio does not match measurements")
    return errors


def _rgb(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) and 0 <= item <= 255 for item in result):
        return None
    return result


def _relative_luminance(rgb: np.ndarray) -> np.ndarray:
    normalized = rgb / 255.0
    linear = np.where(
        normalized <= 0.04045,
        normalized / 12.92,
        ((normalized + 0.055) / 1.055) ** 2.4,
    )
    return linear[..., 0] * 0.2126 + linear[..., 1] * 0.7152 + linear[..., 2] * 0.0722


def _composite_contrast_errors(
    row: Any, phases: dict[str, Any], event_id: str,
) -> list[str]:
    if not isinstance(row, dict):
        return [f"event {event_id} composite contrast measurement is missing"]
    errors: list[str] = []
    if row.get("status") != "pass":
        errors.append(f"event {event_id} composite contrast review is not pass")
    if row.get("method") != COMPOSITE_CONTRAST_METHOD:
        errors.append(f"event {event_id} composite contrast method is unsupported")
    composite_record = row.get("composite_evidence")
    source_record = row.get("source_evidence")
    errors.extend(_image_evidence_errors(
        composite_record, f"event {event_id} composite contrast evidence",
    ))
    errors.extend(_image_evidence_errors(
        source_record, f"event {event_id} composite source evidence",
    ))
    composite_path = _evidence_path(composite_record)
    source_path = _evidence_path(source_record)
    midpoint_path = _evidence_path(phases.get("midpoint"))
    post_exit_path = _evidence_path(phases.get("post_exit"))
    if composite_path != midpoint_path:
        errors.append(f"event {event_id} composite contrast evidence is not the reviewed midpoint")
    if source_path != post_exit_path:
        errors.append(f"event {event_id} composite source evidence is not the reviewed post-exit frame")
    box = _bbox(row.get("overlay_bbox"))
    foreground = _rgb(row.get("foreground_rgb"))
    panel = _rgb(row.get("panel_rgb"))
    try:
        alpha = float(row.get("panel_alpha"))
    except (TypeError, ValueError):
        alpha = -1.0
    if box is None or foreground is None or panel is None or not 0 <= alpha <= 1:
        return [*errors, f"event {event_id} composite contrast inputs are invalid"]
    if source_path is None or not source_path.is_file():
        return errors
    with Image.open(source_path) as image:
        source = image.convert("RGB")
        x, y, width, height = box
        if x < 0 or y < 0 or x + width > source.width or y + height > source.height:
            return [*errors, f"event {event_id} composite contrast bbox leaves the source frame"]
        crop = source.crop((int(x), int(y), int(x + width), int(y + height)))
        crop.thumbnail((160, 90), Image.Resampling.BILINEAR)
        source_pixels = np.asarray(crop, dtype=np.float64)
    panel_pixels = np.asarray(panel, dtype=np.float64)
    composited = panel_pixels * alpha + source_pixels * (1.0 - alpha)
    foreground_luminance = float(_relative_luminance(
        np.asarray(foreground, dtype=np.float64),
    ))
    background_luminance = _relative_luminance(composited)
    ratios = (
        np.maximum(background_luminance, foreground_luminance) + 0.05
    ) / (
        np.minimum(background_luminance, foreground_luminance) + 0.05
    )
    measured_ratio = float(np.percentile(ratios, 5))
    if measured_ratio < 4.5:
        errors.append(
            f"event {event_id} composited contrast {measured_ratio:.2f}:1 is below 4.5:1"
        )
    return errors


def _image_evidence_errors(
    value: Any,
    label: str,
    *,
    minimum_short_edge: int = MIN_REVIEW_IMAGE_SHORT_EDGE_PX,
    minimum_long_edge: int = MIN_REVIEW_IMAGE_LONG_EDGE_PX,
) -> list[str]:
    """Reject placeholder files while accepting legacy paths and hash-bound records."""
    record = value if isinstance(value, dict) else {"path": value}
    path_value = record.get("path")
    if not path_value:
        return [f"{label} is missing"]
    path = Path(str(path_value))
    if not path.is_file():
        return [f"{label} is missing"]
    declared_hash = record.get("sha256")
    if isinstance(value, dict):
        if not re.fullmatch(r"[0-9a-f]{64}", str(declared_hash or "")):
            return [f"{label} structured record requires sha256"]
        if declared_hash != sha256_file(path):
            return [f"{label} hash does not match"]
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError, ValueError):
        return [f"{label} is not a decodable image"]
    if min(width, height) < minimum_short_edge or max(width, height) < minimum_long_edge:
        return [f"{label} is too small for full-size visual review"]
    return []


def _requires_human_anatomy_qa(storyboard: dict[str, Any]) -> bool:
    return any(
        isinstance((event.get("geometry_contract") or {}).get("anatomy_contract"), dict)
        for event in (storyboard.get("events") or [])
    )


def _source_state_delta(left: Path, right: Path) -> float:
    with Image.open(left) as left_image, Image.open(right) as right_image:
        left_rgb = left_image.convert("RGB").resize((320, 180), Image.Resampling.BILINEAR)
        right_rgb = right_image.convert("RGB").resize((320, 180), Image.Resampling.BILINEAR)
        difference = ImageChops.difference(left_rgb, right_rgb)
        return sum(ImageStat.Stat(difference).mean) / (3 * 255)


def validate(
    review: dict[str, Any], storyboard: dict[str, Any], *,
    keyframe_receipt_paths: Mapping[str, Path] | None = None,
    decision_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    criteria = review.get("criteria") or {}
    for name in REQUIRED_CRITERIA:
        row = criteria.get(name)
        if not isinstance(row, dict):
            errors.append(f"missing aesthetic criterion: {name}")
            continue
        if row.get("status") != "pass":
            errors.append(f"aesthetic criterion is not pass: {name}")
        if not row.get("evidence"):
            errors.append(f"aesthetic criterion lacks evidence: {name}")
    if _requires_human_anatomy_qa(storyboard):
        row = criteria.get(HUMAN_ANATOMY_CRITERION)
        if not isinstance(row, dict):
            errors.append(f"missing aesthetic criterion: {HUMAN_ANATOMY_CRITERION}")
        else:
            if row.get("status") != "pass":
                errors.append(f"aesthetic criterion is not pass: {HUMAN_ANATOMY_CRITERION}")
            evidence = row.get("evidence") or []
            anatomy_errors: list[str] = []
            role_records: dict[str, list[tuple[str, str]]] = {
                role: [] for role in REQUIRED_ANATOMY_EVIDENCE_ROLES
            }
            for index, item in enumerate(evidence):
                record = item if isinstance(item, dict) else {"path": item}
                role_value = record.get("role") if isinstance(item, dict) else (
                    REQUIRED_ANATOMY_EVIDENCE_ROLES[index]
                    if index < len(REQUIRED_ANATOMY_EVIDENCE_ROLES) else ""
                )
                role = str(role_value or "").strip()
                path_value = record.get("path")
                path = Path(str(path_value)).resolve() if path_value else None
                if role in role_records and path is not None and path.is_file():
                    role_records[role].append((str(path), sha256_file(path)))
                anatomy_errors.extend(_image_evidence_errors(
                    item,
                    f"generated human anatomy evidence[{index}]",
                    minimum_short_edge=MIN_ANATOMY_IMAGE_EDGE_PX,
                    minimum_long_edge=MIN_ANATOMY_IMAGE_EDGE_PX,
                ))
            if any(len(role_records[role]) != 1 for role in REQUIRED_ANATOMY_EVIDENCE_ROLES):
                anatomy_errors.append(
                    "generated human anatomy evidence roles must include exactly one full_frame, "
                    "left_hand, and right_hand"
                )
            required_records = [
                role_records[role][0]
                for role in REQUIRED_ANATOMY_EVIDENCE_ROLES
                if len(role_records[role]) == 1
            ]
            if (
                len(required_records) != len(REQUIRED_ANATOMY_EVIDENCE_ROLES)
                or len({path for path, _ in required_records}) != 3
                or len({digest for _, digest in required_records}) != 3
            ):
                anatomy_errors.append(
                    "generated human anatomy requires three unique role-specific evidence images"
                )
            if len(evidence) < 3 or anatomy_errors:
                errors.append(
                    "generated human anatomy requires existing full-resolution, left-hand, and right-hand evidence"
                )
                errors.extend(anatomy_errors)
            checks = row.get("checks") or {}
            for name in REQUIRED_ANATOMY_CHECKS:
                if checks.get(name) is not True:
                    errors.append(f"generated human anatomy check is not pass: {name}")
    tech = review.get("technical_qa") or {}
    for name in ("hyperframes_check", "caption_sync", "overlap", "overflow", "decode"):
        if tech.get(name, {}).get("status") != "pass":
            errors.append(f"technical QA is not pass: {name}")
    events = [event for event in (storyboard.get("events") or []) if event.get("treatment") != "quiet_source"]
    signatures = {visual_signature(event) for event in events}
    if not decision_complete and (len(events) < 4 or len(signatures) < 4):
        errors.append("sample must contain at least four genuinely distinct visual structures")
    for signature in signatures:
        if len(signature) != len(REQUIRED_VISUAL_FIELDS) or any(not item for item in signature):
            errors.append("storyboard contains an incomplete visual structure signature")
    snapshots = review.get("snapshots") or {}
    connector_geometry = review.get("connector_geometry") or {}
    target_region_geometry = review.get("target_region_geometry") or {}
    composite_contrast = review.get("composite_contrast") or {}
    reviewed_event_ids = set(review.get("reviewed_event_ids") or [])
    for event in events:
        event_id = str(event.get("id", ""))
        semantic_event_id = str(event.get("semantic_event_id") or event_id)
        if event_id not in reviewed_event_ids:
            errors.append(f"event not included in aesthetic review: {event_id}")
        phases = snapshots.get(event_id) or {}
        for phase in REQUIRED_PHASES:
            evidence = phases.get(phase)
            if not evidence:
                errors.append(f"event {event_id} missing {phase} snapshot evidence")
            else:
                errors.extend(_image_evidence_errors(
                    evidence, f"event {event_id} {phase} snapshot evidence",
                ))
        if keyframe_receipt_paths is not None:
            receipt_path = keyframe_receipt_paths.get(semantic_event_id)
            if receipt_path is None or not Path(receipt_path).is_file():
                errors.append(f"event {event_id} keyframe receipt is missing")
            else:
                try:
                    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    errors.append(f"event {event_id} keyframe receipt is invalid")
                    receipt = {}
                receipt_phases = {
                    str(row.get("phase") or ""): row
                    for row in receipt.get("phase_observations") or []
                    if isinstance(row, dict)
                }
                for review_phase in REQUIRED_PHASES:
                    receipt_phase = "mid" if review_phase == "midpoint" else review_phase
                    receipt_snapshot = (
                        receipt_phases.get(receipt_phase) or {}
                    ).get("snapshot") or {}
                    reviewed_path = _evidence_path(phases.get(review_phase))
                    expected_path = _evidence_path(receipt_snapshot)
                    if (
                        reviewed_path is None or expected_path is None
                        or reviewed_path != expected_path
                        or not expected_path.is_file()
                        or receipt_snapshot.get("sha256") != sha256_file(expected_path)
                    ):
                        errors.append(
                            f"event {event_id} {review_phase} review differs from keyframe receipt"
                        )
        errors.extend(_composite_contrast_errors(
            composite_contrast.get(event_id), phases, event_id,
        ))
        connector_contract = (event.get("geometry_contract") or {}).get("connector_contract")
        if isinstance(connector_contract, dict):
            row = connector_geometry.get(event_id)
            if not isinstance(row, dict):
                errors.append(f"event {event_id} is missing connector geometry review")
                continue
            required_count = int(connector_contract.get("required_connector_count", 0))
            if row.get("status") != "pass":
                errors.append(f"event {event_id} connector geometry review is not pass")
            if int(row.get("required_connector_count", -1)) != required_count:
                errors.append(f"event {event_id} connector required-count evidence does not match storyboard")
            if int(row.get("observed_connector_count", -1)) != required_count:
                errors.append(f"event {event_id} connector count does not match the declared contract")
            for check in ("all_endpoints_attached", "optically_aligned", "no_clipped_paths"):
                if row.get(check) is not True:
                    errors.append(f"event {event_id} connector check is not pass: {check}")
            evidence = row.get("evidence")
            if not evidence:
                errors.append(f"event {event_id} connector geometry evidence is missing")
            else:
                errors.extend(_image_evidence_errors(
                    evidence, f"event {event_id} connector geometry evidence",
                ))
            errors.extend(_connector_measurement_errors(row, connector_contract, event_id))
        if event_requires_target_region_contract(event):
            target_contract = (event.get("geometry_contract") or {}).get(
                "target_region_contract"
            )
            if not isinstance(target_contract, dict):
                errors.append(f"event {event_id} is missing target region contract")
                continue
            row = target_region_geometry.get(event_id)
            if not isinstance(row, dict):
                errors.append(f"event {event_id} is missing target region review")
                continue
            if row.get("status") != "pass":
                errors.append(f"event {event_id} target region review is not pass")
            tracking_mode = target_contract.get("tracking_mode")
            if row.get("tracking_mode") != tracking_mode:
                errors.append(f"event {event_id} target tracking mode does not match storyboard")
            required_count = target_contract.get("required_target_count")
            if (
                isinstance(required_count, bool)
                or not isinstance(required_count, int)
                or required_count < 1
            ):
                errors.append(f"event {event_id} target count contract is invalid")
                required_count = None
            declared_count = row.get("required_target_count")
            if (
                required_count is None
                or isinstance(declared_count, bool)
                or not isinstance(declared_count, int)
                or declared_count != required_count
            ):
                errors.append(f"event {event_id} target required-count evidence does not match storyboard")
            observed_count = row.get("observed_target_count")
            if (
                required_count is None
                or isinstance(observed_count, bool)
                or not isinstance(observed_count, int)
                or observed_count != required_count
            ):
                errors.append(f"event {event_id} target count does not match the declared contract")
            for check in (
                "all_targets_contain_source_content",
                "no_empty_highlight_regions",
                "no_orphan_geometry",
                "event_window_matches_visible_source_state",
            ):
                if row.get(check) is not True:
                    errors.append(f"event {event_id} target region check is not pass: {check}")
            try:
                observed_ratio = float(row.get("minimum_observed_useful_content_ratio"))
                required_ratio = float(target_contract.get("minimum_useful_content_ratio"))
            except (TypeError, ValueError):
                observed_ratio = -1.0
                required_ratio = 1.0
            if observed_ratio < required_ratio:
                errors.append(f"event {event_id} target region useful-content ratio is too low")
            evidence = row.get("evidence")
            if not evidence:
                errors.append(f"event {event_id} target region evidence is missing")
            else:
                errors.extend(_image_evidence_errors(
                    evidence, f"event {event_id} target region evidence",
                ))
            errors.extend(_target_measurement_errors(row, target_contract, event_id))

            source_records = target_contract.get("source_state_evidence") or []
            source_paths: list[Path] = []
            for index, source_record in enumerate(source_records):
                label = f"event {event_id} source state evidence[{index}]"
                record_errors = _image_evidence_errors(source_record, label)
                errors.extend(record_errors)
                if not record_errors:
                    source_paths.append(Path(str(source_record["path"])))
            if tracking_mode in {"static", "scene_bounded"} and len(source_paths) >= 2:
                maximum_delta = float(target_contract.get("maximum_static_state_delta", 0.12))
                observed_delta = max(
                    _source_state_delta(source_paths[index - 1], source_paths[index])
                    for index in range(1, len(source_paths))
                )
                if observed_delta > maximum_delta:
                    errors.append(
                        f"event {event_id} static target geometry spans a source-state change; "
                        "shorten the active window or use keyframed tracking"
                    )
            if tracking_mode == "keyframed" and row.get("keyframes_cover_state_changes") is not True:
                errors.append(f"event {event_id} keyframed target review is incomplete")
    if review.get("verdict") != "pass":
        errors.append("review verdict is not pass")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    review_path = Path(args.review).resolve()
    storyboard_path = Path(args.storyboard).resolve()
    review = json.loads(review_path.read_text(encoding="utf-8"))
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    errors = validate(review, storyboard)
    report = {
        "schema_version": 1,
        "review": str(review_path),
        "storyboard": str(storyboard_path),
        "passed": not errors,
        "errors": errors,
        "note": "Automated tests do not constitute aesthetic approval; this gate requires evidence-backed review.",
    }
    write_json(Path(args.report).resolve(), report)
    print(args.report)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
