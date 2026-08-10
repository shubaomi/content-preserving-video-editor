from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_existing_edit.py"
SPEC = importlib.util.spec_from_file_location("analyze_existing_edit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ExistingEditTests(unittest.TestCase):
    def test_caption_score_distinguishes_lower_third_text(self) -> None:
        plain = Image.new("RGB", (480, 270), (95, 105, 115))
        captioned = plain.copy()
        draw = ImageDraw.Draw(captioned)
        draw.rectangle((105, 210, 375, 242), fill=(25, 25, 25))
        for x in range(120, 355, 18):
            draw.rectangle((x, 218, x + 9, 232), fill=(245, 245, 245))
        self.assertLess(MODULE.caption_score(plain), 0.05)
        self.assertGreater(MODULE.caption_score(captioned), 0.22)

    def test_dense_dashboard_text_is_only_an_unverified_caption_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            samples = []
            for index in range(8):
                path = root / f"dashboard-{index}.png"
                image = Image.new("RGB", (480, 270), "white")
                draw = ImageDraw.Draw(image)
                for row in range(6):
                    y = 170 + row * 13
                    draw.line((30, y, 450, y), fill=(75, 85, 95), width=2)
                    for column in range(8):
                        x = 35 + column * 50
                        draw.rectangle((x, y - 8, x + 24, y - 4), fill=(110, 120, 130))
                image.save(path)
                samples.append((float(index * 5 + 2), path))

            result = MODULE.analyze_visuals(samples, root / "evidence")["burned_caption"]

        self.assertEqual(result["verification_status"], "heuristic_unverified")
        self.assertFalse(result["detected"])
        self.assertEqual(result["decision"], "review_required_before_suppressing_captions")

    def test_declared_existing_bgm_blocks_second_bed(self) -> None:
        probe = {"streams": [{"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "44100"}]}
        original = MODULE.detect_silence
        original_transients = MODULE.analyze_transients
        MODULE.detect_silence = lambda *_: {"active_ratio": 1.0}
        MODULE.analyze_transients = lambda *_: {"state": "no_strong_candidates", "count": 0, "candidates": []}
        try:
            result = MODULE.audio_decision(probe, Path("fixture.mp4"), 60.0, "yes")
        finally:
            MODULE.detect_silence = original
            MODULE.analyze_transients = original_transients
        self.assertEqual(result["existing_bgm"], "yes")
        self.assertFalse(result["add_bgm"])

    def test_declared_bgm_with_long_near_silent_gaps_requires_presence_review(self) -> None:
        probe = {"streams": [{"codec_type": "audio", "codec_name": "aac", "channels": 2}]}
        original = MODULE.detect_silence
        original_transients = MODULE.analyze_transients
        MODULE.detect_silence = lambda *_: {
            "active_ratio": 0.91,
            "silent_seconds": 8.2,
            "longest_silence_seconds": 3.86,
        }
        MODULE.analyze_transients = lambda *_: {"state": "no_strong_candidates", "count": 0, "candidates": []}
        try:
            result = MODULE.audio_decision(probe, Path("fixture.mp4"), 60.0, "yes")
        finally:
            MODULE.detect_silence = original
            MODULE.analyze_transients = original_transients
        self.assertEqual(result["existing_bgm"], "declared_unverified")
        self.assertTrue(result["requires_bgm_presence_review"])
        self.assertFalse(result["add_bgm"])

    def test_unknown_mix_is_conservative(self) -> None:
        probe = {"streams": [{"codec_type": "audio", "codec_name": "aac"}]}
        original = MODULE.detect_silence
        original_transients = MODULE.analyze_transients
        MODULE.detect_silence = lambda *_: {"active_ratio": 0.8}
        MODULE.analyze_transients = lambda *_: {"state": "no_strong_candidates", "count": 0, "candidates": []}
        try:
            result = MODULE.audio_decision(probe, Path("fixture.mp4"), 60.0, "auto")
        finally:
            MODULE.detect_silence = original
            MODULE.analyze_transients = original_transients
        self.assertEqual(result["existing_bgm"], "unknown")
        self.assertFalse(result["add_bgm"])

    def test_budget_exposes_dynamic_candidates_without_legacy_spacing_cap(self) -> None:
        visual = {"frame_change": {"monotony_candidates": [{"timestamp": value} for value in range(20, 380, 30)]}}
        result = MODULE.enhancement_budget(392.0, visual)
        self.assertEqual(result["planner"], "semantic_confidence_first")
        self.assertGreater(len(result["candidate_timestamps"]), 5)
        self.assertEqual(result["recommended_events_per_minute"]["polish_existing"], [3, 7])
        self.assertEqual(result["event_rate_policy"], "advisory_ceiling")
        self.assertNotIn("35-second", result["rule"])

    def test_transient_detector_labels_strong_onset_candidate(self) -> None:
        samples = np.zeros(8000 * 2, dtype=np.float32)
        samples[8000:8400] = 0.8
        result = MODULE.transient_candidates(samples)
        self.assertGreaterEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["timestamp"], 1.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
