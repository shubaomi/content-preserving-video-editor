#!/usr/bin/env python3
"""Produce local SFX and resolve one optional BGM through a stop-on-success cascade."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import os
from datetime import datetime, timezone
import tempfile
import time
import uuid
import wave
from array import array
from pathlib import Path
from typing import Any

import numpy as np

from build_local_sfx_library import build_for_storyboard
from director_adapters import AdapterRunner
from director_contracts import write_json
from motion_contracts import validate_contract_schema


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _dbfs(value: float) -> float:
    return round(20.0 * math.log10(max(value, 1e-12) / 32767.0), 3)


def _wave_samples(path: Path) -> tuple[tuple[int, int, int], array]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise RuntimeError(f"audio evidence must be 16-bit PCM WAV: {path}")
        params = (source.getnchannels(), source.getframerate(), source.getnframes())
        samples = array("h")
        samples.frombytes(source.readframes(source.getnframes()))
    return params, samples


def perceptual_motif_fingerprint(path: Path) -> dict[str, Any]:
    """Fingerprint decoded motif sound rather than its filename or container bytes."""
    path = path.resolve()
    (channels, sample_rate, frame_count), interleaved = _wave_samples(path)
    if channels < 1 or sample_rate <= 0 or frame_count <= 0:
        raise ValueError(f"motif audio has invalid PCM geometry: {path}")
    signal = np.asarray(interleaved, dtype=np.float64)[0::channels]
    if signal.size == 0:
        raise ValueError(f"motif audio contains no samples: {path}")
    signal /= 32768.0
    magnitude = np.abs(np.fft.rfft(signal * np.hanning(signal.size)))
    frequencies = np.fft.rfftfreq(signal.size, d=1.0 / sample_rate)
    magnitude_sum = float(magnitude.sum())
    centroid = (
        float(np.sum(frequencies * magnitude) / magnitude_sum) if magnitude_sum else 0.0
    )
    cumulative = np.cumsum(magnitude)
    rolloff_index = (
        int(np.searchsorted(cumulative, magnitude_sum * 0.85)) if magnitude_sum else 0
    )
    rolloff = float(frequencies[min(rolloff_index, len(frequencies) - 1)])
    rms = float(np.sqrt(np.mean(np.square(signal))))
    zero_crossing = float(np.mean(np.abs(np.diff(np.signbit(signal).astype(np.int8)))))
    # Quantized perceptual features remain stable across path/container metadata while
    # distinguishing pitch, duration, spectral shape, and onset envelope.
    envelope_bins = 16
    envelope = [
        round(float(np.sqrt(np.mean(np.square(chunk)))), 5)
        for chunk in np.array_split(signal, envelope_bins) if chunk.size
    ]
    features = {
        "duration_ms": round(signal.size / sample_rate * 1000),
        "spectral_centroid_hz": round(centroid, 1),
        "spectral_rolloff_hz": round(rolloff, 1),
        "rms": round(rms, 5),
        "zero_crossing_rate": round(zero_crossing, 5),
        "onset_envelope": envelope,
    }
    digest = hashlib.sha256(json.dumps(
        features, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "sha256": digest,
        "sample_rate": sample_rate,
        "channels_analyzed": 1,
        "duration_seconds": round(signal.size / sample_rate, 3),
        "spectral_centroid_hz": round(centroid, 1),
        "spectral_rolloff_hz": round(rolloff, 1),
        "onset_envelope": envelope,
        "method": "pcm-perceptual-v1",
    }


def _wave_metrics(off_path: Path, on_path: Path) -> dict[str, float]:
    off_params, off = _wave_samples(off_path)
    on_params, on = _wave_samples(on_path)
    if off_params != on_params or len(off) != len(on) or not off:
        raise RuntimeError("SFX audition WAV files are not sample-aligned")

    def rms(values: array | list[int]) -> float:
        return math.sqrt(sum(float(value) * float(value) for value in values) / len(values))

    residual = [on_value - off_value for off_value, on_value in zip(off, on)]
    off_rms = rms(off)
    on_rms = rms(on)
    residual_rms = rms(residual)
    peak = max(abs(value) for value in on)
    return {
        "off_mean_dbfs": _dbfs(off_rms),
        "on_mean_dbfs": _dbfs(on_rms),
        "residual_mean_dbfs": _dbfs(residual_rms),
        "on_peak_dbfs": _dbfs(float(peak)),
        "mix_gain_delta_db": round(20.0 * math.log10(max(on_rms, 1e-12) / max(off_rms, 1e-12)), 3),
    }


def _loudnorm_metrics(path: Path) -> dict[str, float]:
    """Measure integrated LUFS and true peak with FFmpeg's EBU R128 loudnorm filter."""
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
            "-af", "loudnorm=I=-24:TP=-2:LRA=7:print_format=json",
            "-f", "null", "-",
        ],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, flags=re.DOTALL)
    if not blocks:
        raise RuntimeError(f"FFmpeg loudnorm did not emit measurements for {path}")
    payload = json.loads(blocks[-1])

    def finite_number(key: str, floor: float = -120.0) -> float:
        try:
            value = float(payload[key])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"FFmpeg loudnorm measurement {key} is invalid for {path}") from error
        return round(value if math.isfinite(value) else floor, 3)

    return {
        "integrated_lufs": finite_number("input_i"),
        "true_peak_dbtp": finite_number("input_tp"),
    }


