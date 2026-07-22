from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compose_generated_cover import compose_with_layout  # noqa: E402


class CoverTemplateRendererTests(unittest.TestCase):
    def _base(self, root: Path) -> Path:
        path = root / "base.png"
        image = Image.new("RGB", (1080, 1920), "#dce8e2")
        draw = ImageDraw.Draw(image)
        for y in range(1920):
            shade = int(220 - 90 * y / 1920)
            draw.line((0, y, 1080, y), fill=(shade, min(240, shade + 16), min(245, shade + 22)))
        draw.rounded_rectangle((650, 260, 1030, 1650), radius=120, fill="#7b8f86")
        image.save(path)
        return path

    def test_template_families_are_structurally_distinct_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = self._base(root)
            arrays = []
            templates = (
                "cinematic_editorial",
                "bright_tech_tutorial",
                "dark_high_energy",
                "thought_leadership_ip",
            )
            for name in templates:
                result, layout = compose_with_layout(
                    base=base,
                    title="稳定生成主题封面",
                    label="AI 视频工作流",
                    subtitle="让内容证据决定视觉",
                    side="top-left",
                    chips=["主题相关", "真人可信"],
                    template_family=name,
                    highlight_terms=["稳定", "主题"],
                    subject_box=[610, 260, 1040, 1680],
                    maximum_lines=3,
                )
                self.assertEqual(result.size, (1080, 1920))
                self.assertEqual(layout["template_family"], name)
                self.assertLessEqual(layout["typography"]["line_count"], 3)
                self.assertGreaterEqual(layout["typography"]["minimum_thumbnail_font_px"], 10)
                self.assertTrue(any("主题" in line for line in layout["typography"]["lines"]))
                self.assertLessEqual(layout["decorative_bounds"][2], layout["subject_box"][0])
                safe = layout["safe_bounds"]
                for box in layout["boxes"].values():
                    self.assertGreaterEqual(box[0], safe[0])
                    self.assertGreaterEqual(box[1], safe[1])
                    self.assertLessEqual(box[2], safe[2])
                    self.assertLessEqual(box[3], safe[3])
                arrays.append(np.asarray(result.resize((108, 192)), dtype=np.float32))
            for index in range(1, len(arrays)):
                difference = float(np.mean(np.abs(arrays[0] - arrays[index])) / 255.0)
                self.assertGreater(difference, 0.01)

    def test_ip_template_integrates_owned_supporting_asset_without_title_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = self._base(root)
            ip = root / "ip.png"
            Image.new("RGBA", (240, 240), (240, 180, 40, 255)).save(ip)

            _, layout = compose_with_layout(
                base=base,
                title="真人与IP共同解释",
                label="知识型封面",
                subtitle="不是随机装饰",
                side="top-left",
                chips=["主题证据"],
                template_family="thought_leadership_ip",
                highlight_terms=["IP"],
                subject_box=[610, 260, 1040, 1680],
                supporting_assets=[{"path": str(ip), "role": "personal_ip"}],
                maximum_lines=3,
            )

            self.assertIn("supporting_asset_0", layout["boxes"])
            title = layout["boxes"]["title"]
            subject = layout["subject_box"]
            overlap_width = max(0, min(title[2], subject[2]) - max(title[0], subject[0]))
            overlap_height = max(0, min(title[3], subject[3]) - max(title[1], subject[1]))
            self.assertEqual(overlap_width * overlap_height, 0)


if __name__ == "__main__":
    unittest.main()
