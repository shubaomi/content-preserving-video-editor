#!/usr/bin/env python3
"""Build an evidence-bound editorial plan for deterministic cover production."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from director_contracts import sha256_file, write_json
from editorial_promise import validate_promise_bindings


COVER_ROUTES = {
    "auto",
    "reference_regenerated",
    "authentic_frame_editorial",
    "real_person_ip_hybrid",
}

COVER_TEMPLATE_FAMILIES = (
    "cinematic_editorial",
    "bright_tech_tutorial",
    "dark_high_energy",
    "thought_leadership_ip",
)

TONE_TEMPLATE = {
    "cinematic": "cinematic_editorial",
    "tutorial": "bright_tech_tutorial",
    "demo": "bright_tech_tutorial",
    "review": "dark_high_energy",
    "high_energy": "dark_high_energy",
    "contrarian": "dark_high_energy",
    "thought_leadership": "thought_leadership_ip",
    "framework": "thought_leadership_ip",
    "interview": "thought_leadership_ip",
}


class CoverEditorialError(ValueError):
    """Raised when an enhanced cover plan lacks evidence or usable assets."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _resolve(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _file_record(root: Path, value: Any, **metadata: Any) -> dict[str, Any]:
    path = _resolve(root, value)
    available = bool(path and path.is_file())
    return {
        "path": str(path) if path else None,
        "available": available,
        "sha256": sha256_file(path) if available and path is not None else None,
        **metadata,
    }


def _clean_length(value: str) -> int:
    return len("".join(value.split()))


def _subject_box(side: str, configured: Any) -> tuple[list[int], bool]:
    if isinstance(configured, list) and len(configured) == 4:
        try:
            values = [int(value) for value in configured]
        except (TypeError, ValueError):
            pass
        else:
            return values, False
    defaults = {
        "left": [40, 260, 500, 1680],
        "center": [310, 300, 800, 1700],
        "right": [610, 260, 1040, 1680],
    }
    return defaults.get(side, defaults["right"]), True


def _route(
    requested: str,
    *,
    prefer_authentic: bool,
    authentic_frames: list[dict[str, Any]],
    supporting_assets: list[dict[str, Any]],
) -> str:
    if requested != "auto":
        return requested
    if prefer_authentic and any(row["available"] for row in authentic_frames):
        return "authentic_frame_editorial"
    if any(row.get("role") == "personal_ip" and row["available"] for row in supporting_assets):
        return "real_person_ip_hybrid"
    return "reference_regenerated"


def _template_pair(
    allowed: list[str], *, tone: str, route: str, variants: dict[str, Any],
) -> tuple[str, str]:
    preferred = TONE_TEMPLATE.get(tone, "cinematic_editorial")
    if route == "real_person_ip_hybrid" and "thought_leadership_ip" in allowed:
        preferred = "thought_leadership_ip"
    if preferred not in allowed:
        preferred = allowed[0]
    configured_a = str((variants.get("A") or {}).get("template_family") or preferred)
    if configured_a not in allowed:
        configured_a = preferred
    configured_b = (variants.get("B") or {}).get("template_family")
    if configured_b in allowed and configured_b != configured_a:
        return configured_a, str(configured_b)
    secondary = next((name for name in allowed if name != configured_a), configured_a)
    return configured_a, secondary


