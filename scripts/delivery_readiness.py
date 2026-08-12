#!/usr/bin/env python3
"""Truthful final-delivery readiness checks for configured project assets."""
from __future__ import annotations

from typing import Any


_SATISFIES = {
    "ready": {"ready", "asset_ready"},
    "asset_ready": {"asset_ready"},
    "not_applicable": {"not_applicable", "ready", "asset_ready"},
}


def asset_is_required(project: dict[str, Any], asset_name: str) -> bool:
    """Return the effective delivery requirement without mutating project config."""
    delivery = project.get("delivery", {})
    rule = (delivery.get("required_assets") or {}).get(asset_name) or {}
    if rule.get("applicability") == "required":
        return True
    # A release pack is a publish package and cannot truthfully omit its cover.
    if asset_name == "cover" and delivery.get("release_pack", {}).get("enabled") is True:
        return True
    return False


def validate_required_asset_readiness(
    project: dict[str, Any], stages: dict[str, Any],
) -> list[str]:
    """Reject required delivery assets whose stage is only contract-complete.

    Optional assets never block delivery. A not-applicable asset must carry an
    explicit reason in configuration and a matching stage readiness receipt.
    """
    errors: list[str] = []
    assets = project.get("delivery", {}).get("required_assets", {})
    if not isinstance(assets, dict):
        return ["delivery.required_assets is missing or invalid"]
    for asset_name, rule in assets.items():
        if not isinstance(rule, dict):
            errors.append(f"required asset {asset_name} policy is invalid")
            continue
        applicability = rule.get("applicability")
        if applicability == "optional" and not asset_is_required(project, asset_name):
            continue
        stage_name = str(rule.get("stage") or "")
        stage = stages.get(stage_name) or {}
        status = str(stage.get("status") or "pending")
        declared_readiness = str(stage.get("readiness") or "").strip()
        # Legacy Director state did not persist readiness. Its completed
        # non-asset stages historically meant ready; explicit contract_ready is
        # never upgraded by this compatibility rule.
        actual = declared_readiness or ("ready" if status == "complete" else status)
        required = str(rule.get("required_readiness") or "")
        if applicability == "not_applicable" and not str(rule.get("reason") or "").strip():
            errors.append(f"required asset {asset_name} has no not_applicable reason")
            continue
        if status != "complete" or actual not in _SATISFIES.get(required, set()):
            errors.append(
                f"required asset {asset_name} stage {stage_name} has readiness "
                f"{actual}; requires {required}"
            )
    return errors
