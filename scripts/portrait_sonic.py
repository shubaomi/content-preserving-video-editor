#!/usr/bin/env python3
"""Compile HongRun portrait sonic decisions into the existing audio pipeline."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from audio_production import perceptual_motif_fingerprint
from director_contracts import read_json, sha256_file, write_json
from portrait_brand_contracts import validate_portrait_contract_schema
from safe_generated_output import (
    SafeGeneratedOutputError, safe_generated_directory, safe_generated_target,
)


ROOT = Path(__file__).parents[1]
DEFAULT_PORTRAIT_SONIC_REGISTRY = ROOT / "references" / "portrait-sonic-motifs-v2.json"
FAMILY_IDS = tuple(f"PBM-S0{index}" for index in range(1, 6))
RECIPE_FAMILY = {
    "PBM-01": "PBM-S01",
    "PBM-02": "PBM-S02",
    "PBM-03": "PBM-S02",
    "PBM-04": "PBM-S03",
    "PBM-05": "PBM-S04",
    "PBM-06": "PBM-S02",
    "PBM-07": "PBM-S04",
    "PBM-08": "PBM-S05",
}
ALLOWED_PHASES = {"entrance", "explain", "hold", "exit"}
ALLOWED_ROLES = {"mark", "explain", "relate", "resolve", "transition"}
RIGHTS_BASIS = "project_owned_original_synthesis"


class PortraitSonicError(ValueError):
    """Raised when a sonic decision would require guessing or stale evidence."""


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PortraitSonicError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PortraitSonicError(f"{label} must be a finite number")
    return result


def _synthesis_shape(spec: Mapping[str, Any]) -> str:
    """Hash non-pitch structure so transposition alone is not counted as variety."""
    notes = spec.get("notes") if isinstance(spec.get("notes"), list) else []
    shape = {
        "waveform": spec.get("waveform"),
        "notes": [
            [row[0], row[1], row[3], row[4], len(row)]
            for row in notes if isinstance(row, list) and len(row) in {5, 6}
        ],
        "noise_level": spec.get("noise_level"),
        "tail_seconds": spec.get("tail_seconds"),
        "duration_seconds": spec.get("duration_seconds"),
    }
    return _stable_hash(shape)


def validate_portrait_sonic_registry(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["portrait sonic registry must be a mapping"]
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("portrait sonic registry schema_version must be 1")
    if payload.get("status") != "proposed":
        errors.append("portrait sonic registry must remain proposed before user taste approval")
    if payload.get("signature_envelope") != ["pulse", "orbit", "focus"]:
        errors.append("portrait sonic signature envelope must be pulse/orbit/focus")
    policy = payload.get("selection_policy")
    if not isinstance(policy, Mapping) or any(
        policy.get(key) is not expected
        for key, expected in (
            ("semantic_role_only", True), ("fixed_cadence", False),
            ("minimum_cue_quota", False), ("random_rotation", False),
            ("speech_is_primary", True),
        )
    ):
        errors.append("portrait sonic selection policy must be semantic, speech-first, and non-cadenced")
    families = payload.get("families")
    if not isinstance(families, list):
        return [*errors, "portrait sonic families must be a list"]
    ids = [row.get("family_id") for row in families if isinstance(row, Mapping)]
    if ids != list(FAMILY_IDS):
        errors.append("portrait sonic families must equal PBM-S01 through PBM-S05 in order")
    variant_ids: set[str] = set()
    recipe_ids: set[str] = set()
    for index, family in enumerate(families):
        label = f"portrait sonic families[{index}]"
        if not isinstance(family, Mapping):
            errors.append(f"{label} must be a mapping")
            continue
        family_id = str(family.get("family_id") or "")
        recipes = family.get("recipe_ids")
        if not isinstance(recipes, list) or not recipes:
            errors.append(f"{label} recipe_ids must be a non-empty list")
        else:
            for recipe_id in recipes:
                if RECIPE_FAMILY.get(str(recipe_id)) != family_id:
                    errors.append(f"{label} recipe mapping is stale: {recipe_id}")
                if str(recipe_id) in recipe_ids:
                    errors.append(f"portrait sonic recipe appears in multiple families: {recipe_id}")
                recipe_ids.add(str(recipe_id))
        if family.get("phase") not in ALLOWED_PHASES:
            errors.append(f"{label} phase is unsupported")
        tolerance = family.get("landing_tolerance_ms")
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not 0 < float(tolerance) <= 180:
            errors.append(f"{label} landing_tolerance_ms is invalid")
        duration_range = family.get("duration_range_seconds")
        if not (
            isinstance(duration_range, list) and len(duration_range) == 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in duration_range)
            and 0.35 <= float(duration_range[0]) <= float(duration_range[1]) <= 2.2
        ):
            errors.append(f"{label} duration range is invalid")
            duration_range = [0.35, 2.2]
        variants = family.get("variants")
        if not isinstance(variants, list):
            errors.append(f"{label} variants must be a list")
            continue
        if len(variants) < 2:
            errors.append(f"{label} requires at least two variants")
        if family.get("production_ready") is not False:
            errors.append(f"{label} must remain non-production before named-user approval")
        shape_hashes: set[str] = set()
        for variant_index, variant in enumerate(variants):
            variant_label = f"{label}.variants[{variant_index}]"
            if not isinstance(variant, Mapping):
                errors.append(f"{variant_label} must be a mapping")
                continue
            variant_id = str(variant.get("variant_id") or "")
            if not variant_id or variant_id in variant_ids:
                errors.append(f"{variant_label} variant_id must be non-empty and unique")
            variant_ids.add(variant_id)
            roles = variant.get("semantic_roles")
            if not isinstance(roles, list) or not roles or any(role not in ALLOWED_ROLES for role in roles):
                errors.append(f"{variant_label} semantic_roles are invalid")
            if variant.get("rights_basis") != RIGHTS_BASIS:
                errors.append(f"{variant_label} rights_basis is missing or unsupported")
            synthesis = variant.get("synthesis")
            if not isinstance(synthesis, Mapping):
                errors.append(f"{variant_label} synthesis must be a mapping")
                continue
            try:
                duration = _finite(synthesis.get("duration_seconds"), f"{variant_label}.duration")
            except PortraitSonicError as error:
                errors.append(str(error))
                continue
            if not float(duration_range[0]) <= duration <= float(duration_range[1]):
                errors.append(f"{variant_label} duration is outside its family range")
            if synthesis.get("waveform") not in {"sine", "triangle"}:
                errors.append(f"{variant_label} waveform is unsupported")
            notes = synthesis.get("notes")
            if not isinstance(notes, list) or not notes:
                errors.append(f"{variant_label} notes must be a non-empty list")
            elif any(not isinstance(row, list) or len(row) not in {5, 6} for row in notes):
                errors.append(f"{variant_label} note rows are malformed")
            shape = _synthesis_shape(synthesis)
            if shape in shape_hashes:
                errors.append(f"{label} variants cannot be transposed copies with one synthesis shape")
            shape_hashes.add(shape)
    if set(RECIPE_FAMILY) != recipe_ids:
        errors.append("portrait sonic registry must cover PBM-01 through PBM-08 exactly")
    return errors


def _oscillator(phase: np.ndarray, waveform: str) -> np.ndarray:
    if waveform == "triangle":
        return (2.0 / math.pi) * np.arcsin(np.sin(phase))
    return np.sin(phase)


def _synthesize_variant(variant_id: str, spec: Mapping[str, Any], output: Path) -> None:
    sample_rate = 48_000
    duration = _finite(spec.get("duration_seconds"), f"{variant_id}.duration_seconds")
    frame_count = max(1, round(duration * sample_rate))
    left = np.zeros(frame_count, dtype=np.float64)
    right = np.zeros(frame_count, dtype=np.float64)
    waveform = str(spec.get("waveform") or "sine")
    for index, raw_note in enumerate(spec.get("notes") or []):
        if not isinstance(raw_note, list) or len(raw_note) not in {5, 6}:
            raise PortraitSonicError(f"{variant_id}.notes[{index}] is malformed")
        start, note_duration, frequency, gain, pan = (
            _finite(value, f"{variant_id}.notes[{index}]") for value in raw_note[:5]
        )
        end_frequency = _finite(raw_note[5], f"{variant_id}.notes[{index}].sweep") if len(raw_note) == 6 else frequency
        if start < 0 or note_duration <= 0 or frequency <= 0 or end_frequency <= 0 or not -1 <= pan <= 1:
            raise PortraitSonicError(f"{variant_id}.notes[{index}] is outside synthesis bounds")
        start_frame = min(frame_count, round(start * sample_rate))
        note_frames = min(frame_count - start_frame, round(note_duration * sample_rate))
        if note_frames <= 0:
            continue
        progress = np.linspace(0.0, 1.0, note_frames, endpoint=False)
        frequencies = frequency + (end_frequency - frequency) * progress
        phase = 2.0 * math.pi * np.cumsum(frequencies) / sample_rate
        attack = np.clip(progress / 0.08, 0.0, 1.0)
        release = np.clip((1.0 - progress) / 0.24, 0.0, 1.0)
        envelope = np.minimum(attack, release) ** 1.5
        signal = _oscillator(phase, waveform) * envelope * gain
        left_gain = math.sqrt((1.0 - pan) / 2.0)
        right_gain = math.sqrt((1.0 + pan) / 2.0)
        left[start_frame:start_frame + note_frames] += signal * left_gain
        right[start_frame:start_frame + note_frames] += signal * right_gain
    noise_level = _finite(spec.get("noise_level", 0.0), f"{variant_id}.noise_level")
    if noise_level > 0:
        seed = int(hashlib.sha256(variant_id.encode("utf-8")).hexdigest()[:16], 16)
        rng = np.random.default_rng(seed)
        progress = np.linspace(0.0, 1.0, frame_count, endpoint=False)
        envelope = np.sin(np.pi * np.clip(progress, 0.0, 1.0)) ** 2
        noise = rng.normal(0.0, noise_level, frame_count) * envelope
        left += noise
        right -= noise * 0.7
    fade_frames = min(frame_count, round(float(spec.get("tail_seconds", 0.2)) * sample_rate))
    if fade_frames > 0:
        fade = np.linspace(1.0, 0.0, fade_frames, endpoint=True) ** 1.7
        left[-fade_frames:] *= fade
        right[-fade_frames:] *= fade
    peak = float(max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-9))
    scale = 0.62 / peak
    interleaved = np.column_stack((left * scale, right * scale)).reshape(-1)
    pcm = np.clip(interleaved * 32767.0, -32768, 32767).astype("<i2")
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm.tobytes())


def materialize_portrait_sonic_library(registry_path: Path, output_dir: Path) -> Path:
    """Generate proposed original motif WAVs and auditable project-owned rights records."""
    registry_path = registry_path.resolve()
    output_dir = Path(os.path.abspath(output_dir))
    if not registry_path.is_file():
        raise FileNotFoundError(registry_path)
    registry = read_json(registry_path)
    errors = validate_portrait_sonic_registry(registry)
    if errors:
        raise PortraitSonicError("; ".join(errors))
    try:
        asset_dir = safe_generated_directory(output_dir, Path("assets"))
        rights_dir = safe_generated_directory(output_dir, Path("rights"))
    except SafeGeneratedOutputError as error:
        raise PortraitSonicError(str(error)) from error
    outputs: list[dict[str, Any]] = []
    for family in registry["families"]:
        variants: list[dict[str, Any]] = []
        for variant in family["variants"]:
            variant_id = str(variant["variant_id"])
            try:
                asset = safe_generated_target(output_dir, Path("assets") / f"{variant_id}.wav")
                rights = safe_generated_target(
                    output_dir, Path("rights") / f"{variant_id}.rights.json",
                )
            except SafeGeneratedOutputError as error:
                raise PortraitSonicError(str(error)) from error
            temporary = asset_dir / f".{variant_id}.wav.tmp"
            try:
                _synthesize_variant(variant_id, variant["synthesis"], temporary)
                os.replace(temporary, asset)
            finally:
                temporary.unlink(missing_ok=True)
            fingerprint = perceptual_motif_fingerprint(asset)
            write_json(rights, {
                "schema_version": 1,
                "status": "current",
                "variant_id": variant_id,
                "family_id": family["family_id"],
                "rights_basis": RIGHTS_BASIS,
                "source": "original local synthesis defined by content-preserving-video-editor",
                "proprietary_template_or_asset_used": False,
                "generator": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
                "registry": {"path": str(registry_path), "sha256": sha256_file(registry_path)},
                "asset": {"path": str(asset), "sha256": sha256_file(asset)},
            })
            variants.append({
                "variant_id": variant_id,
                "semantic_roles": list(variant["semantic_roles"]),
                "asset": {"path": str(asset), "sha256": sha256_file(asset)},
                "rights": {"path": str(rights), "sha256": sha256_file(rights)},
                "pcm_fingerprint": fingerprint["sha256"],
                "duration_seconds": fingerprint["duration_seconds"],
                "synthesis_shape_sha256": _synthesis_shape(variant["synthesis"]),
            })
        outputs.append({
            "family_id": family["family_id"],
            "phase": family["phase"],
            "landing_kind": family["landing_kind"],
            "landing_tolerance_ms": family["landing_tolerance_ms"],
            "technical_variant_ready": len(variants) >= 2,
            "production_ready": False,
            "variants": variants,
        })
    manifest = output_dir / "portrait-sonic-library.json"
    write_json(manifest, {
        "schema_version": 1,
        "registry": {"path": str(registry_path), "sha256": sha256_file(registry_path)},
        "generator": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
        "status": "asset_ready_for_style_reel",
        "brand_taste_approved": False,
        "families": outputs,
    })
    return manifest


def _file_ref_errors(row: Any, label: str) -> list[str]:
    if not isinstance(row, Mapping):
        return [f"{label} must be a file reference"]
    path = Path(str(row.get("path") or ""))
    if not path.is_absolute() or not path.is_file():
        return [f"{label} is missing or non-absolute"]
    if row.get("sha256") != sha256_file(path):
        return [f"{label} hash is stale"]
    return []


def validate_portrait_sonic_library(payload: Any, manifest_path: Path | None = None) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["portrait sonic library must be a mapping"]
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("portrait sonic library schema_version must be 1")
    if payload.get("status") != "asset_ready_for_style_reel":
        errors.append("portrait sonic library status is not asset_ready_for_style_reel")
    if payload.get("brand_taste_approved") is not False:
        errors.append("portrait sonic library cannot self-approve brand taste")
    errors.extend(_file_ref_errors(payload.get("registry"), "portrait sonic registry"))
    errors.extend(_file_ref_errors(payload.get("generator"), "portrait sonic generator"))
    canonical_generator = {
        "path": str(Path(__file__).resolve()),
        "sha256": sha256_file(Path(__file__).resolve()),
    }
    if payload.get("generator") != canonical_generator:
        errors.append("portrait sonic generator is not bound to the current compiler")
    registry: Mapping[str, Any] = {}
    registry_ref = payload.get("registry")
    registry_path = (
        Path(str(registry_ref.get("path") or ""))
        if isinstance(registry_ref, Mapping) else Path()
    )
    if registry_path.is_file():
        try:
            loaded_registry = read_json(registry_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"portrait sonic registry is unreadable: {error}")
        else:
            registry_errors = validate_portrait_sonic_registry(loaded_registry)
            errors.extend(registry_errors)
            if isinstance(loaded_registry, Mapping):
                registry = loaded_registry
    registry_families = {
        str(row.get("family_id")): row
        for row in (registry.get("families") or []) if isinstance(row, Mapping)
    }
    families = payload.get("families")
    if not isinstance(families, list):
        return [*errors, "portrait sonic library families must be a list"]
    ids = [row.get("family_id") for row in families if isinstance(row, Mapping)]
    if ids != list(FAMILY_IDS):
        errors.append("portrait sonic library family inventory is incomplete or out of order")
    for index, family in enumerate(families):
        label = f"portrait sonic library families[{index}]"
        if not isinstance(family, Mapping):
            errors.append(f"{label} must be a mapping")
            continue
        family_id = str(family.get("family_id") or "")
        registry_family = registry_families.get(family_id)
        if not isinstance(registry_family, Mapping):
            errors.append(f"{label} is not bound to the current registry")
            registry_family = {}
        for field in ("phase", "landing_kind", "landing_tolerance_ms"):
            if family.get(field) != registry_family.get(field):
                errors.append(f"{label}.{field} differs from the current registry")
        if family.get("technical_variant_ready") is not True:
            errors.append(f"{label} must explicitly pass technical variant readiness")
        if family.get("production_ready") is not False:
            errors.append(f"{label} cannot claim production readiness before user approval")
        variants = family.get("variants")
        if not isinstance(variants, list) or len(variants) < 2:
            errors.append(f"{label} requires two real variants for technical readiness")
            continue
        fingerprints: set[str] = set()
        shapes: set[str] = set()
        registry_variants = {
            str(row.get("variant_id")): row
            for row in (registry_family.get("variants") or []) if isinstance(row, Mapping)
        }
        for variant_index, variant in enumerate(variants):
            variant_label = f"{label}.variants[{variant_index}]"
            if not isinstance(variant, Mapping):
                errors.append(f"{variant_label} must be a mapping")
                continue
            variant_id = str(variant.get("variant_id") or "")
            registry_variant = registry_variants.get(variant_id)
            if not isinstance(registry_variant, Mapping):
                errors.append(f"{variant_label} is not bound to the current registry")
                registry_variant = {}
            if variant.get("semantic_roles") != registry_variant.get("semantic_roles"):
                errors.append(f"{variant_label} semantic roles differ from the current registry")
            expected_shape = (
                _synthesis_shape(registry_variant["synthesis"])
                if isinstance(registry_variant.get("synthesis"), Mapping) else ""
            )
            if variant.get("synthesis_shape_sha256") != expected_shape:
                errors.append(f"{variant_label} synthesis shape differs from the current registry")
            errors.extend(_file_ref_errors(variant.get("asset"), f"{variant_label}.asset"))
            errors.extend(_file_ref_errors(variant.get("rights"), f"{variant_label}.rights"))
            asset_ref = variant.get("asset")
            rights_ref = variant.get("rights")
            asset_path = Path(str(asset_ref.get("path") or "")) if isinstance(asset_ref, Mapping) else Path()
            rights_path = Path(str(rights_ref.get("path") or "")) if isinstance(rights_ref, Mapping) else Path()
            if asset_path.is_file():
                try:
                    fingerprint = perceptual_motif_fingerprint(asset_path)
                except (OSError, ValueError, RuntimeError, wave.Error) as error:
                    errors.append(f"{variant_label} PCM cannot be decoded: {error}")
                else:
                    if variant.get("pcm_fingerprint") != fingerprint["sha256"]:
                        errors.append(f"{variant_label} PCM fingerprint is stale")
                    if variant.get("duration_seconds") != fingerprint["duration_seconds"]:
                        errors.append(f"{variant_label} duration differs from decoded PCM")
                    fingerprints.add(str(variant.get("pcm_fingerprint") or ""))
                    if isinstance(registry_variant.get("synthesis"), Mapping):
                        with tempfile.TemporaryDirectory() as temp:
                            expected_asset = Path(temp) / f"{variant_id}.wav"
                            _synthesize_variant(
                                variant_id, registry_variant["synthesis"], expected_asset,
                            )
                            if sha256_file(expected_asset) != sha256_file(asset_path):
                                errors.append(
                                    f"{variant_label} asset differs from deterministic synthesis"
                                )
            if rights_path.is_file():
                try:
                    rights = read_json(rights_path)
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    errors.append(f"{variant_label} rights are unreadable: {error}")
                else:
                    if not isinstance(rights, Mapping) or rights.get("rights_basis") != RIGHTS_BASIS:
                        errors.append(f"{variant_label} rights_basis is not current project-owned synthesis")
                    if isinstance(rights, Mapping) and rights.get("asset") != variant.get("asset"):
                        errors.append(f"{variant_label} rights do not bind the asset bytes")
                    if isinstance(rights, Mapping):
                        expected_rights = {
                            "status": "current",
                            "variant_id": variant_id,
                            "family_id": family_id,
                            "proprietary_template_or_asset_used": False,
                            "generator": payload.get("generator"),
                            "registry": payload.get("registry"),
                        }
                        for field, expected_value in expected_rights.items():
                            if rights.get(field) != expected_value:
                                errors.append(f"{variant_label} rights {field} is stale")
            shapes.add(str(variant.get("synthesis_shape_sha256") or ""))
        if set(registry_variants) != {
            str(row.get("variant_id") or "") for row in variants if isinstance(row, Mapping)
        }:
            errors.append(f"{label} variant inventory differs from the current registry")
        if len(fingerprints) != len(variants) or len(shapes) != len(variants):
            errors.append(f"{label} variants must be perceptually distinct and not transposed copies")
    return errors


def portrait_sonic_plan_artifacts(plan: Any) -> list[Path]:
    """Return the full current authority chain needed to resume a sonic plan."""
    schema_errors = validate_portrait_contract_schema("portrait-sonic-plan", plan)
    if schema_errors or not isinstance(plan, Mapping):
        raise PortraitSonicError("invalid portrait sonic plan: " + "; ".join(schema_errors))
    result: list[Path] = []
    for label, ref in (
        ("brand profile", plan.get("brand_profile")),
        ("sonic library", plan.get("sonic_library")),
    ):
        ref_errors = _file_ref_errors(ref, f"portrait sonic {label}")
        if ref_errors:
            raise PortraitSonicError("; ".join(ref_errors))
        result.append(Path(str(ref["path"])).resolve())
    library_path = result[-1]
    library = read_json(library_path)
    library_errors = validate_portrait_sonic_library(library, library_path)
    if library_errors or not isinstance(library, Mapping):
        raise PortraitSonicError("invalid portrait sonic library: " + "; ".join(library_errors))
    for key in ("registry", "generator"):
        ref = library.get(key)
        ref_errors = _file_ref_errors(ref, f"portrait sonic library {key}")
        if ref_errors:
            raise PortraitSonicError("; ".join(ref_errors))
        result.append(Path(str(ref["path"])).resolve())
    for family in library.get("families") or []:
        if not isinstance(family, Mapping):
            raise PortraitSonicError("portrait sonic library family must be a mapping")
        for variant in family.get("variants") or []:
            if not isinstance(variant, Mapping):
                raise PortraitSonicError("portrait sonic library variant must be a mapping")
            for key in ("asset", "rights"):
                ref = variant.get(key)
                ref_errors = _file_ref_errors(ref, f"portrait sonic library variant {key}")
                if ref_errors:
                    raise PortraitSonicError("; ".join(ref_errors))
                result.append(Path(str(ref["path"])).resolve())
    return list(dict.fromkeys(result))


def _variant_by_role(family: Mapping[str, Any], role: str) -> Mapping[str, Any] | None:
    variants = family.get("variants")
    if not isinstance(variants, list):
        return None
    for variant in variants:
        if isinstance(variant, Mapping) and role in (variant.get("semantic_roles") or []):
            return variant
    return next((row for row in variants if isinstance(row, Mapping)), None)


def _landing_for(contract: Mapping[str, Any]) -> tuple[float | None, str, float]:
    recipe_id = str(contract.get("primary_recipe_id") or "")
    if recipe_id == "PBM-03":
        binding = contract.get("gesture_binding")
        if not isinstance(binding, Mapping) or binding.get("output_apex_seconds") is None:
            return None, "gesture", 120.0
        return _finite(binding.get("output_apex_seconds"), "gesture output apex"), "gesture", 120.0
    window = contract.get("output_window")
    if not isinstance(window, Mapping):
        raise PortraitSonicError(f"{recipe_id} output window is missing")
    start = _finite(window.get("start_seconds"), f"{recipe_id} output window start")
    if recipe_id == "PBM-07":
        binding = contract.get("chapter_boundary_binding")
        boundary_window = binding.get("window") if isinstance(binding, Mapping) else None
        if not isinstance(boundary_window, Mapping):
            return None, "chapter", 180.0
        return _finite(boundary_window.get("start_seconds"), "chapter boundary"), "chapter", 180.0
    return start, "word" if recipe_id in {"PBM-01", "PBM-04", "PBM-08"} else "visual", 80.0 if recipe_id in {"PBM-01", "PBM-04", "PBM-08"} else 120.0


def compile_portrait_sonic_plan(
    *, project_id: str, profile_path: Path, motion_contracts_path: Path,
    semantic_brief: Mapping[str, Any], library_manifest_path: Path,
    allow_unavailable_library: bool = False,
) -> dict[str, Any]:
    """Compile one decision per portrait event without making cue availability creative input."""
    profile_path = profile_path.resolve()
    motion_contracts_path = motion_contracts_path.resolve()
    library_manifest_path = library_manifest_path.resolve()
    for path in (profile_path, motion_contracts_path, library_manifest_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    profile = read_json(profile_path)
    profile_errors = validate_portrait_contract_schema("portrait-brand-profile", profile)
    if profile_errors:
        raise PortraitSonicError("invalid portrait profile: " + "; ".join(profile_errors))
    motion_bundle = read_json(motion_contracts_path)
    if not isinstance(motion_bundle, Mapping) or not isinstance(motion_bundle.get("contracts"), list):
        raise PortraitSonicError("portrait motion contracts must be a mapping with contracts")
    if not isinstance(semantic_brief, Mapping) or not isinstance(semantic_brief.get("events"), list):
        raise PortraitSonicError("semantic brief must be a mapping with events")
    library = read_json(library_manifest_path)
    library_errors = validate_portrait_sonic_library(library, library_manifest_path)
    if library_errors and not allow_unavailable_library:
        raise PortraitSonicError("invalid portrait sonic library: " + "; ".join(library_errors))
    if library_errors:
        # The permissive route means visual-only fallback, never permission to
        # consume a partially valid or self-signed asset inventory.
        library = {}
    families = {
        str(row.get("family_id")): row
        for row in (library.get("families") or []) if isinstance(row, Mapping)
    } if isinstance(library, Mapping) else {}
    semantic_by_id = {
        str(row.get("id")): row
        for row in semantic_brief["events"] if isinstance(row, Mapping)
    }
    contracts = [row for row in motion_bundle["contracts"] if isinstance(row, Mapping)]
    contract_ids = [str(row.get("semantic_event_id") or "") for row in contracts]
    if not contract_ids or any(not value for value in contract_ids) or len(set(contract_ids)) != len(contract_ids):
        raise PortraitSonicError("portrait motion contract event IDs must be non-empty and unique")
    semantic_rows = semantic_brief["events"]
    if any(not isinstance(row, Mapping) for row in semantic_rows):
        raise PortraitSonicError("portrait sonic semantic events must be mappings")
    semantic_ids = [str(row.get("id") or "") for row in semantic_rows]
    if any(not value for value in semantic_ids) or len(set(semantic_ids)) != len(semantic_ids):
        raise PortraitSonicError("portrait sonic semantic event IDs must be non-empty and unique")
    render_ids = [
        str(row.get("id") or "") for row in semantic_rows
        if row.get("decision", "render") == "render"
    ]
    if contract_ids != render_ids:
        raise PortraitSonicError(
            "portrait motion render event set/order differs from semantic brief"
        )
    semantic_hash = _stable_hash(semantic_brief)
    for contract in contracts:
        event_id = str(contract.get("semantic_event_id") or "")
        semantic = semantic_by_id[event_id]
        expected_window = {
            "start_seconds": semantic.get("output_start"),
            "end_seconds": semantic.get("output_end"),
        }
        if contract.get("output_window") != expected_window:
            raise PortraitSonicError(
                f"{event_id}: portrait motion output window differs from semantic brief"
            )
        input_hashes = contract.get("input_hashes")
        if not isinstance(input_hashes, Mapping) or input_hashes.get("semantic_brief") != semantic_hash:
            raise PortraitSonicError(
                f"{event_id}: portrait motion semantic authority hash is missing or stale"
            )
    decisions: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    unavailable = False
    for contract in contracts:
        event_id = str(contract["semantic_event_id"])
        recipe_id = str(contract.get("primary_recipe_id") or "")
        family_id = RECIPE_FAMILY.get(recipe_id)
        if family_id is None:
            raise PortraitSonicError(f"{event_id}: unsupported portrait recipe {recipe_id}")
        if family_id not in (profile.get("sonic_family_ids") or []):
            raise PortraitSonicError(f"{event_id}: {family_id} is outside the exact brand profile")
        semantic = semantic_by_id[event_id]
        audio_decision = semantic.get("audio_decision")
        if not isinstance(audio_decision, Mapping):
            raise PortraitSonicError(f"{event_id}: semantic audio_decision is missing")
        if audio_decision.get("type") == "intentionally_silent":
            reason = str(audio_decision.get("reason") or "").strip()
            if len(reason) < 8:
                raise PortraitSonicError(f"{event_id}: intentionally silent reason is too short")
            decisions.append({
                "event_id": event_id, "recipe_id": recipe_id,
                "decision": "intentionally_silent", "reason": reason,
            })
            diagnostics.append({"event_id": event_id, "decision": "intentionally_silent", "reason": reason})
            continue
        if audio_decision.get("type") != "cue":
            raise PortraitSonicError(f"{event_id}: unsupported semantic audio decision")
        family = families.get(family_id)
        role = str(semantic.get("semantic_role") or "explain")
        variant = _variant_by_role(family or {}, role)
        landing, landing_kind, tolerance_ms = _landing_for(contract)
        requested_variant = audio_decision.get("asset") or audio_decision.get("asset_path")
        if requested_variant:
            variant = next((
                row for row in ((family or {}).get("variants") or [])
                if isinstance(row, Mapping) and row.get("variant_id") == requested_variant
            ), None)
        if not isinstance(family, Mapping) or not isinstance(variant, Mapping) or landing is None:
            unavailable = True
            reason = (
                f"Verified output-time gesture apex is unavailable for {event_id}."
                if landing is None else
                f"Two current authorized {family_id} variants are unavailable for {event_id}."
            )
            decisions.append({
                "event_id": event_id, "recipe_id": recipe_id,
                "decision": "intentionally_silent", "reason": reason,
            })
            diagnostics.append({
                "event_id": event_id, "decision": "intentionally_silent",
                "requested_family_id": family_id, "reason": reason,
            })
            continue
        asset = variant.get("asset")
        rights = variant.get("rights")
        file_errors = [
            *_file_ref_errors(asset, f"{event_id} sonic asset"),
            *_file_ref_errors(rights, f"{event_id} sonic rights"),
        ]
        if file_errors:
            if not allow_unavailable_library:
                raise PortraitSonicError("; ".join(file_errors))
            unavailable = True
            reason = f"Current authorized {family_id} asset evidence is unavailable for {event_id}."
            decisions.append({"event_id": event_id, "recipe_id": recipe_id, "decision": "intentionally_silent", "reason": reason})
            diagnostics.append({"event_id": event_id, "decision": "intentionally_silent", "reason": reason})
            continue
        duration = _finite(variant.get("duration_seconds"), f"{event_id} motif duration")
        decisions.append({
            "event_id": event_id,
            "recipe_id": recipe_id,
            "decision": "cue",
            "motif_family_id": family_id,
            "variant_id": str(variant.get("variant_id")),
            "asset": dict(asset),
            "rights": dict(rights),
            "phase": str(family.get("phase")),
            "landing_seconds": round(landing, 6),
            "duration_seconds": duration,
            "gain_db": -16.0,
            "pcm_fingerprint": str(variant.get("pcm_fingerprint") or ""),
        })
        diagnostics.append({
            "event_id": event_id, "decision": "cue", "landing_kind": landing_kind,
            "landing_tolerance_ms": tolerance_ms, "selection_inputs": ["primary_recipe_id", "semantic_role"],
            "fixed_cadence_used": False, "random_rotation_used": False,
        })
    plan = {
        "schema_version": 1,
        "project_id": project_id,
        "brand_profile": {"path": str(profile_path), "sha256": sha256_file(profile_path)},
        "sonic_library": {
            "path": str(library_manifest_path),
            "sha256": sha256_file(library_manifest_path),
        },
        "motion_contract_sha256": sha256_file(motion_contracts_path),
        "decisions": decisions,
        "policy": {
            "decision_coverage": 1.0,
            "cue_coverage_is_adaptive": True,
            "speech_is_primary": True,
            "actual_mix_required": True,
        },
    }
    schema_errors = validate_portrait_contract_schema("portrait-sonic-plan", plan)
    if schema_errors:
        raise PortraitSonicError("; ".join(schema_errors))
    return {
        "plan": plan,
        "report": {
            "schema_version": 1,
            "status": "visual_only_audio_unavailable" if unavailable else "asset_ready_for_style_reel",
            "decision_coverage": len(decisions) / max(len(contracts), 1),
            "cue_count": sum(row["decision"] == "cue" for row in decisions),
            "diagnostics": diagnostics,
            "input_hashes": {
                "profile": sha256_file(profile_path),
                "motion_contracts": sha256_file(motion_contracts_path),
                "semantic_brief": _stable_hash(semantic_brief),
                "library": sha256_file(library_manifest_path),
            },
        },
    }


def _expected_landing(contract: Mapping[str, Any]) -> tuple[float | None, str, float]:
    return _landing_for(contract)


def authorized_portrait_sfx_root(base_dir: Path, *, create: bool = False) -> Path:
    """Return the lexical project SFX root without following a substituted Junction."""
    project_root = Path(base_dir).resolve()
    if create:
        project_root.mkdir(parents=True, exist_ok=True)
    if not project_root.is_dir():
        raise PortraitSonicError("portrait sonic project root is missing")
    current = project_root
    for name in ("assets", "sfx"):
        current = current / name
        if current.is_symlink() or bool(
            getattr(os.path, "isjunction", lambda _path: False)(current)
        ):
            raise PortraitSonicError("portrait sonic authorized SFX root is redirected")
        if create:
            current.mkdir(exist_ok=True)
        if not current.resolve(strict=False).is_relative_to(project_root):
            raise PortraitSonicError("portrait sonic authorized SFX root escapes project")
    return current.resolve(strict=False)


def _relative_asset_copy(ref: Mapping[str, Any], *, base_dir: Path, variant_id: str, suffix: str) -> Path:
    source = Path(str(ref.get("path") or "")).resolve()
    if not source.is_file() or ref.get("sha256") != sha256_file(source):
        raise PortraitSonicError(f"{variant_id} {suffix} reference is stale")
    authorized_root = authorized_portrait_sfx_root(base_dir, create=True)
    brand_root = authorized_root / "portrait-brand-v2"
    brand_root.mkdir(parents=True, exist_ok=True)
    brand_root = brand_root.resolve()
    if not brand_root.is_relative_to(authorized_root):
        raise PortraitSonicError("portrait sonic destination escapes authorized SFX root")
    target_dir = brand_root
    if suffix == "rights":
        target_dir /= "rights"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir = target_dir.resolve()
    if not target_dir.is_relative_to(authorized_root):
        raise PortraitSonicError("portrait sonic destination escapes authorized SFX root")
    target = target_dir / f"{variant_id}{source.suffix}"
    if not target.resolve(strict=False).is_relative_to(authorized_root):
        raise PortraitSonicError("portrait sonic destination escapes authorized SFX root")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target_dir,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != ref.get("sha256"):
            raise PortraitSonicError(f"{variant_id} copied {suffix} hash differs")
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _mean_dbfs(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise PortraitSonicError(f"portrait motif must be 16-bit PCM WAV: {path}")
        data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64)
    if data.size == 0:
        raise PortraitSonicError(f"portrait motif is empty: {path}")
    rms = float(np.sqrt(np.mean(np.square(data))))
    return 20.0 * math.log10(max(rms, 1e-9) / 32767.0)


def project_portrait_sonic_plan(
    plan: Mapping[str, Any], audio_plan: Mapping[str, Any], *, base_dir: Path,
    motion_contracts_path: Path, storyboard: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project portrait decisions into schema-v3 audio-plan; existing FFmpeg owns mixing."""
    schema_errors = validate_portrait_contract_schema("portrait-sonic-plan", plan)
    if schema_errors:
        raise PortraitSonicError("; ".join(schema_errors))
    if not isinstance(audio_plan, Mapping):
        raise PortraitSonicError("audio plan must be a mapping")
    motion_contracts_path = motion_contracts_path.resolve()
    if not motion_contracts_path.is_file() or plan.get("motion_contract_sha256") != sha256_file(motion_contracts_path):
        raise PortraitSonicError("portrait sonic plan motion contract hash is stale")
    motion_bundle = read_json(motion_contracts_path)
    contracts = {
        str(row.get("semantic_event_id")): row
        for row in (motion_bundle.get("contracts") or []) if isinstance(row, Mapping)
    } if isinstance(motion_bundle, Mapping) else {}
    decision_ids = [str(row.get("event_id") or "") for row in plan.get("decisions") or [] if isinstance(row, Mapping)]
    if decision_ids != list(contracts):
        raise PortraitSonicError("portrait sonic plan does not exactly cover motion contracts")
    renderer_id_by_semantic: dict[str, str] = {}
    if storyboard is not None:
        if not isinstance(storyboard, Mapping) or not isinstance(storyboard.get("events"), list):
            raise PortraitSonicError("portrait sonic storyboard must be a mapping with events")
        for index, row in enumerate(storyboard["events"]):
            if not isinstance(row, Mapping):
                raise PortraitSonicError(f"portrait sonic storyboard events[{index}] must be a mapping")
            if row.get("treatment") == "quiet_source":
                continue
            semantic_id = str(row.get("semantic_event_id") or row.get("id") or "")
            renderer_id = str(row.get("id") or "")
            if not semantic_id or not renderer_id or semantic_id in renderer_id_by_semantic:
                raise PortraitSonicError("portrait sonic storyboard IDs must be non-empty and unique")
            renderer_id_by_semantic[semantic_id] = renderer_id
        if list(renderer_id_by_semantic) != decision_ids:
            raise PortraitSonicError("portrait sonic storyboard event set/order differs from motion contracts")
    result = copy.deepcopy(dict(audio_plan))
    result["schema_version"] = max(3, int(result.get("schema_version") or 3))
    sfx = result.setdefault("motion_sfx", {})
    if not isinstance(sfx, dict):
        raise PortraitSonicError("audio plan motion_sfx must be a mapping")
    projected: list[dict[str, Any]] = []
    base_dir = base_dir.resolve()
    for decision in plan["decisions"]:
        semantic_event_id = str(decision["event_id"])
        event_id = renderer_id_by_semantic.get(semantic_event_id, semantic_event_id)
        if decision["decision"] == "intentionally_silent":
            projected.append({
                "event_id": event_id, "decision": "intentionally_silent",
                "reason": decision["reason"], "portrait_recipe_id": decision["recipe_id"],
                **({"semantic_event_id": semantic_event_id} if event_id != semantic_event_id else {}),
            })
            continue
        expected, landing_kind, tolerance_ms = _expected_landing(contracts[semantic_event_id])
        if expected is None:
            raise PortraitSonicError(f"{landing_kind} landing lacks current output-time evidence: {event_id}")
        observed = float(decision["landing_seconds"])
        delta_ms = (observed - expected) * 1000.0
        if landing_kind == "chapter":
            valid = -tolerance_ms <= delta_ms <= 0.0
        else:
            valid = abs(delta_ms) <= tolerance_ms
        if not valid:
            raise PortraitSonicError(
                f"{landing_kind} landing exceeds {tolerance_ms:.0f} ms tolerance: {event_id}"
            )
        variant_id = str(decision["variant_id"])
        asset = _relative_asset_copy(decision["asset"], base_dir=base_dir, variant_id=variant_id, suffix="asset")
        rights = _relative_asset_copy(decision["rights"], base_dir=base_dir, variant_id=variant_id, suffix="rights")
        fingerprint = perceptual_motif_fingerprint(asset)
        if fingerprint["sha256"] != decision["pcm_fingerprint"]:
            raise PortraitSonicError(f"portrait motif PCM fingerprint is stale: {event_id}")
        gain_db = float(decision["gain_db"])
        volume = 10.0 ** (gain_db / 20.0)
        projected.append({
            "event_id": event_id,
            **({"semantic_event_id": semantic_event_id} if event_id != semantic_event_id else {}),
            "decision": "cue",
            "start": observed,
            "family": decision["motif_family_id"],
            "variant_id": variant_id,
            "asset": str(asset.relative_to(base_dir)).replace("\\", "/"),
            "rights_evidence": str(rights.relative_to(base_dir)).replace("\\", "/"),
            "volume": round(volume, 6),
            "portrait_initial_volume": round(volume, 6),
            "duration_seconds": float(decision["duration_seconds"]),
            "post_gain_mean_dbfs": round(_mean_dbfs(asset) + gain_db, 3),
            "portrait_initial_post_gain_mean_dbfs": round(_mean_dbfs(asset) + gain_db, 3),
            "reason": "HongRun portrait motif bound to the approved semantic event",
            "motif_fingerprint_sha256": fingerprint["sha256"],
            "portrait_recipe_id": decision["recipe_id"],
            "portrait_phase": decision["phase"],
            "portrait_landing_kind": landing_kind,
            "portrait_landing_tolerance_ms": tolerance_ms,
        })
    sfx["event_decisions"] = projected
    cue_count = sum(row["decision"] == "cue" for row in projected)
    sfx["mix_audibility_check"] = {
        "status": "pending_render_measurement" if cue_count else "not_applicable",
        "reason": "measure from the exact mixed review bytes" if cue_count else "all portrait events are intentionally silent",
    }
    provenance = result.setdefault("provenance", {})
    if not isinstance(provenance, dict):
        raise PortraitSonicError("audio plan provenance must be a mapping")
    provenance["portrait_sonic_plan"] = {
        "sha256": _stable_hash(plan),
        "decision_coverage": len(projected) / max(len(contracts), 1),
        "actual_mix_owner": "existing_ffmpeg_audio_production_and_qa",
        "brand_taste_approved": False,
    }
    return result


