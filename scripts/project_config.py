#!/usr/bin/env python3
"""In-memory project configuration migrations for the video director."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


CURRENT_PROJECT_SCHEMA_VERSION = 3
MANUAL_FINISH_BACKENDS = {"opencut", "other_nle", "none"}
MANUAL_FINISH_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "backend": "none",
    "returned_final": None,
    "modifications": [],
    "assets": {},
}
PREVIEW_RENDER_PARITY_TOLERANCE_DEFAULTS: dict[str, float] = {
    "position_px": 4.0,
    "size_px": 4.0,
    "time_seconds": 0.05,
}


def _source_version(project: dict[str, Any]) -> int:
    value = project.get("schema_version", project.get("version", 1))
    try:
        version = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("project schema version must be an integer") from error
    if version < 1:
        raise ValueError("project schema version must be at least 1")
    if version > CURRENT_PROJECT_SCHEMA_VERSION:
        raise ValueError(
            f"project schema version {version} is newer than supported "
            f"version {CURRENT_PROJECT_SCHEMA_VERSION}"
        )
    return version


def migrate_project_config(project: dict[str, Any]) -> dict[str, Any]:
    """Return a current in-memory copy without modifying the source mapping/YAML."""
    if not isinstance(project, dict):
        raise ValueError("project configuration must be a mapping")
    _source_version(project)
    migrated = deepcopy(project)
    delivery = migrated.setdefault("delivery", {})
    if not isinstance(delivery, dict):
        raise ValueError("delivery must be a mapping")
    manual = delivery.setdefault("manual_finish", {})
    if not isinstance(manual, dict):
        raise ValueError("delivery.manual_finish must be a mapping")
    for key, value in MANUAL_FINISH_DEFAULTS.items():
        manual.setdefault(key, deepcopy(value))
    if manual.get("backend") not in MANUAL_FINISH_BACKENDS:
        raise ValueError(
            "delivery.manual_finish.backend must be one of "
            f"{sorted(MANUAL_FINISH_BACKENDS)}"
        )
    if not isinstance(manual.get("enabled"), bool):
        raise ValueError("delivery.manual_finish.enabled must be a boolean")
    if not isinstance(manual.get("modifications"), list):
        raise ValueError("delivery.manual_finish.modifications must be a list")
    if not isinstance(manual.get("assets"), dict):
        raise ValueError("delivery.manual_finish.assets must be a mapping")
    qa = migrated.setdefault("qa", {})
    if not isinstance(qa, dict):
        raise ValueError("qa must be a mapping")
    parity = qa.setdefault("preview_render_parity", {})
    if not isinstance(parity, dict):
        raise ValueError("qa.preview_render_parity must be a mapping")
    tolerances = parity.setdefault("tolerances", {})
    if not isinstance(tolerances, dict):
        raise ValueError("qa.preview_render_parity.tolerances must be a mapping")
    for key, value in PREVIEW_RENDER_PARITY_TOLERANCE_DEFAULTS.items():
        tolerances.setdefault(key, value)
    for key in PREVIEW_RENDER_PARITY_TOLERANCE_DEFAULTS:
        try:
            tolerance = float(tolerances[key])
        except (TypeError, ValueError) as error:
            raise ValueError(f"qa.preview_render_parity.tolerances.{key} must be numeric") from error
        if tolerance < 0:
            raise ValueError(f"qa.preview_render_parity.tolerances.{key} must be non-negative")
        tolerances[key] = tolerance
    migrated["schema_version"] = CURRENT_PROJECT_SCHEMA_VERSION
    migrated["version"] = CURRENT_PROJECT_SCHEMA_VERSION
    return migrated
