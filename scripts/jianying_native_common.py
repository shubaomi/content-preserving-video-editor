#!/usr/bin/env python3
"""Shared security and machine-contract primitives for Jianying draft projection."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file
from safe_generated_output import atomic_write_text

SCHEMA_VERSION = 1
PROFILES = {"repair_draft", "layered_reconstruction"}
ASSET_MODES = {"linked", "portable"}
ADAPTER_ID = "pyjianyingdraft_0_3"
ADAPTER_VERSION = "0.3.0"
ADAPTER_WHEEL_SHA256 = "09863de4b0cfbb23fff54b4122ef49eff3527685f7978c6230f0651942954bdc"
LOCK_PATH = (
    Path(__file__).resolve().parents[1]
    / "references" / "jianying-native-draft-v1" / "adapter-lock.json"
)
_HEX = set("0123456789abcdef")
_FORBIDDEN_METADATA_KEYS = {
    "accountid", "account_id", "api_key", "apikey", "authorization",
    "cookie", "cookies", "deviceid", "device_id",
    "mac", "macaddress", "mac_address", "password", "secret", "token",
    "userid", "user_id", "cloudid", "cloud_id",
}
_ROLE_PAYLOAD = {
    "base": "video", "motion": "video", "ip": "ip", "caption": "caption",
    "outro": "outro", "dialogue": "audio", "bgm": "audio", "sfx": "audio",
    "reference": "reference",
}
_TRACK_ROLES = {
    "video": {"base", "motion", "ip", "outro"},
    "text": {"caption", "outro"},
    "audio": {"dialogue", "bgm", "sfx", "outro"},
    "reference": {"reference"},
}
_PAYLOAD_FIELDS = {
    "video": {"type", "alpha_mode", "transform", "motion_editability"},
    "ip": {"type", "asset_role", "transform", "rights_receipt", "protection_window_ids"},
    "caption": {"type", "cue_id", "text", "base_style", "emphasis", "fidelity", "ass_reference"},
    "audio": {"type", "sample_rate_hz", "channels", "gain_db"},
    "outro": {"type", "outro_role", "native_text", "transform"},
    "reference": {"type", "enabled", "locked"},
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]+$")
_DRAFT_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$")
_FIDELITIES = {"full", "degraded", "baked", "unavailable"}

class JianyingNativeDraftError(ValueError):
    """Raised when a native-draft projection cannot be proven safe/current."""

def _transform_errors(value: Any, *, label: str) -> list[str]:
    keys = {"x", "y", "scale_x", "scale_y", "rotation_degrees", "opacity"}
    if not isinstance(value, Mapping) or set(value) != keys:
        return [f"{label} transform shape is invalid"]
    if any(not _finite(value.get(key)) for key in keys):
        return [f"{label} transform is invalid"]
    if (
        float(value["scale_x"]) <= 0
        or float(value["scale_y"]) <= 0
        or not 0 <= float(value["opacity"]) <= 1
    ):
        return [f"{label} transform is out of range"]
    return []

def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2

def _finite(value: Any, *, minimum: float | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and (minimum is None or number >= minimum)

def _canonical_hash(payload: Mapping[str, Any], *, omit: str) -> str:
    value = dict(payload)
    value.pop(omit, None)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise JianyingNativeDraftError("native draft contract is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()

def _write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )

def _is_redirected(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(os.path, "isjunction", lambda _path: False)(path)
    )

def _lexical_child(path: Path, root: Path, *, label: str) -> Path:
    lexical_root = Path(os.path.abspath(root))
    lexical_path = Path(os.path.abspath(path))
    if not lexical_path.is_relative_to(lexical_root):
        raise JianyingNativeDraftError(f"{label} must remain inside the authorized root")
    cursor = lexical_root
    if cursor.exists() and _is_redirected(cursor):
        raise JianyingNativeDraftError(f"{label} authorized root is redirected")
    for part in lexical_path.relative_to(lexical_root).parts:
        cursor /= part
        if cursor.exists() and _is_redirected(cursor):
            raise JianyingNativeDraftError(f"{label} path is redirected")
    return lexical_path

def _tree_has_redirection(path: Path) -> bool:
    if _is_redirected(path):
        return True
    for current, directories, files in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            if _is_redirected(current_path / name):
                return True
    return False

def _assert_generated_tree_safe(
    path: Path, authorized_root: Path, *, identity: tuple[int, int] | None = None,
) -> None:
    safe_path = _lexical_child(path, authorized_root, label="generated draft tree")
    if not safe_path.is_dir() or _tree_has_redirection(safe_path):
        raise JianyingNativeDraftError("generated draft tree is missing or redirected")
    if identity is not None:
        stat = safe_path.stat(follow_symlinks=False)
        if (stat.st_dev, stat.st_ino) != identity:
            raise JianyingNativeDraftError("generated draft tree identity changed")

def _safe_cleanup_generated_tree(
    path: Path, authorized_root: Path, *, identity: tuple[int, int],
) -> None:
    try:
        safe_path = _lexical_child(path, authorized_root, label="generated draft cleanup")
        stat = safe_path.stat(follow_symlinks=False)
        if (
            (stat.st_dev, stat.st_ino) != identity
            or not safe_path.is_dir()
            or _tree_has_redirection(safe_path)
        ):
            return
    except (FileNotFoundError, JianyingNativeDraftError, OSError):
        return
    shutil.rmtree(safe_path)

def _file_ref(path: Path) -> dict[str, str]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise JianyingNativeDraftError(f"required file is missing: {resolved}")
    return {"path": str(resolved), "sha256": sha256_file(resolved)}

def _package_file_ref(path: Path, package_root: Path) -> dict[str, str]:
    resolved = Path(path).resolve()
    root = Path(package_root).resolve()
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise JianyingNativeDraftError("package file must remain inside its package root")
    return {
        "path": str(resolved.relative_to(root)).replace("\\", "/"),
        "sha256": sha256_file(resolved),
    }

def _relative_file_ref(path: Path, package_root: Path, authorized_root: Path) -> dict[str, str]:
    """Bind an external authority without leaking an absolute workstation path."""
    resolved = _lexical_child(path, authorized_root, label="native draft authority")
    if not resolved.is_file():
        raise JianyingNativeDraftError("native draft authority is missing")
    relative = os.path.relpath(resolved, Path(package_root).resolve())
    return {"path": relative.replace("\\", "/"), "sha256": sha256_file(resolved)}

def _resolve_ref(value: Any, *, base: Path | None = None) -> Path | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return None
    path = Path(value["path"])
    if not path.is_absolute() and base is not None:
        path = base / path
    return path.resolve()


def preflight_nle_authorities(
    receipt: Any, *, authorized_root: Path,
) -> list[str]:
    """Reject transitive NLE authority paths before an upstream validator reads them."""
    authorities = receipt.get("authorities") if isinstance(receipt, Mapping) else None
    if not isinstance(authorities, Mapping):
        return ["NLE package authorities are invalid"]
    errors: list[str] = []
    for name in ("project", "source", "edl", "automatic_master"):
        authority_path = _resolve_ref(authorities.get(name))
        if authority_path is None:
            errors.append(f"NLE {name} authority path is invalid")
            continue
        try:
            _lexical_child(
                authority_path, authorized_root, label=f"NLE {name} authority"
            )
        except JianyingNativeDraftError as error:
            errors.append(str(error))
    return errors

def _ref_errors(
    value: Any, *, label: str, authorized_root: Path, base: Path | None = None,
) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} file reference must be an object"]
    if set(value) != {"path", "sha256"}:
        return [f"{label} file reference shape is invalid"]
    if not _valid_sha(value.get("sha256")):
        return [f"{label} file reference hash is invalid"]
    path = _resolve_ref(value, base=base)
    if path is None:
        return [f"{label} path is invalid"]
    try:
        _lexical_child(path, authorized_root, label=label)
    except JianyingNativeDraftError as error:
        return [str(error)]
    if not path.is_file():
        return [f"{label} file is missing"]
    if value.get("sha256") != sha256_file(path):
        return [f"{label} file reference is stale"]
    return []

def _frame(value: Any, *, numerator: int, denominator: int) -> int:
    if not _finite(value, minimum=0):
        raise JianyingNativeDraftError("timeline seconds must be finite and nonnegative")
    scaled = Fraction(str(float(value))) * numerator / denominator
    return (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)

def _timebase(frame_rate: Any, duration: Any) -> dict[str, int]:
    if not _finite(frame_rate, minimum=0.000001) or not _finite(duration, minimum=0.000001):
        raise JianyingNativeDraftError("timeline frame rate and duration must be positive")
    rate = float(frame_rate)
    known = (
        (24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1),
        (50, 1), (60000, 1001), (60, 1),
    )
    numerator, denominator = min(known, key=lambda pair: abs(rate - pair[0] / pair[1]))
    if abs(rate - numerator / denominator) > 0.0005:
        fraction = Fraction(str(rate)).limit_denominator(100_000)
        numerator, denominator = fraction.numerator, fraction.denominator
    duration_frames = _frame(duration, numerator=numerator, denominator=denominator)
    if duration_frames < 1:
        raise JianyingNativeDraftError("timeline duration rounds to zero frames")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "duration_frames": duration_frames,
    }

def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX

def _privacy_errors(value: Any, *, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _FORBIDDEN_METADATA_KEYS or normalized.replace("_", "") in {
                item.replace("_", "") for item in _FORBIDDEN_METADATA_KEYS
            }:
                errors.append(f"native draft contains forbidden metadata key at {path}.{key}")
            errors.extend(_privacy_errors(child, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_privacy_errors(child, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        normalized = value.replace("\\", "/").lower()
        home = str(Path.home()).replace("\\", "/").lower().rstrip("/")
        if re.search(r"(?i)\b(?:https?|file)://", value):
            errors.append(f"native draft contains a forbidden URL at {path}")
        if (
            (home and (normalized == home or normalized.startswith(home + "/")))
            or "/appdata/" in normalized
            or "/.cache/" in normalized
            or "/.config/" in normalized
        ):
            errors.append(f"native draft contains a forbidden home/cache path at {path}")
    return errors
