#!/usr/bin/env python3
"""Atomically initialize a video project from one detected source file."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from project_config import CURRENT_PROJECT_SCHEMA_VERSION, migrate_project_config


PROJECT_DIRS = ("source", "edit", "hyperframes", "scripts", "work", "exports")
MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts",
}

PRESETS: dict[str, dict[str, str]] = {
    "auto": {
        "fixture_type": "auto",
        "content_type": "auto",
        "input_mode": "needs_analysis",
        "hyperframes_route": "auto",
        "asr_backend": "auto",
    },
    "landscape_screen_tutorial": {
        "fixture_type": "landscape_screen_tutorial",
        "content_type": "screen_tutorial",
        "input_mode": "raw",
        "hyperframes_route": "general-video",
        "asr_backend": "local_faster_whisper",
    },
    "portrait_talking_head": {
        "fixture_type": "portrait_talking_head",
        "content_type": "portrait_talking_head",
        "input_mode": "raw",
        "hyperframes_route": "talking-head-recut",
        "asr_backend": "local_faster_whisper",
    },
    "published_edit_polish": {
        "fixture_type": "published_edit_polish",
        "content_type": "existing_edit_polish",
        "input_mode": "existing_edit_polish",
        "hyperframes_route": "general-video",
        "asr_backend": "local_faster_whisper",
    },
    "interview": {
        "fixture_type": "two_person_interview",
        "content_type": "interview",
        "input_mode": "raw",
        "hyperframes_route": "talking-head-recut",
        "asr_backend": "whisperx",
    },
    "screen_plus_camera": {
        "fixture_type": "screen_camera_mixed",
        "content_type": "mixed_screen_camera",
        "input_mode": "raw",
        "hyperframes_route": "general-video",
        "asr_backend": "local_faster_whisper",
    },
}

PRESET_ALIASES = {
    "screen_tutorial": "landscape_screen_tutorial",
    "screen-16x9": "landscape_screen_tutorial",
    "talking_head": "portrait_talking_head",
    "talk-9x16": "portrait_talking_head",
    "existing_edit_polish": "published_edit_polish",
    "polish-existing": "published_edit_polish",
    "two_person_interview": "interview",
    "interview-two": "interview",
    "noisy_audio_hotwords": "auto",
    "noisy-hotwords": "auto",
    "mixed_screen_camera": "screen_plus_camera",
    "screen_camera_mixed": "screen_plus_camera",
    "screen-camera": "screen_plus_camera",
}


def normalize_preset(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    normalized = PRESET_ALIASES.get(normalized, normalized)
    if normalized not in PRESETS:
        raise ValueError(
            f"unknown preset {value!r}; expected one of {', '.join(sorted(PRESETS))}"
        )
    return normalized


def detect_source(source: str | Path) -> Path:
    """Resolve a media file, or require exactly one media file in a directory."""
    candidate = Path(source).expanduser().resolve()
    if candidate.is_file():
        if candidate.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError(f"unsupported source media extension: {candidate.suffix or '<none>'}")
        return candidate
    if not candidate.exists():
        raise FileNotFoundError(candidate)
    if not candidate.is_dir():
        raise ValueError(f"source must be a media file or directory: {candidate}")
    matches = sorted(
        (path.resolve() for path in candidate.iterdir()
         if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS),
        key=lambda path: path.name.lower(),
    )
    if not matches:
        raise FileNotFoundError(f"no supported media file found in {candidate}")
    if len(matches) > 1:
        raise ValueError(f"multiple media files found in {candidate}; pass one file explicitly")
    return matches[0]


def _validate_video_id(video_id: str) -> str:
    cleaned = video_id.strip()
    if not cleaned or cleaned in {".", ".."} or Path(cleaned).name != cleaned:
        raise ValueError("video_id must be one non-empty directory name")
    if any(separator in cleaned for separator in ("/", "\\")):
        raise ValueError("video_id must not contain path separators")
    return cleaned


def probe_media(source: Path) -> dict[str, Any]:
    """Read display geometry and stream evidence; never invent it when ffprobe fails."""
    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(source),
    ]
    try:
        run = subprocess.run(
            command, check=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        payload = json.loads(run.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return {
            "status": "unavailable", "reason": type(error).__name__,
            "orientation": "unknown", "existing_edit_evidence": [],
        }
    streams = payload.get("streams") or []
    videos = [row for row in streams if row.get("codec_type") == "video"]
    audios = [row for row in streams if row.get("codec_type") == "audio"]
    subtitles = [row for row in streams if row.get("codec_type") == "subtitle"]
    primary = videos[0] if videos else {}
    width = int(primary.get("width") or 0)
    height = int(primary.get("height") or 0)
    rotations = [
        row.get("rotation") for row in (primary.get("side_data_list") or [])
        if row.get("rotation") is not None
    ]
    if not rotations and (primary.get("tags") or {}).get("rotate") is not None:
        rotations.append((primary.get("tags") or {}).get("rotate"))
    try:
        rotation = int(float(rotations[0])) % 360 if rotations else 0
    except (TypeError, ValueError):
        rotation = 0
    display_width, display_height = (
        (height, width) if rotation in {90, 270} else (width, height)
    )
    orientation = (
        "landscape" if display_width > display_height else
        "portrait" if display_height > display_width else
        "square" if display_width and display_height else "unknown"
    )
    edit_evidence = []
    if len(videos) > 1 or len(audios) > 1:
        edit_evidence.append("multiple_media_streams")
    if subtitles:
        edit_evidence.append("embedded_subtitles")
    if (payload.get("format", {}).get("tags") or {}).get("encoder"):
        edit_evidence.append("encoder_metadata")
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return {
        "status": "available",
        "width": width,
        "height": height,
        "display_width": display_width,
        "display_height": display_height,
        "display_rotation": rotation,
        "orientation": orientation,
        "aspect_ratio": round(display_width / display_height, 6) if display_height else None,
        "duration_seconds": duration,
        "video_streams": len(videos),
        "audio_streams": len(audios),
        "subtitle_streams": len(subtitles),
        "existing_edit_evidence": edit_evidence,
    }


def _project_config(
    root: Path,
    video_id: str,
    source_name: str,
    preset: str,
    *,
    title: str | None,
    profile: str | Path | None,
    media_probe: dict[str, Any],
) -> dict[str, Any]:
    selected = PRESETS[preset]
    project: dict[str, Any] = {
        "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
        "version": CURRENT_PROJECT_SCHEMA_VERSION,
        "video_id": video_id,
        "title": title or video_id,
        "preset": preset,
        "fixture_type": selected["fixture_type"],
        "content_type": selected["content_type"],
        "content": {"type": selected["content_type"]},
        "paths": {"root": str(root), **{name: name for name in PROJECT_DIRS}},
        "source": {
            "primary_video": (Path("source") / source_name).as_posix(),
            "input_mode": selected["input_mode"],
            "probe": media_probe,
        },
        "workflow": {"input_mode": selected["input_mode"]},
        "editing": {
            "mode": "preserve",
            "require_cut_report": True,
            "require_tail_coverage_check": True,
            "allow_long_semantic_deletion_without_confirmation": False,
        },
        "transcription": {
            "router": {
                "enabled": True,
                "preferred_backend": selected["asr_backend"],
                "hotwords": [],
            },
        },
        "hyperframes": {
            "route": selected["hyperframes_route"],
            "studio_entry": "hyperframes/index.html",
            "overlay_source": "hyperframes/overlay-source.html.txt",
        },
    }
    if profile is not None:
        project["profile"] = str(Path(profile).expanduser().resolve())
    return migrate_project_config(project)


def initialize_project(
    workspace_root: str | Path,
    video_id: str,
    source: str | Path,
    *,
    preset: str = "auto",
    title: str | None = None,
    profile: str | Path | None = None,
) -> Path:
    """Create the complete project off-path, then publish it without overwriting."""
    canonical_preset = normalize_preset(preset)
    safe_video_id = _validate_video_id(video_id)
    parent = Path(workspace_root).expanduser().resolve()
    target = parent / safe_video_id
    if os.path.lexists(target):
        raise FileExistsError(f"Refusing to overwrite existing project: {target}")
    source_file = detect_source(source)
    media_probe = probe_media(source_file)

    parent_existed = parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{safe_video_id}.", suffix=".tmp", dir=parent))
    try:
        for directory in PROJECT_DIRS:
            (staging / directory).mkdir()
        shutil.copy2(source_file, staging / "source" / source_file.name)
        project = _project_config(
            target, safe_video_id, source_file.name, canonical_preset,
            title=title, profile=profile, media_probe=media_probe,
        )
        with (staging / "project.yaml").open("w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(project, handle, allow_unicode=True, sort_keys=False)
        initialization_report = {
            "schema_version": 1,
            "status": "initialized",
            "video_id": safe_video_id,
            "preset": canonical_preset,
            "source_file": (Path("source") / source_file.name).as_posix(),
            "media": media_probe,
            "created_directories": list(PROJECT_DIRS),
            "next_commands": [
                f"python scripts/director.py preflight --project {target / 'project.yaml'}",
                f"python scripts/director.py run --project {target / 'project.yaml'}",
            ],
        }
        (staging / "initialization-report.json").write_text(
            json.dumps(initialization_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging / "INITIALIZATION.md").write_text(
            "# Project initialized\n\n"
            f"- Video ID: {safe_video_id}\n"
            f"- Preset: {canonical_preset}\n"
            f"- Orientation: {media_probe.get('orientation', 'unknown')}\n"
            f"- Probe status: {media_probe.get('status', 'unavailable')}\n\n"
            "Run `director.py preflight` before starting the workflow.\n",
            encoding="utf-8",
        )
        if os.path.lexists(target):
            raise FileExistsError(f"Refusing to overwrite existing project: {target}")
        os.rename(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if not parent_existed:
            try:
                parent.rmdir()
            except OSError:
                pass
        raise
    return target / "project.yaml"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", nargs="?", choices=("init",), help=argparse.SUPPRESS)
    root.add_argument("--root", required=True, help="Parent directory for the new project")
    root.add_argument("--video-id", required=True)
    root.add_argument(
        "--source", default=".", help="Media file or directory containing one media file",
    )
    root.add_argument("--preset", choices=sorted(PRESETS), default="auto")
    root.add_argument("--title")
    root.add_argument("--profile")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        project_file = initialize_project(
            args.root, args.video_id, args.source, preset=args.preset,
            title=args.title, profile=args.profile,
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(json.dumps({"ok": False, "status": "fail", "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "status": "pass", "project": str(project_file)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
