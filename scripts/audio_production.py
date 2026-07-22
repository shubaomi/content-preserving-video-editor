#!/usr/bin/env python3
"""Produce local SFX and resolve one optional BGM through a stop-on-success cascade."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from build_local_sfx_library import build_for_storyboard
from director_adapters import AdapterRunner
from director_contracts import write_json


def _resolve(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _asset_result(path: Path, *, provider: str, authorization: str, model: Any = None,
                  prompt: Any = None) -> dict[str, Any]:
    return {
        "mode": "authorized_asset",
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "authorization": authorization,
        "quota_stopped_after_success": True,
    }


def resolve_bgm(
    config: dict[str, Any], *, root: Path, output_dir: Path, runner: AdapterRunner,
) -> dict[str, Any]:
    if config.get("enabled", config.get("enabled_by_default", True)) is not True:
        return {"mode": "disabled", "reason": "explicitly disabled", "explicitly_disabled": True}
    approved = _resolve(root, config.get("asset"))
    if approved and approved.is_file():
        return _asset_result(
            approved, provider="approved_local",
            authorization=str(config.get("authorization") or "project-authorized asset"),
        )
    attempts: list[dict[str, Any]] = []
    providers = config.get("provider_chain") or []
    for provider in providers:
        if not isinstance(provider, dict) or provider.get("enabled") is not True:
            continue
        name = str(provider.get("name") or "provider")
        if provider.get("requires_paid_call") is True and provider.get("paid_call_authorized") is not True:
            attempts.append({"provider": name, "status": "action_required",
                             "reason": "paid external generation is not authorized"})
            continue
        output = _resolve(root, provider.get("output")) or (output_dir / f"{name}-bgm.wav")
        command = provider.get("command") or []
        if not isinstance(command, list) or not command:
            attempts.append({"provider": name, "status": "unavailable",
                             "reason": "no executable adapter command configured"})
            continue
        result = runner.run(
            name=f"bgm_{name}", enabled=True, command=[str(value) for value in command],
            inputs=[], outputs=[output], blocking=False, cwd=root,
            settings={"provider": name, "model": provider.get("model"),
                      "prompt": provider.get("prompt"), "timeout_seconds": provider.get("timeout_seconds", 900)},
        )
        attempts.append({"provider": name, "status": result.get("status")})
        if result.get("status") in {"complete", "reused"} and output.is_file():
            selected = _asset_result(
                output, provider=name,
                authorization=str(provider.get("authorization") or "configured provider authorization"),
                model=provider.get("model"), prompt=provider.get("prompt"),
            )
            selected["attempts"] = attempts
            return selected
    return {"mode": "disabled", "reason": "no approved BGM provider produced an asset",
            "attempts": attempts}


def build_audio_plan(
    sfx_manifest: dict[str, Any], *, source_audio: str, bgm: dict[str, Any],
    preview_volume: float,
) -> dict[str, Any]:
    decisions = list(sfx_manifest.get("event_decisions") or [])
    cue_count = sum(row.get("decision") == "cue" for row in decisions)
    if bgm.get("mode") == "authorized_asset":
        background = {
            "mode": "authorized_asset", "enabled": True, "source": bgm["path"],
            "preview_volume": preview_volume,
            "ducking": {"enabled": True, "method": "sidechaincompress",
                        "status": "pending_final_mix_measurement"},
            "provenance": {key: bgm.get(key) for key in
                           ("provider", "model", "prompt", "authorization", "sha256")},
        }
    else:
        background = {"mode": "disabled", "enabled": False,
                      "reason": bgm.get("reason") or "no BGM selected",
                      "explicitly_disabled": bgm.get("explicitly_disabled") is True}
    return {
        "schema_version": 3,
        "speech_track": {"source": source_audio, "dominant": True, "immutable": True},
        "motion_sfx": {
            "event_decisions": decisions,
            "mix_audibility_check": {
                "status": "pending_render_measurement" if cue_count else "not_applicable",
                "reason": "measure after SFX is mixed with real speech" if cue_count else "no cue events",
            },
        },
        "background_music": background,
        "provenance": {
            "source_audio": source_audio,
            "motion_sfx": "project-owned deterministic multi-note assets",
            "background_music": bgm,
        },
    }


def produce_audio_assets(
    *, storyboard: Path, project: dict[str, Any], project_root: Path,
    output_dir: Path, source_audio: Path, runner: AdapterRunner,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sfx_dir = storyboard.parent / "assets" / "sfx"
    sfx_manifest_path = storyboard.parent / "audio-sfx-manifest.json"
    sfx_config = project.get("audio", {}).get("sfx", {})
    if sfx_config.get("enabled", True) is True:
        manifest = build_for_storyboard(storyboard, sfx_dir, "assets/sfx")
    else:
        payload = json.loads(storyboard.read_text(encoding="utf-8"))
        manifest = {
            "schema_version": 2, "storyboard": str(storyboard.resolve()), "assets": [],
            "event_decisions": [
                {"event_id": str(event.get("id")), "decision": "intentionally_silent",
                 "reason": "project SFX is explicitly disabled"}
                for event in (payload.get("events") or []) if event.get("treatment") != "quiet_source"
            ],
        }
    write_json(sfx_manifest_path, manifest)
    bgm = resolve_bgm(
        project.get("audio", {}).get("bgm", {}), root=project_root,
        output_dir=output_dir / "bgm", runner=runner,
    )
    bgm_manifest = output_dir / "bgm-provenance.json"
    write_json(bgm_manifest, bgm)
    plan_path = storyboard.parent / "audio-plan.json"
    write_json(plan_path, build_audio_plan(
        manifest, source_audio=str(source_audio.resolve()), bgm=bgm,
        preview_volume=float(project.get("audio", {}).get("bgm", {}).get("preview_volume", 0.1)),
    ))
    assets = [Path(row["frozen_path"]) for row in manifest.get("assets") or []]
    return [sfx_manifest_path, bgm_manifest, plan_path, *assets]
