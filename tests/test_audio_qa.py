from __future__ import annotations

import sys
import tempfile
import unittest
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_qa import validate  # noqa: E402


class AudioQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "assets" / "sfx").mkdir(parents=True)
        for name in ("a.wav", "b.wav", "c.wav", "d.wav"):
            (self.root / "assets" / "sfx" / name).write_bytes(b"audio")
        (self.root / "bgm.wav").write_bytes(b"music")
        (self.root / "mix-audibility.json").write_text("{}", encoding="utf-8")
        self.storyboard = {
            "events": [
                {"id": "e1", "start": 1.0, "end": 4.0, "treatment": "steps"},
                {"id": "e2", "start": 22.0, "end": 26.0, "treatment": "comparison_panel"},
                {"id": "e3", "start": 45.0, "end": 49.0, "treatment": "chapter_transition"},
                {"id": "quiet", "start": 50.0, "end": 55.0, "treatment": "quiet_source"},
            ]
        }
        self.project = {
            "audio": {
                "sfx": {
                    "target_event_coverage": 1.0,
                    "minimum_unique_asset_ratio": 1.0,
                    "maximum_family_ratio": 0.67,
                    "same_file_cooldown_seconds": 20,
                    "minimum_post_gain_mean_dbfs": -34,
                    "maximum_post_gain_mean_dbfs": -18,
                },
                "bgm": {
                    "enabled_by_default": True,
                    "asset": "bgm.wav",
                },
            }
        }
        self.plan = {
            "speech_track": {"dominant": True},
            "background_music": {
                "mode": "authorized_asset",
                "enabled": True,
                "source": "bgm.wav",
                "preview_volume": 0.1,
                "ducking": {"enabled": True, "method": "sidechaincompress", "status": "pass"},
                "provenance": {"authorization": "user-generated asset", "sha256": "abc"},
            },
            "motion_sfx": {
                "event_decisions": [
                    self._cue("e1", "assets/sfx/a.wav", 1.2, "ui_confirm"),
                    self._cue("e2", "assets/sfx/b.wav", 22.2, "compare_exchange"),
                    self._cue("e3", "assets/sfx/c.wav", 45.2, "chapter_chime"),
                ],
                "mix_audibility_check": {
                    "status": "pass",
                    "evidence": "mix-audibility.json",
                },
            },
            "provenance": [{"role": "speech", "path": "source.mp4"}],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _cue(event_id: str, asset: str, start: float, family: str) -> dict:
        return {
            "event_id": event_id,
            "decision": "cue",
            "asset": asset,
            "family": family,
            "start": start,
            "duration_seconds": 1.2,
            "volume": 0.28,
            "post_gain_mean_dbfs": -28.0,
        }

    def test_complete_audible_event_map_and_authorized_bgm_pass(self) -> None:
        self.assertEqual(validate(self.plan, self.storyboard, self.project, base_dir=self.root), [])

    def test_missing_event_decision_and_inaudible_cue_are_blocking(self) -> None:
        self.plan["motion_sfx"]["event_decisions"].pop()
        self.plan["motion_sfx"]["event_decisions"][0]["post_gain_mean_dbfs"] = -41.0
        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)
        self.assertTrue(any("e3" in error and "decision" in error for error in errors))
        self.assertTrue(any("e1" in error and "inaudible" in error for error in errors))

    def test_embedded_source_bgm_requires_measured_presence(self) -> None:
        self.project["audio"]["bgm"]["asset"] = None
        self.plan["background_music"] = {
            "mode": "embedded_source",
            "enabled": True,
            "source": "source.mp4",
            "presence_analysis": {
                "status": "not_detected",
                "longest_below_threshold_seconds": 3.86,
                "measured_floor_dbfs": -59.7,
            },
        }
        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)
        self.assertTrue(any("embedded BGM" in error and "measured" in error for error in errors))

    def test_authorized_default_bgm_cannot_be_silently_skipped(self) -> None:
        self.plan["background_music"] = {
            "mode": "disabled",
            "enabled": False,
            "reason": "assumed source already had music",
        }
        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)
        self.assertTrue(any("authorized BGM" in error and "disabled" in error for error in errors))

    def test_unavailable_optional_bgm_is_truthful_when_attempts_and_reason_are_recorded(self) -> None:
        self.project["audio"]["bgm"] = {"enabled_by_default": True}
        self.plan["background_music"] = {
            "mode": "unavailable",
            "enabled": False,
            "reason": "no authorized provider produced an asset",
            "attempts": [{"provider": "local", "status": "unavailable"}],
        }

        self.assertEqual(validate(
            self.plan, self.storyboard, self.project, base_dir=self.root
        ), [])

    def test_different_files_do_not_hide_one_dominant_sfx_family(self) -> None:
        self.plan["motion_sfx"]["event_decisions"] = [
            self._cue("e1", "assets/sfx/a.wav", 1.2, "soft_motif"),
            self._cue("e2", "assets/sfx/b.wav", 22.2, "soft_motif"),
            self._cue("e3", "assets/sfx/c.wav", 45.2, "soft_motif"),
        ]

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertTrue(any("SFX family" in error and "dominates" in error for error in errors), errors)

    def test_single_selected_cue_does_not_trigger_an_impossible_family_variety_gate(self) -> None:
        self.storyboard["events"] = self.storyboard["events"][:1]
        self.plan["motion_sfx"]["event_decisions"] = [
            self._cue("e1", "assets/sfx/a.wav", 1.2, "soft_motif"),
        ]

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertFalse(any("SFX family" in error and "dominates" in error for error in errors), errors)

    def test_sfx_asset_must_stay_inside_authorized_asset_root(self) -> None:
        outside = self.root.parent / "outside.wav"
        outside.write_bytes(b"private")
        self.plan["motion_sfx"]["event_decisions"][0]["asset"] = str(outside)

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertTrue(any("authorized SFX root" in error for error in errors), errors)

    def _enable_perceptual_policy(self) -> None:
        self.project["audio"]["sfx"]["perceptual"] = {
            "enabled": True,
            "minimum_audible_ratio": 0.35,
            "maximum_audible_ratio": 0.65,
            "maximum_onset_error_ms": 80,
        }
        events = []
        for row in self.plan["motion_sfx"]["event_decisions"]:
            if row["decision"] == "cue":
                row["motif_fingerprint_sha256"] = hashlib.sha256(
                    row["family"].encode("utf-8")
                ).hexdigest()
                events.append({
                    "event_id": row["event_id"], "decision": "cue",
                    "motif_fingerprint_sha256": row["motif_fingerprint_sha256"],
                    "onset_error_ms": 20.0,
                    "dialogue_window_lufs": -18.0,
                    "cue_window_lufs": -29.0,
                    "dialogue_cue_delta_lu": 11.0,
                    "audibility_status": "audible_without_masking",
                })
            else:
                events.append({
                    "event_id": row["event_id"], "decision": "intentionally_silent",
                    "audibility_status": "not_applicable",
                })
        evidence = {"schema_version": 2, "status": "pass", "events": events}
        path = self.root / "mix-perceptual.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        self.plan["motion_sfx"]["perceptual_evidence"] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def test_perceptual_policy_counts_decisions_not_only_audible_cues(self) -> None:
        self.plan["motion_sfx"]["event_decisions"][1] = {
            "event_id": "e2", "decision": "intentionally_silent",
            "reason": "dense speech makes this supporting event masking-prone",
        }
        self._enable_perceptual_policy()

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertFalse(any("coverage" in error for error in errors), errors)

    def test_perceptual_policy_rejects_cue_on_every_event(self) -> None:
        self._enable_perceptual_policy()

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertTrue(any("audible-cue ratio" in error for error in errors), errors)

    def test_perceptual_policy_rejects_stale_or_masking_mix_evidence(self) -> None:
        self.plan["motion_sfx"]["event_decisions"][1] = {
            "event_id": "e2", "decision": "intentionally_silent",
            "reason": "dense speech",
        }
        self._enable_perceptual_policy()
        evidence_path = Path(self.plan["motion_sfx"]["perceptual_evidence"]["path"])
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["events"][0]["onset_error_ms"] = 120.0
        evidence["events"][0]["audibility_status"] = "dialogue_harmed"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        self.plan["motion_sfx"]["perceptual_evidence"]["sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertTrue(any("onset" in error for error in errors), errors)
        self.assertTrue(any("dialogue_harmed" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
