from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from production_contract import build_contract, validate_contract  # noqa: E402


class ProductionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.transcript = self.root / "transcript.json"
        self.edl = self.root / "edl.json"
        self.brief = self.root / "semantic-brief.json"
        self.source.write_bytes(b"source")
        self.transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
        self.edl.write_text(json.dumps({"owner": "video-use", "ranges": []}), encoding="utf-8")
        self.brief.write_text(json.dumps({
            "schema_version": 2,
            "events": [{"id": "e1", "viewer_takeaway": "理解请求如何流转"}],
        }, ensure_ascii=False), encoding="utf-8")
        self.project = {
            "schema_version": 8,
            "workflow": {"input_mode": "source_first", "production_contract": {"enabled": True}},
            "content": {"type": "screen_tutorial"},
            "editing": {"mode": "preserve", "caption_punctuation": "spoken_clean"},
            "audio": {"bgm": {"enabled_by_default": True}, "sfx": {"enabled": True}},
            "cover": {"editorial": {"mode": "auto"}},
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_contract_binds_current_inputs_and_role_boundaries(self) -> None:
        contract = build_contract(
            project=self.project,
            source_path=self.source,
            transcript_path=self.transcript,
            edl_path=self.edl,
            semantic_brief_path=self.brief,
            input_mode="preserve",
        )

        self.assertEqual(validate_contract(
            contract,
            project=self.project,
            source_path=self.source,
            transcript_path=self.transcript,
            edl_path=self.edl,
            semantic_brief_path=self.brief,
            input_mode="preserve",
        ), [])
        self.assertEqual(contract["delivery_promise"]["type"], "screen_demo")
        self.assertTrue(contract["motion_policy"]["fixed_event_quota_forbidden"])
        self.assertEqual(contract["owners"]["timeline"], "video-use")
        self.assertEqual(contract["owners"]["creative_motion"], "hyperframes")
        self.assertEqual(contract["owners"]["final_media"], "ffmpeg")

    def test_contract_rejects_hash_drift_and_motion_quota(self) -> None:
        contract = build_contract(
            project=self.project,
            source_path=self.source,
            transcript_path=self.transcript,
            edl_path=self.edl,
            semantic_brief_path=self.brief,
            input_mode="preserve",
        )
        self.transcript.write_text('{"words":[{"text":"changed"}]}', encoding="utf-8")
        contract["motion_policy"]["events_per_minute"] = 6

        errors = validate_contract(
            contract,
            project=self.project,
            source_path=self.source,
            transcript_path=self.transcript,
            edl_path=self.edl,
            semantic_brief_path=self.brief,
            input_mode="preserve",
        )

        self.assertTrue(any("transcript" in error and "hash" in error for error in errors))
        self.assertTrue(any("quota" in error for error in errors))

    def test_contract_rejects_tampered_policy_even_when_inputs_are_current(self) -> None:
        contract = build_contract(
            project=self.project, source_path=self.source, transcript_path=self.transcript,
            edl_path=self.edl, semantic_brief_path=self.brief, input_mode="preserve",
        )
        contract["audio"]["speech_dominant"] = False

        errors = validate_contract(
            contract, project=self.project, source_path=self.source,
            transcript_path=self.transcript, edl_path=self.edl,
            semantic_brief_path=self.brief, input_mode="preserve",
        )

        self.assertTrue(any("deterministic" in error or "integrity" in error for error in errors))

    def test_contract_binds_explicit_third_party_identity_policy(self) -> None:
        self.project["identity"] = {"mode": "third_party"}

        contract = build_contract(
            project=self.project, source_path=self.source, transcript_path=self.transcript,
            edl_path=self.edl, semantic_brief_path=self.brief, input_mode="preserve",
        )

        self.assertEqual(contract["identity"], {
            "mode": "third_party",
            "hongrun_assets_allowed": False,
            "personal_intro_outro_allowed": False,
            "first_person_brand_expression_allowed": False,
        })
        self.assertEqual(validate_contract(
            contract, project=self.project, source_path=self.source,
            transcript_path=self.transcript, edl_path=self.edl,
            semantic_brief_path=self.brief, input_mode="preserve",
        ), [])


if __name__ == "__main__":
    unittest.main()
