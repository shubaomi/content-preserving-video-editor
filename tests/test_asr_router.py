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

from asr_router import (  # noqa: E402
    AsrCapabilityError,
    build_asr_quality_report,
    choose_backend,
    choose_pipeline,
    merge_hotwords,
    normalize_transcript,
    route_sha256,
    transcript_sha256,
    validate_pipeline_reports,
)
from director import Director  # noqa: E402
from director_contracts import DirectorContractError  # noqa: E402


class AsrRouterTests(unittest.TestCase):
    def test_merges_governed_hotwords_from_project_and_profile(self) -> None:
        merged = merge_hotwords(
            {
                "hotwords": ["ExplainIt", "RAG"],
                "products": ["TabOut"],
                "urls": ["example.com/docs"],
                "commands": ["npm run render"],
                "english_terms": ["forced alignment"],
            },
            {
                "hotwords": ["explainit", "HongRun"],
                "products": ["TabOut"],
                "terminology": ["逐字时间戳"],
            },
        )
        self.assertEqual(merged[0], "ExplainIt")
        self.assertEqual(len([v for v in merged if v.casefold() == "explainit"]), 1)
        self.assertIn("example.com/docs", merged)
        self.assertIn("npm run render", merged)
        self.assertIn("forced alignment", merged)
        self.assertIn("逐字时间戳", merged)

    def test_noise_existing_caption_and_drift_are_recorded_in_route(self) -> None:
        route = choose_pipeline({"backends": {
            "local_faster_whisper": {"available": True},
            "funasr": {"available": True},
            "whisperx": {"available": True},
        }}, {
            "language": "zh-CN",
            "project_terms": {"products": ["ExplainIt"]},
            "profile_terms": {"english_terms": ["RAG"]},
            "noise_score": 0.82,
            "existing_captions": {"available": True, "sha256": "a" * 64},
            "timing_drift_seconds": 0.24,
            "drift_threshold_seconds": 0.12,
        })
        self.assertEqual(route["selected_backend"], "funasr")
        self.assertIn("ExplainIt", route["evidence"]["hotwords"])
        self.assertIn("RAG", route["evidence"]["hotwords"])
        self.assertTrue(route["evidence"]["forced_alignment_triggered"])
        self.assertIn({"role": "alignment", "backend": "whisperx"}, route["pipeline"])
        self.assertEqual(route["evidence"]["existing_captions_sha256"], "a" * 64)
        self.assertEqual(route["ownership"]["timeline_and_edl"], "video-use")
        self.assertEqual(len(route["route_input_sha256"]), 64)

    def test_drift_triggered_alignment_fails_closed_without_backend(self) -> None:
        with self.assertRaisesRegex(AsrCapabilityError, "word_alignment"):
            choose_pipeline({"backends": {
                "local_faster_whisper": {"available": True},
                "funasr": {"available": True},
                "whisperx": {"available": False},
            }}, {
                "language": "zh",
                "timing_drift_seconds": 0.3,
                "drift_threshold_seconds": 0.1,
            })

    def test_optional_diarization_and_labels_require_real_backend(self) -> None:
        route = choose_pipeline({"backends": {
            "local_faster_whisper": {"available": True},
            "funasr": {"available": True},
            "whisperx": {"available": True},
        }}, {"language": "zh", "diarization": True, "speaker_labels": True})
        self.assertIn({"role": "diarization", "backend": "whisperx"}, route["pipeline"])
        self.assertIn("diarization", route["required_capabilities"])

    def test_quality_report_is_bound_to_route_transcript_and_media(self) -> None:
        transcript = normalize_transcript({"words": [
            {"text": "ExplainIt", "start": 0.0, "end": 0.5, "speaker": "S1"},
        ]}, backend="whisperx")
        route = choose_pipeline({"backends": {
            "local_faster_whisper": {"available": True},
            "funasr": {"available": True},
            "whisperx": {"available": True},
        }}, {"language": "zh", "hotwords": ["ExplainIt"]})
        report = build_asr_quality_report(
            transcript,
            route=route,
            source_media_sha256="b" * 64,
            measured_drift_seconds=0.05,
            drift_threshold_seconds=0.12,
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["route_sha256"], route_sha256(route))
        self.assertEqual(report["transcript_sha256"], transcript_sha256(transcript))
        self.assertEqual(report["source_media_sha256"], "b" * 64)
        self.assertEqual(report["ownership"]["transcript_and_timeline"], "video-use")
        with self.assertRaisesRegex(ValueError, "source_media_sha256"):
            build_asr_quality_report(
                transcript, route=route, source_media_sha256="stale",
                measured_drift_seconds=0.05, drift_threshold_seconds=0.12,
            )
        with self.assertRaisesRegex(ValueError, "route_sha256"):
            build_asr_quality_report(
                transcript,
                route={**route, "reason": "tampered after routing"},
                source_media_sha256="b" * 64,
                measured_drift_seconds=0.05,
                drift_threshold_seconds=0.12,
            )

    def test_route_rejects_nonfinite_or_malformed_routing_evidence(self) -> None:
        config = {"backends": {
            "local_faster_whisper": {"available": True},
            "funasr": {"available": True},
            "whisperx": {"available": True},
        }}
        for evidence, message in (
            ({"noise_score": float("nan")}, "noise_score"),
            ({"noise_score": 1.1}, "noise_score"),
            ({"timing_drift_seconds": float("inf")}, "timing_drift_seconds"),
            ({"drift_threshold_seconds": 0}, "drift_threshold_seconds"),
            ({"speaker_count": True}, "speaker_count"),
            ({"speaker_count": 0}, "speaker_count"),
            ({"project_terms": {"urls": "not-a-list"}}, "urls"),
            ({"existing_captions": {"available": True}}, "sha256"),
            ({"existing_captions": {"available": True, "sha256": "bad"}}, "sha256"),
        ):
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, message):
                choose_pipeline(config, evidence)

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

    def test_combines_hotword_transcription_with_precise_alignment(self) -> None:
        route = choose_pipeline({"backends": {
            "local_faster_whisper": {"available": True},
            "funasr": {"available": True},
            "whisperx": {"available": True},
        }}, {
            "language": "zh", "hotwords": ["ExplainIt"],
            "precise_word_alignment": True, "speaker_labels": True,
        })
        self.assertEqual(route["pipeline"][0]["backend"], "funasr")
        self.assertEqual(route["pipeline"][0]["role"], "transcription")
        self.assertIn({"role": "alignment", "backend": "whisperx"}, route["pipeline"])
        self.assertEqual(route["missing_required_capabilities"], [])

    def test_required_capability_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(AsrCapabilityError, "word_alignment"):
            choose_pipeline({"backends": {
                "local_faster_whisper": {"available": True},
                "funasr": {"available": True},
                "whisperx": {"available": False},
            }}, {"language": "zh", "required_capabilities": ["word_alignment"]})

    def test_speaker_and_alignment_reports_are_hash_bound_and_complete(self) -> None:
        transcript = normalize_transcript({"words": [
            {"text": "one", "start": 0.0, "end": 0.4, "speaker": "S1"},
            {"text": "two", "start": 0.5, "end": 0.9, "speaker": "S2"},
        ]}, backend="whisperx")
        digest = transcript_sha256(transcript)
        route = {"required_capabilities": ["speaker_labels", "word_alignment"]}
        speaker = {"status": "pass", "transcript_sha256": digest, "labeled_word_count": 2}
        alignment = {"status": "pass", "transcript_sha256": digest, "aligned_word_count": 2}
        report = validate_pipeline_reports(
            transcript, route=route, speaker_report=speaker, alignment_report=alignment,
        )
        self.assertEqual(report["status"], "pass")
        with self.assertRaisesRegex(ValueError, "hash"):
            validate_pipeline_reports(
                transcript, route=route,
                speaker_report={**speaker, "transcript_sha256": "0" * 64},
                alignment_report=alignment,
            )
        with self.assertRaisesRegex(ValueError, "aligned_word_count"):
            validate_pipeline_reports(
                transcript, route=route, speaker_report=speaker,
                alignment_report={**alignment, "aligned_word_count": 1},
            )

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
