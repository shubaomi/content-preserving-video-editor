#!/usr/bin/env python3
"""Evidence-driven routing across supported motion task families."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from director_contracts import write_json


def route_hyperframes(project: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
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
    react_paths = (remotion.get("react_component_paths") or []) if isinstance(remotion, dict) else []
    event_ids = (remotion.get("selected_event_ids") or []) if isinstance(remotion, dict) else []
    remotion_selected = (isinstance(remotion, dict) and remotion.get("enabled") is True
                         and bool(react_paths) and bool(event_ids))
    if remotion_selected:
        renderer = "hyperframes"
        renderer_reason = "HyperFrames remains composition owner; selected events use existing React components"
        optional_event_renderer = "remotion"
    else:
        renderer = "hyperframes"
        renderer_reason = (
            "Remotion missing React component evidence or selected event IDs; HyperFrames remains default"
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
    return {
        "schema_version": 1,
        "route": route,
        "route_reason": reason,
        "renderer": renderer,
        "renderer_reason": renderer_reason,
        "optional_event_renderer": optional_event_renderer,
        "remotion_event_ids": list(event_ids) if remotion_selected else [],
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
