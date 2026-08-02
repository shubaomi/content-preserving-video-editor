#!/usr/bin/env python3
"""Verify a portable audit bundle using only local manifest data and SHA-256."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from action_required_contract import canonical_json, sha256_bytes, sha256_file
from portable_audit_bundle import MANIFEST_NAME, SCHEMA, SCHEMA_VERSION


def _resolve_entry(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not value.strip():
        raise ValueError("bundle entry path must be relative")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"bundle entry escapes bundle root: {value}") from error
    return resolved


def verify_audit_bundle(bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    manifest_path = bundle_dir / MANIFEST_NAME
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    if envelope.get("schema") != SCHEMA or envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported audit bundle schema")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("audit bundle manifest payload must be an object")
    if envelope.get("payload_sha256") != sha256_bytes(canonical_json(payload)):
        raise ValueError("audit bundle manifest payload hash does not match")
    if payload.get("reference_policy") != "bundle_relative_only" \
            or payload.get("sensitive_material_included") is not False:
        raise ValueError("audit bundle safety policy is invalid")
    seen: set[str] = set()
    for index, entry in enumerate(payload.get("entries") or []):
        if not isinstance(entry, dict):
            raise ValueError(f"entries[{index}] must be an object")
        value = str(entry.get("path") or "")
        if value in seen:
            raise ValueError(f"duplicate bundle entry: {value}")
        seen.add(value)
        path = _resolve_entry(bundle_dir, value)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"bundle entry is missing: {value}")
        if path.stat().st_size != entry.get("size") or sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"bundle entry hash does not match: {value}")
    actual = {
        path.relative_to(bundle_dir).as_posix()
        for path in (bundle_dir / "artifacts").rglob("*") if path.is_file()
    } if (bundle_dir / "artifacts").exists() else set()
    if actual != seen:
        raise ValueError("bundle contains unmanifested or missing artifact files")
    return {"status": "pass", "entries_verified": len(seen), "offline_verification": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    args = parser.parse_args()
    print(json.dumps(verify_audit_bundle(Path(args.bundle))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
