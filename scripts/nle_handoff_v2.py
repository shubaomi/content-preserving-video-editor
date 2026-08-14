#!/usr/bin/env python3
"""Editor-neutral, layered NLE handoff package v2.

This module deliberately creates media/timeline files rather than private Jianying
drafts.  Editor compatibility remains a named human canary gate.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file
from otio_adapter import edl_to_otio, otio_to_internal, validate_roundtrip
from safe_generated_output import (
    SafeGeneratedOutputError,
    atomic_replace_file,
    atomic_write_text,
    safe_generated_directory,
    safe_generated_target,
)


class NleHandoffError(ValueError):
    """Raised when a handoff package cannot be built truthfully and safely."""


PACKAGE_PROFILE = "jianying_desktop_compatible_v1"
GUIDE_SCREENSHOT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "manual-nle-handoff-v2"
    / "screenshots"
)
PACKAGE_LEVELS = {"reference_only", "balanced", "max_editable"}
EDITABILITY = {
    "native_editable", "media_layer_editable", "source_project_editable",
    "reference_only", "unavailable",
}
ROLES = {
    "automatic_master", "clean_a_roll", "caption_srt", "caption_ass_reference",
    "caption_style_plan", "motion_event", "motion_full_duration", "ip_source",
    "ip_rendered", "dialogue_stem", "bgm_stem", "sfx_grouped", "sfx_event",
    "outro_background", "outro_overlay", "outro_icon", "outro_copy",
    "outro_reference", "cover", "hyperframes_project", "editorial_authority",
    "evidence",
}

_DESTINATIONS: dict[str, tuple[str, str, str, str]] = {
    "automatic_master": ("00-reference/automatic-master", "reference_only", "automatic reference master", "director final_compose"),
    "clean_a_roll": ("01-base/clean-a-roll", "reference_only", "clean speech-first base", "video-use output timeline"),
    "dialogue_stem": ("01-base/dialogue", "reference_only", "editable dialogue stem candidate", "current audio plan"),
    "caption_srt": ("02-captions/master", "reference_only", "editable UTF-8 subtitle candidate", "video-use master.srt"),
    "caption_ass_reference": ("02-captions/master-reference", "reference_only", "semantic caption appearance reference", "caption treatment output"),
    "caption_style_plan": ("02-captions/caption-emphasis-plan", "reference_only", "caption emphasis recreation plan", "caption treatment plan"),
    "motion_full_duration": ("03-motion/all-motion-overlay", "reference_only", "zero-origin motion overlay candidate", "HyperFrames alpha render"),
    "ip_source": ("04-ip-assets/sources/ip-source", "reference_only", "authorized personal-IP source", "portrait brand asset manifest"),
    "ip_rendered": ("04-ip-assets/rendered/ip-rendered", "reference_only", "rendered personal-IP layer candidate", "HyperFrames portrait render"),
    "bgm_stem": ("05-audio/bgm", "reference_only", "editable background music stem candidate", "current audio plan"),
    "sfx_grouped": ("05-audio/sfx-grouped", "reference_only", "editable grouped sound-effects stem candidate", "current audio plan"),
    "outro_background": ("06-outro/background", "reference_only", "modular outro background candidate", "outro module"),
    "outro_overlay": ("06-outro/overlay-text-free", "reference_only", "text-free modular CTA overlay candidate", "outro module"),
    "outro_copy": ("06-outro/copy", "reference_only", "editable CTA copy instructions", "outro module"),
    "outro_reference": ("06-outro/reference-composite", "reference_only", "approved outro appearance", "outro module"),
    "cover": ("07-cover/cover", "reference_only", "approved cover", "cover workflow"),
    "motion_event": ("03-motion/events", "reference_only", "event-local motion overlay candidate", "HyperFrames event render"),
    "sfx_event": ("05-audio/sfx-events", "reference_only", "event-local sound effect candidate", "current audio plan cue"),
    "outro_icon": ("06-outro/icons", "reference_only", "editable CTA icon candidate", "outro module"),
    "editorial_authority": ("09-source-project", "reference_only", "current editorial/source-project authority", "Director current artifact"),
    "evidence": ("10-evidence/source-evidence", "reference_only", "current QA evidence", "Director current evidence"),
}

_REPEATED_ROLES = {"motion_event", "sfx_event", "outro_icon", "editorial_authority", "evidence"}


def _stable_hash(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    value.pop("integrity_sha256", None)
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _finite_number(value: Any, *, positive: bool = False, nonnegative: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    if not math.isfinite(number):
        return False
    if positive and number <= 0:
        return False
    if nonnegative and number < 0:
        return False
    return True


def _is_redirected(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(os.path, "isjunction", lambda _path: False)(path))


def _file_ref(path: Path, *, relative_to: Path | None = None) -> dict[str, str]:
    path = path.resolve()
    rendered = str(path.relative_to(relative_to.resolve())).replace("\\", "/") if relative_to else str(path)
    return {"path": rendered, "sha256": sha256_file(path)}


def _resolve_ref(value: Any, root: Path, *, external: bool = False) -> Path | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return None
    path = Path(value["path"])
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not external and not path.is_relative_to(root.resolve()):
        return None
    return path


def _ref_errors(value: Any, root: Path, label: str, *, external: bool = False) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} file reference must be an object"]
    path = _resolve_ref(value, root, external=external)
    if path is None or not path.is_file():
        return [f"{label} file reference is missing or outside the package"]
    digest = value.get("sha256")
    if not isinstance(digest, str) or digest != sha256_file(path):
        return [f"{label} file reference is stale"]
    return []


def validate_layer_asset(row: Any, *, package_root: Path) -> list[str]:
    if not isinstance(row, Mapping):
        return ["NLE layer asset must be an object"]
    errors: list[str] = []
    asset_id = row.get("asset_id")
    if row.get("schema_version") != 2:
        errors.append("NLE layer asset schema_version must be 2")
    if not isinstance(asset_id, str) or not asset_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for ch in asset_id):
        errors.append("NLE layer asset_id is invalid")
    if row.get("role") not in ROLES:
        errors.append("NLE layer role is invalid")
    if row.get("editability_class") not in EDITABILITY:
        errors.append("NLE layer editability_class is invalid")
    if not isinstance(row.get("purpose"), str) or not row["purpose"].strip():
        errors.append("NLE layer purpose is missing")
    if not isinstance(row.get("provenance"), str) or not row["provenance"].strip():
        errors.append("NLE layer provenance is missing")
    if row.get("rights_status") not in {
        "project_authorized", "redistribution_authorized", "reference_only", "unavailable",
    }:
        errors.append("NLE layer rights_status is invalid")
    status = row.get("status")
    if status == "unavailable":
        if any(row.get(key) is not None for key in ("path", "sha256", "size_bytes")):
            errors.append("unavailable NLE layer cannot declare path, hash, or size")
        if row.get("editability_class") != "unavailable" or row.get("rights_status") != "unavailable":
            errors.append("unavailable NLE layer must use unavailable editability and rights")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            errors.append("unavailable NLE layer requires a reason")
        return errors
    if status != "available":
        errors.append("NLE layer status is invalid")
        return errors
    path_value = row.get("path")
    if not isinstance(path_value, str) or not path_value:
        errors.append("available NLE layer path is missing")
        return errors
    path = (package_root / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value).resolve()
    if not path.is_relative_to(package_root.resolve()) or not path.is_file():
        errors.append("available NLE layer path is missing or outside package")
    else:
        if row.get("sha256") != sha256_file(path):
            errors.append("available NLE layer hash is stale")
        size = row.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size != path.stat().st_size:
            errors.append("available NLE layer size is stale")
    timeline = row.get("timeline")
    if timeline is not None:
        if not isinstance(timeline, Mapping):
            errors.append("NLE layer timeline must be an object")
        else:
            start, end, rate = (timeline.get("start_seconds"), timeline.get("end_seconds"), timeline.get("frame_rate"))
            if not _finite_number(start, nonnegative=True) or not _finite_number(end, positive=True) or not _finite_number(rate, positive=True):
                errors.append("NLE layer timeline values must be finite")
            elif float(end) <= float(start):
                errors.append("NLE layer timeline range is invalid")
    video = row.get("video")
    if video is not None:
        if not isinstance(video, Mapping):
            errors.append("NLE video metadata must be an object")
        else:
            for key in ("width", "height"):
                value = video.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    errors.append(f"NLE video {key} is invalid")
            if video.get("alpha_status") == "verified" and path.suffix.lower() == ".mp4":
                errors.append("standard MP4 cannot be labeled as verified alpha")
    audio = row.get("audio")
    if audio is not None:
        if not isinstance(audio, Mapping):
            errors.append("NLE audio metadata must be an object")
        elif audio.get("sample_rate") != 48000 or not _finite_number(audio.get("duration_seconds"), positive=True):
            errors.append("NLE audio must be finite-duration 48 kHz PCM evidence")
    if row.get("role") in {"motion_event", "sfx_event"}:
        if not isinstance(row.get("semantic_event_id"), str) or not row["semantic_event_id"]:
            errors.append("event-local NLE layer requires semantic_event_id")
        if not isinstance(timeline, Mapping):
            errors.append("event-local NLE layer requires exact timeline placement")
    return errors


def validate_layer_timeline(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["NLE layer timeline must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != 2 or payload.get("authority") != "video-use-output-timeline":
        errors.append("NLE layer timeline authority is invalid")
    if payload.get("origin_seconds") != 0 or isinstance(payload.get("origin_seconds"), bool):
        errors.append("NLE layer timeline origin must be numeric zero")
    duration = payload.get("duration_seconds")
    rate = payload.get("frame_rate")
    if not _finite_number(duration, positive=True) or not _finite_number(rate, positive=True):
        errors.append("NLE layer timeline duration/rate must be finite and positive")
    canvas = payload.get("canvas")
    if not isinstance(canvas, Mapping) or any(
        isinstance(canvas.get(key), bool) or not isinstance(canvas.get(key), int) or canvas.get(key) < 1
        for key in ("width", "height")
    ):
        errors.append("NLE layer timeline canvas is invalid")
    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("NLE layer timeline requires tracks")
        return errors
    track_ids: set[str] = set()
    clip_ids: set[str] = set()
    for track in tracks:
        if not isinstance(track, Mapping):
            errors.append("NLE track must be an object")
            continue
        track_id = track.get("track_id")
        if not isinstance(track_id, str) or not track_id or track_id in track_ids:
            errors.append("NLE track ID is missing or duplicate")
        else:
            track_ids.add(track_id)
        clips = track.get("clips")
        if not isinstance(clips, list):
            errors.append("NLE track clips must be a list")
            continue
        for clip in clips:
            if not isinstance(clip, Mapping):
                errors.append("NLE clip must be an object")
                continue
            clip_id = clip.get("clip_id")
            if not isinstance(clip_id, str) or not clip_id or clip_id in clip_ids:
                errors.append("NLE clip ID is missing or duplicate")
            else:
                clip_ids.add(clip_id)
            values = [clip.get(key) for key in ("timeline_start", "timeline_end", "source_start", "source_end")]
            if not all(_finite_number(value, nonnegative=True) for value in values):
                errors.append("NLE clip range values must be finite")
            elif float(values[1]) <= float(values[0]) or float(values[3]) <= float(values[2]):
                errors.append("NLE clip range is invalid")
            elif _finite_number(duration, positive=True) and float(values[1]) > float(duration) + 1e-6:
                errors.append("NLE clip exceeds timeline duration")
    markers = payload.get("markers")
    if not isinstance(markers, list):
        errors.append("NLE timeline markers must be a list")
    return errors


def validate_compatibility_report(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["NLE compatibility report must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != 2 or payload.get("package_profile") != PACKAGE_PROFILE:
        errors.append("NLE compatibility report identity is invalid")
    if payload.get("status") not in {"pending", "pass", "failed", "stale"}:
        errors.append("NLE compatibility report status is invalid")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, Mapping):
        errors.append("NLE compatibility capabilities must be an object")
    else:
        for key in ("native_draft", "api", "cli", "headless_render"):
            if capabilities.get(key) is not False:
                errors.append(f"NLE compatibility cannot claim {key.replace('_', ' ')}")
        if not isinstance(capabilities.get("srt_import"), bool):
            errors.append("NLE compatibility srt_import must be boolean")
    rows = payload.get("format_results")
    if not isinstance(rows, list) or not rows:
        errors.append("NLE compatibility requires format results")
    else:
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("format_id"), str):
                errors.append("NLE compatibility format result is malformed")
    canary = payload.get("human_canary")
    if not isinstance(canary, Mapping) or canary.get("actor") != "HongRun" or not isinstance(canary.get("tasks"), list) or len(canary["tasks"]) < 5:
        errors.append("NLE compatibility requires the HongRun five-task human canary")
    if payload.get("status") == "pass":
        if not isinstance(canary, Mapping) or canary.get("status") != "pass" or any(
            not isinstance(row, Mapping) or row.get("status") != "pass"
            for row in (canary.get("tasks") or [])
        ):
            errors.append("NLE compatibility pass requires all five HongRun tasks to pass")
        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping) or row.get("imported") is not True
            for row in rows
        ):
            errors.append("NLE compatibility pass requires every declared format to import")
    return errors


def _copy_asset(
    source: Path, staging: Path, role: str, *, asset_id: str | None = None,
    semantic_event_id: str | None = None, render_event_id: str | None = None,
    timeline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    if not source.is_file():
        raise NleHandoffError(f"NLE asset is missing: {source}")
    stem, editability, purpose, provenance = _DESTINATIONS[role]
    suffix = source.suffix.lower() or ".bin"
    safe_id = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in (asset_id or source.stem)).strip(".-")
    safe_id = safe_id or hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:16]
    destination = Path(stem) / f"{safe_id}{suffix}" if role in _REPEATED_ROLES else Path(stem + suffix)
    target = safe_generated_target(staging, destination)
    atomic_replace_file(source, target)
    row = {
        "schema_version": 2, "asset_id": asset_id or role, "role": role,
        "status": "available", "editability_class": editability,
        "path": str(target.relative_to(staging)).replace("\\", "/"),
        "sha256": sha256_file(target), "size_bytes": target.stat().st_size,
        "media_type": _media_type(target), "purpose": purpose, "provenance": provenance,
        "rights_status": "project_authorized", "reason": None,
    }
    if semantic_event_id is not None:
        row["semantic_event_id"] = semantic_event_id
    if render_event_id is not None:
        row["render_event_id"] = render_event_id
    if timeline is not None:
        row["timeline"] = dict(timeline)
    return row


def _unavailable(role: str, reason: str) -> dict[str, Any]:
    _, _, purpose, provenance = _DESTINATIONS[role]
    return {
        "schema_version": 2, "asset_id": role, "role": role, "status": "unavailable",
        "editability_class": "unavailable", "path": None, "sha256": None,
        "size_bytes": None, "media_type": None, "purpose": purpose,
        "provenance": provenance, "rights_status": "unavailable", "reason": reason,
    }


def _media_type(path: Path) -> str:
    return {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".wav": "audio/wav",
        ".srt": "application/x-subrip", ".ass": "text/x-ssa", ".json": "application/json",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    }.get(path.suffix.lower(), "application/octet-stream")


def probe_video_frame_rate(path: Path) -> float:
    """Read the current video stream rate; never invent an editor timeline rate."""
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=avg_frame_rate", "-of", "default=nw=1:nk=1", str(path)],
            check=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        numerator, denominator = completed.stdout.strip().split("/", 1)
        rate = float(numerator) / float(denominator)
    except (OSError, subprocess.SubprocessError, ValueError, ZeroDivisionError) as error:
        raise NleHandoffError("manual NLE package cannot verify automatic-master frame rate") from error
    if not _finite_number(rate, positive=True):
        raise NleHandoffError("manual NLE package automatic-master frame rate is invalid")
    return rate


def _write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _timeline(edl: Mapping[str, Any], assets: list[dict[str, Any]], *, rate: float, width: int, height: int) -> dict[str, Any]:
    ranges = edl.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        raise NleHandoffError("NLE package requires a non-empty video-use EDL")
    duration = 0.0
    for row in ranges:
        if not isinstance(row, Mapping):
            raise NleHandoffError("NLE package EDL range is malformed")
        start, end = row.get("start"), row.get("end")
        cursor = row.get("timeline_start", duration)
        if not all(_finite_number(value, nonnegative=True) for value in (start, end, cursor)) or float(end) <= float(start):
            raise NleHandoffError("NLE package EDL times are invalid")
        duration = max(duration, float(cursor) + float(end) - float(start))
    available = {row["role"]: row for row in assets if row["status"] == "available"}
    tracks: list[dict[str, Any]] = []
    for order, (role, track_role) in enumerate((
        ("automatic_master", "reference"), ("clean_a_roll", "base_video"),
        ("caption_srt", "captions"), ("dialogue_stem", "dialogue"),
        ("bgm_stem", "bgm"), ("sfx_grouped", "sfx"),
    )):
        row = available.get(role)
        if row:
            tracks.append({
                "track_id": f"track-{role}", "role": track_role, "order": order,
                "clips": [{"clip_id": f"clip-{role}", "asset_id": row["asset_id"],
                           "timeline_start": 0.0, "timeline_end": duration,
                           "source_start": 0.0, "source_end": duration}],
            })
    for role, track_role in (("motion_event", "motion"), ("sfx_event", "sfx"),
                             ("ip_rendered", "ip"), ("outro_overlay", "outro")):
        repeated = [row for row in assets if row["role"] == role and row["status"] == "available"]
        clips = []
        for row in repeated:
            placement = row.get("timeline")
            if not isinstance(placement, Mapping):
                continue
            clips.append({
                "clip_id": f"clip-{row['asset_id']}", "asset_id": row["asset_id"],
                "timeline_start": float(placement["start_seconds"]),
                "timeline_end": float(placement["end_seconds"]),
                "source_start": 0.0,
                "source_end": float(placement["end_seconds"]) - float(placement["start_seconds"]),
                "semantic_event_id": row.get("semantic_event_id"),
            })
        if clips:
            tracks.append({"track_id": f"track-{role}", "role": track_role,
                           "order": len(tracks), "clips": clips})
    payload = {
        "schema_version": 2, "authority": "video-use-output-timeline", "origin_seconds": 0,
        "duration_seconds": duration, "frame_rate": float(rate),
        "canvas": {"width": width, "height": height}, "tracks": tracks, "markers": [],
        "otio": edl_to_otio(dict(edl), rate=float(rate)),
        "loss_report": validate_roundtrip(dict(edl), otio_to_internal(edl_to_otio(dict(edl), rate=float(rate)))),
    }
    errors = validate_layer_timeline(payload)
    if errors:
        raise NleHandoffError("NLE timeline failed:\n- " + "\n- ".join(errors))
    return payload


def _copy_guide_screenshots(staging: Path) -> None:
    for name in (
        "01-empty-project.png",
        "02-import-subtitles.png",
        "03-audio-panel.png",
        "04-project-settings.png",
    ):
        source = GUIDE_SCREENSHOT_ROOT / name
        if not source.is_file():
            raise NleHandoffError(f"Jianying guide screenshot is missing: {source}")
        target = safe_generated_target(
            staging, Path("08-timeline/screenshots") / name,
        )
        atomic_replace_file(source, target)


def _import_guide(
    level: str, *, width: int, height: int, frame_rate: float,
) -> str:
    return f"""# 剪映专业版手动导入与调整指南

