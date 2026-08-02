from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from semantic_confidence import (  # noqa: E402
    build_candidate_report,
    build_confidence_report,
    validate_candidate_report,
    validate_confidence_report,
)


class SemanticConfidenceTests(unittest.TestCase):
    def _candidate(self, frame: Path, **overrides):
        candidate = {
            "event_id": "event-1",
            "anchor": "本地优先的隐私转写",
            "raw_word_ids": ["w001", "w002", "w003"],
            "raw_quote": "这里使用本地优先的隐私转写",
            "source_timing": {"start": 1.0, "end": 3.0},
            "output_timing": {"start": 1.2, "end": 3.2},
            "frame_evidence": [{
                "path": str(frame),
                "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
                "timestamp": 2.0,
            }],
            "anchor_specificity": 0.92,
            "claim_grounding": 0.9,
            "explanatory_value": 0.88,
            "asr_confidence": 0.94,
            "term_confidence": 0.96,
            "caption_duplication": 0.1,
            "motion_duplication": 0.0,
            "ip_duplication": 0.0,
            "counterexamples": [],
            "conflicts": [],
            "semantic_effect": "emphasis",
        }
        candidate.update(overrides)
        return candidate

    def test_candidate_report_records_complete_evidence_and_scores(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            frame = Path(folder) / "frame.png"
            frame.write_bytes(b"frame")
            report = build_candidate_report([self._candidate(frame)])
            row = report["candidates"][0]
            self.assertEqual(row["raw_word_ids"], ["w001", "w002", "w003"])
            self.assertEqual(row["raw_quote"], "这里使用本地优先的隐私转写")
            self.assertEqual(row["source_timing"], {"start": 1.0, "end": 3.0})
            self.assertEqual(row["output_timing"], {"start": 1.2, "end": 3.2})
            self.assertEqual(row["frame_evidence"][0]["timestamp"], 2.0)
            self.assertGreater(row["total_confidence"], 0.7)
            self.assertEqual(row["disposition"], "accepted_for_motion")
            self.assertTrue(row["reasons"])
            self.assertEqual(row["rejection_reasons"], [])
            self.assertEqual(report["selection_policy"], "evidence_weighted_no_keyword_or_random")
            self.assertEqual(validate_candidate_report(report), report)
            report["candidates"][0]["total_confidence"] = 1.0
            with self.assertRaisesRegex(ValueError, "scores or decisions"):
                validate_candidate_report(report)

    def test_low_information_anchor_cannot_be_highlighted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            frame = Path(folder) / "frame.png"
            frame.write_bytes(b"frame")
            for anchor in ("打开", "点击", "添加", "然后", "点击这里", "然后打开一下"):
                with self.subTest(anchor=anchor):
                    report = build_candidate_report([
                        self._candidate(frame, anchor=anchor, disposition="accepted_for_motion")
                    ])
                    row = report["candidates"][0]
                    self.assertNotEqual(row["disposition"], "accepted_for_motion")
                    self.assertIn("low_information_anchor", row["rejection_reasons"])
                    self.assertFalse(row["eligible_for_highlight"])

    def test_low_confidence_downgrades_and_meaning_change_requires_action(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            frame = Path(folder) / "frame.png"
            frame.write_bytes(b"frame")
            low = dict(
                anchor_specificity=0.2, claim_grounding=0.2,
                explanatory_value=0.2, asr_confidence=0.4,
                term_confidence=0.3, caption_duplication=0.8,
            )
            report = build_candidate_report([self._candidate(frame, **low)])
            self.assertEqual(report["candidates"][0]["disposition"], "caption_only")
            changing = build_candidate_report([
                self._candidate(frame, semantic_effect="reorder", **low)
            ])
            self.assertEqual(changing["status"], "action_required")
            self.assertEqual(changing["candidates"][0]["disposition"], "action_required")

    def test_candidate_rejects_incomplete_evidence_and_prohibited_selection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            frame = Path(folder) / "frame.png"
            frame.write_bytes(b"frame")
            for missing in ("raw_word_ids", "raw_quote", "source_timing", "output_timing",
                            "frame_evidence", "counterexamples", "conflicts"):
                row = self._candidate(frame)
                row.pop(missing)
                with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, missing):
                    build_candidate_report([row])
            with self.assertRaisesRegex(ValueError, "prohibited selection_method"):
                build_candidate_report([
                    self._candidate(frame, selection_method="keyword_frequency")
                ])

    def test_duplication_conflicts_and_false_claim_reduce_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            frame = Path(folder) / "frame.png"
            frame.write_bytes(b"frame")
            clean = build_candidate_report([self._candidate(frame)])["candidates"][0]
            conflicted = build_candidate_report([self._candidate(
                frame,
                caption_duplication=0.9,
                motion_duplication=0.8,
                ip_duplication=0.7,
                counterexamples=[{"quote": "稍后画面显示这是云端处理"}],
                conflicts=[{"type": "frame_conflict", "detail": "UI contradicts the claim"}],
            )])["candidates"][0]
            self.assertLess(conflicted["total_confidence"], clean["total_confidence"])
            self.assertNotEqual(conflicted["disposition"], "accepted_for_motion")

    def test_report_binds_evidence_and_preserves_counterexamples(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "frame.png"
            evidence.write_bytes(b"frame")
            digest = hashlib.sha256(b"frame").hexdigest()
            report = build_confidence_report([{
                "claim_id": "claim-1",
                "claim": "The panel is the primary interaction target.",
                "confidence": 0.91,
                "evidence": [{"path": str(evidence), "sha256": digest}],
                "counterexamples": [{"description": "A later frame emphasizes the toolbar."}],
            }])
            validated = validate_confidence_report(report)
            self.assertEqual(validated["claims"][0]["evidence"][0]["sha256"], digest)
            self.assertEqual(len(validated["claims"][0]["counterexamples"]), 1)
            self.assertEqual(validated["claims"][0]["disposition"], "accepted_for_planning")
            self.assertFalse(validated["semantic_deletion_authority"])

    def test_low_confidence_requires_non_destructive_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "frame.png"
            evidence.write_bytes(b"frame")
            base = {
                "claim_id": "claim-low", "claim": "This is likely a settings panel.",
                "confidence": 0.42,
                "evidence": [{"path": str(evidence), "sha256": hashlib.sha256(b"frame").hexdigest()}],
                "counterexamples": [],
            }
            with self.assertRaisesRegex(ValueError, "low-confidence.*disposition"):
                build_confidence_report([base])
            report = build_confidence_report([{**base, "disposition": "preserve_source"}])
            self.assertEqual(report["status"], "action_required")
            with self.assertRaisesRegex(ValueError, "low-confidence.*disposition"):
                build_confidence_report([{**base, "disposition": "auto_apply"}])

    def test_rejects_stale_evidence_hash_and_missing_counterexample_review(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "frame.png"
            evidence.write_bytes(b"new")
            with self.assertRaisesRegex(ValueError, "hash is stale"):
                build_confidence_report([{
                    "claim_id": "claim-1", "claim": "claim", "confidence": 0.8,
                    "evidence": [{"path": str(evidence), "sha256": hashlib.sha256(b"old").hexdigest()}],
                    "counterexamples": [],
                }])
            with self.assertRaisesRegex(ValueError, "counterexamples"):
                build_confidence_report([{
                    "claim_id": "claim-1", "claim": "claim", "confidence": 0.8,
                    "evidence": [{"path": str(evidence), "sha256": hashlib.sha256(b"new").hexdigest()}],
                }])


if __name__ == "__main__":
    unittest.main()
