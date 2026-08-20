#!/usr/bin/env python3
"""Build the always-on, editor-neutral repair kit for a completed automatic edit."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from director_contracts import sha256_file
from safe_generated_output import (
    SafeGeneratedOutputError,
    atomic_replace_file,
    atomic_write_text,
    safe_generated_directory,
    safe_generated_target,
)


class EditableDeliveryError(ValueError):
    """The standard editability kit cannot be built truthfully or safely."""


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {"path": str(resolved), "sha256": sha256_file(resolved)}


def _require_file(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise EditableDeliveryError(f"{label} is missing: {resolved}")
    return resolved


def _project_inventory(project: Path) -> list[dict[str, Any]]:
    project = project.resolve()
    if not project.is_dir():
        raise EditableDeliveryError(f"editable HyperFrames project is missing: {project}")
    names = (
        "frame.md", "storyboard.json", "index.html", "index.motion.json",
        "renderer-payload.json", "renderer-project-manifest.json", "audio-plan.json",
    )
    rows = [
        {"relative_path": name, **_file_record(project / name)}
        for name in names if (project / name).is_file()
    ]
    if not any(row["relative_path"] == "index.html" for row in rows):
        raise EditableDeliveryError("editable HyperFrames project lacks index.html")
    if not any(row["relative_path"] == "storyboard.json" for row in rows):
        raise EditableDeliveryError("editable HyperFrames project lacks storyboard.json")
    return rows


def build_editable_delivery(
    *, output_root: Path, authorized_root: Path, automatic_master: Path,
    caption_free_candidate: Path, caption_srt: Path, caption_ass: Path,
    caption_style_plan: Path, hyperframes_project: Path,
) -> Path:
    """Materialize the minimum assets needed for local NLE/AI-editor repair.

    The large video files remain at their authoritative project paths.  SRT,
    ASS, and the style plan are copied into one stable repair-kit directory.
    """
    lexical_root = Path(os.path.abspath(authorized_root))
    lexical_output = Path(os.path.abspath(output_root))
    try:
        relative_output = lexical_output.relative_to(lexical_root)
        output = safe_generated_directory(lexical_root, relative_output)
    except (ValueError, SafeGeneratedOutputError) as error:
        raise EditableDeliveryError(f"editable delivery output is unsafe: {error}") from error

    automatic = _require_file(automatic_master, "automatic master")
    candidate = _require_file(caption_free_candidate, "caption-free candidate")
    if automatic == candidate:
        raise EditableDeliveryError(
            "caption-free candidate must be distinct from the captioned automatic master"
        )
    sources = {
        "srt": _require_file(caption_srt, "editable SRT"),
        "ass": _require_file(caption_ass, "styled ASS"),
        "style_plan": _require_file(caption_style_plan, "caption style plan"),
    }
    copies: dict[str, Path] = {}
    for key, (name, source) in {
        "srt": ("master.srt", sources["srt"]),
        "ass": ("master.ass", sources["ass"]),
        "style_plan": ("caption-style-plan.json", sources["style_plan"]),
    }.items():
        target = safe_generated_target(lexical_root, relative_output / "captions" / name)
        atomic_replace_file(source, target)
        if sha256_file(target) != sha256_file(source):
            raise EditableDeliveryError(f"editable {key} copy differs from its authority")
        copies[key] = target.resolve()

    project = hyperframes_project.resolve()
    project_files = _project_inventory(project)
    guide = safe_generated_target(lexical_root, relative_output / "README-中文.md")
    atomic_write_text(guide, (
        "# 自动剪辑可修复交付包\n\n"
        "- `automatic_master` 是不可覆盖的自动成片参考。\n"
        "- `caption_free_candidate` 是字幕最后叠加前的候选视频；在专业剪辑软件中导入它。\n"
        "- `captions/master.srt` 用于逐句改字、拆句和调整时间。\n"
        "- `captions/master.ass` 保留样式参考；编辑器不支持 ASS 时，以 SRT 为文字权威。\n"
        "- 深度修改动效时打开 manifest 指向的 HyperFrames 工程，再重新渲染受影响的动效。\n\n"
        "本包不生成剪映、ChatCut 或其他软件的私有工程文件，也不保证这些软件支持 ASS。\n"
    ))
    manifest = {
        "schema_version": 1,
        "kind": "standard_editable_delivery",
        "status": "ready",
        "automatic_master": {**_file_record(automatic), "immutable_reference": True},
        "caption_free_candidate": {
            **_file_record(candidate),
            "new_director_caption_layer": False,
            "purpose": "professional_editor_picture_and_audio_base",
        },
        "captions": {
            "srt": {**_file_record(copies["srt"]), "source": _file_record(sources["srt"]),
                    "editable_text_authority": True},
            "ass": {**_file_record(copies["ass"]), "source": _file_record(sources["ass"]),
                    "styled_reference": True},
            "style_plan": {**_file_record(copies["style_plan"]),
                           "source": _file_record(sources["style_plan"])},
        },
        "hyperframes_project": {
            "path": str(project), "deep_motion_edit_source": True,
            "files": project_files,
        },
        "guide": _file_record(guide),
        "interoperability": {
            "burned_master_text_editable": False,
            "native_editor_draft_generated": False,
            "editor_neutral_assets": ["mp4", "srt", "ass", "json", "html"],
            "editor_support_must_be_verified_locally": True,
        },
    }
    manifest_path = safe_generated_target(
        lexical_root, relative_output / "editable-delivery-manifest.json",
    )
    atomic_write_text(manifest_path, json.dumps(
        manifest, ensure_ascii=False, indent=2, allow_nan=False,
    ) + "\n")
    errors = validate_editable_delivery(manifest_path)
    if errors:
        raise EditableDeliveryError("; ".join(errors))
    return manifest_path.resolve()


def _artifact_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} record is missing"]
    path_value = value.get("path")
    if not isinstance(path_value, str) or not path_value:
        return [f"{label} path is invalid"]
    path = Path(path_value).resolve()
    if not path.is_file():
        return [f"{label} file is missing"]
    if value.get("sha256") != sha256_file(path):
        return [f"{label} hash is stale"]
    return []


def validate_editable_delivery(manifest_path: Path) -> list[str]:
    path = Path(manifest_path).resolve()
    if not path.is_file():
        return ["editable delivery manifest is missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["editable delivery manifest is unreadable"]
    if not isinstance(payload, Mapping):
        return ["editable delivery manifest must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != 1 or payload.get("kind") != "standard_editable_delivery":
        errors.append("editable delivery identity is invalid")
    if payload.get("status") != "ready":
        errors.append("editable delivery status must be ready")
    errors.extend(_artifact_errors(payload.get("automatic_master"), "automatic master"))
    candidate = payload.get("caption_free_candidate")
    errors.extend(_artifact_errors(candidate, "caption-free candidate"))
    if isinstance(candidate, Mapping) and candidate.get("new_director_caption_layer") is not False:
        errors.append("caption-free candidate caption-layer claim is invalid")
    captions = payload.get("captions")
    if not isinstance(captions, Mapping):
        errors.append("editable caption records are missing")
    else:
        for key in ("srt", "ass", "style_plan"):
            errors.extend(_artifact_errors(captions.get(key), f"caption {key}"))
            row = captions.get(key)
            if isinstance(row, Mapping):
                errors.extend(_artifact_errors(row.get("source"), f"caption {key} source"))
                source = row.get("source")
                if isinstance(source, Mapping) and row.get("sha256") != source.get("sha256"):
                    errors.append(f"caption {key} copy differs from source")
    project = payload.get("hyperframes_project")
    if not isinstance(project, Mapping) or project.get("deep_motion_edit_source") is not True:
        errors.append("editable HyperFrames project record is invalid")
    else:
        project_path = Path(str(project.get("path") or "")).resolve()
        if not project_path.is_dir():
            errors.append("editable HyperFrames project is missing")
        rows = project.get("files")
        if not isinstance(rows, list):
            errors.append("editable HyperFrames project inventory is missing")
        else:
            for index, row in enumerate(rows):
                errors.extend(_artifact_errors(row, f"HyperFrames project file {index}"))
    errors.extend(_artifact_errors(payload.get("guide"), "editable delivery guide"))
    interoperability = payload.get("interoperability")
    if not isinstance(interoperability, Mapping):
        errors.append("editable delivery interoperability boundary is missing")
    elif (
        interoperability.get("burned_master_text_editable") is not False
        or interoperability.get("native_editor_draft_generated") is not False
        or interoperability.get("editor_support_must_be_verified_locally") is not True
    ):
        errors.append("editable delivery interoperability claims are invalid")
    return errors