> 适用配置：`{PACKAGE_PROFILE}`
>
> 交接包级别：`{level}`
>
> 建议画布：`{width} × {height}`
>
> 建议帧率：`{frame_rate:g} fps`

本目录是一套**普通媒体文件 + 字幕 + 时间线说明 + 保留的 HyperFrames 深度编辑入口**，方便在剪映专业版里继续手动调整。它**不包含剪映原生草稿**，也不声称使用了剪映 API、CLI 或无人值守渲染能力。

## 一、先了解各目录

| 目录 | 用途 | 在剪映中的建议 |
|---|---|---|
| `00-reference/` | 自动成片参考版 | 放在最上方参考轨，默认锁定并关闭可见性；需要对照时再开启 |
| `01-base/` | 干净 A-roll、对白音轨 | A-roll 放主视频轨 0 秒；对白放音频轨 0 秒 |
| `02-captions/` | SRT、ASS 外观参考、重点词计划 | SRT 可直接导入；ASS 和 JSON 用于复刻颜色、加粗、放大等视觉效果 |
| `03-motion/` | 整段或事件级动效 | 整段素材从 0 秒放置；事件素材按 `layer-timeline.json` 的时间放置 |
| `04-ip-assets/` | 个人 IP 插画和已渲染层 | 作为普通图片/视频叠加层导入；缺失时不要自行补造 |
| `05-audio/` | BGM、分组音效、事件音效 | BGM/分组干声通常从 0 秒；**事件音效不能全部放在 0 秒** |
| `06-outro/` | 关注、点赞、转发等片尾模块 | 背景、图标、文字说明分层导入；按需删改或缩短 |
| `07-cover/` | 封面参考 | 用于封面导出，不放入正片时间线 |
| `08-timeline/` | OTIO、JSON 时间线、标记和本说明 | 所有精确入点以 `layer-timeline.json` 为准 |
| `09-source-project/` | HyperFrames/编辑权威文件 | 需要改动效内部结构时回到 HyperFrames 工程修改 |
| `10-evidence/` | 清单、哈希、兼容性与验证报告 | 排错和确认文件没有漂移，不导入时间线 |

