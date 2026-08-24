#!/usr/bin/env python3
"""Project-local Jianying draft candidate generation.

This module deliberately has no Jianying draft-store parameter.  It creates a
new, disposable draft folder below the current video project; a human may copy
that folder to the draft location selected in their own Jianying installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import uuid
from fractions import Fraction
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Mapping

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from director_contracts import read_json, sha256_file
from editable_delivery import validate_editable_delivery
from safe_generated_output import (
    SafeGeneratedOutputError, atomic_replace_file, atomic_write_text, safe_generated_directory,
    safe_generated_target,
)
from jianying_native_common import (
    ADAPTER_ID, ADAPTER_VERSION, ADAPTER_WHEEL_SHA256, JianyingNativeDraftError,
    _DRAFT_IDENTIFIER, _assert_generated_tree_safe, _canonical_hash, _file_ref,
    _lexical_child, _package_file_ref, _relative_file_ref,
    _ref_errors, _tree_has_redirection, _write_json,
)
from jianying_native_plan import validate_draft_plan
from jianying_native_adapter_lock import ADAPTER_DEPENDENCY_LOCK, ADAPTER_RUNTIME_LOCK
from jianying_native_install_fs import (
    _identity as _locked_identity,
    _exclusive_write_json,
    _inventory as _locked_inventory,
    _locked_directory,
    _locked_file,
    _read_stable_json,
    _rename_locked_directory,
    _safe_remove_partial_generated_tree,
)


RUNNER_PATH = Path(__file__).with_name("jianying_native_adapter_runner.py")
ADAPTER_LOCK_PATH = Path(__file__).with_name("jianying_native_adapter_lock.py")
LOCKED_IO_PATH = Path(__file__).with_name("jianying_native_locked_io.py")
GUIDE_SCREENSHOT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "references" / "manual-nle-handoff-v2" / "screenshots"
)


def _inventory(root: Path, *, root_already_locked: bool = False) -> list[dict[str, Any]]:
    return [
        row for row in _locked_inventory(
            root, allow_empty=True, root_already_locked=root_already_locked
        )
        if row["path"] != "candidate-manifest.json"
    ]


def _frame_to_us(frame: int, *, numerator: int, denominator: int) -> int:
    value = Fraction(frame * denominator * 1_000_000, numerator)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _exclusive_write_text(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _lock_adapter_inputs(context: Mapping[str, Any], locks: ExitStack) -> None:
    """Pin every path the child adapter may read before CreateProcess."""
    authorized_root = context["authorized_root"]
    files: dict[Path, str] = {
        context["adapter_wheel"]: ADAPTER_WHEEL_SHA256,
        **{
            path: ADAPTER_DEPENDENCY_LOCK[path.name]
            for path in context["adapter_dependencies"]
        },
    }
    for track in context["plan"]["tracks"]:
        if track["kind"] == "reference":
            continue
        for clip in track["clips"]:
            path = _lexical_child(
                Path(clip["source"]["path"]), authorized_root,
                label="adapter media source",
            )
            expected = clip["source"]["sha256"]
            if path in files and files[path] != expected:
                raise JianyingNativeDraftError(
                    "adapter input has conflicting approved hashes"
                )
            files[path] = expected
    directories: set[Path] = set()
    for path in files:
        relative_parent = path.parent.relative_to(authorized_root)
        current = authorized_root
        directories.add(current)
        for part in relative_parent.parts:
            current /= part
            directories.add(current)
    for directory in sorted(
        directories, key=lambda value: (len(value.parts), str(value).casefold())
    ):
        identity = _locked_identity(directory)
        locks.enter_context(_locked_directory(directory, identity))
    for path, expected_sha256 in sorted(
        files.items(), key=lambda row: str(row[0]).casefold()
    ):
        locks.enter_context(_locked_file(
            path, expected_identity=_locked_identity(path),
            expected_sha256=expected_sha256,
        ))


def _load_plan_context(
    *, plan_path: Path, output_root: Path, authorized_root: Path,
    build_id: str, adapter_python: Path, adapter_wheel: Path,
    standard_editable_delivery: Path,
) -> dict[str, Any]:
    authorized_root = Path(os.path.abspath(authorized_root))
    plan_path = _lexical_child(plan_path, authorized_root, label="native plan")
    output_root = _lexical_child(
        output_root, authorized_root, label="project-local native output"
    )
    adapter_python = _lexical_child(
        adapter_python, authorized_root, label="isolated adapter Python"
    )
    adapter_wheel = _lexical_child(
        adapter_wheel, authorized_root, label="pinned adapter wheel"
    )
    standard_editable_delivery = _lexical_child(
        standard_editable_delivery, authorized_root,
        label="standard editable-delivery fallback",
    )
    if not isinstance(build_id, str) or not _DRAFT_IDENTIFIER.fullmatch(build_id):
        raise JianyingNativeDraftError("project-local draft build ID is invalid")
    for path, label in (
        (plan_path, "draft plan"), (adapter_python, "adapter Python"),
        (adapter_wheel, "adapter wheel"),
        (standard_editable_delivery, "editable-delivery fallback"),
    ):
        if not path.is_file():
            raise JianyingNativeDraftError(f"{label} is missing")
    venv_root = adapter_python.parent.parent
    if (
        adapter_python.name.lower() != "python.exe"
        or adapter_python.parent.name.lower() != "scripts"
        or not (venv_root / "pyvenv.cfg").is_file()
    ):
        raise JianyingNativeDraftError(
            "adapter Python must be a project-local Windows virtual environment"
        )
    if (
        sha256_file(adapter_python)
        != ADAPTER_RUNTIME_LOCK["python_executable_sha256"]
        or sha256_file(venv_root / "pyvenv.cfg")
        != ADAPTER_RUNTIME_LOCK["pyvenv_cfg_sha256"]
    ):
        raise JianyingNativeDraftError(
            "adapter Python runtime differs from the approved runtime lock"
        )
    if (
        adapter_wheel.name != "pyjianyingdraft-0.3.0-py3-none-any.whl"
        or sha256_file(adapter_wheel) != ADAPTER_WHEEL_SHA256
    ):
        raise JianyingNativeDraftError("adapter wheel differs from the frozen lock")
    dependencies: list[Path] = []
    for name, expected_sha256 in ADAPTER_DEPENDENCY_LOCK.items():
        dependency = adapter_wheel.parent / name
        if not dependency.is_file() or sha256_file(dependency) != expected_sha256:
            raise JianyingNativeDraftError(
                f"adapter dependency differs from the frozen lock: {name}"
            )
        dependencies.append(dependency)
    if errors := validate_editable_delivery(standard_editable_delivery):
        raise JianyingNativeDraftError(
            "standard editable-delivery fallback is invalid:\n- " + "\n- ".join(errors)
        )
    try:
        plan = read_json(plan_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise JianyingNativeDraftError("draft plan is unreadable") from error
    if errors := validate_draft_plan(plan, authorized_root=authorized_root):
        raise JianyingNativeDraftError("draft plan is invalid:\n- " + "\n- ".join(errors))
    if plan.get("asset_mode") != "linked":
        raise JianyingNativeDraftError(
            "v1 project-local candidate supports linked assets only; portable rewrite is unimplemented"
        )
    timebase = plan["timebase"]
    numerator = int(timebase["numerator"])
    denominator = int(timebase["denominator"])
    if numerator % denominator:
        raise JianyingNativeDraftError(
            "v1 project-local adapter requires an integer Jianying frame rate"
        )
    timeline_ref = plan["authorities"]["layer_timeline"]
    timeline_path = _lexical_child(
        Path(timeline_ref["path"]), authorized_root, label="layer timeline"
    )
    if not timeline_path.is_file() or sha256_file(timeline_path) != timeline_ref["sha256"]:
        raise JianyingNativeDraftError("layer timeline authority is missing or stale")
    timeline = read_json(timeline_path)
    canvas = timeline.get("canvas") if isinstance(timeline, Mapping) else None
    if (
        not isinstance(canvas, Mapping)
        or any(isinstance(canvas.get(key), bool) or not isinstance(canvas.get(key), int)
               or canvas[key] < 1 for key in ("width", "height"))
    ):
        raise JianyingNativeDraftError("layer timeline canvas is invalid")
    try:
        relative = output_root.relative_to(authorized_root)
        safe_generated_directory(authorized_root, relative)
        staging_parent = safe_generated_directory(authorized_root, relative / "staging")
        published_parent = safe_generated_directory(authorized_root, relative / "published")
    except (ValueError, SafeGeneratedOutputError) as error:
        raise JianyingNativeDraftError(str(error)) from error
    target = published_parent / build_id
    if target.exists():
        raise JianyingNativeDraftError("project-local published draft candidate already exists")
    return {
        "authorized_root": authorized_root, "plan_path": plan_path,
        "output_root": output_root, "adapter_python": adapter_python,
        "adapter_wheel": adapter_wheel,
        "adapter_dependencies": dependencies,
        "adapter_runtime_lock": dict(ADAPTER_RUNTIME_LOCK),
        "adapter_lock_sha256": sha256_file(ADAPTER_LOCK_PATH),
        "adapter_runner_sha256": sha256_file(RUNNER_PATH),
        "adapter_locked_io_sha256": sha256_file(LOCKED_IO_PATH),
        "adapter_toolchain_parent_identity": _locked_identity(RUNNER_PATH.parent),
        "adapter_runner_identity": _locked_identity(RUNNER_PATH),
        "adapter_lock_identity": _locked_identity(ADAPTER_LOCK_PATH),
        "adapter_locked_io_identity": _locked_identity(LOCKED_IO_PATH),
        "adapter_python_identity": _locked_identity(adapter_python),
        "adapter_scripts_identity": _locked_identity(adapter_python.parent),
        "adapter_venv_identity": _locked_identity(venv_root),
        "adapter_cfg_path": venv_root / "pyvenv.cfg",
        "adapter_cfg_identity": _locked_identity(venv_root / "pyvenv.cfg"),
        "standard_editable_delivery": standard_editable_delivery,
        "plan": plan, "fps": numerator // denominator,
        "canvas": {"width": int(canvas["width"]), "height": int(canvas["height"])},
        "staging_parent": staging_parent, "published_parent": published_parent,
        "output_identity": _locked_identity(output_root),
        "output_parent_identity": _locked_identity(output_root.parent),
        "staging_parent_identity": _locked_identity(staging_parent),
        "published_parent_identity": _locked_identity(published_parent),
        "target": target,
    }


def _adapter_request(context: Mapping[str, Any], *, staging: Path) -> dict[str, Any]:
    plan = context["plan"]
    numerator = int(plan["timebase"]["numerator"])
    denominator = int(plan["timebase"]["denominator"])
    tracks: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    for track in plan["tracks"]:
        if track["kind"] == "reference":
            omitted.extend({
                "clip_id": clip["clip_id"],
                "reason": "disabled_reference_is_external_fallback",
            } for clip in track["clips"])
            continue
        clips: list[dict[str, Any]] = []
        for clip in track["clips"]:
            start = int(clip["start_frame"])
            duration = int(clip["duration_frames"])
            source_start = int(clip["source_start_frame"])
            target_start_us = _frame_to_us(
                start, numerator=numerator, denominator=denominator
            )
            source_start_us = _frame_to_us(
                source_start, numerator=numerator, denominator=denominator
            )
            row = {
                "clip_id": clip["clip_id"], "role": clip["role"],
                "target_start_us": target_start_us,
                "target_duration_us": _frame_to_us(
                    start + duration, numerator=numerator, denominator=denominator
                ) - target_start_us,
                "source_start_us": source_start_us,
                "source_duration_us": _frame_to_us(
                    source_start + duration,
                    numerator=numerator, denominator=denominator,
                ) - source_start_us,
                "source_path": clip["source"]["path"],
                "source_sha256": clip["source"]["sha256"],
                "payload": clip["payload"],
            }
            if track["kind"] == "text":
                row["text"] = (
                    clip["payload"].get("text")
                    if clip["role"] == "caption"
                    else clip["payload"].get("native_text")
                )
            clips.append(row)
        tracks.append({
            "track_id": track["track_id"], "kind": track["kind"],
            "order": track["order"], "clips": clips,
        })
    return {
        "schema_version": 1, "kind": "jianying_adapter_execution_request",
        "plan_sha256": plan["plan_sha256"], "draft_id": plan["draft_id"],
        "fps": context["fps"], "canvas": context["canvas"],
        "native_draft_root": str(staging / "native-draft"),
        "native_parent": str(staging),
        "projection_report_path": str(staging / "projection-report.json"),
        "adapter_wheel": str(context["adapter_wheel"]),
        "adapter_wheel_sha256": ADAPTER_WHEEL_SHA256,
        "adapter_dependencies": [
            {"path": str(path), "sha256": ADAPTER_DEPENDENCY_LOCK[path.name]}
            for path in context["adapter_dependencies"]
        ],
        "adapter_runtime_lock": context["adapter_runtime_lock"],
        "adapter_lock_sha256": context["adapter_lock_sha256"],
        "adapter_locked_io_sha256": context["adapter_locked_io_sha256"],
        "adapter_python_sha256": sha256_file(context["adapter_python"]),
        "runner_sha256": context["adapter_runner_sha256"],
        "parent_input_locks": True,
        "network_access_control": "not_enforced",
        "authorized_root": str(context["authorized_root"]),
        "adapter_runtime_root": str(staging / ".adapter-runtime"),
        "tracks": tracks, "omitted": omitted,
    }


def _guide(*, build_id: str, canvas: Mapping[str, int], fps: int) -> str:
    ratio = "9:16" if canvas["height"] > canvas["width"] else "16:9"
    return f"""# 剪映草稿候选：中文手动复制与微调说明

