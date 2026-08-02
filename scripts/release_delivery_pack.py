#!/usr/bin/env python3
"""Assemble a hash-bound local release pack without uploading or publishing."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from action_required_contract import canonical_json, sha256_bytes, sha256_file, write_json
from portable_audit_bundle import copy_sanitized


AUTH_SCHEMA = "content-preserving-video-editor/publication-authorization"
PACK_SCHEMA = "content-preserving-video-editor/release-delivery-pack"
PRIVACY_SCHEMA = "content-preserving-video-editor/prepublish-privacy-audit"
RIGHTS_SCHEMA = "content-preserving-video-editor/rights-authorization-report"


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_file(path: Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"{label} is missing: {resolved}")
    return resolved


def _validate_report_envelope(report: dict[str, Any], schema: str, label: str) -> None:
    if report.get("schema") != schema or report.get("schema_version") != 1:
        raise ValueError(f"unsupported {label} schema")
    payload = {key: value for key, value in report.items()
               if key not in {"schema", "schema_version", "payload_sha256"}}
    if report.get("payload_sha256") != sha256_bytes(canonical_json(payload)):
        raise ValueError(f"{label} payload hash does not match")


def _validate_authorization(path: Path, hashes: dict[str, str]) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("separate publication authorization is required")
    authorization = _load_json(path, "publication authorization")
    if authorization.get("schema") != AUTH_SCHEMA or authorization.get("schema_version") != 1:
        raise ValueError("unsupported publication authorization schema")
    if authorization.get("authorized") is not True:
        raise ValueError("publication authorization must be explicitly granted")
    for field in ("authorized_by", "authorized_at", "platform", "publication_id"):
        if not str(authorization.get(field) or "").strip():
            raise ValueError(f"publication authorization requires {field}")
    if authorization.get("bindings") != hashes:
        raise ValueError("publication authorization bindings do not match exact video, cover, and copy")
    return authorization


def _validate_release_gates(
    sources: dict[str, Path], release_hashes: dict[str, str],
) -> dict[str, Any]:
    authorization = _validate_authorization(
        sources["publication_authorization"], release_hashes,
    )
    privacy = _load_json(sources["privacy_audit"], "privacy audit")
    _validate_report_envelope(privacy, PRIVACY_SCHEMA, "privacy audit")
    if privacy.get("status") != "pass" or privacy.get("fail_closed") is not True:
        raise ValueError("privacy audit must pass before release packing")
    privacy_bindings = privacy.get("bindings") or {}
    expected_privacy = {
        "final_video_sha256": release_hashes["video_sha256"],
        "cover_sha256": release_hashes["cover_sha256"],
        "publishing_copy_sha256": release_hashes["copy_sha256"],
    }
    if any(privacy_bindings.get(name) != value for name, value in expected_privacy.items()):
        raise ValueError("privacy audit is not bound to exact release artifacts")
    rights = _load_json(sources["rights_report"], "rights report")
    _validate_report_envelope(rights, RIGHTS_SCHEMA, "rights report")
    if rights.get("status") != "pass" or rights.get("fail_closed") is not True \
            or not str(rights.get("manifest_sha256") or "").strip():
        raise ValueError("rights authorization report must pass before release packing")
    authorized_hashes = {
        str(asset.get("sha256"))
        for asset in rights.get("assets") or []
        if isinstance(asset, dict)
        and asset.get("status") == "authorized"
        and "publication" in str(asset.get("usage_scope") or "").lower()
    }
    missing_rights = [
        name for name, digest in release_hashes.items() if digest not in authorized_hashes
    ]
    if missing_rights:
        raise ValueError(
            "rights authorization does not cover exact release assets: "
            + ", ".join(missing_rights)
        )
    return {"authorization": authorization, "privacy": privacy, "rights": rights}


def verify_release_delivery_pack(
    output_dir: Path, *, video: Path, cover: Path, publishing_copy: Path,
    privacy_audit: Path, rights_report: Path, publication_authorization: Path,
) -> dict[str, Any]:
    output_dir = Path(output_dir).resolve()
    sources = {
        "video": _require_file(video, "video"),
        "cover": _require_file(cover, "cover"),
        "publishing_copy": _require_file(publishing_copy, "publishing copy"),
        "privacy_audit": _require_file(privacy_audit, "privacy audit"),
        "rights_report": _require_file(rights_report, "rights report"),
        "publication_authorization": _require_file(
            publication_authorization, "publication authorization",
        ),
    }
    release_hashes = {
        "video_sha256": sha256_file(sources["video"]),
        "cover_sha256": sha256_file(sources["cover"]),
        "copy_sha256": sha256_file(sources["publishing_copy"]),
    }
    _validate_release_gates(sources, release_hashes)
    manifest = _load_json(output_dir / "release-pack.json", "release pack")
    if manifest.get("schema") != PACK_SCHEMA or manifest.get("schema_version") != 1:
        raise ValueError("unsupported release pack schema")
    payload = {key: value for key, value in manifest.items()
               if key not in {"schema", "schema_version", "payload_sha256"}}
    if manifest.get("payload_sha256") != sha256_bytes(canonical_json(payload)):
        raise ValueError("release pack payload hash does not match")
    if manifest.get("release_bindings") != release_hashes:
        raise ValueError("release pack bindings are stale")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("release pack artifacts are invalid")
    expected_files = {"release-pack.json"}
    for name, row in artifacts.items():
        if not isinstance(row, dict):
            raise ValueError(f"release pack artifact {name} is invalid")
        relative = Path(str(row.get("path") or ""))
        candidate = (output_dir / relative).resolve()
        if relative.is_absolute() or output_dir not in candidate.parents \
                or not candidate.is_file() or candidate.is_symlink():
            raise ValueError(f"release pack artifact {name} is missing or unsafe")
        if candidate.stat().st_size != row.get("size") or sha256_file(candidate) != row.get("sha256"):
            raise ValueError(f"release pack artifact {name} hash does not match")
        expected_files.add(relative.as_posix())
    actual_files: set[str] = set()
    for candidate in output_dir.rglob("*"):
        if candidate.is_symlink():
            raise ValueError("release pack contains a symbolic link")
        if candidate.is_file():
            actual_files.add(candidate.relative_to(output_dir).as_posix())
    if actual_files != expected_files:
        raise ValueError("release pack contains unmanifested or missing files")
    expected_evidence = {
        "privacy_audit": sha256_file(sources["privacy_audit"]),
        "rights_report": sha256_file(sources["rights_report"]),
        "publication_authorization": sha256_file(sources["publication_authorization"]),
    }
    for name, digest in expected_evidence.items():
        if (artifacts.get(name) or {}).get("sha256") != digest:
            raise ValueError(f"release pack {name} evidence is stale")
    for name, digest in (
        ("video", release_hashes["video_sha256"]),
        ("cover", release_hashes["cover_sha256"]),
        ("publishing_copy", release_hashes["copy_sha256"]),
    ):
        if (artifacts.get(name) or {}).get("sha256") != digest:
            raise ValueError(f"release pack {name} does not match authorization")
    return {"status": "pass", "artifacts_verified": len(artifacts)}


def create_release_delivery_pack(
    *,
    video: Path,
    cover: Path,
    publishing_copy: Path,
    privacy_audit: Path,
    rights_report: Path,
    publication_authorization: Path,
    output_dir: Path,
    additional_artifacts: dict[str, Path] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    publication_authorization = Path(publication_authorization).resolve()
    if not publication_authorization.is_file():
        raise ValueError("separate publication authorization is required")
    sources = {
        "video": _require_file(video, "video"),
        "cover": _require_file(cover, "cover"),
        "publishing_copy": _require_file(publishing_copy, "publishing copy"),
        "privacy_audit": _require_file(privacy_audit, "privacy audit"),
        "rights_report": _require_file(rights_report, "rights report"),
        "publication_authorization": publication_authorization,
    }
    for name, value in sorted((additional_artifacts or {}).items()):
        normalized_name = str(name).strip()
        if not normalized_name or normalized_name in sources \
                or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                       for character in normalized_name):
            raise ValueError(f"invalid additional release artifact name: {name}")
        sources[normalized_name] = _require_file(Path(value), normalized_name)
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise ValueError(f"release pack output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        artifacts: dict[str, dict[str, Any]] = {}
        snapshot_sources: dict[str, Path] = {}
        for name, source in sources.items():
            category = (
                "release" if name in {"video", "cover", "publishing_copy"}
                else "evidence" if name in {
                    "privacy_audit", "rights_report", "publication_authorization"
                } else "project_evidence"
            )
            destination = temporary / category / name / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            sanitized = False
            if category == "project_evidence" and project_root is not None:
                sanitized = copy_sanitized(source, destination, Path(project_root).resolve())
            else:
                shutil.copyfile(source, destination)
            snapshot_sources[name] = destination
            artifacts[name] = {
                "path": destination.relative_to(temporary).as_posix(),
                "sha256": sha256_file(destination),
                "size": destination.stat().st_size,
                "absolute_paths_sanitized": sanitized,
            }
        release_hashes = {
            "video_sha256": artifacts["video"]["sha256"],
            "cover_sha256": artifacts["cover"]["sha256"],
            "copy_sha256": artifacts["publishing_copy"]["sha256"],
        }
        gates = _validate_release_gates(snapshot_sources, release_hashes)
        authorization = gates["authorization"]
        payload = {
            "delivery_mode": "local_only",
            "upload_performed": False,
            "publication": {"id": authorization["publication_id"], "platform": authorization["platform"]},
            "release_bindings": release_hashes,
            "artifacts": artifacts,
            "external_action": "requires a separately authorized human or publishing tool",
        }
        manifest = {
            "schema": PACK_SCHEMA,
            "schema_version": 1,
            **payload,
            "payload_sha256": sha256_bytes(canonical_json(payload)),
        }
        write_json(temporary / "release-pack.json", manifest)
        verify_release_delivery_pack(
            temporary,
            video=snapshot_sources["video"], cover=snapshot_sources["cover"],
            publishing_copy=snapshot_sources["publishing_copy"],
            privacy_audit=snapshot_sources["privacy_audit"],
            rights_report=snapshot_sources["rights_report"],
            publication_authorization=snapshot_sources["publication_authorization"],
        )
        temporary.rename(output_dir)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--cover", required=True)
    parser.add_argument("--copy", required=True)
    parser.add_argument("--privacy-audit", required=True)
    parser.add_argument("--rights-report", required=True)
    parser.add_argument("--publication-authorization", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest = create_release_delivery_pack(
        video=Path(args.video), cover=Path(args.cover), publishing_copy=Path(args.copy),
        privacy_audit=Path(args.privacy_audit), rights_report=Path(args.rights_report),
        publication_authorization=Path(args.publication_authorization), output_dir=Path(args.out),
    )
    print(json.dumps({"status": "created", "output": str(Path(args.out).resolve()),
                      "upload_performed": manifest["upload_performed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
