#!/usr/bin/env python3
"""Report local video-director prerequisites without changing the environment."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from capability_registry import build_toolchain_report


HYPERFRAMES_SKILLS = (
    "hyperframes",
    "hyperframes-core",
    "hyperframes-creative",
    "hyperframes-animation",
    "hyperframes-cli",
)
REQUIRED_TOOLS = ("python", "ffmpeg", "ffprobe", "node", "npm", "npx")
OPTIONAL_PROVIDER_ENVIRONMENT = (
    "MINIMAX_API_KEY", "MINIMAX_API_HOST", "ELEVENLABS_API_KEY",
)


def _status(
    status_id: str,
    passed: bool,
    message: str,
    *,
    required: bool = True,
    path: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": status_id,
        "status": "pass" if passed else ("fail" if required else "warn"),
        "required": required,
        "message": message,
    }
    if path:
        row["path"] = path
    row["availability"] = (
        "available" if passed else "unavailable" if required else "optional"
    )
    return row


def build_environment_statuses(toolchain_report: dict[str, Any]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    tools = toolchain_report.get("tools", {})
    for name in REQUIRED_TOOLS:
        record = tools.get(name, {})
        available = record.get("available") is True
        statuses.append(_status(
            f"tool.{name}", available,
            f"{name} is available" if available else f"{name} was not found",
            path=record.get("path"),
        ))

    hyperframes_command = tools.get("hyperframes", {})
    command_available = hyperframes_command.get("available") is True
    statuses.append(_status(
        "tool.hyperframes", command_available,
        "HyperFrames command is available" if command_available
        else "HyperFrames command was not found; an installed local npx package may still provide it",
        required=False,
        path=hyperframes_command.get("path"),
    ))

    skill_records = toolchain_report.get("required_hyperframes_skills", {})
    for name in HYPERFRAMES_SKILLS:
        record = skill_records.get(name, {})
        available = record.get("available") is True
        statuses.append(_status(
            f"skill.{name}", available,
            f"{name} Skill is available" if available else f"{name} Skill was not found",
            path=record.get("path"),
        ))

    video_use = toolchain_report.get("skill_roots", {}).get("video-use", {})
    available = video_use.get("available") is True
    statuses.append(_status(
        "skill.video-use", available,
        "video-use Skill is available" if available else "video-use Skill was not found",
        path=video_use.get("path"),
    ))
    return statuses


def summarize(statuses: list[dict[str, Any]]) -> tuple[bool, str, dict[str, int]]:
    counts = {
        name: sum(row["status"] == name for row in statuses)
        for name in ("pass", "warn", "fail")
    }
    ok = counts["fail"] == 0
    overall = "fail" if not ok else "warn" if counts["warn"] else "pass"
    return ok, overall, counts


def run_doctor(*, toolchain_report: dict[str, Any] | None = None) -> dict[str, Any]:
    inventory = toolchain_report if toolchain_report is not None else build_toolchain_report(
        probe_versions=False,
    )
    statuses = build_environment_statuses(inventory)
    ok, overall, counts = summarize(statuses)
    return {
        "schema_version": 1,
        "command": "doctor",
        "ok": ok,
        "status": overall,
        "summary": counts,
        "statuses": statuses,
        "mutates_environment": False,
        "network_access": False,
        "installs_dependencies": False,
        "provider_environment": {
            name: {"configured": bool(os.environ.get(name)), "value_exposed": False}
            for name in OPTIONAL_PROVIDER_ENVIRONMENT
        },
    }


def terminal_summary(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    return (
        f"Doctor {str(report.get('status', 'unknown')).upper()}: "
        f"{summary.get('pass', 0)} available, {summary.get('warn', 0)} optional, "
        f"{summary.get('fail', 0)} action required."
    )


def parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


def main(argv: list[str] | None = None) -> int:
    parser().parse_args(argv)
    report = run_doctor()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(terminal_summary(report), file=sys.stderr)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
