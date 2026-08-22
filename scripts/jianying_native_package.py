#!/usr/bin/env python3
"""Isolated synthetic materialization, package integrity, and privacy validation."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file
from editable_delivery import validate_editable_delivery
from nle_handoff_v2 import validate_nle_handoff_package
from safe_generated_output import (
    SafeGeneratedOutputError, atomic_write_text, safe_generated_directory,
    safe_generated_target,
)
from jianying_native_common import (
    ADAPTER_ID, ADAPTER_VERSION, ADAPTER_WHEEL_SHA256, ASSET_MODES, PROFILES,
    JianyingNativeDraftError, _DRAFT_IDENTIFIER, _assert_generated_tree_safe,
    _canonical_hash, _finite, _is_redirected, _lexical_child, _package_file_ref,
    _privacy_errors, _ref_errors, _relative_file_ref, _resolve_ref,
    _safe_cleanup_generated_tree, _tree_has_redirection, _write_json,
    preflight_nle_authorities,
)
from jianying_native_compatibility import validate_compatibility_profile
from jianying_native_plan import validate_draft_plan
from jianying_native_projection import sanitize_fixture_plan

def _inventory(root: Path, *, excluded: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = excluded or set()
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        if relative in excluded:
            continue
        rows.append({"path": relative, "sha256": sha256_file(path)})
    return rows

def _canonical_native_output(root: Path) -> str:
    rows = _inventory(root / "native-draft")
    return hashlib.sha256(json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()

def _preflight_materialization(
    *, plan_path: Path, compatibility_profile_path: Path, output_root: Path,
    authorized_root: Path, build_id: str, standard_editable_delivery: Path,
    max_package_gib: float,
) -> dict[str, Any]:
    authorized_root = Path(os.path.abspath(authorized_root))
    output_root = _lexical_child(output_root, authorized_root, label="native draft output")
    plan_path = _lexical_child(plan_path, authorized_root, label="native draft plan")
    compatibility_profile_path = _lexical_child(
        compatibility_profile_path, authorized_root, label="compatibility profile"
    )
    standard_editable_delivery = _lexical_child(
        standard_editable_delivery, authorized_root,
        label="standard editable delivery fallback",
    )
    if not standard_editable_delivery.is_file():
        raise JianyingNativeDraftError("standard editable delivery fallback is missing")
    if errors := validate_editable_delivery(standard_editable_delivery):
        raise JianyingNativeDraftError(
            "standard editable delivery fallback is invalid:\n- " + "\n- ".join(errors)
        )
    if not isinstance(build_id, str) or not build_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in build_id
    ):
        raise JianyingNativeDraftError("native draft build ID is invalid")
    if not _finite(max_package_gib, minimum=0.000000001) or float(max_package_gib) > 64:
        raise JianyingNativeDraftError("native draft package size budget is invalid")
    plan = read_json(plan_path)
    if errors := validate_draft_plan(plan, authorized_root=authorized_root):
        raise JianyingNativeDraftError("draft plan is invalid:\n- " + "\n- ".join(errors))
    compatibility = read_json(compatibility_profile_path)
    if errors := validate_compatibility_profile(compatibility, allow_fixture=True):
        raise JianyingNativeDraftError(
            "fixture compatibility is invalid:\n- " + "\n- ".join(errors)
        )
    if compatibility.get("editor", {}).get("version") != "fixture-only-not-an-editor":
        raise JianyingNativeDraftError("synthetic materializer requires fixture compatibility")
    try:
        root_relative = output_root.relative_to(authorized_root)
        safe_generated_directory(authorized_root, root_relative)
        staging_parent = safe_generated_directory(
            authorized_root, root_relative / "staging"
        )
        published_parent = safe_generated_directory(
            authorized_root, root_relative / "published"
        )
    except (ValueError, SafeGeneratedOutputError) as error:
        raise JianyingNativeDraftError(str(error)) from error
    target = published_parent / build_id
    if target.exists():
        raise JianyingNativeDraftError("native draft published build already exists")
    return {
        "authorized_root": authorized_root,
        "plan_path": plan_path,
        "standard_editable_delivery": standard_editable_delivery,
        "plan": plan,
        "compatibility": compatibility,
        "target": target,
        "staging_parent": staging_parent,
        "published_parent": published_parent,
    }


def _build_package_manifest(
    *, staging: Path, plan_path: Path, plan: Mapping[str, Any],
    authorized_root: Path, standard_editable_delivery: Path,
    build_id: str,
) -> Path:
    manifest = {
        "schema_version": 1,
        "kind": "jianying_native_draft_package",
        "status": "validated",
        "build_id": build_id,
        "profile": plan["profile"],
        "asset_mode": plan["asset_mode"],
        "plan": _relative_file_ref(plan_path, staging, authorized_root),
        "compatibility": _package_file_ref(
            staging / "compatibility-report.json", staging
        ),
        "adapter_report": _package_file_ref(
            staging / "adapter-report.json", staging
        ),
        "output_root": ".",
        "inventory": _inventory(staging),
        "safety": {
            "new_isolated_draft": True,
            "existing_draft_read": False,
            "existing_draft_modified": False,
            "network_used": False,
            "secret_required": False,
        },
        "fallbacks": {
            "automatic_master": _relative_file_ref(
                _resolve_ref(plan["authorities"]["automatic_master"]),
                staging, authorized_root,
            ),
            "standard_editable_delivery": _relative_file_ref(
                standard_editable_delivery, staging, authorized_root,
            ),
            "nle_package": _relative_file_ref(
                _resolve_ref(plan["authorities"]["nle_package"]),
                staging, authorized_root,
            ),
        },
    }
    manifest["integrity_sha256"] = _canonical_hash(
        manifest, omit="integrity_sha256"
    )
    manifest_path = safe_generated_target(
        staging, Path("draft-package-manifest.json")
    )
    _write_json(manifest_path, manifest)
    return manifest_path


def _write_synthetic_staging(
    context: Mapping[str, Any], *, staging: Path, build_id: str,
    max_package_gib: float,
) -> Path:
    authorized_root = context["authorized_root"]
    plan_path = context["plan_path"]
    standard_editable_delivery = context["standard_editable_delivery"]
    plan = context["plan"]
    compatibility = context["compatibility"]
    safe_generated_directory(staging, Path("native-draft"))
    fixture = sanitize_fixture_plan(plan)
    _write_json(safe_generated_target(staging, Path("native-draft/draft_content.json")), fixture)
    _write_json(safe_generated_target(staging, Path("native-draft/draft_meta_info.json")), {
        "schema_version": 1,
        "synthetic_fixture_only": True,
        "draft_id": plan["draft_id"],
    })
    _write_json(safe_generated_target(staging, Path("adapter-plan.json")), fixture)
    _write_json(
        safe_generated_target(staging, Path("compatibility-report.json")), compatibility
    )
    adapter_report = {
        "schema_version": 1,
        "status": "pass",
        "adapter_id": ADAPTER_ID,
        "adapter_version": ADAPTER_VERSION,
        "artifact_sha256": ADAPTER_WHEEL_SHA256,
        "mode": "synthetic_contract_fixture",
        "third_party_code_executed": False,
        "network_used": False,
        "editor_store_read": False,
        "editor_store_written": False,
        "real_jianying_compatibility_claimed": False,
        "synthetic_fixture_only": True,
        "canonical_output_sha256": _canonical_native_output(staging),
        "max_package_gib": float(max_package_gib),
        "source_plan_sha256": plan["plan_sha256"],
        "source_draft_id": plan["draft_id"],
    }
    _write_json(safe_generated_target(staging, Path("adapter-report.json")), adapter_report)
    atomic_write_text(
        safe_generated_target(staging, Path("README-中文.md")),
        "# 剪映原生草稿适配器合成夹具\n\n"
        "本目录只验证时间轴、轨道、清单和安全合同，不是真实剪映草稿，"
        "不能复制到剪映草稿目录，也不代表任何剪映版本兼容。\n",
    )
    manifest_path = _build_package_manifest(
        staging=staging,
        plan_path=plan_path,
        plan=plan,
        authorized_root=authorized_root,
        standard_editable_delivery=standard_editable_delivery,
        build_id=build_id,
    )
    package_size_bytes = sum(
        path.stat().st_size for path in staging.rglob("*") if path.is_file()
    )
    if package_size_bytes > int(float(max_package_gib) * 1024 ** 3):
        raise JianyingNativeDraftError("synthetic draft package exceeds size budget")
    for json_path in sorted(staging.rglob("*.json")):
        try:
            privacy_errors = _privacy_errors(read_json(json_path), path=json_path.name)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise JianyingNativeDraftError(
                f"synthetic draft JSON is unreadable: {json_path.name}"
            ) from error
        if privacy_errors:
            raise JianyingNativeDraftError(
                "synthetic draft package contains forbidden metadata:\n- "
                + "\n- ".join(privacy_errors)
            )
    return manifest_path


def materialize_synthetic_fixture(
    *, plan_path: Path, compatibility_profile_path: Path, output_root: Path,
    authorized_root: Path, build_id: str, standard_editable_delivery: Path,
    max_package_gib: float = 8.0,
) -> dict[str, Any]:
    """Materialize an isolated deterministic fixture, never a real editor draft."""
    context = _preflight_materialization(
        plan_path=plan_path,
        compatibility_profile_path=compatibility_profile_path,
        output_root=output_root,
        authorized_root=authorized_root,
        build_id=build_id,
        standard_editable_delivery=standard_editable_delivery,
        max_package_gib=max_package_gib,
    )
    authorized_root = context["authorized_root"]
    target = context["target"]
    published_parent = context["published_parent"]
    staging_identity: tuple[int, int] | None = None
    published = False
    staging = context["staging_parent"] / f".{build_id}.staging-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        staging_stat = staging.stat(follow_symlinks=False)
        staging_identity = (staging_stat.st_dev, staging_stat.st_ino)
        _assert_generated_tree_safe(
            staging, authorized_root, identity=staging_identity
        )
        manifest_path = _write_synthetic_staging(
            context, staging=staging, build_id=build_id,
            max_package_gib=max_package_gib,
        )
        if errors := validate_draft_package(
            manifest_path, authorized_root=authorized_root,
            package_root_override=staging, expected_output_root=staging,
        ):
            raise JianyingNativeDraftError(
                "synthetic draft package is invalid:\n- " + "\n- ".join(errors)
            )
        _assert_generated_tree_safe(
            staging, authorized_root, identity=staging_identity
        )
        _lexical_child(published_parent, authorized_root, label="native draft publish root")
        if target.exists() or _is_redirected(target):
            raise JianyingNativeDraftError("native draft published target changed")
        os.replace(staging, target)
        published = True
        _assert_generated_tree_safe(target, authorized_root)
        published_manifest = target / "draft-package-manifest.json"
        if errors := validate_draft_package(
            published_manifest, authorized_root=authorized_root
        ):
            raise JianyingNativeDraftError(
                "published synthetic draft package is invalid:\n- " + "\n- ".join(errors)
            )
        return read_json(published_manifest)
    except Exception:
        if staging_identity is not None:
            _safe_cleanup_generated_tree(
                target if published else staging,
                authorized_root, identity=staging_identity,
            )
        raise


def _validate_package_header_and_refs(
    manifest: Mapping[str, Any], *, package_root: Path,
    authorized_root: Path, expected_output_root: Path | None,
    errors: list[str],
) -> dict[str, Path]:
    if set(manifest) != {
        "schema_version", "kind", "status", "build_id", "profile", "asset_mode",
        "plan", "compatibility", "adapter_report", "output_root", "inventory",
        "safety", "fallbacks", "integrity_sha256",
    }:
        errors.append("native draft package shape is invalid")
    if manifest.get("schema_version") != 1 or manifest.get(
        "kind"
    ) != "jianying_native_draft_package":
        errors.append("native draft package identity is invalid")
    if manifest.get("status") != "validated":
        errors.append("native draft package status is invalid")
    if not isinstance(manifest.get("build_id"), str) or not _DRAFT_IDENTIFIER.fullmatch(
        manifest.get("build_id", "")
    ):
        errors.append("native draft package build ID is invalid")
    if manifest.get("profile") not in PROFILES or manifest.get(
        "asset_mode"
    ) not in ASSET_MODES:
        errors.append("native draft package profile or asset mode is invalid")
    declared_output = manifest.get("output_root")
    if not isinstance(declared_output, str) or not declared_output:
        errors.append("native draft output root is invalid")
    else:
        try:
            declared_path = Path(declared_output)
            if declared_path.is_absolute():
                raise JianyingNativeDraftError(
                    "native draft output root must be package-relative"
                )
            output_root = _lexical_child(
                package_root / declared_path,
                authorized_root, label="native draft output root"
            )
        except JianyingNativeDraftError as error:
            errors.append(str(error))
        else:
            expected = Path(expected_output_root or package_root).resolve()
            if output_root.resolve(strict=False) != expected:
                errors.append("native draft output root differs from the package root")
    try:
        expected_integrity = _canonical_hash(manifest, omit="integrity_sha256")
    except JianyingNativeDraftError as error:
        errors.append(str(error))
    else:
        if manifest.get("integrity_sha256") != expected_integrity:
            errors.append("native draft package integrity is stale")
    safety = manifest.get("safety")
    expected_safety = {
        "new_isolated_draft": True,
        "existing_draft_read": False,
        "existing_draft_modified": False,
        "network_used": False,
        "secret_required": False,
    }
    if safety != expected_safety:
        errors.append("native draft package safety contract is invalid")
    package_ref_paths: dict[str, Path] = {}
    for key in ("plan", "compatibility", "adapter_report"):
        ref_errors = _ref_errors(
            manifest.get(key), label=f"native draft {key}",
            authorized_root=authorized_root, base=package_root,
        )
        errors.extend(ref_errors)
        if not ref_errors:
            resolved = _resolve_ref(manifest.get(key), base=package_root)
            if resolved is not None:
                package_ref_paths[key] = resolved
    return package_ref_paths


def _validate_source_plan_and_fallbacks(
    manifest: Mapping[str, Any], *, package_root: Path,
    authorized_root: Path, package_ref_paths: Mapping[str, Path],
    errors: list[str],
) -> Mapping[str, Any] | None:
    plan_path = package_ref_paths.get("plan")
    source_plan: Mapping[str, Any] | None = None
    if plan_path and plan_path.is_file():
        try:
            candidate_plan = read_json(plan_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("native draft source plan is unreadable")
        else:
            if not isinstance(candidate_plan, Mapping):
                errors.append("native draft source plan must be an object")
            else:
                plan_errors = validate_draft_plan(
                    candidate_plan, authorized_root=authorized_root
                )
                errors.extend(plan_errors)
                if not plan_errors:
                    source_plan = candidate_plan
                if not plan_errors and (
                    candidate_plan.get("profile") != manifest.get("profile")
                    or candidate_plan.get("asset_mode") != manifest.get("asset_mode")
                ):
                    errors.append("native draft package differs from its source plan")
    fallbacks = manifest.get("fallbacks")
    if not isinstance(fallbacks, Mapping) or set(fallbacks) != {
        "automatic_master", "standard_editable_delivery", "nle_package"
    }:
        errors.append("native draft fallback inventory is invalid")
    else:
        fallback_paths: dict[str, Path] = {}
        for key, ref in fallbacks.items():
            ref_errors = _ref_errors(
                ref, label=f"native draft fallback {key}",
                authorized_root=authorized_root, base=package_root,
            )
            errors.extend(ref_errors)
            if not ref_errors:
                resolved = _resolve_ref(ref, base=package_root)
                if resolved is not None:
                    fallback_paths[str(key)] = resolved
        standard_path = fallback_paths.get("standard_editable_delivery")
        if standard_path and standard_path.is_file():
            errors.extend(validate_editable_delivery(standard_path))
        nle_path = fallback_paths.get("nle_package")
        if nle_path and nle_path.is_file():
            try:
                nle_receipt = read_json(nle_path)
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append("native draft NLE fallback receipt is unreadable")
            else:
                authority_errors = preflight_nle_authorities(
                    nle_receipt, authorized_root=authorized_root
                )
                errors.extend(authority_errors)
                if not authority_errors:
                    errors.extend(validate_nle_handoff_package(nle_path))
        if source_plan is not None:
            source_authorities = source_plan.get("authorities")
            if not isinstance(source_authorities, Mapping):
                source_authorities = {}
            for fallback_name, authority_name in (
                ("automatic_master", "automatic_master"),
                ("nle_package", "nle_package"),
            ):
                fallback_ref = fallbacks.get(fallback_name)
                authority_ref = source_authorities.get(authority_name)
                fallback_path = fallback_paths.get(fallback_name)
                authority_path = _resolve_ref(authority_ref)
                if (
                    fallback_path is None
                    or authority_path is None
                    or fallback_path != authority_path
                    or not isinstance(fallback_ref, Mapping)
                    or not isinstance(authority_ref, Mapping)
                    or fallback_ref.get("sha256") != authority_ref.get("sha256")
                ):
                    errors.append(
                        f"native draft {fallback_name} fallback differs from source plan"
                    )
    return source_plan


def _validate_inventory_and_privacy(
    manifest: Mapping[str, Any], *, package_root: Path,
    authorized_root: Path, errors: list[str],
) -> tuple[Path, str | None]:
    inventory = manifest.get("inventory")
    if not isinstance(inventory, list):
        errors.append("native draft package inventory is invalid")
    else:
        declared: set[str] = set()
        for index, ref in enumerate(inventory):
            if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str):
                errors.append(f"native draft inventory {index} is invalid")
                continue
            declared.add(ref["path"].replace("\\", "/"))
            errors.extend(_ref_errors(
                ref, label=f"native draft inventory {index}",
                authorized_root=authorized_root, base=package_root,
            ))
        actual = {
            str(path.relative_to(package_root)).replace("\\", "/")
            for path in package_root.rglob("*")
            if path.is_file() and path.name != "draft-package-manifest.json"
        } if package_root.is_dir() else set()
        if declared != actual:
            errors.append("native draft package inventory has missing or extra files")
    for path in sorted(package_root.rglob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"native draft package JSON is unreadable: {path.name}")
            continue
        errors.extend(_privacy_errors(payload, path=path.name))
        text = json.dumps(payload, ensure_ascii=False).lower()
        if path.is_relative_to(package_root / "native-draft") and any(
            token in text for token in ("effect_id", "resource_id", "transition_id")
        ):
            errors.append("native draft fixture contains a proprietary effect/resource ID")
    native_root = package_root / "native-draft"
    if native_root.is_dir():
        actual_native_hash = _canonical_native_output(package_root)
    else:
        errors.append("native draft directory is missing")
        actual_native_hash = None
    return native_root, actual_native_hash


def _validate_projection_report_and_compatibility(
    manifest: Mapping[str, Any], *, package_root: Path,
    source_plan: Mapping[str, Any] | None, native_root: Path,
    actual_native_hash: str | None,
    package_ref_paths: Mapping[str, Path], errors: list[str],
) -> None:
    if source_plan is not None:
        expected_fixture = sanitize_fixture_plan(source_plan)
        native_content_path = native_root / "draft_content.json"
        adapter_plan_path = package_root / "adapter-plan.json"
        try:
            native_content = read_json(native_content_path)
            adapter_plan = read_json(adapter_plan_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("native draft projected plan is unreadable")
        else:
            if native_content != expected_fixture or adapter_plan != expected_fixture:
                errors.append("native draft projected plan differs from source plan")
    adapter_report_path = package_ref_paths.get("adapter_report")
    if adapter_report_path and adapter_report_path.is_file():
        try:
            adapter_report = read_json(adapter_report_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("native draft adapter report is unreadable")
        else:
            if not isinstance(adapter_report, Mapping):
                errors.append("native draft adapter report must be an object")
                adapter_report = {}
            expected_report_fields = {
                "schema_version", "status", "adapter_id", "adapter_version",
                "artifact_sha256", "mode", "third_party_code_executed",
                "network_used", "editor_store_read", "editor_store_written",
                "real_jianying_compatibility_claimed", "synthetic_fixture_only",
                "canonical_output_sha256", "max_package_gib",
                "source_plan_sha256", "source_draft_id",
            }
            if (
                set(adapter_report) != expected_report_fields
                or adapter_report.get("schema_version") != 1
                or adapter_report.get("status") != "pass"
                or adapter_report.get("adapter_id") != ADAPTER_ID
                or adapter_report.get("adapter_version") != ADAPTER_VERSION
                or adapter_report.get("artifact_sha256") != ADAPTER_WHEEL_SHA256
                or adapter_report.get("mode") != "synthetic_contract_fixture"
                or adapter_report.get("synthetic_fixture_only") is not True
                or adapter_report.get("real_jianying_compatibility_claimed") is not False
                or adapter_report.get("third_party_code_executed") is not False
                or adapter_report.get("network_used") is not False
                or adapter_report.get("editor_store_read") is not False
                or adapter_report.get("editor_store_written") is not False
                or not _finite(
                    adapter_report.get("max_package_gib"), minimum=0.000000001
                )
            ):
                errors.append("native draft synthetic fixture boundary is invalid")
            if source_plan is not None and (
                adapter_report.get("source_plan_sha256") != source_plan.get("plan_sha256")
                or adapter_report.get("source_draft_id") != source_plan.get("draft_id")
            ):
                errors.append("native draft adapter report differs from its source plan")
            if actual_native_hash is not None and adapter_report.get(
                "canonical_output_sha256"
            ) != actual_native_hash:
                errors.append("native draft canonical output is stale")
            if _finite(adapter_report.get("max_package_gib"), minimum=0.000000001):
                actual_size = sum(
                    candidate.stat().st_size
                    for candidate in package_root.rglob("*") if candidate.is_file()
                )
                if actual_size > int(float(adapter_report["max_package_gib"]) * 1024 ** 3):
                    errors.append("native draft package exceeds size budget")
    compatibility_path = package_ref_paths.get("compatibility")
    if compatibility_path and compatibility_path.is_file():
        try:
            errors.extend(validate_compatibility_profile(
                read_json(compatibility_path), allow_fixture=True
            ))
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("native draft compatibility profile is unreadable")


def validate_draft_package(
    manifest_path: Path, *, authorized_root: Path,
    package_root_override: Path | None = None,
    expected_output_root: Path | None = None,
) -> list[str]:
    authorized_root = Path(os.path.abspath(authorized_root))
    try:
        manifest_path = _lexical_child(
            manifest_path, authorized_root, label="native draft package manifest"
        )
        package_root = _lexical_child(
            Path(package_root_override or manifest_path.parent),
            authorized_root, label="native draft package",
        )
    except JianyingNativeDraftError as error:
        return [str(error)]
    if not package_root.is_dir() or _tree_has_redirection(package_root):
        return ["native draft package tree is missing or redirected"]
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["native draft package manifest is unreadable"]
    if not isinstance(manifest, Mapping):
        return ["native draft package manifest must be an object"]
    errors: list[str] = []
    package_ref_paths = _validate_package_header_and_refs(
        manifest, package_root=package_root, authorized_root=authorized_root,
        expected_output_root=expected_output_root, errors=errors,
    )
    source_plan = _validate_source_plan_and_fallbacks(
        manifest, package_root=package_root, authorized_root=authorized_root,
        package_ref_paths=package_ref_paths, errors=errors,
    )
    native_root, actual_native_hash = _validate_inventory_and_privacy(
        manifest, package_root=package_root, authorized_root=authorized_root,
        errors=errors,
    )
    _validate_projection_report_and_compatibility(
        manifest, package_root=package_root, source_plan=source_plan,
        native_root=native_root, actual_native_hash=actual_native_hash,
        package_ref_paths=package_ref_paths, errors=errors,
    )
    return errors
