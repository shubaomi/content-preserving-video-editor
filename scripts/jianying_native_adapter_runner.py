#!/usr/bin/env python3
"""Execute the exact pinned pyJianYingDraft wheel in an isolated subprocess."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import platform
import stat
import struct
import sys
import zipfile
import os
from pathlib import Path
from typing import Any, Mapping


sys.path.insert(0, str(Path(__file__).resolve().parent))
from jianying_native_adapter_lock import (  # noqa: E402
    ADAPTER_DEPENDENCY_LOCK, ADAPTER_RUNTIME_LOCK, ADAPTER_WHEEL_FILENAME,
    ADAPTER_WHEEL_SHA256,
)
from jianying_native_locked_io import (  # noqa: E402
    _identity as _locked_identity, _is_redirected, _read_file_snapshot,
    _sha256_file_snapshot,
)

ADAPTER_ID = "pyjianyingdraft_0_3"
ADAPTER_VERSION = "0.3.0"
LOCK_MODULE_PATH = Path(__file__).with_name("jianying_native_adapter_lock.py")
LOCKED_IO_PATH = Path(__file__).with_name("jianying_native_locked_io.py")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _authorized_chain(
    path: Path, *, authorized_root: Path,
) -> tuple[Path, list[Path], list[tuple[int, int]]]:
    path = Path(os.path.abspath(path))
    authorized_root = Path(os.path.abspath(authorized_root))
    try:
        relative_parent = path.parent.relative_to(authorized_root)
    except ValueError as error:
        raise ValueError("adapter artifact is outside the authorized root") from error
    chain = [authorized_root]
    current = authorized_root
    for part in relative_parent.parts:
        current /= part
        chain.append(current)
    try:
        identities = [_locked_identity(directory) for directory in chain]
        if any(_is_redirected(directory) for directory in chain):
            raise ValueError("adapter authorized path chain is redirected")
    except OSError as error:
        raise ValueError("adapter authorized path chain is unreadable") from error
    return path, chain, identities


def _locked_authorized_bytes(
    path: Path, *, authorized_root: Path, max_bytes: int,
) -> bytes:
    """Read a bounded file while the trusted parent holds its full input chain."""
    path, chain, identities = _authorized_chain(path, authorized_root=authorized_root)
    try:
        raw, _identity = _read_file_snapshot(path)
        if any(
            _locked_identity(directory) != identity or _is_redirected(directory)
            for directory, identity in zip(chain, identities)
        ):
            raise ValueError("adapter authorized path chain changed")
    except OSError as error:
        raise ValueError("adapter authorized file is unreadable") from error
    if len(raw) > max_bytes:
        raise ValueError("adapter artifact exceeds its size limit")
    return raw


def _locked_authorized_hash(
    path: Path, *, authorized_root: Path,
) -> str:
    path, chain, identities = _authorized_chain(path, authorized_root=authorized_root)
    digest, _size, _identity = _sha256_file_snapshot(path)
    if any(
        _locked_identity(directory) != identity or _is_redirected(directory)
        for directory, identity in zip(chain, identities)
    ):
        raise ValueError("adapter authorized path chain changed")
    return digest


def _safe_extract(
    wheel_bytes: bytes, target: Path, *, create_root: bool = True,
) -> None:
    if create_root:
        target.mkdir()
    elif not target.is_dir():
        raise ValueError("adapter runtime root is missing")
    root = target.resolve()
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        entries = archive.infolist()
        if len(entries) > 4096 or sum(row.file_size for row in entries) > 1024 * 1024 * 1024:
            raise ValueError("adapter wheel exceeds extraction limits")
        canonical: set[str] = set()
        for info in entries:
            relative = Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("adapter wheel contains an unsafe path")
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if stat.S_ISLNK(mode) or file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("adapter wheel contains an unsupported entry")
            if info.flag_bits & 0x1 or info.file_size > 512 * 1024 * 1024:
                raise ValueError("adapter wheel entry exceeds extraction limits")
            if info.compress_size and info.file_size / info.compress_size > 250:
                raise ValueError("adapter wheel entry compression ratio is unsafe")
            parts = []
            for part in relative.parts:
                normalized = part.rstrip(" .").casefold()
                stem = normalized.split(".", 1)[0]
                if (
                    not normalized or ":" in normalized
                    or stem in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
                ):
                    raise ValueError("adapter wheel contains an unsafe Windows name")
                parts.append(normalized)
            key = "/".join(parts)
            if key in canonical:
                raise ValueError("adapter wheel contains a canonical path collision")
            canonical.add(key)
            destination = (target / relative).resolve()
            if not destination.is_relative_to(root):
                raise ValueError("adapter wheel extraction escaped its runtime root")
        for info in entries:
            destination = target / Path(info.filename)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with archive.open(info) as source, os.fdopen(descriptor, "wb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)


def _color(value: Any) -> tuple[float, float, float]:
    if not isinstance(value, str) or len(value) < 7 or not value.startswith("#"):
        return (1.0, 1.0, 1.0)
    try:
        return tuple(int(value[index:index + 2], 16) / 255 for index in (1, 3, 5))
    except ValueError:
        return (1.0, 1.0, 1.0)


def _text_style(draft, clip: Mapping[str, Any]):
    payload = clip.get("payload") if isinstance(clip.get("payload"), Mapping) else {}
    base = payload.get("base_style") if isinstance(payload.get("base_style"), Mapping) else {}
    size_value = base.get("font_size") or base.get("font_size_px") or base.get("size") or 8.0
    try:
        size = float(size_value)
    except (TypeError, ValueError):
        size = 8.0
    if not math.isfinite(size) or size <= 0:
        size = 8.0
    color = base.get("base_color") or base.get("color") or "#FFFFFF"
    return draft.TextStyle(
        size=size, bold=bool(base.get("bold", False)), color=_color(color),
        align=1, auto_wrapping=True, max_line_width=0.82,
    )


def _clip_settings(draft, payload: Mapping[str, Any]):
    transform = payload.get("transform") if isinstance(payload.get("transform"), Mapping) else {}
    return draft.ClipSettings(
        alpha=float(transform.get("opacity", 1.0)),
        rotation=float(transform.get("rotation_degrees", 0.0)),
        scale_x=float(transform.get("scale_x", 1.0)),
        scale_y=float(transform.get("scale_y", 1.0)),
        transform_x=float(transform.get("x", 0.0)),
        transform_y=float(transform.get("y", 0.0)),
    )


def _enable_windows_long_path_mediainfo() -> None:
    """Let ctypes load the bundled DLL when the project path exceeds MAX_PATH."""
    if os.name != "nt":
        return
    import pymediainfo  # type: ignore
    dll = Path(pymediainfo.__file__).resolve().parent / "MediaInfo.dll"
    if not dll.is_file():
        return
    extended = str(dll)
    if not extended.startswith("\\\\?\\"):
        extended = "\\\\?\\" + extended
    original = pymediainfo.MediaInfo._get_library

    @classmethod
    def long_path_get_library(cls, library_file=None):
        return original(extended if library_file is None else library_file)

    pymediainfo.MediaInfo._get_library = long_path_get_library


def _validate_request(
    request: Mapping[str, Any], *, expected_parent: Path, authorized_root: Path,
) -> dict[str, Any]:
    required = {
        "schema_version", "kind", "plan_sha256", "draft_id", "fps", "canvas",
        "native_draft_root", "native_parent", "projection_report_path",
        "adapter_wheel", "adapter_wheel_sha256", "adapter_runtime_root", "tracks",
        "adapter_dependencies", "authorized_root",
        "adapter_python_sha256", "adapter_runtime_lock", "adapter_lock_sha256",
        "adapter_locked_io_sha256",
        "runner_sha256", "network_access_control", "parent_input_locks",
        "omitted",
    }
    if set(request) != required or request.get("schema_version") != 1 or request.get(
        "kind"
    ) != "jianying_adapter_execution_request":
        raise ValueError("adapter request shape is invalid")
    authorized_root = authorized_root.resolve()
    if Path(request["authorized_root"]).resolve() != authorized_root:
        raise ValueError("adapter authorized root is invalid")
    if not expected_parent.resolve().is_relative_to(authorized_root):
        raise ValueError("adapter authorized root is invalid")
    wheel = Path(os.path.abspath(request["adapter_wheel"]))
    runtime = Path(request["adapter_runtime_root"]).resolve()
    native_parent = Path(request["native_parent"]).resolve()
    native_root = Path(request["native_draft_root"]).resolve()
    report_path = Path(request["projection_report_path"]).resolve()
    expected_parent = expected_parent.resolve()
    interpreter = Path(sys.executable).resolve()
    runner = Path(__file__).resolve()
    if wheel.name != ADAPTER_WHEEL_FILENAME:
        raise ValueError("adapter wheel does not match the compiled lock")
    wheel_bytes = _locked_authorized_bytes(
        wheel, authorized_root=authorized_root, max_bytes=64 * 1024 * 1024
    )
    if len(wheel_bytes) > 64 * 1024 * 1024 or hashlib.sha256(wheel_bytes).hexdigest() != ADAPTER_WHEEL_SHA256:
        raise ValueError("adapter wheel does not match the compiled lock")
    if (
        request["adapter_wheel_sha256"] != ADAPTER_WHEEL_SHA256
        or runtime.exists() or native_root.exists()
        or native_parent != expected_parent
        or runtime.parent != native_parent or native_root.parent != native_parent
        or report_path.parent != native_parent
        or request.get("adapter_runtime_lock") != ADAPTER_RUNTIME_LOCK
        or request.get("adapter_lock_sha256") != _sha256(LOCK_MODULE_PATH)
        or request.get("adapter_locked_io_sha256") != _sha256(LOCKED_IO_PATH)
        or _sha256(interpreter) != ADAPTER_RUNTIME_LOCK["python_executable_sha256"]
        or request["adapter_python_sha256"]
        != ADAPTER_RUNTIME_LOCK["python_executable_sha256"]
        or _sha256(interpreter.parent.parent / "pyvenv.cfg")
        != ADAPTER_RUNTIME_LOCK["pyvenv_cfg_sha256"]
        or platform.python_version() != ADAPTER_RUNTIME_LOCK["python_version"]
        or platform.machine() != ADAPTER_RUNTIME_LOCK["machine"]
        or struct.calcsize("P") * 8 != ADAPTER_RUNTIME_LOCK["pointer_bits"]
        or _sha256(runner) != request["runner_sha256"]
        or request["network_access_control"] != "not_enforced"
        or request["parent_input_locks"] is not True
    ):
        raise ValueError("adapter request paths or pinned wheel are invalid")
    dependency_bytes: list[bytes] = []
    dependencies = request.get("adapter_dependencies")
    if not isinstance(dependencies, list) or len(dependencies) != len(ADAPTER_DEPENDENCY_LOCK):
        raise ValueError("adapter dependency lock is incomplete")
    received = {Path(row.get("path", "")).name: row for row in dependencies if isinstance(row, Mapping)}
    if set(received) != set(ADAPTER_DEPENDENCY_LOCK):
        raise ValueError("adapter dependency lock is incomplete")
    for name, expected_hash in ADAPTER_DEPENDENCY_LOCK.items():
        row = received[name]
        path = Path(os.path.abspath(received[name]["path"]))
        raw = _locked_authorized_bytes(
            path, authorized_root=authorized_root, max_bytes=512 * 1024 * 1024
        )
        if row.get("sha256") != expected_hash or hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError("adapter dependency differs from the compiled lock")
        dependency_bytes.append(raw)
    source_hashes: dict[Path, str] = {}
    for track in request.get("tracks") or []:
        for clip in track.get("clips") or []:
            source = Path(os.path.abspath(str(clip.get("source_path", ""))))
            if source not in source_hashes:
                source_hashes[source] = _locked_authorized_hash(
                    source, authorized_root=authorized_root,
                )
            if (
                source_hashes[source] != clip.get("source_sha256")
            ):
                raise ValueError("adapter source reference is invalid")
    return {
        "wheel_bytes": wheel_bytes, "runtime": runtime,
        "native_parent": native_parent, "report_path": report_path,
        "dependency_bytes": dependency_bytes,
    }


def _load_adapter(*, wheel_bytes: bytes, dependency_bytes: list[bytes], runtime: Path):
    _safe_extract(wheel_bytes, runtime)
    for raw in dependency_bytes:
        _safe_extract(raw, runtime, create_root=False)
    sys.path.insert(0, str(runtime))
    import pyJianYingDraft as draft  # type: ignore
    module_path = Path(draft.__file__).resolve()
    if not module_path.is_relative_to(runtime):
        raise ValueError("adapter import did not use the pinned wheel runtime")
    _enable_windows_long_path_mediainfo()
    return draft


def _make_segment(draft, *, kind: str, clip: Mapping[str, Any]):
    target = draft.Timerange(
        int(clip["target_start_us"]), int(clip["target_duration_us"])
    )
    source = draft.Timerange(
        int(clip["source_start_us"]), int(clip["source_duration_us"])
    )
    if kind == "video":
        return draft.VideoSegment(
            draft.VideoMaterial(clip["source_path"]), target,
            source_timerange=source,
            clip_settings=_clip_settings(draft, clip["payload"]),
        )
    if kind == "audio":
        gain_db = float(clip["payload"].get("gain_db", 0.0))
        return draft.AudioSegment(
            draft.AudioMaterial(clip["source_path"]), target,
            source_timerange=source, volume=10 ** (gain_db / 20),
        )
    text = clip.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError("native text clip is empty")
    return draft.TextSegment(
        text, target, style=_text_style(draft, clip),
        clip_settings=_clip_settings(draft, clip["payload"]),
    )


def _add_segment_with_exact_touching_boundary(script, segment, track_ref) -> None:
    """Work around the pinned adapter treating exact end/start contact as overlap.

    The canonical frame plan remains authoritative. We temporarily shorten only
    an existing segment whose end exactly equals the new segment's start, let
    the pinned library register the new segment and its materials, then restore
    the exact duration before the draft is serialized and validated.
    """
    track = script._resolve_track_ref(track_ref)
    touching = [
        existing for existing in track.segments
        if existing.target_timerange.end == segment.target_timerange.start
        and existing.target_timerange.duration > 1
    ]
    for existing in touching:
        existing.target_timerange.duration -= 1
    try:
        script.add_segment(segment, track_ref)
    finally:
        for existing in touching:
            existing.target_timerange.duration += 1


def _project_tracks(draft, *, script, tracks: list[Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    type_map = {
        "video": draft.TrackType.video,
        "audio": draft.TrackType.audio,
        "text": draft.TrackType.text,
    }
    for track in sorted(tracks, key=lambda row: (row["order"], row["track_id"])):
        kind = track["kind"]
        if kind not in type_map:
            raise ValueError(f"unsupported native track kind: {kind}")
        track_ref = script.append_track(draft.TrackSpec(type_map[kind], track["track_id"]))
        for clip in track["clips"]:
            segment = _make_segment(draft, kind=kind, clip=clip)
            _add_segment_with_exact_touching_boundary(script, segment, track_ref)
            projected.append({
                "clip_id": clip["clip_id"], "track_id": track["track_id"],
                "segment_id": segment.segment_id, "status": "projected",
            })
    return projected


def _write_report(
    *, request: Mapping[str, Any], projected: list[dict[str, Any]],
    report_path: Path,
) -> dict[str, Any]:
    report = {
        "schema_version": 1, "kind": "jianying_native_projection_report",
        "status": "generated_unopened", "adapter_id": ADAPTER_ID,
        "adapter_version": ADAPTER_VERSION,
        "source_plan_sha256": request["plan_sha256"],
        "adapter_artifact_sha256": request["adapter_wheel_sha256"],
        "adapter_python_sha256": request["adapter_python_sha256"],
        "adapter_runtime_lock": request["adapter_runtime_lock"],
        "adapter_lock_sha256": request["adapter_lock_sha256"],
        "adapter_locked_io_sha256": request["adapter_locked_io_sha256"],
        "adapter_dependencies": {
            Path(row["path"]).name: row["sha256"]
            for row in request["adapter_dependencies"]
        },
        "parent_input_locks": request["parent_input_locks"],
        "runner_sha256": request["runner_sha256"],
        "third_party_code_executed": True,
        "editor_store_path_supplied": False,
        "editor_store_operation_requested": False,
        "editor_store_access_control": "not_enforced",
        "editor_store_access_evidence": "unknown",
        "editor_launched_by_orchestrator": False,
        "network_access_control": "not_enforced",
        "network_use_evidence": "unknown",
        "projected": projected, "omitted": request["omitted"],
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def execute(
    request: Mapping[str, Any], *, expected_parent: Path, authorized_root: Path,
) -> dict[str, Any]:
    context = _validate_request(
        request, expected_parent=expected_parent, authorized_root=authorized_root,
    )
    draft = _load_adapter(
        wheel_bytes=context["wheel_bytes"],
        dependency_bytes=context["dependency_bytes"], runtime=context["runtime"]
    )
    folder = draft.DraftFolder(str(context["native_parent"]))
    script = folder.create_draft(
        "native-draft", int(request["canvas"]["width"]),
        int(request["canvas"]["height"]), int(request["fps"]),
        allow_replace=False,
    )
    projected = _project_tracks(draft, script=script, tracks=request["tracks"])
    script.save()
    return _write_report(
        request=request, projected=projected, report_path=context["report_path"]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--authorized-root", type=Path, required=True)
    args = parser.parse_args()
    raw = args.request.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("adapter request snapshot hash is stale")
    request = json.loads(raw.decode("utf-8"))
    execute(
        request, expected_parent=args.request.resolve().parent,
        authorized_root=args.authorized_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
