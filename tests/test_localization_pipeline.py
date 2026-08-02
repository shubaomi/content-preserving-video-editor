from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from localization_pipeline import build_localization_manifest, validate_localization_manifest  # noqa: E402


class LocalizationPipelineTests(unittest.TestCase):
    def test_missing_provider_is_action_required_without_fake_translation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / "transcript.json"
            transcript.write_text('{"words":[{"id":"w1","text":"你好","start":0,"end":1}]}', encoding="utf-8")
            report = build_localization_manifest(
                transcript_path=transcript, target_language="en", glossary={"你好": "hello"},
                provider={}, voice_clone_authorized=False, output=root / "localization.json",
            )
            self.assertEqual(report["status"], "action_required")
            self.assertEqual(report["translations"], [])

    def test_fixture_provider_writes_auditable_translation_and_backtranslation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / "transcript.json"
            transcript.write_text('{"words":[{"id":"w1","text":"你好","start":0,"end":1}]}', encoding="utf-8")
            report = build_localization_manifest(
                transcript_path=transcript, target_language="en", glossary={"你好": "hello"},
                provider={"backend": "fixture", "name": "fixture", "translations": {
                    "w1": {"translated": "hello", "back_translation": "你好"}
                }}, voice_clone_authorized=False, output=root / "localization.json",
            )
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["translations"][0]["word_id"], "w1")
            self.assertEqual(validate_localization_manifest(report), [])

    def test_real_result_file_is_adopted_with_hash_and_complete_word_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); transcript = root / "transcript.json"
            transcript.write_text(
                '{"words":[{"id":"w1","text":"你好","start":0,"end":1}]}',
                encoding="utf-8",
            )
            result = root / "provider-result.json"
            result.write_text(json.dumps({
                "provider": "authorized-translator", "target_language": "en",
                "input_contract": {
                    "transcript_sha256": __import__("director_contracts").sha256_file(transcript),
                    "glossary_sha256": hashlib.sha256(json.dumps(
                        {"你好": "hello"}, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")).hexdigest(),
                },
                "translations": {"w1": {"translated": "hello", "back_translation": "你好"}},
                "tts": {"status": "not_requested"}, "lipsync": {"status": "not_requested"},
            }, ensure_ascii=False), encoding="utf-8")

            report = build_localization_manifest(
                transcript_path=transcript, target_language="en", glossary={"你好": "hello"},
                provider={"backend": "result_file", "name": "authorized-translator",
                          "result": str(result), "authorized": True},
                voice_clone_authorized=False, output=root / "localization.json",
            )

            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["provider_result"]["sha256"], __import__(
                "director_contracts"
            ).sha256_file(result))
            self.assertEqual(validate_localization_manifest(report), [])

    def test_real_result_file_without_current_input_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); transcript = root / "transcript.json"
            transcript.write_text(
                '{"words":[{"id":"w1","text":"hello","start":0,"end":1}]}',
                encoding="utf-8",
            )
            result = root / "provider-result.json"
            result.write_text(json.dumps({
                "provider": "authorized-translator", "target_language": "zh",
                "translations": {"w1": {"translated": "你好", "back_translation": "hello"}},
            }, ensure_ascii=False), encoding="utf-8")

            report = build_localization_manifest(
                transcript_path=transcript, target_language="zh", glossary={},
                provider={"backend": "result_file", "name": "authorized-translator",
                          "result": str(result), "authorized": True},
                voice_clone_authorized=False, output=root / "localization.json",
            )

            self.assertEqual(report["status"], "failed")
            self.assertIn("input contract", report["reason"])


if __name__ == "__main__":
    unittest.main()
