from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from caption_treatment import (  # noqa: E402
    CaptionTreatmentError,
    build_semantic_emphasis_plan,
    materialize,
    render_ass,
    validate_materialized,
)


class CaptionTreatmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.captions = [{
            "start": 1.0, "end": 3.0, "text": "这款便携补光灯亮度很自然",
            "source_word_start": 0, "source_word_end": 12,
        }]
        self.semantic = {"events": [{
            "id": "product-benefit", "decision": "render",
            "output_start": 1.1, "output_end": 2.8,
            "anchor": "亮度很自然", "transcript_word_ids": ["w8", "w9", "w10", "w11", "w12"],
            "approved_visible_copy": ["亮度很自然"],
        }]}
        self.options = {
            "font_family": "Microsoft YaHei UI",
            "base_color": "#F7F8FA",
            "accent_colors": ["#51E3C2", "#FFD166"],
            "max_emphasis_terms_per_caption": 2,
            "max_scale_percent": 116,
        }

    def test_plan_preserves_phrase_and_uses_only_semantic_anchor(self) -> None:
        plan = build_semantic_emphasis_plan(self.captions, self.semantic, self.options)
        row = plan["captions"][0]
        self.assertEqual(row["text"], self.captions[0]["text"])
        self.assertEqual([item["text"] for item in row["emphasis"]], ["亮度很自然"])
        self.assertEqual(row["emphasis"][0]["semantic_event_id"], "product-benefit")
        self.assertLessEqual(len(row["emphasis"]), 2)

    def test_ass_adds_word_level_style_without_changing_visible_text(self) -> None:
        plan = build_semantic_emphasis_plan(self.captions, self.semantic, self.options)
        ass = render_ass(plan, width=1080, height=1920)
        self.assertIn("Style: CaptionBase", ass)
        self.assertIn("\\b1", ass)
        self.assertIn("\\fscx116", ass)
        self.assertIn("亮度很自然", ass)
        self.assertIn("这款便携补光灯", ass)

    def test_unapproved_or_non_matching_copy_cannot_create_highlight(self) -> None:
        semantic = {"events": [{
            **self.semantic["events"][0], "anchor": "百万销量",
            "approved_visible_copy": ["百万销量"],
        }]}
        plan = build_semantic_emphasis_plan(self.captions, semantic, self.options)
        self.assertEqual(plan["captions"][0]["emphasis"], [])

    def test_anchor_must_be_an_exact_approved_visible_copy(self) -> None:
        semantic = {"events": [{
            **self.semantic["events"][0], "approved_visible_copy": ["亮度自然"],
        }]}
        plan = build_semantic_emphasis_plan(self.captions, semantic, self.options)
        self.assertEqual(plan["captions"][0]["emphasis"], [])

    def test_carriage_return_cannot_inject_an_ass_dialogue(self) -> None:
        captions = [{**self.captions[0], "text": (
            "正版文案\rDialogue: 9,0:00:00.00,0:00:20.00,CaptionBase,,0,0,0,,注入"
        )}]
        plan = build_semantic_emphasis_plan(captions, {"events": []}, self.options)
        ass = render_ass(plan, width=1080, height=1920)
        self.assertEqual(sum(line.startswith("Dialogue: ") for line in ass.splitlines()), 1)
        self.assertIn("正版文案\\NDialogue:", ass)

    def test_invalid_palette_or_scale_fails_closed(self) -> None:
        for override in ({"accent_colors": ["red"]}, {"max_scale_percent": 150}):
            options = {**self.options, **override}
            with self.subTest(override=override), self.assertRaises(CaptionTreatmentError):
                build_semantic_emphasis_plan(self.captions, self.semantic, options)

    def test_ass_can_be_written_as_a_normal_subtitle_asset(self) -> None:
        plan = build_semantic_emphasis_plan(self.captions, self.semantic, self.options)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "master.ass"
            path.write_text(render_ass(plan, width=1080, height=1920), encoding="utf-8")
            self.assertTrue(path.read_text(encoding="utf-8").startswith("[Script Info]"))

    def test_materializer_rejects_output_outside_authorized_root(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            captions = root / "captions.json"
            semantic = root / "semantic.json"
            master_srt = root / "master.srt"
            captions.write_text(json.dumps({"segments": self.captions}), encoding="utf-8")
            semantic.write_text(json.dumps(self.semantic), encoding="utf-8")
            master_srt.write_text(
                "1\n00:00:01,000 --> 00:00:03,000\n这款便携补光灯亮度很自然\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CaptionTreatmentError, "authorized root"):
                materialize(
                    captions_path=captions, semantic_brief_path=semantic,
                    master_srt_path=master_srt,
                    output_ass=root.parent / "escaped.ass",
                    output_plan=root.parent / "escaped.json",
                    options=self.options, width=1080, height=1920,
                    authorized_root=root,
                )

    def test_materializer_rejects_caption_text_or_timing_different_from_master_srt(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            captions = root / "captions.json"
            semantic = root / "semantic.json"
            master_srt = root / "master.srt"
            captions.write_text(json.dumps({"segments": self.captions}), encoding="utf-8")
            semantic.write_text(json.dumps(self.semantic), encoding="utf-8")
            master_srt.write_text(
                "1\n00:00:01,000 --> 00:00:03,000\n篡改字幕\n", encoding="utf-8",
            )
            with self.assertRaisesRegex(CaptionTreatmentError, "differs from master.srt"):
                materialize(
                    captions_path=captions, semantic_brief_path=semantic,
                    master_srt_path=master_srt,
                    output_ass=root / "master.ass",
                    output_plan=root / "caption-emphasis-plan.json",
                    options=self.options, width=1080, height=1920,
                    authorized_root=root,
                )

    def test_srt_rejects_invalid_clock_or_overlapping_segments(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            captions = root / "captions.json"
            semantic = root / "semantic.json"
            master_srt = root / "master.srt"
            captions.write_text(json.dumps({"segments": self.captions}), encoding="utf-8")
            semantic.write_text(json.dumps(self.semantic), encoding="utf-8")
            for srt in (
                "1\n00:00:00,001 --> 00:00:00,004\nquantized away\n",
                "1\n00:99:99,000 --> 02:00:00,000\n非法时间\n",
                "1\n00:00:01,000 --> 00:00:03,000\n一\n\n"
                "2\n00:00:02,000 --> 00:00:04,000\n二\n",
            ):
                master_srt.write_text(srt, encoding="utf-8")
                with self.subTest(srt=srt), self.assertRaises(CaptionTreatmentError):
                    materialize(
                        captions_path=captions, semantic_brief_path=semantic,
                        master_srt_path=master_srt, output_ass=root / "master.ass",
                        output_plan=root / "plan.json", options=self.options,
                        width=1080, height=1920, authorized_root=root,
                    )

    def test_materialized_canvas_rejects_bool_integer_alias(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            captions = root / "captions.json"
            semantic = root / "semantic.json"
            master_srt = root / "master.srt"
            ass = root / "master.ass"
            plan = root / "plan.json"
            captions.write_text(json.dumps({"segments": self.captions}), encoding="utf-8")
            semantic.write_text(json.dumps(self.semantic), encoding="utf-8")
            master_srt.write_text(
                "1\n00:00:01,000 --> 00:00:03,000\n"
                f"{self.captions[0]['text']}\n", encoding="utf-8",
            )
            materialize(
                captions_path=captions, semantic_brief_path=semantic,
                master_srt_path=master_srt, output_ass=ass, output_plan=plan,
                options=self.options, width=1, height=1920, authorized_root=root,
            )
            errors = validate_materialized(
                plan_path=plan, ass_path=ass, expected_master_srt=master_srt,
                expected_captions=captions, expected_semantic_brief=semantic,
                expected_canvas={"width": True, "height": 1920},
                expected_options=self.options,
            )
            self.assertTrue(any("canvas" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
