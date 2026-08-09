from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from aesthetic_qa import (  # noqa: E402
    HUMAN_ANATOMY_CRITERION,
    REQUIRED_ANATOMY_CHECKS,
    REQUIRED_CRITERIA,
    REQUIRED_PHASES,
    validate,
)
from director_contracts import sha256_file  # noqa: E402


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
                Image.new("RGB", (320, 180), "white").save(path)
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

    def test_corrupt_or_tiny_snapshot_cannot_fake_visual_review(self) -> None:
        corrupt = Path(self.review["snapshots"]["e0"]["midpoint"])
        corrupt.write_bytes(b"not-an-image")
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("midpoint snapshot evidence is not a decodable image" in error
                            for error in errors))

        Image.new("RGB", (8, 8), "white").save(corrupt)
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("midpoint snapshot evidence is too small" in error
                            for error in errors))

        Image.new("RGB", (128, 128), "white").save(corrupt)
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("midpoint snapshot evidence is too small" in error
                            for error in errors))

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
        for index, (name, role) in enumerate((
            ("full", "full_frame"),
            ("left-hand", "left_hand"),
            ("right-hand", "right_hand"),
        )):
            path = root / f"anatomy-{name}.png"
            Image.new("RGB", (512, 512), (230 - index * 20, 240, 245)).save(path)
            evidence.append({"path": str(path), "sha256": sha256_file(path), "role": role})
        self.review["criteria"][HUMAN_ANATOMY_CRITERION] = {
            "status": "pass",
            "evidence": evidence,
            "checks": {name: True for name in REQUIRED_ANATOMY_CHECKS},
        }
        self.assertEqual(validate(self.review, self.storyboard), [])

    def test_human_anatomy_evidence_requires_unique_roles_and_images(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        path = Path(self.temp.name) / "one-view.png"
        Image.new("RGB", (512, 512), "white").save(path)
        record = {"path": str(path), "sha256": sha256_file(path), "role": "full_frame"}
        self.review["criteria"][HUMAN_ANATOMY_CRITERION] = {
            "status": "pass",
            "evidence": [record, record, record],
            "checks": {name: True for name in REQUIRED_ANATOMY_CHECKS},
        }

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("roles" in error or "unique" in error for error in errors), errors)

    def test_required_anatomy_roles_cannot_borrow_an_extra_image_for_uniqueness(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        root = Path(self.temp.name)
        paths = []
        for index, color in enumerate(("white", "gray", "black")):
            path = root / f"role-{index}.png"
            Image.new("RGB", (512, 512), color).save(path)
            paths.append(path)
        evidence = [
            {"path": str(paths[0]), "sha256": sha256_file(paths[0]), "role": "full_frame"},
            {"path": str(paths[0]), "sha256": sha256_file(paths[0]), "role": "left_hand"},
            {"path": str(paths[1]), "sha256": sha256_file(paths[1]), "role": "right_hand"},
            {"path": str(paths[2]), "sha256": sha256_file(paths[2]), "role": "extra"},
        ]
        self.review["criteria"][HUMAN_ANATOMY_CRITERION] = {
            "status": "pass", "evidence": evidence,
            "checks": {name: True for name in REQUIRED_ANATOMY_CHECKS},
        }

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("unique role-specific" in error for error in errors), errors)

    def test_structured_visual_evidence_requires_a_matching_sha256(self) -> None:
        snapshot = Path(self.review["snapshots"]["e0"]["midpoint"])
        self.review["snapshots"]["e0"]["midpoint"] = {"path": str(snapshot)}

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("requires sha256" in error for error in errors), errors)

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
        Image.new("RGB", (320, 180), "white").save(evidence)
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
