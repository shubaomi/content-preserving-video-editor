#!/usr/bin/env python3
"""Select and prepare topic-specific IP components only for semantic opportunities."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from director_adapters import AdapterRunner
from director_contracts import read_json, sha256_file, write_json


class IpProductionActionRequired(RuntimeError):
    def __init__(self, packet: dict[str, Any]) -> None:
        super().__init__("IP generation or human anatomy evidence is incomplete")
        self.packet = packet


def _normalize(value: Any) -> str:
    return re.sub(r"\W+", "", str(value or "").lower(), flags=re.UNICODE)


def _resolve(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _opportunities(brief: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event for event in (brief.get("events") or [])
        if event.get("form") == "ip_asset" or event.get("treatment") in {"ip_asset", "ip_visual"}
    ]


def produce_ip_components(
    *, project: dict[str, Any], project_root: Path, semantic_brief: Path,
    design_tokens: Path, output_dir: Path, runner: AdapterRunner, execute_external: bool,
) -> list[Path]:
    brief = read_json(semantic_brief)
    opportunities = _opportunities(brief)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision = output_dir / "ip-opportunity-decision.json"
    if not opportunities:
        write_json(decision, {
            "schema_version": 1, "status": "not_applicable", "selected_event_count": 0,
            "reason": "semantic brief contains no evidence-backed IP visual opportunity",
        })
        return [decision]
    manifest = output_dir / "ip-components.json"
    binding = output_dir / "ip-asset-binding.json"
    if manifest.is_file() and binding.is_file() and read_json(binding).get("passed") is True:
        return [decision, manifest, binding]

    configured = project.get("visuals", {}).get("ip_assets", {})
    missing: list[dict[str, Any]] = []
    sources: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    for event in opportunities:
        event_id = str(event.get("id") or event.get("event_id") or "")
        row = configured.get(event_id, {}) if isinstance(configured, dict) else {}
        source = _resolve(project_root, row.get("source")) if isinstance(row, dict) else None
        if source is None or not source.is_file():
            command = row.get("generator_command") if isinstance(row, dict) else None
            expected = _resolve(project_root, row.get("generated_output")) if isinstance(row, dict) else None
            paid_blocked = isinstance(row, dict) and row.get("requires_paid_call") is True \
                and row.get("paid_call_authorized") is not True
            if execute_external and command and expected and not paid_blocked:
                result = runner.run(
                    name=f"ip_generate_{event_id}", enabled=True,
                    command=[str(value) for value in command], inputs=[semantic_brief],
                    outputs=[expected], blocking=True, cwd=project_root,
                    settings={"event_id": event_id, "timeout_seconds": row.get("timeout_seconds", 900)},
                )
                if result.get("status") in {"complete", "reused"}:
                    source = expected
            if source is None or not source.is_file():
                missing.append({
                    "event_id": event_id,
                    "viewer_takeaway": event.get("viewer_takeaway"),
                    "visual_mechanism": event.get("visual_mechanism"),
                    "missing": "topic-specific generated IP source asset",
                    "paid_generation_authorization_required": paid_blocked,
                })
                continue
        anatomy = row.get("anatomy_review") or {}
        anatomy_passed = all(anatomy.get(name) is True for name in (
            "complete_frame", "hands_valid", "limbs_valid", "no_extra_appendages",
        ))
        semantic_match = _normalize(row.get("semantic_match"))
        takeaway = _normalize(event.get("viewer_takeaway"))
        if not anatomy_passed or not semantic_match or semantic_match != takeaway \
                or row.get("information_overlap_with_motion") is not False:
            missing.append({
                "event_id": event_id,
                "missing": "passing semantic, anatomy, crop, and information-dedup review",
                "required_anatomy_checks": ["complete_frame", "hands_valid", "limbs_valid",
                                             "no_extra_appendages"],
            })
            continue
        sources.append((event, row, source))
    if missing:
        raise IpProductionActionRequired({
            "schema_version": 1, "generation_mode": "topic_specific_ip_components",
            "events": missing, "transparent_or_scene_matched": True,
            "default_integration": "dynamic PiP or local composition, not full-screen cover",
            "full_screen_only_for_evidence_backed_chapter_bridge": True,
            "must_match_design_tokens": True,
        })
    if not execute_external:
        raise IpProductionActionRequired({
            "schema_version": 1, "generation_mode": "topic_specific_ip_components",
            "events": [{"event_id": str(event.get("id")),
                        "missing": "local component preparation execution"} for event, _, _ in sources],
            "transparent_or_scene_matched": True,
        })

    command = [
        sys.executable, str(Path(__file__).with_name("prepare_ip_components.py")),
        "--output-dir", str(output_dir / "components"), "--manifest", str(manifest),
    ]
    if design_tokens.is_file():
        command.extend(["--design-tokens", str(design_tokens)])
    for _, row, source in sources:
        command.extend(["--asset", f"{row.get('role', 'character')}={source}"])
    result = runner.run(
        name="ip_components", enabled=True, command=command,
        inputs=[semantic_brief, *([design_tokens] if design_tokens.is_file() else []),
                *[source for _, _, source in sources]],
        outputs=[manifest], blocking=True, cwd=project_root,
        settings={"timeout_seconds": 300},
    )
    if result.get("status") not in {"complete", "reused"}:
        raise RuntimeError("IP component preparation did not complete")
    prepared = read_json(manifest)
    components = prepared.get("components") or []
    bindings = []
    for index, (event, row, source) in enumerate(sources):
        component = components[index] if index < len(components) else {}
        bindings.append({
            "event_id": str(event.get("id")),
            "viewer_takeaway": event.get("viewer_takeaway"),
            "visual_mechanism": event.get("visual_mechanism"),
            "source": str(source), "source_sha256": sha256_file(source),
            "component": component.get("output"),
            "anatomy_review": row.get("anatomy_review"),
            "semantic_match": row.get("semantic_match"),
            "information_overlap_with_motion": False,
            "integration": {"mode": "dynamic_pip_or_local_composition",
                            "full_screen": False, "editable_in_hyperframes": True},
        })
    passed = prepared.get("overall_passed") is True and len(bindings) == len(opportunities)
    write_json(binding, {"schema_version": 1, "passed": passed, "bindings": bindings,
                         "manifest": str(manifest), "manifest_sha256": sha256_file(manifest)})
    write_json(decision, {"schema_version": 1, "status": "selected", "selected_event_count": len(bindings),
                          "manifest": str(manifest), "binding": str(binding)})
    if not passed:
        raise RuntimeError("IP component transparency or binding QA failed")
    return [decision, manifest, binding,
            *[Path(str(row.get("output"))) for row in components if row.get("output")],
            *[Path(str(row.get("evidence"))) for row in components if row.get("evidence")]]

