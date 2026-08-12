#!/usr/bin/env python3
"""Govern optional perception/generative adapters without granting creative approval."""
from __future__ import annotations

from typing import Any


REQUIRED_CONTRACTS = (
    "provider", "rights_approved", "privacy_approved", "budget_approved",
    "provenance_enabled", "human_review_required",
)
SUPPORTED_KINDS = {
    "scene_detection", "ocr", "face_tracking", "hand_tracking",
    "ip_image", "cover_generation", "music_generation",
}


def authorize_optional_adapter(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("enabled") is not True:
        return {
            "schema_version": 1, "status": "disabled",
            "kind": str(config.get("kind") or "unknown"),
            "default_off": True, "aesthetic_approval_granted": False,
        }
    kind = str(config.get("kind") or "unknown")
    if kind not in SUPPORTED_KINDS:
        return {
            "schema_version": 1, "status": "unavailable", "kind": kind,
            "reason": "unsupported optional adapter kind", "default_off": True,
            "aesthetic_approval_granted": False, "publication_authorized": False,
        }
    missing = []
    for field in REQUIRED_CONTRACTS:
        value = config.get(field)
        valid = (
            isinstance(value, str) and bool(value.strip())
            if field == "provider" else value is True
        )
        if not valid:
            missing.append(field)
    if config.get("cloud_upload") is True and config.get("privacy_approved") is not True:
        if "privacy_approved" not in missing:
            missing.append("privacy_approved")
    status = "action_required" if missing else "authorized_to_run"
    return {
        "schema_version": 1,
        "status": status,
        "kind": kind,
        "provider": config.get("provider"),
        "cloud_upload": config.get("cloud_upload") is True,
        "missing_contracts": missing,
        "provenance_required": True,
        "human_review_required": True,
        "review_dimensions": [
            "anatomy", "visible_text", "likeness", "topic_fit", "rights", "privacy",
        ],
        "aesthetic_approval_granted": False,
        "publication_authorized": False,
        "execution_status": "not_run",
        "review_status": "pending",
    }