def validate_portrait_sonic_projection(
    plan: Any, audio_plan: Any, *, base_dir: Path,
    motion_contracts_path: Path, storyboard: Any,
) -> list[str]:
    """Verify that an audio-plan is the exact current projection of the sonic contract."""
    errors = validate_portrait_contract_schema("portrait-sonic-plan", plan)
    if errors:
        return errors
    if not isinstance(plan, Mapping) or not isinstance(audio_plan, Mapping):
        return ["portrait sonic plan and audio plan must be mappings"]
    motion_contracts_path = motion_contracts_path.resolve()
    if not motion_contracts_path.is_file():
        return [f"portrait sonic motion contracts are missing: {motion_contracts_path}"]
    if plan.get("motion_contract_sha256") != sha256_file(motion_contracts_path):
        errors.append("portrait sonic motion contract hash is stale")
    profile_errors = _file_ref_errors(plan.get("brand_profile"), "portrait sonic brand profile")
    errors.extend(profile_errors)
    library_ref = plan.get("sonic_library")
    errors.extend(_file_ref_errors(library_ref, "portrait sonic library"))
    library: Mapping[str, Any] = {}
    library_path = (
        Path(str(library_ref.get("path") or "")).resolve()
        if isinstance(library_ref, Mapping) else Path()
    )
    if library_path.is_file():
        try:
            loaded_library = read_json(library_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"portrait sonic library is unreadable: {error}")
        else:
            library_errors = validate_portrait_sonic_library(loaded_library, library_path)
            errors.extend(library_errors)
            if isinstance(loaded_library, Mapping):
                library = loaded_library
                registry_ref = library.get("registry")
                registry_path = (
                    Path(str(registry_ref.get("path") or "")).resolve()
                    if isinstance(registry_ref, Mapping) else Path()
                )
                if registry_path != DEFAULT_PORTRAIT_SONIC_REGISTRY.resolve():
                    errors.append("portrait sonic library is not bound to the frozen default registry")
    library_families = {
        str(row.get("family_id") or ""): row
        for row in (library.get("families") or []) if isinstance(row, Mapping)
    }
    try:
        motion_bundle = read_json(motion_contracts_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [*errors, f"portrait sonic motion contracts are unreadable: {error}"]
    contracts = {
        str(row.get("semantic_event_id")): row
        for row in (motion_bundle.get("contracts") or []) if isinstance(row, Mapping)
    } if isinstance(motion_bundle, Mapping) else {}
    if not isinstance(storyboard, Mapping) or not isinstance(storyboard.get("events"), list):
        return [*errors, "portrait sonic storyboard must be a mapping with events"]
    renderer_pairs: list[tuple[str, str]] = []
    for index, row in enumerate(storyboard["events"]):
        if not isinstance(row, Mapping):
            errors.append(f"portrait sonic storyboard events[{index}] must be a mapping")
            continue
        if row.get("treatment") == "quiet_source":
            continue
        semantic_id = str(row.get("semantic_event_id") or row.get("id") or "")
        renderer_id = str(row.get("id") or "")
        if not semantic_id or not renderer_id:
            errors.append("portrait sonic storyboard IDs must be non-empty")
            continue
        renderer_pairs.append((semantic_id, renderer_id))
    if [semantic_id for semantic_id, _ in renderer_pairs] != list(contracts):
        errors.append("portrait sonic storyboard event set/order differs from motion contracts")
    if len({semantic_id for semantic_id, _ in renderer_pairs}) != len(renderer_pairs):
        errors.append("portrait sonic storyboard semantic IDs must be unique")
    if len({renderer_id for _, renderer_id in renderer_pairs}) != len(renderer_pairs):
        errors.append("portrait sonic storyboard renderer IDs must be unique")
    renderer_by_semantic = dict(renderer_pairs)
    plan_rows = [row for row in plan.get("decisions") or [] if isinstance(row, Mapping)]
    if [str(row.get("event_id") or "") for row in plan_rows] != list(contracts):
        errors.append("portrait sonic decision set/order differs from motion contracts")
    audio_rows = [
        row for row in ((audio_plan.get("motion_sfx") or {}).get("event_decisions") or [])
        if isinstance(row, Mapping)
    ] if isinstance(audio_plan.get("motion_sfx"), Mapping) else []
    audio_by_semantic = {
        str(row.get("semantic_event_id") or row.get("event_id") or ""): row
        for row in audio_rows
    }
    if list(audio_by_semantic) != list(contracts):
        errors.append("portrait sonic audio projection does not exactly cover motion contracts")
    provenance = audio_plan.get("provenance")
    projection = provenance.get("portrait_sonic_plan") if isinstance(provenance, Mapping) else None
    if not isinstance(projection, Mapping) or projection.get("sha256") != _stable_hash(plan):
        errors.append("portrait sonic audio projection hash is missing or stale")
    elif projection.get("decision_coverage") != 1.0:
        errors.append("portrait sonic audio projection decision coverage must be 1.0")
    base_dir = base_dir.resolve()
    try:
        authorized_root = authorized_portrait_sfx_root(base_dir)
    except PortraitSonicError as error:
        errors.append(str(error))
        authorized_root = base_dir / "__invalid_sfx_root__"
    for planned in plan_rows:
        semantic_event_id = str(planned.get("event_id") or "")
        contract = contracts.get(semantic_event_id)
        projected = audio_by_semantic.get(semantic_event_id)
        if not isinstance(contract, Mapping) or not isinstance(projected, Mapping):
            continue
        renderer_id = renderer_by_semantic.get(semantic_event_id, semantic_event_id)
        if projected.get("event_id") != renderer_id:
            errors.append(f"portrait sonic renderer event ID is stale: {semantic_event_id}")
        expected_semantic_id = semantic_event_id if renderer_id != semantic_event_id else None
        if projected.get("semantic_event_id") != expected_semantic_id:
            errors.append(f"portrait sonic semantic event projection is stale: {semantic_event_id}")
        if projected.get("decision") != planned.get("decision"):
            errors.append(f"portrait sonic decision projection is stale: {semantic_event_id}")
            continue
        if projected.get("portrait_recipe_id") != planned.get("recipe_id"):
            errors.append(f"portrait sonic recipe projection is stale: {semantic_event_id}")
        if planned.get("decision") == "intentionally_silent":
            if projected.get("reason") != planned.get("reason"):
                errors.append(f"portrait sonic silence reason is stale: {semantic_event_id}")
            continue
        expected_family_id = RECIPE_FAMILY.get(str(planned.get("recipe_id") or ""))
        library_family = library_families.get(str(expected_family_id or ""))
        library_variants = {
            str(row.get("variant_id") or ""): row
            for row in ((library_family or {}).get("variants") or [])
            if isinstance(row, Mapping)
        }
        library_variant = library_variants.get(str(planned.get("variant_id") or ""))
        if not isinstance(library_variant, Mapping):
            errors.append(f"portrait sonic library variant is missing: {semantic_event_id}")
        else:
            library_projection = {
                "motif_family_id": expected_family_id,
                "asset": library_variant.get("asset"),
                "rights": library_variant.get("rights"),
                "pcm_fingerprint": library_variant.get("pcm_fingerprint"),
                "duration_seconds": library_variant.get("duration_seconds"),
                "phase": (library_family or {}).get("phase"),
            }
            for field, expected_value in library_projection.items():
                if planned.get(field) != expected_value:
                    errors.append(
                        f"portrait sonic library {field} binding is stale: {semantic_event_id}"
                    )
        expected, landing_kind, tolerance_ms = _expected_landing(contract)
        if expected is None:
            errors.append(f"portrait sonic {landing_kind} landing evidence is unavailable: {semantic_event_id}")
            continue
        try:
            observed = float(projected.get("start"))
            planned_landing = float(planned.get("landing_seconds"))
        except (TypeError, ValueError):
            errors.append(f"portrait sonic landing is malformed: {semantic_event_id}")
            continue
        delta_ms = (observed - expected) * 1000.0
        landing_valid = (
            -tolerance_ms <= delta_ms <= 0.0
            if landing_kind == "chapter" else abs(delta_ms) <= tolerance_ms
        )
        if observed != planned_landing or not landing_valid:
            errors.append(f"portrait sonic {landing_kind} landing is stale: {semantic_event_id}")
        expected_fields = {
            "family": planned.get("motif_family_id"),
            "variant_id": planned.get("variant_id"),
            "portrait_phase": planned.get("phase"),
            "portrait_landing_kind": landing_kind,
            "portrait_landing_tolerance_ms": tolerance_ms,
            "motif_fingerprint_sha256": planned.get("pcm_fingerprint"),
        }
        for field, expected_value in expected_fields.items():
            if projected.get(field) != expected_value:
                errors.append(f"portrait sonic {field} is stale: {semantic_event_id}")
        variant_id = str(planned.get("variant_id") or "")
        planned_asset = planned.get("asset") if isinstance(planned.get("asset"), Mapping) else {}
        planned_rights = planned.get("rights") if isinstance(planned.get("rights"), Mapping) else {}
        expected_asset = (
            Path("assets") / "sfx" / "portrait-brand-v2"
            / f"{variant_id}{Path(str(planned_asset.get('path') or '')).suffix}"
        ).as_posix()
        expected_rights = (
            Path("assets") / "sfx" / "portrait-brand-v2" / "rights"
            / f"{variant_id}{Path(str(planned_rights.get('path') or '')).suffix}"
        ).as_posix()
        exact_projection = {
            "asset": expected_asset,
            "rights_evidence": expected_rights,
            "duration_seconds": float(planned.get("duration_seconds")),
            "reason": "HongRun portrait motif bound to the approved semantic event",
        }
        for field, expected_value in exact_projection.items():
            if projected.get(field) != expected_value:
                errors.append(f"portrait sonic {field} projection is stale: {semantic_event_id}")
        asset = (base_dir / str(projected.get("asset") or "")).resolve()
        rights = (base_dir / str(projected.get("rights_evidence") or "")).resolve()
        if not asset.is_relative_to(authorized_root) or not asset.is_file():
            errors.append(f"portrait sonic projected asset is missing or unauthorized: {semantic_event_id}")
        elif asset.stat().st_size == 0 or sha256_file(asset) != (planned.get("asset") or {}).get("sha256"):
            errors.append(f"portrait sonic projected asset hash is stale: {semantic_event_id}")
        else:
            try:
                fingerprint = perceptual_motif_fingerprint(asset)
            except (OSError, ValueError, RuntimeError, wave.Error) as error:
                errors.append(f"portrait sonic projected asset cannot decode: {semantic_event_id}: {error}")
            else:
                if fingerprint["sha256"] != planned.get("pcm_fingerprint"):
                    errors.append(f"portrait sonic projected PCM identity is stale: {semantic_event_id}")
                expected_post_gain = round(
                    _mean_dbfs(asset) + float(planned.get("gain_db")), 3,
                )
                expected_volume = round(
                    10.0 ** (float(planned.get("gain_db")) / 20.0), 6,
                )
                if projected.get("portrait_initial_volume") != expected_volume:
                    errors.append(
                        f"portrait sonic initial volume projection is stale: {semantic_event_id}"
                    )
                if projected.get("portrait_initial_post_gain_mean_dbfs") != expected_post_gain:
                    errors.append(
                        f"portrait sonic initial post-gain projection is stale: {semantic_event_id}"
                    )
                try:
                    observed_volume = float(projected.get("volume"))
                    observed_post_gain = float(projected.get("post_gain_mean_dbfs"))
                except (TypeError, ValueError):
                    errors.append(f"portrait sonic measured gain is malformed: {semantic_event_id}")
                else:
                    exact_initial = (
                        observed_volume == expected_volume
                        and observed_post_gain == expected_post_gain
                    )
                    adjusted_post_gain = round(
                        expected_post_gain
                        + 20.0 * math.log10(max(observed_volume, 1e-9) / expected_volume),
                        1,
                    )
                    legitimate_adjustment = (
                        0.05 <= observed_volume <= expected_volume
                        and observed_volume == round(observed_volume, 3)
                        and observed_post_gain == adjusted_post_gain
                    )
                    if not (exact_initial or legitimate_adjustment):
                        errors.append(
                            f"portrait sonic adaptive gain projection is stale: {semantic_event_id}"
                        )
                if not math.isfinite(expected_post_gain):
                    errors.append(
                        f"portrait sonic post_gain_mean_dbfs projection is stale: {semantic_event_id}"
                    )
        if not rights.is_relative_to(authorized_root) or not rights.is_file():
            errors.append(f"portrait sonic projected rights are missing or unauthorized: {semantic_event_id}")
        elif sha256_file(rights) != (planned.get("rights") or {}).get("sha256"):
            errors.append(f"portrait sonic projected rights hash is stale: {semantic_event_id}")
    return errors