def _write_residual_wav(
    path: Path, *, params: tuple[int, int, int], off: array, on: array,
) -> None:
    channels, sample_rate, _ = params
    length = min(len(off), len(on))
    residual = array("h", (
        max(-32768, min(32767, int(on[index]) - int(off[index])))
        for index in range(length)
    ))
    with wave.open(str(path), "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(residual.tobytes())


def _perceptual_mix_metrics(
    *, off_path: Path, on_path: Path, cue_path: Path, planned_delay_seconds: float,
) -> dict[str, Any]:
    """Measure cue identity, approximate window loudness, and delivered onset."""
    off_params, off_samples = _wave_samples(off_path)
    on_params, on_samples = _wave_samples(on_path)
    cue_params, cue_samples = _wave_samples(cue_path)
    channels, sample_rate, _ = off_params
    if on_params[:2] != off_params[:2] or cue_params[1] != sample_rate:
        raise RuntimeError("perceptual audio evidence sample geometry differs")
    off = np.asarray(off_samples, dtype=np.float64)[0::channels]
    on = np.asarray(on_samples, dtype=np.float64)[0::channels]
    cue = np.asarray(cue_samples, dtype=np.float64)[0::cue_params[0]]
    length = min(off.size, on.size)
    residual = on[:length] - off[:length]

    def rms_db(values: np.ndarray) -> float:
        if values.size == 0:
            return -120.0
        rms = float(np.sqrt(np.mean(np.square(values))))
        return round(20.0 * math.log10(max(rms, 1e-12) / 32767.0), 3)

    dialogue_level = rms_db(off[:length])
    cue_level = rms_db(residual)
    # The limiter can make small dialogue-only changes before the cue. Locate the
    # authorized motif itself by full-band correlation instead of treating the
    # first residual sample as the cue onset.
    correlation_length = residual.size + cue.size - 1
    if residual.size and cue.size:
        fft_size = 1 << correlation_length.bit_length()
        correlation = np.fft.irfft(
            np.fft.rfft(residual, fft_size) * np.conj(np.fft.rfft(cue, fft_size)),
            fft_size,
        )
        observed_onset = float(np.argmax(np.abs(correlation[:residual.size])) / sample_rate)
    else:
        observed_onset = float("inf")
    onset_error = (
        abs(observed_onset - planned_delay_seconds) * 1000.0
        if math.isfinite(observed_onset) else float("inf")
    )
    delta = round(dialogue_level - cue_level, 3)
    on_level = rms_db(on[:length])
    mix_gain_delta = on_level - dialogue_level
    on_peak = float(np.max(np.abs(on[:length]))) if length else 0.0
    if cue_level <= -60.0 or onset_error > 80.0:
        status = "masked"
    elif mix_gain_delta > 4.0 or on_peak >= 32766.0:
        status = "dialogue_harmed"
    else:
        status = "audible_without_masking"
    residual_path = off_path.with_name(f".{off_path.stem}.{uuid.uuid4().hex}.residual.wav")
    try:
        _write_residual_wav(
            residual_path, params=off_params, off=off_samples, on=on_samples,
        )
        dialogue_loudness = _loudnorm_metrics(off_path)["integrated_lufs"]
        cue_loudness = _loudnorm_metrics(residual_path)["integrated_lufs"]
    finally:
        residual_path.unlink(missing_ok=True)
    perceptual_delta = round(dialogue_loudness - cue_loudness, 3)
    # Fingerprint the decoded authorized cue. Identity itself is also checked by
    # full-band correlation in the delivered review mix validator.
    return {
        "motif_fingerprint": perceptual_motif_fingerprint(cue_path),
        "dialogue_window_lufs": float(dialogue_loudness),
        "cue_window_lufs": float(cue_loudness),
        "dialogue_cue_delta_lu": float(perceptual_delta),
        "onset_error_ms": round(float(onset_error), 3),
        "audibility_status": status,
        "measurement_method": "ffmpeg-loudnorm-window-plus-fullband-identity-v1",
    }


def audition_filename_stem(value: Any) -> str:
    stem = str(value or "").strip()
    if not stem or not re.fullmatch(r"[A-Za-z0-9._:-]+", stem):
        raise ValueError(f"semantic event id is not safe for an audition filename: {value!r}")
    if re.fullmatch(r"[A-Za-z0-9._-]+", stem):
        return stem
    prefix = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "event"
    digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


_event_stem = audition_filename_stem


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def materialize_motion_audio_decisions(
    *, motion_design_contract: Path, audio_plan: Path, source_audio: Path,
    final_mix: Path, perceptual_evidence: Path, license_evidence: Path,
    audio_policy: dict[str, Any], output_dir: Path,
) -> list[Path]:
    """Materialize the frozen per-event audio contracts from measured delivered audio."""
    paths = [
        motion_design_contract.resolve(), audio_plan.resolve(), source_audio.resolve(),
        final_mix.resolve(), perceptual_evidence.resolve(), license_evidence.resolve(),
    ]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("motion-audio inputs are missing: " + ", ".join(missing))
    contract = json.loads(motion_design_contract.read_text(encoding="utf-8"))
    plan = json.loads(audio_plan.read_text(encoding="utf-8"))
    measured = json.loads(perceptual_evidence.read_text(encoding="utf-8"))
    licenses = json.loads(license_evidence.read_text(encoding="utf-8"))
    if not all(isinstance(value, dict) for value in (contract, plan, measured, licenses)):
        raise ValueError("motion-audio inputs must be JSON objects")
    rendered = {
        str(row.get("semantic_event_id")): row
        for row in (contract.get("opportunities") or [])
        if isinstance(row, dict) and row.get("decision") == "render"
    }
    decisions = {
        str(row.get("semantic_event_id") or row.get("event_id")): row
        for row in ((plan.get("motion_sfx") or {}).get("event_decisions") or [])
        if isinstance(row, dict) and row.get("event_id")
    }
    measurements = {
        str(row.get("event_id")): row
        for row in (measured.get("events") or []) if isinstance(row, dict)
    }
    assets = {
        str(row.get("event_id")): row
        for row in (licenses.get("assets") or []) if isinstance(row, dict)
    }
    if set(rendered) != set(decisions):
        raise ValueError("motion-audio decisions must exactly cover rendered motion events")
    candidate_binding = measured.get("candidate_media")
    if (
        not isinstance(candidate_binding, dict)
        or Path(str(candidate_binding.get("path") or "")).resolve() != final_mix.resolve()
        or candidate_binding.get("sha256") != _sha256(final_mix)
    ):
        raise ValueError("motion-audio perceptual evidence is not bound to the final mix")
    final_loudness = _loudnorm_metrics(final_mix)
    hashes = {
        "motion_design_contract_sha256": _sha256(motion_design_contract),
        "source_audio_sha256": _sha256(source_audio),
        "audio_policy_sha256": _json_sha256(audio_policy),
    }
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    inventory: list[dict[str, Any]] = []
    for event_id, opportunity in rendered.items():
        decision = decisions[event_id]
        decision_id = str(opportunity.get("audio_decision_id") or f"audio-{event_id}")
        rationale = str(decision.get("reason") or opportunity.get("rationale") or "").strip()
        if not rationale:
            raise ValueError(f"motion-audio decision lacks rationale: {event_id}")
        semantic_role = str(opportunity.get("semantic_role") or "explain")
        importance = {
            "resolve": "critical", "transition": "important", "relate": "important",
            "explain": "important", "mark": "supporting",
        }.get(semantic_role, "supporting")
        payload: dict[str, Any] = {
            "schema_version": "1.0.0",
            "decision_id": decision_id,
            "event_id": event_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "producer": "content-preserving-video-editor.audio-production",
            "decision": str(decision.get("decision")),
            "rationale": rationale,
            "semantic_importance": importance,
            "chapter_energy": {"supporting": 0.35, "important": 0.65, "critical": 0.85}[importance],
            "masking_risk": "high" if decision.get("decision") == "intentionally_silent" else "medium",
            "input_hashes": hashes,
            "status": "asset_ready",
        }
        if decision.get("decision") == "cue":
            renderer_event_id = str(decision.get("event_id") or event_id)
            row = measurements.get(renderer_event_id) or {}
            perceptual = row.get("perceptual") or {}
            if row.get("decision_binding") != _decision_binding(decision, audio_plan):
                raise ValueError(f"motion-audio cue decision binding is stale: {event_id}")
            for role in ("sfx_off", "sfx_on"):
                artifact = row.get(role)
                artifact_path = Path(str((artifact or {}).get("path") or ""))
                if (
                    not isinstance(artifact, dict) or not artifact_path.is_absolute()
                    or not artifact_path.is_file() or artifact.get("sha256") != _sha256(artifact_path)
                ):
                    raise ValueError(f"motion-audio cue lacks real {role} evidence: {event_id}")
            observed = _perceptual_mix_metrics(
                off_path=Path(str(row["sfx_off"]["path"])),
                on_path=Path(str(row["sfx_on"]["path"])),
                cue_path=_authorized_sfx_path(audio_plan, decision.get("asset")),
                planned_delay_seconds=max(
                    0.0, float(decision.get("start", 0.0))
                    - float(row.get("excerpt_start_seconds", 0.0))
                ),
            )
            measured_fingerprint = (perceptual.get("motif_fingerprint") or {}).get("sha256")
            if (
                observed["motif_fingerprint"]["sha256"] != measured_fingerprint
                or abs(float(observed["onset_error_ms"]) - float(perceptual.get("onset_error_ms", -1))) > 2.0
                or observed["audibility_status"] != perceptual.get("audibility_status")
            ):
                raise ValueError(f"motion-audio cue perceptual measurement is stale: {event_id}")
            if row.get("status") != "pass" or perceptual.get("audibility_status") != "audible_without_masking":
                raise ValueError(f"motion-audio cue lacks passing perceptual evidence: {event_id}")
            cue_path = _authorized_sfx_path(audio_plan, decision.get("asset"))
            license_row = assets.get(renderer_event_id) or {}
            if (
                Path(str(license_row.get("frozen_path") or "")).resolve() != cue_path
                or license_row.get("sha256") != _sha256(cue_path)
                or not str(license_row.get("license") or "").strip()
            ):
                raise ValueError(f"motion-audio cue lacks matching license provenance: {event_id}")
            fingerprint = perceptual.get("motif_fingerprint") or {}
            payload["cue"] = {
                "asset": {
                    "path": str(cue_path), "sha256": _sha256(cue_path),
                    "duration_seconds": _probe_duration(cue_path),
                },
                "family": str(decision.get("family") or semantic_role),
                "motif_fingerprint_sha256": str(fingerprint.get("sha256") or ""),
                "onset_seconds": float(decision.get("start", 0.0)),
                "duration_seconds": float(decision.get("duration_seconds") or _probe_duration(cue_path)),
                "gain_db": round(20.0 * math.log10(max(float(decision.get("volume", 1.0)), 0.001)), 3),
                "phase": "entrance",
                "license_evidence": {
                    "path": str(license_evidence), "sha256": _sha256(license_evidence),
                    "rights_basis": str(license_row["license"]),
                },
            }
            payload["mix_evidence"] = {
                "final_mix_sha256": _sha256(final_mix),
                "dialogue_window_lufs": float(perceptual["dialogue_window_lufs"]),
                "cue_window_lufs": float(perceptual["cue_window_lufs"]),
                "dialogue_cue_delta_lu": float(perceptual["dialogue_cue_delta_lu"]),
                "integrated_lufs": float(final_loudness["integrated_lufs"]),
                "true_peak_dbtp": float(final_loudness["true_peak_dbtp"]),
                "onset_error_ms": float(perceptual["onset_error_ms"]),
                "audibility_status": "audible_without_masking",
            }
            payload["status"] = "mixed_and_validated"
        elif decision.get("decision") != "intentionally_silent":
            raise ValueError(f"unsupported motion-audio decision: {event_id}")
        schema_errors = validate_contract_schema("motion-audio-decision", payload)
        if schema_errors:
            raise ValueError("; ".join(schema_errors))
        output = output_dir / f"{audition_filename_stem(decision_id)}.json"
        write_json(output, payload)
        outputs.append(output)
        inventory.append({
            "event_id": event_id, "decision_id": decision_id,
            "path": str(output), "sha256": _sha256(output), "status": payload["status"],
        })
    manifest = output_dir / "manifest.json"
    write_json(manifest, {
        "schema_version": 1, "status": "pass", "decisions": inventory,
        "input_hashes": hashes, "final_mix_sha256": _sha256(final_mix),
    })
    outputs.append(manifest)
    return outputs


def _audio_artifact(path: Path, *, role: str) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "duration_seconds": round(_probe_duration(path), 3),
        "role": role,
    }


