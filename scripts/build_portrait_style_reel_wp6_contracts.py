#!/usr/bin/env python3
"""Compile the real WP6 portrait Style Reel contract chain without rendering media."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from brand_motion_playbook import compile_playbook
from director_contracts import read_json, sha256_file
from portrait_brand_engine import (
    build_portrait_energy_authorities, compile_portrait_energy_map,
    derive_portrait_chapters,
)
from portrait_motion_recipes import (
    DEFAULT_PORTRAIT_RECIPE_REGISTRY, compile_portrait_motion_contracts,
)
from portrait_sonic import (
    DEFAULT_PORTRAIT_SONIC_REGISTRY, compile_portrait_sonic_plan,
    materialize_portrait_sonic_library, project_portrait_sonic_plan,
)
from portrait_style_reel import build_style_reel_plan
from safe_generated_output import atomic_write_text, safe_generated_target


class Wp6ContractError(ValueError):
    """Raised before an incomplete real-project authority chain is persisted."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Wp6ContractError(f"{label} must be a mapping")
    return value


def _stable_hash(value: Any) -> str:
    return sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _write_json(root: Path, relative: Path, payload: Any) -> Path:
    path = safe_generated_target(root, relative)
    atomic_write_text(path, json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False,
    ) + "\n")
    return path.resolve()