本目录是视频工程内生成的**全新剪映草稿候选**，不是剪映 APP 的草稿目录。
编排流程没有接收、查找或请求访问本机剪映的“草稿位置”，也没有启动剪映。
第三方适配器进程没有接受操作系统级文件访问审计，因此收据会把草稿目录访问证据
如实标记为 `unknown`；这不能证明第三方进程绝对没有访问其他本机路径。

## 当前候选

- 构建 ID：`{build_id}`
- 草稿文件夹：`native-draft/`
- 建议画布：`{canvas['width']} × {canvas['height']}`（{ratio}）
- 帧率：`{fps} fps`
- 当前状态：已生成、尚未在剪映中打开验证

## 手动复制到剪映

1. 先关闭剪映专业版，避免剪映正在写草稿。
2. 在剪映专业版的设置中查看**你当前电脑实际使用的草稿位置**。不同电脑、不同账号或以后修改设置时，位置都可能不同，本工程不会把它写死。
3. 回到本目录，完整复制 `native-draft` 文件夹；不要只复制其中两个 JSON 文件。
4. 把这整个文件夹粘贴为剪映当前草稿位置下的一个**全新子目录**。若目标已有同名目录，立即停止；不要合并、覆盖或删除已有草稿，可给复制件换一个从未使用过的新目录名。
5. 启动剪映，在本地草稿列表中寻找新草稿。若没有出现，先退出剪映，再确认复制的是整个目录且层级没有多套一层。
6. 打开后先检查画布、帧率、缺失素材和首尾同步，不要直接覆盖原始视频工程。

