from __future__ import annotations

import unittest

from scripts.build_phrase_captions import build_phrase_rows


class BuildPhraseCaptionsTests(unittest.TestCase):
    def test_segments_without_rewriting_word_text(self) -> None:
        transcript = {"words": [
            {"id": "w1", "text": "以前", "start": 0.0, "end": 0.4},
            {"id": "w2", "text": "總聽", "start": 0.4, "end": 0.8},
            {"id": "w3", "text": "別人說", "start": 0.8, "end": 1.2},
        ]}
        rows = build_phrase_rows(transcript, ["w2", "w3"])
        self.assertEqual([row["text"] for row in rows], ["以前總聽", "別人說"])
        self.assertEqual("".join(row["text"] for row in rows), "以前總聽別人說")

    def test_rejects_unknown_or_partial_boundary_inventory(self) -> None:
        transcript = {"words": [
            {"id": "w1", "text": "一", "start": 0.0, "end": 0.2},
            {"id": "w2", "text": "二", "start": 0.2, "end": 0.4},
        ]}
        with self.assertRaises(ValueError):
            build_phrase_rows(transcript, ["missing"])
        with self.assertRaises(ValueError):
            build_phrase_rows(transcript, ["w1"])

    def test_spoken_clean_keeps_source_text_but_removes_display_punctuation(self) -> None:
        transcript = {"words": [
            {"id": "w1", "text": "轻轻", "start": 0.0, "end": 0.3},
            {"id": "w2", "text": "一放，", "start": 0.3, "end": 0.6},
            {"id": "w3", "text": "就会", "start": 0.8, "end": 1.1},
            {"id": "w4", "text": "充电。", "start": 1.1, "end": 1.5},
        ]}
        rows = build_phrase_rows(transcript, ["w2", "w4"], punctuation_style="spoken_clean")
        self.assertEqual([row["text"] for row in rows], ["轻轻一放", "就会充电"])
        self.assertEqual([row["source_text"] for row in rows], ["轻轻一放，", "就会充电。"])
        self.assertEqual([row["word_ids"] for row in rows], [["w1", "w2"], ["w3", "w4"]])

    def test_accepts_video_use_mapped_source_word_ids(self) -> None:
        transcript = {"words": [
            {"source_word_id": "w1", "text": "运动", "start": 0.0, "end": 0.4},
            {"source_word_id": "w2", "text": "也稳", "start": 0.4, "end": 0.8},
        ]}
        rows = build_phrase_rows(transcript, ["w2"])
        self.assertEqual(rows[0]["word_ids"], ["w1", "w2"])
        self.assertEqual(rows[0]["text"], "运动也稳")


if __name__ == "__main__":
    unittest.main()
