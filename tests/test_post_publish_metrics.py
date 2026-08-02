from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from post_publish_metrics import import_metrics  # noqa: E402


class PostPublishMetricsTests(unittest.TestCase):
    def test_non_finite_metrics_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "metrics.json"
            for value in (float("nan"), float("inf"), float("-inf")):
                source.write_text(json.dumps({
                    "platform": "douyin", "published_at": "2026-08-01T00:00:00Z",
                    "metrics": {"average_watch_seconds": value},
                }), encoding="utf-8")
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                    import_metrics(source, root / "out.json")

    def test_import_is_hash_bound_and_never_claims_platform_api_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "douyin-export.json"
            source.write_text(json.dumps({
                "platform": "douyin", "published_at": "2026-07-20T10:00:00Z",
                "metrics": {"views": 1200, "completion_rate": 0.31},
            }), encoding="utf-8")
            output = root / "metrics.json"
            report = import_metrics(source, output)
            self.assertEqual(report["acquisition"], "user_supplied_export")
            self.assertFalse(report["platform_api_claimed"])
            self.assertTrue(report["source_sha256"])
            self.assertIsNone(report["binding"])

    def test_bound_import_records_exact_release_cover_copy_motion_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "export.json"
            source.write_text(json.dumps({
                "platform": "douyin", "published_at": "2026-07-20T10:00:00Z",
                "observed_at": "2026-07-21T10:00:00Z", "metrics": {"views": 500},
            }), encoding="utf-8")
            binding = {
                "publication_id": "pub-1", "version_id": "v1",
                "release_manifest_sha256": "a" * 64, "video_sha256": "b" * 64,
                "cover_sha256": "c" * 64, "publishing_copy_sha256": "d" * 64,
                "motion_structure_sha256": "e" * 64,
            }
            report = import_metrics(source, root / "bound.json", binding=binding)
            self.assertEqual(report["binding"], binding)
            self.assertEqual(report["observed_at"], "2026-07-21T10:00:00Z")

    def test_unknown_or_out_of_range_metrics_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bad.json"
            source.write_text(json.dumps({
                "platform": "douyin", "published_at": "2026-07-20T10:00:00Z",
                "metrics": {"completion_rate": 1.5, "magic_score": 99},
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                import_metrics(source, root / "out.json")


if __name__ == "__main__":
    unittest.main()
