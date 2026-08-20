from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class GuidedIntakeContractTests(unittest.TestCase):
    def test_skill_requires_one_batch_and_evidence_derived_type(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Start with one guided intake", skill)
        self.assertIn("ask once for only the missing items in one compact batch", skill)
        self.assertIn("Do not ask the user to classify the video", skill)
        self.assertIn("determine the effective input mode and content format", skill)
        self.assertIn("Do not repeat answered questions", skill)

    def test_new_source_cannot_bypass_sample_gate(self) -> None:
        protocol = (ROOT / "references" / "guided-intake.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("New or changed source: sample first", protocol)
        self.assertIn("Direct full rendering is accepted only as a", protocol)
        self.assertIn("resume operation", protocol)
        self.assertIn("does not approve a new full render", protocol)

    def test_defaults_remove_technical_prompt_burden(self) -> None:
        protocol = (ROOT / "references" / "guided-intake.md").read_text(
            encoding="utf-8"
        )
        for expected in (
            "video_id",
            "titles",
            "cover copy",
            "description",
            "topics",
            "canvas",
            "frame rate",
            "content format",
        ):
            self.assertIn(expected, protocol)
        self.assertIn("Natural-language answers are accepted", protocol)


if __name__ == "__main__":
    unittest.main()
