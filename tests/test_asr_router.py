from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from asr_router import choose_backend, normalize_transcript  # noqa: E402
from director import Director  # noqa: E402
from director_contracts import DirectorContractError  # noqa: E402


class AsrRouterTests(unittest.TestCase):
    def test_routes_chinese_hotwords_to_funasr_and_interview_to_whisperx(self) -> None:
        configured = {
            "backends": {
                "local_faster_whisper": {"available": True},
                "funasr": {"available": True},
                "whisperx": {"available": True},
            }
        }
        hotword = choose_backend(configured, {
            "language": "zh", "hotwords": ["ExplainIt"], "speaker_count": 1,
        })
        interview = choose_backend(configured, {
            "language": "zh", "speaker_count": 2, "precise_word_alignment": True,
        })
        self.assertEqual(hotword["selected_backend"], "funasr")
        self.assertEqual(interview["selected_backend"], "whisperx")
        self.assertFalse(hotword["semantic_deletion_authority"])

    def test_unavailable_specialist_falls_back_to_local(self) -> None:
        route = choose_backend({
            "backends": {
                "local_faster_whisper": {"available": True},
                "funasr": {"available": False},
                "whisperx": {"available": False},
            }
        }, {"language": "zh", "hotwords": ["产品名"]})
        self.assertEqual(route["selected_backend"], "local_faster_whisper")
        self.assertIn("funasr_unavailable", route["fallbacks"])

    def test_normalizes_segment_words_without_changing_text_or_timing(self) -> None:
        raw = {
            "language": "zh",
            "segments": [{"speaker": "S1", "words": [
                {"word": "你好", "start": 0.1, "end": 0.4, "score": 0.9},
                {"word": "世界", "start": 0.5, "end": 0.8, "score": 0.8},
            ]}],
        }
        normalized = normalize_transcript(raw, backend="whisperx")
        self.assertEqual([row["text"] for row in normalized["words"]], ["你好", "世界"])
        self.assertEqual(normalized["words"][0]["start"], 0.1)
        self.assertEqual(normalized["words"][0]["speaker_id"], "S1")
        self.assertFalse(normalized["normalization"]["text_or_timing_modified"])

    def test_normalization_preserves_whitespace_and_fails_on_invalid_word(self) -> None:
        normalized = normalize_transcript({"words": [
            {"text": " keep ", "start": 0.0, "end": 0.5}
        ]}, backend="local_faster_whisper")
        self.assertEqual(normalized["words"][0]["text"], " keep ")
        with self.assertRaisesRegex(ValueError, "missing text or timing"):
            normalize_transcript({"words": [{"text": "lost", "start": 0.0}]}, backend="funasr")

    def test_normalization_rejects_non_finite_timing_and_confidence(self) -> None:
        for row in (
            {"text": "bad", "start": float("nan"), "end": 1.0},
            {"text": "bad", "start": 0.0, "end": float("inf")},
            {"text": "bad", "start": 0.0, "end": 1.0, "confidence": float("-inf")},
        ):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "invalid ASR word"):
                normalize_transcript({"words": [row]}, backend="local_faster_whisper")

    def test_director_routes_missing_transcript_when_optional_router_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"fixture")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "schema_version": 4, "version": 4, "video_id": "fixture",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4", "input_mode": "raw"},
                "transcription": {"router": {
                    "enabled": True, "language": "zh", "hotwords": ["ExplainIt"],
                    "backends": {"local_faster_whisper": {"available": True},
                                 "funasr": {"available": True}, "whisperx": {"available": False}},
                }},
            }), encoding="utf-8")
            director = Director(project)
            director._start("video_use_timeline")
            with self.assertRaises(DirectorContractError):
                director.stage_video_use_timeline()
            route = json.loads((director.video_use_dir / "asr-route.json").read_text(encoding="utf-8"))
            self.assertEqual(route["selected_backend"], "funasr")
            action = json.loads(director.action_path.read_text(encoding="utf-8"))
            self.assertEqual(action["actions"][0]["backend"], "funasr")


if __name__ == "__main__":
    unittest.main()
