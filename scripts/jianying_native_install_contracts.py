#!/usr/bin/env python3
"""Approval, package, intent and receipt contracts for WP4 test installs."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from jianying_native_common import (
    JianyingNativeDraftError, _canonical_hash, _is_redirected, _lexical_child,
    _tree_has_redirection,
)
from jianying_native_package import validate_draft_package
from safe_generated_output import SafeGeneratedOutputError, safe_generated_directory
from jianying_native_install_fs import (
    _absolute_without_resolution, _exclusive_write_json, _identity, _inventory,
    _lexical_project_child, _locked_directory, _read_stable_json,
)

WP4_TEST_STORE_MARKER_FILENAME = ".codex-jianying-wp4-test-store.json"
WP4_TEST_TARGET_NAME = "Codex-WP4-Isolated-Test-Draft"
_TEST_STORE_MARKER = {
    "schema_version": 1,
    "kind": "jianying_wp4_isolated_test_store",
    "purpose": "wp4_install_boundary_test_only",
    "real_jianying_store": False,
}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WP4_APPROVAL_PATH = (
    _REPOSITORY_ROOT / "references" / "jianying-native-draft-v1" / "wp4-approval.json"
)
_DESIGN_CANDIDATE_PATH = (
    _REPOSITORY_ROOT / "references" / "jianying-native-draft-v1"
    / "design-freeze-candidate.json"
)
_WP4_APPROVAL_TEXT = (
    "批准 jianying-native-draft-v1 WP4：按照已冻结设计实现剪映草稿安装边界。"
    "仅允许创建一个全新且确认不存在的测试草稿，不得读取、修改、合并、覆盖或删除任何现有剪映草稿；"
    "不得启动剪映、导出视频或进入 WP5。完成实现、隔离测试、安全复审、证据刷新、提交并推送 GitHub后，"
    "等待我批准真实短片 canary"
)


def _require_wp4_approval() -> tuple[dict[str, Any], tuple[int, int], str]:
    approval_parent_identity = _identity(_WP4_APPROVAL_PATH.parent)
    approval, approval_identity, approval_sha256 = _read_stable_json(
        _WP4_APPROVAL_PATH, label="WP4 approval receipt",
        parent_identity=approval_parent_identity,
    )
    expected_keys = {
        "schema_version", "kind", "status", "actor", "approved_at",
        "approval_text", "design_candidate", "authorized_scope", "prohibited_scope",
    }
    if not isinstance(approval, Mapping) or set(approval) != expected_keys:
        raise JianyingNativeDraftError("WP4 approval receipt shape is invalid")
    if (
        approval.get("schema_version") != 1
        or approval.get("kind") != "jianying_native_draft_v1_wp4_approval"
        or approval.get("status") != "approved"
        or approval.get("actor") != "HongRun"
        or not isinstance(approval.get("approved_at"), str)
        or not approval["approved_at"]
        or approval.get("approval_text") != _WP4_APPROVAL_TEXT
        or approval.get("authorized_scope")
        != "isolated_test_store_install_boundary_implementation_only"
        or approval.get("prohibited_scope") != [
            "real_jianying_draft_store_installation",
            "existing_draft_read_modify_merge_overwrite_or_delete",
            "launch_jianying",
            "export_video",
            "wp5_real_short_canary",
            "long_or_full_video_render",
        ]
    ):
        raise JianyingNativeDraftError("WP4 approval receipt does not authorize this boundary")
    candidate = approval.get("design_candidate")
    if not isinstance(candidate, Mapping) or set(candidate) != {"path", "sha256"}:
        raise JianyingNativeDraftError("WP4 approval design binding is invalid")
    if candidate.get("path") != "design-freeze-candidate.json":
        raise JianyingNativeDraftError("WP4 approval design path is invalid")
    _candidate, _candidate_identity, candidate_sha256 = _read_stable_json(
        _DESIGN_CANDIDATE_PATH,
        label="WP4 design candidate",
        parent_identity=approval_parent_identity,
    )
    if candidate.get("sha256") != candidate_sha256:
        raise JianyingNativeDraftError("WP4 approval design binding is stale")
    return dict(approval), approval_identity, approval_sha256


def _assert_safe_test_store(
    root: Path,
) -> tuple[Path, tuple[int, int], str, tuple[int, int]]:
    root = _absolute_without_resolution(root)
    for candidate in (root, *root.parents):
        if _is_redirected(candidate):
            raise JianyingNativeDraftError("WP4 isolated test-store root is redirected")
    if not root.is_dir():
        raise JianyingNativeDraftError("WP4 isolated test-store root must already exist")
    marker = root / WP4_TEST_STORE_MARKER_FILENAME
    if _is_redirected(marker) or not marker.is_file():
        raise JianyingNativeDraftError("WP4 isolated test-store marker is missing or redirected")
    root_identity = _identity(root)
    marker_payload, marker_identity, marker_sha256 = _read_stable_json(
        marker, label="WP4 isolated test-store marker", parent_identity=root_identity,
    )
    if marker_payload != _TEST_STORE_MARKER:
        raise JianyingNativeDraftError("WP4 isolated test-store marker is invalid")
    return root, root_identity, marker_sha256, marker_identity


def _validate_synthetic_adapter(
    manifest: Mapping[str, Any], package_root: Path,
    package_root_identity: tuple[int, int],
) -> None:
    adapter_ref = manifest.get("adapter_report")
    if (
        not isinstance(adapter_ref, Mapping)
        or set(adapter_ref) != {"path", "sha256"}
        or not isinstance(adapter_ref.get("path"), str)
        or Path(adapter_ref["path"]).is_absolute()
        or ".." in Path(adapter_ref["path"]).parts
    ):
        raise JianyingNativeDraftError("WP4 adapter report reference is invalid")
    adapter_path = _lexical_child(
        package_root / adapter_ref["path"], package_root, label="WP4 adapter report"
    )
    adapter, _adapter_identity, adapter_sha256 = _read_stable_json(
        adapter_path, label="WP4 adapter report",
        parent_identity=package_root_identity,
    )
    if adapter_ref.get("sha256") != adapter_sha256:
        raise JianyingNativeDraftError("WP4 adapter report reference is stale")
    if not isinstance(adapter, Mapping):
        raise JianyingNativeDraftError("WP4 adapter report is invalid")
    if (
        adapter.get("synthetic_fixture_only") is not True
        or adapter.get("third_party_code_executed") is not False
        or adapter.get("editor_store_read") is not False
        or adapter.get("editor_store_written") is not False
        or adapter.get("real_jianying_compatibility_claimed") is not False
    ):
        raise JianyingNativeDraftError("WP4 permits only the isolated synthetic test package")


def _native_inventory_contract(
    manifest: Mapping[str, Any], package_root: Path,
) -> tuple[Path, list[dict[str, str]]]:
    native_root = package_root / "native-draft"
    if not native_root.is_dir() or _tree_has_redirection(native_root):
        raise JianyingNativeDraftError("WP4 source native draft is missing or redirected")
    expected_native_inventory: list[dict[str, str]] = []
    inventory = manifest.get("inventory")
    if not isinstance(inventory, list):
        raise JianyingNativeDraftError("WP4 source package inventory is invalid")
    for row in inventory:
        if not isinstance(row, Mapping):
            raise JianyingNativeDraftError("WP4 source package inventory row is invalid")
        relative = row.get("path")
        digest = row.get("sha256")
        if isinstance(relative, str) and relative.startswith("native-draft/"):
            expected_native_inventory.append({
                "path": relative.removeprefix("native-draft/"),
                "sha256": digest,
            })
    if not expected_native_inventory:
        raise JianyingNativeDraftError("WP4 source package has no native draft inventory")
    return native_root, expected_native_inventory


def _package_preflight(
    package_manifest_path: Path, *, authorized_project_root: Path,
) -> dict[str, Any]:
    project_root = _absolute_without_resolution(authorized_project_root)
    manifest_path = _lexical_project_child(
        package_manifest_path, project_root, label="WP4 package manifest"
    )
    package_root = manifest_path.parent
    package_root_identity = _identity(package_root)
    manifest, manifest_identity, manifest_sha256 = _read_stable_json(
        manifest_path, label="WP4 source package manifest",
        parent_identity=package_root_identity,
    )
    with _locked_directory(package_root, package_root_identity):
        if errors := validate_draft_package(manifest_path, authorized_root=project_root):
            raise JianyingNativeDraftError(
                "WP4 source package is invalid:\n- " + "\n- ".join(errors)
            )
    _verified, verified_identity, verified_sha256 = _read_stable_json(
        manifest_path, label="WP4 source package manifest",
        parent_identity=package_root_identity,
    )
    if verified_identity != manifest_identity or verified_sha256 != manifest_sha256:
        raise JianyingNativeDraftError("WP4 source package changed after validation")
    if not isinstance(manifest, Mapping):
        raise JianyingNativeDraftError("WP4 source package manifest is invalid")
    _validate_synthetic_adapter(manifest, package_root, package_root_identity)
    native_root, expected_native_inventory = _native_inventory_contract(
        manifest, package_root
    )
    return {
        "manifest_path": manifest_path,
        "manifest": dict(manifest),
        "manifest_identity": manifest_identity,
        "manifest_sha256": manifest_sha256,
        "package_root_identity": package_root_identity,
        "source_native": native_root,
        "source_native_identity": _identity(native_root),
        "expected_native_inventory": expected_native_inventory,
    }


def _prepare_install_paths(
    project_root: Path, test_store_root: Path, receipt_path: Path,
) -> dict[str, Any]:
    store_candidate = _lexical_project_child(
        test_store_root, project_root, label="WP4 isolated test-store root"
    )
    if store_candidate == project_root:
        raise JianyingNativeDraftError("WP4 isolated test-store must be below project root")
    store_root, store_identity, marker_sha256, marker_identity = (
        _assert_safe_test_store(store_candidate)
    )
    target = store_root / WP4_TEST_TARGET_NAME
    if os.path.lexists(target):
        raise JianyingNativeDraftError("WP4 test draft target already exists")
    receipt_path = _lexical_project_child(
        receipt_path, project_root, label="WP4 install receipt"
    )
    if receipt_path == store_root or receipt_path.is_relative_to(store_root):
        raise JianyingNativeDraftError("WP4 install receipt cannot be inside the test store")
    if os.path.lexists(receipt_path):
        raise JianyingNativeDraftError("WP4 install receipt already exists")
    try:
        receipt_parent = safe_generated_directory(
            project_root, receipt_path.parent.relative_to(project_root)
        )
    except (SafeGeneratedOutputError, ValueError) as error:
        raise JianyingNativeDraftError("WP4 install receipt path is unsafe") from error
    receipt_path = receipt_parent / receipt_path.name
    pending_path = receipt_parent / (
        f".{receipt_path.name}.pending-{uuid.uuid4().hex}.json"
    )
    return {
        "store_root": store_root, "store_identity": store_identity,
        "store_parent_identity": _identity(store_root.parent),
        "marker_sha256": marker_sha256, "marker_identity": marker_identity,
        "target": target, "receipt_path": receipt_path,
        "receipt_parent_identity": _identity(receipt_parent),
        "pending_path": pending_path,
    }


def _install_intent(
    package: Mapping[str, Any], approval_sha256: str, marker_sha256: str,
) -> dict[str, Any]:
    intent = {
        "schema_version": 1,
        "kind": "jianying_native_draft_v1_install_intent",
        "status": "prepared_test_only",
        "target_name": WP4_TEST_TARGET_NAME,
        "source_package_sha256": package["manifest_sha256"],
        "approval_sha256": approval_sha256,
        "test_store_marker_sha256": marker_sha256,
        "safety": {
            "fixed_new_target_only": True,
            "existing_drafts_enumerated": False,
            "existing_drafts_read": False,
            "existing_drafts_modified": False,
            "editor_launched": False,
            "wp5_entered": False,
        },
    }
    intent["integrity_sha256"] = _canonical_hash(intent, omit="integrity_sha256")
    return intent


def _prepare_install(
    *, package_manifest_path: Path, authorized_project_root: Path,
    test_store_root: Path, receipt_path: Path,
) -> dict[str, Any]:
    approval, approval_identity, approval_sha256 = _require_wp4_approval()
    project_root = _absolute_without_resolution(authorized_project_root)
    package = _package_preflight(
        package_manifest_path, authorized_project_root=project_root
    )
    paths = _prepare_install_paths(project_root, test_store_root, receipt_path)
    intent = _install_intent(package, approval_sha256, paths["marker_sha256"])
    _exclusive_write_json(
        paths["pending_path"], intent,
        parent_identity=paths["receipt_parent_identity"],
    )
    return {**paths,
        "approval": approval,
        "approval_identity": approval_identity,
        "approval_sha256": approval_sha256,
        "approval_parent_identity": _identity(_WP4_APPROVAL_PATH.parent),
        "project_root": project_root,
        "package": package,
        "pending_identity": _identity(paths["pending_path"]),
    }


def _assert_install_authorities_current(
    context: Mapping[str, Any], *, staging: Path,
    staging_identity: tuple[int, int], installed_inventory: list[dict[str, Any]],
) -> None:
    package = context["package"]
    manifest_path = package["manifest_path"]
    _manifest, manifest_identity, manifest_sha256 = _read_stable_json(
        manifest_path, label="WP4 source package manifest",
        parent_identity=package["package_root_identity"],
    )
    if (
        manifest_identity != package["manifest_identity"]
        or manifest_sha256 != package["manifest_sha256"]
    ):
        raise JianyingNativeDraftError("WP4 source package changed during install")
    if _identity(context["store_root"]) != context["store_identity"]:
        raise JianyingNativeDraftError("WP4 isolated test-store identity changed")
    marker_path = context["store_root"] / WP4_TEST_STORE_MARKER_FILENAME
    _marker, marker_identity, marker_sha256 = _read_stable_json(
        marker_path, label="WP4 isolated test-store marker",
    )
    _approval, approval_identity, approval_sha256 = _read_stable_json(
        _WP4_APPROVAL_PATH, label="WP4 approval receipt",
        parent_identity=context["approval_parent_identity"],
    )
    if (
        marker_identity != context["marker_identity"]
        or marker_sha256 != context["marker_sha256"]
        or approval_identity != context["approval_identity"]
        or approval_sha256 != context["approval_sha256"]
    ):
        raise JianyingNativeDraftError("WP4 approval or test-store marker changed")
    if os.path.lexists(context["target"]):
        raise JianyingNativeDraftError("WP4 test draft target already exists")
    if os.name != "nt":
        raise JianyingNativeDraftError("WP4 test draft promotion is Windows-only")
    if (
        _identity(staging) != staging_identity
        or _inventory(staging, expected_identity=staging_identity)
        != installed_inventory
    ):
        raise JianyingNativeDraftError("WP4 staging draft changed before promotion")


def _install_receipt_safety() -> dict[str, bool]:
    return {
        "target_absent_before_install": True,
        "target_name_caller_controlled": False,
        "existing_drafts_enumerated": False,
        "existing_drafts_read": False,
        "existing_drafts_modified": False,
        "network_used": False,
        "secret_required": False,
        "editor_launched": False,
        "video_exported": False,
        "wp5_entered": False,
    }


def _build_install_receipt(
    context: Mapping[str, Any], state: Mapping[str, Any],
) -> dict[str, Any]:
    package = context["package"]
    manifest_path = package["manifest_path"]
    target_identity = state["target_identity"]
    receipt = {
        "schema_version": 1,
        "kind": "jianying_native_draft_v1_install_receipt",
        "status": "installed_test_only",
        "mode": "isolated_synthetic_test",
        "target_name": WP4_TEST_TARGET_NAME,
        "source_package": {
            "path": manifest_path.relative_to(context["project_root"]).as_posix(),
            "sha256": package["manifest_sha256"],
            "build_id": package["manifest"]["build_id"],
        },
        "approval": {
            "path": "references/jianying-native-draft-v1/wp4-approval.json",
            "sha256": context["approval_sha256"],
            "actor": context["approval"]["actor"],
        },
        "test_store": {
            "marker": WP4_TEST_STORE_MARKER_FILENAME,
            "marker_sha256": context["marker_sha256"],
            "marker_device": context["marker_identity"][0],
            "marker_file_id": context["marker_identity"][1],
            "parent_device": context["store_identity"][0],
            "parent_file_id": context["store_identity"][1],
        },
        "created_inventory": state["inventory"],
        "created_tree": {"device": target_identity[0], "file_id": target_identity[1]},
        "safety": _install_receipt_safety(),
        "rollback": {
            "automated_only_if_inventory_unchanged": True,
            "executed": False,
        },
    }
    receipt["integrity_sha256"] = _canonical_hash(receipt, omit="integrity_sha256")
    return receipt


def _validate_receipt_shape(receipt: Any) -> list[str]:
    if not isinstance(receipt, Mapping):
        return ["WP4 install receipt must be an object"]
    expected = {
        "schema_version", "kind", "status", "mode", "target_name",
        "source_package", "approval", "test_store", "created_inventory",
        "created_tree", "safety", "rollback", "integrity_sha256",
    }
    errors: list[str] = []
    if set(receipt) != expected:
        errors.append("WP4 install receipt shape is invalid")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "jianying_native_draft_v1_install_receipt"
        or receipt.get("status") != "installed_test_only"
        or receipt.get("mode") != "isolated_synthetic_test"
        or receipt.get("target_name") != WP4_TEST_TARGET_NAME
    ):
        errors.append("WP4 install receipt identity is invalid")
    try:
        expected_integrity = _canonical_hash(receipt, omit="integrity_sha256")
    except JianyingNativeDraftError as error:
        errors.append(str(error))
    else:
        if receipt.get("integrity_sha256") != expected_integrity:
            errors.append("WP4 install receipt integrity is stale")
    if receipt.get("safety") != _install_receipt_safety():
        errors.append("WP4 install receipt safety boundary is invalid")
    if receipt.get("rollback") != {
        "automated_only_if_inventory_unchanged": True, "executed": False,
    }:
        errors.append("WP4 install receipt rollback boundary is invalid")
    errors.extend(_validate_created_tree_inventory(receipt))
    return errors


def _validate_created_tree_inventory(receipt: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    created_tree = receipt.get("created_tree")
    if (
        not isinstance(created_tree, Mapping)
        or set(created_tree) != {"device", "file_id"}
        or any(isinstance(created_tree.get(key), bool) for key in ("device", "file_id"))
        or any(not isinstance(created_tree.get(key), int) for key in ("device", "file_id"))
    ):
        errors.append("WP4 install receipt created-tree identity is invalid")
    inventory = receipt.get("created_inventory")
    if not isinstance(inventory, list) or not inventory:
        errors.append("WP4 install receipt created inventory is invalid")
    elif any(
        not isinstance(row, Mapping)
        or set(row) != {"path", "sha256", "size_bytes"}
        or not isinstance(row.get("path"), str)
        or not row["path"]
        or Path(row["path"]).is_absolute()
        or ".." in Path(row["path"]).parts
        or not isinstance(row.get("sha256"), str)
        or len(row["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in row["sha256"])
        or isinstance(row.get("size_bytes"), bool)
        or not isinstance(row.get("size_bytes"), int)
        or row["size_bytes"] < 0
        for row in inventory
    ):
        errors.append("WP4 install receipt created inventory row is invalid")
    return errors


def _validation_authorities(
    project_root: Path, test_store_root: Path,
) -> tuple[dict[str, Any], str, Path, tuple[int, int], str, tuple[int, int]]:
    approval, _approval_identity, approval_sha256 = _require_wp4_approval()
    store_candidate = _lexical_project_child(
        test_store_root, project_root, label="WP4 isolated test-store root"
    )
    if store_candidate == project_root:
        raise JianyingNativeDraftError("WP4 isolated test-store must be below project root")
    store_root, store_identity, marker_sha256, marker_identity = (
        _assert_safe_test_store(store_candidate)
    )
    return (
        approval, approval_sha256, store_root, store_identity,
        marker_sha256, marker_identity,
    )


def _validate_authority_bindings(
    receipt: Mapping[str, Any], approval: Mapping[str, Any],
    approval_sha256: str, store_identity: tuple[int, int],
    marker_sha256: str, marker_identity: tuple[int, int],
) -> list[str]:
    errors: list[str] = []
    if receipt.get("approval") != {
        "path": "references/jianying-native-draft-v1/wp4-approval.json",
        "sha256": approval_sha256, "actor": approval["actor"],
    }:
        errors.append("WP4 install receipt approval binding is stale")
    if receipt.get("test_store") != {
        "marker": WP4_TEST_STORE_MARKER_FILENAME, "marker_sha256": marker_sha256,
        "marker_device": marker_identity[0], "marker_file_id": marker_identity[1],
        "parent_device": store_identity[0], "parent_file_id": store_identity[1],
    }:
        errors.append("WP4 install receipt test-store binding is stale")
    return errors


def _validate_source_binding(
    receipt: Mapping[str, Any], project_root: Path,
) -> list[str]:
    errors: list[str] = []
    source = receipt.get("source_package")
    if not isinstance(source, Mapping) or set(source) != {"path", "sha256", "build_id"}:
        return ["WP4 install receipt source binding is invalid"]
    try:
        source_path = _lexical_project_child(
            project_root / str(source["path"]), project_root,
            label="WP4 source package",
        )
    except (OSError, JianyingNativeDraftError) as error:
        return [str(error)]
    try:
        parent_identity = _identity(source_path.parent)
        manifest, _source_identity, source_sha256 = _read_stable_json(
            source_path, label="WP4 source package", parent_identity=parent_identity,
        )
    except (OSError, ValueError, json.JSONDecodeError, JianyingNativeDraftError):
        return ["WP4 install receipt source package is unreadable"]
    if source.get("sha256") != source_sha256:
        return ["WP4 install receipt source binding is stale"]
    if not isinstance(manifest, Mapping):
        errors.append("WP4 install receipt source package is invalid")
    elif source.get("build_id") != manifest.get("build_id"):
        errors.append("WP4 install receipt source build is stale")
    with _locked_directory(source_path.parent, parent_identity):
        if validate_draft_package(source_path, authorized_root=project_root):
            errors.append("WP4 install receipt source package drifted")
    return errors


def _validate_target_binding(
    receipt: Mapping[str, Any], store_root: Path,
) -> list[str]:
    inventory = receipt.get("created_inventory")
    target = store_root / WP4_TEST_TARGET_NAME
    if not target.is_dir():
        return ["WP4 installed test draft is missing"]
    if not isinstance(inventory, list):
        return []
    try:
        created_tree = receipt.get("created_tree")
        expected_identity = (
            created_tree.get("device"), created_tree.get("file_id")
        ) if isinstance(created_tree, Mapping) else (-1, -1)
        errors = []
        if _identity(target) != expected_identity:
            errors.append("WP4 installed test draft identity drifted")
        if _inventory(target, expected_identity=expected_identity) != inventory:
            errors.append("WP4 installed test draft inventory drifted")
        return errors
    except (OSError, JianyingNativeDraftError) as error:
        return [str(error)]


def validate_install_receipt(
    receipt_path: Path, *, authorized_project_root: Path, test_store_root: Path,
) -> list[str]:
    errors: list[str] = []
    project_root = _absolute_without_resolution(authorized_project_root)
    try:
        receipt_path = _lexical_project_child(
            receipt_path, project_root, label="WP4 install receipt"
        )
        receipt, _receipt_identity, _receipt_sha256 = _read_stable_json(
            receipt_path, label="WP4 install receipt",
            parent_identity=_identity(receipt_path.parent),
        )
    except (OSError, ValueError, json.JSONDecodeError, JianyingNativeDraftError) as error:
        return [str(error) or "WP4 install receipt is unreadable"]
    errors.extend(_validate_receipt_shape(receipt))
    if not isinstance(receipt, Mapping):
        return errors
    try:
        approval, approval_sha256, store_root, store_identity, marker_sha256, marker_identity = (
            _validation_authorities(project_root, test_store_root)
        )
    except (OSError, JianyingNativeDraftError) as error:
        errors.append(str(error))
        return errors
    errors.extend(_validate_authority_bindings(
        receipt, approval, approval_sha256,
        store_identity, marker_sha256, marker_identity,
    ))
    errors.extend(_validate_source_binding(receipt, project_root))
    errors.extend(_validate_target_binding(receipt, store_root))
    return errors


def _verified_install_receipt_for_rollback(
    install_receipt_path: Path, project_root: Path, test_store_root: Path,
) -> tuple[Mapping[str, Any], tuple[int, int], str, tuple[int, int]]:
    install_receipt_path = _lexical_project_child(
        install_receipt_path, project_root, label="WP4 install receipt"
    )
    install_receipt_parent_identity = _identity(install_receipt_path.parent)
    receipt, receipt_identity, receipt_sha256 = _read_stable_json(
        install_receipt_path, label="WP4 install receipt",
        parent_identity=install_receipt_parent_identity,
    )
    errors = validate_install_receipt(
        install_receipt_path,
        authorized_project_root=project_root,
        test_store_root=test_store_root,
    )
    if errors:
        raise JianyingNativeDraftError("WP4 rollback blocked by drift:\n- " + "\n- ".join(errors))
    verified_receipt, verified_identity, verified_sha256 = _read_stable_json(
        install_receipt_path, label="WP4 install receipt",
        parent_identity=install_receipt_parent_identity,
    )
    if (
        verified_identity != receipt_identity
        or verified_sha256 != receipt_sha256
        or verified_receipt != receipt
        or not isinstance(receipt, Mapping)
    ):
        raise JianyingNativeDraftError("WP4 install receipt changed after validation")
    return receipt, receipt_identity, receipt_sha256, install_receipt_parent_identity


def _prepare_rollback_receipt_path(
    path: Path, project_root: Path, store_root: Path,
) -> tuple[Path, tuple[int, int]]:
    path = _lexical_project_child(path, project_root, label="WP4 rollback receipt")
    if path == store_root or path.is_relative_to(store_root):
        raise JianyingNativeDraftError("WP4 rollback receipt cannot be inside the test store")
    if os.path.lexists(path):
        raise JianyingNativeDraftError("WP4 rollback receipt already exists")
    try:
        parent = safe_generated_directory(
            project_root, path.parent.relative_to(project_root)
        )
    except (SafeGeneratedOutputError, ValueError) as error:
        raise JianyingNativeDraftError("WP4 rollback receipt path is unsafe") from error
    return parent / path.name, _identity(parent)


def _prepare_rollback_context(
    install_receipt_path: Path, authorized_project_root: Path,
    test_store_root: Path, rollback_receipt_path: Path,
) -> dict[str, Any]:
    project_root = _absolute_without_resolution(authorized_project_root)
    receipt, receipt_identity, receipt_sha256, install_parent_identity = (
        _verified_install_receipt_for_rollback(
            install_receipt_path, project_root, test_store_root
        )
    )
    install_receipt_path = _lexical_project_child(
        install_receipt_path, project_root, label="WP4 install receipt"
    )
    _approval, _approval_hash, store_root, store_identity, _marker_hash, _marker_id = (
        _validation_authorities(project_root, test_store_root)
    )
    store_parent_identity = _identity(store_root.parent)
    rollback_receipt_path, rollback_parent_identity = _prepare_rollback_receipt_path(
        rollback_receipt_path, project_root, store_root
    )
    return {
        "project_root": project_root, "install_receipt_path": install_receipt_path,
        "install_receipt_parent_identity": install_parent_identity,
        "receipt": receipt, "receipt_identity": receipt_identity,
        "receipt_sha256": receipt_sha256, "store_root": store_root,
        "store_identity": store_identity,
        "store_parent_identity": store_parent_identity,
        "rollback_receipt_path": rollback_receipt_path,
        "rollback_parent_identity": rollback_parent_identity,
        "target": store_root / WP4_TEST_TARGET_NAME,
    }


def _rollback_intent(context: Mapping[str, Any]) -> dict[str, Any]:
    receipt = context["receipt"]
    created_tree = receipt["created_tree"]
    intent = {
        "schema_version": 1,
        "kind": "jianying_native_draft_v1_rollback_intent",
        "status": "prepared_test_only",
        "target_name": WP4_TEST_TARGET_NAME,
        "install_receipt_sha256": context["receipt_sha256"],
        "verified_tree": dict(created_tree),
        "verified_inventory": receipt["created_inventory"],
        "safety": {
            "exact_generated_target_only": True,
            "existing_drafts_enumerated": False,
            "existing_drafts_read": False,
            "existing_drafts_modified": False,
            "editor_launched": False,
        },
    }
    intent["integrity_sha256"] = _canonical_hash(intent, omit="integrity_sha256")
    return intent


def _rollback_receipt(context: Mapping[str, Any]) -> dict[str, Any]:
    receipt = context["receipt"]
    rollback = {
        "schema_version": 1,
        "kind": "jianying_native_draft_v1_rollback_receipt",
        "status": "rolled_back_test_only",
        "target_name": WP4_TEST_TARGET_NAME,
        "install_receipt_sha256": context["receipt_sha256"],
        "removed_inventory": receipt["created_inventory"],
        "safety": {
            "exact_generated_target_only": True,
            "existing_drafts_enumerated": False,
            "existing_drafts_read": False,
            "existing_drafts_modified": False,
            "editor_launched": False,
        },
    }
    rollback["integrity_sha256"] = _canonical_hash(rollback, omit="integrity_sha256")
    return rollback
