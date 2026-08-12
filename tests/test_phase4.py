from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


PREFERENCES = load("motion_preferences")
HOOK = load("audit_hook_pacing")
COPY = load("generate_publishing_copy")


class Phase4Tests(unittest.TestCase):
    def test_preferences_require_approval_and_provenance(self):
        profile = PREFERENCES.load(Path("missing.json"))
        with self.assertRaises(ValueError):
            PREFERENCES.record(profile, "global", None, {"density": "sparse"}, "approved edit", False)
        with self.assertRaises(ValueError):
            PREFERENCES.record(profile, "global", None, {"density": "sparse"}, None, True)

    def test_preferences_apply_across_projects_but_yield_to_safety(self):
        profile = PREFERENCES.load(Path("missing.json"))
        PREFERENCES.record(profile, "global", None, {"density": "sparse", "scale": 1.2}, "approved tabout final", True)
        PREFERENCES.record(profile, "content_type", "screen_tutorial", {"position": "right"}, "approved tabout final", True)
        first = PREFERENCES.apply(profile, "screen_tutorial", "project-a", {"forbidden_positions": ["right"], "fallback_position": "left", "max_scale": 1.0})
        second = PREFERENCES.apply(profile, "screen_tutorial", "project-b", {"forbidden_positions": [], "max_scale": 1.1})
        self.assertEqual(first["preferences"]["position"], "left")
        self.assertEqual(first["preferences"]["scale"], 1.0)
        self.assertEqual(second["preferences"]["position"], "right")
        self.assertEqual(second["preferences"]["scale"], 1.1)
        self.assertEqual(len(profile["history"]), 2)
        profile["enabled"] = False
        self.assertFalse(PREFERENCES.apply(profile, "screen_tutorial", "project-c")["enabled"])

    def test_hook_audit_separates_measurement_and_judgment(self):
        transcript = {"segments": [
            {"start": 2.0, "end": 4.0, "text": "今天分享一个关键功能"},
            {"start": 35.0, "end": 38.0, "text": "这是具体效果"},
        ]}
        result = HOOK.audit(transcript, {"visual_analysis": {"monotony_candidates": [{"timestamp": 30}]}})
        self.assertIn("measurements", result)
        self.assertTrue(result["heuristic_judgments"]["heuristic_only"])
        self.assertTrue(result["preserve_mode_edl_unchanged"])
        self.assertIn("conclusions", result["forbidden_automatic_deletions"])
        self.assertTrue(all("evidence" in item and "timestamp" in item for item in result["suggestions"]))

    def test_publishing_copy_is_evidence_linked_and_platform_adapted(self):
        transcript = {"segments": [
            {"start": 1.0, "end": 4.0, "text": "这个功能可以帮助我们快速整理标签页"},
            {"start": 30.0, "end": 35.0, "text": "关键是它保留了原来的页面上下文"},
            {"start": 61.0, "end": 66.0, "text": "最后我建议先从一个小场景开始使用"},
        ]}
        result = COPY.build("TabOut 浏览器插件", transcript, ["TabOut"])
        self.assertNotEqual(result["douyin"]["adaptation"], result["wechat_channels"]["adaptation"])
        self.assertLessEqual(len(result["douyin"]["recommended"]["title"]), 32)
        for platform in (result["douyin"], result["wechat_channels"]):
            self.assertGreaterEqual(len(platform["alternatives"]), 2)
            self.assertEqual(platform["external_action_gate"], "Publishing/upload requires explicit user action.")
            self.assertTrue(all(claim["evidence"]["type"] == "transcript" for claim in platform["claims"]))
            self.assertIn("no performance", platform["claim_policy"].lower())

    def test_publishing_copy_binds_to_promise_without_forcing_identical_wording(self):
        transcript = {"segments": [
            {"start": 1.0, "end": 4.0, "text": "这个方法能够减少重复工作"},
        ]}
        ledger = {
            "promise_id": "promise-1",
            "single_promise": {"proof_event_ids": ["semantic-1"]},
        }
        result = COPY.build("减少重复工作的方法", transcript, ["工作流"], ledger)
        binding = result["promise_binding"]
        self.assertEqual(binding["promise_id"], "promise-1")
        self.assertTrue(all(row["proof_event_ids"] == ["semantic-1"] for row in binding["surfaces"]))
        self.assertGreater(len({row["copy"] for row in binding["surfaces"]}), 1)

    def test_cover_ab_reports_distinct_strategies_without_performance_claim(self):
        text = (ROOT / "scripts" / "build_cover_ab.py").read_text(encoding="utf-8")
        self.assertIn("communication_strategies_are_distinct", text)
        self.assertIn("performance_claim", text)
        self.assertIn("inherits authorized source-photo provenance", text)


if __name__ == "__main__":
    unittest.main()
