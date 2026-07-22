#!/usr/bin/env python3
"""Evidence-bound cover production with controlled templates and local typography."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cover_editorial import CoverEditorialError, build_cover_editorial_plan
from director_adapters import AdapterRunner
from director_contracts import read_json, sha256_file, write_json


class CoverProductionActionRequired(RuntimeError):
    def __init__(self, packet: dict[str, Any]) -> None:
        super().__init__("reference-guided cover inputs or review are incomplete")
        self.packet = packet


def _resolve(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _request(
    config: dict[str, Any], *, semantic_brief: Path, output: Path,
    missing: list[str], editorial_plan: Path | None = None,
) -> dict[str, Any]:
    editorial = config.get("editorial") or {}
    return {
        "schema_version": 2,
        "generation_mode": "evidence_bound_editorial_cover" if editorial.get("enabled") else
                           "reference_guided_regeneration",
        "supported_routes": [
            "reference_regenerated", "authentic_frame_editorial", "real_person_ip_hybrid",
        ],
        "variant_count": 2,
        "aspect_ratio": "9:16",
        "semantic_brief": str(semantic_brief.resolve()),
        "editorial_plan": str(editorial_plan.resolve()) if editorial_plan else None,
        "stable_output": str(output.resolve()),
        "missing": list(dict.fromkeys(missing)),
        "clean_base_contract": {
            "same_recognizable_creator": True,
            "topic_specific_scene": True,
            "natural_slight_smile_and_engaged_eye_line": True,
            "credible_hands_and_body": True,
            "negative_space_for_local_typography": True,
            "generated_text_or_logo": False,
        },
        "local_typography_and_template_qa": True,
        "no_pasted_cutout": True,
        "paid_generation_requires_explicit_authorization": True,
        "identity_likeness_requires_user_approval_after_automation": True,
    }


def _run_or_raise(
    runner: AdapterRunner, *, name: str, command: list[str],
    inputs: list[Path], outputs: list[Path], root: Path,
) -> None:
    result = runner.run(
        name=name, enabled=True, command=command, inputs=inputs, outputs=outputs,
        blocking=True, cwd=root, settings={"timeout_seconds": 1200},
    )
    if result.get("status") not in {"complete", "reused"}:
        raise RuntimeError(f"cover adapter {name} did not complete")


def _expanded_command(
    command: list[Any], *, plan: Path, prompt: Path, output: Path, semantic_brief: Path,
) -> list[str]:
    replacements = {
        "plan": str(plan.resolve()),
        "prompt": str(prompt.resolve()),
        "output": str(output.resolve()),
        "semantic_brief": str(semantic_brief.resolve()),
    }
    expanded: list[str] = []
    for token in command:
        value = str(token)
        for name, replacement in replacements.items():
            value = value.replace("{" + name + "}", replacement)
        expanded.append(value)
    return expanded


def _prompt_packet(plan: dict[str, Any], *, variant: str) -> dict[str, Any]:
    row = plan["variants"][variant]
    return {
        "schema_version": 1,
        "variant": variant,
        "route": plan["route"],
        "communication_strategy": row["communication_strategy"],
        "template_family": row["template_family"],
        "headline_is_for_local_typography_only": plan["headline"]["text"],
        "clean_base_prompt": {
            "visual_concept": plan["evidence"]["visual_concept"],
            "subject_side": plan["subject"]["side"],
            "subject_box": plan["subject"]["box"],
            "expression": plan["subject"]["expression"],
            "negative_space": row["text_side"],
            "requirements": plan["generation_contract"],
            "forbid": [
                "generated words", "logos", "watermarks", "fake metrics",
                "unrelated floating UI", "duplicated limbs", "pasted-cutout edge",
            ],
        },
        "identity_references": plan["identity_references"],
        "expression_references": plan["expression_references"],
        "authentic_frames": plan["authentic_frames"],
        "supporting_assets": plan["supporting_assets"],
        "semantic_brief_sha256": plan["semantic_brief_sha256"],
    }


def _available_paths(rows: list[dict[str, Any]]) -> list[Path]:
    return [Path(str(row["path"])) for row in rows if row.get("available") and row.get("path")]


def produce_cover(
    *, project: dict[str, Any], project_root: Path, semantic_brief: Path,
    output: Path, work_dir: Path, runner: AdapterRunner, execute_external: bool,
) -> list[Path]:
    config = project.get("cover", {})
    editorial_enabled = (config.get("editorial") or {}).get("enabled") is True
    manifest_out = output.with_suffix(".manifest.json")
    if output.is_file() and manifest_out.is_file():
        if not editorial_enabled:
            return [output, manifest_out]
        try:
            manifest = read_json(manifest_out)
            existing_plan = Path(str(manifest.get("editorial_plan") or ""))
            existing_qa = Path(str((manifest.get("selection") or {}).get("quality_report") or ""))
            plan = read_json(existing_plan) if existing_plan.is_file() else {}
            qa = read_json(existing_qa) if existing_qa.is_file() else {}
            current = (
                semantic_brief.is_file()
                and plan.get("semantic_brief_sha256") == sha256_file(semantic_brief)
                and manifest.get("editorial_plan_sha256") == sha256_file(existing_plan)
                and qa.get("automated_passed") is True
                and qa.get("candidate_sha256") == sha256_file(output)
            )
        except (OSError, ValueError, json.JSONDecodeError):
            current = False
            existing_plan = None
            existing_qa = None
        if current:
            return [output, manifest_out, existing_plan, existing_qa]
        raise CoverProductionActionRequired(_request(
            config, semantic_brief=semantic_brief, output=output,
            missing=[
                "existing enhanced cover is stale; archive it or choose a new stable output before regeneration"
            ],
            editorial_plan=existing_plan if isinstance(existing_plan, Path) else None,
        ))

    work_dir.mkdir(parents=True, exist_ok=True)
    plan_path = work_dir / "cover-editorial-plan.json"
    plan: dict[str, Any] | None = None
    if editorial_enabled:
        try:
            plan = build_cover_editorial_plan(
                project=project, project_root=project_root,
                semantic_brief=semantic_brief, output=plan_path,
            )
        except CoverEditorialError as error:
            raise CoverProductionActionRequired(_request(
                config, semantic_brief=semantic_brief, output=output,
                missing=error.errors, editorial_plan=plan_path,
            )) from error

    identity = [_resolve(project_root, value) for value in config.get("identity_references") or []]
    expression = [_resolve(project_root, value) for value in config.get("expression_references") or []]
    identity = [path for path in identity if path and path.is_file()]
    expression = [path for path in expression if path and path.is_file()]
    variants = config.get("variants") or {}
    route = plan["route"] if plan else "reference_regenerated"
    authentic = _available_paths(plan["authentic_frames"]) if plan else []
    missing: list[str] = []
    if route != "authentic_frame_editorial" and len(identity) < 2:
        missing.append("at least two existing authorized identity reference photos")
    if route != "authentic_frame_editorial" and not expression:
        missing.append("at least one existing authorized warm-expression reference photo")
    if not semantic_brief.is_file():
        missing.append("semantic brief/topic evidence")
    for name in ("A", "B"):
        if not isinstance(variants.get(name), dict):
            missing.append(f"variant {name} clean-base generation configuration")
    if missing:
        raise CoverProductionActionRequired(_request(
            config, semantic_brief=semantic_brief, output=output,
            missing=missing, editorial_plan=plan_path if editorial_enabled else None,
        ))

    generated_bases: dict[str, Path] = {}
    prompt_paths: dict[str, Path] = {}
    for name in ("A", "B"):
        row = variants[name]
        prompt_path = work_dir / f"cover-{name.lower()}-generation-request.json"
        if plan:
            write_json(prompt_path, _prompt_packet(plan, variant=name))
            prompt_paths[name] = prompt_path
        configured_base = _resolve(project_root, row.get("clean_base"))
        if configured_base is None and route == "authentic_frame_editorial" and authentic:
            configured_base = authentic[0]
        base = configured_base or (work_dir / f"cover-{name.lower()}-clean.png")
        if not base.is_file():
            if not execute_external:
                missing.append(f"variant {name} topic-specific clean base")
                continue
            if row.get("requires_paid_call") is True and row.get("paid_call_authorized") is not True:
                missing.append(f"variant {name} paid generation authorization")
                continue
            command = row.get("generator_command") or []
            if not isinstance(command, list) or not command:
                missing.append(f"variant {name} generator adapter command")
                continue
            if not plan:
                missing.append(f"variant {name} evidence-bound editorial plan")
                continue
            _run_or_raise(
                runner,
                name=f"cover_generate_{name.lower()}",
                command=_expanded_command(
                    command, plan=plan_path, prompt=prompt_path,
                    output=base, semantic_brief=semantic_brief,
                ),
                inputs=[plan_path, prompt_path, *identity, *expression, semantic_brief],
                outputs=[base], root=project_root,
            )
        if row.get("agent_identity_reviewed") is not True:
            missing.append(f"variant {name} agent identity review")
        if row.get("agent_expression_reviewed") is not True:
            missing.append(f"variant {name} agent expression review")
        generated_bases[name] = base
    if missing or len(generated_bases) != 2:
        raise CoverProductionActionRequired(_request(
            config, semantic_brief=semantic_brief, output=output,
            missing=missing, editorial_plan=plan_path if editorial_enabled else None,
        ))
    if not execute_external:
        raise CoverProductionActionRequired(_request(
            config, semantic_brief=semantic_brief, output=output,
            missing=["local typography/A-B production execution authorization"],
            editorial_plan=plan_path if editorial_enabled else None,
        ))

    import sys
    compose_script = Path(__file__).with_name("compose_generated_cover.py")
    quality_script = Path(__file__).with_name("cover_quality.py")
    artifacts: list[Path] = [plan_path] if plan else []
    artifacts.extend(prompt_paths.values())
    manifests: dict[str, Path] = {}
    qa_reports: dict[str, Path] = {}
    for name in ("A", "B"):
        row = variants[name]
        candidate = work_dir / f"cover-{name.lower()}.jpg"
        manifest = work_dir / f"cover-{name.lower()}.manifest.json"
        plan_variant = plan["variants"][name] if plan else {}
        headline = plan["headline"] if plan else {}
        command = [
            sys.executable, str(compose_script), "--base", str(generated_bases[name]),
            "--title", str(headline.get("text") or project.get("title") or
                             project.get("content", {}).get("title") or project.get("video_id") or "Video"),
            "--label", str(headline.get("eyebrow") or config.get("label") or "CREATOR LAB"),
            "--text-side", str(plan_variant.get("text_side") or row.get("text_side") or
                                ("top-left" if name == "A" else "top-right")),
            "--template-family", str(plan_variant.get("template_family") or
                                      row.get("template_family") or "cinematic_editorial"),
            "--maximum-lines", str(headline.get("maximum_lines") or 3),
            "--target-expression", str(config.get("target_expression") or
                                         "natural friendly confidence with visible warmth"),
            "--strategy", str(plan_variant.get("communication_strategy") or row.get("strategy") or name),
            "--generator", str(row.get("generator") or "configured reference-guided generator"),
            "--generation-mode", route,
            "--rights-basis", str(config.get("rights_basis") or
                                   "authorized personal references and project-owned output"),
            "--agent-identity-reviewed", "--agent-expression-reviewed",
            "--topic-evidence", str(semantic_brief),
            "--out", str(candidate), "--manifest", str(manifest),
        ]
        if headline.get("subtitle"):
            command.extend(["--subtitle", str(headline["subtitle"])])
        if plan:
            command.extend([
                "--editorial-plan", str(plan_path), "--variant", name,
                "--subject-box", json.dumps(plan["subject"]["box"]),
            ])
            for value in headline.get("highlight_terms") or []:
                command.extend(["--highlight-term", str(value)])
            for asset in _available_paths(plan["supporting_assets"]):
                command.extend(["--supporting-asset", str(asset)])
            for frame in authentic:
                command.extend(["--authentic-frame", str(frame)])
        for reference in identity:
            command.extend(["--reference", str(reference)])
        for reference in expression:
            command.extend(["--expression-reference", str(reference)])
        for chip in (config.get("chips") or []):
            command.extend(["--chip", str(chip)])
        compose_inputs = [generated_bases[name], *identity, *expression, semantic_brief]
        if plan:
            compose_inputs.append(plan_path)
            compose_inputs.extend(_available_paths(plan["supporting_assets"]))
        _run_or_raise(
            runner, name=f"cover_compose_{name.lower()}", command=command,
            inputs=compose_inputs, outputs=[candidate, manifest], root=project_root,
        )
        artifacts.extend([generated_bases[name], candidate, manifest])
        manifests[name] = manifest
        if plan:
            qa = work_dir / f"cover-{name.lower()}-qa.json"
            thumbnail = work_dir / f"cover-{name.lower()}-thumbnail.jpg"
            _run_or_raise(
                runner, name=f"cover_quality_{name.lower()}",
                command=[
                    sys.executable, str(quality_script), "--image", str(candidate),
                    "--manifest", str(manifest), "--plan", str(plan_path),
                    "--variant", name, "--thumbnail", str(thumbnail), "--out", str(qa),
                ],
                inputs=[candidate, manifest, plan_path], outputs=[thumbnail, qa], root=project_root,
            )
            if read_json(qa).get("automated_passed") is not True:
                raise CoverProductionActionRequired(_request(
                    config, semantic_brief=semantic_brief, output=output,
                    missing=[f"variant {name} automated cover QA repair"], editorial_plan=plan_path,
                ))
            qa_reports[name] = qa
            artifacts.extend([thumbnail, qa])

    comparison = work_dir / "cover-ab-report.json"
    sheet = work_dir / "cover-ab-comparison.jpg"
    compare_command = [
        sys.executable, str(Path(__file__).with_name("compare_generated_covers.py")),
        "--manifest-a", str(manifests["A"]), "--manifest-b", str(manifests["B"]),
        "--recommended", str(config.get("recommended_variant") or "A"),
        "--rationale", str(config.get("editorial_rationale") or
                            "Variant A communicates the verified topic most directly"),
        "--sheet", str(sheet), "--out", str(comparison),
    ]
    compare_inputs = [manifests["A"], manifests["B"]]
    if qa_reports:
        compare_command.extend(["--qa-a", str(qa_reports["A"]), "--qa-b", str(qa_reports["B"])])
        compare_inputs.extend([qa_reports["A"], qa_reports["B"]])
    _run_or_raise(
        runner, name="cover_compare", command=compare_command,
        inputs=compare_inputs, outputs=[sheet, comparison], root=project_root,
    )
    promote_command = [
        sys.executable, str(Path(__file__).with_name("promote_generated_cover.py")),
        "--report", str(comparison), "--out", str(output), "--manifest", str(manifest_out),
    ]
    _run_or_raise(
        runner, name="cover_promote", command=promote_command,
        inputs=[comparison, manifests["A"], manifests["B"], *qa_reports.values()],
        outputs=[output, manifest_out], root=project_root,
    )
    artifacts.extend([sheet, comparison, output, manifest_out])
    return artifacts


def write_cover_request(path: Path, packet: dict[str, Any]) -> Path:
    write_json(path, packet)
    return path