## 二、创建剪映工程

1. 打开剪映专业版，创建空白草稿。
2. 进入草稿后，先按本页顶部参数或 `layer-timeline.json` 设置比例、分辨率和帧率。
3. 若剪映显示的是比例而不是像素：竖屏通常选 `9:16`，横屏通常选 `16:9`；最终仍以包内宽高为准。

![空白工程与素材导入入口](screenshots/01-empty-project.png)

草稿设置入口位于播放器右下方的草稿参数区域；不同版本的按钮位置可能略有变化。

![草稿比例、分辨率与帧率设置](screenshots/04-project-settings.png)

## 三、按顺序导入素材

### 1. 导入主画面和参考成片

1. 在顶部进入 **素材 → 导入**。
2. 导入 `01-base/clean-a-roll.*`，拖到主视频轨并对齐 `00:00:00.000`。
3. 导入 `00-reference/automatic-master.*`，放到最上方参考轨，同样从 0 秒开始。
4. 将参考轨静音、关闭可见性并锁定；只有 A/B 对照时才临时开启。

### 2. 导入对白、BGM 和音效

本地音频文件同样通过 **素材 → 导入** 导入；顶部“音频”页主要用于素材库和音频处理，不是本交接包的唯一导入入口。

![剪映音频面板](screenshots/03-audio-panel.png)

