#!/usr/bin/env python3
"""Validate a fail-closed, artifact-bound pre-publication privacy checklist."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from action_required_contract import canonical_json, sha256_bytes, sha256_file, write_json


REQUIRED_ARTIFACTS = ("source_video", "final_video", "cover", "publishing_copy")
REQUIRED_PRIVACY_CHECKS = (
    "visual_pii",
    "credentials_and_secrets",
    "private_messages_history_and_filenames",
    "unintended_faces_and_voices",
    "subsecond_and_cut_boundary_exposure",
    "publishing_copy_privacy",
)
PASSING_STATUSES = {"pass", "remediated"}


def _bound_file(base: Path, record: Any, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"privacy manifest requires artifact {label}")
    value = str(record.get("path") or "")
    relative = Path(value)
    if relative.is_absolute() or not value:
        raise ValueError(f"privacy artifact {label} path must be relative")
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"privacy artifact {label} escapes manifest directory") from error
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise ValueError(f"privacy artifact {label} hash does not match")
    return path


def create_privacy_audit(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = sha256_bytes(manifest_bytes)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported privacy review schema")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("privacy manifest requires artifacts")
    paths = {name: _bound_file(manifest_path.parent, artifacts.get(name), name)
             for name in REQUIRED_ARTIFACTS}
    declared_bindings = {
        f"{name}_sha256": str(artifacts[name]["sha256"]) for name in REQUIRED_ARTIFACTS
    }
    checks = manifest.get("checks")
    if not isinstance(checks, list):
        raise ValueError("privacy manifest requires checks")
    rows = {str(row.get("id") or ""): row for row in checks if isinstance(row, dict)}
    missing = sorted(set(REQUIRED_PRIVACY_CHECKS) - set(rows))
    if missing:
        raise ValueError(f"missing privacy checks: {', '.join(missing)}")
    duplicates = [check for check in REQUIRED_PRIVACY_CHECKS
                  if sum(1 for row in checks if isinstance(row, dict) and row.get("id") == check) != 1]
    if duplicates:
        raise ValueError(f"duplicate privacy checks: {', '.join(duplicates)}")
    for check in REQUIRED_PRIVACY_CHECKS:
        row = rows[check]
        if row.get("status") not in PASSING_STATUSES:
            raise ValueError(f"privacy check {check} is not resolved")
        if not str(row.get("reviewer") or "").strip() or not str(row.get("reviewed_at") or "").strip():
            raise ValueError(f"privacy check {check} requires reviewer and reviewed_at")
        if not row.get("evidence"):
            raise ValueError(f"privacy check {check} requires evidence")
        findings = row.get("findings") or []
        if not isinstance(findings, list) or any(
            not isinstance(finding, dict) or finding.get("resolved") is not True
            for finding in findings
        ):
            raise ValueError(f"privacy check {check} has unresolved or invalid findings")
    if any(sha256_file(paths[name]) != declared_bindings[f"{name}_sha256"]
           for name in REQUIRED_ARTIFACTS):
        raise ValueError("privacy artifact changed while creating audit")
    if sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("privacy review manifest changed while creating audit")
    bindings = declared_bindings
    payload = {
        "status": "pass",
        "fail_closed": True,
        "bindings": bindings,
        "checks": checks,
        "review_manifest_sha256": manifest_sha256,
    }
    report = {
        "schema": "content-preserving-video-editor/prepublish-privacy-audit",
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
    report = create_privacy_audit(Path(args.manifest), Path(args.out))
    print(json.dumps({"status": report["status"], "output": str(Path(args.out).resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
