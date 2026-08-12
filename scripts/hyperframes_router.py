#!/usr/bin/env python3
"""Evidence-driven routing across supported motion task families."""
from __future__ import annotations

import argparse
import json
import math
import wave
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, UnidentifiedImageError

from director_contracts import sha256_file, write_json


def _measured_image_delta(reference: Path, rendered: Path) -> float | None:
    try:
        with Image.open(reference) as before_image, Image.open(rendered) as after_image:
            before = before_image.convert("RGB")
            after = after_image.convert("RGB")
            if before.size != after.size or before.width <= 0 or before.height <= 0:
                return None
            histogram = ImageChops.difference(before, after).histogram()
            channel_samples = before.width * before.height * 3
            return sum(index % 256 * count for index, count in enumerate(histogram)) / (
                255.0 * channel_samples
            )
    except (OSError, UnidentifiedImageError):
        return None


def _decoded_pcm(path: Path) -> tuple[tuple[int, int, int], np.ndarray] | None:
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            width = audio.getsampwidth()
            rate = audio.getframerate()
            frames = audio.getnframes()
            compression = audio.getcomptype()
            raw = audio.readframes(frames)
    except (OSError, EOFError, wave.Error):
        return None
    if channels <= 0 or rate <= 0 or frames <= 0 or compression != "NONE":
        return None
    if width == 1:
        samples = np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
        scale = 128.0
    elif width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float64)
        scale = 32768.0
    elif width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float64)
        scale = 2147483648.0
    else:
        return None
    expected = frames * channels
    if samples.size != expected:
        return None
    return (channels, rate, frames), samples / scale


def _audio_parity_valid(
    measurement: dict[str, Any], component_manifest: dict[str, Any] | None,
) -> bool:
    applicable = measurement.get("audio_applicable")
    declared_delta = measurement.get("audio_sample_delta")
    if applicable is False:
        render_contract = (
            component_manifest.get("render_contract")
            if isinstance(component_manifest, dict) else None
        )
        return (
            declared_delta == 0
            and isinstance(render_contract, dict)
            and render_contract.get("output_kind") == "visual_only"
            and render_contract.get("audio_policy") == "forbidden"
        )
    if applicable is not True:
        return False
    reference = Path(str(measurement.get("reference_audio_artifact") or ""))
    rendered = Path(str(measurement.get("rendered_audio_artifact") or ""))
    if not (
        reference.is_absolute() and rendered.is_absolute()
        and reference.is_file() and rendered.is_file()
        and measurement.get("reference_audio_sha256") == sha256_file(reference)
        and measurement.get("rendered_audio_sha256") == sha256_file(rendered)
        and isinstance(declared_delta, (int, float)) and not isinstance(declared_delta, bool)
        and math.isfinite(float(declared_delta)) and 0 <= float(declared_delta) <= 1
    ):
        return False
    before = _decoded_pcm(reference)
    after = _decoded_pcm(rendered)
    if before is None or after is None or before[0] != after[0]:
        return False
    measured = float(np.max(np.abs(before[1] - after[1])))
    return measured <= 0.001 and abs(float(declared_delta) - measured) <= 0.0001