1. `01-base/dialogue.*`：放到独立对白轨，从 0 秒开始。
2. `05-audio/bgm.*`：放到独立 BGM 轨，从 0 秒开始，并避免盖住对白。
3. `05-audio/sfx-grouped.*`：若它是完整分组音轨，从 0 秒开始。
4. `05-audio/sfx-events/*`：逐个查看 `layer-timeline.json` 的 `timeline_start`，放到对应时间；**事件音效不能全部放在 0 秒**。
5. 如主视频自身带有相同对白或音效，只保留一份，避免重音、回声或响度叠加。

### 3. 导入字幕

1. 进入 **文本 → 新建文本 → 导入本地字幕**。
2. 选择 `02-captions/master.srt`。
3. 检查首句、末句、切点附近及重点词时间是否对齐。

![导入本地字幕入口](screenshots/02-import-subtitles.png)

注意：SRT 只保存字幕文字和时间，不能完整保存 ASS 中的逐词品牌色、加粗、放大和动画。若要在剪映中保持可编辑：

- 把 `02-captions/master-reference.ass` 当作外观参考，不要把它误当作剪映原生可编辑样式。
- 打开 `02-captions/caption-emphasis-plan.json`，按其中的重点词、颜色、字号倍率和时间范围，在剪映中拆分相应字幕片段并手动复刻。
- 对需要放大或换色的词，通常要拆成独立文本片段或复制字幕层，再修改局部样式。
- 修改字幕分句时，优先保持原词和时间权威，只调整语义断句与屏幕呈现，不擅自改写口播内容。

