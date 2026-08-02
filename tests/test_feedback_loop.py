from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from feedback_loop import analyze_feedback_snapshots  # noqa: E402


class FeedbackLoopTests(unittest.TestCase):
    def test_non_finite_snapshot_metric_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = root / "first.json", root / "second.json"
            self._write_snapshot(first, "2026-08-02T00:00:00Z", 10, 0.3)
            self._write_snapshot(second, "2026-08-03T00:00:00Z", 20, 0.3)
            data = json.loads(second.read_text(encoding="utf-8"))
            data["metrics"]["average_watch_seconds"] = float("nan")
            second.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-negative"):
                analyze_feedback_snapshots([first, second], root / "out.json")

    def _write_snapshot(self, path: Path, observed_at: str, views: int, completion: float,
                        *, release_hash: str = "a" * 64) -> None:
        path.write_text(json.dumps({
            "schema_version": 1,
            "platform": "douyin",
            "published_at": "2026-07-20T00:00:00Z",
            "observed_at": observed_at,
            "binding": {
                "publication_id": "pub-1",
                "release_manifest_sha256": release_hash,
                "video_sha256": "b" * 64,
            },
            "metrics": {"views": views, "completion_rate": completion, "shares": 2},
        }), encoding="utf-8")

    def test_multi_snapshot_report_is_time_and_release_bound_and_advisory_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = root / "first.json", root / "second.json"
            self._write_snapshot(first, "2026-07-20T02:00:00Z", 120, 0.35)
            self._write_snapshot(second, "2026-07-22T02:00:00Z", 500, 0.28)
            report = analyze_feedback_snapshots([second, first], root / "feedback.json",
                                                min_views=200, min_elapsed_hours=24)
            self.assertEqual(report["status"], "ready_for_review")
            self.assertEqual(report["recommendation_mode"], "suggestion_candidates_only")
            self.assertEqual(report["automatic_changes"], [])
            self.assertEqual(report["binding"]["publication_id"], "pub-1")
            self.assertTrue(report["suggestion_candidates"])
            self.assertEqual(report["preference_candidates"], [])
            self.assertFalse(report["eligible_for_preference_learning"])
            self.assertEqual(report["snapshots"][0]["source_name"], "first.json")

    def test_small_sample_is_explicit_and_binding_or_time_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = root / "first.json", root / "second.json"
            self._write_snapshot(first, "2026-07-20T01:00:00Z", 10, 0.3)
            self._write_snapshot(second, "2026-07-20T02:00:00Z", 20, 0.2)
            report = analyze_feedback_snapshots([first, second], root / "feedback.json")
            self.assertEqual(report["status"], "insufficient_evidence")
            self.assertFalse(report["sample_assessment"]["meets_minimum"])
            self.assertEqual(report["automatic_changes"], [])

            self._write_snapshot(second, "2026-07-20T00:30:00Z", 20, 0.2,
                                 release_hash="c" * 64)
            with self.assertRaisesRegex(ValueError, "binding"):
                analyze_feedback_snapshots([first, second], root / "bad.json")


if __name__ == "__main__":
    unittest.main()
