#!/usr/bin/env python3
"""WP4-only isolated Jianying draft install and exact rollback boundary."""
from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from jianying_native_common import JianyingNativeDraftError
from jianying_native_install_contracts import (
    WP4_TEST_STORE_MARKER_FILENAME, WP4_TEST_TARGET_NAME,
    _assert_install_authorities_current, _build_install_receipt,
    _prepare_install, _prepare_rollback_context, _rollback_intent,
    _rollback_receipt, validate_install_receipt,
)
from jianying_native_install_fs import (
    _copy_tree, _exclusive_write_json, _identity, _inventory,
    _locked_directory, _read_stable_json, _safe_remove_exact_tree,
    _safe_remove_partial_generated_tree, _safe_unlink_owned,
)


def _promoted_target_is_exact(
    target: Path, state: Mapping[str, Any], inventory: list[dict[str, Any]],
) -> bool:
    return (
            _identity(target) == state["staging_identity"]
            and _inventory(target, expected_identity=state["staging_identity"])
            == inventory
    )


def _quarantine_untrusted_promotion(store_root: Path, target: Path) -> None:
    quarantine = store_root / f".{WP4_TEST_TARGET_NAME}.untrusted-{uuid.uuid4().hex}"
    if os.path.lexists(quarantine):
        raise JianyingNativeDraftError(
            "WP4 post-promotion identity drift requires manual isolation"
        )
    os.rename(target, quarantine)


def _materialize_install_target(
    context: Mapping[str, Any], state: dict[str, Any],
) -> None:
    store_root = context["store_root"]
    target = context["target"]
    package = context["package"]
    staging = store_root / f".{WP4_TEST_TARGET_NAME}.staging-{uuid.uuid4().hex}"
    state["staging"] = staging
    with _locked_directory(
        store_root.parent, context["store_parent_identity"]
    ):
        if _identity(store_root) != context["store_identity"]:
            raise JianyingNativeDraftError("WP4 isolated test-store identity changed")
        os.mkdir(staging)
        state["staging_identity"] = _identity(staging)
        _copy_tree(
            package["source_native"], staging,
            source_identity=package["source_native_identity"],
            staging_identity=state["staging_identity"],
            expected_inventory=package["expected_native_inventory"],
        )
        inventory = _inventory(staging, expected_identity=state["staging_identity"])
        state["inventory"] = inventory
        projected = [
            {"path": row["path"], "sha256": row["sha256"]} for row in inventory
        ]
        if projected != package["expected_native_inventory"]:
            raise JianyingNativeDraftError("WP4 source native draft changed during copy")
        _assert_install_authorities_current(
            context,
            staging=staging,
            staging_identity=state["staging_identity"],
            installed_inventory=inventory,
        )
        os.rename(staging, target)
        state["installed"] = True
        if _promoted_target_is_exact(target, state, inventory):
            state["target_identity"] = _identity(target)
            return
        _quarantine_untrusted_promotion(store_root, target)
        state["installed"] = False
        raise JianyingNativeDraftError(
            "WP4 post-promotion identity drift was quarantined for manual review"
        )


def _cleanup_install_failure(
    context: Mapping[str, Any], state: Mapping[str, Any],
) -> None:
    identity = state.get("staging_identity")
    inventory = state.get("inventory")
    if state.get("installed") and identity is not None and inventory:
        _safe_remove_exact_tree(
            context["target"],
            store_root=context["store_root"],
            store_identity=context["store_identity"],
            store_parent_identity=context["store_parent_identity"],
            tree_identity=identity,
            expected_inventory=inventory,
        )
    elif identity is not None:
        _safe_remove_partial_generated_tree(
            state["staging"],
            store_root=context["store_root"],
            store_identity=context["store_identity"],
            store_parent_identity=context["store_parent_identity"],
            tree_identity=identity,
        )


