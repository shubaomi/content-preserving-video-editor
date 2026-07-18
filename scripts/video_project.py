#!/usr/bin/env python3
"""Initialize, validate, inspect, and coverage-audit video projects."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from project_config import CURRENT_PROJECT_SCHEMA_VERSION, migrate_project_config


MODES = {"preserve", "balanced", "tight"}
PROJECT_DIRS = ("source", "edit", "hyperframes", "scripts", "work", "exports")


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return value


def resolve(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def ffprobe(path: Path) -> dict:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is not available on PATH")
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,display_aspect_ratio,r_frame_rate,sample_rate,channels:stream_tags=rotate:stream_side_data=rotation",
        "-of", "json", str(path),
    ]
    result = json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))
    video = next((s for s in result.get("streams", []) if s.get("codec_type") == "video"), None)
    if video:
        rotation = int((video.get("tags") or {}).get("rotate", 0) or 0)
        for side_data in video.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = int(side_data["rotation"] or 0)
                break
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        if abs(rotation) % 180 == 90:
            width, height = height, width
        ratio = width / height if height else 0
        orientation = "portrait" if ratio < 0.85 else "square" if ratio <= 1.2 else "landscape"
        standard_ratio = "9:16" if orientation == "portrait" else "1:1" if orientation == "square" else "16:9"
        result["display"] = {
            "width": width,
            "height": height,
            "rotation": rotation,
            "aspect_ratio": round(ratio, 6),
            "orientation": orientation,
            "recommended_canvas": standard_ratio,
        }
    return result


def project_paths(project_file: Path, project: dict) -> dict[str, Path | None]:
    paths = project.get("paths") or {}
    root = resolve(project_file.parent, paths.get("root")) or project_file.parent
    result: dict[str, Path | None] = {"root": root}
    for name in PROJECT_DIRS:
        result[name] = resolve(root, paths.get(name, name)) or root / name
    source = project.get("source") or {}
    result["primary_video"] = resolve(root, source.get("primary_video"))
    return result


def validate_project(project_file: Path) -> list[str]:
    errors: list[str] = []
    try:
        project = migrate_project_config(load_yaml(project_file))
    except ValueError as error:
        return [str(error)]
    for key in ("version", "video_id", "paths", "source"):
        if key not in project:
            errors.append(f"missing project field: {key}")
    mode = (project.get("editing") or {}).get("mode", "preserve")
    if mode not in MODES:
        errors.append(f"editing.mode must be one of {sorted(MODES)}")
    paths = project_paths(project_file, project)
    for key in ("root", *PROJECT_DIRS):
        path = paths[key]
        if path is None or not path.exists():
            errors.append(f"missing directory {key}: {path}")
    video = paths.get("primary_video")
    if video is None or not video.is_file():
        errors.append(f"missing source.primary_video: {video}")
    profile_value = project.get("profile")
    if profile_value:
        profile_file = resolve(project_file.parent, profile_value)
        if profile_file is None or not profile_file.is_file():
            errors.append(f"missing profile: {profile_file}")
        else:
            profile = load_yaml(profile_file)
            profile_root = resolve(profile_file.parent, (profile.get("paths") or {}).get("root")) or profile_file.parent
            character = profile.get("character") or {}
            for key in ("main_anchor", "spec_board", "action_sheet"):
                asset = resolve(profile_root, character.get(key))
                if asset is not None and not asset.is_file():
                    errors.append(f"missing profile character.{key}: {asset}")
            status = str(character.get("status", ""))
            if character and not status.startswith("confirmed"):
                errors.append("profile character.status must be confirmed before generating identity-sensitive assets")
    return errors


def init_project(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() / args.video_id
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty project: {root}")
    if args.dry_run:
        print(json.dumps({"root": str(root), "directories": list(PROJECT_DIRS)}, ensure_ascii=False, indent=2))
        return 0
    for directory in PROJECT_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    source_name = Path(args.source).name if args.source else "input.mp4"
    if args.source:
        source_path = Path(args.source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        shutil.copy2(source_path, root / "source" / source_name)
    project = {
        "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
        "version": CURRENT_PROJECT_SCHEMA_VERSION,
        "video_id": args.video_id,
        "title": args.title or args.video_id,
        "profile": str(Path(args.profile).resolve()) if args.profile else None,
        "paths": {"root": str(root), **{name: name for name in PROJECT_DIRS}},
        "source": {"primary_video": f"source/{source_name}"},
        "editing": {
            "mode": args.mode,
            "require_cut_report": True,
            "require_tail_coverage_check": True,
            "allow_long_semantic_deletion_without_confirmation": False,
        },
        "hyperframes": {
            "studio_entry": "hyperframes/index.html",
            "overlay_source": "hyperframes/overlay-source.html.txt",
        },
        "audio": {
            "sfx": {"enabled": True, "volume": 0.28, "max_cues_per_minute": 6,
                    "max_event_ratio": 1.0, "same_file_cooldown_seconds": 45,
                    "target_event_coverage": 1.0, "minimum_unique_asset_ratio": 0.8,
                    "minimum_cue_duration_seconds": 0.8,
                    "minimum_post_gain_mean_dbfs": -34,
                    "maximum_post_gain_mean_dbfs": -18},
            "bgm": {
                "enabled_by_default": True,
                "optional": True,
                "asset": None,
                "providers": ["heygen", "minimax", "musicgen"],
                "stop_after_first_success": True,
                "preview_volume": 0.1,
                "ducking": {
                    "enabled": True,
                    "method": "sidechaincompress",
                    "threshold": 0.03,
                    "ratio": 8,
                    "attack_ms": 200,
                    "release_ms": 400,
                },
            },
        },
        "editable_motion": {"require_separate_layout_and_motion_layers": True, "profile": "adaptive_dynamic", "event_rate_policy": "advisory_ceiling", "recommended_events_per_minute": {"screen_tutorial": [4, 10], "polish_existing": [3, 7]}, "maximum_visual_quiet_gap_seconds": 12, "anchor_repeat_cooldown_seconds": 40},
    }
    project = migrate_project_config(project)
    with (root / "project.yaml").open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(project, handle, allow_unicode=True, sort_keys=False)
    print(root / "project.yaml")
    return 0


def inspect_media(args: argparse.Namespace) -> int:
    path = Path(args.media).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    print(json.dumps(ffprobe(path), ensure_ascii=False, indent=2))
    return 0


def merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(ranges):
        if end <= start:
            raise ValueError(f"Invalid range: {start}-{end}")
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def omitted_ranges(ranges: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    omitted: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in ranges:
        if start > cursor:
            omitted.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        omitted.append((cursor, duration))
    return omitted


def audit(args: argparse.Namespace) -> int:
    project_file = Path(args.project).resolve()
    project = load_yaml(project_file)
    paths = project_paths(project_file, project)
    video = paths["primary_video"]
    if video is None or not video.is_file():
        raise FileNotFoundError(video)
    duration = float(ffprobe(video)["format"]["duration"])
    edl = json.loads(Path(args.edl).resolve().read_text(encoding="utf-8"))
    ranges = merge_ranges([(float(item["start"]), float(item["end"])) for item in edl.get("ranges", [])])
    for start, end in ranges:
        if start < 0 or end > duration + 0.05:
            raise ValueError(f"EDL range outside source duration: {start}-{end}, duration={duration}")
    kept = sum(end - start for start, end in ranges)
    first = ranges[0][0] if ranges else None
    last = ranges[-1][1] if ranges else None
    tail_gap = duration - last if last is not None else duration
    omitted = omitted_ranges(ranges, duration)
    long_omissions = [
        {"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)}
        for start, end in omitted
        if end - start >= args.long_gap
    ]
    report = {
        "source": str(video),
        "source_duration_s": round(duration, 3),
        "kept_source_duration_s": round(kept, 3),
        "source_coverage_ratio": round(kept / duration, 4) if duration else 0,
        "first_used_source_s": first,
        "last_used_source_s": last,
        "tail_gap_s": round(tail_gap, 3),
        "omitted_intervals_over_threshold": long_omissions,
        "long_gap_threshold_s": args.long_gap,
        "complete_label_allowed": tail_gap <= args.max_tail_gap,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["complete_label_allowed"] else 2


def validate(args: argparse.Namespace) -> int:
    project_file = Path(args.project).resolve()
    errors = validate_project(project_file)
    print(json.dumps({"project": str(project_file), "ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    create = sub.add_parser("init")
    create.add_argument("--root", required=True)
    create.add_argument("--video-id", required=True)
    create.add_argument("--source")
    create.add_argument("--profile")
    create.add_argument("--title")
    create.add_argument("--mode", choices=sorted(MODES), default="preserve")
    create.add_argument("--dry-run", action="store_true")
    create.set_defaults(func=init_project)
    check = sub.add_parser("validate")
    check.add_argument("--project", required=True)
    check.set_defaults(func=validate)
    media = sub.add_parser("inspect")
    media.add_argument("--media", required=True)
    media.set_defaults(func=inspect_media)
    coverage = sub.add_parser("audit")
    coverage.add_argument("--project", required=True)
    coverage.add_argument("--edl", required=True)
    coverage.add_argument("--max-tail-gap", type=float, default=10.0)
    coverage.add_argument("--long-gap", type=float, default=15.0)
    coverage.set_defaults(func=audit)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, yaml.YAMLError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
