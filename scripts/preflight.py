#!/usr/bin/env python3
"""Read-only project and toolchain preflight for the video director."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from capability_registry import build_toolchain_report
from doctor import build_environment_statuses, summarize
from project_config import CURRENT_PROJECT_SCHEMA_VERSION, migrate_project_config
from provider_governance import build_decision_report
from director_contracts import sha256_file


PROJECT_DIRS = ("source", "edit", "hyperframes", "scripts", "work", "exports")


def _status(
    status_id: str,
    passed: bool,
    message: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": status_id,
        "status": "pass" if passed else "fail",
        "required": True,
        "message": message,
    }
    if path is not None:
        row["path"] = str(path)
    row["availability"] = "available" if passed else "action_required"
    return row


def _optional_status(status_id: str, enabled: bool, available: bool, message: str,
                     *, path: Path | None = None) -> dict[str, Any]:
    row = {
        "id": status_id,
        "status": "pass" if available or not enabled else "warn",
        "required": False,
        "availability": (
            "available" if available else "unavailable" if enabled else "disabled"
        ),
        "message": message,
    }
    if path is not None:
        row["path"] = str(path)
    return row


def _resolve(root: Path, value: Any, default: str | None = None) -> Path | None:
    if value in (None, ""):
        if default is None:
            return None
        value = default
    candidate = Path(str(value)).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _project_statuses(project_file: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    if not project_file.is_file():
        return [_status(
            "project.config", False, "project configuration file was not found", path=project_file,
        )], {}
    try:
        raw = yaml.safe_load(project_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("configuration is not a mapping")
        project = migrate_project_config(raw)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        return [{
            **_status(
                "project.config", False,
                "project configuration could not be loaded or migrated",
                path=project_file,
            ),
            "error_type": type(error).__name__,
        }], {}

    version = project.get("schema_version")
    statuses.append(_status(
        "project.config", version == CURRENT_PROJECT_SCHEMA_VERSION,
        "project configuration is valid" if version == CURRENT_PROJECT_SCHEMA_VERSION
        else "project configuration schema is not current",
        path=project_file,
    ))
    paths = project.get("paths", {})
    root = _resolve(project_file.parent, paths.get("root"), ".")
    assert root is not None
    statuses.append(_status(
        "project.root", root.is_dir(),
        "project root is available" if root.is_dir() else "project root was not found",
        path=root,
    ))
    for name in PROJECT_DIRS:
        directory = _resolve(root, paths.get(name), name)
        assert directory is not None
        statuses.append(_status(
            f"project.directory.{name}", directory.is_dir(),
            f"{name} directory is available" if directory.is_dir()
            else f"{name} directory was not found",
            path=directory,
        ))
        if directory.is_dir():
            statuses.append(_status(
                f"project.writable.{name}", os.access(directory, os.W_OK),
                f"{name} directory is writable" if os.access(directory, os.W_OK)
                else f"{name} directory is not writable",
                path=directory,
            ))

    source_value = project.get("source", {}).get("primary_video")
    source = _resolve(root, source_value)
    source_ok = source is not None and source.is_file()
    statuses.append(_status(
        "project.source", source_ok,
        "primary source media is available" if source_ok
        else "primary source media was not found",
        path=source,
    ))

    profile_value = project.get("profile")
    if profile_value:
        profile = _resolve(project_file.parent, profile_value)
        profile_ok = profile is not None and profile.is_file()
        statuses.append(_status(
            "project.profile", profile_ok,
            "profile is available" if profile_ok else "profile was not found",
            path=profile,
        ))
    else:
        statuses.append(_optional_status(
            "project.profile", False, False, "no personal profile is configured",
        ))

    optional_paths = (
        ("project.cover-reference-pack", project.get("cover", {}).get("reference_pack")),
        ("project.bgm-asset", project.get("audio", {}).get("bgm", {}).get("asset")),
        ("project.sfx-library", project.get("audio", {}).get("sfx", {}).get("library")),
    )
    for status_id, raw_path in optional_paths:
        resolved = _resolve(root, raw_path) if raw_path else None
        statuses.append(_optional_status(
            status_id, bool(raw_path), bool(resolved and resolved.exists()),
            f"{status_id.removeprefix('project.')} is available"
            if resolved and resolved.exists() else
            f"{status_id.removeprefix('project.')} is not configured or unavailable",
            path=resolved,
        ))
    fonts = project.get("brand", {}).get("fonts") or []
    if not isinstance(fonts, list):
        fonts = []
    missing_fonts = []
    for value in fonts:
        font_path = _resolve(root, value)
        if font_path is not None and not font_path.is_file():
            missing_fonts.append(str(value))
    statuses.append(_optional_status(
        "project.fonts", bool(fonts), bool(fonts) and not missing_fonts,
        "configured fonts are available" if fonts and not missing_fonts
        else "fonts are not configured" if not fonts else "one or more configured fonts are unavailable",
    ))

    governance = project.get("provider_governance") or {}
    decision = build_decision_report(config=governance, project_hash=sha256_file(project_file))
    estimate = 0.0
    for task, row in (decision.get("decisions") or {}).items():
        candidates = (governance.get("providers") or {}).get(task) or []
        if not candidates:
            continue
        selected = row.get("selected") if row.get("status") == "selected" else None
        if selected:
            estimate += float(selected.get("incremental_cost") or 0.0)
            availability = True
            message = f"provider selected for {task}: {selected.get('name')}"
        else:
            availability = False
            message = f"configured providers for {task} require authorization or current evidence"
        statuses.append(_optional_status(
            f"provider.{task}", True, availability, message,
        ))

    state_file = root / "director-state.json"
    statuses.append(_status(
        "project.director-state", True,
        "existing director state was left untouched" if state_file.exists()
        else "director state was not created",
        path=state_file,
    ))
    return statuses, {
        "currency": governance.get("currency", "USD"),
        "estimated_incremental_cost": round(estimate, 6),
        "basis": "configured authorized provider evidence only",
    }


def run_preflight(
    project_file: str | Path,
    *,
    toolchain_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(project_file).expanduser().resolve()
    inventory = toolchain_report if toolchain_report is not None else build_toolchain_report(
        probe_versions=False,
    )
    project_statuses, cost_estimate = _project_statuses(path)
    statuses = [*project_statuses, *build_environment_statuses(inventory)]
    ok, _doctor_style_overall, counts = summarize(statuses)
    # Preflight answers whether the configured project is runnable. Optional
    # capabilities remain visible as warnings but do not downgrade a runnable
    # project from PASS to WARN.
    overall = "pass" if ok else "fail"
    return {
        "schema_version": 1,
        "command": "preflight",
        "project": str(path),
        "ok": ok,
        "status": overall,
        "summary": counts,
        "statuses": statuses,
        "mutates_project": False,
        "mutates_environment": False,
        "network_access": False,
        "installs_dependencies": False,
        "cost_estimate": cost_estimate,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--project", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = run_preflight(args.project)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        f"Preflight {report['status'].upper()}: {report['summary']['pass']} available, "
        f"{report['summary']['warn']} optional, {report['summary']['fail']} action required.",
        file=sys.stderr,
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
