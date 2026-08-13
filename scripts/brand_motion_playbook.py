#!/usr/bin/env python3
"""Compile project evidence into a versioned HyperFrames design contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from director_contracts import read_json, sha256_file, write_json
from portrait_brand_contracts import validate_portrait_contract_schema


FIELD_MAPPING = {
    "surface.color": "tokens.surface",
    "surface.text_color": "tokens.text",
    "accent.color": "tokens.accent",
    "shape.border_radius_px": "tokens.radius_px",
    "shape.line_width_px": "tokens.line_width_px",
    "shadow.css": "tokens.shadow",
    "typography.font_family": "tokens.font_family",
    "safe_zones": "tokens.safe_zones",
}
PORTRAIT_ROLE_MOTION_GRAMMAR = {
    "mark": "pulse_dot_orbit_phrase",
    "explain": "speaker_depth_phrase",
    "relate": "open_contrast_planes",
    "sequence": "gesture_or_phrase_sequence",
    "prove": "integrated_semantic_cutaway",
    "resolve": "warm_resolution_bloom",
    "transition": "luminous_chapter_bridge",
}


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _binding(path: Path) -> dict[str, str]:
    path = path.resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def compile_playbook(
    *, project: dict[str, Any], design_tokens_path: Path, semantic_brief_path: Path,
    profile_path: Path | None, output_dir: Path,
) -> tuple[Path, Path, Path]:
    design_tokens_path = design_tokens_path.resolve()
    semantic_brief_path = semantic_brief_path.resolve()
    tokens = read_json(design_tokens_path)
    brief = read_json(semantic_brief_path)
    dimensions = (tokens.get("sampling") or {}).get("dimensions") or {}
    width = int(dimensions.get("width") or 1920)
    height = int(dimensions.get("height") or 1080)
    orientation = "portrait" if height > width else "landscape"
    profile = None
    profile_binding = None
    if profile_path is not None and profile_path.resolve().is_file():
        profile_path = profile_path.resolve()
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        profile_binding = _binding(profile_path)
    motion_config = project.get("brand", {}).get("motion_playbook", {}).get("motion", {})
    motion = {
        "speed": motion_config.get("speed", "balanced"),
        "easing": motion_config.get("easing", "cubic-bezier(.22,.8,.24,1)"),
        "entrance": motion_config.get("entrance", "fade_translate_8px"),
        "reveal": motion_config.get("reveal", "semantic_sequence"),
        "hold": motion_config.get("hold", "readable_hold"),
        "exit": motion_config.get("exit", "fade_translate_4px"),
    }
    compiled_tokens = {
        "surface": (tokens.get("surface") or {}).get("color", "#ffffff"),
        "text": (tokens.get("surface") or {}).get("text_color", "#172033"),
        "accent": (tokens.get("accent") or {}).get("color", "#35d6a6"),
        "radius_px": (tokens.get("shape") or {}).get("border_radius_px", 18),
        "line_width_px": (tokens.get("shape") or {}).get("line_width_px", 1),
        "shadow": (tokens.get("shadow") or {}).get("css", "none"),
        "font_family": (tokens.get("typography") or {}).get("font_family", "system-ui"),
        "safe_zones": tokens.get("safe_zones") or {},
    }
    implementation = Path(__file__).resolve()
    playbook = {
        "schema_version": 1,
        "video_id": project.get("video_id"),
        "topic": brief.get("topic") or project.get("content", {}).get("topic")
        or project.get("delivery", {}).get("title") or "project topic",
        "orientation": orientation,
        "aspect_ratio": f"{width}:{height}",
        "inputs": {
            "design_tokens": _binding(design_tokens_path),
            "semantic_brief": _binding(semantic_brief_path),
            "profile": profile_binding or {"status": "unavailable"},
        },
        "profile": profile,
        "project_config_sha256": _stable_hash(project),
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "field_mapping": FIELD_MAPPING,
        "tokens": compiled_tokens,
        "motion_tokens": motion,
        "component_rules": {
            "captions": "preserve video-use wording and safe zone",
            "ip_illustration": "topic-specific and semantically justified only",
            "card": "explain rather than restate subtitle",
            "process": "connectors encode ordered relations",
            "comparison": "paired surfaces share visual grammar",
            "chapter": "use at real structural boundary",
            "result_emphasis": "reserve accent for verified outcome",
        },
        "forbidden_combinations": [
            "caption_occlusion_with_card", "face_or_cursor_occlusion", "repeated_layout_family",
            "low_information_keyword_only", "unrelated_ip_illustration", "conflicting_motion_tokens",
        ],
        "manual_adjustment_policy": (
            "Project-specific optical adjustments and correction-ledger entries override compiled defaults; "
            "the compiler never rewrites those records."
        ),
    }
    portrait_config = (project.get("motion_quality") or {}).get("portrait_brand") or {}
    if portrait_config.get("enabled") is True:
        profile_errors = validate_portrait_contract_schema(
            "portrait-brand-profile", profile
        )
        if profile_errors:
            raise ValueError("invalid portrait brand profile: " + "; ".join(profile_errors))
        if orientation != "portrait":
            raise ValueError("portrait brand playbook requires portrait design geometry")
        if (project.get("identity") or {}).get("mode") != "self":
            raise ValueError("portrait brand playbook requires identity.mode self")
        if (project.get("source") or {}).get("content_type") != "talking_head":
            raise ValueError("portrait brand playbook requires talking_head content")
        direction = portrait_config.get("style_direction")
        if direction != profile.get("direction"):
            raise ValueError("portrait brand profile direction differs from project selection")
        playbook["portrait_brand"] = {
            "grammar_id": "hongrun-portrait-expressive-v2",
            "grammar_version": 2,
            "direction": direction,
            "profile_id": profile.get("profile_id"),
            "profile_version": profile.get("profile_version"),
            "profile_sha256": profile_binding["sha256"],
            "signature_primitives": list(profile.get("signature_primitives") or []),
            "role_motion_grammar": PORTRAIT_ROLE_MOTION_GRAMMAR,
            "sonic_family_ids": list(profile.get("sonic_family_ids") or []),
            "forbidden_defaults": list(profile.get("forbidden_defaults") or []),
            "fixed_cadence": False,
            "random_rotation": False,
            "product_card_default": False,
            "named_user_brand_approval_required": True,
        }
    output_dir = output_dir.resolve()
    playbook_path = output_dir / "brand-motion-playbook.json"
    css_path = output_dir / "brand-motion-tokens.css"
    design_path = output_dir / "DESIGN.md"
    css = ":root {\n" + "\n".join([
        f"  --hr-surface: {compiled_tokens['surface']};",
        f"  --hr-text: {compiled_tokens['text']};",
        f"  --hr-accent: {compiled_tokens['accent']};",
        f"  --hr-radius: {compiled_tokens['radius_px']}px;",
        f"  --hr-line-width: {compiled_tokens['line_width_px']}px;",
        f"  --hr-shadow: {compiled_tokens['shadow']};",
        f"  --hr-font-family: {compiled_tokens['font_family']};",
        f"  --hr-easing: {motion['easing']};",
    ]) + "\n}\n"
    design = (
        f"# Brand Motion Playbook\n\nTopic: {playbook['topic']}\n\n"
        f"Orientation: {orientation} ({width}x{height})\n\n"
        "Use the JSON contract and CSS variables as defaults. Preserve correction-ledger and "
        "project optical adjustments. Motion must add explanatory value.\n"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")
    design_path.write_text(design, encoding="utf-8")
    playbook["outputs"] = {"css": _binding(css_path), "design": _binding(design_path)}
    playbook["integrity_sha256"] = _stable_hash(playbook)
    write_json(playbook_path, playbook)
    return playbook_path, css_path, design_path


def validate_playbook(
    playbook: dict[str, Any], *, project: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if playbook.get("schema_version") != 1:
        errors.append("brand motion playbook schema_version must be 1")
    if playbook.get("field_mapping") != FIELD_MAPPING:
        errors.append("brand motion field mapping is incomplete or drifted")
    if project is not None and playbook.get("project_config_sha256") != _stable_hash(project):
        errors.append("brand motion project configuration binding is stale")
    for key in ("surface", "text", "accent", "radius_px", "line_width_px", "shadow",
                "font_family", "safe_zones"):
        if key not in (playbook.get("tokens") or {}):
            errors.append(f"brand motion token mapping lacks {key}")
    for phase in ("entrance", "reveal", "hold", "exit", "speed", "easing"):
        if not (playbook.get("motion_tokens") or {}).get(phase):
            errors.append(f"brand motion playbook lacks {phase}")
    for label, row in (playbook.get("inputs") or {}).items():
        if row.get("status") == "unavailable":
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or row.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append(f"brand motion input {label} is stale")
    for label, row in (playbook.get("outputs") or {}).items():
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or row.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append(f"brand motion output {label} is stale")
    implementation = playbook.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("brand motion implementation binding is stale")
    if playbook.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in playbook.items() if key != "integrity_sha256"}
    ):
        errors.append("brand motion integrity hash is stale")
    portrait = playbook.get("portrait_brand")
    if portrait is not None:
        if not isinstance(portrait, dict):
            errors.append("portrait brand playbook must be a mapping")
        else:
            if portrait.get("grammar_id") != "hongrun-portrait-expressive-v2":
                errors.append("portrait brand grammar ID is invalid")
            if portrait.get("grammar_version") != 2:
                errors.append("portrait brand grammar version must be 2")
            if portrait.get("role_motion_grammar") != PORTRAIT_ROLE_MOTION_GRAMMAR:
                errors.append("portrait brand role motion grammar is drifted")
            if portrait.get("fixed_cadence") is not False:
                errors.append("portrait brand playbook must not use fixed cadence")
            if portrait.get("random_rotation") is not False:
                errors.append("portrait brand playbook must not use random rotation")
            if portrait.get("product_card_default") is not False:
                errors.append("portrait brand playbook must not default to product cards")
            if portrait.get("named_user_brand_approval_required") is not True:
                errors.append("portrait brand playbook must retain the named-user gate")
    return errors