![空白工程与素材入口](guide-assets/01-empty-project.png)

![项目画布与帧率设置参考](guide-assets/04-project-settings.png)

## 建议完成的五项微调验证

1. 修改一条字幕，并尝试拆分或合并语义句；重点词样式可能因适配器能力而降级。
2. 移动、裁短或隐藏一个事件动效，确认主画面不受影响。
3. 静音一个事件音效，确认对白仍然存在。

![音频轨与音频面板参考](guide-assets/03-audio-panel.png)
4. 若本候选包含独立 IP/产品辅助图，移动或隐藏一次；缺失时记录为 unavailable，不能伪装通过。
5. 修改片尾 CTA 原生文字，并隐藏一个独立片尾元素；缺失时同样如实记录。

## 重要边界

- `native-draft/` 可以作为人工微调起点，但尚未证明与你当前剪映版本兼容。
- 这是仅限本机使用的 linked 草稿，JSON 内含素材的绝对路径；不要把整个
  候选目录原样上传、公开分享或发送给不受信任的人。
- `00-reference` 等编辑中性交接资产仍是兜底；原自动成片不会因草稿失败而丢失。
- 事件动效是已渲染分层素材，可调整位置、时长、显隐和透明度；内部节点与复杂缓动仍需回到 HyperFrames 工程。
- ASS 只作样式参考。SRT 字幕文字和时间已映射为原生文本片段，逐词品牌色/放大可能需要在剪映中复刻。
- 完成人工打开、五项修改和短片导出前，不得把本候选标为“剪映兼容已通过”。
"""


def _copy_guide_assets(staging: Path) -> None:
    for name in (
        "01-empty-project.png", "02-import-subtitles.png",
        "03-audio-panel.png", "04-project-settings.png",
    ):
        source = GUIDE_SCREENSHOT_ROOT / name
        if not source.is_file():
            raise JianyingNativeDraftError(f"Chinese guide screenshot is missing: {name}")
        atomic_replace_file(
            source, safe_generated_target(staging, Path("guide-assets") / name)
        )


def _write_manifest(
    context: Mapping[str, Any], *, staging: Path, build_id: str,
    max_package_gib: float,
) -> Path:
    plan = context["plan"]
    manifest = {
        "schema_version": 1, "kind": "jianying_native_project_local_candidate",
        "status": "generated_awaiting_manual_canary", "build_id": build_id,
        "profile": plan["profile"], "asset_mode": plan["asset_mode"],
        "plan": _relative_file_ref(
            context["plan_path"], staging, context["authorized_root"]
        ),
        "adapter_wheel": _relative_file_ref(
            context["adapter_wheel"], staging, context["authorized_root"]
        ),
        "adapter_python": _relative_file_ref(
            context["adapter_python"], staging, context["authorized_root"]
        ),
        "adapter_runtime": {
            "runtime_lock": context["adapter_runtime_lock"],
            "lock_module_sha256": context["adapter_lock_sha256"],
            "runner_sha256": context["adapter_runner_sha256"],
            "locked_io_sha256": context["adapter_locked_io_sha256"],
            "dependency_wheels": dict(ADAPTER_DEPENDENCY_LOCK),
        },
        "projection_report": _package_file_ref(
            staging / "projection-report.json", staging
        ),
        "native_draft": {"path": "native-draft"},
        "inventory": _inventory(staging, root_already_locked=True),
        "safety": {
            "project_local_generation": True, "new_isolated_draft": True,
            "editor_store_path_supplied": False,
            "editor_store_operation_requested": False,
            "editor_store_access_control": "not_enforced",
            "editor_store_access_evidence": "unknown",
            "editor_launched_by_orchestrator": False,
            "network_access_control": "not_enforced",
            "network_use_evidence": "unknown", "secret_required": False,
        },
        "privacy": {
            "contains_absolute_linked_media_paths": True,
            "local_private_artifact": True,
            "safe_to_upload_as_is": False,
        },
        "fallbacks": {
            "automatic_master": _relative_file_ref(
                Path(plan["authorities"]["automatic_master"]["path"]),
                staging, context["authorized_root"],
            ),
            "standard_editable_delivery": _relative_file_ref(
                context["standard_editable_delivery"], staging,
                context["authorized_root"],
            ),
            "nle_package": _relative_file_ref(
                Path(plan["authorities"]["nle_package"]["path"]),
                staging, context["authorized_root"],
            ),
        },
        "compatibility": {
            "real_jianying_compatibility_claimed": False,
            "human_open_edit_export_required": True,
            "production_default": False,
        },
        "max_package_gib": float(max_package_gib),
    }
    manifest["integrity_sha256"] = _canonical_hash(
        manifest, omit="integrity_sha256"
    )
    path = safe_generated_target(staging, Path("candidate-manifest.json"))
    _exclusive_write_json(path, manifest)
    return path


def _resolve_package_ref(value: Any, *, package_root: Path) -> Path | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return None
    path = Path(value["path"])
    return (package_root / path).resolve() if not path.is_absolute() else path.resolve()


def _read_json_snapshot(path: Path, *, expected_sha256: str) -> Mapping[str, Any]:
    try:
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise JianyingNativeDraftError("JSON authority changed during snapshot read")
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise JianyingNativeDraftError("JSON authority snapshot is unreadable") from error
    if not isinstance(value, Mapping):
        raise JianyingNativeDraftError("JSON authority snapshot must be an object")
    return value


@contextmanager
def _director_binding_lock(
    *, status_path: Path, handoff_path: Path, authorized_root: Path,
):
    root = status_path.parent
    if handoff_path.parent.parent != root:
        raise JianyingNativeDraftError(
            "Director status and manual-copy handoff do not share one binding root"
        )
    lock_path = _lexical_child(
        root / ".project-local-candidate-binding.lock",
        authorized_root, label="Director Jianying binding lock",
    )
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"1")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise JianyingNativeDraftError(
                "another Director Jianying binding is already active"
            ) from error
        yield
    finally:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)


def _native_projection_errors(
    *, plan: Mapping[str, Any], content: Mapping[str, Any],
    report: Mapping[str, Any], expected_canvas: Mapping[str, int],
) -> list[str]:
    errors: list[str] = []
    tracks = content.get("tracks")
    materials = content.get("materials")
    if not isinstance(tracks, list) or not isinstance(materials, Mapping):
        return ["native draft content shape is invalid"]
    if content.get("fps") != int(plan["timebase"]["numerator"]) // int(
        plan["timebase"]["denominator"]
    ):
        errors.append("native draft frame rate differs from the canonical plan")
    native_canvas = content.get("canvas_config")
    if not isinstance(native_canvas, Mapping) or any(
        native_canvas.get(key) != expected_canvas.get(key)
        for key in ("width", "height")
    ):
        errors.append("native draft canvas differs from the layer timeline")
    native_tracks = {
        row.get("name"): row for row in tracks
        if isinstance(row, Mapping) and isinstance(row.get("name"), str)
    }
    valid_track_rows = [
        row for row in tracks
        if isinstance(row, Mapping) and isinstance(row.get("name"), str)
    ]
    if len(valid_track_rows) != len(tracks):
        errors.append("native draft track inventory shape is invalid")
    if len(native_tracks) != len(valid_track_rows):
        errors.append("native draft contains duplicate track names")
    expected_track_ids = {
        track["track_id"] for track in plan["tracks"]
        if track["kind"] != "reference"
    }
    if set(native_tracks) != expected_track_ids:
        errors.append("native track inventory differs from the source plan")
    projected = report.get("projected")
    if not isinstance(projected, list):
        return ["native projection report inventory is invalid"]
    projected_by_clip = {
        row.get("clip_id"): row for row in projected
        if isinstance(row, Mapping) and isinstance(row.get("clip_id"), str)
    }
    valid_projected_rows = [
        row for row in projected
        if isinstance(row, Mapping) and isinstance(row.get("clip_id"), str)
    ]
    if len(valid_projected_rows) != len(projected):
        errors.append("native projection report row shape is invalid")
    if len(projected_by_clip) != len(valid_projected_rows):
        errors.append("native projection report contains duplicate clip IDs")
    material_by_id: dict[str, Mapping[str, Any]] = {}
    material_ids: list[str] = []
    for key in ("videos", "audios", "texts"):
        bucket = materials.get(key)
        if not isinstance(bucket, list):
            errors.append(f"native draft material bucket shape is invalid: {key}")
            continue
        for row in bucket:
            if isinstance(row, Mapping) and isinstance(row.get("id"), str):
                material_by_id[row["id"]] = row
                material_ids.append(row["id"])
            else:
                errors.append(f"native draft material row shape is invalid: {key}")
    if len(material_by_id) != len(material_ids):
        errors.append("native draft contains duplicate primary material IDs")
    numerator = int(plan["timebase"]["numerator"])
    denominator = int(plan["timebase"]["denominator"])
    expected_ids: set[str] = set()
    for track in plan["tracks"]:
        if track["kind"] == "reference":
            continue
        native_track = native_tracks.get(track["track_id"])
        if not isinstance(native_track, Mapping) or native_track.get("type") != track["kind"]:
            errors.append(f"native track missing or mismatched: {track['track_id']}")
            continue
        raw_segments = native_track.get("segments")
        if not isinstance(raw_segments, list):
            errors.append(f"native segment inventory shape is invalid for {track['track_id']}")
            continue
        segment_rows = [
            row for row in raw_segments
            if isinstance(row, Mapping) and isinstance(row.get("id"), str)
        ]
        segments = {
            row.get("id"): row for row in raw_segments
            if isinstance(row, Mapping) and isinstance(row.get("id"), str)
        }
        expected_segment_ids = {
            projected_by_clip[clip["clip_id"]].get("segment_id")
            for clip in track["clips"]
            if isinstance(projected_by_clip.get(clip["clip_id"]), Mapping)
        }
        if len(segments) != len(segment_rows) or set(segments) != expected_segment_ids:
            errors.append(f"native segment inventory differs for {track['track_id']}")
        for clip in track["clips"]:
            clip_id = clip["clip_id"]
            expected_ids.add(clip_id)
            projection = projected_by_clip.get(clip_id)
            if not isinstance(projection, Mapping) or (
                set(projection) != {"clip_id", "track_id", "segment_id", "status"}
                or projection.get("track_id") != track["track_id"]
                or projection.get("status") != "projected"
            ):
                errors.append(f"native projection binding differs for {clip_id}")
            segment = segments.get(projection.get("segment_id")) if isinstance(projection, Mapping) else None
            if not isinstance(segment, Mapping):
                errors.append(f"native segment is missing for {clip_id}")
                continue
            target = segment.get("target_timerange")
            expected_target = {
                "start": _frame_to_us(
                    int(clip["start_frame"]), numerator=numerator, denominator=denominator
                ),
                "duration": (
                    _frame_to_us(
                        int(clip["start_frame"]) + int(clip["duration_frames"]),
                        numerator=numerator, denominator=denominator,
                    )
                    - _frame_to_us(
                        int(clip["start_frame"]),
                        numerator=numerator, denominator=denominator,
                    )
                ),
            }
            if target != expected_target:
                errors.append(f"native timeline differs for {clip_id}")
            material = material_by_id.get(segment.get("material_id"))
            if not isinstance(material, Mapping):
                errors.append(f"native material is missing for {clip_id}")
                continue
            if track["kind"] in {"video", "audio"}:
                if Path(str(material.get("path"))).resolve() != Path(
                    clip["source"]["path"]
                ).resolve():
                    errors.append(f"native media path differs for {clip_id}")
                source = segment.get("source_timerange")
                source_start = int(clip["source_start_frame"])
                expected_source = {
                    "start": _frame_to_us(
                        source_start, numerator=numerator, denominator=denominator
                    ),
                    "duration": (
                        _frame_to_us(
                            source_start + int(clip["duration_frames"]),
                            numerator=numerator, denominator=denominator,
                        )
                        - _frame_to_us(
                            source_start, numerator=numerator, denominator=denominator,
                        )
                    ),
                }
                if source != expected_source:
                    errors.append(f"native source timeline differs for {clip_id}")
                if track["kind"] == "video":
                    transform = clip["payload"].get("transform") or {}
                    native_clip = segment.get("clip")
                    native_scale = native_clip.get("scale") if isinstance(native_clip, Mapping) else None
                    native_transform = native_clip.get("transform") if isinstance(native_clip, Mapping) else None
                    actual_transform = (
                        native_clip.get("alpha"), native_clip.get("rotation"),
                        native_scale.get("x") if isinstance(native_scale, Mapping) else None,
                        native_scale.get("y") if isinstance(native_scale, Mapping) else None,
                        native_transform.get("x") if isinstance(native_transform, Mapping) else None,
                        native_transform.get("y") if isinstance(native_transform, Mapping) else None,
                    ) if isinstance(native_clip, Mapping) else ()
                    expected_transform = (
                        float(transform.get("opacity", 1.0)),
                        float(transform.get("rotation_degrees", 0.0)),
                        float(transform.get("scale_x", 1.0)),
                        float(transform.get("scale_y", 1.0)),
                        float(transform.get("x", 0.0)),
                        float(transform.get("y", 0.0)),
                    )
                    if len(actual_transform) != 6 or any(
                        isinstance(actual, bool)
                        or not isinstance(actual, (int, float))
                        or not math.isfinite(float(actual))
                        or abs(float(actual) - expected) > 1e-6
                        for actual, expected in zip(actual_transform, expected_transform)
                    ):
                        errors.append(f"native visual transform differs for {clip_id}")
                else:
                    volume = segment.get("volume")
                    gain_db = float(clip["payload"].get("gain_db", 0.0))
                    if (
                        not isinstance(volume, (int, float)) or isinstance(volume, bool)
                        or not math.isfinite(float(volume)) or float(volume) <= 0
                        or abs(20 * math.log10(float(volume)) - gain_db) > 0.1
                    ):
                        errors.append(f"native audio gain differs for {clip_id}")
            elif track["kind"] == "text":
                try:
                    native_text_payload = json.loads(str(material.get("content")))
                    if not isinstance(native_text_payload, Mapping):
                        raise TypeError("native text payload must be an object")
                    native_text = native_text_payload.get("text")
                except (TypeError, ValueError, json.JSONDecodeError):
                    native_text_payload = {}
                    native_text = None
                expected_text = (
                    clip["payload"].get("text") if clip["role"] == "caption"
                    else clip["payload"].get("native_text")
                )
                if native_text != expected_text:
                    errors.append(f"native text differs for {clip_id}")
                base_style = clip["payload"].get("base_style")
                base_style = base_style if isinstance(base_style, Mapping) else {}
                size_value = (
                    base_style.get("font_size") or base_style.get("font_size_px")
                    or base_style.get("size") or 8.0
                )
                try:
                    expected_size = float(size_value)
                except (TypeError, ValueError):
                    expected_size = 8.0
                if not math.isfinite(expected_size) or expected_size <= 0:
                    expected_size = 8.0
                expected_color = base_style.get("base_color") or base_style.get("color") or "#FFFFFF"
                try:
                    expected_rgb = [
                        int(str(expected_color)[index:index + 2], 16) / 255
                        for index in (1, 3, 5)
                    ]
                except (TypeError, ValueError):
                    expected_rgb = [1.0, 1.0, 1.0]
                styles = native_text_payload.get("styles")
                style = styles[0] if isinstance(styles, list) and styles else None
                fill = style.get("fill") if isinstance(style, Mapping) else None
                fill_content = fill.get("content") if isinstance(fill, Mapping) else None
                solid = fill_content.get("solid") if isinstance(fill_content, Mapping) else None
                actual_rgb = solid.get("color") if isinstance(solid, Mapping) else None
                if (
                    not isinstance(style, Mapping)
                    or isinstance(style.get("size"), bool)
                    or not isinstance(style.get("size"), (int, float))
                    or not math.isfinite(float(style["size"]))
                    or abs(float(style["size"]) - expected_size) > 1e-6
                    or style.get("bold") is not bool(base_style.get("bold", False))
                    or not isinstance(actual_rgb, list) or len(actual_rgb) != 3
                    or any(
                        isinstance(actual, bool)
                        or not isinstance(actual, (int, float))
                        or not math.isfinite(float(actual))
                        or abs(float(actual) - expected) > 1e-6
                        for actual, expected in zip(actual_rgb, expected_rgb)
                    )
                ):
                    errors.append(f"native base text style differs for {clip_id}")
    if set(projected_by_clip) != expected_ids:
        errors.append("native projected clip inventory differs from the source plan")
    used_material_ids = {
        segment.get("material_id") for track in tracks if isinstance(track, Mapping)
        for segment in (
            track.get("segments") if isinstance(track.get("segments"), list) else []
        ) if isinstance(segment, Mapping)
        and isinstance(segment.get("material_id"), str)
    }
    if set(material_by_id) != used_material_ids:
        errors.append("native primary material inventory differs from projected segments")
    return errors


def validate_project_local_candidate(
    manifest_path: Path, *, authorized_root: Path,
) -> list[str]:
    authorized_root = Path(os.path.abspath(authorized_root))
    try:
        manifest_path = _lexical_child(
            manifest_path, authorized_root, label="project-local candidate manifest"
        )
        package_root = _lexical_child(
            manifest_path.parent, authorized_root, label="project-local candidate"
        )
    except JianyingNativeDraftError as error:
        return [str(error)]
    if not package_root.is_dir() or _tree_has_redirection(package_root):
        return ["project-local candidate tree is missing or redirected"]
    try:
        package_parent_identity = _locked_identity(package_root.parent)
        package_identity = _locked_identity(package_root)
        with ExitStack() as locks:
            locks.enter_context(_locked_directory(
                package_root.parent, package_parent_identity
            ))
            locks.enter_context(_locked_directory(package_root, package_identity))
            manifest, _manifest_identity, _manifest_sha256 = _read_stable_json(
                manifest_path, label="project-local candidate manifest"
            )
            return _validate_project_local_candidate_locked(
                manifest_path=manifest_path, authorized_root=authorized_root,
                package_root=package_root, manifest=manifest,
            )
    except (OSError, JianyingNativeDraftError):
        return ["project-local candidate manifest is unreadable or unstable"]


def _validate_project_local_candidate_locked(
    *, manifest_path: Path, authorized_root: Path, package_root: Path,
    manifest: Any,
) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version", "kind", "status", "build_id", "profile", "asset_mode",
        "plan", "adapter_wheel", "adapter_python", "adapter_runtime",
        "projection_report",
        "native_draft", "inventory",
        "safety", "privacy", "fallbacks", "compatibility", "max_package_gib",
        "integrity_sha256",
    }
    if not isinstance(manifest, Mapping) or set(manifest) != required:
        return ["project-local candidate manifest shape is invalid"]
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "jianying_native_project_local_candidate"
        or manifest.get("status") != "generated_awaiting_manual_canary"
    ):
        errors.append("project-local candidate identity or status is invalid")
    build_id = manifest.get("build_id")
    if (
        not isinstance(build_id, str) or not _DRAFT_IDENTIFIER.fullmatch(build_id)
        or package_root.name != build_id
        and not package_root.name.startswith(f".{build_id}.staging-")
    ):
        errors.append("project-local candidate build identity is invalid")
    budget = manifest.get("max_package_gib")
    budget_valid = not (
        isinstance(budget, bool) or not isinstance(budget, (int, float))
        or not math.isfinite(float(budget)) or not 0 < float(budget) <= 64
    )
    if not budget_valid:
        errors.append("project-local candidate size budget is invalid")
    try:
        if manifest.get("integrity_sha256") != _canonical_hash(
            manifest, omit="integrity_sha256"
        ):
            errors.append("project-local candidate integrity is stale")
    except JianyingNativeDraftError as error:
        errors.append(str(error))
    expected_safety = {
        "project_local_generation": True, "new_isolated_draft": True,
        "editor_store_path_supplied": False,
        "editor_store_operation_requested": False,
        "editor_store_access_control": "not_enforced",
        "editor_store_access_evidence": "unknown",
        "editor_launched_by_orchestrator": False,
        "network_access_control": "not_enforced",
        "network_use_evidence": "unknown", "secret_required": False,
    }
    if manifest.get("safety") != expected_safety:
        errors.append("project-local candidate safety boundary is invalid")
    if manifest.get("privacy") != {
        "contains_absolute_linked_media_paths": True,
        "local_private_artifact": True,
        "safe_to_upload_as_is": False,
    }:
        errors.append("project-local candidate privacy boundary is invalid")
    compatibility = manifest.get("compatibility")
    if compatibility != {
        "real_jianying_compatibility_claimed": False,
        "human_open_edit_export_required": True, "production_default": False,
    }:
        errors.append("project-local candidate compatibility boundary is invalid")
    inventory = manifest.get("inventory")
    if not isinstance(inventory, list) or any(
        not isinstance(row, Mapping) for row in inventory
    ):
        errors.append("project-local candidate inventory shape is invalid")
        inventory = []
    if manifest.get("native_draft") != {"path": "native-draft"}:
        errors.append("project-local native draft reference is invalid")
    expected_runtime = {
        "runtime_lock": dict(ADAPTER_RUNTIME_LOCK),
        "lock_module_sha256": sha256_file(ADAPTER_LOCK_PATH),
        "runner_sha256": sha256_file(RUNNER_PATH),
        "locked_io_sha256": sha256_file(LOCKED_IO_PATH),
        "dependency_wheels": dict(ADAPTER_DEPENDENCY_LOCK),
    }
    if manifest.get("adapter_runtime") != expected_runtime:
        errors.append("project-local adapter runtime receipt differs from the frozen lock")
    try:
        actual = {
            row["path"]: {
                "sha256": row["sha256"], "size_bytes": row["size_bytes"],
            }
            for row in _inventory(package_root, root_already_locked=True)
        }
    except JianyingNativeDraftError as error:
        return [str(error)]
    declared = {
        row.get("path"): {"sha256": row.get("sha256"), "size_bytes": row.get("size_bytes")}
        for row in inventory
    }
    if len(declared) != len(inventory) or actual != declared:
        errors.append("project-local candidate inventory is stale")
    elif budget_valid and sum(
        int(row["size_bytes"]) for row in actual.values()
    ) > int(float(budget) * 1024 ** 3):
        errors.append("project-local candidate exceeds its declared size budget")
    # Do not trust any external reference unless the manifest itself and the
    # package-local inventory have passed their fail-closed gates.
    if errors:
        return errors
    references: dict[str, Any] = {
        "plan": manifest.get("plan"),
        "adapter wheel": manifest.get("adapter_wheel"),
        "adapter Python": manifest.get("adapter_python"),
        "projection report": manifest.get("projection_report"),
    }
    fallbacks = manifest.get("fallbacks")
    if not isinstance(fallbacks, Mapping) or set(fallbacks) != {
        "automatic_master", "standard_editable_delivery", "nle_package"
    }:
        return ["project-local candidate fallback inventory is invalid"]
    references.update({f"fallback {name}": value for name, value in fallbacks.items()})
    resolved: dict[str, Path] = {}
    reference_errors: list[str] = []
    for label, value in references.items():
        current = _ref_errors(
            value, label=f"project-local {label}", authorized_root=authorized_root,
            base=package_root,
        )
        reference_errors.extend(current)
        if not current:
            path = _resolve_package_ref(value, package_root=package_root)
            if path is None:
                reference_errors.append(f"project-local {label} cannot be resolved")
            else:
                resolved[label] = path
    if reference_errors:
        return reference_errors
    editable_path = resolved["fallback standard_editable_delivery"]
    errors.extend(validate_editable_delivery(editable_path))
    wheel_path = resolved["adapter wheel"]
    if (
        wheel_path.name != "pyjianyingdraft-0.3.0-py3-none-any.whl"
        or sha256_file(wheel_path) != ADAPTER_WHEEL_SHA256
    ):
        errors.append("project-local adapter wheel differs from the frozen lock")
    if errors:
        return errors
    plan_path = resolved["plan"]
    report_path = resolved["projection report"]
    native_root = package_root / "native-draft"
    try:
        plan = read_json(plan_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["project-local source plan is unreadable"]
    plan_errors = validate_draft_plan(plan, authorized_root=authorized_root)
    if plan_errors:
        return plan_errors
    if (
        manifest.get("profile") != plan.get("profile")
        or manifest.get("asset_mode") != plan.get("asset_mode")
    ):
        return ["project-local candidate profile or asset mode differs from the plan"]
    timeline_path = _resolve_package_ref(
        plan["authorities"]["layer_timeline"], package_root=package_root
    )
    try:
        timeline = read_json(timeline_path) if timeline_path else None
        report = read_json(report_path)
        content = read_json(native_root / "draft_content.json")
        read_json(native_root / "draft_meta_info.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return ["project-local native draft, timeline or projection report is unreadable"]
    expected_canvas = timeline.get("canvas") if isinstance(timeline, Mapping) else None
    if not isinstance(expected_canvas, Mapping):
        return ["project-local layer timeline canvas is invalid"]
    if not isinstance(report, Mapping) or (
        report.get("kind") != "jianying_native_projection_report"
        or report.get("status") != "generated_unopened"
        or report.get("adapter_id") != ADAPTER_ID
        or report.get("adapter_version") != ADAPTER_VERSION
        or report.get("source_plan_sha256") != plan.get("plan_sha256")
        or report.get("adapter_artifact_sha256") != ADAPTER_WHEEL_SHA256
        or report.get("adapter_python_sha256") != sha256_file(
            resolved["adapter Python"]
        )
        or report.get("adapter_runtime_lock") != dict(ADAPTER_RUNTIME_LOCK)
        or report.get("adapter_lock_sha256") != sha256_file(ADAPTER_LOCK_PATH)
        or report.get("adapter_locked_io_sha256") != sha256_file(LOCKED_IO_PATH)
        or report.get("adapter_dependencies") != dict(ADAPTER_DEPENDENCY_LOCK)
        or report.get("parent_input_locks") is not True
        or report.get("runner_sha256") != sha256_file(RUNNER_PATH)
        or report.get("third_party_code_executed") is not True
        or report.get("network_access_control") != "not_enforced"
        or report.get("network_use_evidence") != "unknown"
        or report.get("editor_store_path_supplied") is not False
        or report.get("editor_store_operation_requested") is not False
        or report.get("editor_store_access_control") != "not_enforced"
        or report.get("editor_store_access_evidence") != "unknown"
        or report.get("editor_launched_by_orchestrator") is not False
    ):
        errors.append("project-local projection report boundary is invalid")
    elif isinstance(content, Mapping):
        errors.extend(_native_projection_errors(
            plan=plan, content=content, report=report,
            expected_canvas=expected_canvas,
        ))
    else:
        errors.append("project-local native draft content must be an object")
    return errors


def materialize_project_local_candidate(
    *, plan_path: Path, output_root: Path, authorized_root: Path, build_id: str,
    adapter_python: Path, adapter_wheel: Path,
    standard_editable_delivery: Path, max_package_gib: float = 8.0,
) -> dict[str, Any]:
    """Create a new draft candidate below the video project, never in the APP store."""
    if (
        isinstance(max_package_gib, bool) or not isinstance(max_package_gib, (int, float))
        or not math.isfinite(float(max_package_gib)) or not 0 < float(max_package_gib) <= 64
    ):
        raise JianyingNativeDraftError("project-local candidate size budget is invalid")
    context = _load_plan_context(
        plan_path=plan_path, output_root=output_root, authorized_root=authorized_root,
        build_id=build_id, adapter_python=adapter_python,
        adapter_wheel=adapter_wheel,
        standard_editable_delivery=standard_editable_delivery,
    )
    # Keep the unpublished tree beside its final target.  Holding output_root
    # pins the published parent; holding the new tree itself prevents a path
    # exchange during third-party execution.  Promotion then uses the already
    # open tree handle, never a reopened source path.
    staging = context["published_parent"] / f".{build_id}.staging-{uuid.uuid4().hex}"
    staging_identity: tuple[int, int] | None = None
    published = False
    try:
        with ExitStack() as locks:
            locks.enter_context(_locked_directory(
                context["output_root"], context["output_identity"]
            ))
            if (
                _locked_identity(context["staging_parent"])
                != context["staging_parent_identity"]
                or _locked_identity(context["published_parent"])
                != context["published_parent_identity"]
            ):
                raise JianyingNativeDraftError("project-local output tree changed")
            staging.mkdir()
            staging_identity = _locked_identity(staging)
            staging_handle = locks.enter_context(
                _locked_directory(staging, staging_identity)
            )
            locks.enter_context(_locked_directory(
                context["adapter_python"].parent.parent,
                context["adapter_venv_identity"],
            ))
            locks.enter_context(_locked_directory(
                context["adapter_python"].parent,
                context["adapter_scripts_identity"],
            ))
            locks.enter_context(_locked_file(
                context["adapter_python"],
                expected_identity=context["adapter_python_identity"],
                expected_sha256=context["adapter_runtime_lock"]["python_executable_sha256"],
            ))
            locks.enter_context(_locked_file(
                context["adapter_cfg_path"],
                expected_identity=context["adapter_cfg_identity"],
                expected_sha256=context["adapter_runtime_lock"]["pyvenv_cfg_sha256"],
            ))
            locks.enter_context(_locked_directory(
                RUNNER_PATH.parent, context["adapter_toolchain_parent_identity"]
            ))
            for path, identity, expected_sha256 in (
                (RUNNER_PATH, context["adapter_runner_identity"],
                 context["adapter_runner_sha256"]),
                (ADAPTER_LOCK_PATH, context["adapter_lock_identity"],
                 context["adapter_lock_sha256"]),
                (LOCKED_IO_PATH, context["adapter_locked_io_identity"],
                 context["adapter_locked_io_sha256"]),
            ):
                locks.enter_context(_locked_file(
                    path, expected_identity=identity,
                    expected_sha256=expected_sha256,
                ))
            _lock_adapter_inputs(context, locks)
            _assert_generated_tree_safe(
                staging, context["authorized_root"], identity=staging_identity
            )
            request = _adapter_request(context, staging=staging)
            request_path = safe_generated_target(staging, Path(".adapter-request.json"))
            _exclusive_write_json(request_path, request)
            try:
                completed = subprocess.run(
                [str(context["adapter_python"]), "-I", "-S", str(RUNNER_PATH),
                 "--request", str(request_path),
                 "--request-sha256", sha256_file(request_path),
                 "--authorized-root", str(context["authorized_root"])],
                check=False, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300,
                cwd=str(context["authorized_root"]),
                env={
                    key: os.environ[key] for key in (
                        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH"
                    ) if key in os.environ
                } | {
                    "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                },
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise JianyingNativeDraftError("pinned adapter execution failed") from error
            finally:
                request_path.unlink(missing_ok=True)
                runtime = staging / ".adapter-runtime"
                if runtime.is_dir() and not _tree_has_redirection(runtime):
                    shutil.rmtree(runtime)
            if completed.returncode != 0:
                raise JianyingNativeDraftError(
                    f"pinned adapter rejected the candidate (exit {completed.returncode})"
                )
            _assert_generated_tree_safe(
                staging, context["authorized_root"], identity=staging_identity
            )
            _copy_guide_assets(staging)
            _exclusive_write_text(
                safe_generated_target(staging, Path("README-中文.md")),
                _guide(build_id=build_id, canvas=context["canvas"], fps=context["fps"]),
            )
            manifest_path = _write_manifest(
                context, staging=staging, build_id=build_id,
                max_package_gib=float(max_package_gib),
            )
            manifest_snapshot = read_json(manifest_path)
            package_bytes = sum(row["size_bytes"] for row in manifest_snapshot["inventory"])
            if package_bytes > int(float(max_package_gib) * 1024 ** 3):
                raise JianyingNativeDraftError("project-local candidate exceeds size budget")
            if errors := _validate_project_local_candidate_locked(
                manifest_path=manifest_path,
                authorized_root=context["authorized_root"],
                package_root=staging, manifest=manifest_snapshot,
            ):
                raise JianyingNativeDraftError(
                    "project-local candidate is invalid:\n- " + "\n- ".join(errors)
                )
            if (
                _locked_identity(staging) != staging_identity
                or _locked_identity(context["output_root"]) != context["output_identity"]
                or _locked_identity(context["staging_parent"]) != context["staging_parent_identity"]
                or _locked_identity(context["published_parent"]) != context["published_parent_identity"]
                or os.path.lexists(context["target"])
            ):
                raise JianyingNativeDraftError("project-local candidate target changed")
            _rename_locked_directory(
                staging_handle, target_path=context["target"]
            )
            if _locked_identity(context["target"]) != staging_identity:
                raise JianyingNativeDraftError("published candidate identity changed")
            published = True
            published_manifest = context["target"] / "candidate-manifest.json"
            if errors := _validate_project_local_candidate_locked(
                manifest_path=published_manifest,
                authorized_root=context["authorized_root"],
                package_root=context["target"], manifest=manifest_snapshot,
            ):
                raise JianyingNativeDraftError(
                    "published project-local candidate is invalid:\n- " + "\n- ".join(errors)
                )
            return read_json(published_manifest)
    except Exception:
        if staging_identity is not None:
            store_root = context["published_parent"]
            store_identity = context["published_parent_identity"]
            _safe_remove_partial_generated_tree(
                context["target"] if published else staging,
                store_root=store_root, store_identity=store_identity,
                store_parent_identity=context["output_identity"],
                tree_identity=staging_identity,
            )
        raise


def _load_binding_snapshot(
    *, manifest_path: Path, status_path: Path, handoff_path: Path,
    authorized_root: Path,
) -> dict[str, Any]:
    manifest_hash = sha256_file(manifest_path)
    errors = validate_project_local_candidate(
        manifest_path, authorized_root=authorized_root
    )
    if errors or sha256_file(manifest_path) != manifest_hash:
        detail = errors or ["candidate manifest changed during validation"]
        raise JianyingNativeDraftError(
            "cannot bind an invalid project-local candidate:\n- " + "\n- ".join(detail)
        )
    manifest = _read_json_snapshot(manifest_path, expected_sha256=manifest_hash)
    plan_path = _resolve_package_ref(manifest["plan"], package_root=manifest_path.parent)
    if plan_path is None:
        raise JianyingNativeDraftError("candidate source plan cannot be resolved")
    plan = _read_json_snapshot(plan_path, expected_sha256=manifest["plan"]["sha256"])
    status_hash = sha256_file(status_path)
    handoff_hash = sha256_file(handoff_path)
    status = _read_json_snapshot(status_path, expected_sha256=status_hash)
    handoff = _read_json_snapshot(handoff_path, expected_sha256=handoff_hash)
    if any((
        sha256_file(manifest_path) != manifest_hash,
        sha256_file(plan_path) != manifest["plan"]["sha256"],
        sha256_file(status_path) != status_hash,
        sha256_file(handoff_path) != handoff_hash,
    )):
        raise JianyingNativeDraftError(
            "Director Jianying binding authorities changed during validation"
        )
    return {
        "manifest": manifest, "plan": plan, "plan_path": plan_path,
        "status": status, "status_hash": status_hash,
        "handoff": handoff, "handoff_hash": handoff_hash,
    }


def _build_binding_receipts(
    *, snapshot: Mapping[str, Any], manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan, plan_path = snapshot["plan"], snapshot["plan_path"]
    status, handoff = snapshot["status"], snapshot["handoff"]
    draft_id, expected_plan_ref = plan.get("draft_id"), _file_ref(plan_path)
    if (
        status.get("kind") != "jianying_native_draft_status"
        or status.get("draft_id") != draft_id or status.get("plan") != expected_plan_ref
        or handoff.get("kind") != "jianying_manual_copy_handoff"
        or handoff.get("draft_id") != draft_id
        or handoff.get("source_plan") != expected_plan_ref
    ):
        raise JianyingNativeDraftError(
            "Director Jianying binding does not match the source plan"
        )
    candidate_ref = _file_ref(manifest_path)
    next_status = dict(status)
    next_status.update({
        "status": "action_required",
        "maturity": "project_local_candidate_generated",
        "reason": (
            "项目内剪映草稿候选已生成并通过自动合同验证；仍需用户手动复制整个 "
            "native-draft 文件夹并完成剪映打开、编辑和导出 canary。"
        ),
        "native_package_generated": True,
        "candidate": candidate_ref,
        "real_jianying_compatibility_claimed": False,
        "editor_launched": False,
        "draft_store_read": False,
        "draft_store_written": False,
    })
    next_handoff = dict(handoff)
    next_handoff.update({
        "status": "candidate_ready_for_manual_copy",
        "candidate_root": str((manifest_path.parent / "native-draft").resolve()),
        "candidate_manifest": candidate_ref,
        "jianying_draft_store_parameter": None,
        "draft_store_inspected": False,
        "draft_store_written": False,
    })
    return next_status, next_handoff, candidate_ref


def _commit_binding_receipts(
    *, status_path: Path, handoff_path: Path, snapshot: Mapping[str, Any],
    next_status: Mapping[str, Any], next_handoff: Mapping[str, Any],
) -> None:
    if (
        sha256_file(status_path) != snapshot["status_hash"]
        or sha256_file(handoff_path) != snapshot["handoff_hash"]
    ):
        raise JianyingNativeDraftError("Director receipts changed before binding commit")
    journal_path = status_path.parent / "candidate-binding.json"
    journal = {
        "schema_version": 1,
        "kind": "jianying_project_local_candidate_binding",
        "status": "committed_authority_views_may_be_recovered",
        "candidate_manifest": next_status["candidate"],
        "source_plan": next_status["plan"],
        "status_view_sha256": _json_hash(next_status),
        "handoff_view_sha256": _json_hash(next_handoff),
        "status_view": dict(next_status),
        "handoff_view": dict(next_handoff),
    }
    _write_json(journal_path, journal)
    try:
        _write_json(handoff_path, next_handoff)
        _write_json(status_path, next_status)
    except Exception as error:
        raise JianyingNativeDraftError(
            "Director Jianying binding views are incomplete; rerun to recover from candidate-binding.json"
        ) from error


def bind_project_local_candidate(
    *, manifest_path: Path, director_status_path: Path,
    director_handoff_path: Path, authorized_root: Path,
) -> dict[str, Any]:
    """Bind a validated project-local candidate to Director's manual handoff."""
    authorized_root = Path(os.path.abspath(authorized_root))
    manifest_path = _lexical_child(
        manifest_path, authorized_root, label="project-local candidate manifest"
    )
    status_path = _lexical_child(
        director_status_path, authorized_root, label="Director Jianying status"
    )
    handoff_path = _lexical_child(
        director_handoff_path, authorized_root, label="Director manual-copy handoff"
    )
    with _director_binding_lock(
        status_path=status_path, handoff_path=handoff_path,
        authorized_root=authorized_root,
    ):
        snapshot = _load_binding_snapshot(
            manifest_path=manifest_path, status_path=status_path,
            handoff_path=handoff_path, authorized_root=authorized_root,
        )
        next_status, next_handoff, candidate_ref = _build_binding_receipts(
            snapshot=snapshot, manifest_path=manifest_path,
        )
        _commit_binding_receipts(
            status_path=status_path, handoff_path=handoff_path, snapshot=snapshot,
            next_status=next_status, next_handoff=next_handoff,
        )
    return {
        "status": next_status, "handoff": next_handoff,
        "candidate_manifest": candidate_ref,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a project-local Jianying candidate; never access the APP store."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--authorized-root", type=Path, required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--adapter-python", type=Path, required=True)
    parser.add_argument("--adapter-wheel", type=Path, required=True)
    parser.add_argument("--editable-delivery", type=Path, required=True)
    parser.add_argument("--director-status", type=Path)
    parser.add_argument("--director-handoff", type=Path)
    args = parser.parse_args()
    if (args.director_status is None) != (args.director_handoff is None):
        parser.error("--director-status and --director-handoff must be supplied together")
    materialize_project_local_candidate(
        plan_path=args.plan, output_root=args.output_root,
        authorized_root=args.authorized_root, build_id=args.build_id,
        adapter_python=args.adapter_python, adapter_wheel=args.adapter_wheel,
        standard_editable_delivery=args.editable_delivery,
    )
    manifest_path = args.output_root / "published" / args.build_id / "candidate-manifest.json"
    if args.director_status is not None:
        bind_project_local_candidate(
            manifest_path=manifest_path, director_status_path=args.director_status,
            director_handoff_path=args.director_handoff,
            authorized_root=args.authorized_root,
        )
    print(str(manifest_path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
