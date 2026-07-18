#!/usr/bin/env python3
"""Write the reviewable plan artifacts required by a dynamic-motion variant."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _events(plan: dict) -> list[dict]:
    return list(plan.get("attention_events", plan.get("events", [])))


def motion_plan(plan: dict, width: int, height: int, fps: float) -> dict:
    events = _events(plan)
    beats = []
    for event in events:
        beats.append({
            "id": event["id"], "start": event["start"], "end": event["end"],
            "safeZone": event["safe_zone"], "purpose": event["purpose"],
            "tier": event["tier"], "visual_family": event["visual_family"],
            "motion_variant": event["motion_variant"],
            "editableLayer": f"#{event['id']} .event-host",
            "semantic_anchor": event["semantic_anchor"],
            "transcript_evidence": event["transcript_evidence"],
            "collision_check": event["collision_check"],
        })
    return {
        "schema_version": 2,
        "source": "attention-plan.json",
        "composition": {"width": width, "height": height, "fps": fps, "durationSeconds": plan["duration"]},
        "beats": beats,
        "intentional_quiet_sections": plan.get("intentional_quiet_sections", []),
        "constraints": plan.get("constraints", {}),
    }


def audio_plan(plan: dict, analysis: dict | None) -> dict:
    events = _events(plan)
    cues = []
    for event in events:
        sfx = event.get("sfx", {})
        if not sfx.get("enabled"):
            continue
        cues.append({
            "event_id": event["id"], "start": event["start"], "family": sfx["family"],
            "asset": f"assets/sfx/{sfx['variant']}", "volume_db": sfx.get("volume_db", -18),
            "reason": sfx["reason"], "original_speech_priority": True,
        })
    source_audio = (analysis or {}).get("audio", {})
    return {
        "schema_version": 1,
        "duration": plan["duration"],
        "tracks": {
            "original": {"enabled": True, "source": "baseline.mp4", "immutable": True},
            "sfx": {"enabled": True, "cue_count": len(cues), "palette": "local_project_owned"},
            "bgm": {"enabled": False, "reason": "No approved BGM asset was required for this preserved baseline", "existing_bgm": source_audio.get("existing_bgm", "unknown")},
        },
        "cues": cues,
        "rules": {"same_file_cooldown_seconds": 20, "speech_priority": True, "render_has_no_remote_audio_dependency": True},
    }


def visual_audit(plan: dict) -> dict:
    sections = []
    for event in _events(plan):
        family = event["visual_family"]
        if family in {"ui_attention", "camera_motion", "semantic_icon"}:
            decision, asset_type = "ui_annotation", "native_motion_component"
            reason = "The source action remains the primary explanation; this event only directs attention."
        elif family == "ip_visual":
            decision, asset_type = "caption_only", "none"
            reason = "No topic-specific approved IP component is mounted yet; avoid presenting a generic identity marker as a finished illustration."
        elif family == "chapter_transition":
            decision, asset_type = "none", "none"
            reason = "A short semantic bridge is sufficient; no separate topic image is needed."
        else:
            decision, asset_type = "caption_only", "kinetic_text"
            reason = "The spoken idea is primary; the overlay emphasizes only its selected keyword or phrase."
        sections.append({
            "section_id": event["id"], "start": event["start"], "end": event["end"],
            "chapter": event["purpose"], "content_type": event["tier"], "current_visual": family,
            "score": event.get("semantic_score", 0), "decision": decision, "reason": reason,
            "ip_role": "none" if family != "ip_visual" else "deferred_topic_component",
            "asset_type": asset_type,
            "semantic_owner": "source footage" if decision == "ui_annotation" else "spoken idea",
            "relationship_to_existing_motion": "primary attention event",
            "redundancy_action": "none", "integration_mode": "pip-card" if decision == "ui_annotation" else "chapter-bridge",
            "background_treatment": "integrated light surface; no raw white image canvas",
        })
    return {"schema_version": 1, "sections": sections, "generated_from": "attention-plan.json"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--fps", type=float, default=30)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    analysis = json.loads(args.analysis.read_text(encoding="utf-8")) if args.analysis else None
    args.out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "motion-plan.json": motion_plan(plan, args.width, args.height, args.fps),
        "audio-plan.json": audio_plan(plan, analysis),
        "visual-opportunity-audit.json": visual_audit(plan),
    }
    for name, payload in outputs.items():
        (args.out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir.resolve()), "files": sorted(outputs)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
