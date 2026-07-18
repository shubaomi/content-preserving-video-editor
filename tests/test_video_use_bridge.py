from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import video_use_bridge as bridge  # noqa: E402


class VideoUseBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        helper = root / "helpers" / "render.py"
        helper.parent.mkdir(parents=True)
        helper.write_text(
            "def _words_in_range(transcript, start, end):\n"
            "    return [w for w in transcript['words'] if w.get('type') == 'word' and w['end'] > start and w['start'] < end]\n",
            encoding="utf-8",
        )
        self.old_root = os.environ.get("VIDEO_USE_SKILL_ROOT")
        os.environ["VIDEO_USE_SKILL_ROOT"] = str(root)

    def tearDown(self) -> None:
        if self.old_root is None:
            os.environ.pop("VIDEO_USE_SKILL_ROOT", None)
        else:
            os.environ["VIDEO_USE_SKILL_ROOT"] = self.old_root
        self.temp.cleanup()

    def test_words_are_remapped_with_video_use_output_timeline_formula(self) -> None:
        transcript = {"words": [
            {"id": "w1", "type": "word", "text": "核心", "start": 10.2, "end": 10.5},
            {"id": "w2", "type": "word", "text": "流程。", "start": 10.5, "end": 11.0},
        ]}
        edl = {"ranges": [{"source": "a", "start": 10.0, "end": 12.0, "timeline_start": 5.0}]}
        mapped = bridge.map_words_to_output(edl, {"a": transcript})
        self.assertAlmostEqual(mapped[0]["start"], 5.2)
        self.assertAlmostEqual(mapped[-1]["end"], 6.0)
        captions = bridge.build_captions(mapped)
        self.assertEqual(captions[0]["text"], "核心流程。")
        self.assertEqual(captions[0]["mapping_owner"], "video-use")
        self.assertTrue(bridge.synchronization_report(mapped, captions)["passed"])

    def test_render_command_uses_real_video_use_helper(self) -> None:
        command = bridge.render_command(Path("edl.json"), Path("preview.mp4"), preview=True)
        self.assertIn(str(bridge.render_helper_path()), command)
        self.assertIn("--build-subtitles", command)
        self.assertIn("--preview", command)

    def test_sync_sampling_does_not_absorb_adjacent_words(self) -> None:
        words = [
            {"text": "前句。", "start": 0.0, "end": 0.5, "source_word_count": 1},
            {"text": "本句", "start": 0.7, "end": 1.0, "source_word_count": 1},
            {"text": "结束。", "start": 1.0, "end": 1.4, "source_word_count": 1},
            {"text": "后句。", "start": 1.6, "end": 2.0, "source_word_count": 1},
        ]
        captions = bridge.build_captions(words)
        report = bridge.synchronization_report(words, captions, sample_count=3)
        self.assertTrue(report["passed"])
        self.assertTrue(all(sample["lead_error_s"] == 0 for sample in report["samples"]))

    def test_only_audited_corrections_can_change_mapped_words(self) -> None:
        words = [
            {"text": "H", "start": 0.0, "end": 0.2, "source_word_count": 1},
            {"text": "Run", "start": 0.2, "end": 0.5, "source_word_count": 1},
        ]
        corrected, applied = bridge.apply_audited_corrections(words, {"replacements": [{
            "from": "H Run", "to": "HongRun", "evidence": "confirmed profile name",
        }]})
        self.assertEqual("".join(word["text"] for word in corrected), "HongRun")
        self.assertEqual(applied[0]["evidence"], "confirmed profile name")

    def test_semantic_phrase_is_not_split_only_to_hit_soft_duration(self) -> None:
        text = "你想了解的概念词语，"
        words = [{"text": char, "start": index * 0.55, "end": index * 0.55 + 0.5,
                  "source_word_count": 1} for index, char in enumerate(text)]
        captions = bridge.build_captions(words, max_duration=4.2, max_chars=20)
        self.assertEqual(len(captions), 1)
        self.assertEqual(captions[0]["text"], text)

    def test_short_incomplete_words_are_not_stranded_by_a_pause(self) -> None:
        words = [
            {"text": "它", "start": 0.0, "end": 0.2, "source_word_count": 1},
            {"text": "会", "start": 0.2, "end": 0.4, "source_word_count": 1},
            {"text": "给", "start": 0.4, "end": 0.6, "source_word_count": 1},
            {"text": "概", "start": 1.5, "end": 1.7, "source_word_count": 1},
            {"text": "念", "start": 1.7, "end": 1.9, "source_word_count": 1},
            {"text": "。", "start": 1.9, "end": 2.0, "source_word_count": 1},
        ]
        captions = bridge.build_captions(words, pause_break=0.5)
        self.assertEqual([caption["text"] for caption in captions], ["它会给概念。"])

    def test_connector_suffix_waits_for_the_semantic_completion(self) -> None:
        text = "还有一些和其他相关概念的一些对比。"
        words = []
        for index, char in enumerate(text):
            start = index * 0.55 + (0.8 if index > text.index("他") else 0.0)
            words.append({"text": char, "start": start, "end": start + 0.5, "source_word_count": 1})
        captions = bridge.build_captions(words, max_duration=6.5, max_chars=24, pause_break=0.5)
        self.assertEqual([caption["text"] for caption in captions], [text])

    def test_ascii_comma_breaks_a_long_spoken_clause_before_the_next_subject(self) -> None:
        tokens = [*"但是这个对比不是什么时候都会生成", "的,", *"这个是根据不同的概念生成的。"]
        words = [
            {
                "text": token,
                "start": index * 0.35,
                "end": index * 0.35 + 0.3,
                "source_word_count": 1,
            }
            for index, token in enumerate(tokens)
        ]
        captions = bridge.build_captions(
            words,
            max_duration=6.5,
            max_chars=24,
            pause_break=0.5,
            punctuation_style="spoken_clean",
        )
        self.assertEqual(
            [caption["text"] for caption in captions],
            ["但是这个对比不是什么时候都会生成的", "这个是根据不同的概念生成的"],
        )

    def test_sentence_punctuation_wins_over_incomplete_suffix_rebalancing(self) -> None:
        tokens = [*"我做的第一版本就是概念学习", "的。", *"它会给你想需要了解的概念词语，"]
        words = []
        for index, token in enumerate(tokens):
            start = index * 0.2 + (0.7 if index > tokens.index("的。") else 0.0)
            words.append({"text": token, "start": start, "end": start + 0.18,
                          "source_word_count": 1})
        captions = bridge.build_captions(words, max_duration=6.5, max_chars=24,
                                         pause_break=0.5, punctuation_style="spoken_clean")
        self.assertEqual(
            [caption["text"] for caption in captions],
            ["我做的第一版本就是概念学习的", "它会给你想需要了解的概念词语"],
        )
        self.assertFalse(any(caption["text"].startswith("的") for caption in captions[1:]))

    def test_spoken_clean_keeps_question_tone_but_hides_terminal_stops(self) -> None:
        self.assertEqual(bridge._display_caption_text("这是结论。", "spoken_clean"), "这是结论")
        self.assertEqual(bridge._display_caption_text("概念，原理。", "spoken_clean"), "概念原理")
        self.assertEqual(bridge._display_caption_text("你理解了吗？", "spoken_clean"), "你理解了吗？")
        self.assertEqual(bridge._display_caption_text("概念，原理。", "none"), "概念原理")

    def test_hard_split_rebalances_incomplete_tail_to_next_caption(self) -> None:
        text = "通过一个Skill来在不改变原产品的基础之上去做一个原产品核心功能一次完整请求的拆解。"
        tokens = [*"通过一个", "Skill", *"来在不改变原产品的基础之上去做一个原产品核心功能一次完整请求的拆解。"]
        words = [
            {"text": token, "start": index * 0.2, "end": index * 0.2 + 0.18,
             "source_word_count": 1}
            for index, token in enumerate(tokens)
        ]
        captions = bridge.build_captions(words, max_duration=6.5, max_chars=24, pause_break=0.5)
        self.assertEqual("".join(caption["text"] for caption in captions), text)
        self.assertTrue(captions[0]["text"].endswith("基础之上"))
        self.assertTrue(captions[1]["text"].startswith("去做一个原产品"))

    def test_hard_split_does_not_leave_a_tiny_final_flash(self) -> None:
        text = "它通过不同模块帮助你理解某一个词的基本意思和核心原理是什么。"
        words = [
            {"text": char, "start": index * 0.25, "end": index * 0.25 + 0.22,
             "source_word_count": 1}
            for index, char in enumerate(text)
        ]
        captions = bridge.build_captions(words, max_duration=6.5, max_chars=24, pause_break=0.5)
        self.assertEqual([caption["text"] for caption in captions], [text])


if __name__ == "__main__":
    unittest.main()
