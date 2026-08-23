#!/usr/bin/env python3
"""Dependency-free Windows no-reparse reads for the isolated adapter runner."""
from __future__ import annotations

import ctypes
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt


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


def _open_no_reparse(path: Path, *, directory: bool) -> int:
    if os.name != "nt":
        raise ValueError("locked adapter I/O is Windows-only")
    kernel32 = ctypes.windll.kernel32
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    desired = (
        0x00010000 | 0x00000080 | 0x00000001
    ) if directory else 0x80000000
    share = 0x00000001 | (0x00000002 if directory else 0)
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = create_file(str(path), desired, share, None, 3, flags, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ValueError("adapter path could not be locked safely")
    information = _ByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(
        ctypes.c_void_p(handle), ctypes.byref(information)
    ) or information.file_attributes & 0x00000400:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise ValueError("adapter path is unreadable or redirected")
    return int(handle)


def _identity(path: Path) -> tuple[int, int]:
    value = path.stat(follow_symlinks=False)
    return value.st_dev, value.st_ino


def _is_redirected(path: Path) -> bool:
    value = path.lstat()
    return path.is_symlink() or bool(
        getattr(value, "st_file_attributes", 0) & 0x00000400
    )


@contextmanager
def _locked_directory(path: Path, expected_identity: tuple[int, int]):
    handle = _open_no_reparse(path, directory=True)
    try:
        if _identity(path) != expected_identity:
            raise ValueError("adapter locked directory identity changed")
        yield
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


@contextmanager
def _locked_file(path: Path, expected_identity: tuple[int, int]):
    handle = _open_no_reparse(path, directory=False)
    try:
        if _identity(path) != expected_identity or _is_redirected(path):
            raise ValueError("adapter locked file identity changed")
        yield
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def _open_file(path: Path):
    handle = _open_no_reparse(path, directory=False)
    try:
        descriptor = msvcrt.open_osfhandle(
            handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
    except Exception:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise
    return os.fdopen(descriptor, "rb")


def _verify_open_file(stream, path: Path) -> tuple[int, int]:
    opened = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    identity = opened.st_dev, opened.st_ino
    if identity != (current.st_dev, current.st_ino):
        raise ValueError("adapter locked file identity changed")
    return identity


def _read_file_snapshot(path: Path) -> tuple[bytes, tuple[int, int]]:
    with _open_file(path) as stream:
        identity = _verify_open_file(stream, path)
        return stream.read(), identity


def _sha256_file_snapshot(path: Path) -> tuple[str, int, tuple[int, int]]:
    with _open_file(path) as stream:
        identity = _verify_open_file(stream, path)
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        return digest.hexdigest(), size, identity
