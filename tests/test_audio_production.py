from __future__ import annotations

import json
import hashlib
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_production import (  # noqa: E402
    build_audio_plan,
    materialize_motion_audio_decisions,
    perceptual_motif_fingerprint,
    materialize_sample_audio_evidence,
    materialize_sample_review_mix,
    produce_audio_assets,
    resolve_bgm,
    validate_sample_audio_evidence,
    validate_sample_review_mix_receipt,
)
from motion_contracts import validate_contract_schema  # noqa: E402
from audio_qa import validate as validate_audio_plan  # noqa: E402
from director_adapters import AdapterRunner  # noqa: E402


class AudioProductionTests(unittest.TestCase):
    @staticmethod
    def _json_hash(value: object) -> str:
        return hashlib.sha256(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
    @staticmethod
    def _write_tone(path: Path, *, duration: float, frequency: float, amplitude: float) -> None:
        sample_rate = 48_000
        frames = int(duration * sample_rate)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as target:
            target.setnchannels(2)
            target.setsampwidth(2)
            target.setframerate(sample_rate)
            for index in range(frames):
                value = int(32767 * amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
                target.writeframesraw(struct.pack("<hh", value, value))

    def test_approved_local_asset_wins_without_spending_provider_quota(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bgm = root / "approved.wav"
            bgm.write_bytes(b"music")
            runner = AdapterRunner(root / "state.json")
            result = resolve_bgm({
                "enabled_by_default": True,
                "asset": str(bgm),
                "authorization": "creator-owned",
                "provider_chain": [{"name": "minimax", "enabled": True,
                                    "command": [sys.executable, "missing.py"]}],
            }, root=root, output_dir=root / "audio", runner=runner)
            self.assertEqual(result["mode"], "authorized_asset")
            self.assertEqual(result["provider"], "approved_local")
            self.assertFalse((root / "state.json").exists())

    def test_perceptual_motif_fingerprint_is_content_based_not_path_based(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first.wav"
            copy = root / "renamed.wav"
            different = root / "different.wav"
            self._write_tone(first, duration=1.0, frequency=720.0, amplitude=0.2)
            copy.write_bytes(first.read_bytes())
            self._write_tone(different, duration=1.0, frequency=900.0, amplitude=0.2)

            first_result = perceptual_motif_fingerprint(first)
            copy_result = perceptual_motif_fingerprint(copy)
            different_result = perceptual_motif_fingerprint(different)

            self.assertEqual(first_result["sha256"], copy_result["sha256"])
            self.assertNotEqual(first_result["sha256"], different_result["sha256"])
            self.assertEqual(first_result["sample_rate"], 48_000)
            self.assertGreater(first_result["duration_seconds"], 0.9)
            self.assertTrue(first_result["spectral_centroid_hz"] > 0)

    def test_provider_chain_stops_after_first_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "audio" / "first.wav"
            second = root / "audio" / "second.wav"
            create_first = (
                "from pathlib import Path; p=Path(r'%s'); p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_bytes(b'first')" % first
            )
            create_second = (
                "from pathlib import Path; p=Path(r'%s'); p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_bytes(b'second')" % second
            )
            result = resolve_bgm({
                "enabled_by_default": True,
                "provider_chain": [
                    {"name": "heygen", "enabled": True,
                     "command": [sys.executable, "-c", create_first], "output": str(first),
                     "authorization": "test"},
                    {"name": "minimax", "enabled": True,
                     "command": [sys.executable, "-c", create_second], "output": str(second),
                     "authorization": "test"},
                ],
            }, root=root, output_dir=root / "audio", runner=AdapterRunner(root / "state.json"))
            self.assertEqual(result["provider"], "heygen")
            self.assertTrue(first.is_file())
            self.assertFalse(second.exists())

    def test_audio_plan_preserves_silent_decisions_and_records_pending_mix_measurement(self) -> None:
        manifest = {"event_decisions": [
            {"event_id": "e1", "decision": "cue", "asset": "assets/e1.wav"},
            {"event_id": "e2", "decision": "intentionally_silent", "reason": "source UI click is audible"},
        ]}
        plan = build_audio_plan(
            manifest, source_audio="source.mp4",
            bgm={"mode": "disabled", "reason": "no approved asset"}, preview_volume=0.1,
        )
        self.assertEqual(plan["motion_sfx"]["event_decisions"][1]["decision"],
                         "intentionally_silent")
        self.assertEqual(plan["motion_sfx"]["mix_audibility_check"]["status"],
                         "pending_render_measurement")
        self.assertEqual(plan["background_music"]["mode"], "disabled")

    def test_enabled_bgm_without_a_working_provider_is_unavailable_not_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = resolve_bgm({
                "enabled_by_default": True,
                "provider_chain": [{"name": "minimax", "enabled": True}],
            }, root=root, output_dir=root / "audio", runner=AdapterRunner(root / "state.json"))

            self.assertEqual(result["mode"], "unavailable")
            self.assertTrue(result["reason"])
            self.assertEqual(result["attempts"][0]["status"], "unavailable")

            plan = build_audio_plan(
                {"event_decisions": []}, source_audio="source.mp4",
                bgm=result, preview_volume=0.1,
            )
            self.assertEqual(plan["background_music"]["mode"], "unavailable")
            self.assertEqual(plan["background_music"]["attempts"], result["attempts"])

    def test_audio_production_inherits_semantic_audio_decisions_by_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "render-1", "semantic_event_id": "semantic-1",
                "start": 1.0, "end": 3.0,
                "visual_structure": {"layout_archetype": "generic-mark"},
            }]}), encoding="utf-8")
            semantic = root / "semantic-brief.json"
            semantic.write_text(json.dumps({"events": [{
                "id": "semantic-1",
                "audio_decision": {"type": "cue", "family": "two-note-contrast"},
            }]}), encoding="utf-8")
            source = root / "source.wav"
            self._write_tone(source, duration=4.0, frequency=180.0, amplitude=0.04)

            produce_audio_assets(
                storyboard=storyboard,
                semantic_brief=semantic,
                project={"audio": {"sfx": {"enabled": True}, "bgm": {"enabled": False}}},
                project_root=root,
                output_dir=root / "audio",
                source_audio=source,
                runner=AdapterRunner(root / "adapter-state.json"),
            )

            plan = json.loads((root / "audio-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(
                plan["motion_sfx"]["event_decisions"][0]["family"],
                "two_note_contrast",
            )

    def test_portrait_audio_production_projects_compiler_decisions_into_existing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "render-1", "semantic_event_id": "semantic-1",
                "start": 1.0, "end": 2.5,
                "visual_structure": {"layout_archetype": "portrait-phrase"},
            }]}), encoding="utf-8")
            semantic = root / "semantic-brief.json"
            semantic_payload = {"events": [{
                "id": "semantic-1", "semantic_role": "mark",
                "output_start": 1.0, "output_end": 2.5,
                "audio_decision": {"type": "cue"},
            }]}
            semantic.write_text(json.dumps(semantic_payload), encoding="utf-8")
            profile = root / "profile.json"
            profile.write_bytes((
                ROOT / "references" / "portrait-brand-profiles"
                / "hongrun-portrait-brand-v2.0.0.json"
            ).read_bytes())
            motion = root / "portrait-motion-contracts.json"
            motion.write_text(json.dumps({"schema_version": 1, "contracts": [{
                "semantic_event_id": "semantic-1", "primary_recipe_id": "PBM-01",
                "energy_tier": "micro",
                "output_window": {"start_seconds": 1.0, "end_seconds": 2.5},
                "input_hashes": {"semantic_brief": self._json_hash(semantic_payload)},
            }]}), encoding="utf-8")
            source = root / "source.wav"
            self._write_tone(source, duration=4.0, frequency=180.0, amplitude=0.04)

            outputs = produce_audio_assets(
                storyboard=storyboard,
                semantic_brief=semantic,
                project={"audio": {"sfx": {"enabled": True}, "bgm": {"enabled": False}}},
                project_root=root,
                output_dir=root / "audio",
                source_audio=source,
                runner=AdapterRunner(root / "adapter-state.json"),
                portrait_motion_contracts=motion,
                portrait_profile=profile,
            )

            plan = json.loads((root / "audio-plan.json").read_text(encoding="utf-8"))
            decision = plan["motion_sfx"]["event_decisions"][0]
            self.assertEqual(decision["event_id"], "render-1")
            self.assertEqual(decision["semantic_event_id"], "semantic-1")
            self.assertEqual(decision["family"], "PBM-S01")
            self.assertTrue((root / decision["asset"]).is_file())
            self.assertEqual(
                plan["provenance"]["portrait_sonic_plan"]["actual_mix_owner"],
                "existing_ffmpeg_audio_production_and_qa",
            )
            sonic_plan = motion.parent / "portrait-sonic-plan.json"
            sonic_report = motion.parent / "portrait-sonic-compile-report.json"
            self.assertIn(sonic_plan, outputs)
            self.assertIn(sonic_report, outputs)
            manifest = json.loads((root / "audio-sfx-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"][0]["event_id"], "render-1")
            self.assertEqual(manifest["assets"][0]["license"], "project-owned original synthesis")

    def test_portrait_audio_production_respects_explicit_sfx_disable_per_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "render-1", "semantic_event_id": "semantic-1",
                "start": 1.0, "end": 2.5,
                "visual_structure": {"layout_archetype": "portrait-phrase"},
            }]}), encoding="utf-8")
            semantic = root / "semantic-brief.json"
            semantic_payload = {"events": [{
                "id": "semantic-1", "semantic_role": "mark",
                "output_start": 1.0, "output_end": 2.5,
                "audio_decision": {"type": "cue"},
            }]}
            semantic.write_text(json.dumps(semantic_payload), encoding="utf-8")
            profile = root / "profile.json"
            profile.write_bytes((
                ROOT / "references" / "portrait-brand-profiles"
                / "hongrun-portrait-brand-v2.0.0.json"
            ).read_bytes())
            motion = root / "portrait-motion-contracts.json"
            motion.write_text(json.dumps({"schema_version": 1, "contracts": [{
                "semantic_event_id": "semantic-1", "primary_recipe_id": "PBM-01",
                "energy_tier": "micro",
                "output_window": {"start_seconds": 1.0, "end_seconds": 2.5},
                "input_hashes": {"semantic_brief": self._json_hash(semantic_payload)},
            }]}), encoding="utf-8")
            source = root / "source.wav"
            self._write_tone(source, duration=4.0, frequency=180.0, amplitude=0.04)

            produce_audio_assets(
                storyboard=storyboard,
                semantic_brief=semantic,
                project={"audio": {"sfx": {"enabled": False}, "bgm": {"enabled": False}}},
                project_root=root,
                output_dir=root / "audio",
                source_audio=source,
                runner=AdapterRunner(root / "adapter-state.json"),
                portrait_motion_contracts=motion,
                portrait_profile=profile,
            )

            plan = json.loads((root / "audio-plan.json").read_text(encoding="utf-8"))
            decision = plan["motion_sfx"]["event_decisions"][0]
            self.assertEqual(decision["event_id"], "render-1")
            self.assertEqual(decision["semantic_event_id"], "semantic-1")
            self.assertEqual(decision["decision"], "intentionally_silent")
            self.assertIn("explicitly disabled", decision["reason"])
            self.assertEqual(
                plan["motion_sfx"]["mix_audibility_check"]["status"],
                "not_applicable",
            )
            manifest = json.loads((root / "audio-sfx-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"], [])

    def test_portrait_motif_survives_real_short_sample_mix_and_receipt_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "portrait-sample.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=0x172033:s=320x568:r=25:d=4",
                "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=48000:duration=4",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(candidate),
            ], check=True)
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "render-1", "semantic_event_id": "semantic-1",
                "start": 1.0, "end": 2.5,
                "visual_structure": {"layout_archetype": "portrait-phrase"},
            }]}), encoding="utf-8")
            semantic = root / "semantic-brief.json"
            semantic_payload = {"events": [{
                "id": "semantic-1", "semantic_role": "mark",
                "output_start": 1.0, "output_end": 2.5,
                "audio_decision": {"type": "cue"},
            }]}
            semantic.write_text(json.dumps(semantic_payload), encoding="utf-8")
            profile = root / "profile.json"
            profile.write_bytes((
                ROOT / "references" / "portrait-brand-profiles"
                / "hongrun-portrait-brand-v2.0.0.json"
            ).read_bytes())
            motion = root / "portrait-motion-contracts.json"
            motion.write_text(json.dumps({"schema_version": 1, "contracts": [{
                "semantic_event_id": "semantic-1", "primary_recipe_id": "PBM-01",
                "energy_tier": "micro",
                "output_window": {"start_seconds": 1.0, "end_seconds": 2.5},
                "input_hashes": {"semantic_brief": self._json_hash(semantic_payload)},
            }]}), encoding="utf-8")

            produce_audio_assets(
                storyboard=storyboard,
                semantic_brief=semantic,
                project={"audio": {"sfx": {"enabled": True}, "bgm": {"enabled": False}}},
                project_root=root,
                output_dir=root / "audio",
                source_audio=candidate,
                runner=AdapterRunner(root / "adapter-state.json"),
                portrait_motion_contracts=motion,
                portrait_profile=profile,
            )
            audio_plan = root / "audio-plan.json"
            review_audio = root / "sample-qa" / "review-audio"
            artifacts = materialize_sample_audio_evidence(
                storyboard=storyboard,
                audio_plan=audio_plan,
                candidate_media=candidate,
                output_dir=review_audio,
            )
            evidence = root / "sample-qa" / "mix-audibility.json"
            measured = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(measured["status"], "pass")
            self.assertEqual(measured["events"][0]["event_id"], "render-1")
            self.assertEqual(measured["events"][0]["semantic_event_id"], "semantic-1")
            self.assertLessEqual(measured["events"][0]["perceptual"]["onset_error_ms"], 80.0)
            self.assertIn(evidence.resolve(), artifacts)
            evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
            self.assertEqual(validate_sample_audio_evidence(
                audio_plan=audio_plan, storyboard=storyboard,
                candidate_media=candidate, evidence_path=evidence,
                output_dir=review_audio, expected_evidence_path=evidence,
                declared_evidence_sha256=evidence_hash,
            ), [])

            measured["events"][0]["residual_mean_dbfs"] += 12.0
            evidence.write_text(json.dumps(measured), encoding="utf-8")
            forged_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
            self.assertTrue(any("remeasured" in row for row in validate_sample_audio_evidence(
                audio_plan=audio_plan, storyboard=storyboard,
                candidate_media=candidate, evidence_path=evidence,
                output_dir=review_audio, expected_evidence_path=evidence,
                declared_evidence_sha256=forged_hash,
            )))
            materialize_sample_audio_evidence(
                storyboard=storyboard, audio_plan=audio_plan,
                candidate_media=candidate, output_dir=review_audio,
            )

            for value in (float("nan"), float("inf"), float("-inf")):
                forged = json.loads(evidence.read_text(encoding="utf-8"))
                forged["events"][0]["residual_mean_dbfs"] = value
                forged["events"][0]["perceptual"]["dialogue_window_lufs"] = value
                forged["events"][0]["perceptual"]["onset_error_ms"] = value
                evidence.write_text(json.dumps(forged), encoding="utf-8")
                forged_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
                with self.subTest(non_finite=value):
                    errors = validate_sample_audio_evidence(
                        audio_plan=audio_plan, storyboard=storyboard,
                        candidate_media=candidate, evidence_path=evidence,
                        output_dir=review_audio, expected_evidence_path=evidence,
                        declared_evidence_sha256=forged_hash,
                    )
                    self.assertTrue(any("non-finite" in row for row in errors), errors)
                materialize_sample_audio_evidence(
                    storyboard=storyboard, audio_plan=audio_plan,
                    candidate_media=candidate, output_dir=review_audio,
                )

            mixed = root / "portrait-sample-with-sfx.mp4"
            receipt = root / "sample-review-mix.json"
            materialize_sample_review_mix(
                candidate_media=candidate,
                audio_plan=audio_plan,
                output=mixed,
                receipt_path=receipt,
            )
            self.assertEqual(
                validate_sample_review_mix_receipt(
                    json.loads(receipt.read_text(encoding="utf-8")),
                    candidate_media=candidate,
                    audio_plan=audio_plan,
                    output=mixed,
                ),
                [],
            )

    def test_sample_audio_evidence_rejects_self_signed_non_media_bytes(self) -> None:
        from audio_production import _decision_binding

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.mp4"
            candidate.write_bytes(b"not media")
            cue = root / "assets" / "sfx" / "cue.wav"
            cue.parent.mkdir(parents=True)
            cue.write_bytes(b"not audio")
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "event-1", "semantic_event_id": "semantic-1",
                "start": 0.0, "end": 1.0, "treatment": "portrait",
            }]}), encoding="utf-8")
            audio_plan = root / "audio-plan.json"
            decision = {
                "event_id": "event-1", "decision": "cue", "family": "PBM-S01",
                "asset": "assets/sfx/cue.wav", "start": 0.0,
                "duration_seconds": 1.0, "volume": 0.1,
                "post_gain_mean_dbfs": -30.0,
            }
            audio_plan.write_text(json.dumps({
                "motion_sfx": {"event_decisions": [decision]},
            }), encoding="utf-8")
            review_audio = root / "sample-qa" / "review-audio"
            review_audio.mkdir(parents=True)
            off = review_audio / "semantic-1-sfx-off.wav"
            on = review_audio / "semantic-1-sfx-on.wav"
            off.write_bytes(b"same junk")
            on.write_bytes(b"same junk")
            artifact = lambda path: {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            evidence = root / "sample-qa" / "mix-audibility.json"
            evidence.write_text(json.dumps({
                "schema_version": 1, "status": "pass",
                "storyboard": artifact(storyboard),
                "candidate_media": artifact(candidate),
                "events": [{
                    "event_id": "event-1", "semantic_event_id": "semantic-1",
                    "decision": "cue", "status": "pass",
                    "decision_binding": _decision_binding(decision, audio_plan),
                    "excerpt_start_seconds": 0.0,
                    "sfx_off": artifact(off), "sfx_on": artifact(on),
                    "off_mean_dbfs": -20.0, "on_mean_dbfs": -20.0,
                    "residual_mean_dbfs": 0.0, "on_peak_dbfs": -1.0,
                    "mix_gain_delta_db": 0.0,
                    "perceptual": {
                        "motif_fingerprint": {"sha256": "0" * 64},
                        "dialogue_window_lufs": -20.0, "cue_window_lufs": -30.0,
                        "dialogue_cue_delta_lu": 10.0, "onset_error_ms": 0.0,
                        "audibility_status": "audible_without_masking",
                    },
                }],
            }), encoding="utf-8")

            errors = validate_sample_audio_evidence(
                audio_plan=audio_plan, storyboard=storyboard,
                candidate_media=candidate, evidence_path=evidence,
                output_dir=review_audio, expected_evidence_path=evidence,
                declared_evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
            )
            self.assertTrue(any("decodable" in row or "audio evidence" in row for row in errors), errors)

    def test_materializes_hash_bound_sfx_auditions_and_real_mix_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "sample-preview.wav"
            cue = root / "assets" / "sfx" / "cue.wav"
            self._write_tone(candidate, duration=4.0, frequency=180.0, amplitude=0.04)
            self._write_tone(cue, duration=1.0, frequency=720.0, amplitude=0.60)
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "render-event-1",
                "semantic_event_id": "semantic-event-1",
                "start": 0.5,
                "end": 3.5,
                "treatment": "comparison_panel",
            }]}), encoding="utf-8")
            audio_plan = root / "audio-plan.json"
            audio_plan.write_text(json.dumps({
                "schema_version": 3,
                "speech_track": {"source": str(candidate), "dominant": True, "immutable": True},
                "motion_sfx": {
                    "event_decisions": [{
                        "event_id": "render-event-1",
                        "decision": "cue",
                        "start": 1.25,
                        "family": "comparison_panel",
                        "asset": "assets/sfx/cue.wav",
                        "volume": 0.40,
                        "duration_seconds": 1.0,
                        "post_gain_mean_dbfs": -29.0,
                    }],
                    "mix_audibility_check": {"status": "pending_render_measurement"},
                },
                "background_music": {
                    "mode": "disabled",
                    "enabled": False,
                    "reason": "test explicitly disables BGM",
                    "explicitly_disabled": True,
                },
                "provenance": {"source_audio": str(candidate)},
            }), encoding="utf-8")

            artifacts = materialize_sample_audio_evidence(
                storyboard=storyboard,
                audio_plan=audio_plan,
                candidate_media=candidate,
                output_dir=root / "sample-qa" / "review-audio",
            )

            off = root / "sample-qa" / "review-audio" / "semantic-event-1-sfx-off.wav"
            on = root / "sample-qa" / "review-audio" / "semantic-event-1-sfx-on.wav"
            evidence = root / "sample-qa" / "mix-audibility.json"
            self.assertTrue(off.is_file())
            self.assertTrue(on.is_file())
            self.assertTrue(evidence.is_file())
            self.assertNotEqual(off.read_bytes(), on.read_bytes())
            self.assertEqual(set(artifacts), {off.resolve(), on.resolve(), evidence.resolve(), audio_plan.resolve()})
            measurements = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(measurements["status"], "pass")
            self.assertEqual(measurements["events"][0]["semantic_event_id"], "semantic-event-1")
            self.assertGreater(measurements["events"][0]["residual_mean_dbfs"], -60.0)
            perceptual = measurements["events"][0]["perceptual"]
            self.assertEqual(perceptual["motif_fingerprint"]["method"], "pcm-perceptual-v1")
            self.assertLessEqual(perceptual["onset_error_ms"], 80.0)
            self.assertIn(perceptual["audibility_status"], {
                "audible_without_masking", "masked", "dialogue_harmed",
            })
            self.assertIsInstance(perceptual["dialogue_window_lufs"], float)
            self.assertIsInstance(perceptual["cue_window_lufs"], float)
            self.assertEqual(perceptual["measurement_method"], "ffmpeg-loudnorm-window-plus-fullband-identity-v1")
            plan = json.loads(audio_plan.read_text(encoding="utf-8"))
            self.assertEqual(plan["motion_sfx"]["mix_audibility_check"]["status"], "pass")
            self.assertEqual(
                Path(plan["motion_sfx"]["mix_audibility_check"]["evidence"]),
                evidence.resolve(),
            )
            self.assertLess(plan["motion_sfx"]["event_decisions"][0]["volume"], 0.40)
            self.assertEqual(validate_audio_plan(
                plan,
                json.loads(storyboard.read_text(encoding="utf-8")),
                {"audio": {"sfx": {"perceptual": {
                    "enabled": True,
                    "minimum_audible_ratio": 0.35,
                    "maximum_audible_ratio": 0.65,
                    "maximum_onset_error_ms": 80.0,
                }}, "bgm": {"enabled": False}}},
                base_dir=root,
            ), [])

    def test_materializes_frozen_motion_audio_contracts_from_real_mix_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "sample.mp4"
            cue = root / "assets" / "sfx" / "cue.wav"
            self._write_tone(cue, duration=1.0, frequency=720.0, amplitude=0.25)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=3",
                "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=48000:duration=3",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(candidate),
            ], check=True)
            contract = root / "motion-design-contract.json"
            contract.write_text(json.dumps({"opportunities": [{
                "semantic_event_id": "e1", "decision": "render", "semantic_role": "mark",
                "audio_decision_id": "audio-e1", "output_window": {"start_seconds": .5, "end_seconds": 2.0},
            }]}), encoding="utf-8")
            plan = root / "audio-plan.json"
            plan.write_text(json.dumps({"motion_sfx": {"event_decisions": [{
                "event_id": "render-e1", "semantic_event_id": "e1",
                "decision": "cue", "asset": "assets/sfx/cue.wav",
                "family": "mark", "start": .8, "duration_seconds": 1.0,
                "volume": .05, "reason": "semantic mark",
            }]}}), encoding="utf-8")
            evidence = root / "mix-audibility.json"
            off = root / "off.wav"; on = root / "on.wav"
            self._write_tone(off, duration=3.0, frequency=180.0, amplitude=0.1)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(off), "-i", str(cue),
                "-filter_complex", "[1:a]volume=0.05,adelay=800:all=1[cue];[0:a][cue]amix=inputs=2:duration=first:normalize=0[out]",
                "-map", "[out]", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(on),
            ], check=True)
            decision = json.loads(plan.read_text(encoding="utf-8"))["motion_sfx"]["event_decisions"][0]
            from audio_production import _decision_binding
            measured = __import__("audio_production")._perceptual_mix_metrics(
                off_path=off, on_path=on, cue_path=cue, planned_delay_seconds=0.8,
            )
            final_mix = root / "final-mix.wav"
            final_mix.write_bytes(on.read_bytes())
            evidence.write_text(json.dumps({
                "candidate_media": {"path": str(final_mix.resolve()), "sha256": __import__("hashlib").sha256(final_mix.read_bytes()).hexdigest()},
                "status": "pass", "events": [{
                "event_id": "render-e1", "decision": "cue", "status": "pass",
                "decision_binding": _decision_binding(decision, plan),
                "sfx_off": {"path": str(off.resolve()), "sha256": __import__("hashlib").sha256(off.read_bytes()).hexdigest()},
                "sfx_on": {"path": str(on.resolve()), "sha256": __import__("hashlib").sha256(on.read_bytes()).hexdigest()},
                "excerpt_start_seconds": 0.0,
                "perceptual": measured,
            }]}), encoding="utf-8")
            license_receipt = root / "audio-sfx-manifest.json"
            license_receipt.write_text(json.dumps({"assets": [{
                "event_id": "render-e1", "semantic_event_id": "e1",
                "frozen_path": str(cue.resolve()),
                "sha256": __import__("hashlib").sha256(cue.read_bytes()).hexdigest(),
                "license": "project-owned generated asset",
            }]}), encoding="utf-8")

            outputs = materialize_motion_audio_decisions(
                motion_design_contract=contract, audio_plan=plan, source_audio=candidate,
                final_mix=final_mix, perceptual_evidence=evidence,
                license_evidence=license_receipt, audio_policy={"maximum_onset_error_ms": 80},
                output_dir=root / "motion-audio-decisions",
            )

            self.assertEqual(len(outputs), 2)
            payload = json.loads((root / "motion-audio-decisions" / "audio-e1.json").read_text(encoding="utf-8"))
            self.assertEqual(validate_contract_schema("motion-audio-decision", payload), [])
            self.assertEqual(payload["status"], "mixed_and_validated")
            self.assertEqual(payload["mix_evidence"]["final_mix_sha256"], __import__("hashlib").sha256(final_mix.read_bytes()).hexdigest())

    def test_materializes_hash_bound_full_sample_review_mix_with_planned_sfx(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "sample-preview.mp4"
            cue = root / "assets" / "sfx" / "cue.wav"
            self._write_tone(cue, duration=1.0, frequency=720.0, amplitude=0.35)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=3",
                "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=48000:duration=3",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(candidate),
            ], check=True)
            plan_path = root / "audio-plan.json"
            plan_path.write_text(json.dumps({
                "schema_version": 3,
                "motion_sfx": {
                    "event_decisions": [{
                        "event_id": "e1", "decision": "cue", "asset": "assets/sfx/cue.wav",
                        "start": 0.8, "duration_seconds": 1.0, "volume": 0.25,
                    }],
                    "mix_audibility_check": {"status": "pass"},
                },
                "background_music": {"mode": "disabled", "enabled": False},
            }), encoding="utf-8")
            output = root / "sample-preview-with-sfx.mp4"
            receipt_path = root / "sample-review-mix.json"

            receipt = materialize_sample_review_mix(
                candidate_media=candidate,
                audio_plan=plan_path,
                output=output,
                receipt_path=receipt_path,
            )

            self.assertTrue(output.is_file())
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(receipt["status"], "pass")
            self.assertEqual(receipt["cue_count"], 1)
            self.assertEqual(
                validate_sample_review_mix_receipt(
                    receipt, candidate_media=candidate, audio_plan=plan_path, output=output,
                ),
                [],
            )
            self.assertNotEqual(candidate.read_bytes(), output.read_bytes())

            cue.write_bytes(cue.read_bytes() + b"tampered")
            errors = validate_sample_review_mix_receipt(
                receipt, candidate_media=candidate, audio_plan=plan_path, output=output,
            )
            self.assertTrue(any("cue asset hash is stale" in error for error in errors), errors)

    def test_sample_review_mix_rejects_aliased_wrong_cues_even_when_residual_is_audible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.mp4"
            authorized = root / "assets" / "sfx" / "authorized.wav"
            self._write_tone(authorized, duration=1.0, frequency=720.0, amplitude=0.35)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=3",
                "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=48000:duration=3",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(candidate),
            ], check=True)
            plan = root / "audio-plan.json"
            plan.write_text(json.dumps({"motion_sfx": {"event_decisions": [{
                "event_id": "e1", "decision": "cue", "asset": "assets/sfx/authorized.wav",
                "start": 0.8, "duration_seconds": 1.0, "volume": 0.25,
            }]}}), encoding="utf-8")
            for frequency in (280.0, 1720.0, 5280.0):
                wrong = root / f"wrong-{int(frequency)}.wav"
                output = root / f"wrong-mix-{int(frequency)}.mp4"
                self._write_tone(wrong, duration=1.0, frequency=frequency, amplitude=0.35)
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(candidate), "-i", str(wrong), "-filter_complex",
                    "[1:a]volume=0.25,adelay=800:all=1[cue];"
                    "[0:a][cue]amix=inputs=2:duration=first:normalize=0[aout]",
                    "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
                    str(output),
                ], check=True)
                receipt = {
                    "schema_version": 1, "status": "pass",
                    "mode": "planned_sfx_over_hyperframes_candidate",
                    "candidate_input": {"path": str(candidate), "sha256": self._sha(candidate)},
                    "audio_plan": {"path": str(plan), "sha256": self._sha(plan)},
                    "output": {"path": str(output), "sha256": self._sha(output)},
                    "cue_count": 1,
                    "cue_assets": [{"event_id": "e1", "path": str(authorized),
                                    "sha256": self._sha(authorized)}],
                    "argv": ["ffmpeg", "-filter_complex", "amix=inputs=2", str(output)],
                    "full_decode": True,
                }

                errors = validate_sample_review_mix_receipt(
                    receipt, candidate_media=candidate, audio_plan=plan, output=output,
                )

                self.assertTrue(
                    any("authorized cue identity" in error for error in errors),
                    (frequency, errors),
                )

    def test_sample_review_mix_receipt_rejects_wrong_cue_binding_and_malformed_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.mp4"
            output = root / "mixed.mp4"
            cue = root / "cue.wav"
            other = root / "other.wav"
            for path, payload in ((candidate, b"candidate"), (output, b"mixed"),
                                  (cue, b"cue"), (other, b"other")):
                path.write_bytes(payload)
            plan_path = root / "audio-plan.json"
            plan_path.write_text(json.dumps({
                "motion_sfx": {"event_decisions": [{
                    "event_id": "e1", "decision": "cue", "asset": str(cue),
                }]},
            }), encoding="utf-8")
            base = {
                "schema_version": 1, "status": "pass",
                "mode": "planned_sfx_over_hyperframes_candidate",
                "candidate_input": {"path": str(candidate), "sha256": self._sha(candidate)},
                "audio_plan": {"path": str(plan_path), "sha256": self._sha(plan_path)},
                "output": {"path": str(output), "sha256": self._sha(output)},
                "cue_count": 1,
                "cue_assets": [{
                    "event_id": "e1", "path": str(other), "sha256": self._sha(other),
                }],
                "argv": ["ffmpeg", "-filter_complex", "amix=inputs=2", str(output)],
                "full_decode": True,
            }

            errors = validate_sample_review_mix_receipt(
                base, candidate_media=candidate, audio_plan=plan_path, output=output,
            )
            self.assertTrue(any("does not match the audio plan" in error for error in errors), errors)

            base["cue_count"] = "not-a-number"
            errors = validate_sample_review_mix_receipt(
                base, candidate_media=candidate, audio_plan=plan_path, output=output,
            )
            self.assertTrue(any("cue_count is invalid" in error for error in errors), errors)

    def test_sample_review_mix_rejects_cue_outside_authorized_asset_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.mp4"
            candidate.write_bytes(b"candidate")
            outside = root / "private.wav"
            outside.write_bytes(b"private")
            plan_dir = root / "project"
            plan_dir.mkdir()
            plan = plan_dir / "audio-plan.json"
            plan.write_text(json.dumps({
                "motion_sfx": {"event_decisions": [{
                    "event_id": "e1", "decision": "cue",
                    "asset": "../private.wav", "start": 0.1,
                    "duration_seconds": 1.0, "volume": 0.2,
                }]},
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "authorized SFX root"):
                materialize_sample_review_mix(
                    candidate_media=candidate, audio_plan=plan,
                    output=root / "mixed.mp4", receipt_path=root / "receipt.json",
                )

    def test_audio_audition_rejects_cue_outside_authorized_asset_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.wav"
            outside = root / "private.wav"
            self._write_tone(candidate, duration=3.0, frequency=180.0, amplitude=0.04)
            self._write_tone(outside, duration=1.0, frequency=720.0, amplitude=0.3)
            project = root / "project"
            project.mkdir()
            storyboard = project / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "e1", "semantic_event_id": "semantic-1",
                "start": 0.5, "end": 2.5, "treatment": "structure",
            }]}), encoding="utf-8")
            plan = project / "audio-plan.json"
            plan.write_text(json.dumps({
                "motion_sfx": {"event_decisions": [{
                    "event_id": "e1", "decision": "cue", "asset": "../private.wav",
                    "start": 0.8, "duration_seconds": 1.0, "volume": 0.2,
                }]},
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "authorized SFX root"):
                materialize_sample_audio_evidence(
                    storyboard=storyboard, audio_plan=plan, candidate_media=candidate,
                    output_dir=root / "review-audio",
                )

    def test_receipt_validator_fails_closed_for_malformed_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.mp4"
            output = root / "output.mp4"
            plan = root / "audio-plan.json"
            for path in (candidate, output):
                path.write_bytes(b"not-media")
            plan.write_text(json.dumps({"motion_sfx": {"event_decisions": []}}), encoding="utf-8")
            errors = validate_sample_review_mix_receipt(
                {"schema_version": 1, "status": "pass",
                 "mode": "planned_sfx_over_hyperframes_candidate",
                 "candidate_input": "bad", "audio_plan": [], "output": None,
                 "cue_count": 0, "cue_assets": [], "argv": [], "full_decode": True},
                candidate_media=candidate, audio_plan=plan, output=output,
            )
            self.assertTrue(errors)

            for malformed in ([], "bad", None):
                errors = validate_sample_review_mix_receipt(
                    malformed, candidate_media=candidate, audio_plan=plan, output=output,
                )
                self.assertTrue(errors)

    def test_semantic_id_with_colon_uses_safe_audition_filename(self) -> None:
        from audio_production import _event_stem

        stem = _event_stem("chapter:1")

        self.assertNotIn(":", stem)
        self.assertEqual(stem, _event_stem("chapter:1"))
        self.assertNotEqual(stem, _event_stem("chapter_1"))

    @staticmethod
    def _sha(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