def _json_evidence(value: Any, *, kind: str) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value.get("path") or not value.get("sha256"):
        return None
    path = Path(str(value["path"]))
    if not path.is_absolute() or not path.is_file() or value["sha256"] != sha256_file(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 \
            or payload.get("kind") != kind or payload.get("status") != "pass":
        return None
    return payload


def _remotion_readiness(
    remotion: Any, *, allowed_event_ids: set[str],
) -> tuple[bool, list[str], list[str]]:
    if not isinstance(remotion, dict) or remotion.get("enabled") is not True:
        return False, [], []
    events = [str(value) for value in remotion.get("selected_event_ids") or [] if str(value)]
    components = remotion.get("react_components")
    if isinstance(components, list):
        component_ready = bool(components)
        component_manifest_hashes: dict[str, str] = {}
        component_manifests: dict[str, dict[str, Any]] = {}
        for row in components:
            if not isinstance(row, dict):
                component_ready = False
                continue
            event_id = str(row.get("event_id") or "")
            component_path = Path(str(row.get("path") or ""))
            manifest_record = {
                "path": row.get("manifest_path"), "sha256": row.get("manifest_sha256"),
            }
            manifest = _json_evidence(manifest_record, kind="remotion_component")
            row_ready = (
                event_id in events and component_path.is_absolute() and component_path.is_file()
                and row.get("sha256") == sha256_file(component_path)
                and manifest is not None and manifest.get("event_id") == event_id
                and Path(str(manifest.get("component_path") or "")).resolve() == component_path.resolve()
                and manifest.get("component_sha256") == row.get("sha256")
            )
            component_ready = component_ready and row_ready
            if row_ready:
                component_manifest_hashes[event_id] = str(row.get("manifest_sha256"))
                component_manifests[event_id] = manifest
        component_paths = [str(row.get("path")) for row in components if isinstance(row, dict)]
        component_events = {
            str(row.get("event_id") or "") for row in components if isinstance(row, dict)
        }
        component_ready = component_ready and component_events == set(events)
    else:
        component_ready = False
        component_paths = []
        component_manifests = {}
    parity = remotion.get("parity_evidence")
    license_evidence = remotion.get("license_evidence")
    parity_payload = _json_evidence(parity, kind="remotion_parity")
    license_payload = _json_evidence(license_evidence, kind="remotion_license")
    event_set = set(events)
    parity_ready = parity_payload is not None and set(
        str(value) for value in parity_payload.get("selected_event_ids") or []
    ) == event_set and parity_payload.get("component_manifest_sha256_by_event") == component_manifest_hashes \
        and isinstance(parity_payload.get("measurements"), list)
    measurements = parity_payload.get("measurements") if parity_payload else []
    measurement_events: set[str] = set()
    if parity_ready:
        for measurement in measurements:
            if not isinstance(measurement, dict):
                parity_ready = False
                continue
            event_id = str(measurement.get("event_id") or "")
            reference = Path(str(measurement.get("reference_artifact") or ""))
            rendered = Path(str(measurement.get("rendered_artifact") or ""))
            measured_frame_delta = (
                _measured_image_delta(reference, rendered)
                if reference.is_file() and rendered.is_file() else None
            )
            declared_frame_delta = measurement.get("frame_delta")
            row_ready = (
                event_id in event_set and event_id not in measurement_events
                and measurement.get("status") == "pass"
                and isinstance(measurement.get("frame_delta"), (int, float))
                and not isinstance(measurement.get("frame_delta"), bool)
                and 0 <= float(measurement["frame_delta"]) <= 1
                and isinstance(measurement.get("audio_sample_delta"), (int, float))
                and not isinstance(measurement.get("audio_sample_delta"), bool)
                and 0 <= float(measurement["audio_sample_delta"]) <= 1
                and reference.is_absolute() and rendered.is_absolute()
                and reference.is_file() and rendered.is_file()
                and measurement.get("reference_sha256") == sha256_file(reference)
                and measurement.get("rendered_sha256") == sha256_file(rendered)
                and measured_frame_delta is not None
                and abs(float(declared_frame_delta) - measured_frame_delta) <= 0.001
                and float(declared_frame_delta) <= 0.02
                and _audio_parity_valid(measurement, component_manifests.get(event_id))
            )
            parity_ready = parity_ready and row_ready
            measurement_events.add(event_id)
        parity_ready = parity_ready and measurement_events == event_set
    license_ready = license_payload is not None and set(
        str(value) for value in license_payload.get("authorized_event_ids") or []
    ) >= event_set and bool(str(license_payload.get("rights_basis") or "").strip())
    events_ready = bool(events) and event_set <= allowed_event_ids
    return component_ready and events_ready and parity_ready and license_ready, component_paths, events


def route_hyperframes(
    project: dict[str, Any], evidence: dict[str, Any], *,
    motion_design_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = str(evidence.get("task") or project.get("content", {}).get("task") or "").lower()
    content_type = str(
        evidence.get("content_type") or project.get("content", {}).get("type") or ""
    ).lower()
    if task in {"captions_only", "subtitle_only", "embedded_captions"}:
        route = "embedded-captions"
        reason = "explicit captions-only task"
    elif task in {"standalone_motion", "motion_graphics"}:
        route = "motion-graphics"
        reason = "independent motion-graphics deliverable"
    elif content_type in {"talking_head", "interview", "portrait_talking_head"}:
        route = "talking-head-recut"
        reason = "face-led speech content"
    else:
        route = "general-video"
        reason = "screen, mixed, tutorial, or unclassified video"

    remotion = project.get("renderer", {}).get("remotion", {})
    allowed_event_ids = {
        str(value) for value in ((motion_design_contract or {}).get("selected_event_ids") or [])
    }
    remotion_selected, react_paths, event_ids = _remotion_readiness(
        remotion, allowed_event_ids=allowed_event_ids,
    )
    if remotion_selected:
        renderer = "hyperframes"
        renderer_reason = "HyperFrames remains composition owner; selected events use existing React components"
        optional_event_renderer = "remotion"
    else:
        renderer = "hyperframes"
        renderer_reason = (
            "Remotion missing React component, selected event, parity, or license evidence; "
            "HyperFrames remains default"
            if isinstance(remotion, dict) and remotion.get("enabled") is True
            else "default motion renderer"
        )
        optional_event_renderer = None
    skills = ["hyperframes", "hyperframes-core", "hyperframes-creative",
              "hyperframes-animation", "hyperframes-cli", route]
    assets = project.get("assets", {})
    if (assets.get("use_media_catalog") is True
            or (assets.get("media_catalog") or {}).get("enabled") is True):
        skills.extend(["media-use", "hyperframes-registry", "hyperframes-catalog"])
    result = {
        "schema_version": 1,
        "route": route,
        "route_reason": reason,
        "renderer": renderer,
        "renderer_reason": renderer_reason,
        "optional_event_renderer": optional_event_renderer,
        "remotion_event_ids": list(event_ids) if remotion_selected else [],
        "remotion_component_paths": list(react_paths) if remotion_selected else [],
        "remotion_status": (
            "ready" if remotion_selected else
            "action_required" if isinstance(remotion, dict) and remotion.get("enabled") is True
            else "disabled"
        ),
        "capability_skills": skills,
        "semantic_selection_owner": "director_with_llm",
        "fixed_card_count": False,
        "density_formula_authority": False,
        "catalog_policy": "components require semantic relevance, target-frame geometry, safe-zone, and parity gates",
        "license_boundary": (
            "Remotion is an optional adapter and does not replace or modify upstream HyperFrames"
            if optional_event_renderer == "remotion" else "HyperFrames used through its public Skill/CLI contract"
        ),
    }
    if project.get("motion_quality", {}).get("enabled") is True:
        if not isinstance(motion_design_contract, dict):
            result["motion_quality"] = {
                "status": "action_required",
                "reason": "enabled motion quality requires a validated motion-design contract",
                "selection_owner": "director_motion_quality_engine",
                "renderer_authority": "typed_choreography_only",
            }
        else:
            result["motion_quality"] = {
                "status": "ready",
                "contract_id": motion_design_contract.get("contract_id"),
                "selected_event_ids": list(
                    motion_design_contract.get("selected_event_ids") or []
                ),
                "selection_owner": "director_motion_quality_engine",
                "renderer_authority": "typed_choreography_only",
            }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    import yaml
    project = yaml.safe_load(Path(args.project).read_text(encoding="utf-8")) or {}
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    output = Path(args.out).resolve()
    write_json(output, route_hyperframes(project, evidence))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
