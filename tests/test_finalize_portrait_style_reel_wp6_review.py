from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from finalize_portrait_style_reel_wp6_review import (  # noqa: E402
    DIRECTION_QA, PHASE_SOURCE_NAMES, _copy_phase_evidence,
)
from portrait_style_reel import PHASES, _file_ref, _phase_structure_observation  # noqa: E402


class FinalizePortraitStyleReelWp6ReviewTests(unittest.TestCase):
    def test_real_phase_evidence_is_candidate_minus_same_time_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direction = "luminous_intelligence"
            event_id = "event-1"
            timestamps = ("0.70", "4.80", "9.20", "10.30")
            for index, (source_name, timestamp) in enumerate(
                zip(PHASE_SOURCE_NAMES, timestamps, strict=True)
            ):
                raw = root / "hyperframes" / direction / "phase-snapshots" / source_name
                raw.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (544, 960), "black").save(raw)
                baseline = root / "qa" / "final" / "baseline-captioned" / f"at-{timestamp}.png"
                candidate = root / "qa" / "final" / DIRECTION_QA[direction] / f"at-{timestamp}.png"
                baseline.parent.mkdir(parents=True, exist_ok=True)
                candidate.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (544, 960), (24, 31, 38)).save(baseline)
                image = Image.new("RGB", (544, 960), (24, 31, 38))
                if index < 3:
                    draw = ImageDraw.Draw(image)
                    draw.rectangle(
                        (40 + index * 20, 520, 460, 650 + index * 30),
                        outline=(235, 255, 245), width=18,
                    )
                image.save(candidate)

            paths = _copy_phase_evidence(
                style_root=root, direction_id=direction, event_id=event_id,
            )
            self.assertEqual(4, len(paths))
            self.assertTrue(all(path.is_file() for path in paths))
            fingerprint, masks = _phase_structure_observation(
                [_file_ref(path) for path in paths], direction,
            )
            self.assertEqual(64, len(fingerprint))
            self.assertEqual(len(PHASES), len(masks))
            self.assertLess(
                sum(1 for value in masks[-1] if value),
                sum(1 for value in masks[1] if value) * 0.35,
            )


if __name__ == "__main__":
    unittest.main()
