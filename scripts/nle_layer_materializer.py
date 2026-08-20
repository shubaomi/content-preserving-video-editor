#!/usr/bin/env python3
"""Materialize editable HyperFrames motion layers for manual NLE handoff.

The output is editor-neutral media plus evidence.  It never writes a Jianying
draft and never upgrades compatibility without the named human import canary.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from director_contracts import read_json, sha256_file
from safe_generated_output import (
    SafeGeneratedOutputError,
    atomic_replace_file,
    atomic_write_text,
    safe_generated_directory,
    safe_generated_target,
)


class NleLayerMaterializationError(ValueError):
    """Raised when a truthful removable layer cannot be produced."""


_IMPLEMENTATION = Path(__file__).resolve()


def _stable_hash(payload: Mapping[str, Any], field: str = "integrity_sha256") -> str:
    value = dict(payload)
    value.pop(field, None)
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _finite(value: Any, *, nonnegative: bool = False, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    if not math.isfinite(number):
        return False
    if nonnegative and number < 0:
        return False
    if positive and number <= 0:
        return False
    return True


def _is_redirected(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(os.path, "isjunction", lambda _value: False)(path)
    )


def _safe_source_tree(root: Path) -> list[Path]:
    lexical = Path(os.path.abspath(root))
    if not lexical.is_dir():
        raise NleLayerMaterializationError("HyperFrames source project is missing")
    for candidate in (lexical, *lexical.parents):
        if candidate.exists() and _is_redirected(candidate):
            raise NleLayerMaterializationError("HyperFrames source project is redirected")
    resolved = lexical.resolve()
    files: list[Path] = []
    for path in sorted(lexical.rglob("*")):
        if _is_redirected(path):
            raise NleLayerMaterializationError(
                f"HyperFrames source project contains redirected content: {path}"
            )
        if path.is_file():
            if not path.resolve().is_relative_to(resolved):
                raise NleLayerMaterializationError("HyperFrames source project escapes its root")
            files.append(path)
    return files


def source_project_tree_sha256(root: Path) -> str:
    lexical = Path(os.path.abspath(root))
    files = _safe_source_tree(lexical)
    resolved = lexical.resolve()
    digest = hashlib.sha256()
    for path in files:
        relative = str(path.resolve().relative_to(resolved)).replace("\\", "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _event_window(event: Mapping[str, Any]) -> tuple[float, float]:
    window = event.get("outputWindow")
    if not isinstance(window, Mapping):
        raise NleLayerMaterializationError("motion event output window is invalid")
    start, end = window.get("start_seconds"), window.get("end_seconds")
    if not _finite(start, nonnegative=True) or not _finite(end, positive=True):
        raise NleLayerMaterializationError("motion event output window must be finite")
    if float(end) <= float(start):
        raise NleLayerMaterializationError("motion event output window is empty")
    return float(start), float(end)


def hyperframes_frame_rate_argument(value: Any) -> str:
    """Serialize a measured rate without HyperFrames' ambiguous decimals."""
    if not _finite(value, positive=True):
        raise NleLayerMaterializationError("motion layer frame rate is invalid")
    number = float(value)
    rounded = round(number)
    if abs(number - rounded) <= 1e-9:
        return str(rounded)
    fraction = Fraction(number).limit_denominator(100_000)
    if abs(float(fraction) - number) > 1e-7:
        raise NleLayerMaterializationError("motion layer frame rate is not exact")
    return f"{fraction.numerator}/{fraction.denominator}"


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return _stable_hash(payload, field="payload_sha256")


def _safe_event_stem(event: Mapping[str, Any]) -> str:
    semantic = event.get("semanticEventId")
    rendered = event.get("eventId")
    if not isinstance(semantic, str) or not semantic or not isinstance(rendered, str) or not rendered:
        raise NleLayerMaterializationError("motion event identity is invalid")
    value = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in semantic)
    value = value.strip(".-")
    if not value:
        value = hashlib.sha256(semantic.encode("utf-8")).hexdigest()[:16]
    return value


