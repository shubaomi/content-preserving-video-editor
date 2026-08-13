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

    def test_dashboard_links_pending_only_portrait_style_reel(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            director = root / "work" / "director"
            director.mkdir(parents=True)
            (director / "director-state.json").write_text(
                json.dumps({"status": "active", "stages": {}}), encoding="utf-8",
            )
            style = director / "review" / "portrait-style-review.html"
            style.parent.mkdir(parents=True)
            style.write_text("<!doctype html>", encoding="utf-8")
            output = director / "review" / "index.html"
            generate_dashboard(
                project_root=root, director_root=director, output=output,
                style_reel_dashboard_path=style,
            )
            document = output.read_text(encoding="utf-8")
            self.assertIn("HongRun portrait Style Reel", document)
            self.assertIn(style.resolve().as_uri(), document)
            self.assertIn("pending-only", document)

    def test_interactive_dashboard_uses_auto_session_without_user_key_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            director = root / "work" / "director"
            director.mkdir(parents=True)
            (director / "director-state.json").write_text(
                json.dumps({"status": "active", "stages": {}}), encoding="utf-8",
            )
            review = director / "creative-review.json"
            contract = director / "motion-design-contract.json"
            review.write_text(json.dumps({"event_comparisons": []}), encoding="utf-8")
            contract.write_text(json.dumps({"events": []}), encoding="utf-8")
            output = director / "review" / "index.html"
            generate_dashboard(
                project_root=root,
                director_root=director,
                output=output,
                creative_review_path=review,
                motion_design_contract_path=contract,
                interactive_api_url="http://127.0.0.1:8765/api/proposals",
                interactive_session={"authorization": "ephemeral-a", "csrf": "ephemeral-c"},
            )
            document = output.read_text(encoding="utf-8")
            self.assertIn("ephemeral-a", document)
            self.assertIn("ephemeral-c", document)
            self.assertNotIn("DIRECTOR_REVIEW_TOKEN", document)
            self.assertNotIn("DIRECTOR_REVIEW_CSRF_TOKEN", document)
            self.assertNotIn("window.prompt", document)


if __name__ == "__main__":
    unittest.main()
