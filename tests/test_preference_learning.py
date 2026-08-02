from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from preference_learning import (  # noqa: E402
    approve_preference_candidate,
    build_preference_candidates,
    correction_id,
    revoke_preference,
    restore_preference,
    write_preference_candidates,
)


class PreferenceLearningTests(unittest.TestCase):
    def _ledger(self, related: Path) -> dict:
        row = {
            "event_id": "event-1",
            "target": {"file": str(related.resolve()), "selector": "#callout"},
            "property": "position",
            "before_value": "right",
            "after_value": "left",
            "reason": "approved optical correction",
            "approved_by": "reviewer",
            "approved_at": "2026-08-02T12:00:00+00:00",
            "related_files": [{
                "path": str(related.resolve()),
                "sha256": hashlib.sha256(related.read_bytes()).hexdigest(),
            }],
        }
        row["correction_id"] = correction_id(row)
        return {"schema_version": 1, "entries": [row]}

    def test_approved_hash_bound_correction_only_creates_pending_video_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            related = Path(folder) / "storyboard.json"
            related.write_text("{}", encoding="utf-8")
            report = build_preference_candidates(self._ledger(related), video_id="video-1")
            candidate = report["candidates"][0]
            self.assertEqual(candidate["status"], "pending")
            self.assertEqual(candidate["scope"], {"type": "video", "key": "video-1"})
            self.assertEqual(candidate["source_correction_id"], self._ledger(related)["entries"][0]["correction_id"])
            self.assertFalse(report["auto_applied"])

    def test_rejects_unapproved_stale_or_cross_project_without_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            related = Path(folder) / "storyboard.json"
            related.write_text("{}", encoding="utf-8")
            ledger = self._ledger(related)
            ledger["entries"][0]["approved_by"] = ""
            with self.assertRaisesRegex(ValueError, "approved correction"):
                build_preference_candidates(ledger, video_id="video-1")
            ledger = self._ledger(related)
            related.write_text('{"changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "related file hash is stale"):
                build_preference_candidates(ledger, video_id="video-1")
            related.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cross-project"):
                build_preference_candidates(
                    self._ledger(related), video_id="video-1", scope="content_type",
                    scope_key="tutorial",
                )
            report = build_preference_candidates(
                self._ledger(related), video_id="video-1", scope="content_type",
                scope_key="tutorial", cross_project_approved_by="reviewer",
            )
            self.assertEqual(report["candidates"][0]["scope"]["type"], "content_type")

    def test_candidate_write_uses_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            related = Path(folder) / "storyboard.json"
            related.write_text("{}", encoding="utf-8")
            output = Path(folder) / "preferences" / "candidates.json"
            report = build_preference_candidates(self._ledger(related), video_id="video-1")
            with patch("director_contracts.os.replace", wraps=__import__("os").replace) as replace:
                write_preference_candidates(output, report)
            self.assertTrue(replace.called)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)

    def test_candidates_report_samples_confidence_sources_and_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            related = Path(folder) / "storyboard.json"
            related.write_text("{}", encoding="utf-8")
            ledger = self._ledger(related)
            duplicate = dict(ledger["entries"][0])
            duplicate["event_id"] = "event-2"
            duplicate["correction_id"] = correction_id(duplicate)
            conflict = dict(ledger["entries"][0])
            conflict["event_id"] = "event-3"
            conflict["after_value"] = "right"
            conflict["correction_id"] = correction_id(conflict)
            ledger["entries"].extend([duplicate, conflict])
            report = build_preference_candidates(
                ledger, video_id="video-1", scope="project", scope_key="project-1",
            )
            left = next(row for row in report["candidates"] if row["preference"]["value"] == "left")
            self.assertEqual(left["sample_count"], 2)
            self.assertGreater(left["confidence"], 0.5)
            self.assertEqual(left["source"]["type"], "correction_ledger")
            self.assertTrue(left["conflicts"])
            self.assertFalse(left["stale_evidence"])
            self.assertEqual(left["status"], "pending")

    def test_profile_requires_explicit_candidate_approval_and_supports_revocation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            related = Path(folder) / "cover-review.json"
            related.write_text("{}", encoding="utf-8")
            ledger = self._ledger(related)
            ledger["entries"][0]["source_type"] = "cover_choice"
            ledger["entries"][0]["property"] = "cover_strategy"
            ledger["entries"][0]["after_value"] = "human_plus_product"
            ledger["entries"][0]["correction_id"] = correction_id(ledger["entries"][0])
            report = build_preference_candidates(
                ledger, video_id="video-1", scope="profile", scope_key="hongrun",
                cross_project_approved_by="owner",
            )
            candidate_id = report["candidates"][0]["candidate_id"]
            with self.assertRaisesRegex(ValueError, "explicit"):
                approve_preference_candidate(
                    report, candidate_id=candidate_id, approved_by="", approved_at="",
                    profile=None,
                )
            promoted = approve_preference_candidate(
                report, candidate_id=candidate_id, approved_by="owner",
                approved_at="2026-08-02T13:00:00+00:00", profile=None,
            )
            record = promoted["profile"]["records"][0]
            self.assertEqual(record["status"], "active")
            self.assertEqual(record["source_candidate_id"], candidate_id)
            revoked = revoke_preference(
                promoted["profile"], preference_id=record["preference_id"],
                revoked_by="owner", revoked_at="2026-08-02T14:00:00+00:00",
                reason="not useful for this profile",
            )
            self.assertEqual(revoked["records"][0]["status"], "revoked")
            self.assertEqual(revoked["records"][0]["revocation"]["reason"], "not useful for this profile")
            restored = restore_preference(
                revoked, preference_id=record["preference_id"], restored_by="owner",
                restored_at="2026-08-02T15:00:00+00:00", reason="re-enable after review",
            )
            self.assertEqual(restored["records"][0]["status"], "active")
            self.assertIsNone(restored["records"][0]["revocation"])
            self.assertEqual(len(restored["records"][0]["revocation_history"]), 1)

    def test_private_or_secret_fields_are_never_learned(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            related = Path(folder) / "storyboard.json"
            related.write_text("{}", encoding="utf-8")
            for field in ("api_key", "raw_transcript", "private_source_content"):
                ledger = self._ledger(related)
                ledger["entries"][0]["property"] = field
                ledger["entries"][0]["correction_id"] = correction_id(ledger["entries"][0])
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "sensitive"):
                    build_preference_candidates(ledger, video_id="video-1")
            ledger = self._ledger(related)
            ledger["entries"][0]["after_value"] = {"api_key": "sk-do-not-store"}
            ledger["entries"][0]["correction_id"] = correction_id(ledger["entries"][0])
            with self.assertRaisesRegex(ValueError, "sensitive"):
                build_preference_candidates(ledger, video_id="video-1")

    def test_explicit_approval_resolves_conflicting_candidate_without_auto_apply(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            related = Path(folder) / "storyboard.json"
            related.write_text("{}", encoding="utf-8")
            ledger = self._ledger(related)
            conflict = dict(ledger["entries"][0])
            conflict["event_id"] = "event-2"
            conflict["after_value"] = "right"
            conflict["correction_id"] = correction_id(conflict)
            ledger["entries"].append(conflict)
            report = build_preference_candidates(ledger, video_id="video-1")
            chosen = next(row for row in report["candidates"] if row["preference"]["value"] == "left")
            promoted = approve_preference_candidate(
                report, candidate_id=chosen["candidate_id"], approved_by="owner",
                approved_at="2026-08-02T13:00:00+00:00", profile=None,
            )
            statuses = {row["preference"]["value"]: row["status"] for row in promoted["report"]["candidates"]}
            self.assertEqual(statuses, {"left": "approved", "right": "rejected_conflict"})
            self.assertFalse(promoted["report"]["auto_applied"])


if __name__ == "__main__":
    unittest.main()
