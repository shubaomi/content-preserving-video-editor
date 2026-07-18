from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("safe_zones", ROOT / "scripts" / "select_motion_safe_zones.py")
SAFE_ZONES = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(SAFE_ZONES)


class SafeZoneSelectorTests(unittest.TestCase):
    def test_avoids_visually_occupied_top_left(self):
        image = Image.new("RGB", (960, 540), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 70, 330, 190), fill="black")
        selected, scores = SAFE_ZONES.select_zone(image, "meso")
        self.assertNotEqual(selected, "top_left")
        self.assertGreater(scores["top_left"], scores[selected])

    def test_apply_records_reviewable_geometry_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "frame.jpg"
            Image.new("RGB", (960, 540), "white").save(frame)
            plan = {"events": [{
                "id": "event-1", "start": 1, "tier": "micro",
                "collision_check": {"evidence": "frame.jpg"},
            }]}
            result = SAFE_ZONES.apply(plan, root)
            evidence = result["events"][0]["collision_check"]["evidence"]
            self.assertIn(result["events"][0]["safe_zone"], SAFE_ZONES.ZONE_ORIGINS)
            self.assertEqual(evidence["selected"], result["events"][0]["safe_zone"])
            self.assertEqual(len(evidence["scores"]), 6)


if __name__ == "__main__":
    unittest.main()
