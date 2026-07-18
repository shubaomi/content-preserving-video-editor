from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from aesthetic_qa import (  # noqa: E402
    HUMAN_ANATOMY_CRITERION,
    REQUIRED_ANATOMY_CHECKS,
    REQUIRED_CRITERIA,
    REQUIRED_PHASES,
    validate,
)


def structure(name: str) -> dict:
    return {
        "dom_structure": name + "-dom",
        "information_hierarchy": name + "-hierarchy",
        "layout_archetype": name,
        "animation_choreography": name + "-motion",
        "use_case": name + "-case",
    }


class AestheticQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        events = [{"id": f"e{i}", "visual_structure": structure(f"s{i}")} for i in range(4)]
        self.storyboard = {"events": events}
        snapshots = {}
        for event in events:
            snapshots[event["id"]] = {}
            for phase in REQUIRED_PHASES:
                path = root / f"{event['id']}-{phase}.png"
                path.write_bytes(b"png")
                snapshots[event["id"]][phase] = str(path)
        self.review = {
            "verdict": "pass",
            "reviewed_event_ids": [event["id"] for event in events],
            "criteria": {name: {"status": "pass", "evidence": ["review-note"]}
                         for name in REQUIRED_CRITERIA},
            "technical_qa": {name: {"status": "pass"}
                             for name in ("hyperframes_check", "caption_sync", "overlap", "overflow", "decode")},
            "snapshots": snapshots,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_complete_evidence_backed_review_passes(self) -> None:
        self.assertEqual(validate(self.review, self.storyboard), [])

    def test_tests_cannot_replace_missing_aesthetic_criterion(self) -> None:
        del self.review["criteria"][REQUIRED_CRITERIA[0]]
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("missing aesthetic criterion" in error for error in errors))

    def test_missing_motion_phase_is_blocking(self) -> None:
        del self.review["snapshots"]["e0"]["post_exit"]
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("post_exit snapshot" in error for error in errors))

    def test_human_asset_requires_anatomy_evidence_and_checks(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        errors = validate(self.review, self.storyboard)
        self.assertIn(f"missing aesthetic criterion: {HUMAN_ANATOMY_CRITERION}", errors)

    def test_complete_human_anatomy_review_passes(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        root = Path(self.temp.name)
        evidence = []
        for name in ("full", "left-hand", "right-hand"):
            path = root / f"anatomy-{name}.png"
            path.write_bytes(b"png")
            evidence.append(str(path))
        self.review["criteria"][HUMAN_ANATOMY_CRITERION] = {
            "status": "pass",
            "evidence": evidence,
            "checks": {name: True for name in REQUIRED_ANATOMY_CHECKS},
        }
        self.assertEqual(validate(self.review, self.storyboard), [])

    def test_declared_connector_contract_requires_per_event_geometry_evidence(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "connector_contract": {
                "required_connector_count": 3,
                "relations": ["source->a", "source->b", "source->c"],
            }
        }
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("connector geometry review" in error for error in errors))

    def test_complete_connector_geometry_review_passes(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "connector_contract": {
                "required_connector_count": 3,
                "relations": ["source->a", "source->b", "source->c"],
            }
        }
        evidence = Path(self.temp.name) / "e0-connectors.png"
        evidence.write_bytes(b"png")
        self.review["connector_geometry"] = {
            "e0": {
                "status": "pass",
                "required_connector_count": 3,
                "observed_connector_count": 3,
                "all_endpoints_attached": True,
                "optically_aligned": True,
                "no_clipped_paths": True,
                "evidence": str(evidence),
            }
        }
        self.assertEqual(validate(self.review, self.storyboard), [])


if __name__ == "__main__":
    unittest.main()
