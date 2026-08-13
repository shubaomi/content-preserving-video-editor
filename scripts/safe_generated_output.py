#!/usr/bin/env python3
"""Junction-safe, atomic helpers for generated project artifacts on Windows."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path


class SafeGeneratedOutputError(ValueError):
    """Raised before a generated artifact could escape its authorized root."""


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(os.path, "isjunction", lambda _path: False)(path)
    )


def safe_generated_directory(root: Path, relative: Path) -> Path:
    """Create one relative directory while rejecting every redirected component."""
    root = Path(os.path.abspath(root))
    for candidate in (root, *root.parents):
        if _is_link(candidate):
            raise SafeGeneratedOutputError(f"generated output root is redirected: {candidate}")
    root = root.resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise SafeGeneratedOutputError("generated output must be a relative child")
    root.mkdir(parents=True, exist_ok=True)
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise SafeGeneratedOutputError(f"generated output is redirected: {current}")
        current.mkdir(exist_ok=True)
        if not current.resolve().is_relative_to(root):
            raise SafeGeneratedOutputError(f"generated output escapes its root: {current}")
    return current.resolve()


def safe_generated_target(root: Path, relative: Path) -> Path:
    """Resolve a file target under root, creating only safe parent directories."""
    relative = Path(relative)
    parent = safe_generated_directory(root, relative.parent)
    target = parent / relative.name
    if _is_link(target) or (target.exists() and not target.is_file()):
        raise SafeGeneratedOutputError(f"generated output target is redirected or invalid: {target}")
    if not target.resolve(strict=False).is_relative_to(Path(root).resolve()):
        raise SafeGeneratedOutputError(f"generated output target escapes its root: {target}")
    return target


def atomic_replace_file(source: Path, target: Path) -> None:
    """Copy source beside target, then atomically replace after bytes are complete."""
    source = Path(source).resolve()
    target = Path(target)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(target: Path, value: str) -> None:
    """Write UTF-8 text beside target and atomically replace the completed file."""
    target = Path(target)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    finally:
        temporary.unlink(missing_ok=True)
