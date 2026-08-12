from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from creative_review import (  # noqa: E402
    build_contract,
    mark_stale,
    record_user_decision,
    validate_sample_pair_durations,
    validate_review,
)
from director_contracts import sha256_file  # noqa: E402
from review_dashboard import generate_dashboard  # noqa: E402


class CreativeReviewTests(unittest.TestCase):
    def test_director_sample_pair_requires_aligned_sixty_to_ninety_seconds(self) -> None:
        self.assertEqual(validate_sample_pair_durations(75.0, 75.2), [])
        self.assertTrue(any("60-90" in error for error in validate_sample_pair_durations(45.0, 45.0)))
        self.assertTrue(any("aligned" in error for error in validate_sample_pair_durations(75.0, 77.0)))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.director = self.project / "work" / "director"
        self.director.mkdir(parents=True)
        (self.director / "director-state.json").write_text(
            json.dumps({"status": "action_required", "stages": {}}), encoding="utf-8",
        )
        self.baseline = self.project / "baseline.mp4"
        self.candidate = self.project / "candidate.mp4"
        self.baseline.write_bytes(b"baseline-media")
        self.candidate.write_bytes(b"candidate-media")
        self.motion_contract = self.director / "motion-design-contract.json"
        self.motion_contract.write_text(json.dumps({
            "selected_event_ids": ["event-1"],
            "opportunities": [{
                "semantic_event_id": "event-1", "decision": "render",
                "rationale": "Explain the verified comparison",
                "output_window": {"start_seconds": 2.0, "end_seconds": 6.0},
                "viewer_takeaway": "Understand the comparison",
                "approved_visible_copy": ["核心对比"],
                "target_binding_ids": ["target-1"],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.storyboard = self.director / "storyboard.json"
        self.storyboard.write_text(json.dumps({
            "events": [{"id": "event-1", "semantic_event_id": "event-1"}],
        }), encoding="utf-8")
        self.semantic_brief = self.director / "semantic-brief.json"
        self.semantic_brief.write_text(json.dumps({
            "events": [{
                "id": "event-1",
                "transcript_quote": "<script>alert(1)</script> 原句",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.phase_paths: dict[str, Path] = {}
        observations = []
        for index, phase in enumerate(("entrance", "mid", "pre_exit", "post_exit")):
            path = self.project / f"event-1-{phase}.png"
            Image.new("RGB", (640, 360), (240, 245, 248)).save(path)
            self.phase_paths[phase] = path
            observations.append({
                "phase": phase, "timestamp_seconds": 2.5 + index,
                "snapshot": {"path": str(path.resolve()), "sha256": sha256_file(path)},
            })
        self.receipt = self.project / "event-1-receipt.json"
        self.receipt.write_text(json.dumps({
            "event_id": "event-1", "phase_observations": observations,
        }), encoding="utf-8")
        self.gate = self.director / "gate-report.json"
        self.gate.write_text(json.dumps({"passed": True}), encoding="utf-8")
        self.audio: dict[str, Path] = {}
        for name in ("sfx_off", "sfx_on", "bgm_off", "bgm_on"):
            path = self.project / f"event-1-{name}.wav"
            path.write_bytes((name + "-audio").encode("utf-8"))
            self.audio[name] = path
        self.output = self.director / "sample-qa" / "creative-review.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build(self) -> dict:
        return build_contract(
            project_id="project-1",
            baseline_path=self.baseline,
            candidate_path=self.candidate,
            baseline_duration_seconds=12.0,
            candidate_duration_seconds=12.0,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            semantic_brief_path=self.semantic_brief,
            keyframe_receipt_paths={"event-1": self.receipt},
            gate_report_paths=[self.gate],
            audio_auditions={"event-1": self.audio},
            output=self.output,
        )

    def test_builds_pending_hash_bound_paired_review_and_dashboard(self) -> None:
        review = self._build()
        self.assertEqual(validate_review(
            review,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            keyframe_receipt_paths={"event-1": self.receipt},
            motion_audio_decisions_path=None,
        ), [])
        self.assertEqual(review["status"], "pending_user_review")
        self.assertEqual(review["user_review"], {"decision": "pending"})

        dashboard = generate_dashboard(
            project_root=self.project,
            director_root=self.director,
            output=self.director / "review" / "index.html",
            creative_review_path=self.output,
            motion_design_contract_path=self.motion_contract,
        )
        document = dashboard.read_text(encoding="utf-8")
        self.assertIn("Baseline", document)
        self.assertIn("Candidate", document)
        self.assertIn("entrance", document)
        self.assertIn("post_exit", document)
        self.assertIn("Explain the verified comparison", document)
        self.assertIn("<audio", document)
        self.assertNotIn("<script>alert(1)</script>", document)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", document)

        interactive = generate_dashboard(
            project_root=self.project,
            director_root=self.director,
            output=self.director / "review" / "interactive.html",
            creative_review_path=self.output,
            motion_design_contract_path=self.motion_contract,
            interactive_api_url="http://127.0.0.1:8765/api/proposals",
        ).read_text(encoding="utf-8")
        self.assertIn("fetch(", interactive)
        self.assertIn("仅生成 pending proposal", interactive)
        self.assertNotIn("button type=\"button\" disabled", interactive)
        self.assertNotIn("secret-token", interactive)
        self.assertNotIn("csrf-token", interactive)
        with self.assertRaisesRegex(ValueError, "loopback"):
            generate_dashboard(
                project_root=self.project,
                director_root=self.director,
                output=self.director / "review" / "unsafe.html",
                creative_review_path=self.output,
                motion_design_contract_path=self.motion_contract,
                interactive_api_url="https://evil.example/api/proposals",
            )

    def test_hash_drift_marks_review_stale_and_clears_user_approval(self) -> None:
        review = self._build()
        approved = record_user_decision(
            review, decision="approved", reviewer="HongRun",
            publish_willingness="yes", baseline_preference="candidate",
            reason="Candidate adds useful explanation without distracting",
        )
        self.assertEqual(approved["status"], "approved")
        self.storyboard.write_text('{"events":[]}', encoding="utf-8")
        errors = validate_review(
            approved,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            keyframe_receipt_paths={"event-1": self.receipt},
            motion_audio_decisions_path=None,
        )
        self.assertTrue(any("stale" in error for error in errors), errors)
        stale = mark_stale(approved, errors)
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["user_review"], {"decision": "pending"})

    def test_agent_or_multimodal_output_cannot_author_user_approval(self) -> None:
        review = self._build()
        forged = copy.deepcopy(review)
        forged["user_review"] = {
            "decision": "approved", "reviewer": "multimodal-agent",
            "reviewed_at": "2026-08-11T00:00:00+00:00",
            "publish_willingness": "yes", "baseline_preference": "candidate",
            "reason": "automated recommendation must not become user approval",
        }
        forged["status"] = "approved"
        errors = validate_review(
            forged,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            keyframe_receipt_paths={"event-1": self.receipt},
            motion_audio_decisions_path=None,
        )
        self.assertTrue(any("human user" in error for error in errors), errors)

    def test_correction_proposals_must_remain_pending(self) -> None:
        review = self._build()
        review["correction_proposals"] = [{
            "proposal_id": "proposal-1", "event_id": "event-1",
            "selector": "#event-1", "property": "position",
            "before": [1, 2], "after": [3, 4], "reason": "align target",
            "status": "approved",
        }]
        errors = validate_review(
            review,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            keyframe_receipt_paths={"event-1": self.receipt},
            motion_audio_decisions_path=None,
        )
        self.assertTrue(any("pending correction proposal" in error for error in errors), errors)

    def test_approval_requires_reason_and_comparable_event_times(self) -> None:
        review = self._build()
        with self.assertRaisesRegex(ValueError, "reason"):
            record_user_decision(
                review, decision="approved", reviewer="HongRun",
                publish_willingness="yes", baseline_preference="candidate",
            )
        review["event_comparisons"][0]["baseline_timestamp_seconds"] = 10.0
        errors = validate_review(
            review,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            keyframe_receipt_paths={"event-1": self.receipt},
            motion_audio_decisions_path=None,
        )
        self.assertTrue(any("baseline timestamp" in error for error in errors), errors)

    def test_malformed_bound_gate_fails_closed_without_crashing(self) -> None:
        review = self._build()
        self.gate.write_text("{broken", encoding="utf-8")
        errors = validate_review(
            review,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            keyframe_receipt_paths={"event-1": self.receipt},
            motion_audio_decisions_path=None,
        )
        self.assertTrue(any("gate" in error and "unreadable" in error for error in errors), errors)

    def test_malformed_bound_receipt_fails_closed_without_crashing(self) -> None:
        review = self._build()
        self.receipt.write_text("{broken", encoding="utf-8")
        errors = validate_review(
            review,
            motion_design_contract_path=self.motion_contract,
            storyboard_path=self.storyboard,
            keyframe_receipt_paths={"event-1": self.receipt},
            motion_audio_decisions_path=None,
        )
        self.assertTrue(any("receipt" in error and "unreadable" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