### 4. 导入动效、个人 IP 插画和片尾

1. `03-motion/all-motion-overlay.*` 若存在，作为整段叠加轨从 0 秒放置。
2. `03-motion/events/*` 按各自 `timeline_start` 放置；可以在剪映中移动、裁切、隐藏、复制或调透明度。
3. `04-ip-assets/` 中状态为 `available` 的文件才导入；没有文件就保持 `unavailable`，不要临时编造素材。
4. `06-outro/` 中的背景、图标、文字说明和参考合成分别放到独立轨道，方便改文案、缩短时长或删除某一层。
5. 若要改变动效内部节点、连线、文字结构或关键帧逻辑，应回到 `09-source-project/` 中保留的 HyperFrames 工程修改后再重新导出；剪映更适合处理已渲染层的位置、时长、透明度和组合关系。

## 四、建议的时间线轨道顺序

从上到下可使用：

1. 临时参考成片（默认关闭并锁定）
2. 片尾文字和图标
3. 个人 IP 插图/插画
4. 事件级动效
5. 整段动效
6. 字幕和重点词文本
7. 主画面 clean A-roll
8. 事件音效
9. BGM
10. 对白

轨道名称、素材入点、出点和语义事件 ID 都可在 `layer-timeline.json` 中查到。不要只凭文件名猜时间。

## 五、导入后必须完成的五项验证

1. **字幕可编辑**：修改一个测试字幕，确认文字和样式能保存，再撤销。
2. **动效可移动**：移动一个事件动效约 0.5 秒，确认它是独立素材层，再撤销。
3. **音效可静音**：静音一个事件音效，确认对白没有同时消失，再撤销。
4. **IP 素材可移动**：移动一个 IP 插图，确认它不是烧录在主视频里，再撤销。
5. **片尾文案可改**：修改一次 CTA 文案，确认文字层独立，再撤销。

完成后把结果记录到 `10-evidence/compatibility-report.json`。在五项人工验证完成前，兼容性状态应保持 `pending`，不能自动宣称剪映原生可编辑。

## 六、常见问题

