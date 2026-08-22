#!/usr/bin/env python3
"""No-reparse Windows filesystem primitives for the WP4 draft boundary."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Mapping

if os.name == "nt":
    import msvcrt

from jianying_native_common import (
    JianyingNativeDraftError, _is_redirected, _lexical_child,
)


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("file_attributes", ctypes.c_uint32),
        ("creation_time_low", ctypes.c_uint32),
        ("creation_time_high", ctypes.c_uint32),
        ("access_time_low", ctypes.c_uint32),
        ("access_time_high", ctypes.c_uint32),
        ("write_time_low", ctypes.c_uint32),
        ("write_time_high", ctypes.c_uint32),
        ("volume_serial", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("link_count", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


def _win_open_no_reparse(path: Path, *, directory: bool) -> int:
    if os.name != "nt":
        raise JianyingNativeDraftError("WP4 filesystem locking is Windows-only")
    kernel32 = ctypes.windll.kernel32
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    # DELETE access plus no FILE_SHARE_DELETE makes a directory handle an
    # effective exchange lock on Windows; FILE_READ_ATTRIBUTES alone still
    # permits rename-to-junction races.
    desired_access = (0x00010000 | 0x00000080) if directory else 0x80000000
    share_mode = 0x00000001 | (0x00000002 if directory else 0)
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = create_file(str(path), desired_access, share_mode, None, 3, flags, None)
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise JianyingNativeDraftError("WP4 path could not be locked safely")
    information = _ByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(
        ctypes.c_void_p(handle), ctypes.byref(information)
    ):
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise JianyingNativeDraftError("WP4 locked path identity is unreadable")
    if information.file_attributes & 0x00000400:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise JianyingNativeDraftError("WP4 locked path is redirected")
    return int(handle)


@contextmanager
def _locked_directory(path: Path, expected_identity: tuple[int, int]):
    handle = _win_open_no_reparse(path, directory=True)
    try:
        if _identity(path) != expected_identity or _is_redirected(path):
            raise JianyingNativeDraftError("WP4 locked directory identity changed")
        yield
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def _read_file_no_reparse(path: Path) -> bytes:
    handle = _win_open_no_reparse(path, directory=False)
    try:
        descriptor = msvcrt.open_osfhandle(
            handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
    except Exception:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read()


def _read_file_snapshot(path: Path) -> tuple[bytes, tuple[int, int]]:
    """Read one regular file while its non-reparse identity is pinned."""
    handle = _win_open_no_reparse(path, directory=False)
    try:
        descriptor = msvcrt.open_osfhandle(
            handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
    except Exception:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        current = path.stat(follow_symlinks=False)
        identity = (opened.st_dev, opened.st_ino)
        if identity != (current.st_dev, current.st_ino) or _is_redirected(path):
            raise JianyingNativeDraftError("WP4 locked file identity changed")
        return stream.read(), identity


def _identity(path: Path) -> tuple[int, int]:
    stat = path.stat(follow_symlinks=False)
    return stat.st_dev, stat.st_ino


def _read_stable_json(
    path: Path, *, label: str, parent_identity: tuple[int, int] | None = None,
) -> tuple[Any, tuple[int, int], str]:
    def read_locked() -> tuple[Any, tuple[int, int], str]:
        raw, identity = _read_file_snapshot(path)
        payload = json.loads(raw.decode("utf-8"))
        return payload, identity, hashlib.sha256(raw).hexdigest()

    try:
        if parent_identity is None:
            return read_locked()
        with _locked_directory(path.parent, parent_identity):
            return read_locked()
    except JianyingNativeDraftError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JianyingNativeDraftError(f"{label} is unreadable") from error


def _absolute_without_resolution(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _lexical_project_child(path: Path, root: Path, *, label: str) -> Path:
    try:
        return _lexical_child(path, root, label=label)
    except JianyingNativeDraftError:
        raise
    except (OSError, ValueError) as error:
        raise JianyingNativeDraftError(f"{label} is invalid") from error


def _inventory(
    root: Path, *, expected_identity: tuple[int, int] | None = None,
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    """Inventory without following a directory redirect or an unpinned file."""
    if not root.is_dir():
        raise JianyingNativeDraftError("WP4 generated test draft is missing or redirected")
    root_identity = expected_identity or _identity(root)
    rows: list[dict[str, Any]] = []

    def visit(directory: Path, relative_root: Path, locks: ExitStack) -> None:
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            relative = relative_root / entry.name
            if entry.is_symlink() or _is_redirected(path):
                raise JianyingNativeDraftError("WP4 generated test draft is redirected")
            if entry.is_dir(follow_symlinks=False):
                identity = _identity(path)
                locks.enter_context(_locked_directory(path, identity))
                visit(path, relative, locks)
            elif entry.is_file(follow_symlinks=False):
                raw, _file_identity = _read_file_snapshot(path)
                rows.append({
                    "path": relative.as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                })
            else:
                raise JianyingNativeDraftError(
                    "WP4 generated test draft contains an unsupported entry"
                )

    with ExitStack() as locks:
        locks.enter_context(_locked_directory(root, root_identity))
        visit(root, Path("."), locks)
    if not rows and not allow_empty:
        raise JianyingNativeDraftError("WP4 generated test draft is empty")
    return rows


def _copy_tree(
    source: Path, staging: Path, *, source_identity: tuple[int, int],
    staging_identity: tuple[int, int], expected_inventory: list[dict[str, str]],
) -> None:
    directories = {Path(".")}
    for row in expected_inventory:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise JianyingNativeDraftError("WP4 native inventory path is unsafe")
        directories.update([relative.parent, *relative.parent.parents])
    directories.discard(Path("."))
    with ExitStack() as locks:
        # Hold both roots before creating any descendant.  On Windows the
        # no-delete-share handles prevent either root from being exchanged for
        # a junction between validation and the first mkdir/write.
        locks.enter_context(_locked_directory(source, source_identity))
        locks.enter_context(_locked_directory(staging, staging_identity))
        for relative in sorted(directories, key=lambda value: (len(value.parts), str(value))):
            (staging / relative).mkdir()
        source_directories = [source / row for row in sorted(directories)]
        staging_directories = [staging / row for row in sorted(directories)]
        source_identities = [_identity(path) for path in source_directories]
        staging_identities = [_identity(path) for path in staging_directories]
        for path, identity in zip(source_directories, source_identities):
            locks.enter_context(_locked_directory(path, identity))
        for path, identity in zip(staging_directories, staging_identities):
            locks.enter_context(_locked_directory(path, identity))
        for row in expected_inventory:
            source_path = source / row["path"]
            raw = _read_file_no_reparse(source_path)
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise JianyingNativeDraftError("WP4 source native file changed during copy")
            target = staging / row["path"]
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())


def _exclusive_write_json(
    path: Path, payload: Mapping[str, Any],
    *, parent_identity: tuple[int, int] | None = None,
) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    descriptor: int | None = None
    created_identity: tuple[int, int] | None = None
    def write_locked() -> None:
        nonlocal descriptor, created_identity
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created_stat = os.fstat(descriptor)
            created_identity = (created_stat.st_dev, created_stat.st_ino)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            if created_identity is not None:
                try:
                    current = path.stat(follow_symlinks=False)
                    if (
                        (current.st_dev, current.st_ino) == created_identity
                        and not _is_redirected(path)
                    ):
                        path.unlink()
                except (FileNotFoundError, OSError):
                    pass
            raise

    if parent_identity is None:
        write_locked()
    else:
        with _locked_directory(path.parent, parent_identity):
            write_locked()


def _safe_remove_exact_tree(
    path: Path, *, store_root: Path, store_identity: tuple[int, int],
    store_parent_identity: tuple[int, int],
    tree_identity: tuple[int, int], expected_inventory: list[dict[str, Any]],
) -> bool:
    quarantine = store_root / f".{path.name}.quarantine-{uuid.uuid4().hex}"
    try:
        # Lock the store's parent: this prevents replacing the store root while
        # still permitting the intended atomic rename of one direct child.
        with _locked_directory(store_root.parent, store_parent_identity):
            if _identity(store_root) != store_identity:
                return False
            if not path.is_dir() or _identity(path) != tree_identity:
                return False
            if _inventory(path, expected_identity=tree_identity) != expected_inventory:
                return False
            if os.path.lexists(quarantine):
                return False
            os.rename(path, quarantine)
            if (
                _identity(quarantine) != tree_identity
                or _inventory(quarantine, expected_identity=tree_identity)
                != expected_inventory
            ):
                if not os.path.lexists(path):
                    os.rename(quarantine, path)
                return False
            shutil.rmtree(quarantine)
            return True
    except (OSError, JianyingNativeDraftError):
        return False


def _safe_remove_partial_generated_tree(
    path: Path, *, store_root: Path, store_identity: tuple[int, int],
    store_parent_identity: tuple[int, int], tree_identity: tuple[int, int],
) -> bool:
    """Remove only the still-identical staging tree created by this attempt."""
    quarantine = store_root / f".{path.name}.partial-{uuid.uuid4().hex}"
    try:
        with _locked_directory(store_root.parent, store_parent_identity):
            if _identity(store_root) != store_identity:
                return False
            if not path.is_dir() or _identity(path) != tree_identity:
                return False
            inventory = _inventory(
                path, expected_identity=tree_identity, allow_empty=True
            )
            if os.path.lexists(quarantine):
                return False
            os.rename(path, quarantine)
            if (
                _identity(quarantine) != tree_identity
                or _inventory(
                    quarantine, expected_identity=tree_identity, allow_empty=True
                ) != inventory
            ):
                if not os.path.lexists(path):
                    os.rename(quarantine, path)
                return False
            shutil.rmtree(quarantine)
            return True
    except (OSError, JianyingNativeDraftError):
        return False


def _safe_unlink_owned(
    path: Path, identity: tuple[int, int], *, parent_identity: tuple[int, int],
) -> None:
    try:
        with _locked_directory(path.parent, parent_identity):
            if _identity(path) == identity and not _is_redirected(path):
                path.unlink()
    except (OSError, JianyingNativeDraftError):
        pass
