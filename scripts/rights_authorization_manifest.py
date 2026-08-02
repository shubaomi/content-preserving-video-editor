#!/usr/bin/env python3
"""Validate asset rights and authorization evidence with fail-closed semantics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from action_required_contract import canonical_json, sha256_bytes, sha256_file, write_json


REQUIRED_FIELDS = ("id", "type", "path", "sha256", "rights_basis", "authorized_by",
                   "authorized_at", "usage_scope")


def _resolve_asset(base: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not value.strip():
        raise ValueError("rights asset path must be relative")
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"rights asset path escapes manifest directory: {value}") from error
    return path


def create_rights_authorization_report(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported rights manifest schema")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("rights manifest requires at least one asset")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise ValueError(f"assets[{index}] must be an object")
        asset_id = str(asset.get("id") or "").strip()
        if not asset_id or asset_id in seen:
            raise ValueError(f"assets[{index}] requires a unique id")
        seen.add(asset_id)
        if asset.get("status") != "authorized":
            raise ValueError(f"asset {asset_id} must be explicitly authorized")
        missing = [field for field in REQUIRED_FIELDS if not str(asset.get(field) or "").strip()]
        if missing:
            raise ValueError(f"asset {asset_id} missing authorization fields: {', '.join(missing)}")
        path = _resolve_asset(manifest_path.parent, str(asset["path"]))
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"authorized asset is missing: {asset['path']}")
        if sha256_file(path) != asset["sha256"]:
            raise ValueError(f"authorized asset hash does not match: {asset_id}")
        normalized.append(dict(asset))
    payload = {
        "status": "pass",
        "fail_closed": True,
        "assets": normalized,
        "manifest_sha256": sha256_file(manifest_path),
    }
    report = {
        "schema": "content-preserving-video-editor/rights-authorization-report",
        "schema_version": 1,
        **payload,
        "payload_sha256": sha256_bytes(canonical_json(payload)),
    }
    write_json(Path(output), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = create_rights_authorization_report(Path(args.manifest), Path(args.out))
    print(json.dumps({"status": report["status"], "assets": len(report["assets"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
