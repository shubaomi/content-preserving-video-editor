from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_ip_components.py"
SPEC = importlib.util.spec_from_file_location("prepare_ip_components", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class IpComponentTests(unittest.TestCase):
    def test_white_connected_canvas_becomes_transparent(self) -> None:
        image = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(image).rectangle((30, 30, 70, 80), fill="black")
        result, meta = MODULE.remove_connected_matte(image)
        alpha = np.asarray(result)[:, :, 3]
        self.assertEqual(int(alpha[0, 0]), 0)
        self.assertEqual(int(alpha[50, 50]), 255)
        self.assertGreater(meta["border_consistency"], 0.9)

    def test_native_alpha_corners_pass(self) -> None:
        image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse((10, 10, 30, 30), fill=(10, 100, 200, 255))
        qa = MODULE.alpha_qa(image)
        self.assertTrue(qa["passed"])
        self.assertEqual(qa["transparent_corner_count"], 4)


if __name__ == "__main__":
    unittest.main()