def _atomic_directory_publish(staging: Path, output: Path) -> None:
    backup = output.parent / f".{output.name}.backup-{uuid.uuid4().hex}"
    had_previous = output.exists()
    def replace(source: Path, target: Path) -> None:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(source, target)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    if had_previous:
        replace(output, backup)
    try:
        replace(staging, output)
    except Exception:
        if had_previous and backup.exists():
            replace(backup, output)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def build_event_overlay_project(
    *, source_project: Path, output_project: Path, event: Mapping[str, Any],
    authorized_root: Path,
) -> dict[str, Any]:
    """Create one zero-based, transparent derivative without mutating source."""
    source_project = Path(os.path.abspath(source_project))
    authorized_root = Path(os.path.abspath(authorized_root))
    authorized_resolved = safe_generated_directory(authorized_root, Path("."))
    _safe_source_tree(source_project)
    source_resolved = source_project.resolve()
    if not source_resolved.is_relative_to(authorized_resolved):
        raise NleLayerMaterializationError("HyperFrames source project is outside authorized root")
    start, end = _event_window(event)
    duration = end - start
    index_path = source_project / "index.html"
    try:
        html = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise NleLayerMaterializationError("HyperFrames source index is unreadable") from error
    base_media: set[str] = set()
    for tag_name, element_id in (("video", "a-roll"), ("audio", "a-roll-audio")):
        tag_match = re.search(
            rf"<{tag_name}\b(?=[^>]*\bid=[\"']{re.escape(element_id)}[\"'])[^>]*>",
            html, flags=re.IGNORECASE,
        )
        if tag_match:
            source_match = re.search(
                r"\bsrc=[\"']([^\"']+)[\"']", tag_match.group(0), flags=re.IGNORECASE,
            )
            if source_match and not re.match(r"^[a-z]+:", source_match.group(1), re.I):
                base_media.add(source_match.group(1).replace("\\", "/").lstrip("./"))
    output_lexical = Path(os.path.abspath(output_project))
    if not output_lexical.is_relative_to(authorized_root):
        raise NleLayerMaterializationError("event overlay project is outside authorized root")
    try:
        relative_parent = output_lexical.parent.relative_to(authorized_root)
        safe_generated_directory(authorized_root, relative_parent)
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleLayerMaterializationError(str(error)) from error
    staging = safe_generated_directory(
        output_lexical.parent,
        Path(f".{output_lexical.name}.staging-{uuid.uuid4().hex}"),
    )
    try:
        for source in _safe_source_tree(source_project):
            relative = source.resolve().relative_to(source_resolved)
            rendered_relative = str(relative).replace("\\", "/")
            if rendered_relative in base_media:
                continue
            if relative.name in {"index.html", "renderer-payload.json"}:
                continue
            target = safe_generated_target(staging, relative)
            atomic_replace_file(source, target)

        original_payload = read_json(source_project / "renderer-payload.json")
        if not isinstance(original_payload, Mapping):
            raise NleLayerMaterializationError("renderer payload must be an object")
        selected = copy.deepcopy(dict(event))
        selected["outputWindow"] = {
            "start_seconds": 0.0, "end_seconds": round(duration, 6),
        }
        payload = copy.deepcopy(dict(original_payload))
        payload["events"] = [selected]
        payload["payload_sha256"] = _payload_hash(payload)
        payload_path = safe_generated_target(staging, Path("renderer-payload.json"))
        atomic_write_text(
            payload_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        )

        html = re.sub(
            r"<video\b[^>]*\bid=[\"']a-roll[\"'][^>]*>.*?</video>",
            "", html, flags=re.IGNORECASE | re.DOTALL,
        )
        html = re.sub(
            r"<audio\b[^>]*\bid=[\"']a-roll-audio[\"'][^>]*>.*?</audio>",
            "", html, flags=re.IGNORECASE | re.DOTALL,
        )
        if any(value in html for value in base_media):
            raise NleLayerMaterializationError("overlay derivative still references source media")
        rendered_payload = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        html, replacements = re.subn(
            r"const payload=\{.*?\};\s*const master=",
            f"const payload={rendered_payload};\nconst master=",
            html, count=1, flags=re.DOTALL,
        )
        if replacements != 1:
            raise NleLayerMaterializationError("HyperFrames renderer payload injection is unavailable")
        html, duration_replacements = re.subn(
            r'(data-duration=[\"\'])[^\"\']+([\"\'])',
            rf"\g<1>{duration:.6f}\g<2>", html, count=1,
        )
        if duration_replacements != 1:
            raise NleLayerMaterializationError("HyperFrames composition duration is unavailable")
        html = html.replace(
            "</head>",
            "<style>html,body,#root{background:transparent!important}</style></head>",
            1,
        )
        target_index = safe_generated_target(staging, Path("index.html"))
        atomic_write_text(target_index, html)
        _atomic_directory_publish(staging, output_lexical)
        return {
            "project": output_lexical.resolve(),
            "duration_seconds": round(duration, 6),
            "timeline_start_seconds": start,
            "timeline_end_seconds": end,
            "semantic_event_id": selected["semanticEventId"],
            "render_event_id": selected["eventId"],
            "payload_sha256": payload["payload_sha256"],
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 600) -> None:
    try:
        subprocess.run(
            command, cwd=cwd, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or error.stdout or "").strip()
        raise NleLayerMaterializationError(
            "external layer materialization failed" + (f": {detail[-1000:]}" if detail else "")
        ) from error


def _probe_video(path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,profile,width,height,pix_fmt,avg_frame_rate:stream_tags=alpha_mode:format=duration",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        numerator, denominator = str(stream["avg_frame_rate"]).split("/", 1)
        return {
            "codec_name": str(stream["codec_name"]),
            "profile": str(stream.get("profile") or ""),
            "width": int(stream["width"]), "height": int(stream["height"]),
            "pixel_format": str(stream["pix_fmt"]),
            "frame_rate": float(numerator) / float(denominator),
            "duration_seconds": float(payload["format"]["duration"]),
            "alpha_mode": (stream.get("tags") or {}).get("alpha_mode"),
        }
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, TypeError,
            ValueError, json.JSONDecodeError, ZeroDivisionError) as error:
        raise NleLayerMaterializationError("rendered motion layer cannot be probed") from error


