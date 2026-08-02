from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from correction_ledger import append_correction, new_ledger  # noqa: E402
from editorial_regression import (  # noqa: E402
    create_baseline, evaluate_regression, validate_baseline, validate_regression,
)


def _story(events: list[dict]) -> dict:
    return {"renderer": "hyperframes", "events": events}


def _event(event_id: str, anchor: str, family: str) -> dict:
    return {
        "id": event_id, "anchor": anchor, "treatment": "structure",
        "visual_structure": {"layout_archetype": family},
        "audio_decision": {"type": "cue", "family": f"{family}-sfx"},
    }


class EditorialRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storyboard = self.root / "storyboard.json"
        self.brief = self.root / "brief.json"
        events = [_event("e1", "概念关系", "relation"), _event("e2", "步骤路径", "process")]
        self.storyboard.write_text(json.dumps(_story(events)), encoding="utf-8")
        self.brief.write_text(json.dumps({"events": events}), encoding="utf-8")
        self.baseline_path = self.root / "golden.json"
        self.baseline = create_baseline(
            storyboard_path=self.storyboard, semantic_brief_path=self.brief,
            audio_plan_path=None, cover_plan_path=None, correction_ledger_path=None,
            approved_by="hongr", output=self.baseline_path,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _evaluate(self, events: list[dict], ledger: Path | None = None) -> dict:
        current_story = self.root / "current-story.json"
        current_brief = self.root / "current-brief.json"
        current_story.write_text(json.dumps(_story(events)), encoding="utf-8")
        current_brief.write_text(json.dumps({"events": events}), encoding="utf-8")
        return evaluate_regression(
            baseline=self.baseline, storyboard_path=current_story,
            semantic_brief_path=current_brief, correction_ledger_path=ledger,
        )

    def test_matching_structured_decisions_pass(self) -> None:
        self.assertEqual(validate_baseline(self.baseline), [])
        report = self._evaluate([_event("e1", "概念关系", "relation"),
                                 _event("e2", "步骤路径", "process")])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(validate_regression(report), [])

    def test_repeated_motion_family_fails(self) -> None:
        report = self._evaluate([_event(f"e{i}", f"关键{i}", "same-card") for i in range(5)])
        self.assertEqual(report["status"], "failed")
        self.assertIn("repeated_motion_family", {row["code"] for row in report["findings"]})

    def test_random_low_information_keyword_fails(self) -> None:
        report = self._evaluate([_event("e1", "打开", "relation")])
        self.assertEqual(report["status"], "failed")
        self.assertIn("low_information_anchor", {row["code"] for row in report["findings"]})

    def test_removed_approved_event_and_connector_drift_fail(self) -> None:
        baseline_events = json.loads(self.storyboard.read_text(encoding="utf-8"))["events"]
        baseline_events[0]["geometry_contract"] = {"connector_contract": {
            "relations": [{"from": "a", "to": "b"}],
        }}
        self.storyboard.write_text(json.dumps(_story(baseline_events)), encoding="utf-8")
        self.brief.write_text(json.dumps({"events": baseline_events}), encoding="utf-8")
        self.baseline = create_baseline(
            storyboard_path=self.storyboard, semantic_brief_path=self.brief,
            audio_plan_path=None, cover_plan_path=None, correction_ledger_path=None,
            approved_by="hongr", output=self.baseline_path,
        )
        current = [_event("e1", "概念关系", "relation")]

        report = self._evaluate(current)
        codes = {row["code"] for row in report["findings"]}

        self.assertIn("approved_event_removed", codes)
        self.assertIn("unapproved_editorial_drift", codes)

    def test_approved_correction_allows_audited_change(self) -> None:
        ledger_path = self.root / "ledger.json"
        new_ledger(ledger_path, project_root=self.root)
        append_correction(
            ledger_path, event_id="e1", target_file=self.brief, selector="#e1",
            property_name="anchor", before_value="概念关系", after_value="系统关系",
            reason="user approved clearer wording", approved_by="hongr",
            approved_at="2026-07-30T12:00:00+00:00", related_files=[self.brief],
        )
        report = self._evaluate([
            _event("e1", "系统关系", "relation"), _event("e2", "步骤路径", "process")
        ], ledger_path)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approved_corrections_applied"], ["e1:anchor"])

    def test_approved_connector_correction_targets_current_full_storyboard(self) -> None:
        baseline_events = json.loads(self.storyboard.read_text(encoding="utf-8"))["events"]
        baseline_events[0]["geometry_contract"] = {"connector_contract": {
            "relations": [{"from": "a", "to": "b"}],
        }}
        self.storyboard.write_text(json.dumps(_story(baseline_events)), encoding="utf-8")
        self.brief.write_text(json.dumps({"events": baseline_events}), encoding="utf-8")
        self.baseline = create_baseline(
            storyboard_path=self.storyboard, semantic_brief_path=self.brief,
            audio_plan_path=None, cover_plan_path=None, correction_ledger_path=None,
            approved_by="hongr", output=self.baseline_path,
        )
        current_story = self.root / "current-story.json"
        current_brief = self.root / "current-brief.json"
        current_events = json.loads(json.dumps(baseline_events))
        current_events[0]["geometry_contract"]["connector_contract"]["relations"].append(
            {"from": "a", "to": "c"}
        )
        current_story.write_text(json.dumps(_story(current_events)), encoding="utf-8")
        current_brief.write_text(json.dumps({"events": current_events}), encoding="utf-8")
        ledger_path = self.root / "ledger.json"
        new_ledger(ledger_path, project_root=self.root)
        append_correction(
            ledger_path, event_id="e1", target_file=current_story, selector="#e1",
            property_name="connector_relations",
            before_value=[{"from": "a", "to": "b"}],
            after_value=[{"from": "a", "to": "b"}, {"from": "a", "to": "c"}],
            reason="user approved the additional explained branch", approved_by="hongr",
            approved_at="2026-07-30T12:00:00+00:00", related_files=[current_story],
        )

        report = evaluate_regression(
            baseline=self.baseline, storyboard_path=current_story,
            semantic_brief_path=current_brief, correction_ledger_path=ledger_path,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approved_corrections_applied"], ["e1:connector_relations"])

    def test_approved_event_removal_is_auditable(self) -> None:
        current_story = self.root / "current-story.json"
        current_brief = self.root / "current-brief.json"
        retained = [_event("e1", "概念关系", "relation")]
        current_story.write_text(json.dumps(_story(retained)), encoding="utf-8")
        current_brief.write_text(json.dumps({"events": retained}), encoding="utf-8")
        ledger_path = self.root / "ledger.json"
        new_ledger(ledger_path, project_root=self.root)
        append_correction(
            ledger_path, event_id="e2", target_file=current_story, selector="#e2",
            property_name="event.removed", before_value=False, after_value=True,
            reason="user approved removing the redundant event", approved_by="hongr",
            approved_at="2026-07-30T12:00:00+00:00", related_files=[current_story],
        )

        report = evaluate_regression(
            baseline=self.baseline, storyboard_path=current_story,
            semantic_brief_path=current_brief, correction_ledger_path=ledger_path,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approved_corrections_applied"], ["e2:event_removed"])

    def test_correction_with_only_unrelated_file_hash_cannot_approve_drift(self) -> None:
        current_story = self.root / "current-story.json"
        current_brief = self.root / "current-brief.json"
        changed = [_event("e1", "系统关系", "relation"),
                   _event("e2", "步骤路径", "process")]
        current_story.write_text(json.dumps(_story(changed)), encoding="utf-8")
        current_brief.write_text(json.dumps({"events": changed}), encoding="utf-8")
        unrelated = self.root / "unrelated.txt"
        unrelated.write_text("not editorial evidence", encoding="utf-8")
        ledger_path = self.root / "ledger.json"
        new_ledger(ledger_path, project_root=self.root)
        append_correction(
            ledger_path, event_id="e1", target_file=current_brief, selector="#e1",
            property_name="anchor", before_value="概念关系", after_value="系统关系",
            reason="invalid unrelated evidence", approved_by="hongr",
            approved_at="2026-07-30T12:00:00+00:00", related_files=[unrelated],
        )

        report = evaluate_regression(
            baseline=self.baseline, storyboard_path=current_story,
            semantic_brief_path=current_brief, correction_ledger_path=ledger_path,
        )

        self.assertEqual(report["status"], "failed")
        self.assertIn("unapproved_editorial_drift", {
            finding["code"] for finding in report["findings"]
        })

    def test_approved_anchor_correction_can_target_current_full_semantic_brief(self) -> None:
        current_story = self.root / "current-story.json"
        current_brief = self.root / "current-brief.json"
        changed = [_event("e1", "系统关系", "relation"),
                   _event("e2", "步骤路径", "process")]
        current_story.write_text(json.dumps(_story(changed)), encoding="utf-8")
        current_brief.write_text(json.dumps({"events": changed}), encoding="utf-8")
        ledger_path = self.root / "ledger.json"
        new_ledger(ledger_path, project_root=self.root)
        append_correction(
            ledger_path, event_id="e1", target_file=current_brief, selector="#e1",
            property_name="anchor", before_value="概念关系", after_value="系统关系",
            reason="user approved the clearer full-video anchor", approved_by="hongr",
            approved_at="2026-07-30T12:00:00+00:00", related_files=[current_brief],
        )

        report = evaluate_regression(
            baseline=self.baseline, storyboard_path=current_story,
            semantic_brief_path=current_brief, correction_ledger_path=ledger_path,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approved_corrections_applied"], ["e1:anchor"])

    def test_storyboard_owned_ip_change_requires_and_accepts_storyboard_target(self) -> None:
        baseline_events = [_event("e1", "概念关系", "relation"),
                           _event("e2", "步骤路径", "process")]
        baseline_events[0]["treatment"] = "ip_asset"
        baseline_brief = json.loads(json.dumps(baseline_events))
        baseline_brief[0]["form"] = "comparison"
        self.storyboard.write_text(json.dumps(_story(baseline_events)), encoding="utf-8")
        self.brief.write_text(json.dumps({"events": baseline_brief}), encoding="utf-8")
        self.baseline = create_baseline(
            storyboard_path=self.storyboard, semantic_brief_path=self.brief,
            audio_plan_path=None, cover_plan_path=None, correction_ledger_path=None,
            approved_by="hongr", output=self.baseline_path,
        )
        current_story = self.root / "current-story.json"
        current_brief = self.root / "current-brief.json"
        current_events = json.loads(json.dumps(baseline_events))
        current_events[0]["treatment"] = "structure"
        current_story.write_text(json.dumps(_story(current_events)), encoding="utf-8")
        current_brief.write_text(json.dumps({"events": baseline_brief}), encoding="utf-8")
        ledger_path = self.root / "ledger.json"
        new_ledger(ledger_path, project_root=self.root)
        append_correction(
            ledger_path, event_id="e1", target_file=current_story, selector="#e1",
            property_name="ip_visual", before_value=True, after_value=False,
            reason="user approved removing the redundant IP insert", approved_by="hongr",
            approved_at="2026-07-30T12:00:00+00:00", related_files=[current_story],
        )

        report = evaluate_regression(
            baseline=self.baseline, storyboard_path=current_story,
            semantic_brief_path=current_brief, correction_ledger_path=ledger_path,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approved_corrections_applied"], ["e1:ip_visual"])

    def test_approved_cover_route_change_uses_immutable_baseline_snapshot(self) -> None:
        baseline_cover = self.root / "approved-cover.json"
        current_cover = self.root / "current-cover.json"
        baseline_cover.write_text(json.dumps({"route": "portrait-poster"}), encoding="utf-8")
        current_cover.write_text(json.dumps({"route": "topic-poster"}), encoding="utf-8")
        self.baseline = create_baseline(
            storyboard_path=self.storyboard, semantic_brief_path=self.brief,
            audio_plan_path=None, cover_plan_path=baseline_cover,
            correction_ledger_path=None, approved_by="hongr", output=self.baseline_path,
        )
        current_story = self.root / "current-story.json"
        current_brief = self.root / "current-brief.json"
        current_story.write_text(self.storyboard.read_text(encoding="utf-8"), encoding="utf-8")
        current_brief.write_text(self.brief.read_text(encoding="utf-8"), encoding="utf-8")
        ledger_path = self.root / "ledger.json"
        new_ledger(ledger_path, project_root=self.root)
        append_correction(
            ledger_path, event_id="__global__", target_file=current_cover,
            selector="#cover_route", property_name="cover_route",
            before_value="portrait-poster", after_value="topic-poster",
            reason="user approved a topic-led cover", approved_by="hongr",
            approved_at="2026-07-30T12:00:00+00:00", related_files=[current_cover],
        )

        report = evaluate_regression(
            baseline=self.baseline, storyboard_path=current_story,
            semantic_brief_path=current_brief, correction_ledger_path=ledger_path,
            cover_plan_path=current_cover,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approved_corrections_applied"], ["__global__:cover_route"])

    def test_tampered_golden_baseline_is_rejected_before_comparison(self) -> None:
        self.baseline["signature"]["events"]["e1"]["anchor"] = "打开"

        self.assertTrue(validate_baseline(self.baseline))
        with self.assertRaises(ValueError):
            self._evaluate([_event("e1", "打开", "relation")])


if __name__ == "__main__":
    unittest.main()
