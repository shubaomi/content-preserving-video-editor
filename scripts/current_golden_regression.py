#!/usr/bin/env python3
"""Versioned, hash-bound regression evidence for the current Director release."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from director import DIRECTOR_VERSION
from director_contracts import read_json, sha256_file, write_json
from fixture_acceptance import CHECK_NAMES, evaluate_suite
from project_config import CURRENT_PROJECT_SCHEMA_VERSION
from six_media_acceptance import validate_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEDIA_MANIFEST = REPO_ROOT / "references" / "validation" / "six-media-acceptance.json"
IMPLEMENTATION_PATHS = (
    Path("scripts/current_golden_regression.py"),
    Path("scripts/director.py"),
    Path("scripts/project_config.py"),
    Path("scripts/fixture_acceptance.py"),
    Path("scripts/asr_router.py"),
    Path("scripts/semantic_confidence.py"),
    Path("scripts/preview_render_parity.py"),
    Path("scripts/audio_qa.py"),
    Path("scripts/ip_production.py"),
    Path("scripts/cover_quality.py"),
    Path("scripts/event_cache.py"),
    Path("scripts/event_render_pipeline.py"),
    Path("scripts/review_server.py"),
    Path("scripts/cover_reference_pack.py"),
    Path("scripts/preference_learning.py"),
    Path("scripts/portable_audit_bundle.py"),
    Path("scripts/release_delivery_pack.py"),
    Path("scripts/feedback_loop.py"),
    Path("scripts/representative_short_media.py"),
)
_MEDIA_EVIDENCE_CACHE: dict[str, tuple[dict[str, dict[str, Any]], list[str]]] = {}


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _integrity_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "report_integrity_sha256"}


def _media_evidence(manifest_path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        manifest = read_json(manifest_path)
        base = manifest_path.resolve().parent
        cache_material = {
            "manifest": sha256_file(manifest_path),
            "files": [
                {
                    "media": sha256_file((base / str(row["media"])).resolve()),
                    "report": sha256_file((base / str(row["technical_report"])).resolve()),
                }
                for row in manifest.get("scenarios") or []
            ],
            "implementation": {
                path.as_posix(): sha256_file(REPO_ROOT / path)
                for path in (
                    Path("scripts/six_media_acceptance.py"),
                    Path("scripts/technical_qa.py"),
                    Path("scripts/validate_platform_export.py"),
                )
            },
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return {}, [f"six-media evidence is unreadable: {error}"]
    cache_key = _hash_json(cache_material)
    cached = _MEDIA_EVIDENCE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    errors = validate_manifest(manifest_path)
    if errors:
        return {}, errors
    indexed: dict[str, dict[str, Any]] = {}
    for row in manifest.get("scenarios") or []:
        report_path = (base / str(row["technical_report"])).resolve()
        technical = read_json(report_path)
        indexed[str(row["fixture_type"])] = {
            "media_sha256": row["media_sha256"],
            "technical_report_sha256": row["technical_report_sha256"],
            "representative_frames": [
                {
                    "timestamp": sample.get("timestamp"),
                    "sha256": sample.get("sha256"),
                }
                for sample in technical.get("samples") or []
            ],
            "visual_fingerprint": (row.get("characteristic_evidence") or {}).get(
                "visual_fingerprint"
            ),
            "audio_fingerprint": (row.get("characteristic_evidence") or {}).get(
                "audio_fingerprint"
            ),
        }
    result = (indexed, [])
    _MEDIA_EVIDENCE_CACHE[cache_key] = result
    return result


def build_report(
    fixture_source: Path,
    policy_path: Path,
    output: Path | None = None,
    *,
    media_manifest: Path = DEFAULT_MEDIA_MANIFEST,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    fixture_source = fixture_source.resolve()
    policy_path = policy_path.resolve()
    media_manifest = media_manifest.resolve()
    fixtures = read_json(fixture_source)
    policy = read_json(policy_path)
    suite = evaluate_suite(fixtures, fixture_source=fixture_source)
    required = policy.get("required_checks")
    if required != list(CHECK_NAMES):
        raise ValueError("golden policy required_checks does not match the executable contract")
    media, media_errors = _media_evidence(media_manifest)
    cases = []
    for scenario in suite.get("scenarios") or []:
        fixture_type = str(scenario.get("fixture_type"))
        cases.append({
            "id": scenario.get("id"),
            "fixture_type": fixture_type,
            "scenario_evidence_sha256": scenario.get("scenario_evidence_sha256"),
            "checks": scenario.get("checks"),
            "media_evidence": media.get(fixture_type),
        })
    status = "pass" if (
        suite.get("status") == "pass"
        and not media_errors
        and len(media) == len(cases)
        and all(len((case.get("media_evidence") or {}).get("representative_frames") or []) >= 3
                for case in cases)
    ) else "failed"
    report: dict[str, Any] = {
        "schema_version": 1,
        "suite_version": policy.get("suite_version"),
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "status": status,
        "automated_evidence_boundary": (
            "The suite verifies deterministic semantics, captions, technical frames, audio, geometry, "
            "and parity contracts. It does not approve aesthetics, identity likeness, or platform results."
        ),
        "source": {"path": _relative(fixture_source), "sha256": sha256_file(fixture_source)},
        "policy": {"path": _relative(policy_path), "sha256": sha256_file(policy_path)},
        "media_manifest": {
            "path": _relative(media_manifest),
            "sha256": sha256_file(media_manifest) if media_manifest.is_file() else None,
            "errors": media_errors,
        },
        "bindings": {
            "director_version": DIRECTOR_VERSION,
            "project_schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "implementation_sha256": {
                path.as_posix(): sha256_file(REPO_ROOT / path) for path in IMPLEMENTATION_PATHS
            },
            "fixture_suite_sha256": _hash_json(suite),
        },
        "cases": cases,
    }
    report["report_integrity_sha256"] = _hash_json(_integrity_payload(report))
    if output is not None:
        write_json(output, report)
    return report


def validate_report(
    report_path: Path,
    fixture_source: Path,
    policy_path: Path,
    *,
    media_manifest: Path = DEFAULT_MEDIA_MANIFEST,
    now: datetime | None = None,
) -> list[str]:
    if not report_path.is_file():
        return ["current golden regression report is missing"]
    try:
        report = read_json(report_path)
        policy = read_json(policy_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"current golden regression report is unreadable: {error}"]
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("current golden regression schema_version is unsupported")
    if report.get("status") != "pass":
        errors.append("current golden regression did not pass")
    if report.get("report_integrity_sha256") != _hash_json(_integrity_payload(report)):
        errors.append("current golden regression integrity hash is stale")
    try:
        generated = datetime.fromisoformat(str(report.get("generated_at")))
        if generated.tzinfo is None:
            raise ValueError("timezone is required")
        age_days = ((now or datetime.now(timezone.utc)) - generated).total_seconds() / 86400
        max_age = policy.get("max_age_days")
        if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 1:
            errors.append("golden policy max_age_days is invalid")
        elif age_days < -1 or age_days > max_age:
            errors.append("current golden regression evidence is expired or future-dated")
    except (TypeError, ValueError):
        errors.append("current golden regression generated_at is invalid")
    try:
        expected = build_report(
            fixture_source, policy_path, None, media_manifest=media_manifest,
            generated_at=datetime.fromisoformat(str(report.get("generated_at"))),
        )
        if report != expected:
            errors.append("current golden regression bindings or evidence are stale")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"current golden regression cannot be reproduced: {error}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--media-manifest", default=str(DEFAULT_MEDIA_MANIFEST))
    parser.add_argument("--out")
    parser.add_argument("--validate-report")
    args = parser.parse_args()
    if args.validate_report:
        errors = validate_report(
            Path(args.validate_report), Path(args.fixtures), Path(args.policy),
            media_manifest=Path(args.media_manifest),
        )
        if errors:
            print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False))
            return 2
        print(json.dumps({"status": "pass", "report": str(Path(args.validate_report).resolve())}))
        return 0
    if not args.out:
        parser.error("--out is required unless --validate-report is used")
    report = build_report(
        Path(args.fixtures), Path(args.policy), Path(args.out),
        media_manifest=Path(args.media_manifest),
    )
    print(Path(args.out).resolve())
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
