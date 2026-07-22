#!/usr/bin/env python3
"""Optional media-use/Registry/Catalog adapter for evidence-backed asset requests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from director_adapters import AdapterRunner
from director_contracts import exclusive_file_lock, read_json, sha256_file, write_json


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_catalog(payload: dict[str, Any], requests: list[dict[str, Any]], root: Path) -> list[str]:
    errors: list[str] = []
    decisions = payload.get("decisions") or []
    expected = {row["event_id"] for row in requests}
    observed = {str(row.get("event_id")) for row in decisions}
    if not decisions or expected != observed:
        errors.append("catalog decisions must cover every semantic asset request exactly once")
    if len(observed) != len(decisions):
        errors.append("catalog decisions contain duplicate event IDs")
    request_set_sha256 = _stable_hash([
        {key: value for key, value in row.items() if key != "request_sha256"}
        for row in requests
    ])
    if payload.get("request_set_sha256") != request_set_sha256:
        errors.append("catalog output is not bound to the current request set")
    request_by_event = {row["event_id"]: row for row in requests}
    for index, decision in enumerate(decisions):
        request = request_by_event.get(str(decision.get("event_id")))
        if request and (
            decision.get("request_sha256") != request.get("request_sha256")
            or decision.get("query") != request.get("query")
            or decision.get("purpose") != request.get("purpose")
        ):
            errors.append(f"catalog decision {index} is not bound to its semantic request")
        status = decision.get("status")
        if status == "no_match":
            if not str(decision.get("reason") or "").strip():
                errors.append(f"catalog decision {index} no_match requires a reason")
            continue
        if status != "selected" or not isinstance(decision.get("asset"), dict):
            errors.append(f"catalog decision {index} must be selected or evidenced no_match")
            continue
        asset = decision["asset"]
        path = _resolve(root, asset.get("path"))
        if not path.is_file() or asset.get("sha256") != (sha256_file(path) if path.is_file() else None):
            errors.append(f"catalog decision {index} asset is missing or hash-mismatched")
        for field in ("type", "purpose", "provenance", "rights_basis"):
            if not str(asset.get(field) or "").strip():
                errors.append(f"catalog decision {index} asset lacks {field}")
    return errors


def run_media_catalog(
    *, project: dict[str, Any], semantic_brief: dict[str, Any], root: Path,
    runner: AdapterRunner, execute: bool,
) -> dict[str, Any]:
    assets = project.get("assets", {})
    config = assets.get("media_catalog", {}) if isinstance(assets, dict) else {}
    if not isinstance(config, dict):
        config = {}
    enabled = config.get("enabled") is True or assets.get("use_media_catalog") is True
    if not enabled:
        return {"schema_version": 1, "status": "disabled", "reason": "optional_default_off",
                "outputs": []}
    requests: list[dict[str, Any]] = []
    for event in semantic_brief.get("events") or []:
        asset_request = event.get("asset_request")
        if not isinstance(asset_request, dict):
            continue
        if not str(asset_request.get("query") or "").strip() or not str(
            asset_request.get("purpose") or ""
        ).strip():
            continue
        if "event_id" in asset_request:
            return {"schema_version": 1, "status": "failed",
                    "reason": "asset_request must not override canonical event_id",
                    "outputs": []}
        request = {**asset_request, "event_id": str(event.get("id"))}
        request["request_sha256"] = _stable_hash(request)
        requests.append(request)
    if not requests:
        return {"schema_version": 1, "status": "not_applicable",
                "reason": "no evidence-backed semantic asset request", "outputs": []}
    request_set_payload = [
        {key: value for key, value in row.items() if key != "request_sha256"}
        for row in requests
    ]
    request_set_sha256 = _stable_hash(request_set_payload)
    request_manifest = Path(os.path.abspath(
        root / "work" / "director" / "media-catalog-requests"
        / f"{request_set_sha256}.json"
    ))
    manifest = {
        "schema_version": 1,
        "semantic_brief_sha256": _stable_hash(semantic_brief),
        "request_set_sha256": request_set_sha256,
        "requests": requests,
    }
    with exclusive_file_lock(request_manifest):
        if request_manifest.is_file():
            if read_json(request_manifest) != manifest:
                raise RuntimeError("content-addressed media catalog manifest has conflicting bytes")
        else:
            write_json(request_manifest, manifest)
    manifest_sha256 = sha256_file(request_manifest)
    if not execute:
        return {"schema_version": 1, "status": "action_required",
                "reason": "media catalog adapter execution is not enabled", "requests": requests,
                "event_ids": [row["event_id"] for row in requests], "outputs": [],
                "request_manifest": str(request_manifest),
                "request_manifest_sha256": manifest_sha256}
    command = config.get("command") or []
    outputs = [_resolve(root, value) for value in (config.get("outputs") or [])]
    if not isinstance(command, list) or not command or not outputs:
        return {"schema_version": 1, "status": "unavailable",
                "reason": "no media-use/Catalog command and outputs are configured",
                "requests": requests, "event_ids": [row["event_id"] for row in requests],
                "outputs": [], "request_manifest": str(request_manifest),
                "request_manifest_sha256": manifest_sha256}
    if not any("{request_manifest}" in str(value) for value in command):
        return {"schema_version": 1,
                "status": "failed" if config.get("required") is True else "unavailable",
                "reason": "media catalog command must include {request_manifest}",
                "requests": requests, "event_ids": [row["event_id"] for row in requests],
                "outputs": [], "request_manifest": str(request_manifest),
                "request_manifest_sha256": manifest_sha256}
    resolved_command = [
        str(value).replace("{request_manifest}", str(request_manifest)) for value in command
    ]
    result = runner.run(
        name="media_catalog", enabled=True, command=resolved_command,
        inputs=[request_manifest], outputs=outputs,
        blocking=config.get("required") is True, cwd=root,
        settings={"requests": requests, "timeout_seconds": config.get("timeout_seconds", 900)},
    )
    status = result.get("status")
    validation_errors: list[str] = []
    if status in {"complete", "reused"}:
        validation_errors = _validate_catalog(read_json(outputs[0]), requests, root)
        if validation_errors:
            status = "failed" if config.get("required") is True else "unavailable"
    return {"schema_version": 1, "status": status, "requests": requests,
            "event_ids": [row["event_id"] for row in requests],
            "request_manifest": str(request_manifest),
            "request_manifest_sha256": manifest_sha256,
            "outputs": [str(path) for path in outputs], "adapter": result,
            "validation_errors": validation_errors}
