#!/usr/bin/env python3
"""Generate and validate retained real-media technical evidence for six fixture types."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json
from fixture_acceptance import REQUIRED_TYPES
from technical_qa import run_technical_qa


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION_PATHS = (
    Path("scripts/six_media_acceptance.py"),
    Path("scripts/technical_qa.py"),
    Path("scripts/validate_platform_export.py"),
)
FIXTURE_SPECS = {
    "landscape_screen_tutorial": {
        "dimensions": (320, 180),
        "base": "0x102030",
        "video_filter": (
            "drawbox=x=0:y=0:w=iw:h=20:color=0x1b263b:t=fill,"
            "drawbox=x=8:y=28:w=76:h=144:color=0x26354d:t=fill,"
            "drawbox=x=92:y=28:w=220:h=94:color=0xe8eef5:t=fill,"
            "drawbox=x=92:y=130:w=104:h=42:color=0x4c78ff:t=fill,"
            "drawbox=x=204:y=130:w=108:h=42:color=0x2d3748:t=fill,"
            "drawbox=x='108+70*t':y='55+20*t':w=6:h=10:color=white:t=fill"
        ),
        "audio": "aevalsrc=0.065*sin(2*PI*440*t):s=48000:d=2",
    },
    "portrait_talking_head": {
        "dimensions": (180, 320),
        "base": "0x415a77",
        "video_filter": (
            "drawbox=x=34:y=214:w=112:h=106:color=0x274c77:t=fill,"
            "drawbox=x=54:y=58:w=72:h=116:color=0xe2a878:t=fill,"
            "drawbox=x=54:y=58:w=72:h=25:color=0x3b2f2f:t=fill,"
            "drawbox=x=67:y=105:w=8:h=7:color=0x202020:t=fill,"
            "drawbox=x=105:y=105:w=8:h=7:color=0x202020:t=fill,"
            "drawbox=x=76:y=144:w=28:h=8:color=0x8b1e3f:t=fill"
        ),
        "audio": "aevalsrc=0.055*sin(2*PI*180*t)+0.025*sin(2*PI*360*t):s=48000:d=2",
    },
    "published_edit_polish": {
        "dimensions": (320, 180),
        "base": "0x38618c",
        "video_filter": (
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x9d4edd:t=fill:enable='gte(t,1)',"
            "drawbox=x=0:y=0:w=iw:h=12:color=black:t=fill,"
            "drawbox=x=0:y=168:w=iw:h=12:color=black:t=fill,"
            "drawbox=x=18:y=126:w=190:h=30:color=0xf9c74f:t=fill,"
            "drawbox=x=285:y=22:w=20:h=20:color=white:t=fill"
        ),
        "audio": "aevalsrc=0.05*sin(2*PI*520*t)+0.022*sin(2*PI*1040*t):s=48000:d=2",
    },
    "two_person_interview": {
        "dimensions": (320, 180),
        "base": "0x20252b",
        "video_filter": (
            "drawbox=x=0:y=0:w=157:h=ih:color=0x1d7874:t=fill,"
            "drawbox=x=163:y=0:w=157:h=ih:color=0x7d2941:t=fill,"
            "drawbox=x=0:y=0:w=iw:h=14:color=0x171a1f:t=fill,"
            "drawbox=x=54:y=43:w=48:h=67:color=0xe0a878:t=fill,"
            "drawbox=x=218:y=43:w=48:h=67:color=0xc98f65:t=fill,"
            "drawbox=x=38:y=118:w=80:h=62:color=0x264653:t=fill,"
            "drawbox=x=202:y=118:w=80:h=62:color=0x5a2333:t=fill"
        ),
        "audio": "aevalsrc=0.05*sin(2*PI*220*t)+0.05*sin(2*PI*330*t):s=48000:d=2",
    },
    "noisy_audio_hotwords": {
        "dimensions": (320, 180),
        "base": "0x241f31",
        "video_filter": (
            "drawbox=x=14:y=16:w=292:h=148:color=0x302a40:t=fill,"
            "drawbox=x=32:y=85:w=20:h=42:color=0xf8961e:t=fill,"
            "drawbox=x=70:y=60:w=20:h=67:color=0xf9c74f:t=fill,"
            "drawbox=x=108:y=38:w=20:h=89:color=0xf94144:t=fill,"
            "drawbox=x=146:y=72:w=20:h=55:color=0x90be6d:t=fill,"
            "drawbox=x=184:y=48:w=20:h=79:color=0x43aa8b:t=fill,"
            "drawbox=x=222:y=67:w=20:h=60:color=0x577590:t=fill,"
            "drawbox=x=260:y=91:w=20:h=36:color=0xf3722c:t=fill"
        ),
        "audio": (
            "aevalsrc=0.025*random(0)+"
            "0.095*sin(2*PI*880*t)*lt(mod(t\\,0.6)\\,0.12):s=48000:d=2"
        ),
    },
    "screen_camera_mixed": {
        "dimensions": (320, 180),
        "base": "0x0b132b",
        "video_filter": (
            "drawbox=x=0:y=0:w=iw:h=20:color=0x1c2541:t=fill,"
            "drawbox=x=8:y=28:w=70:h=144:color=0x253658:t=fill,"
            "drawbox=x=86:y=28:w=226:h=144:color=0xdce6f2:t=fill,"
            "drawbox=x=226:y=92:w=86:h=80:color=white:t=fill,"
            "drawbox=x=232:y=98:w=74:h=68:color=0x38618c:t=fill,"
            "drawbox=x=251:y=106:w=36:h=36:color=0xe2a878:t=fill,"
            "drawbox=x=242:y=145:w=54:h=21:color=0x274c77:t=fill"
        ),
        "audio": "aevalsrc=0.06*sin(2*PI*640*t):s=48000:d=2",
    },
}


def _resolve(base: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _relative_path(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base.resolve())).as_posix()


def _normalize_report_paths(report: dict[str, Any], suite_dir: Path) -> dict[str, Any]:
    normalized = dict(report)
    normalized["file"] = Path(str(report["file"])).relative_to(suite_dir).as_posix()
    normalized["samples"] = [
        {**row, "path": Path(str(row["path"])).relative_to(suite_dir).as_posix()}
        for row in report.get("samples") or []
    ]
    return normalized


def _implementation_dependencies() -> dict[str, str]:
    return {path.as_posix(): sha256_file(REPO_ROOT / path) for path in IMPLEMENTATION_PATHS}


def _probe_dimensions(media: Path) -> tuple[int, int]:
    run = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(media),
    ], check=True, capture_output=True, text=True, encoding="utf-8")
    stream = (json.loads(run.stdout).get("streams") or [{}])[0]
    return int(stream.get("width", 0)), int(stream.get("height", 0))


def _decode_frame(media: Path, timestamp: float) -> tuple[bytes, int, int]:
    width, height = _probe_dimensions(media)
    run = subprocess.run([
        "ffmpeg", "-v", "error", "-ss", f"{timestamp:.3f}", "-i", str(media),
        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ], check=True, capture_output=True)
    if len(run.stdout) != width * height * 3:
        raise RuntimeError(f"unexpected decoded frame size for {media}")
    return run.stdout, width, height


def _pixel(frame: bytes, width: int, height: int, x: int, y: int) -> list[int] | None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return None
    offset = (y * width + x) * 3
    return list(frame[offset:offset + 3])


def _near(rgb: list[int] | None, expected: tuple[int, int, int], tolerance: int = 45) -> bool:
    return rgb is not None and max(abs(rgb[index] - expected[index]) for index in range(3)) <= tolerance


def _distance(first: list[int] | None, second: list[int] | None) -> int:
    if first is None or second is None:
        return 0
    return sum(abs(first[index] - second[index]) for index in range(3))


def _decode_audio(media: Path, sample_rate: int = 8000) -> list[float]:
    run = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1",
        "-ar", str(sample_rate), "-f", "f32le", "-",
    ], check=True, capture_output=True)
    values = array.array("f")
    values.frombytes(run.stdout)
    return list(values)


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def _tone_amplitude(values: list[float], frequency: float, sample_rate: int = 8000) -> float:
    if not values:
        return 0.0
    sine = sum(value * math.sin(2 * math.pi * frequency * index / sample_rate)
               for index, value in enumerate(values))
    cosine = sum(value * math.cos(2 * math.pi * frequency * index / sample_rate)
                 for index, value in enumerate(values))
    return 2.0 * math.hypot(sine, cosine) / len(values)


def _audio_observations(values: list[float], sample_rate: int = 8000) -> dict[str, Any]:
    amplitudes = {
        str(frequency): round(_tone_amplitude(values, frequency, sample_rate), 6)
        for frequency in (180, 220, 330, 360, 440, 520, 640, 700, 880, 1040)
    }
    crossings = sum(1 for left, right in zip(values, values[1:]) if (left < 0) != (right < 0))
    burst = values[int(0.03 * sample_rate):int(0.10 * sample_rate)]
    gap = values[int(0.30 * sample_rate):int(0.50 * sample_rate)]
    tone_880 = float(amplitudes["880"])
    residual_rms = math.sqrt(max(0.0, _rms(values) ** 2 - tone_880 ** 2 / 2))
    return {
        "rms": round(_rms(values), 6),
        "zero_crossing_rate": round(crossings / max(1, len(values) - 1), 6),
        "tone_amplitudes": amplitudes,
        "hotword_pulse_rms_ratio": round(_rms(burst) / max(_rms(gap), 1e-9), 6),
        "noise_residual_rms": round(residual_rms, 6),
    }


def _check(identifier: str, passed: bool, observed: Any, expectation: str) -> dict[str, Any]:
    return {"id": identifier, "passed": bool(passed), "observed": observed, "expectation": expectation}


def _measure_characteristics(media: Path, fixture_type: str) -> dict[str, Any]:
    early, width, height = _decode_frame(media, 0.5)
    late, late_width, late_height = _decode_frame(media, 1.5)
    audio = _audio_observations(_decode_audio(media))
    pixels: dict[str, list[int] | None] = {}

    def sample(name: str, x: int, y: int, *, frame: str = "early") -> list[int] | None:
        data = late if frame == "late" else early
        frame_width = late_width if frame == "late" else width
        frame_height = late_height if frame == "late" else height
        pixels[name] = _pixel(data, frame_width, frame_height, x, y)
        return pixels[name]

    amplitudes = audio["tone_amplitudes"]
    checks: list[dict[str, Any]] = []
    if fixture_type == "landscape_screen_tutorial":
        toolbar = sample("toolbar", 10, 10)
        sidebar = sample("sidebar", 30, 60)
        canvas = sample("tutorial_canvas", 150, 60)
        cursor_early = sample("cursor_early", 145, 68)
        cursor_late = sample("cursor_late", 215, 88, frame="late")
        checks = [
            _check("landscape_orientation", width > height, [width, height], "width greater than height"),
            _check("screen_toolbar", _near(toolbar, (27, 38, 59)), toolbar, "dark application toolbar"),
            _check("screen_panel_contrast", _distance(sidebar, canvas) > 250,
                   _distance(sidebar, canvas), "sidebar and work canvas visibly separated"),
            _check("moving_cursor", _near(cursor_early, (255, 255, 255), 55) and
                   _near(cursor_late, (255, 255, 255), 55),
                   [cursor_early, cursor_late], "white cursor occupies different positions over time"),
            _check("tutorial_tone", amplitudes["440"] > 0.035, amplitudes["440"], "audible 440 Hz tutorial cue"),
        ]
    elif fixture_type == "portrait_talking_head":
        face = sample("center_face", 80, 100)
        mouth = sample("mouth", 85, 147)
        shoulders = sample("shoulders", 50, 250)
        checks = [
            _check("portrait_orientation", height > width, [width, height], "height greater than width"),
            _check("centered_face", _near(face, (226, 168, 120)), face, "centered skin-tone face region"),
            _check("visible_mouth", _near(mouth, (139, 30, 63)), mouth, "contrasting mouth feature"),
            _check("talking_head_shoulders", _near(shoulders, (39, 76, 119)), shoulders, "shoulders below face"),
            _check("voice_band_fundamental", amplitudes["180"] > amplitudes["440"] * 3,
                   {"180": amplitudes["180"], "440": amplitudes["440"]},
                   "voice-like 180 Hz fundamental dominates unrelated tone"),
        ]
    elif fixture_type == "published_edit_polish":
        early_scene = sample("early_scene", 250, 80)
        late_scene = sample("late_scene", 250, 80, frame="late")
        lower_third = sample("lower_third", 50, 140)
        letterbox = sample("letterbox", 100, 5)
        checks = [
            _check("edited_scene_change", _distance(early_scene, late_scene) > 100,
                   _distance(early_scene, late_scene), "distinct picture treatment across edit point"),
            _check("lower_third_graphic", _near(lower_third, (249, 199, 79)), lower_third,
                   "persistent polished lower-third graphic"),
            _check("cinematic_letterbox", _near(letterbox, (0, 0, 0), 28), letterbox,
                   "black framing bar"),
            _check("polish_music_layers", amplitudes["520"] > 0.025 and amplitudes["1040"] > 0.009,
                   {"520": amplitudes["520"], "1040": amplitudes["1040"]},
                   "two audible harmonic polish layers"),
        ]
    elif fixture_type == "two_person_interview":
        left_background = sample("left_background", 20, 50)
        right_background = sample("right_background", 300, 50)
        left_face = sample("left_face", 75, 80)
        right_face = sample("right_face", 240, 80)
        divider = sample("split_divider", 160, 80)
        ratio = amplitudes["220"] / max(amplitudes["330"], 1e-9)
        checks = [
            _check("two_distinct_sides", _distance(left_background, right_background) > 100,
                   _distance(left_background, right_background), "contrasting left and right interview panels"),
            _check("two_visible_people", _near(left_face, (224, 168, 120)) and
                   _near(right_face, (201, 143, 101)), [left_face, right_face], "two separate face regions"),
            _check("split_screen_divider", _near(divider, (32, 37, 43)), divider, "center divider between people"),
            _check("two_voice_bands", amplitudes["220"] > 0.025 and amplitudes["330"] > 0.025 and 0.7 < ratio < 1.4,
                   {"220": amplitudes["220"], "330": amplitudes["330"], "ratio": round(ratio, 6)},
                   "two similarly present voice-band fundamentals"),
        ]
    elif fixture_type == "noisy_audio_hotwords":
        warning_bar = sample("warning_bar", 115, 50)
        quiet_panel = sample("audio_panel", 20, 30)
        checks = [
            _check("audio_meter_visual", _near(warning_bar, (249, 65, 68)), warning_bar,
                   "high red audio-meter bar"),
            _check("meter_panel", _near(quiet_panel, (48, 42, 64)), quiet_panel, "dark audio analysis panel"),
            _check("measured_noise_floor", audio["noise_residual_rms"] > 0.012,
                   audio["noise_residual_rms"], "decoded broadband residual above noise threshold"),
            _check("hotword_tone_marker", amplitudes["880"] > 0.012, amplitudes["880"],
                   "decoded 880 Hz hotword marker energy"),
            _check("hotword_pulse_envelope", audio["hotword_pulse_rms_ratio"] > 1.5,
                   audio["hotword_pulse_rms_ratio"], "marker window louder than intervening noise"),
            _check("broadband_zero_crossings", audio["zero_crossing_rate"] > 0.04,
                   audio["zero_crossing_rate"], "noise produces high decoded zero-crossing rate"),
        ]
    elif fixture_type == "screen_camera_mixed":
        screen = sample("screen_canvas", 120, 60)
        sidebar = sample("screen_sidebar", 30, 60)
        pip_border = sample("camera_border", 228, 94)
        pip_face = sample("camera_face", 265, 120)
        checks = [
            _check("mixed_screen_layout", _distance(screen, sidebar) > 250,
                   _distance(screen, sidebar), "application canvas and sidebar are distinct"),
            _check("camera_pip_border", _near(pip_border, (255, 255, 255), 55), pip_border,
                   "bright PiP camera border"),
            _check("camera_pip_face", _near(pip_face, (226, 168, 120)), pip_face,
                   "skin-tone face inside PiP region"),
            _check("mixed_audio_cue", amplitudes["640"] > 0.03, amplitudes["640"],
                   "audible mixed-presentation cue"),
        ]
    else:
        checks = [_check("known_fixture_type", False, fixture_type, "one required fixture type")]
    observations = {
        "dimensions": [width, height],
        "pixels": pixels,
        "audio": audio,
    }
    return {
        "schema_version": 1,
        "fixture_type": fixture_type,
        "status": "pass" if checks and all(check["passed"] for check in checks) else "failed",
        "visual_fingerprint": hashlib.sha256(early + late).hexdigest(),
        "audio_fingerprint": hashlib.sha256(
            json.dumps(audio, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "observations": observations,
        "checks": checks,
    }


def generate(suite_dir: Path, manifest_path: Path) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg and FFprobe are required; six-media acceptance cannot be skipped")
    suite_dir = suite_dir.resolve()
    manifest_path = manifest_path.resolve()
    suite_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for fixture_type, spec in FIXTURE_SPECS.items():
        width, height = spec["dimensions"]
        media = suite_dir / f"{fixture_type}.mp4"
        command = [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c={spec['base']}:size={width}x{height}:rate=12:duration=2",
            "-f", "lavfi", "-i",
            str(spec["audio"]),
            "-vf", str(spec["video_filter"]),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(media),
        ]
        run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
        if run.returncode != 0:
            raise RuntimeError(f"six-media generation failed for {fixture_type}: {run.stderr}")
        report_path = suite_dir / f"{fixture_type}-technical-qa.json"
        report = run_technical_qa(
            media, output=report_path, evidence_dir=suite_dir / "evidence" / fixture_type,
        )
        normalized = _normalize_report_paths(report, suite_dir)
        write_json(report_path, normalized)
        characteristic_evidence = _measure_characteristics(media, fixture_type)
        rows.append({
            "fixture_type": fixture_type,
            "evidence_kind": "generated_type_specific_short_media_technical_fixture",
            "dimensions": [width, height],
            "media": _relative_path(media, manifest_path.parent),
            "media_sha256": sha256_file(media),
            "technical_report": _relative_path(report_path, manifest_path.parent),
            "technical_report_sha256": sha256_file(report_path),
            "generation_command": command[:-1] + [media.name],
            "characteristic_evidence": characteristic_evidence,
        })
    manifest = {
        "schema_version": 2,
        "status": "pass",
        "required_types": sorted(REQUIRED_TYPES),
        "scenario_count": len(rows),
        "skipped": 0,
        "implementation_dependencies": _implementation_dependencies(),
        "scenarios": rows,
    }
    write_json(manifest_path, manifest)
    errors = validate_manifest(manifest_path)
    if errors:
        raise RuntimeError("generated six-media manifest failed validation: " + "; ".join(errors))
    return manifest


def validate_manifest(manifest_path: Path) -> list[str]:
    errors: list[str] = []
    if not manifest_path.is_file():
        return ["six-media acceptance manifest is missing"]
    manifest = read_json(manifest_path)
    manifest_dir = manifest_path.resolve().parent
    rows = manifest.get("scenarios") or []
    types = [row.get("fixture_type") for row in rows]
    if (
        manifest.get("schema_version") != 2
        or manifest.get("status") != "pass"
        or int(manifest.get("scenario_count", 0)) != len(REQUIRED_TYPES)
        or int(manifest.get("skipped", -1)) != 0
        or len(rows) != len(REQUIRED_TYPES)
        or set(types) != REQUIRED_TYPES
        or len(set(types)) != len(types)
    ):
        errors.append("six-media manifest coverage or status is invalid")
    expected_dependencies = _implementation_dependencies()
    if manifest.get("implementation_dependencies") != expected_dependencies:
        errors.append("six-media implementation dependency hashes are stale")
    for index, row in enumerate(rows):
        media = _resolve(manifest_dir, row.get("media"))
        report_path = _resolve(manifest_dir, row.get("technical_report"))
        if not media.is_file() or row.get("media_sha256") != (
            sha256_file(media) if media.is_file() else None
        ):
            errors.append(f"six-media scenario {index} media is missing or stale")
            continue
        if not report_path.is_file() or row.get("technical_report_sha256") != (
            sha256_file(report_path) if report_path.is_file() else None
        ):
            errors.append(f"six-media scenario {index} report is missing or stale")
            continue
        report = read_json(report_path)
        samples = report.get("samples") or []
        if (
            report.get("status") != "pass"
            or report.get("decode_status") != "pass"
            or report.get("file_sha256") != sha256_file(media)
            or int((report.get("media") or {}).get("video_streams", 0)) < 1
            or int((report.get("media") or {}).get("audio_streams", 0)) < 1
            or (report.get("audio") or {}).get("measured") is not True
            or report.get("blocking_errors")
            or len(samples) < 3
        ):
            errors.append(f"six-media scenario {index} technical report did not pass")
        fixture_type = str(row.get("fixture_type", ""))
        try:
            measured_characteristics = _measure_characteristics(media, fixture_type)
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            errors.append(f"six-media scenario {index} characteristic measurement failed: {exc}")
            measured_characteristics = None
        if (
            measured_characteristics is None
            or measured_characteristics.get("status") != "pass"
            or row.get("characteristic_evidence") != measured_characteristics
        ):
            errors.append(f"six-media scenario {index} characteristic evidence is missing, stale, or failed")
        for sample in samples:
            path = _resolve(report_path.parent, sample.get("path"))
            if not path.is_file() or sample.get("sha256") != (
                sha256_file(path) if path.is_file() else None
            ):
                errors.append(f"six-media scenario {index} sample evidence is missing or stale")
    characteristic_rows = [row.get("characteristic_evidence") or {} for row in rows]
    if len({row.get("visual_fingerprint") for row in characteristic_rows}) != len(REQUIRED_TYPES):
        errors.append("six-media visual characteristic fingerprints are not unique")
    if len({row.get("audio_fingerprint") for row in characteristic_rows}) != len(REQUIRED_TYPES):
        errors.append("six-media audio characteristic fingerprints are not unique")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    generate(Path(args.suite_dir), Path(args.manifest))
    print(Path(args.manifest).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
