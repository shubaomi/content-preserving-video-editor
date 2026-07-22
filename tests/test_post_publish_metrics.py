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
