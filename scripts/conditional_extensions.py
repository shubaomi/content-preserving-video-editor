#!/usr/bin/env python3
"""Evidence-gated optional capability adapters that never affect the default path."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from director_adapters import AdapterRunner
from director_contracts import read_json


EXTENSIONS = ("b_roll", "multicam", "voice_isolation", "localization")


def _config(project: dict[str, Any], name: str) -> dict[str, Any]:
    value = project.get("extensions", {}).get(name, {})
    return value if isinstance(value, dict) else {}


def route_extensions(
    project: dict[str, Any], evidence: dict[str, Any], semantic_brief: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for name in EXTENSIONS:
        config = _config(project, name)
        if config.get("enabled") is not True:
            routes[name] = {"status": "disabled", "reason": "optional_default_off"}
            continue
        if name == "b_roll":
            events = [event for event in (semantic_brief.get("events") or [])
                      if event.get("form") == "b_roll" or event.get("treatment") == "b_roll"]
            routes[name] = {
                "status": "ready" if events else "not_applicable",
                "reason": "semantic B-roll event selected" if events else "no semantic B-roll event",
                "event_ids": [str(event.get("id")) for event in events],
                "required_checks": ["target-frame match", "asset-frame match", "face/UI/text/logo safety",
                                    "full-screen versus PiP decision"],
            }
        elif name == "multicam":
            sources = project.get("source", {}).get("camera_sources") or []
            routes[name] = {
                "status": "ready" if len(sources) >= 2 else "action_required",
                "reason": "two or more declared camera sources" if len(sources) >= 2
                else "multicam requires at least two declared camera sources",
                "alignment_authority": "audio synchronization evidence; never guessed offsets",
            }
        elif name == "voice_isolation":
            noise = (evidence.get("existing_assets") or {}).get("noise_impairs_speech") is True \
                or config.get("force_with_evidence") is True
            routes[name] = {
                "status": "ready" if noise else "not_applicable",
                "reason": "measured noise/music impairs speech" if noise else "no impairment evidence",
            }
        else:
            targets = config.get("target_languages") or []
            routes[name] = {
                "status": "ready" if targets else "action_required",
                "reason": "target languages declared" if targets else "localization requires target_languages",
                "target_languages": targets,
                "method": "terminology -> sentence segmentation -> translation reflection -> alignment -> TTS fallback",
            }
    return routes


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate_output(name: str, payload: dict[str, Any], route: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if name == "b_roll":
        rows = payload.get("events") or []
        expected = set(route.get("event_ids") or [])
        observed = {str(row.get("event_id")) for row in rows}
        if not rows or not expected <= observed:
            errors.append("B-roll output must cover every selected semantic event")
        required_safety = {"caption", "face", "hands", "product", "text", "logo"}
        for index, row in enumerate(rows):
            if row.get("target_frame_match") is not True or row.get("asset_frame_match") is not True:
                errors.append(f"B-roll event {index} lacks bidirectional frame match")
            if row.get("integration_mode") not in {"full_screen", "pip"}:
                errors.append(f"B-roll event {index} lacks full_screen/pip decision")
            safety = row.get("safety") or {}
            if not all(safety.get(key) is True for key in required_safety):
                errors.append(f"B-roll event {index} lacks caption/face/hands/product/text/logo safety")
    elif name == "multicam":
        alignment = payload.get("alignment") or {}
        if alignment.get("method") != "audio_correlation" or alignment.get("verified") is not True:
            errors.append("multicam requires verified audio-correlation alignment")
        sources = payload.get("sources") or []
        if len(sources) < 2 or any(row.get("offset_seconds") is None or not row.get("evidence")
                                   for row in sources):
            errors.append("multicam requires evidenced offsets for at least two sources")
        if any(row.get("verified") is not True for row in (payload.get("cut_points") or [])):
            errors.append("every multicam cut point must be verified")
    elif name == "voice_isolation":
        quality = payload.get("quality") or {}
        if payload.get("impairment_evidence") is not True or payload.get("speech_preserved") is not True:
            errors.append("voice isolation requires impairment evidence and speech preservation")
        try:
            improved = float(quality["after_intelligibility"]) >= float(quality["before_intelligibility"])
        except (KeyError, TypeError, ValueError):
            improved = False
        if not improved or not payload.get("output_sha256"):
            errors.append("voice isolation requires non-regressing measured output and hash")
    elif name == "localization":
        segments = payload.get("segments") or []
        if not isinstance(payload.get("terminology"), list) or not segments:
            errors.append("localization requires terminology decisions and aligned segments")
        for index, row in enumerate(segments):
            required = (row.get("source_start") is not None, row.get("source_end") is not None,
                        bool(row.get("translated_text")), row.get("reflection_passed") is True,
                        row.get("alignment_passed") is True)
            if not all(required):
                errors.append(f"localized segment {index} lacks timing, reflection, or alignment evidence")
    return errors


def run_extension_adapters(
    *, project: dict[str, Any], routes: dict[str, dict[str, Any]], inputs: list[Path],
    root: Path, runner: AdapterRunner, execute: bool,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in EXTENSIONS:
        route = routes[name]
        config = _config(project, name)
        if route.get("status") != "ready":
            results[name] = route
            continue
        command = config.get("command") or []
        outputs = [_resolve(root, value) for value in (config.get("outputs") or [])]
        if not execute:
            results[name] = {**route, "status": "action_required",
                             "reason": "adapter execution is not enabled for this run"}
            continue
        if not isinstance(command, list) or not command or not outputs:
            results[name] = {**route, "status": "unavailable",
                             "reason": "no adapter command and outputs are configured"}
            continue
        result = runner.run(
            name=name, enabled=True, command=[str(value) for value in command],
            inputs=inputs, outputs=outputs, blocking=config.get("required") is True,
            cwd=root, settings={"route": route, "timeout_seconds": config.get("timeout_seconds", 1800)},
        )
        combined = {**route, **result}
        if result.get("status") in {"complete", "reused"}:
            payload = read_json(outputs[0])
            errors = _validate_output(name, payload, route)
            if errors:
                combined.update({"status": "failed" if config.get("required") is True else "unavailable",
                                 "validation_errors": errors})
        results[name] = combined
    return {"schema_version": 1, "extensions": results,
            "default_path_unchanged": all(_config(project, name).get("enabled") is not True
                                           for name in EXTENSIONS)}
