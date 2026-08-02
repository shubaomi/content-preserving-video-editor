#!/usr/bin/env python3
"""Create and verify relocatable, tamper-evident action-required packets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "content-preserving-video-editor/action-required"
SCHEMA_VERSION = 1


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_relative(base: Path, target: Path) -> str:
    base = base.resolve()
    target = target.resolve()
    try:
        relative = target.relative_to(base)
    except ValueError as error:
        raise ValueError(f"artifact must be inside the packet directory: {target}") from error
    if not target.is_file() or target.is_symlink():
        raise ValueError(f"artifact must be a regular file: {target}")
    return relative.as_posix()


def _resolve_relative(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not value.strip():
        raise ValueError("artifact path must be a non-empty relative path")
    resolved = (base / path).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"artifact path escapes packet directory: {value}") from error
    return resolved


def _artifact_root(packet_parent: Path, reference_root: Path | None) -> tuple[Path, str]:
    root = (reference_root or packet_parent).resolve()
    try:
        packet_parent.resolve().relative_to(root)
    except ValueError as error:
        raise ValueError("reference_root must contain the action packet") from error
    return root, Path(os.path.relpath(root, packet_parent.resolve())).as_posix()


def create_action_packet(
    output: Path,
    *,
    stage: str,
    owner: str,
    reason: str,
    actions: list[dict[str, Any]],
    artifacts: Iterable[Path] = (),
    created_at: str | None = None,
    reference_root: Path | None = None,
    resume_command: str,
) -> dict[str, Any]:
    """Write a stable packet whose references remain valid after moving its directory."""
    output = output.resolve()
    if not all(str(value).strip() for value in (stage, owner, reason, resume_command)):
        raise ValueError("stage, owner, reason, and resume_command are required")
    if not actions:
        raise ValueError("at least one action is required")
    action_ids: set[str] = set()
    normalized_actions: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"actions[{index}] must be an object")
        action_id = str(action.get("id") or "").strip()
        instruction = str(action.get("instruction") or "").strip()
        if not action_id or not instruction:
            raise ValueError(f"actions[{index}] requires id and instruction")
        if action_id in action_ids:
            raise ValueError(f"duplicate action id: {action_id}")
        missing_fields = [
            field for field in ("owner", "command", "inputs", "expected_outputs")
            if field not in action
        ]
        if missing_fields:
            raise ValueError(
                f"actions[{index}] requires owner, command, inputs, expected_outputs"
            )
        if not str(action.get("owner") or "").strip():
            raise ValueError(f"actions[{index}] owner must be non-empty")
        if not isinstance(action.get("inputs"), list) or not isinstance(
            action.get("expected_outputs"), list
        ):
            raise ValueError(f"actions[{index}] inputs and expected_outputs must be lists")
        if not isinstance(action.get("command"), (list, dict, str)):
            raise ValueError(f"actions[{index}] command must be a list, object, or string")
        action_ids.add(action_id)
        normalized_actions.append(dict(action))

    root, root_reference = _artifact_root(output.parent, reference_root)
    records = []
    for artifact in artifacts:
        path = Path(artifact)
        relative = _safe_relative(root, path)
        records.append({"path": relative, "sha256": sha256_file(path), "size": path.stat().st_size})
    records.sort(key=lambda row: row["path"])
    payload = {
        "stage": stage,
        "owner": owner,
        "reason": reason,
        "created_at": created_at or _utc_now(),
        "resume_command": resume_command,
        "artifact_root": root_reference,
        "actions": normalized_actions,
        "artifacts": records,
    }
    packet = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "stage": stage,
        "owner": owner,
        "reason": reason,
        "actions": normalized_actions,
        "resume_command": resume_command,
        "payload": payload,
        "payload_sha256": sha256_bytes(canonical_json(payload)),
    }
    write_json(output, packet)
    return packet


def validate_action_packet(path: Path) -> dict[str, Any]:
    path = path.resolve()
    packet = json.loads(path.read_text(encoding="utf-8"))
    if packet.get("schema") != SCHEMA or packet.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported action packet schema")
    payload = packet.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("action packet payload must be an object")
    if packet.get("payload_sha256") != sha256_bytes(canonical_json(payload)):
        raise ValueError("action packet payload hash does not match")
    for name in ("stage", "owner", "reason", "created_at", "resume_command"):
        if not str(payload.get(name) or "").strip():
            raise ValueError(f"action packet payload requires {name}")
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("action packet requires actions")
    seen: set[str] = set()
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or not str(action.get("id") or "").strip() \
                or not str(action.get("instruction") or "").strip():
            raise ValueError(f"actions[{index}] requires id and instruction")
        if action["id"] in seen:
            raise ValueError(f"duplicate action id: {action['id']}")
        seen.add(action["id"])
        for field in ("owner", "command", "inputs", "expected_outputs"):
            if field not in action:
                raise ValueError(f"actions[{index}] requires {field}")
        if not str(action.get("owner") or "").strip():
            raise ValueError(f"actions[{index}] owner must be non-empty")
        if not isinstance(action.get("inputs"), list) or not isinstance(
            action.get("expected_outputs"), list
        ):
            raise ValueError(f"actions[{index}] inputs and expected_outputs must be lists")
    for name in ("stage", "owner", "reason", "actions", "resume_command"):
        if packet.get(name) != payload.get(name):
            raise ValueError(f"action packet top-level {name} compatibility field is stale")
    root_value = str(payload.get("artifact_root") or "")
    if Path(root_value).is_absolute() or not root_value:
        raise ValueError("action packet artifact_root must be relative")
    artifact_root = (path.parent / root_value).resolve()
    try:
        path.parent.resolve().relative_to(artifact_root)
    except ValueError as error:
        raise ValueError("action packet artifact_root must contain the packet") from error
    for index, record in enumerate(payload.get("artifacts") or []):
        if not isinstance(record, dict):
            raise ValueError(f"artifacts[{index}] must be an object")
        artifact = _resolve_relative(artifact_root, str(record.get("path") or ""))
        if not artifact.is_file() or artifact.is_symlink():
            raise ValueError(f"action packet artifact is missing: {record.get('path')}")
        if artifact.stat().st_size != record.get("size") or sha256_file(artifact) != record.get("sha256"):
            raise ValueError(f"action packet artifact hash does not match: {record.get('path')}")
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--out", required=True)
    create.add_argument("--stage", required=True)
    create.add_argument("--owner", required=True)
    create.add_argument("--reason", required=True)
    create.add_argument("--actions-json", required=True,
                        help="JSON file containing an array of action objects")
    create.add_argument("--artifact", action="append", default=[])
    create.add_argument("--reference-root")
    create.add_argument("--resume-command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("packet")
    args = parser.parse_args()
    if args.command == "create":
        actions = json.loads(Path(args.actions_json).read_text(encoding="utf-8"))
        if not isinstance(actions, list):
            raise ValueError("actions JSON must contain an array")
        packet = create_action_packet(
            Path(args.out), stage=args.stage, owner=args.owner, reason=args.reason,
            actions=actions, artifacts=[Path(value) for value in args.artifact],
            reference_root=Path(args.reference_root) if args.reference_root else None,
            resume_command=args.resume_command,
        )
        print(json.dumps({"status": "created", "payload_sha256": packet["payload_sha256"]}))
        return 0
    packet = validate_action_packet(Path(args.packet))
    print(json.dumps({"status": "pass", "stage": packet["payload"]["stage"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
