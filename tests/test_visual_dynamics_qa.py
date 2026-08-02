from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from visual_dynamics_qa import build_report, validate_report  # noqa: E402


def event(identifier: str, anchor: str, start: float, family: str) -> dict:
    return {
        "id": identifier,
        "anchor": anchor,
        "start": start,
        "end": start + 4,
        "treatment": family,
        "viewer_takeaway": f"理解{anchor}",
        "relevance_rationale": "把口播中的抽象关系转成可见结构",
        "visual_mechanism": "用结构关系而不是重复字幕来解释",
        "transcript_quote": f"这里解释{anchor}背后的关系",
        "motion": {"entrance": "fade", "reveal": "draw", "hold": "hold", "exit": "fade"},
        "visual_structure": {
            "dom_structure": identifier + "-dom",
            "information_hierarchy": identifier + "-hierarchy",
            "layout_archetype": family,
            "animation_choreography": identifier + "-motion",
            "use_case": identifier + "-case",
        },
    }


class VisualDynamicsQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storyboard = self.root / "storyboard.json"
        self.brief = self.root / "semantic-brief.json"
        self.contract = self.root / "production-contract.json"
        self.contract.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        self.project = {"qa": {"visual_dynamics": {
            "enabled": True,
            "blocking": True,
            "maximum_family_ratio": 0.65,
            "maximum_unexplained_gap_seconds": 30.0,
            "minimum_useful_content_ratio": 0.2,
        }}}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, events: list[dict]) -> None:
        payload = {"composition": {"duration": 80}, "events": events}
        self.storyboard.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.brief.write_text(json.dumps({"events": events}, ensure_ascii=False), encoding="utf-8")

    def test_four_meaningful_distinct_events_pass(self) -> None:
        self._write([
            event("e1", "请求入口", 5, "ui-focus"),
            event("e2", "三步处理", 20, "process-path"),
            event("e3", "方案对比", 40, "comparison"),
            event("e4", "最终结果", 60, "numeric-result"),
        ])

        report = build_report(
            storyboard_path=self.storyboard,
            semantic_brief_path=self.brief,
            config=self.project["qa"]["visual_dynamics"],
            production_contract_path=self.contract,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(validate_report(
            report, self.storyboard, self.brief,
            config=self.project["qa"]["visual_dynamics"],
            production_contract_path=self.contract,
        ), [])

    def test_many_random_low_information_events_fail_instead_of_earning_density_credit(self) -> None:
        events = [event(f"e{i}", "打开", i * 6.0, "keyword-card") for i in range(10)]
        self._write(events)

        report = build_report(
            storyboard_path=self.storyboard,
            semantic_brief_path=self.brief,
            config=self.project["qa"]["visual_dynamics"],
            production_contract_path=self.contract,
        )

        self.assertEqual(report["status"], "failed")
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("low_information_anchor", codes)
        self.assertIn("visual_family_repetition", codes)

    def test_report_is_invalid_after_storyboard_hash_drift(self) -> None:
        self._write([
            event("e1", "请求入口", 5, "ui-focus"),
            event("e2", "三步处理", 20, "process-path"),
            event("e3", "方案对比", 40, "comparison"),
            event("e4", "最终结果", 60, "numeric-result"),
        ])
        report = build_report(
            storyboard_path=self.storyboard,
            semantic_brief_path=self.brief,
            config=self.project["qa"]["visual_dynamics"],
            production_contract_path=self.contract,
        )
        self.storyboard.write_text('{"events":[]}', encoding="utf-8")

        errors = validate_report(
            report, self.storyboard, self.brief,
            config=self.project["qa"]["visual_dynamics"],
            production_contract_path=self.contract,
        )

        self.assertTrue(any("storyboard hash" in error for error in errors))

    def test_report_rejects_config_contract_and_integrity_drift(self) -> None:
        self._write([
            event("e1", "请求入口", 5, "ui-focus"),
            event("e2", "三步处理", 20, "process-path"),
            event("e3", "方案对比", 40, "comparison"),
            event("e4", "最终结果", 60, "numeric-result"),
        ])
        config = self.project["qa"]["visual_dynamics"]
        report = build_report(
            storyboard_path=self.storyboard, semantic_brief_path=self.brief,
            config=config, production_contract_path=self.contract,
        )
        report["metrics"]["distinct_visual_families"] = 99
        self.contract.write_text(json.dumps({"schema_version": 1, "changed": True}), encoding="utf-8")

        errors = validate_report(
            report, self.storyboard, self.brief,
            config={**config, "maximum_family_ratio": 0.5},
            production_contract_path=self.contract,
        )

        self.assertTrue(any("configuration" in error for error in errors))
        self.assertTrue(any("production_contract hash" in error for error in errors))
        self.assertTrue(any("integrity" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
