#!/usr/bin/env python3
"""Build the always-on, editor-neutral repair kit for a completed automatic edit."""
from __future__ import annotations

import hashlib
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


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _strict_json(path: Path) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EditableDeliveryError(f"instance handoff duplicate JSON key: {key}")
            result[key] = value
        return result
    payload = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)
    _canonical_hash(payload)  # Reject nonfinite values, including exponent overflow.
    return payload


def _instance_handoff_summary(path: Path) -> dict[str, Any]:
    """Validate bundle bytes and rederive whatever has current file authorities.

    Inline-only hashes remain integrity declarations, not current-file evidence.
    No media is opened/copied and no editor compatibility claim is generated.
    """
    try:
        payload = _strict_json(path)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("kind") != "editorial_instance_handoff":
            raise EditableDeliveryError("instance handoff identity is invalid")
        unsigned = {key: value for key, value in payload.items() if key != "bundle_sha256"}
        if payload.get("bundle_sha256") != _canonical_hash(unsigned):
            raise EditableDeliveryError("instance handoff bundle hash is stale")
        if payload.get("verification_scope") != "output_instance_linkage_only" or any(
            payload.get(key) is not False for key in ("native_editor_verified", "assets_copied",
                                                    "caption_files_generated", "full_render_authorized")
        ):
            raise EditableDeliveryError("instance handoff scope claims are invalid")
        records = payload.get("inputs")
        required = {"projection", "output_brief", "captions"}
        optional = {"audio_plan": "audio", "target_bindings": "targets", "promise_ledger": "promises"}
        if not isinstance(records, dict) or not required <= set(records) or set(records) - required - set(optional):
            raise EditableDeliveryError("instance handoff input inventory is invalid")
        file_inputs = {}
        for name, record in records.items():
            if not isinstance(record, dict):
                raise EditableDeliveryError(f"instance handoff {name} record is invalid")
            canonical = record.get("canonical_sha256")
            if not isinstance(canonical, str) or len(canonical) != 64 or any(c not in "0123456789abcdef" for c in canonical):
                raise EditableDeliveryError(f"instance handoff {name} canonical hash is invalid")
            if record.get("hash_scope") == "current_file_bytes":
                if set(record) != {"path", "sha256", "canonical_sha256", "hash_scope"} or not Path(str(record.get("path") or "")).is_absolute():
                    raise EditableDeliveryError(f"instance handoff {name} needs an absolute file path")
                errors = _artifact_errors(record, f"instance handoff {name}")
                if errors:
                    raise EditableDeliveryError("; ".join(errors))
                if _canonical_hash(_strict_json(Path(record["path"]))) != canonical:
                    raise EditableDeliveryError(f"instance handoff {name} canonical hash is stale")
                file_inputs[name] = {"path": record["path"], "sha256": record["sha256"]}
            elif record.get("hash_scope") != "canonical_json_integrity_only" or set(record) != {"hash_scope", "canonical_sha256"}:
                raise EditableDeliveryError(f"instance handoff {name} hash scope is invalid")
        for name in ("captions", "audio", "targets", "promises"):
            section = payload.get(name)
            if not isinstance(section, dict) or section.get("status") not in {"linked", "partial", "unavailable", "not_provided"} or not isinstance(section.get("rows"), list) or not isinstance(section.get("unavailable"), list):
                raise EditableDeliveryError(f"instance handoff {name} section is invalid")
        recomputed = required <= set(file_inputs)
        if recomputed:
            from editorial_handoff import build_handoff
            rebuilt = build_handoff(**file_inputs)
            omitted = {"inputs", "bundle_sha256"} | {section for name, section in optional.items()
                                                     if name in records and name not in file_inputs}
            if {k: v for k, v in payload.items() if k not in omitted} != {k: v for k, v in rebuilt.items() if k not in omitted}:
                raise EditableDeliveryError("instance handoff differs from recomputed current file inputs")
        return {"bundle_sha256": payload["bundle_sha256"],
                "verification_scope": "output_instance_linkage_only", "native_editor_verified": False,
                "caption_linkage_status": payload["captions"]["status"],
                "file_inputs_recomputed": recomputed,
                "inline_integrity_only_inputs": sorted(set(records) - set(file_inputs))}
    except (OSError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, EditableDeliveryError):
            raise
        raise EditableDeliveryError(f"instance handoff validation failed: {error}") from error


def build_editable_delivery(
    *, output_root: Path, authorized_root: Path, automatic_master: Path,
    caption_free_candidate: Path, caption_srt: Path, caption_ass: Path,
    caption_style_plan: Path, hyperframes_project: Path,
    instance_handoff: Path | None = None,
) -> Path:
    """Materialize the minimum assets needed for local NLE/AI-editor repair.

    The large video files remain at their authoritative project paths.  SRT,
    ASS, and the style plan are copied into one stable repair-kit directory.
    An opt-in instance handoff is copied as JSON only; None retains legacy bytes.
    """
    instance_source = None
    instance_summary = None
    if instance_handoff is not None:
        instance_source = _require_file(instance_handoff, "instance handoff")
        instance_summary = _instance_handoff_summary(instance_source)
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
    if instance_source is not None:
        source_record = _file_record(instance_source)
        target = safe_generated_target(lexical_root, relative_output / "editorial" / "instance-handoff.json")
        atomic_replace_file(instance_source, target)
        if sha256_file(target) != source_record["sha256"] or sha256_file(instance_source) != source_record["sha256"]:
            raise EditableDeliveryError("instance handoff copy differs from its authority")
        if _instance_handoff_summary(target) != instance_summary:
            raise EditableDeliveryError("instance handoff changed while copying")
        manifest["instance_handoff"] = {**_file_record(target), "source": source_record, **instance_summary}
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
    if "instance_handoff" in payload:
        row = payload["instance_handoff"]
        current_errors = _artifact_errors(row, "instance handoff")
        if isinstance(row, Mapping):
            source = row.get("source")
            current_errors.extend(_artifact_errors(source, "instance handoff source"))
            if isinstance(source, Mapping) and row.get("sha256") != source.get("sha256"):
                current_errors.append("instance handoff copy differs from source")
            if not current_errors:
                try:
                    summary = _instance_handoff_summary(Path(row["path"]))
                    if any(row.get(key) != value for key, value in summary.items()):
                        current_errors.append("instance handoff manifest claims differ from bundle")
                except EditableDeliveryError as error:
                    current_errors.append(str(error))
        errors.extend(current_errors)
    return errors
