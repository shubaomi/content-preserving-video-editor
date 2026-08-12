#!/usr/bin/env python3
"""Build and validate a deterministic manifest of HyperFrames project sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from director_contracts import sha256_file, write_json


MANIFEST_NAME = "renderer-project-manifest.json"
EXCLUDED_FILE_NAMES = {
    MANIFEST_NAME,
    "audio-plan.json",
    "audio-sfx-manifest.json",
    "bgm-provenance.json",
    "mix-audibility.json",
    "renderer-evidence-contract.json",
    "renderer-export.json",
    "sample-preview.mp4",
}
EXCLUDED_DIRECTORY_NAMES = {
    "keyframe-receipts",
    "motion-snapshots",
    "snapshots",
    "renders",
    "render",
    "dist",
    ".cache",
}
EXCLUDED_RELATIVE_PREFIXES = {
    ("assets", "sfx"),
    ("review-audio",),
}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _included_files(project_root: Path, output: Path) -> list[Path]:
    result: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file() or path.resolve() == output.resolve():
            continue
        relative = path.relative_to(project_root)
        if path.name in EXCLUDED_FILE_NAMES:
            continue
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts[:-1]):
            continue
        if any(relative.parts[:len(prefix)] == prefix for prefix in EXCLUDED_RELATIVE_PREFIXES):
            continue
        result.append(path.resolve())
    return sorted(result, key=lambda path: path.relative_to(project_root).as_posix())


def build_manifest(project_root: Path, output: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    output = output.resolve()
    if not project_root.is_dir():
        raise ValueError("HyperFrames project root is missing")
    try:
        output.relative_to(project_root)
    except ValueError as error:
        raise ValueError("renderer project manifest must be inside the project root") from error
    required = [project_root / "index.html", project_root / "storyboard.json"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError("renderer project manifest requires: " + ", ".join(missing))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "project_root": str(project_root),
        "files": [
            {
                "relative_path": path.relative_to(project_root).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in _included_files(project_root, output)
        ],
        "runtime_evidence_excluded": sorted(
            EXCLUDED_FILE_NAMES
            | EXCLUDED_DIRECTORY_NAMES
            | {"/".join(prefix) for prefix in EXCLUDED_RELATIVE_PREFIXES}
        ),
    }
    payload["integrity_sha256"] = _stable_hash(payload)
    write_json(output, payload)
    return payload


def validate_manifest(manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("renderer project manifest schema_version must be 1")
    manifest_path = manifest_path.resolve()
    project_root_value = str(manifest.get("project_root") or "")
    if not project_root_value or not Path(project_root_value).is_absolute():
        return [*errors, "renderer project manifest root must be an absolute path"]
    project_root = Path(project_root_value)
    if not project_root.is_dir():
        return [*errors, "renderer project manifest root is missing"]
    project_root = project_root.resolve()
    try:
        manifest_path.relative_to(project_root)
    except ValueError:
        errors.append("renderer project manifest path escapes project root")
    rows = manifest.get("files")
    if not isinstance(rows, list):
        return [*errors, "renderer project manifest files must be a list"]
    names = [
        str(row.get("relative_path") or "") for row in rows if isinstance(row, dict)
    ]
    if len(names) != len(rows):
        errors.append("renderer project manifest contains invalid file entries")
    if len(names) != len(set(names)):
        errors.append("renderer project manifest contains duplicate file entries")
    if names != sorted(names):
        errors.append("renderer project manifest file inventory must be sorted")
    expected_names = [
        path.relative_to(project_root).as_posix()
        for path in _included_files(project_root, manifest_path)
    ]
    if names != expected_names:
        errors.append("renderer project manifest inventory is stale")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        relative = Path(str(row.get("relative_path") or ""))
        path = (project_root / relative).resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            errors.append(f"renderer project manifest files[{index}] escapes project root")
            continue
        if not path.is_file():
            errors.append(f"renderer project manifest file is missing: {relative.as_posix()}")
            continue
        if row.get("sha256") != sha256_file(path):
            errors.append(f"renderer project manifest file hash is stale: {relative.as_posix()}")
        if row.get("size_bytes") != path.stat().st_size:
            errors.append(f"renderer project manifest file size is stale: {relative.as_posix()}")
    expected_integrity = _stable_hash({
        key: value for key, value in manifest.items() if key != "integrity_sha256"
    })
    if manifest.get("integrity_sha256") != expected_integrity:
        errors.append("renderer project manifest integrity hash is stale")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a hash-bound manifest of HyperFrames project sources.",
    )
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.project, args.out)
    errors = validate_manifest(manifest, args.out)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(str(args.out.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
