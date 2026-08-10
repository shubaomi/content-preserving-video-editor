from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_qa import validate  # noqa: E402


class AudioQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "sfx").mkdir()
        for name in ("a.wav", "b.wav", "c.wav", "d.wav"):
            (self.root / "sfx" / name).write_bytes(b"audio")
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
                    self._cue("e1", "sfx/a.wav", 1.2, "ui_confirm"),
                    self._cue("e2", "sfx/b.wav", 22.2, "compare_exchange"),
                    self._cue("e3", "sfx/c.wav", 45.2, "chapter_chime"),
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

    def test_different_files_do_not_hide_one_dominant_sfx_family(self) -> None:
        self.plan["motion_sfx"]["event_decisions"] = [
            self._cue("e1", "sfx/a.wav", 1.2, "soft_motif"),
            self._cue("e2", "sfx/b.wav", 22.2, "soft_motif"),
            self._cue("e3", "sfx/c.wav", 45.2, "soft_motif"),
        ]

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertTrue(any("SFX family" in error and "dominates" in error for error in errors), errors)

    def test_single_selected_cue_does_not_trigger_an_impossible_family_variety_gate(self) -> None:
        self.storyboard["events"] = self.storyboard["events"][:1]
        self.plan["motion_sfx"]["event_decisions"] = [
            self._cue("e1", "sfx/a.wav", 1.2, "soft_motif"),
        ]

        errors = validate(self.plan, self.storyboard, self.project, base_dir=self.root)

        self.assertFalse(any("SFX family" in error and "dominates" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
