from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from review_dashboard import generate_dashboard  # noqa: E402


class ReviewDashboardTests(unittest.TestCase):
    def test_static_readonly_dashboard_exposes_required_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            director = root / "work" / "director"
            director.mkdir(parents=True)
            (director / "director-state.json").write_text(json.dumps({
                "status": "action_required", "current_stage": "sample_qa",
                "stages": {"sample_qa": {"status": "action_required"}},
            }), encoding="utf-8")
            for name in ("production-contract.json", "provider-decision.json", "cost-ledger.json"):
                (director / name).write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
            snapshot = director / "sample-qa" / "event-entrance.png"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_bytes(b"png")
            output = director / "review" / "index.html"
            generate_dashboard(project_root=root, director_root=director, output=output)
            html = output.read_text(encoding="utf-8")
            for label in ("Production Contract", "Visual Dynamics QA", "Provider Decision",
                          "Cost Ledger", "Correction Ledger", "Universal MP4",
                          "entrance", "sample_qa", "action_required"):
                self.assertIn(label, html)
            self.assertIn("Read-only", html)


if __name__ == "__main__":
    unittest.main()
