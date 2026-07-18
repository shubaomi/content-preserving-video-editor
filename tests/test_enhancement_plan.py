from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_enhancement_plan.py"
SPEC = importlib.util.spec_from_file_location("build_enhancement_plan", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class EnhancementPlanTests(unittest.TestCase):
    def test_plan_uses_complete_transcript_segments(self) -> None:
        analysis = {
            "captions": {"add_caption_layer": False},
            "audio": {"add_bgm": False},
            "enhancement_budget": {"beats": [{"timestamp": value} for value in (30, 90, 150)]},
        }
        segments = [
            {"start": 25, "end": 29, "text": "因为这是第一个完整观点。"},
            {"start": 85, "end": 89, "text": "关键是保留原有语义。"},
            {"start": 145, "end": 149, "text": "最后给出清楚的结论。"},
        ]
        plan = MODULE.build_plan(
            analysis,
            segments,
            glossary=["完整观点", "原有语义", "清楚的结论"],
        )
        self.assertEqual(len(plan["beats"]), 3)
        self.assertFalse(plan["constraints"]["add_caption_layer"])
        self.assertEqual(plan["beats"][1]["message"], "关键是保留原有语义。")


if __name__ == "__main__":
    unittest.main()
