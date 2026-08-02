#!/usr/bin/env python3
"""Create an auditable localization request or validate a configured fixture result."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def build_localization_manifest(
    *, transcript_path: Path, target_language: str, glossary: dict[str, str],
    provider: dict[str, Any], voice_clone_authorized: bool, output: Path,
) -> dict[str, Any]:
    transcript_path = transcript_path.resolve(); transcript = read_json(transcript_path)
    words = [row for row in transcript.get("words") or [] if row.get("type", "word") == "word"]
    implementation = Path(__file__).resolve()
    request_contract = {
        "transcript_sha256": sha256_file(transcript_path),
        "glossary_sha256": _stable_hash(glossary),
    }
    report = {
        "schema_version": 1, "target_language": target_language, "glossary": glossary,
        "transcript": {"path": str(transcript_path), "sha256": sha256_file(transcript_path)},
        "provider": {key: provider.get(key) for key in ("name", "backend", "model")},
        "voice_clone_authorized": voice_clone_authorized,
        "request_contract": request_contract,
        "tts_or_lipsync_claimed": False,
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "translations": [],
    }
    if not provider:
        report.update({"status": "action_required",
                       "reason": "translation provider is not configured"})
    elif provider.get("backend") == "result_file":
        result_path = Path(str(provider.get("result") or "")).resolve()
        if provider.get("authorized") is not True or not result_path.is_file():
            report.update({"status": "action_required",
                           "reason": "authorized localization provider result file is missing"})
        else:
            result = read_json(result_path)
            report["provider_result"] = {
                "path": str(result_path), "sha256": sha256_file(result_path),
                "input_contract": result.get("input_contract"),
            }
            if (
                result.get("provider") != provider.get("name")
                or result.get("target_language") != target_language
            ):
                report.update({"status": "failed", "reason": "provider result identity or language mismatch"})
            elif result.get("input_contract") != request_contract:
                report.update({"status": "failed", "reason": "provider result input contract is stale"})
            elif (result.get("voice_clone") or {}).get("status") == "complete" and not voice_clone_authorized:
                report.update({"status": "failed", "reason": "voice cloning was not authorized"})
            elif any((result.get(name) or {}).get("status") == "complete" for name in ("tts", "lipsync")):
                report.update({"status": "failed",
                               "reason": "TTS/lip-sync completion requires separate hash-bound media QA"})
            else:
                configured = result.get("translations") or {}
                missing = []
                for word in words:
                    word_id = str(word.get("id")); row = configured.get(word_id) or {}
                    if not row.get("translated") or not row.get("back_translation"):
                        missing.append(word_id); continue
                    report["translations"].append({
                        "word_id": word_id, "source": word.get("text"),
                        "start": word.get("start"), "end": word.get("end"),
                        "translated": row["translated"],
                        "back_translation": row["back_translation"],
                    })
                report.update({
                    "status": "complete" if not missing else "failed",
                    "reason": None if not missing else
                    "provider result omitted word IDs: " + ", ".join(missing),
                })
    elif provider.get("backend") != "fixture":
        report.update({"status": "action_required",
                       "reason": "configured production provider must return a real hashed output"})
    else:
        configured = provider.get("translations") or {}
        missing = []
        for word in words:
            word_id = str(word.get("id")); row = configured.get(word_id) or {}
            if not row.get("translated") or not row.get("back_translation"):
                missing.append(word_id); continue
            report["translations"].append({
                "word_id": word_id, "source": word.get("text"), "start": word.get("start"),
                "end": word.get("end"), "translated": row["translated"],
                "back_translation": row["back_translation"],
            })
        report.update({
            "status": "complete" if not missing else "failed",
            "reason": None if not missing else "fixture provider omitted word IDs: " + ", ".join(missing),
        })
    report["integrity_sha256"] = _stable_hash(report)
    write_json(output.resolve(), report)
    return report


def validate_localization_manifest(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1 or report.get("status") != "complete":
        errors.append("localization manifest is not complete schema 1")
    row = report.get("transcript") or {}; path = Path(str(row.get("path") or ""))
    if not path.is_file() or row.get("sha256") != (sha256_file(path) if path.is_file() else None):
        errors.append("localization transcript binding is stale")
    expected_request = {
        "transcript_sha256": sha256_file(path) if path.is_file() else None,
        "glossary_sha256": _stable_hash(report.get("glossary") or {}),
    }
    if report.get("request_contract") != expected_request:
        errors.append("localization request contract is stale")
    result = report.get("provider_result")
    if result:
        path = Path(str(result.get("path") or ""))
        if not path.is_file() or result.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append("localization provider-result binding is stale")
    if not report.get("translations"):
        errors.append("localization has no translated word evidence")
    if report.get("tts_or_lipsync_claimed") is not False:
        errors.append("localization cannot claim TTS or lip sync without an output adapter")
    if report.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in report.items() if key != "integrity_sha256"}
    ):
        errors.append("localization integrity hash is stale")
    implementation = report.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("localization implementation binding is stale")
    return errors
