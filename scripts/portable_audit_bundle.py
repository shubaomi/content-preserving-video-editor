#!/usr/bin/env python3
"""Build an offline, relocatable audit bundle while excluding sensitive inputs."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable

import yaml

from action_required_contract import canonical_json, sha256_bytes, sha256_file, write_json


SCHEMA = "content-preserving-video-editor/portable-audit-bundle"
SCHEMA_VERSION = 1
MANIFEST_NAME = "audit-bundle.json"
SENSITIVE_NAMES = {
    ".env", ".npmrc", ".pypirc", "credentials", "credentials.json", "id_rsa", "id_ed25519",
    "private-key.pem", "private_key.pem", "secrets.json",
}
SENSITIVE_NAME_TOKENS = ("secret", "credential", "private_key", "access_token", "refresh_token")
SENSITIVE_CONTENT = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)\s*[:=]\s*['\"]?(?!redacted|<redacted>)[^\s'\"]{6,}"),
    re.compile(rb"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(rb"\bhf_[A-Za-z0-9]{16,}\b"),
    re.compile(rb"(?i)\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY)\b\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
)
TEXT_SUFFIXES = {".txt", ".md", ".log", ".csv", ".srt", ".vtt", ".html", ".css"}
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/][^\s\"'<>]+)")
USER_UNIX_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:Users|home)/[^\s\"'<>]+")


class UnsafeBundleInput(ValueError):
    """Raised when a file cannot be safely represented in a portable bundle."""


def _redact_text_paths(value: str, project_root: Path) -> tuple[str, bool]:
    changed = False
    normalized = value
    for spelling in {str(project_root.resolve()), project_root.resolve().as_posix()}:
        if spelling and spelling in normalized:
            normalized = normalized.replace(spelling, "$PROJECT_ROOT")
            changed = True
    for pattern in (WINDOWS_PATH, USER_UNIX_PATH):
        replaced = pattern.sub("$EXTERNAL_PATH_REDACTED", normalized)
        changed = changed or replaced != normalized
        normalized = replaced
    return normalized, changed


def _redact_paths(value: Any, project_root: Path) -> tuple[Any, bool]:
    changed = False
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result[key], item_changed = _redact_paths(item, project_root)
            changed = changed or item_changed
        return result, changed
    if isinstance(value, list):
        result = []
        for item in value:
            normalized, item_changed = _redact_paths(item, project_root)
            result.append(normalized)
            changed = changed or item_changed
        return result, changed
    if isinstance(value, str):
        candidate = Path(value)
        looks_absolute = candidate.is_absolute() or bool(re.match(r"^[A-Za-z]:[\\/]", value))
        if looks_absolute:
            try:
                relative = candidate.resolve().relative_to(project_root.resolve())
                return f"$PROJECT_ROOT/{relative.as_posix()}", True
            except (OSError, ValueError):
                return "$EXTERNAL_PATH_REDACTED", True
        return _redact_text_paths(value, project_root)
    return value, False


def copy_sanitized(source: Path, destination: Path, project_root: Path) -> bool:
    """Copy while removing absolute machine paths from structured diagnostics."""
    suffix = source.suffix.lower()
    if suffix in {".json", ".yaml", ".yml"}:
        try:
            text = source.read_text(encoding="utf-8")
            value = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
        except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as error:
            raise UnsafeBundleInput("structured_parse_failed") from error
        normalized, changed = _redact_paths(value, project_root)
        serialized = (
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
            if suffix == ".json"
            else yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False)
        )
        destination.write_text(serialized, encoding="utf-8")
        return changed
    if suffix in TEXT_SUFFIXES:
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise UnsafeBundleInput("text_decode_failed") from error
        normalized, changed = _redact_text_paths(text, project_root)
        destination.write_text(normalized, encoding="utf-8")
        return changed
    raise UnsafeBundleInput("unsupported_binary_or_unstructured_input")


def _relative(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"bundle input must be inside project root: {path}") from error


def _sensitivity_reason(relative: Path, path: Path) -> str | None:
    lowered_parts = [part.lower() for part in relative.parts]
    if any(part in SENSITIVE_NAMES or part.startswith(".env.")
           or any(token in part for token in SENSITIVE_NAME_TOKENS)
           for part in lowered_parts):
        return "sensitive_path"
    overlap = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            data = overlap + chunk
            if any(pattern.search(data) for pattern in SENSITIVE_CONTENT):
                return "sensitive_content"
            overlap = data[-512:]
    return None


def _expand_inputs(root: Path, paths: Iterable[Path]) -> list[tuple[Path, Path]]:
    expanded: dict[str, tuple[Path, Path]] = {}
    for requested in paths:
        path = Path(requested).resolve()
        relative = _relative(root, path)
        if not path.exists():
            raise ValueError(f"bundle input does not exist: {path}")
        if path.is_symlink():
            raise ValueError(f"bundle inputs may not be symlinks: {path}")
        candidates = sorted(candidate for candidate in path.rglob("*") if candidate.is_file()) \
            if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(f"bundle inputs may not contain symlinks: {candidate}")
            candidate_relative = _relative(root, candidate)
            expanded[candidate_relative.as_posix()] = (candidate_relative, candidate)
    return [expanded[key] for key in sorted(expanded)]


def create_portable_audit_bundle(
    project_root: Path,
    output_dir: Path,
    paths: Iterable[Path],
    *,
    replace: bool = False,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    if not project_root.is_dir():
        raise ValueError(f"project root does not exist: {project_root}")
    from verify_audit_bundle import verify_audit_bundle
    active_backups = sorted(output_dir.parent.glob(f".{output_dir.name}.replace-backup*"))
    if active_backups and not output_dir.exists():
        if len(active_backups) != 1:
            raise ValueError("multiple interrupted audit bundle replacements require review")
        backup = active_backups[0]
        if backup.is_symlink() or not backup.is_dir():
            raise ValueError("audit bundle replacement backup is unsafe")
        verify_audit_bundle(backup)
        os.replace(backup, output_dir)
        active_backups = []
    if output_dir.exists() and active_backups:
        verify_audit_bundle(output_dir)
        for backup in active_backups:
            verify_audit_bundle(backup)
            retired = backup.with_name(
                f".{output_dir.name}.retired-backup-{uuid.uuid4().hex}"
            )
            os.replace(backup, retired)
            try:
                shutil.rmtree(retired)
            except OSError:
                pass
    if output_dir.exists():
        manifest_path = output_dir / MANIFEST_NAME
        if not replace:
            raise ValueError(f"bundle output already exists: {output_dir}")
        if not manifest_path.is_file():
            raise ValueError("refusing to replace a directory that is not an audit bundle")
        verify_audit_bundle(output_dir)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    entries: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    try:
        for relative, source in _expand_inputs(project_root, paths):
            reason = _sensitivity_reason(relative, source)
            if reason:
                excluded.append({"project_path": relative.as_posix(), "reason": reason})
                continue
            bundle_relative = Path("artifacts") / relative
            destination = temporary / bundle_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                sanitized = copy_sanitized(source, destination, project_root)
            except UnsafeBundleInput as error:
                destination.unlink(missing_ok=True)
                excluded.append({
                    "project_path": relative.as_posix(), "reason": str(error),
                })
                continue
            entries.append({
                "path": bundle_relative.as_posix(),
                "project_path": relative.as_posix(),
                "sha256": sha256_file(destination),
                "size": destination.stat().st_size,
                "source_sha256": sha256_file(source),
                "absolute_paths_sanitized": sanitized,
            })
        payload = {
            "entries": entries,
            "excluded": excluded,
            "reference_policy": "bundle_relative_only",
            "sensitive_material_included": False,
            "verification": "offline_sha256",
        }
        envelope = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "payload": payload,
            "payload_sha256": sha256_bytes(canonical_json(payload)),
        }
        write_json(temporary / MANIFEST_NAME, envelope)
        verify_audit_bundle(temporary)
        if output_dir.exists():
            backup = output_dir.with_name(
                f".{output_dir.name}.replace-backup-{uuid.uuid4().hex}"
            )
            os.replace(output_dir, backup)
            try:
                os.replace(temporary, output_dir)
            except Exception:
                os.replace(backup, output_dir)
                raise
            retired = backup.with_name(
                f".{output_dir.name}.retired-backup-{uuid.uuid4().hex}"
            )
            os.replace(backup, retired)
            try:
                shutil.rmtree(retired)
            except OSError:
                pass
        else:
            os.replace(temporary, output_dir)
        return payload
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    payload = create_portable_audit_bundle(
        Path(args.project_root), Path(args.out), [Path(path) for path in args.paths], replace=args.replace,
    )
    print(json.dumps({"status": "created", "entries": len(payload["entries"]),
                      "excluded": len(payload["excluded"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
