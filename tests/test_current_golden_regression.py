from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from current_golden_regression import build_report, validate_report  # noqa: E402


class CurrentGoldenRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = ROOT / "tests" / "fixtures" / "acceptance-scenarios.json"
        self.policy = ROOT / "tests" / "fixtures" / "current-golden-policy.json"

    def test_current_suite_is_bound_to_source_policy_implementation_and_versions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report_path = Path(folder) / "golden.json"
            report = build_report(self.fixtures, self.policy, report_path)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(len(report["cases"]), 6)
            self.assertEqual(validate_report(report_path, self.fixtures, self.policy), [])
            self.assertTrue(report["bindings"]["director_version"])
            self.assertGreaterEqual(report["bindings"]["project_schema_version"], 8)
            self.assertTrue(report["bindings"]["implementation_sha256"])

    def test_tamper_missing_and_expired_reports_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report_path = Path(folder) / "golden.json"
            report = build_report(self.fixtures, self.policy, report_path)
            report["cases"][0]["checks"][0]["status"] = "failed"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.assertTrue(validate_report(report_path, self.fixtures, self.policy))
            report = build_report(self.fixtures, self.policy, report_path)
            report["generated_at"] = (
                datetime.now(timezone.utc) - timedelta(days=400)
            ).isoformat()
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.assertTrue(any("expired" in error for error in validate_report(
                report_path, self.fixtures, self.policy,
            )))
            report_path.unlink()
            self.assertTrue(validate_report(report_path, self.fixtures, self.policy))

    def test_wrong_semantics_layout_or_caption_drift_is_rejected(self) -> None:
        payload = json.loads(self.fixtures.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            policy = root / "policy.json"
            policy.write_bytes(self.policy.read_bytes())
            for index, mutation in enumerate(("semantic", "layout", "caption")):
                changed = copy.deepcopy(payload)
                if mutation == "semantic":
                    changed["scenarios"][0]["semantic"]["events"][0]["anchor"] = "打开"
                elif mutation == "layout":
                    changed["scenarios"][0]["geometry"]["overflow_count"] = 1
                else:
                    changed["scenarios"][0]["captions"]["max_sync_error_seconds"] = 0.8
                source = root / f"fixtures-{index}.json"
                source.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                report_path = root / f"report-{index}.json"
                report = build_report(source, policy, report_path)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(validate_report(report_path, source, policy))


if __name__ == "__main__":
    unittest.main()
