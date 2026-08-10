from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_motion_snapshot_plan.py"
SPEC = importlib.util.spec_from_file_location("build_motion_snapshot_plan", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class MotionSnapshotPlanTests(unittest.TestCase):
    def test_every_beat_has_four_ordered_phases(self) -> None:
        storyboard = {
            "composition": {"durationSeconds": 20, "width": 1920, "height": 1080},
            "cards": [{"id": "card-a", "startSec": 2, "endSec": 8, "editableLayer": "#card-a .surface"}],
        }
        plan = MODULE.build_plan(storyboard)
        points = plan["beats"][0]["snapshots"]
        self.assertEqual(list(points), ["entrance", "midpoint", "pre_exit", "post_exit"])
        self.assertLess(points["entrance"], points["midpoint"])
        self.assertLess(points["midpoint"], points["pre_exit"])
        self.assertLess(points["pre_exit"], points["post_exit"])

    def test_post_exit_is_clamped_to_composition(self) -> None:
        points = MODULE.snapshot_points({"start": 18.0, "end": 20.0}, composition_duration=20.0)
        self.assertLess(points["post_exit"], 20.0)
        self.assertLessEqual(points["post_exit"], 19.88)

    def test_nested_composition_duration_clamps_final_event(self) -> None:
        plan = MODULE.build_plan({
            "composition": {"duration": 20.0},
            "events": [{"id": "outro", "start": 18.0, "end": 20.0}],
        })
        self.assertEqual(plan["composition"]["duration"], 20.0)
        self.assertLess(plan["beats"][0]["snapshots"]["post_exit"], 20.0)

    def test_sidecar_asserts_appearance_bounds_and_order(self) -> None:
        storyboard = {
            "composition": {"durationSeconds": 20},
            "cards": [
                {"id": "a", "startSec": 1, "endSec": 4},
                {"id": "b", "startSec": 6, "endSec": 9},
            ],
        }
        sidecar = MODULE.build_motion_sidecar(MODULE.build_plan(storyboard))
        kinds = [item["kind"] for item in sidecar["assertions"]]
        self.assertEqual(kinds.count("appearsBy"), 2)
        self.assertEqual(kinds.count("staysInFrame"), 2)
        self.assertEqual(kinds.count("before"), 1)

    def test_dynamic_attention_events_are_supported_directly(self) -> None:
        plan = MODULE.build_plan({
            "duration": 12.0,
            "events": [{
                "id": "motion-001", "start": 2.0, "end": 4.0,
                "tier": "meso", "visual_family": "structure",
                "safe_zone": "top_right", "layout_selector": "#motion-001 .event-host",
            }],
        })
        self.assertEqual(plan["composition"]["duration"], 12.0)
        self.assertEqual(plan["beats"][0]["selector"], "#motion-001 .event-host")
        self.assertEqual(plan["beats"][0]["safe_zone"], "top_right")

    def test_target_bound_event_snapshots_use_its_active_geometry_window(self) -> None:
        plan = MODULE.build_plan({
            "duration": 20.0,
            "events": [{
                "id": "target-overlay", "start": 2.0, "end": 18.0,
                "geometry_contract": {"target_region_contract": {
                    "active_selector": "#target-overlay .target",
                    "active_output_start": 10.0,
                    "active_output_end": 14.0,
                }},
            }],
        })

        beat = plan["beats"][0]
        self.assertEqual(beat["event_start"], 2.0)
        self.assertEqual(beat["event_end"], 18.0)
        self.assertEqual(beat["start"], 10.0)
        self.assertEqual(beat["end"], 14.0)
        self.assertEqual(beat["selector"], "#target-overlay .target")
        self.assertGreaterEqual(beat["snapshots"]["entrance"], 10.0)
        self.assertLessEqual(beat["snapshots"]["pre_exit"], 14.0)

    def test_target_region_sidecar_checks_each_declared_target(self) -> None:
        plan = MODULE.build_plan({
            "duration": 12.0,
            "events": [{
                "id": "target-overlay", "start": 2.0, "end": 10.0,
                "geometry_contract": {"target_region_contract": {
                    "active_selector": "#target-overlay .primary-target",
                    "active_output_start": 4.0,
                    "active_output_end": 8.0,
                    "target_ids": ["primary-target", "secondary-target"],
                }},
            }],
        })

        assertions = MODULE.build_motion_sidecar(plan)["assertions"]
        selectors = {row["selector"] for row in assertions if "selector" in row}
        self.assertIn(
            '#target-overlay [data-hf-id="primary-target"]', selectors,
        )
        self.assertIn(
            '#target-overlay [data-hf-id="secondary-target"]', selectors,
        )


if __name__ == "__main__":
    unittest.main()
