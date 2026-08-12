from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from editorial_promise import (  # noqa: E402
    build_promise_ledger, build_promise_closure, validate_promise_bindings,
)
from audit_hook_pacing import audit as audit_hook  # noqa: E402
from generate_publishing_copy import build as build_publishing_copy  # noqa: E402


class EditorialPromiseTests(unittest.TestCase):
    def brief(self) -> dict:
        return {
            "events": [{
                "id": "semantic-1", "decision": "render",
                "viewer_takeaway": "理解这个方法如何减少重复工作",
                "approved_visible_copy": ["减少重复工作"],
                "transcript_word_ids": ["w1", "w2"],
                "target_frame_evidence": ["frame-sha256:" + "a" * 64],
            }],
            "editorial_intent": {
                "audience": "需要提高效率的知识工作者",
                "viewer_job": "判断这个方法是否适合自己的工作流",
                "single_promise": "理解这个方法如何减少重复工作",
                "proof_event_ids": ["semantic-1"],
                "cta": "结合自己的重复任务做一次验证",
                "tone": "清晰克制",
                "prohibited_claims": ["效率提升十倍"],
            },
        }

    def test_ledger_binds_single_promise_to_semantic_evidence(self) -> None:
        ledger = build_promise_ledger(self.brief())
        self.assertEqual(ledger["mode"], "explicit_intent")
        self.assertEqual(ledger["single_promise"]["text"], "理解这个方法如何减少重复工作")
        self.assertEqual(ledger["single_promise"]["proof_event_ids"], ["semantic-1"])
        self.assertIn("w1", ledger["single_promise"]["transcript_word_ids"])

    def test_missing_intent_uses_neutral_education_without_sales_goal(self) -> None:
        brief = self.brief()
        brief.pop("editorial_intent")
        ledger = build_promise_ledger(brief)
        self.assertEqual(ledger["mode"], "neutral_education")
        self.assertEqual(ledger["cta"], "continue_learning")
        self.assertFalse(ledger["commercial_goal_invented"])
        self.assertEqual(ledger["single_promise"]["proof_event_ids"], ["semantic-1"])

    def test_downstream_claims_require_ledger_binding_and_forbid_prohibited_claims(self) -> None:
        ledger = build_promise_ledger(self.brief())
        outputs = [{
            "surface": "title", "copy": "这个方法如何减少重复工作",
            "promise_id": ledger["promise_id"], "proof_event_ids": ["semantic-1"],
        }, {
            "surface": "cover", "copy": "效率提升十倍",
            "promise_id": ledger["promise_id"], "proof_event_ids": ["semantic-1"],
        }]
        errors = validate_promise_bindings(ledger, outputs)
        self.assertTrue(any("prohibited claim" in error for error in errors), errors)

    def test_copy_may_vary_but_mechanical_repetition_is_rejected(self) -> None:
        ledger = build_promise_ledger(self.brief())
        outputs = [{
            "surface": surface, "copy": "减少重复工作",
            "promise_id": ledger["promise_id"], "proof_event_ids": ["semantic-1"],
        } for surface in ("hook", "title", "cover", "description")]
        errors = validate_promise_bindings(ledger, outputs)
        self.assertTrue(any("mechanically repeated" in error for error in errors), errors)

    def test_hook_and_publishing_surfaces_are_bound_and_validated(self) -> None:
        ledger = build_promise_ledger(self.brief())
        transcript = {"segments": [{
            "start": 0.2, "end": 4.0, "text": "这个方法能减少重复工作。",
        }]}
        hook = audit_hook(transcript, promise_ledger=ledger)
        publishing = build_publishing_copy("减少重复工作", transcript, ["工作流"], ledger)
        rows = [hook["promise_binding"], *publishing["promise_binding"]["surfaces"]]

        self.assertEqual(validate_promise_bindings(ledger, rows), [])

    def test_publishing_generation_fails_closed_for_prohibited_claim(self) -> None:
        ledger = build_promise_ledger(self.brief())
        ledger["prohibited_claims"] = ["保证翻倍"]
        transcript = {"segments": [{"start": 0, "end": 2, "text": "保证翻倍。"}]}

        with self.assertRaisesRegex(ValueError, "prohibited"):
            build_publishing_copy("保证翻倍", transcript, [], ledger)

    def test_promise_closure_requires_all_configured_surfaces_together(self) -> None:
        ledger = build_promise_ledger(self.brief())
        rows = [{
            "surface": surface, "copy": f"{surface}：减少重复工作",
            "promise_id": ledger["promise_id"], "proof_event_ids": ["semantic-1"],
        } for surface in ("hook", "title", "cover", "description", "cta", "motion_copy")]

        closure = build_promise_closure(ledger, rows)

        self.assertEqual(closure["status"], "pass")
        self.assertEqual(closure["covered_surfaces"], [
            "cover", "cta", "description", "hook", "motion_copy", "title",
        ])

    def test_promise_closure_rejects_missing_cover_or_motion_surface(self) -> None:
        ledger = build_promise_ledger(self.brief())
        rows = [{
            "surface": surface, "copy": f"{surface}：减少重复工作",
            "promise_id": ledger["promise_id"], "proof_event_ids": ["semantic-1"],
        } for surface in ("hook", "title", "description", "cta")]

        closure = build_promise_closure(ledger, rows)

        self.assertEqual(closure["status"], "failed")
        self.assertIn("cover", closure["missing_surfaces"])
        self.assertIn("motion_copy", closure["missing_surfaces"])

    def test_promise_closure_rejects_empty_unrelated_and_duplicate_surfaces(self) -> None:
        ledger = build_promise_ledger(self.brief())
        rows = [{
            "surface": surface, "copy": "",
            "promise_id": ledger["promise_id"], "proof_event_ids": ["semantic-1"],
        } for surface in ("hook", "title", "cover", "description", "cta", "motion_copy")]
        rows.append({**rows[0], "copy": "Guaranteed $1m tomorrow"})
        closure = build_promise_closure(ledger, rows)
        self.assertEqual(closure["status"], "failed")
        self.assertTrue(any("empty" in error for error in closure["errors"]))
        self.assertTrue(any("semantic overlap" in error for error in closure["errors"]))
        self.assertTrue(any("exactly one hook" in error for error in closure["errors"]))

    def test_promise_binding_rejects_overlap_plus_unapproved_numeric_claim(self) -> None:
        ledger = build_promise_ledger(self.brief())
        errors = validate_promise_bindings(ledger, [{
            "surface": "title", "copy": "减少重复工作，Guaranteed $1m tomorrow",
            "promise_id": ledger["promise_id"], "proof_event_ids": ["semantic-1"],
        }])
        self.assertTrue(any("unapproved claim tokens" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
