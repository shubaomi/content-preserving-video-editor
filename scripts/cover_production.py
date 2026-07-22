#!/usr/bin/env python3
"""Reference-guided cinematic cover production with local typography and A/B evidence."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from director_adapters import AdapterRunner
from director_contracts import write_json


class CoverProductionActionRequired(RuntimeError):
    def __init__(self, packet: dict[str, Any]) -> None:
        super().__init__("reference-guided cover inputs or review are incomplete")
        self.packet = packet


def _resolve(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _request(config: dict[str, Any], *, semantic_brief: Path, output: Path,
             missing: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generation_mode": "reference_guided_regeneration",
        "variant_count": 2,
        "aspect_ratio": "9:16",
        "semantic_brief": str(semantic_brief.resolve()),
        "stable_output": str(output.resolve()),
        "missing": missing,
        "clean_base_contract": {
            "same_recognizable_creator": True,
            "topic_specific_scene": True,
            "natural_slight_smile_and_engaged_eye_line": True,
            "credible_hands_and_body": True,
            "negative_space_for_local_typography": True,
            "generated_text_or_logo": False,
        },
        "no_pasted_cutout": True,
        "paid_generation_requires_explicit_authorization": True,
        "identity_likeness_requires_user_approval_after_automation": True,
    }


def _run_or_raise(runner: AdapterRunner, *, name: str, command: list[str],
                  inputs: list[Path], outputs: list[Path], root: Path) -> None:
    result = runner.run(
        name=name, enabled=True, command=command, inputs=inputs, outputs=outputs,
        blocking=True, cwd=root, settings={"timeout_seconds": 1200},
    )
    if result.get("status") not in {"complete", "reused"}:
        raise RuntimeError(f"cover adapter {name} did not complete")


def produce_cover(
    *, project: dict[str, Any], project_root: Path, semantic_brief: Path,
    output: Path, work_dir: Path, runner: AdapterRunner, execute_external: bool,
) -> list[Path]:
    config = project.get("cover", {})
    manifest_out = output.with_suffix(".manifest.json")
    if output.is_file() and manifest_out.is_file():
        return [output, manifest_out]
    identity = [_resolve(project_root, value) for value in config.get("identity_references") or []]
    expression = [_resolve(project_root, value) for value in config.get("expression_references") or []]
    identity = [path for path in identity if path and path.is_file()]
    expression = [path for path in expression if path and path.is_file()]
    variants = config.get("variants") or {}
    missing: list[str] = []
    if len(identity) < 2:
        missing.append("at least two existing authorized identity reference photos")
    if not expression:
        missing.append("at least one existing authorized warm-expression reference photo")
    if not semantic_brief.is_file():
        missing.append("semantic brief/topic evidence")
    for name in ("A", "B"):
        if not isinstance(variants.get(name), dict):
            missing.append(f"variant {name} clean-base generation configuration")
    if missing:
        raise CoverProductionActionRequired(_request(
            config, semantic_brief=semantic_brief, output=output, missing=missing,
        ))

    work_dir.mkdir(parents=True, exist_ok=True)
    generated_bases: dict[str, Path] = {}
    for name in ("A", "B"):
        row = variants[name]
        base = _resolve(project_root, row.get("clean_base")) or (work_dir / f"cover-{name.lower()}-clean.png")
        if not base.is_file():
            if not execute_external:
                missing.append(f"variant {name} reference-guided clean base")
                continue
            if row.get("requires_paid_call") is True and row.get("paid_call_authorized") is not True:
                missing.append(f"variant {name} paid generation authorization")
                continue
            command = row.get("generator_command") or []
            if not isinstance(command, list) or not command:
                missing.append(f"variant {name} generator adapter command")
                continue
            _run_or_raise(
                runner, name=f"cover_generate_{name.lower()}",
                command=[str(value) for value in command], inputs=[*identity, *expression, semantic_brief],
                outputs=[base], root=project_root,
            )
        if row.get("agent_identity_reviewed") is not True:
            missing.append(f"variant {name} agent identity review")
        if row.get("agent_expression_reviewed") is not True:
            missing.append(f"variant {name} agent expression review")
        generated_bases[name] = base
    if missing or len(generated_bases) != 2:
        raise CoverProductionActionRequired(_request(
            config, semantic_brief=semantic_brief, output=output, missing=missing,
        ))
    if not execute_external:
        raise CoverProductionActionRequired(_request(
            config, semantic_brief=semantic_brief, output=output,
            missing=["local typography/A-B production execution authorization"],
        ))

    import sys
    compose_script = Path(__file__).with_name("compose_generated_cover.py")
    artifacts: list[Path] = []
    manifests: dict[str, Path] = {}
    for name in ("A", "B"):
        row = variants[name]
        candidate = work_dir / f"cover-{name.lower()}.jpg"
        manifest = work_dir / f"cover-{name.lower()}.manifest.json"
        command = [
            sys.executable, str(compose_script), "--base", str(generated_bases[name]),
            "--title", str(project.get("title") or project.get("content", {}).get("title") or
                             project.get("video_id") or "Video"),
            "--label", str(config.get("label") or "CREATOR LAB"),
            "--text-side", str(row.get("text_side") or ("top-left" if name == "A" else "top-right")),
            "--target-expression", str(config.get("target_expression") or
                                         "natural friendly confidence with visible warmth"),
            "--strategy", str(row.get("strategy") or name),
            "--topic-evidence", str(semantic_brief),
            "--generator", str(row.get("generator") or "configured reference-guided generator"),
            "--rights-basis", str(config.get("rights_basis") or
                                   "authorized personal references and project-owned output"),
            "--agent-identity-reviewed", "--agent-expression-reviewed",
            "--out", str(candidate), "--manifest", str(manifest),
        ]
        for reference in identity:
            command.extend(["--reference", str(reference)])
        for reference in expression:
            command.extend(["--expression-reference", str(reference)])
        for chip in (config.get("chips") or []):
            command.extend(["--chip", str(chip)])
        _run_or_raise(
            runner, name=f"cover_compose_{name.lower()}", command=command,
            inputs=[generated_bases[name], *identity, *expression, semantic_brief],
            outputs=[candidate, manifest], root=project_root,
        )
        artifacts.extend([generated_bases[name], candidate, manifest])
        manifests[name] = manifest

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
    _run_or_raise(runner, name="cover_compare", command=compare_command,
                  inputs=[manifests["A"], manifests["B"]], outputs=[sheet, comparison],
                  root=project_root)
    promote_command = [
        sys.executable, str(Path(__file__).with_name("promote_generated_cover.py")),
        "--report", str(comparison), "--out", str(output), "--manifest", str(manifest_out),
    ]
    _run_or_raise(runner, name="cover_promote", command=promote_command,
                  inputs=[comparison, manifests["A"], manifests["B"]],
                  outputs=[output, manifest_out], root=project_root)
    artifacts.extend([sheet, comparison, output, manifest_out])
    return artifacts


def write_cover_request(path: Path, packet: dict[str, Any]) -> Path:
    write_json(path, packet)
    return path

