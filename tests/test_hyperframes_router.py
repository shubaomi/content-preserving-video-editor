from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hyperframes_router import route_hyperframes  # noqa: E402


class HyperFramesRouterTests(unittest.TestCase):
    def test_task_specific_routes_are_evidence_driven(self) -> None:
        self.assertEqual(route_hyperframes({}, {"content_type": "talking_head"})["route"],
                         "talking-head-recut")
        self.assertEqual(route_hyperframes({}, {"content_type": "interview"})["route"],
                         "talking-head-recut")
        self.assertEqual(route_hyperframes({}, {"task": "captions_only"})["route"],
                         "embedded-captions")
        self.assertEqual(route_hyperframes({}, {"task": "standalone_motion"})["route"],
                         "motion-graphics")
        self.assertEqual(route_hyperframes({}, {"content_type": "screen_tutorial"})["route"],
                         "general-video")

    def test_default_is_general_video_and_semantic_authority_stays_with_director(self) -> None:
        result = route_hyperframes({}, {})
        self.assertEqual(result["route"], "general-video")
        self.assertEqual(result["semantic_selection_owner"], "director_with_llm")
        self.assertFalse(result["fixed_card_count"])
        self.assertFalse(result["density_formula_authority"])

    def test_remotion_requires_explicit_enable_and_react_component_evidence(self) -> None:
        denied = route_hyperframes({"renderer": {"remotion": {"enabled": True}}}, {})
        self.assertEqual(denied["renderer"], "hyperframes")
        self.assertIn("missing React", denied["renderer_reason"])
        selected = route_hyperframes({"renderer": {"remotion": {
            "enabled": True, "react_component_paths": ["brand/Title.tsx"],
            "selected_event_ids": ["event-2"],
        }}}, {})
        self.assertEqual(selected["renderer"], "hyperframes")
        self.assertEqual(selected["optional_event_renderer"], "remotion")
        self.assertEqual(selected["remotion_event_ids"], ["event-2"])
        self.assertTrue(selected["license_boundary"])


if __name__ == "__main__":
    unittest.main()