def _ref(path: Path) -> dict[str, str]:
    path = path.resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def build_wp6_contracts(
    *, project_root: Path, wp6_manifest_path: Path, profile_path: Path,
    evidence_bundle_path: Path, subject_track_path: Path,
    design_tokens_path: Path, audio_policy_path: Path, output_root: Path,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    output_root = output_root.absolute()
    try:
        output_relative = output_root.relative_to(project_root.absolute())
    except ValueError as error:
        raise Wp6ContractError("WP6 contract output must stay under the project root") from error
    required = {
        "wp6_manifest": wp6_manifest_path.resolve(), "profile": profile_path.resolve(),
        "evidence_bundle": evidence_bundle_path.resolve(), "subject_track": subject_track_path.resolve(),
        "design_tokens": design_tokens_path.resolve(), "audio_policy": audio_policy_path.resolve(),
    }
    for name, path in required.items():
        if not path.is_file():
            raise Wp6ContractError(f"required {name} authority is missing: {path}")
    manifest = _mapping(read_json(required["wp6_manifest"]), "WP6 authority manifest")
    if manifest.get("status") != "prepared" or manifest.get("render_authorization") != "style_reel_only":
        raise Wp6ContractError("WP6 authority manifest is not prepared for Style Reel only")
    artifacts = _mapping(manifest.get("artifacts"), "WP6 authority artifacts")
    source = Path(str(_mapping(manifest.get("source"), "WP6 source").get("path"))).resolve()
    source_ref = _ref(source)
    source_transcript = Path(str(_mapping(artifacts.get("source_transcript"), "source transcript").get("path"))).resolve()
    output_transcript = Path(str(_mapping(artifacts.get("output_transcript"), "output transcript").get("path"))).resolve()
    validation_edl = Path(str(_mapping(artifacts.get("validation_edl"), "validation EDL").get("path"))).resolve()
    scoped_semantic = Path(str(_mapping(artifacts.get("semantic_brief"), "semantic brief").get("path"))).resolve()
    phrase_captions = output_root / "authorities" / "video-use" / "master-phrase.srt"
    captions = phrase_captions if phrase_captions.is_file() else (
        output_root / "authorities" / "video-use" / "master.srt"
    )
    for path in (source_transcript, output_transcript, validation_edl, scoped_semantic, captions):
        if not path.is_file():
            raise Wp6ContractError(f"prepared WP6 authority is missing: {path}")

    transcript = _mapping(read_json(source_transcript), "scoped transcript")
    brief = deepcopy(dict(_mapping(read_json(scoped_semantic), "scoped semantic brief")))
    events = brief.get("events")
    if not isinstance(events, list) or len(events) != 3:
        raise Wp6ContractError("WP6 semantic brief must contain the three confirmed events")
    brief["schema_version"] = 3
    brief["opportunity_model"] = "decision_complete_v1"
    brief["topic"] = "告别上半辈子，温和接受平淡的人生阶段"
    tiers = {
        "life-halves-question": ("meso", "contrast", 2, 0.78),
        "self-defined-boundary": ("micro", "resolve", 1, 0.48),
        "farewell-to-first-half": ("quiet", "settle", 0, 0.22),
    }
    for row in events:
        if not isinstance(row, dict):
            raise Wp6ContractError("WP6 semantic events must be mappings")
        event_id = str(row.get("id") or "")
        if event_id not in tiers:
            raise Wp6ContractError(f"unexpected WP6 semantic event: {event_id}")
        tier, transition, attention, pressure = tiers[event_id]
        word_ids = list(row.get("transcript_word_ids") or [])
        if not word_ids:
            raise Wp6ContractError(f"{event_id} has no video-use word evidence")
        row.setdefault("semantic_role", "relate" if row.get("decision") == "render" else "resolve")
        row.setdefault("source_sentence", row.get("transcript_quote"))
        row["portrait_energy_intent"] = {
            "chapter_id": "chapter-farewell-boundary",
            "tier": tier,
            "transition_intent": transition,
            "max_attention_layers": attention,
            "rationale": str(row.get("decision_rationale") or "confirmed WP6 editorial decision"),
            "evidence_refs": [word_ids[0]],
            "fallback_tier": "quiet" if tier == "quiet" else "micro",
            "signals": {
                "semantic_pressure": pressure,
                "emotional_turn": transition,
                "speech_rate_wpm": 118.0 if tier == "quiet" else 142.0,
                "pause_seconds": 0.9 if tier == "quiet" else 0.35,
                "gesture_evidence_id": None,
                "chapter_boundary_evidence_id": None,
            },
        }
    compiled_brief = _write_json(project_root, output_relative / "semantic-brief-v3.json", brief)

    evidence_bundle = _mapping(read_json(required["evidence_bundle"]), "evidence bundle")
    subject_track = _mapping(read_json(required["subject_track"]), "subject track")
    edl = _mapping(read_json(validation_edl), "validation EDL")
    authorities = build_portrait_energy_authorities(
        transcript=transcript, evidence_bundle=evidence_bundle,
        subject_track=subject_track, semantic_brief=brief, edl=edl,
        source_hashes={
            "transcript": sha256_file(source_transcript),
            "evidence_bundle": sha256_file(required["evidence_bundle"]),
            "subject_track": sha256_file(required["subject_track"]),
            "semantic_brief": sha256_file(compiled_brief),
            "edl": sha256_file(validation_edl),
        },
    )
    chapters = derive_portrait_chapters(
        brief, evidence_authorities=authorities["evidence_by_id"],
    )
    energy = compile_portrait_energy_map(
        project_id=str(manifest.get("project_id") or ""), semantic_brief=brief,
        source_media=source_ref,
        input_hashes={
            "semantic_brief": _stable_hash(brief), "edl": sha256_file(validation_edl),
            "transcript": sha256_file(source_transcript),
            "evidence": sha256_file(required["evidence_bundle"]),
        }, chapters=chapters, evidence_authorities=authorities["evidence_by_id"],
    )
    energy_path = _write_json(
        project_root, output_relative / "portrait-energy-map.json", energy["energy_map"],
    )
    project = {
        "schema_version": 11, "video_id": str(manifest.get("project_id") or ""),
        "identity": {"mode": "self"},
        "source": {"content_type": "talking_head"},
        "motion_quality": {"enabled": True, "portrait_brand": {
            "enabled": True, "grammar_version": 2,
            "style_direction": "luminous_intelligence",
            "require_user_brand_approval": True,
        }},
    }
    playbook_path = compile_playbook(
        project=project, design_tokens_path=required["design_tokens"],
        semantic_brief_path=compiled_brief, profile_path=required["profile"],
        output_dir=output_root / "brand-playbook",
    )[0]
    render_event = next(row for row in events if row.get("decision") == "render")
    base_motion = {
        "opportunities": [{
            "semantic_event_id": render_event["id"], "decision": "render",
            "approved_visible_copy": list(render_event.get("approved_visible_copy") or []),
            "output_window": {
                "start_seconds": render_event["output_start"],
                "end_seconds": render_event["output_end"],
            },
        }],
    }
    motion = compile_portrait_motion_contracts(
        semantic_brief=brief, base_motion_contract=base_motion,
        profile_path=required["profile"], energy_map_path=energy_path,
        registry_path=DEFAULT_PORTRAIT_RECIPE_REGISTRY,
        brand_playbook_path=playbook_path,
    )
    motion_path = _write_json(
        project_root, output_relative / "portrait-motion-contracts.json", motion,
    )
    storyboard = {"events": [{
        "id": render_event["id"], "semantic_event_id": render_event["id"],
        "treatment": "portrait_brand_motion_v2",
    }]}
    storyboard_path = _write_json(project_root, output_relative / "storyboard.json", storyboard)
    library_path = materialize_portrait_sonic_library(
        DEFAULT_PORTRAIT_SONIC_REGISTRY, output_root / "sonic-library",
    )
    sonic = compile_portrait_sonic_plan(
        project_id=str(manifest.get("project_id") or ""),
        profile_path=required["profile"], motion_contracts_path=motion_path,
        semantic_brief=brief, library_manifest_path=library_path,
    )["plan"]
    sonic_path = _write_json(project_root, output_relative / "portrait-sonic-plan.json", sonic)
    base_audio = {
        "schema_version": 3,
        "speech_track": {"source": str(source), "dominant": True, "immutable": True},
        "motion_sfx": {"event_decisions": [], "mix_audibility_check": {"status": "not_applicable"}},
        "background_music": {"mode": "disabled", "enabled": False,
                             "reason": "Style Reel keeps the same voice-first comparison basis"},
        "provenance": {"source_audio": str(source)},
    }
    projected_audio = project_portrait_sonic_plan(
        sonic, base_audio, base_dir=output_root,
        motion_contracts_path=motion_path, storyboard=storyboard,
    )
    audio_plan_path = _write_json(project_root, output_relative / "audio-plan.json", projected_audio)
    plan_path = output_root / "style-reel-plan.json"
    plan = build_style_reel_plan(
        project_id=str(manifest.get("project_id") or ""), source_path=source,
        edl_path=validation_edl, transcript_path=source_transcript,
        output_transcript_path=output_transcript, semantic_brief_path=compiled_brief,
        captions_path=captions, audio_policy_path=required["audio_policy"],
        voice_stem_path=source, subject_evidence_path=required["subject_track"],
        profile_path=required["profile"],
        semantic_event_ids=list(manifest.get("semantic_event_ids") or []),
        audio_plan_path=audio_plan_path, sonic_plan_path=sonic_path,
        motion_contracts_path=motion_path, storyboard_path=storyboard_path,
        start_seconds=float(manifest["source_window"]["start_seconds"]),
        end_seconds=float(manifest["source_window"]["end_seconds"]),
        output=plan_path, authorized_root=project_root, evidence_class="real_project",
    )
    result = {
        "schema_version": 1, "status": "compiled", "plan": _ref(plan_path),
        "authority_manifest": _ref(plan_path.with_name("style-reel-authorities.json")),
        "semantic_brief": _ref(compiled_brief), "energy_map": _ref(energy_path),
        "brand_playbook": _ref(playbook_path), "motion_contracts": _ref(motion_path),
        "storyboard": _ref(storyboard_path), "sonic_plan": _ref(sonic_path),
        "audio_plan": _ref(audio_plan_path), "style_reel_plan_payload_sha256": _stable_hash(plan),
        "full_video_render_authorized": False,
    }
    report_path = _write_json(project_root, output_relative / "wp6-contract-report.json", result)
    result["report_path"] = str(report_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--wp6-manifest", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--evidence-bundle", required=True)
    parser.add_argument("--subject-track", required=True)
    parser.add_argument("--design-tokens", required=True)
    parser.add_argument("--audio-policy", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = build_wp6_contracts(
        project_root=Path(args.project_root), wp6_manifest_path=Path(args.wp6_manifest),
        profile_path=Path(args.profile), evidence_bundle_path=Path(args.evidence_bundle),
        subject_track_path=Path(args.subject_track), design_tokens_path=Path(args.design_tokens),
        audio_policy_path=Path(args.audio_policy), output_root=Path(args.output_root),
    )
    print(result["report_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
