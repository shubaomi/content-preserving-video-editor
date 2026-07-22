from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from platform_occlusion_gate import evaluate_geometry  # noqa: E402


class PlatformOcclusionGateTests(unittest.TestCase):
    def test_safe_geometry_passes_both_platforms(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"landscape": [{"id": "controls", "x0": .9, "y0": 0, "x1": 1, "y1": 1}]},
            "wechat_channels": {"landscape": [{"id": "controls", "x0": .9, "y0": 0,
                                                  "x1": 1, "y1": 1}]},
        }}
        report = evaluate_geometry({"orientation": "landscape", "events": [{
            "event_id": "e1", "elements": [{"id": "card", "x0": .1, "y0": .1,
                                                "x1": .3, "y1": .3, "z": 2, "opacity": .9}],
            "protected_zones": [{"id": "face", "x0": .6, "y0": .2, "x1": .8, "y1": .6}],
            "cropped": False, "caption_occluded": False,
        }]}, templates)
        self.assertTrue(report["passed"])

    def test_platform_and_face_collisions_are_blocking(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": [{"id": "buttons", "x0": .8, "y0": .2, "x1": 1, "y1": .9}]},
            "wechat_channels": {"portrait": []},
        }}
        report = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "e1", "elements": [{"id": "card", "x0": .75, "y0": .3,
                                                "x1": .95, "y1": .7, "z": 2, "opacity": 1}],
            "protected_zones": [{"id": "face", "x0": .7, "y0": .25, "x1": .9, "y1": .65}],
            "cropped": False, "caption_occluded": False,
        }]}, templates)
        codes = {row["code"] for row in report["findings"]}
        self.assertIn("platform_ui_collision", codes)
        self.assertIn("protected_region_collision", codes)
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