def build_cover_editorial_plan(
    *, project: dict[str, Any], project_root: Path, semantic_brief: Path, output: Path,
) -> dict[str, Any]:
    """Validate semantic cover intent and persist a deterministic production plan."""
    errors: list[str] = []
    if not semantic_brief.is_file():
        raise CoverEditorialError(["semantic brief/topic evidence is missing"])
    try:
        brief = json.loads(semantic_brief.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CoverEditorialError([f"semantic brief is unreadable: {error}"]) from error
    if not isinstance(brief, dict):
        raise CoverEditorialError(["semantic brief must be a mapping"])

    cover = project.get("cover") or {}
    editorial = cover.get("editorial") or {}
    direction = brief.get("cover_direction") or editorial.get("direction")
    if not isinstance(direction, dict):
        raise CoverEditorialError([
            "semantic brief requires cover_direction with headline, highlights, visual concept and evidence_event_ids"
        ])

    headline = str(direction.get("headline") or "").strip()
    highlights = [str(value).strip() for value in direction.get("highlight_terms") or [] if str(value).strip()]
    max_characters = int(editorial.get("headline_max_characters", 26))
    if not headline:
        errors.append("cover_direction.headline is required")
    elif _clean_length(headline) > max_characters:
        errors.append(f"cover_direction.headline exceeds {max_characters} non-space characters")
    if not highlights:
        errors.append("cover_direction.highlight_terms requires at least one evidence-backed emphasis")
    elif len(highlights) > 3:
        errors.append("cover_direction.highlight_terms supports at most three terms")
    for value in highlights:
        if value not in headline:
            errors.append(f"highlight term is not present in headline: {value}")

    events = {
        str(row.get("id")): row
        for row in brief.get("events") or []
        if isinstance(row, dict) and row.get("id")
    }
    evidence_ids = [str(value) for value in direction.get("evidence_event_ids") or []]
    if not evidence_ids:
        errors.append("cover_direction.evidence_event_ids is required")
    missing_evidence = [value for value in evidence_ids if value not in events]
    if missing_evidence:
        errors.append(
            "cover_direction.evidence_event_ids references unknown events: "
            + ", ".join(missing_evidence)
        )
    quotes = [
        str(events[value].get("transcript_quote") or events[value].get("viewer_takeaway") or "").strip()
        for value in evidence_ids if value in events
    ]
    if evidence_ids and not any(quotes):
        errors.append("cover evidence events require a transcript quote or viewer takeaway")
    visual_concept = str(direction.get("visual_concept") or "").strip()
    if not visual_concept:
        errors.append("cover_direction.visual_concept is required")

    identity = [
        _file_record(project_root, value, role="identity_reference")
        for value in cover.get("identity_references") or []
    ]
    expression = [
        _file_record(project_root, value, role="expression_reference")
        for value in cover.get("expression_references") or []
    ]
    authentic = [
        _file_record(project_root, value, role="authentic_frame")
        for value in editorial.get("authentic_frames") or []
    ]
    supporting: list[dict[str, Any]] = []
    for row in editorial.get("supporting_assets") or []:
        if not isinstance(row, dict):
            errors.append("cover.editorial.supporting_assets entries must be mappings")
            continue
        supporting.append(_file_record(
            project_root,
            row.get("path"),
            role=str(row.get("role") or "supporting_visual"),
            purpose=str(row.get("purpose") or ""),
            rights_basis=str(row.get("rights_basis") or ""),
        ))
    for row in supporting:
        if row["available"] and (not row["purpose"] or not row["rights_basis"]):
            errors.append(f"supporting asset requires purpose and rights_basis: {row['path']}")

    requested = str(direction.get("visual_route") or editorial.get("mode") or "auto")
    if requested not in COVER_ROUTES:
        errors.append(f"unsupported cover route: {requested}")
        requested = "auto"
    route = _route(
        requested,
        prefer_authentic=editorial.get("prefer_authentic_frame") is True,
        authentic_frames=authentic,
        supporting_assets=supporting,
    )
    if route == "reference_regenerated":
        if sum(row["available"] for row in identity) < 2:
            errors.append("reference_regenerated requires at least two available identity references")
        if not any(row["available"] for row in expression):
            errors.append("reference_regenerated requires an available expression reference")
    elif route == "authentic_frame_editorial" and not any(row["available"] for row in authentic):
        errors.append("authentic_frame_editorial requires an available authentic frame")
    elif route == "real_person_ip_hybrid":
        if sum(row["available"] for row in identity) < 2:
            errors.append("real_person_ip_hybrid requires at least two available identity references")
        if not any(row.get("role") == "personal_ip" and row["available"] for row in supporting):
            errors.append("real_person_ip_hybrid requires an available personal_ip supporting asset")

    allowed = [str(value) for value in editorial.get("template_families") or COVER_TEMPLATE_FAMILIES]
    invalid_templates = [value for value in allowed if value not in COVER_TEMPLATE_FAMILIES]
    if invalid_templates:
        errors.append("unsupported cover template families: " + ", ".join(invalid_templates))
    allowed = [value for value in allowed if value in COVER_TEMPLATE_FAMILIES]
    if len(set(allowed)) < 2:
        errors.append("enhanced cover production requires at least two distinct template families")
    if errors:
        raise CoverEditorialError(errors)

    promise_ledger_path = project_root / "work" / "director" / "editorial-promise-ledger.json"
    promise_binding = None
    if promise_ledger_path.is_file():
        ledger = json.loads(promise_ledger_path.read_text(encoding="utf-8"))
        promise_binding = {
            "surface": "cover", "copy": headline,
            "promise_id": str(ledger.get("promise_id") or ""),
            "proof_event_ids": evidence_ids,
        }
        binding_errors = validate_promise_bindings(ledger, [promise_binding])
        if binding_errors:
            raise CoverEditorialError(binding_errors)

    variant_config = cover.get("variants") or {}
    template_a, template_b = _template_pair(
        allowed, tone=str(direction.get("tone") or "cinematic"), route=route,
        variants=variant_config,
    )
    subject_side = str(direction.get("subject_side") or editorial.get("subject_side") or "right")
    if subject_side not in {"left", "center", "right"}:
        subject_side = "right"
    subject_box, estimated = _subject_box(subject_side, direction.get("subject_box"))
    text_side = "top-right" if subject_side == "left" else "top-left"

    plan = {
        "schema_version": 1,
        "route": route,
        "semantic_brief": str(semantic_brief.resolve()),
        "semantic_brief_sha256": sha256_file(semantic_brief),
        "headline": {
            "text": headline,
            "highlight_terms": highlights,
            "eyebrow": str(direction.get("eyebrow") or cover.get("label") or "CREATOR LAB"),
            "subtitle": str(direction.get("subtitle") or ""),
            "maximum_characters": max_characters,
            "maximum_lines": int(editorial.get("headline_max_lines", 3)),
        },
        "evidence": {
            "event_ids": evidence_ids,
            "quotes": quotes,
            "visual_concept": visual_concept,
        },
        "subject": {
            "side": subject_side,
            "box": subject_box,
            "box_is_estimate": estimated,
            "expression": str(direction.get("expression") or cover.get("target_expression") or
                              "natural friendly confidence with visible warmth"),
        },
        "identity_references": identity,
        "expression_references": expression,
        "authentic_frames": authentic,
        "supporting_assets": supporting,
        "variants": {
            "A": {
                "template_family": template_a,
                "communication_strategy": str((variant_config.get("A") or {}).get("strategy") or
                                                "topic clarity"),
                "text_side": str((variant_config.get("A") or {}).get("text_side") or text_side),
            },
            "B": {
                "template_family": template_b,
                "communication_strategy": str((variant_config.get("B") or {}).get("strategy") or
                                                "human curiosity"),
                "text_side": str((variant_config.get("B") or {}).get("text_side") or text_side),
            },
        },
        "generation_contract": {
            "clean_base_has_no_text_or_logo": True,
            "topic_specific_scene": True,
            "identity_reference_guided_when_regenerated": route != "authentic_frame_editorial",
            "local_deterministic_typography": True,
            "user_likeness_approval_required": route != "authentic_frame_editorial",
        },
        "output": str(output.resolve()),
    }
    if promise_binding is not None:
        plan["editorial_promise"] = {
            "ledger": str(promise_ledger_path.resolve()),
            "ledger_sha256": sha256_file(promise_ledger_path),
            "binding": promise_binding,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, plan)
    return plan