def _extract_rgba_frame(video: Path, timestamp: float, output: Path) -> None:
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.6f}",
        "-i", str(video), "-frames:v", "1", "-pix_fmt", "rgba", str(output),
    ], timeout=60)


def _alpha_stats(path: Path) -> dict[str, Any]:
    try:
        image = Image.open(path).convert("RGBA")
        alpha = image.getchannel("A")
        minimum, maximum = alpha.getextrema()
        histogram = alpha.histogram()
    except (OSError, ValueError) as error:
        raise NleLayerMaterializationError("motion alpha evidence is not a decodable image") from error
    pixels = image.width * image.height
    visible = sum(histogram[1:])
    return {
        "width": image.width, "height": image.height,
        "minimum_alpha": minimum, "maximum_alpha": maximum,
        "visible_ratio": visible / pixels,
    }


def _alpha_capable(pixel_format: Any, alpha_mode: Any) -> bool:
    value = str(pixel_format or "").lower()
    return str(alpha_mode) == "1" or value.startswith(
        ("yuva", "rgba", "argb", "bgra", "abgr", "gbrap", "ya")
    )


def _composite_backgrounds(width: int, height: int) -> dict[str, Image.Image]:
    backgrounds = {
        "black": Image.new("RGBA", (width, height), (0, 0, 0, 255)),
        "white": Image.new("RGBA", (width, height), (255, 255, 255, 255)),
    }
    busy = Image.new("RGBA", (width, height), (30, 42, 54, 255))
    block = max(8, min(width, height) // 12)
    pixels = busy.load()
    for y in range(height):
        for x in range(width):
            if ((x // block) + (y // block)) % 2:
                pixels[x, y] = (214, 219, 224, 255)
    backgrounds["busy"] = busy
    return backgrounds


def _contained_current_file(root: Path, value: Any) -> tuple[Path | None, str | None]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return None, "file reference is malformed"
    candidate = (root / value["path"]).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        return None, "file reference is missing or outside evidence root"
    if value.get("sha256") != sha256_file(candidate):
        return None, "file reference is stale"
    return candidate, None


def validate_alpha_evidence(
    evidence_path: Path, *, overlay: Path, expected_video: Mapping[str, Any],
    expected_duration: float, expected_frame_rate: float,
) -> list[str]:
    """Recompute the current alpha proof instead of trusting its declarations."""
    try:
        payload = read_json(evidence_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["motion alpha evidence is unreadable"]
    if not isinstance(payload, Mapping):
        return ["motion alpha evidence must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != 1 or payload.get("kind") != "nle_motion_alpha_evidence" or payload.get("status") != "pass":
        errors.append("motion alpha evidence identity is invalid")
    try:
        if payload.get("integrity_sha256") != _stable_hash(payload):
            errors.append("motion alpha evidence integrity is stale")
    except (TypeError, ValueError):
        errors.append("motion alpha evidence is not canonical")
    overlay = Path(overlay).resolve()
    if not overlay.is_file() or payload.get("video_sha256") != sha256_file(overlay):
        errors.append("motion alpha evidence video binding is stale")
        return errors
    try:
        actual_probe = _probe_video(overlay)
    except NleLayerMaterializationError as error:
        errors.append(str(error))
        return errors
    declared_probe = payload.get("probe")
    if not isinstance(declared_probe, Mapping):
        errors.append("motion alpha evidence probe is malformed")
    else:
        for key in ("codec_name", "profile", "width", "height", "pixel_format"):
            if declared_probe.get(key) != actual_probe.get(key):
                errors.append(f"motion alpha evidence probe {key} is stale")
        for key in ("frame_rate", "duration_seconds"):
            declared = declared_probe.get(key)
            actual = actual_probe.get(key)
            if not _finite(declared, positive=True) or not _finite(actual, positive=True) or abs(float(declared) - float(actual)) > 1e-6:
                errors.append(f"motion alpha evidence probe {key} is stale")
    for key in ("codec_name", "profile", "width", "height", "pixel_format"):
        if expected_video.get(key) != actual_probe.get(key):
            errors.append(f"motion alpha evidence differs from expected video {key}")
    if (
        expected_video.get("alpha_status") != "verified"
        or actual_probe.get("codec_name") != "prores"
        or "4444" not in str(actual_probe.get("profile"))
        or not _alpha_capable(actual_probe.get("pixel_format"), actual_probe.get("alpha_mode"))
    ):
        errors.append("motion alpha evidence does not prove an alpha-capable stream")
    tolerance = max(0.05, 1.5 / float(expected_frame_rate))
    if not _finite(expected_duration, positive=True) or abs(float(actual_probe["duration_seconds"]) - float(expected_duration)) > tolerance:
        errors.append("motion alpha evidence duration differs from event window")
    if not _finite(expected_frame_rate, positive=True) or abs(float(actual_probe["frame_rate"]) - float(expected_frame_rate)) > 0.001:
        errors.append("motion alpha evidence frame rate differs from timeline")

    root = Path(evidence_path).resolve().parent
    computed: dict[str, dict[str, Any]] = {}
    computed_paths: dict[str, Path] = {}
    for label in ("midpoint", "post_exit"):
        row = payload.get(label)
        path, reference_error = _contained_current_file(root, row)
        if reference_error or path is None:
            errors.append(f"motion alpha {label} {reference_error}")
            continue
        try:
            stats = _alpha_stats(path)
        except NleLayerMaterializationError as error:
            errors.append(str(error))
            continue
        computed[label] = stats
        computed_paths[label] = path
        if stats["width"] != actual_probe["width"] or stats["height"] != actual_probe["height"]:
            errors.append(f"motion alpha {label} canvas differs from the rendered video")
        if not isinstance(row, Mapping):
            continue
        for key in ("width", "height", "minimum_alpha", "maximum_alpha"):
            if row.get(key) != stats[key]:
                errors.append(f"motion alpha {label} {key} is stale")
        declared_ratio = row.get("visible_ratio")
        if not _finite(declared_ratio, nonnegative=True) or abs(float(declared_ratio) - stats["visible_ratio"]) > 1e-9:
            errors.append(f"motion alpha {label} visible ratio is stale")
    middle = computed.get("midpoint")
    if middle and (middle["maximum_alpha"] <= 0 or not 0.0001 <= middle["visible_ratio"] < 0.95):
        errors.append("motion alpha midpoint is empty or effectively opaque")
    exited = computed.get("post_exit")
    if exited and exited["maximum_alpha"] > 8:
        errors.append("motion alpha post-exit frame is not clean")
    composites = payload.get("composites")
    seen: set[str] = set()
    if not isinstance(composites, list):
        errors.append("motion alpha composite proofs are missing")
    else:
        for row in composites:
            kind = row.get("kind") if isinstance(row, Mapping) else None
            if kind not in {"black", "white", "busy"} or kind in seen:
                errors.append("motion alpha composite proof identity is invalid")
                continue
            seen.add(kind)
            path, reference_error = _contained_current_file(root, row)
            if reference_error or path is None:
                errors.append(f"motion alpha {kind} composite {reference_error}")
                continue
            try:
                image = Image.open(path).convert("RGB")
            except (OSError, ValueError):
                errors.append(f"motion alpha {kind} composite is not decodable")
                continue
            midpoint_path = computed_paths.get("midpoint")
            if midpoint_path is not None:
                try:
                    overlay_image = Image.open(midpoint_path).convert("RGBA")
                    expected = _composite_backgrounds(
                        overlay_image.width, overlay_image.height,
                    )[kind]
                    expected.alpha_composite(overlay_image)
                    if image.size != expected.size or image.tobytes() != expected.convert("RGB").tobytes():
                        errors.append(f"motion alpha {kind} composite differs from midpoint alpha")
                except (OSError, ValueError):
                    errors.append(f"motion alpha {kind} composite could not be recomputed")
        if seen != {"black", "white", "busy"}:
            errors.append("motion alpha composite proof inventory is incomplete")
    return errors


def _archive_matches_source(archive_path: Path, source_project: Path) -> bool:
    try:
        source_files = _safe_source_tree(source_project)
        expected = {
            str(path.resolve().relative_to(source_project.resolve())).replace("\\", "/"): path
            for path in source_files
        }
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != set(expected):
                return False
            for info in infos:
                if info.is_dir() or Path(info.filename).is_absolute() or ".." in Path(info.filename).parts:
                    return False
                if archive.read(info) != expected[info.filename].read_bytes():
                    return False
    except (OSError, ValueError, zipfile.BadZipFile, NleLayerMaterializationError):
        return False
    return True


def _contained_manifest_ref(root: Path, value: Any) -> Path | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return None
    raw = Path(value["path"])
    if raw.is_absolute() or ".." in raw.parts:
        return None
    candidate = (root / raw).resolve()
    return candidate if candidate.is_relative_to(root.resolve()) else None


def _expected_event_payload(
    renderer_payload: Mapping[str, Any], event: Mapping[str, Any],
) -> tuple[str, float, float]:
    start, end = _event_window(event)
    selected = copy.deepcopy(dict(event))
    selected["outputWindow"] = {
        "start_seconds": 0.0,
        "end_seconds": round(end - start, 6),
    }
    payload = copy.deepcopy(dict(renderer_payload))
    payload["events"] = [selected]
    payload["payload_sha256"] = _payload_hash(payload)
    return str(payload["payload_sha256"]), start, end


def _composite_proofs(frame: Path, output_dir: Path) -> list[dict[str, str]]:
    overlay = Image.open(frame).convert("RGBA")
    width, height = overlay.size
    backgrounds = _composite_backgrounds(width, height)
    results: list[dict[str, str]] = []
    for name, background in backgrounds.items():
        path = safe_generated_target(output_dir, Path(f"composite-{name}.png"))
        background.alpha_composite(overlay)
        background.convert("RGB").save(path, format="PNG")
        results.append({"kind": name, "path": path.name, "sha256": sha256_file(path)})
    return results


def materialize_existing_alpha_evidence(
    *, overlay: Path, evidence_dir: Path, authorized_root: Path,
    expected_width: int, expected_height: int, expected_duration: float,
    expected_frame_rate: float,
) -> dict[str, Any]:
    """Build fresh, hash-bound alpha/decode evidence for an existing render."""
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (expected_width, expected_height)
    ):
        raise NleLayerMaterializationError("motion alpha evidence canvas is invalid")
    if not _finite(expected_duration, positive=True) or not _finite(
        expected_frame_rate, positive=True,
    ):
        raise NleLayerMaterializationError("motion alpha evidence timing is invalid")
    overlay = Path(overlay).resolve()
    if not overlay.is_file():
        raise NleLayerMaterializationError("motion alpha overlay is missing")
    authorized_root = Path(os.path.abspath(authorized_root))
    evidence_lexical = Path(os.path.abspath(evidence_dir))
    try:
        evidence_relative = evidence_lexical.relative_to(authorized_root)
        evidence_dir = safe_generated_directory(authorized_root, evidence_relative)
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleLayerMaterializationError(str(error)) from error

    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(overlay),
        "-map", "0:v:0", "-f", "null", os.devnull,
    ], timeout=180)
    probe = _probe_video(overlay)
    tolerance = max(0.05, 1.5 / float(expected_frame_rate))
    if probe["width"] != expected_width or probe["height"] != expected_height:
        raise NleLayerMaterializationError("motion layer canvas differs from the output timeline")
    if abs(probe["frame_rate"] - float(expected_frame_rate)) > 0.001:
        raise NleLayerMaterializationError("motion layer frame rate differs from the output timeline")
    if abs(probe["duration_seconds"] - float(expected_duration)) > tolerance:
        raise NleLayerMaterializationError("motion layer duration differs from its event window")
    if probe.get("codec_name") != "prores" or "4444" not in str(probe.get("profile")):
        raise NleLayerMaterializationError("motion layer is not ProRes 4444")
    if not _alpha_capable(probe.get("pixel_format"), probe.get("alpha_mode")):
        raise NleLayerMaterializationError("motion layer codec does not expose an alpha channel")

    midpoint = safe_generated_target(evidence_dir, Path("midpoint.png"))
    post_exit = safe_generated_target(evidence_dir, Path("post-exit.png"))
    _extract_rgba_frame(
        overlay, min(float(expected_duration) / 2, max(0.001, float(expected_duration) - 0.08)),
        midpoint,
    )
    _extract_rgba_frame(overlay, max(0.001, float(expected_duration) - 0.04), post_exit)
    middle = _alpha_stats(midpoint)
    exit_stats = _alpha_stats(post_exit)
    if middle["maximum_alpha"] <= 0 or not 0.0001 <= middle["visible_ratio"] < 0.95:
        raise NleLayerMaterializationError("motion layer alpha is empty or effectively opaque")
    if exit_stats["maximum_alpha"] > 8:
        raise NleLayerMaterializationError("motion layer does not cleanly exit its event window")
    evidence = {
        "schema_version": 1,
        "kind": "nle_motion_alpha_evidence",
        "status": "pass",
        "video_sha256": sha256_file(overlay),
        "probe": probe,
        "midpoint": {
            "path": midpoint.name, "sha256": sha256_file(midpoint), **middle,
        },
        "post_exit": {
            "path": post_exit.name, "sha256": sha256_file(post_exit), **exit_stats,
        },
        "composites": _composite_proofs(midpoint, evidence_dir),
    }
    evidence["integrity_sha256"] = _stable_hash(evidence)
    evidence_path = safe_generated_target(evidence_dir, Path("alpha-evidence.json"))
    atomic_write_text(
        evidence_path,
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    video_metadata = {
        "codec_name": probe["codec_name"], "profile": probe["profile"],
        "width": expected_width, "height": expected_height,
        "pixel_format": probe["pixel_format"], "alpha_status": "verified",
        "decode_receipt": {
            "path": str(evidence_path), "sha256": sha256_file(evidence_path),
        },
    }
    errors = validate_alpha_evidence(
        evidence_path,
        overlay=overlay,
        expected_video=video_metadata,
        expected_duration=float(expected_duration),
        expected_frame_rate=float(expected_frame_rate),
    )
    if errors:
        raise NleLayerMaterializationError(
            "motion alpha evidence failed:\n- " + "\n- ".join(errors)
        )
    return video_metadata


def _render_event(
    *, project: Path, output: Path, evidence_dir: Path, duration: float,
    width: int, height: int, frame_rate: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = shutil.which("npx")
    if not executable:
        raise NleLayerMaterializationError("npx is required for HyperFrames layer rendering")
    output.parent.mkdir(parents=True, exist_ok=True)
    # HyperFrames creates a sibling transaction directory beside its output.
    # Real Windows project roots can exceed MAX_PATH once that suffix is added,
    # so render in a short OS temp directory and atomically publish verified
    # bytes back into the authorized project tree.
    with tempfile.TemporaryDirectory(prefix="nle-motion-") as render_folder:
        rendered = Path(render_folder) / "overlay.mov"
        _run([
            executable, "--yes", "hyperframes", "render", str(project), "--format", "mov",
            "--strict", "--quiet", "--workers", "1", "--fps",
            hyperframes_frame_rate_argument(frame_rate),
            "--output", str(rendered),
        ], timeout=900)
        if not rendered.is_file():
            raise NleLayerMaterializationError("HyperFrames did not produce the motion layer")
        atomic_replace_file(rendered, output)
    video_metadata = materialize_existing_alpha_evidence(
        overlay=output, evidence_dir=evidence_dir,
        authorized_root=evidence_dir.parent,
        expected_width=width, expected_height=height,
        expected_duration=duration, expected_frame_rate=frame_rate,
    )
    evidence_path = Path(video_metadata["decode_receipt"]["path"])
    evidence = read_json(evidence_path)
    return video_metadata, evidence


def _archive_project(source_project: Path, target: Path) -> None:
    files = _safe_source_tree(source_project)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                relative = str(path.resolve().relative_to(source_project.resolve())).replace("\\", "/")
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _resolve_manifest_ref(root: Path, value: Any) -> Path | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return None
    path = Path(value["path"])
    if path.is_absolute():
        return path.resolve()
    return (root / path).resolve()


def validate_motion_layer_manifest(path: Path) -> list[str]:
    lexical_path = Path(os.path.abspath(path))
    for candidate in (lexical_path, *lexical_path.parents):
        if candidate.exists() and _is_redirected(candidate):
            return ["motion layer manifest path is redirected"]
    try:
        payload = read_json(lexical_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["motion layer manifest is unreadable"]
    if not isinstance(payload, Mapping):
        return ["motion layer manifest must be an object"]
    root = lexical_path.resolve().parent
    errors: list[str] = []
    if payload.get("schema_version") != 1 or payload.get("kind") != "nle_motion_layer_materialization":
        errors.append("motion layer manifest identity is invalid")
    try:
        if payload.get("integrity_sha256") != _stable_hash(payload):
            errors.append("motion layer manifest integrity is stale")
    except (TypeError, ValueError):
        errors.append("motion layer manifest is not canonical")
    implementation = payload.get("implementation_sha256")
    if implementation != sha256_file(_IMPLEMENTATION):
        errors.append("motion layer implementation binding is stale")
    if payload.get("status") != "pass":
        errors.append("motion layer manifest status is not pass")
    source = payload.get("source_project")
    source_path = _resolve_manifest_ref(root, source)
    if not isinstance(source, Mapping) or source_path is None or not source_path.is_dir():
        errors.append("motion layer source project is missing")
    else:
        try:
            if source.get("tree_sha256") != source_project_tree_sha256(source_path):
                errors.append("motion layer source project is stale")
        except NleLayerMaterializationError:
            errors.append("motion layer source project is invalid")
    renderer_payload: Mapping[str, Any] | None = None
    renderer = payload.get("renderer_payload")
    renderer_path = _resolve_manifest_ref(root, renderer)
    if not isinstance(renderer, Mapping) or renderer_path is None or not renderer_path.is_file():
        errors.append("motion layer renderer payload is missing")
    elif renderer.get("sha256") != sha256_file(renderer_path):
        errors.append("motion layer renderer payload is stale")
    else:
        try:
            loaded_renderer = read_json(renderer_path)
            if not isinstance(loaded_renderer, Mapping):
                errors.append("motion layer renderer payload must be an object")
            else:
                renderer_payload = loaded_renderer
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("motion layer renderer payload is unreadable")
    archive = payload.get("source_project_archive")
    archive_path = _contained_manifest_ref(root, archive)
    if not isinstance(archive, Mapping) or archive_path is None or not archive_path.is_file():
        errors.append("motion layer source project archive is missing")
    elif archive.get("sha256") != sha256_file(archive_path):
        errors.append("motion layer source project archive is stale")
    elif source_path is None or not source_path.is_dir() or not _archive_matches_source(archive_path, source_path):
        errors.append("motion layer source project archive differs from current source")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        errors.append("motion layer manifest requires event outputs")
    else:
        identities: set[str] = set()
        render_identities: set[str] = set()
        expected_events = renderer_payload.get("events") if isinstance(renderer_payload, Mapping) else None
        if not isinstance(expected_events, list) or any(not isinstance(row, Mapping) for row in expected_events):
            errors.append("motion layer renderer event inventory is invalid")
            expected_events = []
        expected_semantic = [row.get("semanticEventId") for row in expected_events]
        expected_render = [row.get("eventId") for row in expected_events]
        actual_semantic = [row.get("semantic_event_id") if isinstance(row, Mapping) else None for row in events]
        actual_render = [row.get("render_event_id") if isinstance(row, Mapping) else None for row in events]
        if actual_semantic != expected_semantic or actual_render != expected_render:
            errors.append("motion layer event inventory differs from current renderer payload")
        for index, row in enumerate(events):
            if not isinstance(row, Mapping):
                errors.append("motion layer event record is malformed")
                continue
            semantic = row.get("semantic_event_id")
            if not isinstance(semantic, str) or not semantic or semantic in identities:
                errors.append("motion layer semantic event identity is missing or duplicate")
            else:
                identities.add(semantic)
            rendered = row.get("render_event_id")
            if not isinstance(rendered, str) or not rendered or rendered in render_identities:
                errors.append("motion layer render event identity is missing or duplicate")
            else:
                render_identities.add(rendered)
            for label in ("overlay", "alpha_evidence"):
                ref = row.get(label)
                ref_path = _contained_manifest_ref(root, ref)
                if not isinstance(ref, Mapping) or ref_path is None or not ref_path.is_file():
                    errors.append(f"motion layer event {label} is missing")
                elif ref.get("sha256") != sha256_file(ref_path):
                    errors.append(f"motion layer event {label} is stale")
            timeline = row.get("timeline")
            timeline_valid = (
                isinstance(timeline, Mapping)
                and _finite(timeline.get("start_seconds"), nonnegative=True)
                and _finite(timeline.get("end_seconds"), positive=True)
                and _finite(timeline.get("frame_rate"), positive=True)
            )
            if not timeline_valid:
                errors.append("motion layer event timeline is invalid")
            elif float(timeline["end_seconds"]) <= float(timeline["start_seconds"]):
                errors.append("motion layer event timeline is empty")
                timeline_valid = False
            video = row.get("video")
            if not isinstance(video, Mapping) or video.get("alpha_status") != "verified":
                errors.append("motion layer event lacks verified alpha evidence")
            else:
                decode = video.get("decode_receipt")
                decode_path = _resolve_manifest_ref(root, decode)
                alpha_path = _resolve_manifest_ref(root, row.get("alpha_evidence"))
                if (
                    not isinstance(decode, Mapping) or decode_path is None
                    or not decode_path.is_file() or decode_path != alpha_path
                ):
                    errors.append("motion layer event decode receipt is not current alpha evidence")
                elif decode.get("sha256") != sha256_file(decode_path):
                    errors.append("motion layer event decode receipt is stale")
            if index >= len(expected_events) or not timeline_valid or not isinstance(video, Mapping):
                continue
            try:
                expected_payload_hash, expected_start, expected_end = _expected_event_payload(
                    renderer_payload or {}, expected_events[index],
                )
            except NleLayerMaterializationError:
                errors.append("motion layer renderer event window is invalid")
                continue
            if row.get("payload_sha256") != expected_payload_hash:
                errors.append("motion layer event payload binding is stale")
            if float(timeline["start_seconds"]) != expected_start or float(timeline["end_seconds"]) != expected_end:
                errors.append("motion layer event timeline differs from renderer payload")
            overlay_path = _contained_manifest_ref(root, row.get("overlay"))
            alpha_path = _contained_manifest_ref(root, row.get("alpha_evidence"))
            if overlay_path is not None and alpha_path is not None:
                errors.extend(validate_alpha_evidence(
                    alpha_path,
                    overlay=overlay_path,
                    expected_video=video,
                    expected_duration=expected_end - expected_start,
                    expected_frame_rate=float(timeline["frame_rate"]),
                ))
    return errors


def _manifest_assets(payload: Mapping[str, Any], manifest_path: Path) -> dict[str, Any]:
    root = manifest_path.resolve().parent
    motion: list[dict[str, Any]] = []
    evidence: list[Path] = [manifest_path.resolve()]
    for row in payload.get("events") or []:
        overlay = _resolve_manifest_ref(root, row.get("overlay"))
        alpha = _resolve_manifest_ref(root, row.get("alpha_evidence"))
        if overlay is None or alpha is None:
            continue
        motion.append({
            "path": overlay,
            "semantic_event_id": row["semantic_event_id"],
            "render_event_id": row["render_event_id"],
            "timeline": dict(row["timeline"]),
            "video": {
                **dict(row["video"]),
                "decode_receipt": {
                    "path": str(alpha), "sha256": sha256_file(alpha),
                },
            },
        })
        evidence.append(alpha)
        alpha_payload = read_json(alpha)
        for key in ("midpoint", "post_exit"):
            ref = alpha_payload.get(key) or {}
            if isinstance(ref.get("path"), str):
                evidence.append((alpha.parent / ref["path"]).resolve())
        for ref in alpha_payload.get("composites") or []:
            if isinstance(ref, Mapping) and isinstance(ref.get("path"), str):
                evidence.append((alpha.parent / ref["path"]).resolve())
    archive = _resolve_manifest_ref(root, payload.get("source_project_archive"))
    return {
        "motion_event": motion,
        "hyperframes_project": archive,
        "evidence": sorted(set(evidence)),
    }


def materialize_motion_handoff_layers(
    *, source_project: Path, output_root: Path, authorized_root: Path,
    width: int, height: int, frame_rate: float, execute: bool,
) -> dict[str, Any] | None:
    """Reuse current evidence or render only the event-local alpha derivatives."""
    output_root = Path(os.path.abspath(output_root))
    manifest_path = output_root / "motion-layer-manifest.json"
    if manifest_path.is_file() and not validate_motion_layer_manifest(manifest_path):
        return _manifest_assets(read_json(manifest_path), manifest_path)
    if not execute:
        return None
    if isinstance(width, bool) or not isinstance(width, int) or width < 1 or isinstance(height, bool) or not isinstance(height, int) or height < 1 or not _finite(frame_rate, positive=True):
        raise NleLayerMaterializationError("motion layer canvas/rate is invalid")
    source_project = Path(os.path.abspath(source_project))
    _safe_source_tree(source_project)
    payload_path = source_project / "renderer-payload.json"
    payload = read_json(payload_path)
    events = payload.get("events") if isinstance(payload, Mapping) else None
    if not isinstance(events, list) or not events or any(not isinstance(row, Mapping) for row in events):
        raise NleLayerMaterializationError("renderer payload event inventory is invalid")
    semantic_ids = [row.get("semanticEventId") for row in events]
    if any(not isinstance(value, str) or not value for value in semantic_ids) or len(set(semantic_ids)) != len(semantic_ids):
        raise NleLayerMaterializationError("renderer payload semantic event inventory is invalid")
    authorized_root = Path(os.path.abspath(authorized_root))
    try:
        relative_parent = output_root.parent.relative_to(authorized_root)
        parent = safe_generated_directory(authorized_root, relative_parent)
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleLayerMaterializationError(str(error)) from error
    staging = safe_generated_directory(
        parent, Path(f".{output_root.name}.staging-{uuid.uuid4().hex}"),
    )
    try:
        archive_path = safe_generated_target(staging, Path("hyperframes-source-project.zip"))
        _archive_project(source_project, archive_path)
        event_rows: list[dict[str, Any]] = []
        for event in events:
            stem = _safe_event_stem(event)
            project = staging / "projects" / stem
            built = build_event_overlay_project(
                source_project=source_project, output_project=project,
                event=event, authorized_root=Path(authorized_root),
            )
            event_dir = safe_generated_directory(staging, Path("events") / stem)
            overlay = safe_generated_target(event_dir, Path("overlay.mov"))
            evidence_dir = safe_generated_directory(event_dir, Path("evidence"))
            video, _ = _render_event(
                project=project, output=overlay, evidence_dir=evidence_dir,
                duration=float(built["duration_seconds"]), width=width, height=height,
                frame_rate=float(frame_rate),
            )
            alpha_path = evidence_dir / "alpha-evidence.json"
            video["decode_receipt"] = {
                "path": str(alpha_path.relative_to(staging)).replace("\\", "/"),
                "sha256": sha256_file(alpha_path),
            }
            event_rows.append({
                "semantic_event_id": built["semantic_event_id"],
                "render_event_id": built["render_event_id"],
                "payload_sha256": built["payload_sha256"],
                "timeline": {
                    "start_seconds": built["timeline_start_seconds"],
                    "end_seconds": built["timeline_end_seconds"],
                    "frame_rate": float(frame_rate),
                },
                "overlay": {"path": str(overlay.relative_to(staging)).replace("\\", "/"), "sha256": sha256_file(overlay)},
                "alpha_evidence": {"path": str(alpha_path.relative_to(staging)).replace("\\", "/"), "sha256": sha256_file(alpha_path)},
                "video": video,
            })
        manifest = {
            "schema_version": 1, "kind": "nle_motion_layer_materialization", "status": "pass",
            "source_project": {"path": str(source_project), "tree_sha256": source_project_tree_sha256(source_project)},
            "renderer_payload": {"path": str(payload_path), "sha256": sha256_file(payload_path)},
            "source_project_archive": {"path": archive_path.name, "sha256": sha256_file(archive_path)},
            "events": event_rows,
            "implementation_sha256": sha256_file(_IMPLEMENTATION),
        }
        manifest["integrity_sha256"] = _stable_hash(manifest)
        staged_manifest = safe_generated_target(staging, Path("motion-layer-manifest.json"))
        atomic_write_text(
            staged_manifest,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        errors = validate_motion_layer_manifest(staged_manifest)
        if errors:
            raise NleLayerMaterializationError("motion layer manifest failed:\n- " + "\n- ".join(errors))
        _atomic_directory_publish(staging, output_root)
        final_manifest = output_root / "motion-layer-manifest.json"
        return _manifest_assets(read_json(final_manifest), final_manifest)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--authorized-root", required=True, type=Path)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--frame-rate", required=True, type=float)
    args = parser.parse_args()
    result = materialize_motion_handoff_layers(
        source_project=args.source_project, output_root=args.output_root,
        authorized_root=args.authorized_root, width=args.width, height=args.height,
        frame_rate=args.frame_rate, execute=True,
    )
    if not result:
        raise NleLayerMaterializationError("motion layers were not materialized")
    print((args.output_root / "motion-layer-manifest.json").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
