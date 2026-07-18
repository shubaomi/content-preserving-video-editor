from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "scripts" / "extract_design_tokens.py"
SPEC = importlib.util.spec_from_file_location("extract_design_tokens", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class DesignTokenTests(unittest.TestCase):
    def test_dark_ui_uses_light_text(self) -> None:
        result = MODULE.extract_tokens([Image.new("RGB", (1920, 1080), "#111827") for _ in range(3)])
        self.assertEqual(result["surface"]["text_color"], "#f8fafc")
        self.assertEqual(result["sampling"]["dimensions"]["width"], 1920)

    def test_light_ui_uses_dark_text(self) -> None:
        result = MODULE.extract_tokens([Image.new("RGB", (1920, 1080), "#f8fafc") for _ in range(3)])
        self.assertEqual(result["surface"]["text_color"], "#172033")

    def test_portrait_safe_zone_reserves_platform_controls(self) -> None:
        result = MODULE.extract_tokens([Image.new("RGB", (1080, 1920), "#dbeafe")])
        self.assertGreaterEqual(result["safe_zones"]["platform_ui_avoid"]["x0"], 0.75)
        self.assertLess(result["shape"]["border_radius_confidence"], 0.5)

    def test_hyperframes_css_has_high_confidence(self) -> None:
        css = ".card{border-radius:24px;border-width:2px;box-shadow:0 4px 9px #000;font-family:Inter,sans-serif}"
        result = MODULE.extract_tokens([Image.new("RGB", (100, 100), "white")], css)
        self.assertEqual(result["shape"]["border_radius_px"], 24)
        self.assertGreater(result["typography"]["confidence"], 0.8)


if __name__ == "__main__":
    unittest.main()
