from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("captions", ROOT / "scripts" / "build_word_aligned_captions.py")
CAPTIONS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(CAPTIONS)


class WordAlignedCaptionTests(unittest.TestCase):
    def test_verbatim_grouping_preserves_word_timing_and_applies_audited_phrase(self):
        raw = {"segments": [{"words": [
            {"start": 0.0, "end": 0.2, "word": "豆"},
            {"start": 0.2, "end": 0.4, "word": "包"},
            {"start": 0.4, "end": 0.6, "word": "签"},
            {"start": 0.6, "end": 0.8, "word": "问"},
            {"start": 0.8, "end": 1.2, "word": "很好用。"},
        ]}]}
        corrections = {"replacements": [{"from": "豆包签问", "to": "豆包、千问", "evidence": "verified product name"}]}
        data, srt, report = CAPTIONS.build(raw, corrections)
        self.assertEqual(data["segments"][0]["start"], 0.0)
        self.assertEqual(data["segments"][0]["end"], 1.2)
        self.assertIn("豆包、千问很好用", srt)
        self.assertEqual(data["segments"][0]["alignment"], "word_timestamp")
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["applied_corrections"]), 1)

    def test_long_speech_is_split_from_word_timestamps_without_summary_text(self):
        words = [{"start": index * 0.3, "end": index * 0.3 + 0.2, "word": char} for index, char in enumerate("这是逐词时间戳生成的完整原话而不是摘要。")]
        data, _, report = CAPTIONS.build({"segments": [{"words": words}]}, None, max_chars=10)
        self.assertGreater(len(data["segments"]), 1)
        self.assertEqual("".join(item["text"] for item in data["segments"]), "这是逐词时间戳生成的完整原话而不是摘要。")
        self.assertTrue(report["passed"])

    def test_long_audited_replacement_remains_splittable_and_within_duration_limit(self):
        raw = {"segments": [{"words": [
            {"start": index * 0.5, "end": index * 0.5 + 0.45, "word": char}
            for index, char in enumerate("非常强大的软件后续说明")
        ]}]}
        corrections = {"replacements": [{
            "from": "非常强大的软件", "to": "非常强大的语言模型", "evidence": "verified context"
        }]}
        data, _, report = CAPTIONS.build(raw, corrections, max_duration=3.8, max_chars=10)
        self.assertGreater(len(data["segments"]), 1)
        self.assertLessEqual(report["max_caption_duration"], 3.8)
        self.assertTrue(report["passed"])

    def test_sequential_correction_does_not_absorb_previous_punctuation_token(self):
        words = [
            {"text": char, "start": index * 0.25, "end": (index + 1) * 0.25}
            for index, char in enumerate("第一句话")
        ] + [
            {"text": char, "start": 3.0 + index * 0.25, "end": 3.0 + (index + 1) * 0.25}
            for index, char in enumerate("希望未来")
        ]
        corrected, applied = CAPTIONS.apply_replacements(words, [
            {"from": "第一句话", "to": "第一句话。", "evidence": "sentence boundary"},
            {"from": "希望未来", "to": "希望未来。", "evidence": "sentence boundary"},
        ])

        second = next(row for row in applied if row["from"] == "希望未来")
        self.assertEqual(second["start"], 3.0)
        self.assertEqual(
            next(row["start"] for row in corrected if row["text"] == "希"),
            3.0,
        )


if __name__ == "__main__":
    unittest.main()
