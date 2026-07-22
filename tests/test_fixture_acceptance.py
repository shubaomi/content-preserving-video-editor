from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fixture_acceptance import CHECK_NAMES, IMPLEMENTATION_DEPENDENCIES, REQUIRED_TYPES, evaluate_suite  # noqa: E402
from director_contracts import sha256_file  # noqa: E402


class FixtureAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(
            (ROOT / "tests" / "fixtures" / "acceptance-scenarios.json").read_text(encoding="utf-8")
        )

    def test_all_six_video_types_pass_shared_acceptance_gates(self) -> None:
        fixture_path = ROOT / "tests" / "fixtures" / "acceptance-scenarios.json"
        report = evaluate_suite(self.payload, fixture_source=fixture_path)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["scenario_count"], 6)
        self.assertEqual({row["fixture_type"] for row in report["scenarios"]}, REQUIRED_TYPES)
        self.assertTrue(all([check["name"] for check in row["checks"]] == list(CHECK_NAMES)
                            for row in report["scenarios"]))
        self.assertEqual(report["fixture_source_sha256"], sha256_file(fixture_path))
        self.assertEqual(report["implementation_sha256"], sha256_file(
            ROOT / "scripts" / "fixture_acceptance.py"
        ))
        self.assertTrue(all(row.get("scenario_evidence_sha256")
                            for row in report["scenarios"]))
        self.assertEqual(report["implementation_dependencies"], {
            path.resolve().relative_to(ROOT.resolve()).as_posix(): sha256_file(path)
            for path in IMPLEMENTATION_DEPENDENCIES
        })
        self.assertEqual(report["fixture_source"], "tests/fixtures/acceptance-scenarios.json")
        self.assertEqual(report["implementation"], "scripts/fixture_acceptance.py")

    def test_seeded_semantic_and_geometry_defects_fail_closed(self) -> None:
        payload = copy.deepcopy(self.payload)
        broken = payload["scenarios"][0]
        broken["semantic"]["events"][0]["anchor"] = "打开"
        broken["geometry"]["overflow_count"] = 1
        report = evaluate_suite(payload)
        self.assertEqual(report["status"], "failed")
        failed = {row["name"] for row in report["scenarios"][0]["checks"]
                  if row["status"] == "failed"}
        self.assertIn("semantic_relevance", failed)
        self.assertIn("geometry_occlusion_crop_whitespace", failed)

    def test_duplicate_fixture_type_or_empty_scenario_set_fails_closed(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["scenarios"][1]["fixture_type"] = payload["scenarios"][0]["fixture_type"]
        report = evaluate_suite(payload)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["duplicate_types"])
        empty = evaluate_suite({"scenarios": []})
        self.assertEqual(empty["status"], "failed")
        self.assertEqual(empty["scenario_count"], 0)


if __name__ == "__main__":
    unittest.main()
