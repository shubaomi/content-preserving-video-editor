#!/usr/bin/env python3
"""Materialize a hash-bound, fail-closed real-project canary receipt."""
from __future__ import annotations

import argparse
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

from director_contracts import sha256_file, write_json
from motion_contracts import _probe_video_media, validate_real_project_validation
from project_config import CURRENT_PROJECT_SCHEMA_VERSION
from test_acceptance_report import source_tree_sha256


MediaProbe = Callable[[Path], Mapping[str, Any]]


def _absolute_file(raw: object, label: str) -> Path:
    path = Path(str(raw or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} file is missing: {path}")
    return path


def _artifact(record: Mapping[str, Any], label: str, default_type: str) -> dict[str, Any]:
    path = _absolute_file(record.get("path"), label)
    purpose = str(record.get("purpose") or "").strip()
    if not purpose:
        raise ValueError(f"{label} purpose is required")
    return {
        "artifact_type": str(record.get("artifact_type") or default_type),
        "path": str(path),
        "sha256": sha256_file(path),
        "purpose": purpose,
    }


def _media(record: Mapping[str, Any], label: str, probe: MediaProbe) -> dict[str, Any]:
    artifact = _artifact(record, label, "video_mp4")
    observed = probe(Path(artifact["path"]))
    duration = float(observed.get("duration_seconds") or 0)
    width = int(observed.get("width") or 0)
    height = int(observed.get("height") or 0)
    if duration <= 0 or width <= 0 or height <= 0:
        raise ValueError(f"{label} probe returned invalid media metadata")
    return {
        **artifact,
        "duration_seconds": duration,
        "width": width,
        "height": height,
    }


def _current_implementation(root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()
    return {
        "git_commit": commit,
        "source_tree_sha256": source_tree_sha256(root),
        "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
    }


def build_receipt(
    *,
    spec: Mapping[str, Any],
    output: Path,
    configuration_path: Path,
    implementation: Mapping[str, Any] | None = None,
    media_probe: MediaProbe | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Build and validate one immutable real-project validation receipt.

    Caller-authored hashes and media dimensions are intentionally ignored. The
    builder derives them from files that exist at build time, then invokes the
    semantic validator before writing anything.
    """
    probe = media_probe or _probe_video_media
    config = _absolute_file(configuration_path, "project configuration")
    root = (repository_root or Path(__file__).parents[1]).resolve()
    receipt = deepcopy(dict(spec))
    receipt.setdefault("schema_version", "1.0.0")
    receipt.setdefault("producer", "content-preserving-video-editor")
    receipt.setdefault("media_kind", "real")
    receipt["implementation"] = dict(implementation or _current_implementation(root))
    receipt["configuration_sha256"] = sha256_file(config)
    receipt["source"] = _media(receipt.get("source") or {}, "source", probe)
    receipt["baseline"] = _media(receipt.get("baseline") or {}, "baseline", probe)
    receipt["candidate"] = _media(receipt.get("candidate") or {}, "candidate", probe)

    rights = dict(receipt.get("rights") or {})
    rights["evidence"] = _artifact(
        rights.get("evidence") or {}, "rights evidence", "rights_record",
    )
    receipt["rights"] = rights

    results: list[dict[str, Any]] = []
    for result_index, raw_result in enumerate(receipt.get("requirement_results") or []):
        result = dict(raw_result)
        evidence = []
        for evidence_index, raw_artifact in enumerate(result.get("evidence") or []):
            evidence.append(_artifact(
                raw_artifact,
                f"requirement_results[{result_index}].evidence[{evidence_index}]",
                "qa_report",
            ))
        result["evidence"] = evidence
        results.append(result)
    receipt["requirement_results"] = results

    validation_errors = validate_real_project_validation(
        receipt,
        media_probe=probe,
        repository_root=root if implementation is None else None,
        configuration_path=config,
    )
    if validation_errors:
        raise ValueError("real-project validation receipt is invalid:\n- " + "\n- ".join(validation_errors))
    write_json(output.resolve(), receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()
    spec = json.loads(args.spec.resolve().read_text(encoding="utf-8"))
    receipt = build_receipt(
        spec=spec,
        output=args.output,
        configuration_path=args.project,
        repository_root=args.repo,
    )
    print(json.dumps({
        "status": "pass",
        "output": str(args.output.resolve()),
        "validation_id": receipt["validation_id"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
