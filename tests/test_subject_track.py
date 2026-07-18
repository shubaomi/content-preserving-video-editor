from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_subject_track.py"
SPEC = importlib.util.spec_from_file_location("analyze_subject_track", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class SubjectTrackTests(unittest.TestCase):
    def test_smoothing_reduces_jump(self) -> None:
        result = MODULE.smooth_point((0.2, 0.4), (0.8, 0.4), 0.25)
        self.assertAlmostEqual(result[0], 0.35)

    def test_crop_stays_inside_source(self) -> None:
        crop = MODULE.crop_box((0.98, 0.4), 1920, 1080, 9 / 16)
        self.assertLessEqual(crop["x1"], 1.0)
        self.assertGreaterEqual(crop["x0"], 0.0)

    def test_primary_prefers_near_previous_subject(self) -> None:
        boxes = [(10, 10, 100, 100), (700, 10, 120, 120)]
        chosen = MODULE.choose_primary(boxes, (0.1, 0.1), 1000, 1000)
        self.assertEqual(chosen, boxes[0])


if __name__ == "__main__":
    unittest.main()
