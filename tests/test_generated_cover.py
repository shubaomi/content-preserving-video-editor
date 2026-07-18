from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("cover", ROOT / "scripts" / "compose_generated_cover.py")
COVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(COVER)


class GeneratedCoverTests(unittest.TestCase):
    def test_cover_crop_is_native_vertical(self):
        image = Image.new("RGB", (800, 1200), "navy")
        self.assertEqual(COVER.cover_crop(image).size, (1080, 1920))

    def test_typography_anchor_uses_shared_platform_center_safe_inset(self):
        self.assertEqual(COVER.CENTER_SAFE_INSET, 104)
        self.assertEqual(COVER.CANVAS[0] - COVER.CENTER_SAFE_INSET, 976)
        self.assertGreaterEqual(COVER.CENTER_SAFE_TOP, round(COVER.CANVAS[1] * 0.08))

    def test_wrap_produces_multiple_lines_for_long_title(self):
        image = Image.new("RGB", (1080, 1920), "black")
        draw = ImageDraw.Draw(image)
        lines = COVER.wrap(draw, "这是一个很长的中文视频封面标题", COVER.font(78, True), 400)
        self.assertGreater(len(lines), 1)

    def test_cover_requires_identity_and_expression_review(self):
        self.assertFalse(COVER.cover_passed(True, False))
        self.assertFalse(COVER.cover_passed(False, True))
        self.assertTrue(COVER.cover_passed(True, True))

    def test_cover_accepts_feature_chips_without_changing_canvas(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "base.png"
            Image.new("RGB", (1080, 1920), "#14222b").save(source)
            result = COVER.compose(
                source,
                "AI 回答，怎么变成知识作品？",
                "ExplainIt · 黑客松作品",
                "把复杂概念讲清楚",
                "top-left",
                ["概念学习", "表达素材", "请求透视"],
            )
            self.assertEqual(result.size, (1080, 1920))
if __name__ == "__main__":
    unittest.main()
