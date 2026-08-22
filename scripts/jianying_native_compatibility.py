#!/usr/bin/env python3
"""Pinned-adapter and exact-version compatibility contracts."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Any, Iterable, Mapping

from director_contracts import read_json, sha256_file
from jianying_native_common import (
    ADAPTER_ID, ADAPTER_VERSION, ADAPTER_WHEEL_SHA256, LOCK_PATH,
    JianyingNativeDraftError, _IDENTIFIER, _privacy_errors, _valid_sha,
    _lexical_child,
)

def validate_adapter_lock(path: Path = LOCK_PATH) -> list[str]:
    errors: list[str] = []
    try:
        payload = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["Jianying adapter lock is unreadable"]
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        return ["Jianying adapter lock identity is invalid"]
    if set(payload) != {
        "schema_version", "adapter_id", "package", "version", "distribution",
        "license", "import_name", "network_required_for_generation",
        "forbidden_operations",
    }:
        errors.append("Jianying adapter lock shape is invalid")
    if payload.get("adapter_id") != ADAPTER_ID or payload.get("version") != ADAPTER_VERSION:
        errors.append("Jianying adapter lock version is not the frozen adapter")
    if payload.get("package") != "pyJianYingDraft" or payload.get(
        "import_name"
    ) != "pyJianYingDraft":
        errors.append("Jianying adapter package/import lock is invalid")
    distribution = payload.get("distribution")
    if (
        not isinstance(distribution, Mapping)
        or set(distribution) != {"filename", "sha256", "index"}
        or distribution.get("filename") != "pyjianyingdraft-0.3.0-py3-none-any.whl"
        or distribution.get("sha256") != ADAPTER_WHEEL_SHA256
        or distribution.get("index") != "https://pypi.org/project/pyjianyingdraft/0.3.0/"
    ):
        errors.append("Jianying adapter distribution lock is invalid")
    license_row = payload.get("license")
    if (
        not isinstance(license_row, Mapping)
        or set(license_row) != {"spdx", "source"}
        or license_row.get("spdx") != "Apache-2.0"
        or license_row.get("source")
        != "https://github.com/GuanYixuan/pyJianYingDraft/blob/main/LICENSE"
    ):
        errors.append("Jianying adapter license lock is invalid")
    if payload.get("network_required_for_generation") is not False:
        errors.append("Jianying adapter generation must be local-only")
    forbidden = payload.get("forbidden_operations")
    expected_forbidden = {
        "load_template", "duplicate_as_template", "remove_existing_draft",
        "open_editor", "export_media", "read_editor_store",
    }
    if (
        not isinstance(forbidden, list)
        or len(forbidden) != len(expected_forbidden)
        or set(forbidden) != expected_forbidden
    ):
        errors.append("Jianying adapter forbidden-operation boundary is incomplete")
    return errors

def _windows_file_version(executable: Path) -> str:
    """Read PE version metadata without starting the executable."""
    if os.name != "nt":
        raise JianyingNativeDraftError(
            "Jianying executable version discovery is supported only on Windows"
        )
    version_api = ctypes.windll.version
    size = version_api.GetFileVersionInfoSizeW(str(executable), None)
    if not size:
        raise JianyingNativeDraftError("Jianying executable has no readable version metadata")
    buffer = ctypes.create_string_buffer(size)
    if not version_api.GetFileVersionInfoW(str(executable), 0, size, buffer):
        raise JianyingNativeDraftError("Jianying executable version metadata read failed")
    value = ctypes.c_void_p()
    length = ctypes.c_uint()
    if not version_api.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(length)):
        raise JianyingNativeDraftError("Jianying executable fixed version is missing")

    class _FixedFileInfo(ctypes.Structure):
        _fields_ = [
            ("signature", ctypes.c_uint32), ("structure_version", ctypes.c_uint32),
            ("file_version_ms", ctypes.c_uint32), ("file_version_ls", ctypes.c_uint32),
            ("product_version_ms", ctypes.c_uint32), ("product_version_ls", ctypes.c_uint32),
            ("file_flags_mask", ctypes.c_uint32), ("file_flags", ctypes.c_uint32),
            ("file_os", ctypes.c_uint32), ("file_type", ctypes.c_uint32),
            ("file_subtype", ctypes.c_uint32), ("file_date_ms", ctypes.c_uint32),
            ("file_date_ls", ctypes.c_uint32),
        ]

    fixed = ctypes.cast(value, ctypes.POINTER(_FixedFileInfo)).contents
    if fixed.signature != 0xFEEF04BD:
        raise JianyingNativeDraftError("Jianying executable fixed version is invalid")
    parts = (
        fixed.file_version_ms >> 16,
        fixed.file_version_ms & 0xFFFF,
        fixed.file_version_ls >> 16,
        fixed.file_version_ls & 0xFFFF,
    )
    return ".".join(str(part) for part in parts)

def discover_jianying_executable(
    *, executable: Path, authorized_install_roots: Iterable[Path],
) -> dict[str, Any]:
    """Hash and version one explicitly supplied editor binary without launching it."""
    executable = Path(os.path.abspath(executable))
    roots = [Path(os.path.abspath(root)) for root in authorized_install_roots]
    if not roots:
        raise JianyingNativeDraftError("Jianying discovery requires an approved install root")
    contained = False
    for root in roots:
        try:
            _lexical_child(executable, root, label="Jianying executable")
        except JianyingNativeDraftError:
            continue
        contained = True
        break
    if not contained:
        raise JianyingNativeDraftError(
            "Jianying executable must remain inside an approved install root"
        )
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise JianyingNativeDraftError("Jianying executable is missing or not an EXE")
    version = _windows_file_version(executable)
    if not version or len(version) > 120:
        raise JianyingNativeDraftError("Jianying executable version is invalid")
    return {
        "schema_version": 1,
        "kind": "jianying_executable_discovery",
        "status": "detected_unapproved",
        "os": {"name": platform.system().lower(), "architecture": platform.machine()},
        "editor": {
            "product": "jianying_desktop",
            "version": version,
            "executable_path": str(executable),
            "executable_sha256": sha256_file(executable),
        },
        "editor_launched": False,
        "draft_store_read": False,
        "draft_store_written": False,
        "compatibility_claimed": False,
    }

def build_fixture_compatibility_profile() -> dict[str, Any]:
    """Return a fixture-only tuple; it is never real Jianying compatibility."""
    if errors := validate_adapter_lock():
        raise JianyingNativeDraftError("adapter lock failed:\n- " + "\n- ".join(errors))
    return {
        "schema_version": 1,
        "profile_id": "fixture.windows.synthetic.pyjianyingdraft-0.3.0",
        "os": {"name": "windows", "architecture": "synthetic"},
        "editor": {
            "product": "jianying_desktop",
            "version": "fixture-only-not-an-editor",
            "executable_sha256": "0" * 64,
        },
        "adapter": {
            "id": ADAPTER_ID,
            "version": ADAPTER_VERSION,
            "artifact_sha256": ADAPTER_WHEEL_SHA256,
            "license": "Apache-2.0",
        },
        "serialization_profile": "synthetic_contract_fixture_v1",
        "draft_layout_signature": hashlib.sha256(
            b"synthetic-contract-fixture-v1"
        ).hexdigest(),
        "maturity": "fixture_validated",
        "capabilities": {
            "real_editor_compatibility": "unverified",
            "caption_tracks": "unverified",
            "media_tracks": "unverified",
            "audio_tracks": "unverified",
        },
        "canary_receipt": None,
    }

def validate_compatibility_profile(payload: Any, *, allow_fixture: bool) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["Jianying compatibility profile must be an object"]
    errors: list[str] = []
    required = {
        "schema_version", "profile_id", "os", "editor", "adapter",
        "serialization_profile", "draft_layout_signature", "maturity",
        "capabilities", "canary_receipt",
    }
    if set(payload) != required or payload.get("schema_version") != 1:
        errors.append("Jianying compatibility profile shape is invalid")
    errors.extend(_privacy_errors(payload))
    os_row = payload.get("os")
    if (
        not isinstance(os_row, Mapping) or set(os_row) != {"name", "architecture"}
        or os_row.get("name") != "windows"
        or not isinstance(os_row.get("architecture"), str)
        or not os_row["architecture"]
    ):
        errors.append("Jianying compatibility OS shape is invalid")
    adapter = payload.get("adapter")
    if not isinstance(adapter, Mapping) or (
        set(adapter) != {"id", "version", "artifact_sha256", "license"}
        or
        adapter.get("id") != ADAPTER_ID
        or adapter.get("version") != ADAPTER_VERSION
        or adapter.get("artifact_sha256") != ADAPTER_WHEEL_SHA256
        or adapter.get("license") != "Apache-2.0"
    ):
        errors.append("Jianying compatibility adapter tuple is invalid")
    editor = payload.get("editor")
    if (
        not isinstance(editor, Mapping)
        or set(editor) != {"product", "version", "executable_sha256"}
        or editor.get("product") != "jianying_desktop"
    ):
        errors.append("Jianying compatibility editor identity is invalid")
    elif not isinstance(editor.get("version"), str) or not editor["version"]:
        errors.append("Jianying compatibility editor version is missing")
    elif not _valid_sha(editor.get("executable_sha256")):
        errors.append("Jianying compatibility executable hash is invalid")
    if not _valid_sha(payload.get("draft_layout_signature")):
        errors.append("Jianying draft layout signature is invalid")
    if (
        not isinstance(payload.get("profile_id"), str)
        or not _IDENTIFIER.fullmatch(payload["profile_id"])
        or not isinstance(payload.get("serialization_profile"), str)
        or not payload["serialization_profile"]
    ):
        errors.append("Jianying compatibility profile identity is invalid")
    maturity = payload.get("maturity")
    if maturity not in {"documented", "fixture_validated", "real_project_validated"}:
        errors.append("Jianying compatibility maturity is invalid")
    fixture = isinstance(editor, Mapping) and editor.get("version") == "fixture-only-not-an-editor"
    if fixture and not allow_fixture:
        errors.append("synthetic compatibility cannot authorize real generation")
    if fixture and maturity != "fixture_validated":
        errors.append("synthetic compatibility maturity must be fixture_validated")
    if maturity == "real_project_validated" and not isinstance(
        payload.get("canary_receipt"), Mapping
    ):
        errors.append("real-project compatibility requires a canary receipt")
    capabilities = payload.get("capabilities")
    if (
        not isinstance(capabilities, Mapping)
        or set(capabilities) != {
            "real_editor_compatibility", "caption_tracks", "media_tracks", "audio_tracks"
        }
        or any(value not in {"supported", "degraded", "unsupported", "unverified"}
               for value in capabilities.values())
    ):
        errors.append("Jianying compatibility capabilities are invalid")
    canary = payload.get("canary_receipt")
    if fixture and canary is not None:
        errors.append("synthetic compatibility cannot contain a canary receipt")
    elif canary is not None and (
        not isinstance(canary, Mapping)
        or set(canary) != {"path", "sha256"}
        or not isinstance(canary.get("path"), str)
        or not canary["path"]
        or not _valid_sha(canary.get("sha256"))
    ):
        errors.append("Jianying compatibility canary reference is invalid")
    errors.extend(validate_adapter_lock())
    return errors
