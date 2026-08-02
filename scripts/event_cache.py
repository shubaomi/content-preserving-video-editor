#!/usr/bin/env python3
"""Content-addressed event cache with atomic, corruption-checked entries."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from dependency_graph import DependencyGraph


class EventCacheError(ValueError):
    """Raised when an event fingerprint or cache entry is unsafe."""


REQUIRED_FINGERPRINT_FIELDS = (
    "event_id",
    "owner_artifact_sha256",
    "renderer",
    "renderer_version",
    "event_payload",
    "captions_sha256",
    "safe_zones_sha256",
    "design_tokens_sha256",
    "provider_evidence_sha256",
    "rights_evidence_sha256",
    "asset_hashes",
    "implementation_sha256",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pid_is_alive(value: Any) -> bool:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        handle = open_process(synchronize, 0, pid)
        if not handle:
            error = ctypes.get_last_error()
            return error == 5  # Access denied still proves the process exists.
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _process_identity(pid: int) -> str | None:
    """Return a stable process-start identity when the platform exposes one."""
    if os.name == "nt":
        import ctypes

        query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        handle = open_process(query_limited_information, 0, pid)
        if not handle:
            return None
        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]
        try:
            creation, exit_time, kernel, user = (FileTime() for _ in range(4))
            get_process_times = kernel32.GetProcessTimes
            get_process_times.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
                ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
            ]
            get_process_times.restype = ctypes.c_int
            if not get_process_times(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel), ctypes.byref(user),
            ):
                return None
            return f"windows-filetime:{(creation.high << 32) | creation.low}"
        finally:
            kernel32.CloseHandle(handle)
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        text = stat_path.read_text(encoding="utf-8")
        fields_after_name = text[text.rfind(")") + 2:].split()
        return f"proc-starttime:{fields_after_name[19]}"
    except (OSError, IndexError):
        return None


def _lock_owner_is_current(record: Mapping[str, Any]) -> bool:
    pid = record.get("pid")
    if not _pid_is_alive(pid):
        return False
    recorded = str(record.get("process_identity") or "").strip()
    if not recorded:
        return True  # Legacy lock: fail closed rather than reclaiming a live PID.
    try:
        current = _process_identity(int(pid))
    except (TypeError, ValueError):
        return False
    return current is None or current == recorded


def build_event_key(fingerprint: Mapping[str, Any]) -> str:
    missing = [field for field in REQUIRED_FINGERPRINT_FIELDS if field not in fingerprint]
    if missing:
        raise EventCacheError("event fingerprint is missing: " + ", ".join(missing))
    event_id = fingerprint.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise EventCacheError("event_id must be a non-empty string")
    for field in REQUIRED_FINGERPRINT_FIELDS:
        if fingerprint[field] is None:
            raise EventCacheError(f"event fingerprint field cannot be null: {field}")
    return hashlib.sha256(_canonical(dict(fingerprint))).hexdigest()


def plan_event_rebuild(
    previous: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    nodes: list[dict[str, Any]],
) -> dict[str, list[str]]:
    graph = DependencyGraph(nodes)
    order = graph.topological_order()
    changed = {
        event_id for event_id in current
        if event_id not in previous
        or build_event_key(previous[event_id]) != build_event_key(current[event_id])
    }
    graph_nodes = set(order)
    unknown = set(current) - graph_nodes
    if unknown:
        raise EventCacheError("current fingerprints missing from dependency graph: " + ", ".join(sorted(unknown)))
    invalidated = graph.invalidated_by(changed) if changed else set()
    removed = sorted(set(previous) - set(current))
    return {
        "rebuild": [event_id for event_id in order if event_id in invalidated],
        "reuse": [event_id for event_id in order if event_id in current and event_id not in invalidated],
        "removed": removed,
    }


class EventCache:
    def __init__(
        self, root: Path, *, lock_timeout_seconds: float = 10.0,
        stale_lock_seconds: float = 300.0,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_timeout_seconds = lock_timeout_seconds
        self.stale_lock_seconds = stale_lock_seconds

    def _entry(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise EventCacheError("cache key must be a lowercase SHA-256")
        return self.root / key

    def lookup(self, key: str) -> dict[str, Any] | None:
        entry = self._entry(key)
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != 1 or manifest.get("event_key") != key:
                return None
            outputs = manifest.get("outputs")
            if not isinstance(outputs, list) or not outputs:
                return None
            enriched: list[dict[str, Any]] = []
            for output in outputs:
                relative = Path(str(output["relative_path"]))
                if relative.is_absolute() or ".." in relative.parts:
                    return None
                cached = (entry / relative).resolve()
                if entry not in cached.parents or not cached.is_file():
                    return None
                if cached.stat().st_size != int(output["size"]):
                    return None
                if _sha256(cached) != output["sha256"]:
                    return None
                enriched.append({**output, "cache_path": str(cached)})
            return {**manifest, "outputs": enriched}
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def _acquire_lock(self, key: str) -> tuple[Path, str]:
        lock = self.root / f"{key}.lock"
        deadline = time.monotonic() + self.lock_timeout_seconds
        token = uuid.uuid4().hex
        payload = json.dumps({
            "schema_version": 1,
            "pid": os.getpid(),
            "created_at": time.time(),
            "process_identity": _process_identity(os.getpid()),
            "token": token,
        }, sort_keys=True).encode("utf-8")
        while True:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(descriptor, payload)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                return lock, token
            except FileExistsError:
                try:
                    observed = lock.read_bytes()
                    record = json.loads(observed.decode("utf-8"))
                    created_at = float(record.get("created_at"))
                    stale = (
                        time.time() - created_at >= self.stale_lock_seconds
                        and not _lock_owner_is_current(record)
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    try:
                        stale = time.time() - lock.stat().st_mtime >= self.stale_lock_seconds
                    except OSError:
                        stale = False
                    observed = b""
                if stale:
                    try:
                        if observed and lock.read_bytes() != observed:
                            continue
                        abandoned = self.root / f"{key}.abandoned-{uuid.uuid4().hex}.lock"
                        os.replace(lock, abandoned)
                        abandoned.unlink(missing_ok=True)
                        continue
                    except (FileNotFoundError, PermissionError, OSError):
                        pass
                if time.monotonic() >= deadline:
                    raise EventCacheError(f"timed out waiting for event cache lock: {key}")
                time.sleep(0.02)

    def store(self, key: str, outputs: Mapping[str, Path]) -> dict[str, Any]:
        existing = self.lookup(key)
        if existing is not None:
            return existing
        if not outputs:
            raise EventCacheError("event cache requires at least one output")
        lock, lock_token = self._acquire_lock(key)
        partial = self.root / f"{key}.partial-{uuid.uuid4().hex}"
        target = self._entry(key)
        try:
            existing = self.lookup(key)
            if existing is not None:
                return existing
            partial.mkdir(parents=False)
            records: list[dict[str, Any]] = []
            for logical_name, source_value in sorted(outputs.items()):
                relative = Path(logical_name)
                if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                    raise EventCacheError(f"unsafe event output name: {logical_name}")
                source = Path(source_value).resolve()
                if not source.is_file():
                    raise EventCacheError(f"event output does not exist: {source}")
                destination = partial / "outputs" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                records.append({
                    "name": logical_name,
                    "relative_path": str(Path("outputs") / relative).replace("\\", "/"),
                    "size": destination.stat().st_size,
                    "sha256": _sha256(destination),
                })
            manifest = {"schema_version": 1, "event_key": key, "outputs": records}
            (partial / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            if target.exists():
                quarantine = self.root / f"{key}.corrupt-{uuid.uuid4().hex}"
                os.replace(target, quarantine)
            os.replace(partial, target)
            verified = self.lookup(key)
            if verified is None:
                raise EventCacheError(f"event cache entry failed verification: {key}")
            return verified
        finally:
            if partial.exists():
                shutil.rmtree(partial, ignore_errors=True)
            try:
                current = json.loads(lock.read_text(encoding="utf-8"))
                if current.get("token") == lock_token:
                    lock.unlink(missing_ok=True)
            except (OSError, json.JSONDecodeError):
                pass