def _decision_binding(decision: dict[str, Any], audio_plan: Path) -> dict[str, Any]:
    binding = {
        "event_id": str(decision.get("event_id") or ""),
        "decision": str(decision.get("decision") or ""),
        "family": str(decision.get("family") or ""),
        "start": decision.get("start"),
        "duration_seconds": decision.get("duration_seconds"),
        "volume": decision.get("volume"),
        "post_gain_mean_dbfs": decision.get("post_gain_mean_dbfs"),
        "reason": decision.get("reason"),
    }
    if decision.get("decision") == "cue":
        asset = _authorized_sfx_path(audio_plan, decision.get("asset"))
        binding["asset"] = {"path": str(asset), "sha256": _sha256(asset)}
    else:
        binding["asset"] = None
    encoded = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"contract": binding, "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def _authorized_sfx_path(audio_plan: Path, value: Any) -> Path:
    path = _resolve(audio_plan.parent, value)
    root = (audio_plan.parent / "assets" / "sfx").resolve()
    if path is None or not path.is_relative_to(root):
        raise ValueError(f"SFX cue must stay inside the authorized SFX root: {root}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _media_decode_errors(path: Path, label: str) -> list[str]:
    errors: list[str] = []
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return [f"{label} cannot be verified without ffmpeg and ffprobe"]
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        stream_types = {
            str(row.get("codec_type"))
            for row in (json.loads(probe.stdout).get("streams") or [])
            if isinstance(row, dict)
        }
        if not {"video", "audio"}.issubset(stream_types):
            errors.append(f"{label} must contain decodable video and audio streams")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path),
             "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError):
        errors.append(f"{label} failed full audio/video decode")
    return errors


def _extract_pcm_window(source: Path, output: Path, *, start: float, duration: float) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.6f}", "-i", str(source), "-t", f"{duration:.6f}",
         "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(output)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )


def _cue_presence_errors(
    *, candidate_media: Path, audio_plan: Path, output: Path,
    decisions: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sample-review-cue-qa-") as temp:
        root = Path(temp)
        for index, decision in enumerate(decisions):
            start = max(0.0, float(decision.get("start", 0.0)))
            duration = max(0.25, min(2.5, float(decision.get("duration_seconds", 1.0))))
            off = root / f"{index}-off.wav"
            on = root / f"{index}-on.wav"
            reference = root / f"{index}-reference.wav"
            try:
                _extract_pcm_window(candidate_media, off, start=start, duration=duration)
                _extract_pcm_window(output, on, start=start, duration=duration)
                metrics = _wave_metrics(off, on)
                cue = _authorized_sfx_path(audio_plan, decision.get("asset"))
                volume = max(0.0, float(decision.get("volume", 0.28)))
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                     "-i", str(cue), "-t", f"{duration:.6f}", "-vn", "-ac", "2",
                     "-ar", "48000", "-af", f"volume={volume:.6f}",
                     "-c:a", "pcm_s16le", str(reference)],
                    check=True, capture_output=True, text=True, encoding="utf-8",
                )
                _, off_samples = _wave_samples(off)
                _, on_samples = _wave_samples(on)
                _, reference_samples = _wave_samples(reference)
                residual = array("h", (
                    max(-32768, min(32767, on_value - off_value))
                    for off_value, on_value in zip(off_samples, on_samples)
                ))
                correlation = _maximum_correlation(residual, reference_samples)
            except (OSError, RuntimeError, subprocess.CalledProcessError, wave.Error):
                errors.append(
                    f"sample review mix cue presence cannot be measured: {decision.get('event_id')}"
                )
                continue
            if metrics["residual_mean_dbfs"] <= -60.0:
                errors.append(
                    f"sample review mix cue is not measurable in delivered audio: {decision.get('event_id')}"
                )
            if correlation < 0.20:
                errors.append(
                    f"sample review mix does not contain the authorized cue identity: "
                    f"{decision.get('event_id')}"
                )
            if metrics["on_peak_dbfs"] > -0.05:
                errors.append(
                    f"sample review mix cue window clips: {decision.get('event_id')}"
                )
    return errors


