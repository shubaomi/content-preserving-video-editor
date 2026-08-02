#!/usr/bin/env python3
"""Non-destructive Director state migrations and explicit corrupt-state recovery."""

from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from director_contracts import STAGES


CURRENT_STATE_SCHEMA_VERSION = 7


class StateRecoveryRequired(ValueError):
    def __init__(self, message: str, quarantine_path: Path) -> None:
        super().__init__(message)
        self.quarantine_path = quarantine_path


def _pending_stage() -> dict[str, Any]:
    return {
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "artifacts": [],
        "artifact_records": [],
        "error": None,
    }


def migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a migrated copy; callers decide when an atomic write is appropriate."""
    if not isinstance(state, dict):
        raise ValueError("director state must be a mapping")
    raw_version = state.get("schema_version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise ValueError("director state schema_version must be an integer")
    if raw_version < 1:
        raise ValueError("director state schema_version must be positive")
    if raw_version > CURRENT_STATE_SCHEMA_VERSION:
        raise ValueError(
            f"director state schema version {raw_version} is newer than supported "
            f"version {CURRENT_STATE_SCHEMA_VERSION}"
        )

    migrated = deepcopy(state)
    stages = migrated.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ValueError("director state stages must be a mapping")
    for name in STAGES:
        stages.setdefault(name, _pending_stage())

    history = migrated.setdefault("migration_history", [])
    if not isinstance(history, list):
        raise ValueError("director state migration_history must be a list")
    if raw_version < 6:
        for name in STAGES:
            stages[name] = _pending_stage()
        migrated["last_invalidation"] = {
            "from_stage": "inspect",
            "reason": "state predates byte-bound schema v6 and cannot preserve completion",
            "invalidated_stages": list(STAGES),
        }
    if raw_version < 7:
        migrated.setdefault("dependency_state", {
            "schema_version": 1,
            "event_fingerprints": {},
            "last_plan": None,
        })
        history.append({
            "from_schema_version": raw_version,
            "to_schema_version": 7,
            "policy": "preserve only evidence that remains subject to Director byte revalidation",
        })
    else:
        dependency_state = migrated.setdefault("dependency_state", {})
        if not isinstance(dependency_state, dict):
            raise ValueError("director state dependency_state must be a mapping")
        dependency_state.setdefault("schema_version", 1)
        dependency_state.setdefault("event_fingerprints", {})
        dependency_state.setdefault("last_plan", None)
    migrated["schema_version"] = CURRENT_STATE_SCHEMA_VERSION
    return migrated


def load_and_migrate_state(path: Path) -> dict[str, Any]:
    """Load without rewriting; quarantine malformed JSON so recovery is explicit."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        quarantine = path.with_name(
            f"{path.name}.corrupt-{time.time_ns()}"
        )
        try:
            os.replace(path, quarantine)
        except OSError:
            quarantine = path
        raise StateRecoveryRequired(
            f"director state is unreadable and requires explicit recovery: {error}",
            quarantine,
        ) from error
    return migrate_state(raw)
