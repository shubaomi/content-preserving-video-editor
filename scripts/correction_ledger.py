#!/usr/bin/env python3
"""Create, validate, and replay auditable manual-finish corrections."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


def new_ledger(path: Path, *, project_root: Path) -> dict[str, Any]:
    ledger = {
        "schema_version": 1,
        "project_root": str(project_root.resolve()),
        "replay_model": "selector_or_file_target_with_before_value_guard",
        "entries": [],
    }
    write_json(path.resolve(), ledger)
    return ledger


def _parse_time(value: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid correction approval time: {value}") from error


def _validate_data(ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if ledger.get("schema_version") != 1:
        errors.append("correction ledger schema_version must be 1")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return ["correction ledger entries must be a list"]
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        prefix = f"entries[{index}]"
        correction_id = str(entry.get("correction_id", ""))
        if not correction_id or correction_id in seen:
            errors.append(f"{prefix} requires a unique correction_id")
        seen.add(correction_id)
        if not str(entry.get("event_id", "")).strip():
            errors.append(f"{prefix} requires event_id")
        target = entry.get("target") or {}
        if not target.get("file") and not target.get("selector"):
            errors.append(f"{prefix} requires a target file or selector")
        if target.get("file") and not Path(str(target["file"])).is_absolute():
            errors.append(f"{prefix} target file must be absolute")
        if not str(entry.get("property", "")).strip():
            errors.append(f"{prefix} requires property")
        if "before_value" not in entry or "after_value" not in entry:
            errors.append(f"{prefix} requires before_value and after_value")
        if entry.get("before_value") == entry.get("after_value"):
            errors.append(f"{prefix} before_value and after_value must differ")
        if not str(entry.get("reason", "")).strip():
            errors.append(f"{prefix} requires reason")
        if not str(entry.get("approved_by", "")).strip():
            errors.append(f"{prefix} requires approved_by")
        approved_at = str(entry.get("approved_at", ""))
        try:
            _parse_time(approved_at)
        except ValueError as error:
            errors.append(f"{prefix} {error}")
        related = entry.get("related_files") or []
        if not related:
            errors.append(f"{prefix} requires related file hashes")
        for related_index, row in enumerate(related):
            path = Path(str(row.get("path", "")))
            if not path.is_absolute() or not path.is_file():
                errors.append(f"{prefix}.related_files[{related_index}] file is missing")
            elif row.get("sha256") != sha256_file(path):
                errors.append(f"{prefix}.related_files[{related_index}] hash is stale")
    return errors


def validate_ledger(value: Path | dict[str, Any]) -> dict[str, Any]:
    ledger = read_json(value.resolve()) if isinstance(value, Path) else value
    errors = _validate_data(ledger)
    if errors:
        raise ValueError("correction ledger failed:\n- " + "\n- ".join(errors))
    return ledger


def append_correction(
    ledger_path: Path,
    *,
    event_id: str,
    target_file: Path | None,
    selector: str | None,
    property_name: str,
    before_value: Any,
    after_value: Any,
    reason: str,
    approved_by: str,
    approved_at: str,
    related_files: list[Path],
) -> dict[str, Any]:
    ledger_path = ledger_path.resolve()
    ledger = read_json(ledger_path)
    target = {
        "file": str(target_file.resolve()) if target_file else None,
        "selector": selector,
    }
    related = [
        {"path": str(path.resolve()), "sha256": sha256_file(path.resolve())}
        for path in related_files
    ]
    content = {
        "event_id": event_id,
        "target": target,
        "property": property_name,
        "before_value": before_value,
        "after_value": after_value,
        "reason": reason,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "related_files": related,
    }
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content["correction_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    ledger.setdefault("entries", []).append(content)
    validate_ledger(ledger)
    write_json(ledger_path, ledger)
    return content


def _set_property(target: dict[str, Any], property_name: str, before: Any, after: Any) -> None:
    parts = [part for part in property_name.split(".") if part]
    if not parts:
        raise ValueError("correction property cannot be empty")
    cursor: dict[str, Any] = target
    for part in parts[:-1]:
        value = cursor.get(part)
        if not isinstance(value, dict):
            raise ValueError(f"correction property path is missing: {property_name}")
        cursor = value
    leaf = parts[-1]
    if cursor.get(leaf) != before:
        raise ValueError(
            f"correction before_value drift for {property_name}: "
            f"expected {before!r}, found {cursor.get(leaf)!r}"
        )
    cursor[leaf] = after


def replay_corrections(document: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    validate_ledger(ledger)
    replayed = copy.deepcopy(document)
    targets = replayed.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("replay document requires a targets mapping")
    for entry in ledger.get("entries") or []:
        target_info = entry.get("target") or {}
        key = target_info.get("selector") or target_info.get("file")
        target = targets.get(str(key))
        if not isinstance(target, dict):
            raise ValueError(f"replay target is missing: {key}")
        _set_property(target, str(entry["property"]), entry["before_value"], entry["after_value"])
    return replayed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--ledger", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("--ledger", required=True)
    replay.add_argument("--input", required=True)
    replay.add_argument("--output", required=True)
    args = parser.parse_args()
    ledger = validate_ledger(Path(args.ledger))
    if args.command == "validate":
        print(args.ledger)
        return 0
    document = read_json(Path(args.input).resolve())
    write_json(Path(args.output).resolve(), replay_corrections(document, ledger))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