def _maximum_correlation(observed: array, expected: array) -> float:
    """Return max normalized cue correlation with a small codec-delay tolerance."""
    # Input is 48 kHz stereo interleaved. Work at full 48 kHz bandwidth so no
    # unfiltered decimation can alias a different high-frequency cue identity.
    left = np.asarray(observed, dtype=np.float64)[0::2]
    right = np.asarray(expected, dtype=np.float64)[0::2]
    length = min(left.size, right.size)
    if length < 20:
        return 0.0
    left = left[:length]
    right = right[:length]
    fft_size = 1 << (left.size + right.size - 1).bit_length()
    correlation = np.fft.irfft(
        np.fft.rfft(left, fft_size) * np.conj(np.fft.rfft(right, fft_size)), fft_size,
    )
    max_lag = min(1440, length - 1)  # 30 ms codec/filter delay tolerance.
    candidates = np.concatenate((correlation[:max_lag + 1], correlation[-max_lag:]))
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.max(np.abs(candidates)) / denominator) if denominator else 0.0


def _replace_with_retry(source: Path, destination: Path, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def validate_sample_review_mix_receipt(
    receipt: dict[str, Any], *, candidate_media: Path, audio_plan: Path, output: Path,
) -> list[str]:
    """Validate that the paired-review candidate contains the current planned SFX."""
    if not isinstance(receipt, dict):
        return ["sample review mix receipt must be an object"]
    errors: list[str] = []
    expected = {
        "candidate_input": candidate_media.resolve(),
        "audio_plan": audio_plan.resolve(),
        "output": output.resolve(),
    }
    if receipt.get("schema_version") != 1:
        errors.append("sample review mix schema_version must be 1")
    if receipt.get("status") != "pass":
        errors.append("sample review mix status must be pass")
    if receipt.get("mode") != "planned_sfx_over_hyperframes_candidate":
        errors.append("sample review mix mode is invalid")
    for field, path in expected.items():
        row = receipt.get(field)
        if not isinstance(row, dict):
            errors.append(f"sample review mix {field} record is invalid")
            row = {}
        observed = Path(str(row.get("path") or "")).resolve()
        if observed != path:
            errors.append(f"sample review mix {field} path is stale")
        if not path.is_file():
            errors.append(f"sample review mix {field} file is missing")
        elif row.get("sha256") != _sha256(path):
            errors.append(f"sample review mix {field} hash is stale")
    plan: dict[str, Any] = {}
    try:
        cue_count = int(receipt.get("cue_count"))
    except (TypeError, ValueError):
        cue_count = -1
        errors.append("sample review mix cue_count is invalid")
    else:
        try:
            plan = json.loads(audio_plan.read_text(encoding="utf-8")) if audio_plan.is_file() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("sample review mix audio plan is unreadable")
        expected_cues = sum(
            isinstance(row, dict) and row.get("decision") == "cue"
            for row in ((plan.get("motion_sfx") or {}).get("event_decisions") or [])
        )
        if cue_count != expected_cues or cue_count <= 0:
            errors.append("sample review mix does not contain every planned cue")
    argv = [str(value) for value in (receipt.get("argv") or [])]
    if "-filter_complex" not in argv or not any("amix=" in value for value in argv):
        errors.append("sample review mix command lacks an SFX audio mix")
    if receipt.get("full_decode") is not True:
        errors.append("sample review mix output lacks a successful full decode")
    cue_assets = receipt.get("cue_assets") or []
    if not isinstance(cue_assets, list):
        cue_assets = []
        errors.append("sample review mix cue asset inventory is invalid")
    if len(cue_assets) != cue_count:
        errors.append("sample review mix cue asset inventory is incomplete")
    planned_cues = [
        row for row in ((plan.get("motion_sfx") or {}).get("event_decisions") or [])
        if isinstance(row, dict) and row.get("decision") == "cue"
    ]
    for index, row in enumerate(cue_assets):
        if not isinstance(row, dict):
            errors.append(f"sample review mix cue asset {index + 1} record is invalid")
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_absolute() or not path.is_file():
            errors.append(f"sample review mix cue asset is missing: {path}")
        elif row.get("sha256") != _sha256(path):
            errors.append(f"sample review mix cue asset hash is stale: {path}")
        if index >= len(planned_cues):
            continue
        planned = planned_cues[index]
        try:
            planned_path = _authorized_sfx_path(audio_plan, planned.get("asset"))
        except (ValueError, FileNotFoundError):
            planned_path = None
        if (
            row.get("event_id") != str(planned.get("event_id") or "")
            or planned_path is None
            or path.resolve() != planned_path.resolve()
        ):
            errors.append("sample review mix cue asset inventory does not match the audio plan")
    errors.extend(_media_decode_errors(candidate_media, "sample review mix candidate input"))
    errors.extend(_media_decode_errors(output, "sample review mix output"))
    if planned_cues and not errors:
        errors.extend(_cue_presence_errors(
            candidate_media=candidate_media, audio_plan=audio_plan,
            output=output, decisions=planned_cues,
        ))
    return errors


def validate_sample_audio_evidence(
    *, audio_plan: Path, storyboard: Path, candidate_media: Path,
    evidence_path: Path, output_dir: Path, expected_evidence_path: Path | None = None,
    declared_evidence_sha256: str | None = None,
) -> list[str]:
    """Validate immutable, input-bound SFX audition evidence for reuse/readiness."""
    errors: list[str] = []
    try:
        plan = json.loads(audio_plan.read_text(encoding="utf-8"))
        board = json.loads(storyboard.read_text(encoding="utf-8"))
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"sample audio evidence is unreadable: {error}"]
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1 \
            or evidence.get("status") != "pass":
        return ["sample audio evidence schema/status is invalid"]
    errors.extend(_media_decode_errors(candidate_media, "sample audio evidence candidate"))
    if expected_evidence_path is not None and evidence_path.resolve() != expected_evidence_path.resolve():
        errors.append("sample audio evidence path is outside the canonical Director location")
    if not declared_evidence_sha256 or declared_evidence_sha256 != _sha256(evidence_path):
        errors.append("sample audio evidence declared hash is missing or stale")
    for key, expected in (("storyboard", storyboard), ("candidate_media", candidate_media)):
        row = evidence.get(key)
        if not isinstance(row, dict):
            errors.append(f"sample audio evidence {key} record is missing")
            continue
        if Path(str(row.get("path") or "")).resolve() != expected.resolve():
            errors.append(f"sample audio evidence {key} path is stale")
        if not expected.is_file() or row.get("sha256") != _sha256(expected):
            errors.append(f"sample audio evidence {key} hash is stale")
    decisions = {
        str(row.get("event_id")): row
        for row in ((plan.get("motion_sfx") or {}).get("event_decisions") or [])
        if isinstance(row, dict) and row.get("event_id")
    }
    board_events = {
        str(row.get("id")): row for row in (board.get("events") or [])
        if isinstance(row, dict) and row.get("treatment") != "quiet_source"
    }
    evidence_events = evidence.get("events")
    if not isinstance(evidence_events, list):
        return [*errors, "sample audio evidence event inventory is invalid"]
    by_event = {
        str(row.get("event_id")): row for row in evidence_events
        if isinstance(row, dict) and row.get("event_id")
    }
    if set(by_event) != set(decisions) or set(decisions) != set(board_events):
        errors.append("sample audio evidence event inventory is stale")
    output_dir = output_dir.resolve()
    for event_id, decision in decisions.items():
        row = by_event.get(event_id)
        event = board_events.get(event_id) or {}
        if not isinstance(row, dict) or row.get("decision") != decision.get("decision"):
            errors.append(f"sample audio evidence decision is stale: {event_id}")
            continue
        if row.get("status") != "pass":
            errors.append(f"sample audio evidence event is not pass: {event_id}")
        try:
            expected_binding = _decision_binding(decision, audio_plan)
        except (ValueError, FileNotFoundError):
            expected_binding = None
        if expected_binding is None or row.get("decision_binding") != expected_binding:
            errors.append(f"sample audio evidence decision binding is stale: {event_id}")
        semantic_id = str(event.get("semantic_event_id") or event_id)
        if row.get("semantic_event_id") != audition_filename_stem(semantic_id):
            errors.append(f"sample audio evidence semantic id is stale: {event_id}")
        artifact_paths: dict[str, Path] = {}
        for role in ("sfx_off", "sfx_on"):
            artifact = row.get(role)
            if not isinstance(artifact, dict):
                errors.append(f"sample audio evidence {role} is missing: {event_id}")
                continue
            path = Path(str(artifact.get("path") or "")).resolve()
            if not path.is_relative_to(output_dir) or not path.is_file():
                errors.append(f"sample audio evidence {role} path is invalid: {event_id}")
            elif artifact.get("sha256") != _sha256(path):
                errors.append(f"sample audio evidence {role} hash is stale: {event_id}")
            else:
                artifact_paths[role] = path
        if set(artifact_paths) != {"sfx_off", "sfx_on"}:
            continue
        try:
            remeasured = _wave_metrics(
                artifact_paths["sfx_off"], artifact_paths["sfx_on"],
            )
        except (OSError, ValueError, RuntimeError, wave.Error) as error:
            errors.append(f"sample audio evidence WAVs cannot be decoded: {event_id}: {error}")
            continue
        for field, observed in remeasured.items():
            try:
                declared = float(row.get(field))
            except (TypeError, ValueError):
                errors.append(f"sample audio evidence {field} is malformed: {event_id}")
                continue
            if not math.isfinite(declared):
                errors.append(f"sample audio evidence {field} is non-finite: {event_id}")
                continue
            if abs(declared - observed) > 0.01:
                errors.append(f"sample audio evidence {field} differs from remeasured audio: {event_id}")
        if decision.get("decision") == "cue":
            try:
                cue_path = _authorized_sfx_path(audio_plan, decision.get("asset"))
                observed_perceptual = _perceptual_mix_metrics(
                    off_path=artifact_paths["sfx_off"],
                    on_path=artifact_paths["sfx_on"],
                    cue_path=cue_path,
                    planned_delay_seconds=max(
                        0.0, float(decision.get("start", 0.0))
                        - float(row.get("excerpt_start_seconds", 0.0))
                    ),
                )
            except (OSError, ValueError, RuntimeError, wave.Error) as error:
                errors.append(f"sample audio evidence cue cannot be remeasured: {event_id}: {error}")
                continue
            declared_perceptual = row.get("perceptual")
            if not isinstance(declared_perceptual, dict):
                errors.append(f"sample audio evidence perceptual record is missing: {event_id}")
                continue
            declared_fingerprint = declared_perceptual.get("motif_fingerprint")
            if (
                not isinstance(declared_fingerprint, dict)
                or declared_fingerprint.get("sha256")
                != observed_perceptual["motif_fingerprint"]["sha256"]
            ):
                errors.append(f"sample audio evidence motif identity differs from remeasured cue: {event_id}")
            for field in (
                "dialogue_window_lufs", "cue_window_lufs",
                "dialogue_cue_delta_lu", "onset_error_ms",
            ):
                try:
                    declared = float(declared_perceptual.get(field))
                except (TypeError, ValueError):
                    errors.append(f"sample audio evidence perceptual {field} is malformed: {event_id}")
                    continue
                if not math.isfinite(declared):
                    errors.append(
                        f"sample audio evidence perceptual {field} is non-finite: {event_id}"
                    )
                    continue
                if abs(declared - float(observed_perceptual[field])) > 0.05:
                    errors.append(
                        f"sample audio evidence perceptual {field} differs from remeasured audio: {event_id}"
                    )
            for field in ("audibility_status", "measurement_method"):
                if declared_perceptual.get(field) != observed_perceptual[field]:
                    errors.append(
                        f"sample audio evidence perceptual {field} differs from remeasured audio: {event_id}"
                    )
            try:
                maximum_onset_error_ms = float(
                    decision.get("portrait_landing_tolerance_ms", 80.0)
                )
            except (TypeError, ValueError):
                maximum_onset_error_ms = float("nan")
            if not math.isfinite(maximum_onset_error_ms) or maximum_onset_error_ms <= 0:
                errors.append(
                    f"sample audio evidence onset tolerance is malformed: {event_id}"
                )
                maximum_onset_error_ms = 0.0
            if observed_perceptual["audibility_status"] != "audible_without_masking":
                errors.append(
                    f"sample audio evidence cue is not audible without masking: {event_id}"
                )
            if abs(float(observed_perceptual["onset_error_ms"])) > maximum_onset_error_ms:
                errors.append(
                    f"sample audio evidence cue onset exceeds {maximum_onset_error_ms:.0f} ms: {event_id}"
                )
            if (
                remeasured["residual_mean_dbfs"] <= -60.0
                or remeasured["on_peak_dbfs"] > -0.05
                or remeasured["mix_gain_delta_db"] > 4.0
            ):
                errors.append(f"sample audio evidence cue fails measured mix thresholds: {event_id}")
        elif (
            artifact_paths["sfx_off"].read_bytes() != artifact_paths["sfx_on"].read_bytes()
            or (row.get("perceptual") or {}).get("audibility_status") != "not_applicable"
        ):
            errors.append(f"sample audio evidence intentional silence is not bit-identical: {event_id}")
    return errors