def install_isolated_test_draft(
    *, package_manifest_path: Path, authorized_project_root: Path,
    test_store_root: Path, receipt_path: Path,
) -> dict[str, Any]:
    """Install one fixed synthetic test draft; real Jianying stores are rejected."""
    context = _prepare_install(
        package_manifest_path=package_manifest_path,
        authorized_project_root=authorized_project_root,
        test_store_root=test_store_root,
        receipt_path=receipt_path,
    )
    state: dict[str, Any] = {"installed": False, "inventory": []}
    try:
        _materialize_install_target(context, state)
        receipt = _build_install_receipt(context, state)
        _exclusive_write_json(
            context["receipt_path"], receipt,
            parent_identity=context["receipt_parent_identity"],
        )
        _safe_unlink_owned(
            context["pending_path"], context["pending_identity"],
            parent_identity=context["receipt_parent_identity"],
        )
        return receipt
    except Exception:
        _cleanup_install_failure(context, state)
        raise


def rollback_isolated_test_draft(
    *, install_receipt_path: Path, authorized_project_root: Path,
    test_store_root: Path, rollback_receipt_path: Path,
) -> dict[str, Any]:
    """Delete only the unchanged WP4-generated fixed test target."""
    context = _prepare_rollback_context(
        install_receipt_path, authorized_project_root,
        test_store_root, rollback_receipt_path,
    )
    receipt = context["receipt"]
    pending_path = context["rollback_receipt_path"].parent / (
        f".{context['rollback_receipt_path'].name}.pending-{uuid.uuid4().hex}.json"
    )
    intent = _rollback_intent(context)
    _exclusive_write_json(
        pending_path, intent, parent_identity=context["rollback_parent_identity"]
    )
    pending_identity = _identity(pending_path)
    current_receipt, current_identity, current_sha256 = _read_stable_json(
        context["install_receipt_path"], label="WP4 install receipt",
        parent_identity=context["install_receipt_parent_identity"],
    )
    if (
        current_identity != context["receipt_identity"]
        or current_sha256 != context["receipt_sha256"]
        or current_receipt != receipt
    ):
        raise JianyingNativeDraftError("WP4 install receipt changed before rollback")
    if not _safe_remove_exact_tree(
        context["target"],
        store_root=context["store_root"],
        store_identity=context["store_identity"],
        store_parent_identity=context["store_parent_identity"],
        tree_identity=(receipt["created_tree"]["device"], receipt["created_tree"]["file_id"]),
        expected_inventory=receipt["created_inventory"],
    ):
        raise JianyingNativeDraftError("WP4 rollback blocked by target identity or inventory drift")
    rollback = _rollback_receipt(context)
    _exclusive_write_json(
        context["rollback_receipt_path"], rollback,
        parent_identity=context["rollback_parent_identity"],
    )
    _safe_unlink_owned(
        pending_path, pending_identity,
        parent_identity=context["rollback_parent_identity"],
    )
    return rollback


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="WP4 isolated synthetic Jianying test-draft boundary only"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install-test")
    install.add_argument("--package-manifest", type=Path, required=True)
    install.add_argument("--project-root", type=Path, required=True)
    install.add_argument("--test-store-root", type=Path, required=True)
    install.add_argument("--receipt", type=Path, required=True)
    rollback = subparsers.add_parser("rollback-test")
    rollback.add_argument("--install-receipt", type=Path, required=True)
    rollback.add_argument("--project-root", type=Path, required=True)
    rollback.add_argument("--test-store-root", type=Path, required=True)
    rollback.add_argument("--rollback-receipt", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "install-test":
        result = install_isolated_test_draft(
            package_manifest_path=args.package_manifest,
            authorized_project_root=args.project_root,
            test_store_root=args.test_store_root,
            receipt_path=args.receipt,
        )
    else:
        result = rollback_isolated_test_draft(
            install_receipt_path=args.install_receipt,
            authorized_project_root=args.project_root,
            test_store_root=args.test_store_root,
            rollback_receipt_path=args.rollback_receipt,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