- **字幕重复**：主视频可能已有烧录字幕，又导入了 SRT；关闭其中一层。
- **人声有回声**：主视频音频和独立对白轨同时播放；静音其中一份重复对白。
- **音效全挤在开头**：事件音效错误地都放在 0 秒；按 JSON 中每个事件的入点重新放置。
- **动效位置能改、内容不能改**：这是普通渲染层的正常边界；深度修改需回到 HyperFrames。
- **某目录为空**：查看 `10-evidence/nle-handoff-package.json` 中对应资产的 `status` 和 `reason`；`unavailable` 不代表打包失败。
- **界面与截图不同**：截图来自 Windows 剪映专业版 `11.1.0.14287` 的空白工程；后续版本菜单位置可能变化，但目录、时间线和验证原则不变。
"""


def build_nle_handoff_package(
    *, package_root: Path, authorized_root: Path, project_path: Path, source_path: Path,
    automatic_master: Path, edl_path: Path, implementation_sha256: str,
    package_level: str, frame_rate: float, width: int, height: int,
    assets: Mapping[str, Any], enabled: bool = True,
) -> dict[str, Any]:
    if not enabled:
        raise NleHandoffError("manual NLE package v2 is disabled")
    if package_level not in PACKAGE_LEVELS:
        raise NleHandoffError("manual NLE package level is invalid")
    if not isinstance(implementation_sha256, str) or len(implementation_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in implementation_sha256):
        raise NleHandoffError("manual NLE implementation hash is invalid")
    if not _finite_number(frame_rate, positive=True) or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (width, height)):
        raise NleHandoffError("manual NLE canvas/rate is invalid")
    authorized_root = Path(os.path.abspath(authorized_root))
    package_root = Path(os.path.abspath(package_root))
    try:
        relative = package_root.relative_to(authorized_root)
        parent = safe_generated_directory(authorized_root, relative.parent)
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleHandoffError(str(error)) from error
    if package_root.exists() and (package_root.is_symlink() or bool(getattr(os.path, "isjunction", lambda _p: False)(package_root))):
        raise NleHandoffError("manual NLE package root is redirected")
    if package_root.exists() and not package_root.is_dir():
        raise NleHandoffError("manual NLE package root must be a directory")
    staging = safe_generated_directory(authorized_root, relative.parent / f".{package_root.name}.staging-{uuid.uuid4().hex}")
    try:
        for path, label in ((project_path, "project"), (source_path, "source"), (automatic_master, "automatic master"), (edl_path, "EDL")):
            if not Path(path).resolve().is_file():
                raise NleHandoffError(f"manual NLE {label} authority is missing")
        edl = read_json(Path(edl_path))
        rows: list[dict[str, Any]] = []
        rows.append(_copy_asset(Path(automatic_master), staging, "automatic_master"))
        for role in _DESTINATIONS:
            if role == "automatic_master":
                continue
            configured = assets.get(role)
            if isinstance(configured, (list, tuple)):
                if not configured:
                    rows.append(_unavailable(role, "current project has no authorized materialized asset"))
                for index, value in enumerate(configured):
                    record = value if isinstance(value, Mapping) else {}
                    source = Path(record.get("path") if record else value)
                    rows.append(_copy_asset(
                        source, staging, role,
                        asset_id=f"{role}:{index}:{hashlib.sha256(str(source.resolve()).encode('utf-8')).hexdigest()[:12]}",
                        semantic_event_id=(str(record.get("semantic_event_id")) if record.get("semantic_event_id") else None),
                        render_event_id=(str(record.get("render_event_id")) if record.get("render_event_id") else None),
                        timeline=(record.get("timeline") if isinstance(record.get("timeline"), Mapping) else None),
                    ))
            elif configured:
                rows.append(_copy_asset(Path(configured), staging, role))
            else:
                rows.append(_unavailable(role, "current project has no authorized materialized asset"))
        if package_level != "reference_only":
            required = {"clean_a_roll", "caption_srt"}
            missing = sorted(role for role in required if not any(row["role"] == role and row["status"] == "available" for row in rows))
            if missing:
                raise NleHandoffError("balanced NLE package requires: " + ", ".join(missing))

        timeline = _timeline(edl, rows, rate=float(frame_rate), width=width, height=height)
        timeline_path = safe_generated_target(staging, Path("08-timeline/layer-timeline.json"))
        _write_json(timeline_path, timeline)
        otio_path = safe_generated_target(staging, Path("08-timeline/timeline.otio.json"))
        _write_json(otio_path, timeline["otio"])
        _copy_guide_screenshots(staging)
        guide_path = safe_generated_target(staging, Path("08-timeline/import-order.md"))
        atomic_write_text(
            guide_path,
            _import_guide(
                package_level, width=width, height=height,
                frame_rate=float(frame_rate),
            ),
        )
        markers_path = safe_generated_target(staging, Path("08-timeline/markers.csv"))
        atomic_write_text(markers_path, "marker_id,kind,time_seconds,label,semantic_event_id\n")

        rights_path = safe_generated_target(staging, Path("10-evidence/rights-manifest.json"))
        rights = {"schema_version": 2, "status": "pass", "assets": [
            {"asset_id": row["asset_id"], "rights_status": row["rights_status"], "sha256": row["sha256"]}
            for row in rows
        ]}
        _write_json(rights_path, rights)
        compatibility_path = safe_generated_target(staging, Path("10-evidence/compatibility-report.json"))
        caption_row = next((row for row in rows if row["role"] == "caption_srt" and row["status"] == "available"), None)
        reference_row = caption_row or next(row for row in rows if row["role"] == "automatic_master")
        compatibility = {
            "schema_version": 2, "status": "pending", "package_profile": PACKAGE_PROFILE,
            "editor": {"name": "Jianying Desktop", "version": "unverified",
                       "platform": "Windows", "observed_at": "1970-01-01T00:00:00Z"},
            "capabilities": {"native_draft": False, "api": False, "cli": False,
                             "headless_render": False, "srt_import": False},
            "format_results": [{"format_id": "srt" if caption_row else "automatic_master_mp4",
                                "asset_sha256": reference_row["sha256"],
                                "imported": False, "decoded": bool(caption_row),
                                "editable_class": "reference_only", "finding": "human import canary pending"}],
            "human_canary": {"actor": "HongRun", "status": "pending",
                             "tasks": [{"task_id": task, "status": "pending", "seconds_spent": None} for task in (
                                 "edit_caption", "move_motion", "mute_sfx", "move_ip", "edit_outro",
                             )], "reason": "Jianying Desktop canary has not been performed"},
        }
        _write_json(compatibility_path, compatibility)
        validation_path = safe_generated_target(staging, Path("10-evidence/package-validation.json"))
        _write_json(validation_path, {"schema_version": 2, "status": "pass", "automated_checks": [
            "safe_output", "authority_hashes", "layer_inventory", "timeline_roundtrip",
        ], "human_compatibility_gate": "pending"})

        inventory_paths = sorted(path for path in staging.rglob("*") if path.is_file())
        inventory = [_file_ref(path, relative_to=staging) for path in inventory_paths]
        receipt = {
            "schema_version": 2, "kind": "manual_nle_package", "status": "action_required",
            "package_profile": PACKAGE_PROFILE, "package_level": package_level,
            "package_root": str(package_root),
            "authorities": {
                "project": _file_ref(Path(project_path)), "source": _file_ref(Path(source_path)),
                "automatic_master": _file_ref(Path(automatic_master)), "edl": _file_ref(Path(edl_path)),
                "implementation": implementation_sha256,
            },
            "capability_claims": {"native_draft": False, "editor_api": False,
                                  "editor_cli": False, "headless_render": False},
            "assets": rows, "timeline": _file_ref(timeline_path, relative_to=staging),
            "rights_manifest": _file_ref(rights_path, relative_to=staging),
            "compatibility_report": _file_ref(compatibility_path, relative_to=staging),
            "validation_report": _file_ref(validation_path, relative_to=staging),
            "import_guide": _file_ref(guide_path, relative_to=staging),
            "complete_file_inventory": inventory,
        }
        receipt["integrity_sha256"] = _stable_hash(receipt)
        receipt_path = safe_generated_target(staging, Path("10-evidence/nle-handoff-package.json"))
        _write_json(receipt_path, receipt)
        errors = validate_nle_handoff_package(receipt_path, package_root_override=staging)
        if errors:
            raise NleHandoffError("manual NLE package failed:\n- " + "\n- ".join(errors))

        backup = parent / f".{package_root.name}.backup-{uuid.uuid4().hex}"
        had_previous = package_root.exists()
        if had_previous:
            os.replace(package_root, backup)
        try:
            os.replace(staging, package_root)
        except Exception:
            if had_previous and backup.exists():
                os.replace(backup, package_root)
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        return receipt
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def validate_nle_handoff_package(receipt_path: Path, *, package_root_override: Path | None = None) -> list[str]:
    lexical_receipt = Path(os.path.abspath(receipt_path))
    for candidate in (lexical_receipt, *lexical_receipt.parents):
        if candidate.exists() and _is_redirected(candidate):
            return ["NLE handoff package receipt path is redirected"]
    try:
        payload = read_json(Path(receipt_path))
    except (OSError, ValueError, json.JSONDecodeError):
        return ["NLE handoff package receipt is unreadable"]
    if not isinstance(payload, Mapping):
        return ["NLE handoff package receipt must be an object"]
    root = Path(package_root_override or payload.get("package_root", "")).resolve()
    errors: list[str] = []
    if payload.get("schema_version") != 2 or payload.get("kind") != "manual_nle_package":
        errors.append("NLE handoff package identity is invalid")
    if payload.get("package_profile") != PACKAGE_PROFILE or payload.get("package_level") not in PACKAGE_LEVELS:
        errors.append("NLE handoff package profile/level is invalid")
    if package_root_override is None and lexical_receipt.resolve().parent.parent != root:
        errors.append("NLE handoff package receipt is not under its declared package root")
    try:
        expected_integrity = _stable_hash(payload)
    except (TypeError, ValueError):
        errors.append("NLE handoff package contains non-canonical values")
    else:
        if payload.get("integrity_sha256") != expected_integrity:
            errors.append("NLE handoff package integrity is stale")
    claims = payload.get("capability_claims")
    if not isinstance(claims, Mapping) or any(claims.get(key) is not False for key in ("native_draft", "editor_api", "editor_cli", "headless_render")):
        errors.append("NLE handoff package cannot claim native editor automation")
    authorities = payload.get("authorities")
    if not isinstance(authorities, Mapping):
        errors.append("NLE handoff package authorities are invalid")
    else:
        for key in ("project", "source", "automatic_master", "edl"):
            errors.extend(_ref_errors(authorities.get(key), root, f"authority {key}", external=True))
        implementation = authorities.get("implementation")
        if not isinstance(implementation, str) or len(implementation) != 64 or any(
            character not in "0123456789abcdef" for character in implementation
        ):
            errors.append("NLE handoff implementation binding is invalid")
        elif implementation != sha256_file(Path(__file__).resolve()):
            errors.append("NLE handoff implementation binding is stale")
    assets = payload.get("assets")
    if not isinstance(assets, list) or len(assets) < 2:
        errors.append("NLE handoff package assets are invalid")
    else:
        ids: set[str] = set()
        for row in assets:
            errors.extend(validate_layer_asset(row, package_root=root))
            if isinstance(row, Mapping):
                if row.get("asset_id") in ids:
                    errors.append("NLE handoff package asset ID is duplicate")
                ids.add(row.get("asset_id"))
        available_roles = {
            row.get("role") for row in assets
            if isinstance(row, Mapping) and row.get("status") == "available"
        }
        required_roles = {"automatic_master"}
        if payload.get("package_level") in {"balanced", "max_editable"}:
            required_roles.update({"clean_a_roll", "caption_srt"})
        if not required_roles.issubset(available_roles):
            errors.append("NLE handoff package is missing required package-level assets")
    for key in ("timeline", "rights_manifest", "compatibility_report", "validation_report", "import_guide"):
        errors.extend(_ref_errors(payload.get(key), root, key))
    guide_path = _resolve_ref(payload.get("import_guide"), root)
    if guide_path and guide_path.is_file():
        try:
            guide = guide_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("NLE handoff Chinese import guide is unreadable")
        else:
            required_guide_text = (
                "剪映专业版手动导入与调整指南",
                "素材 → 导入",
                "文本 → 新建文本 → 导入本地字幕",
                "事件音效不能全部放在 0 秒",
                "不包含剪映原生草稿",
            )
            if any(value not in guide for value in required_guide_text):
                errors.append("NLE handoff Chinese import guide is incomplete")
            for name in (
                "01-empty-project.png",
                "02-import-subtitles.png",
                "03-audio-panel.png",
                "04-project-settings.png",
            ):
                screenshot = root / "08-timeline" / "screenshots" / name
                source = GUIDE_SCREENSHOT_ROOT / name
                if (
                    f"screenshots/{name}" not in guide
                    or not screenshot.is_file()
                    or not source.is_file()
                    or sha256_file(screenshot) != sha256_file(source)
                ):
                    errors.append(
                        f"NLE handoff guide screenshot is missing or stale: {name}"
                    )
    timeline_path = _resolve_ref(payload.get("timeline"), root)
    if timeline_path and timeline_path.is_file():
        try:
            timeline_payload = read_json(timeline_path)
            errors.extend(validate_layer_timeline(timeline_payload))
            if isinstance(authorities, Mapping):
                edl_path = _resolve_ref(authorities.get("edl"), root, external=True)
                if edl_path and edl_path.is_file() and isinstance(assets, list):
                    expected = _timeline(
                        read_json(edl_path), assets,
                        rate=float(timeline_payload.get("frame_rate")),
                        width=int((timeline_payload.get("canvas") or {}).get("width")),
                        height=int((timeline_payload.get("canvas") or {}).get("height")),
                    )
                    if timeline_payload != expected:
                        errors.append("NLE layer timeline differs from current EDL and asset inventory")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            errors.append("NLE layer timeline is unreadable")
    compatibility_path = _resolve_ref(payload.get("compatibility_report"), root)
    if compatibility_path and compatibility_path.is_file():
        try:
            errors.extend(validate_compatibility_report(read_json(compatibility_path)))
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("NLE compatibility report is unreadable")
    rights_path = _resolve_ref(payload.get("rights_manifest"), root)
    if rights_path and rights_path.is_file() and isinstance(assets, list):
        try:
            rights = read_json(rights_path)
            expected_rights = [
                {"asset_id": row.get("asset_id"), "rights_status": row.get("rights_status"),
                 "sha256": row.get("sha256")}
                for row in assets if isinstance(row, Mapping)
            ]
            if not isinstance(rights, Mapping) or rights.get("status") != "pass" or rights.get("assets") != expected_rights:
                errors.append("NLE rights manifest differs from the layer inventory")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            errors.append("NLE rights manifest is unreadable")
    validation_path = _resolve_ref(payload.get("validation_report"), root)
    if validation_path and validation_path.is_file():
        try:
            validation = read_json(validation_path)
            if not isinstance(validation, Mapping) or validation.get("status") != "pass":
                errors.append("NLE automated package validation is not pass")
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("NLE automated package validation is unreadable")
    if payload.get("status") == "pass" and compatibility_path and compatibility_path.is_file():
        try:
            if read_json(compatibility_path).get("status") != "pass":
                errors.append("NLE handoff package pass requires passed compatibility evidence")
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            errors.append("NLE handoff package compatibility evidence is invalid")
    inventory = payload.get("complete_file_inventory")
    if not isinstance(inventory, list) or not inventory:
        errors.append("NLE handoff complete inventory is invalid")
    else:
        declared: set[str] = set()
        for index, ref in enumerate(inventory):
            errors.extend(_ref_errors(ref, root, f"inventory {index}"))
            if isinstance(ref, Mapping) and isinstance(ref.get("path"), str):
                declared.add(ref["path"].replace("\\", "/"))
        actual = {
            str(path.relative_to(root)).replace("\\", "/")
            for path in root.rglob("*") if path.is_file()
            and path.name != "nle-handoff-package.json"
        } if root.is_dir() else set()
        if declared != actual:
            errors.append("NLE handoff complete inventory has missing, extra, or stale files")
    return errors