def sample_audio_evidence_artifacts(evidence_path: Path) -> list[Path]:
    """Return every nested file whose bytes make a sample-audio receipt current."""
    evidence_path = evidence_path.resolve()
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("sample audio evidence must be an object with events")
    result = [evidence_path]
    for row in payload["events"]:
        if not isinstance(row, dict):
            raise ValueError("sample audio evidence event must be an object")
        for role in ("sfx_off", "sfx_on"):
            artifact = row.get(role)
            if not isinstance(artifact, dict):
                raise ValueError(f"sample audio evidence {role} record is missing")
            path = Path(str(artifact.get("path") or ""))
            if not path.is_absolute() or not path.is_file() or artifact.get("sha256") != _sha256(path):
                raise ValueError(f"sample audio evidence {role} record is stale")
            result.append(path.resolve())
    return result


def materialize_sample_review_mix(
    *, candidate_media: Path, audio_plan: Path, output: Path,
    receipt_path: Path, runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Mix every planned sample SFX cue into the review candidate before captions."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required for the sample review mix")
    candidate_media = candidate_media.resolve()
    audio_plan = audio_plan.resolve()
    output = output.resolve()
    receipt_path = receipt_path.resolve()
    for label, path in (("candidate", candidate_media), ("audio plan", audio_plan)):
        if not path.is_file():
            raise FileNotFoundError(f"sample review mix {label} is missing: {path}")
    plan = json.loads(audio_plan.read_text(encoding="utf-8"))
    decisions = [
        row for row in ((plan.get("motion_sfx") or {}).get("event_decisions") or [])
        if isinstance(row, dict) and row.get("decision") == "cue"
    ]
    if not decisions:
        raise ValueError("sample review mix requires at least one planned SFX cue")

    cue_paths: list[Path] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, decision in enumerate(decisions, start=1):
        cue = _authorized_sfx_path(audio_plan, decision.get("asset"))
        cue_paths.append(cue)
        start = max(0.0, float(decision.get("start", 0.0)))
        duration_value = decision.get("duration_seconds")
        duration = max(0.05, float(
            duration_value if duration_value is not None else _probe_duration(cue)
        ))
        volume = max(0.0, float(decision.get("volume", 0.28)))
        label = f"cue{index}"
        labels.append(f"[{label}]")
        filters.append(
            f"[{index}:a]atrim=0:{duration:.6f},asetpts=PTS-STARTPTS,"
            f"volume={volume:.6f},adelay={round(start * 1000)}:all=1[{label}]"
        )
    filters.append(
        f"[0:a]{''.join(labels)}amix=inputs={len(labels) + 1}:duration=first:"
        "dropout_transition=0:normalize=0,alimiter=limit=0.95[aout]"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(
        f".{output.stem}.{uuid.uuid4().hex}.mixing{output.suffix}"
    )
    temporary.unlink(missing_ok=True)
    argv = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(candidate_media)]
    for cue in cue_paths:
        argv.extend(["-i", str(cue)])
    argv.extend([
        "-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(temporary),
    ])
    try:
        runner(argv, check=True, capture_output=True, text=True, encoding="utf-8")
        runner(
            ["ffmpeg", "-v", "error", "-i", str(temporary),
             "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        _replace_with_retry(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    recorded_argv = [str(output) if value == str(temporary) else value for value in argv]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass",
        "mode": "planned_sfx_over_hyperframes_candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_input": {"path": str(candidate_media), "sha256": _sha256(candidate_media)},
        "audio_plan": {"path": str(audio_plan), "sha256": _sha256(audio_plan)},
        "output": {"path": str(output), "sha256": _sha256(output)},
        "cue_count": len(decisions),
        "cue_assets": [
            {"event_id": str(decision.get("event_id") or ""), "path": str(path),
             "sha256": _sha256(path)}
            for decision, path in zip(decisions, cue_paths)
        ],
        "argv": recorded_argv,
        "full_decode": True,
    }
    errors = validate_sample_review_mix_receipt(
        receipt, candidate_media=candidate_media, audio_plan=audio_plan, output=output,
    )
    if errors:
        raise ValueError("; ".join(errors))
    write_json(receipt_path, receipt)
    return receipt


def materialize_sample_audio_evidence(
    *, storyboard: Path, audio_plan: Path, candidate_media: Path, output_dir: Path,
) -> list[Path]:
    """Create aligned SFX off/on auditions and measured mixed-preview evidence."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required for sample audio evidence")
    storyboard_payload = json.loads(storyboard.read_text(encoding="utf-8"))
    plan = json.loads(audio_plan.read_text(encoding="utf-8"))
    candidate_duration = _probe_duration(candidate_media)
    events = {
        str(event.get("id")): event
        for event in (storyboard_payload.get("events") or [])
        if isinstance(event, dict) and event.get("treatment") != "quiet_source"
    }
    decisions = {
        str(row.get("event_id")): row
        for row in ((plan.get("motion_sfx") or {}).get("event_decisions") or [])
        if isinstance(row, dict) and row.get("event_id")
    }
    if set(events) != set(decisions):
        missing = sorted(set(events) - set(decisions))
        extra = sorted(set(decisions) - set(events))
        raise ValueError(f"audio decisions do not match storyboard events; missing={missing}, extra={extra}")

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir.resolve().parent / "mix-audibility.json"
    artifacts: list[Path] = []
    event_evidence: list[dict[str, Any]] = []
    for event_id, event in events.items():
        decision = decisions[event_id]
        semantic_event_id = _event_stem(event.get("semantic_event_id") or event_id)
        cue_start = float(decision.get("start", event.get("start", 0.0)))
        cue_duration = max(float(decision.get("duration_seconds", 0.0)), 0.6)
        clip_start = max(0.0, cue_start - 1.0)
        desired_duration = max(2.5, cue_start - clip_start + cue_duration + 0.6)
        clip_duration = min(5.0, desired_duration, candidate_duration - clip_start)
        if clip_duration <= 0.1:
            raise ValueError(f"audio audition window is outside candidate media: {event_id}")
        off_path = (output_dir / f"{semantic_event_id}-sfx-off.wav").resolve()
        on_path = (output_dir / f"{semantic_event_id}-sfx-on.wav").resolve()
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{clip_start:.6f}", "-i", str(candidate_media),
                "-t", f"{clip_duration:.6f}", "-vn", "-ac", "2", "-ar", "48000",
                "-c:a", "pcm_s16le", str(off_path),
            ],
            check=True,
        )
        if decision.get("decision") == "cue":
            cue_path = _authorized_sfx_path(audio_plan, decision.get("asset"))
            delay_ms = max(0, round((cue_start - clip_start) * 1000.0))
            planned_volume = float(decision.get("volume", 0.28))
            volume = planned_volume
            planned_post_gain = decision.get("post_gain_mean_dbfs")
            metrics: dict[str, float] | None = None
            for _attempt in range(12):
                filter_graph = (
                    f"[1:a]atrim=0:{cue_duration:.6f},asetpts=PTS-STARTPTS,"
                    f"volume={volume:.6f},adelay={delay_ms}:all=1[cue];"
                    "[0:a][cue]amix=inputs=2:duration=first:dropout_transition=0,"
                    "alimiter=limit=0.95[out]"
                )
                subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(off_path), "-i", str(cue_path),
                        "-filter_complex", filter_graph, "-map", "[out]",
                        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(on_path),
                    ],
                    check=True,
                )
                metrics = _wave_metrics(off_path, on_path)
                if (
                    metrics["residual_mean_dbfs"] > -60.0
                    and metrics["on_peak_dbfs"] <= -0.05
                    and metrics["mix_gain_delta_db"] <= 4.0
                ):
                    break
                if metrics["mix_gain_delta_db"] > 4.0 or metrics["on_peak_dbfs"] > -0.05:
                    volume = max(0.05, volume * 0.8)
                else:
                    volume = min(planned_volume, volume * 1.15)
            perceptual = _perceptual_mix_metrics(
                off_path=off_path, on_path=on_path, cue_path=cue_path,
                planned_delay_seconds=max(0.0, cue_start - clip_start),
            )
            decision["motif_fingerprint_sha256"] = perceptual["motif_fingerprint"]["sha256"]
            applied_volume = round(volume, 3)
            decision["volume"] = applied_volume
            if planned_post_gain is not None and planned_volume > 0:
                decision["post_gain_mean_dbfs"] = round(
                    float(planned_post_gain)
                    + 20.0 * math.log10(applied_volume / planned_volume),
                    1,
                )
        elif decision.get("decision") == "intentionally_silent":
            planned_volume = None
            volume = None
            shutil.copyfile(off_path, on_path)
            metrics = _wave_metrics(off_path, on_path)
            perceptual = {
                "motif_fingerprint": None,
                "dialogue_window_lufs": float(metrics["off_mean_dbfs"]),
                "cue_window_lufs": -120.0,
                "dialogue_cue_delta_lu": 120.0,
                "onset_error_ms": 0.0,
                "audibility_status": "not_applicable",
                "measurement_method": "intentional-silence-identity-v1",
            }
        else:
            raise ValueError(f"unsupported SFX decision for {event_id}: {decision.get('decision')}")

        assert metrics is not None
        if decision.get("decision") == "cue":
            passed = (
                metrics["residual_mean_dbfs"] > -60.0
                and metrics["on_peak_dbfs"] <= -0.05
                and metrics["mix_gain_delta_db"] <= 4.0
                and perceptual["audibility_status"] == "audible_without_masking"
                and abs(float(perceptual["onset_error_ms"])) <= float(
                    decision.get("portrait_landing_tolerance_ms", 80.0)
                )
            )
        else:
            passed = _sha256(off_path) == _sha256(on_path)
        event_evidence.append({
            "event_id": event_id,
            "semantic_event_id": semantic_event_id,
            "decision": decision.get("decision"),
            "decision_binding": _decision_binding(decision, audio_plan),
            "planned_volume": planned_volume,
            "applied_volume": round(volume, 3) if volume is not None else None,
            "cue_start_seconds": cue_start,
            "excerpt_start_seconds": round(clip_start, 3),
            "excerpt_duration_seconds": round(clip_duration, 3),
            "sfx_off": _audio_artifact(off_path, role="speech-only audition"),
            "sfx_on": _audio_artifact(on_path, role="speech plus planned SFX audition"),
            "perceptual": perceptual,
            **metrics,
            "status": "pass" if passed else "fail",
        })
        artifacts.extend((off_path, on_path))

    status = "pass" if all(row["status"] == "pass" for row in event_evidence) else "fail"
    write_json(evidence_path, {
        "schema_version": 1,
        "status": status,
        "storyboard": {"path": str(storyboard.resolve()), "sha256": _sha256(storyboard)},
        "candidate_media": {
            "path": str(candidate_media.resolve()),
            "sha256": _sha256(candidate_media),
            "duration_seconds": round(candidate_duration, 3),
        },
        "measurement": "sample-aligned 16-bit PCM residual and mixed-preview level analysis",
        "thresholds": {
            "minimum_residual_mean_dbfs": -60.0,
            "maximum_on_peak_dbfs": -0.05,
            "maximum_mix_gain_delta_db": 4.0,
        },
        "events": event_evidence,
    })
    if status != "pass":
        raise RuntimeError("sample SFX mixed-preview audibility evidence failed")
    plan.setdefault("motion_sfx", {})["mix_audibility_check"] = {
        "status": "pass",
        "evidence": str(evidence_path.resolve()),
        "evidence_sha256": _sha256(evidence_path),
        "candidate_sha256": _sha256(candidate_media),
    }
    plan["motion_sfx"]["perceptual_evidence"] = {
        "path": str(evidence_path.resolve()),
        "sha256": _sha256(evidence_path),
    }
    write_json(audio_plan, plan)
    return [*artifacts, evidence_path.resolve(), audio_plan.resolve()]


def _resolve(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _asset_result(path: Path, *, provider: str, authorization: str, model: Any = None,
                  prompt: Any = None) -> dict[str, Any]:
    return {
        "mode": "authorized_asset",
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "authorization": authorization,
        "quota_stopped_after_success": True,
    }


def resolve_bgm(
    config: dict[str, Any], *, root: Path, output_dir: Path, runner: AdapterRunner,
) -> dict[str, Any]:
    if config.get("enabled", config.get("enabled_by_default", True)) is not True:
        return {"mode": "disabled", "reason": "explicitly disabled", "explicitly_disabled": True}
    approved = _resolve(root, config.get("asset"))
    if approved and approved.is_file():
        return _asset_result(
            approved, provider="approved_local",
            authorization=str(config.get("authorization") or "project-authorized asset"),
        )
    attempts: list[dict[str, Any]] = []
    providers = config.get("provider_chain") or []
    for provider in providers:
        if not isinstance(provider, dict) or provider.get("enabled") is not True:
            continue
        name = str(provider.get("name") or "provider")
        if provider.get("requires_paid_call") is True and provider.get("paid_call_authorized") is not True:
            attempts.append({"provider": name, "status": "action_required",
                             "reason": "paid external generation is not authorized"})
            continue
        output = _resolve(root, provider.get("output")) or (output_dir / f"{name}-bgm.wav")
        command = provider.get("command") or []
        if not isinstance(command, list) or not command:
            attempts.append({"provider": name, "status": "unavailable",
                             "reason": "no executable adapter command configured"})
            continue
        result = runner.run(
            name=f"bgm_{name}", enabled=True, command=[str(value) for value in command],
            inputs=[], outputs=[output], blocking=False, cwd=root,
            settings={"provider": name, "model": provider.get("model"),
                      "prompt": provider.get("prompt"), "timeout_seconds": provider.get("timeout_seconds", 900)},
        )
        attempts.append({"provider": name, "status": result.get("status")})
        if result.get("status") in {"complete", "reused"} and output.is_file():
            selected = _asset_result(
                output, provider=name,
                authorization=str(provider.get("authorization") or "configured provider authorization"),
                model=provider.get("model"), prompt=provider.get("prompt"),
            )
            selected["attempts"] = attempts
            return selected
    return {"mode": "unavailable", "reason": "no approved BGM provider produced an asset",
            "attempts": attempts}


def build_audio_plan(
    sfx_manifest: dict[str, Any], *, source_audio: str, bgm: dict[str, Any],
    preview_volume: float,
) -> dict[str, Any]:
    decisions = list(sfx_manifest.get("event_decisions") or [])
    cue_count = sum(row.get("decision") == "cue" for row in decisions)
    if bgm.get("mode") == "authorized_asset":
        background = {
            "mode": "authorized_asset", "enabled": True, "source": bgm["path"],
            "preview_volume": preview_volume,
            "ducking": {"enabled": True, "method": "sidechaincompress",
                        "status": "pending_final_mix_measurement"},
            "provenance": {key: bgm.get(key) for key in
                           ("provider", "model", "prompt", "authorization", "sha256")},
        }
    else:
        mode = "disabled" if bgm.get("mode") == "disabled" else "unavailable"
        background = {"mode": mode, "enabled": False,
                      "reason": bgm.get("reason") or "no BGM selected",
                      "explicitly_disabled": bgm.get("explicitly_disabled") is True,
                      "attempts": list(bgm.get("attempts") or [])}
    return {
        "schema_version": 3,
        "speech_track": {"source": source_audio, "dominant": True, "immutable": True},
        "motion_sfx": {
            "event_decisions": decisions,
            "mix_audibility_check": {
                "status": "pending_render_measurement" if cue_count else "not_applicable",
                "reason": "measure after SFX is mixed with real speech" if cue_count else "no cue events",
            },
        },
        "background_music": background,
        "provenance": {
            "source_audio": source_audio,
            "motion_sfx": "project-owned deterministic multi-note assets",
            "background_music": bgm,
        },
    }


def produce_audio_assets(
    *, storyboard: Path, project: dict[str, Any], project_root: Path,
    output_dir: Path, source_audio: Path, runner: AdapterRunner,
    semantic_brief: Path | None = None,
    portrait_motion_contracts: Path | None = None,
    portrait_profile: Path | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sfx_dir = storyboard.parent / "assets" / "sfx"
    sfx_manifest_path = storyboard.parent / "audio-sfx-manifest.json"
    sfx_config = project.get("audio", {}).get("sfx", {})
    portrait_enabled = (
        portrait_motion_contracts is not None and portrait_profile is not None
    )
    semantic_payload: dict[str, Any] | None = None
    storyboard_payload: dict[str, Any] | None = None
    if portrait_enabled:
        if semantic_brief is None or not semantic_brief.is_file():
            raise FileNotFoundError("portrait audio production requires semantic brief")
        storyboard_payload = json.loads(storyboard.read_text(encoding="utf-8"))
        semantic_payload = json.loads(semantic_brief.read_text(encoding="utf-8"))
        if not isinstance(storyboard_payload, dict) or not isinstance(semantic_payload, dict):
            raise ValueError("portrait audio storyboard and semantic brief must be objects")
        # Portrait motif assets are compiled below; do not generate the generic
        # screen/product SFX library first and then leave its bytes unused.
        manifest = {
            "schema_version": 2,
            "storyboard": str(storyboard.resolve()),
            "assets": [],
            "event_decisions": [],
        }
    elif sfx_config.get("enabled", True) is True:
        audio_storyboard = storyboard
        if semantic_brief is not None and semantic_brief.is_file():
            storyboard_payload = json.loads(storyboard.read_text(encoding="utf-8"))
            semantic_payload = json.loads(semantic_brief.read_text(encoding="utf-8"))
            semantic_by_id = {
                str(event.get("id")): event
                for event in (semantic_payload.get("events") or [])
                if isinstance(event, dict)
            }
            enriched_events = []
            for event in storyboard_payload.get("events") or []:
                enriched = dict(event)
                semantic = semantic_by_id.get(str(event.get("semantic_event_id") or event.get("id")))
                if semantic and semantic.get("audio_decision") is not None:
                    enriched["audio_decision"] = semantic["audio_decision"]
                enriched_events.append(enriched)
            storyboard_payload["events"] = enriched_events
            audio_storyboard = output_dir / "audio-storyboard.json"
            write_json(audio_storyboard, storyboard_payload)
        manifest = build_for_storyboard(audio_storyboard, sfx_dir, "assets/sfx")
    else:
        payload = json.loads(storyboard.read_text(encoding="utf-8"))
        manifest = {
            "schema_version": 2, "storyboard": str(storyboard.resolve()), "assets": [],
            "event_decisions": [
                {"event_id": str(event.get("id")), "decision": "intentionally_silent",
                 "reason": "project SFX is explicitly disabled"}
                for event in (payload.get("events") or []) if event.get("treatment") != "quiet_source"
            ],
        }
    bgm = resolve_bgm(
        project.get("audio", {}).get("bgm", {}), root=project_root,
        output_dir=output_dir / "bgm", runner=runner,
    )
    bgm_manifest = output_dir / "bgm-provenance.json"
    write_json(bgm_manifest, bgm)
    plan_path = storyboard.parent / "audio-plan.json"
    plan_payload = build_audio_plan(
        manifest, source_audio=str(source_audio.resolve()), bgm=bgm,
        preview_volume=float(project.get("audio", {}).get("bgm", {}).get("preview_volume", 0.1)),
    )
    portrait_outputs: list[Path] = []
    if portrait_enabled:
        from portrait_sonic import (
            DEFAULT_PORTRAIT_SONIC_REGISTRY,
            compile_portrait_sonic_plan,
            materialize_portrait_sonic_library,
            project_portrait_sonic_plan,
        )

        assert portrait_motion_contracts is not None
        assert portrait_profile is not None
        assert semantic_payload is not None
        assert storyboard_payload is not None
        semantic_for_audio = json.loads(json.dumps(semantic_payload))
        library_manifest = materialize_portrait_sonic_library(
            DEFAULT_PORTRAIT_SONIC_REGISTRY,
            output_dir / "portrait-sonic-library",
        )
        compiled = compile_portrait_sonic_plan(
            project_id=str(project.get("video_id") or project_root.name),
            profile_path=portrait_profile,
            motion_contracts_path=portrait_motion_contracts,
            semantic_brief=semantic_for_audio,
            library_manifest_path=library_manifest,
        )
        if sfx_config.get("enabled", True) is not True:
            compiled["plan"]["decisions"] = [
                {
                    "event_id": row["event_id"],
                    "recipe_id": row["recipe_id"],
                    "decision": "intentionally_silent",
                    "reason": "Project SFX is explicitly disabled for this portrait event.",
                }
                for row in compiled["plan"]["decisions"]
            ]
            compiled["report"]["status"] = "explicitly_disabled"
            compiled["report"]["cue_count"] = 0
            compiled["report"]["diagnostics"] = [
                {
                    "event_id": row["event_id"],
                    "decision": "intentionally_silent",
                    "reason": row["reason"],
                }
                for row in compiled["plan"]["decisions"]
            ]
        sonic_plan_path = portrait_motion_contracts.parent / "portrait-sonic-plan.json"
        sonic_report_path = portrait_motion_contracts.parent / "portrait-sonic-compile-report.json"
        write_json(sonic_plan_path, compiled["plan"])
        write_json(sonic_report_path, compiled["report"])
        plan_payload = project_portrait_sonic_plan(
            compiled["plan"], plan_payload,
            base_dir=storyboard.parent,
            motion_contracts_path=portrait_motion_contracts,
            storyboard=storyboard_payload,
        )
        manifest["event_decisions"] = list(plan_payload["motion_sfx"]["event_decisions"])
        manifest["assets"] = []
        for decision in manifest["event_decisions"]:
            if decision.get("decision") != "cue":
                continue
            cue_path = (storyboard.parent / str(decision["asset"])).resolve()
            rights_path = (storyboard.parent / str(decision["rights_evidence"])).resolve()
            manifest["assets"].append({
                "event_id": str(decision["event_id"]),
                "semantic_event_id": str(decision.get("semantic_event_id") or decision["event_id"]),
                "family": str(decision["family"]),
                "variant": str(decision["variant_id"]),
                "duration_seconds": float(decision["duration_seconds"]),
                "post_gain_mean_dbfs": float(decision["post_gain_mean_dbfs"]),
                "frozen_path": str(cue_path),
                "sha256": _sha256(cue_path),
                "source": "HongRun portrait sonic v2 original local synthesis",
                "license": "project-owned original synthesis",
                "rights_evidence": {"path": str(rights_path), "sha256": _sha256(rights_path)},
            })
        portrait_outputs = [
            sonic_plan_path, sonic_report_path, library_manifest,
            *[
                path for path in (library_manifest.parent.rglob("*"))
                if path.is_file() and path != library_manifest
            ],
        ]
    write_json(sfx_manifest_path, manifest)
    write_json(plan_path, plan_payload)
    assets = [Path(row["frozen_path"]) for row in manifest.get("assets") or []]
    return [sfx_manifest_path, bgm_manifest, plan_path, *assets, *portrait_outputs]
