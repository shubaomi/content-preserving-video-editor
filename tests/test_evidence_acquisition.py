from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director import Director  # noqa: E402
from director_contracts import (  # noqa: E402
    DirectorContractError, STAGES, sha256_file, validate_semantic_brief,
    validate_semantic_evidence_binding,
)
from evidence_acquisition import build_evidence_bundle, extract_frames  # noqa: E402


class EvidenceAcquisitionTests(unittest.TestCase):
    def test_lightweight_bundle_records_display_transcript_frames_and_design_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frame = root / "frame.png"
            Image.new("RGB", (320, 180), "#f2f0e8").save(frame)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "type": "word", "text": "示例", "start": 0.0, "end": 0.5}
            ]}), encoding="utf-8")
            media = root / "source.mp4"
            media.write_bytes(b"fixture")
            probe = {
                "format": {"duration": "12.0"},
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080,
                     "side_data_list": [{"rotation": 90}]},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }

            bundle = build_evidence_bundle(media, transcript, probe, [frame])

            self.assertEqual(bundle["display"]["width"], 1080)
            self.assertEqual(bundle["display"]["height"], 1920)
            self.assertEqual(bundle["display"]["orientation"], "portrait")
            self.assertEqual(bundle["transcript"]["word_count"], 1)
            self.assertEqual(bundle["representative_frames"][0]["path"], str(frame.resolve()))
            self.assertIn("palette", bundle["design_tokens"])
            self.assertEqual(bundle["optional_adapters"]["pyscenedetect"]["status"], "disabled")

    def test_director_has_real_evidence_stage_and_completes_with_generated_bundle(self) -> None:
        self.assertLess(STAGES.index("evidence_acquisition"), STAGES.index("semantic_brief"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"fixture")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "version": 1,
                "video_id": "fixture",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4", "input_mode": "raw"},
            }), encoding="utf-8")
            director = Director(project)
            transcript = director.video_use_dir / "transcripts" / "input.json"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "type": "word", "text": "内容", "start": 0, "end": 1}
            ]}), encoding="utf-8")

            def fake_acquire(**kwargs):
                output = kwargs["output_dir"] / "evidence-bundle.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({
                    "schema_version": 1, "status": "pass",
                    "source": {"sha256": sha256_file(source)},
                    "transcript": {"sha256": sha256_file(transcript)},
                    "representative_frames": [],
                }), encoding="utf-8")
                return output

            director._start("evidence_acquisition")
            with patch("director.acquire_evidence", side_effect=fake_acquire) as acquire:
                director.stage_evidence_acquisition()

            self.assertEqual(acquire.call_count, 1)
            self.assertEqual(director.state["stages"]["evidence_acquisition"]["status"], "complete")

    def test_schema_two_visual_beat_requires_evidence_and_motion_audio_contract(self) -> None:
        event = {
            "id": "beat-1", "anchor": "可审计时间线", "transcript_quote": "生成可审计时间线",
            "transcript_word_ids": ["w1", "w2"], "source_start": 1.0, "source_end": 2.0,
            "output_start": 1.0, "output_end": 2.0, "viewer_job": "understand_process",
            "relevance_rationale": "解释输入如何变成时间线", "viewer_takeaway": "结果可追踪",
            "visual_mechanism": "three-step process path", "target_frame_evidence": ["frame.png"],
            "protected_zones": {"face": [], "ui": [], "caption": [], "cursor": []},
            "form": "process", "placement": "right", "size": "medium", "background": "transparent",
            "read_time": 1.0,
            "motion": {"entrance": "fade", "reveal": "step", "hold": "steady", "exit": "fade"},
            "audio_decision": {"type": "cue", "family": "soft-process"},
            "deduplication": {"semantic": "unique", "visual": "unique"},
            "visual_structure": {
                "dom_structure": "path", "information_hierarchy": "input-to-output",
                "layout_archetype": "horizontal-flow", "animation_choreography": "sequential",
                "use_case": "process-explanation",
            },
        }
        brief = {
            "schema_version": 2, "generated_by": "test-llm",
            "content_reading": "raw_word_transcript_and_evidence_frames",
            "transcript_sha256": "a" * 64, "evidence_bundle_sha256": "b" * 64,
            "evidence_frames": ["frame.png"],
            "opening_hook": {"status": "not_selected", "evidence": ["intro is already specific"]},
            "events": [event],
        }
        self.assertEqual(validate_semantic_brief(brief), [])
        del event["viewer_takeaway"]
        self.assertIn("viewer_takeaway", "\n".join(validate_semantic_brief(brief)))

    def test_enabled_subject_tracking_is_invoked_through_hash_bound_adapter(self) -> None:
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
                "workflow": {"capabilities": {"subject_tracking": {"enabled": True}}},
            }), encoding="utf-8")
            director = Director(project)
            transcript = director.video_use_dir / "transcripts" / "input.json"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "type": "word", "text": "内容", "start": 0, "end": 1}
            ]}), encoding="utf-8")

            def fake_acquire(**kwargs):
                output = kwargs["output_dir"] / "evidence-bundle.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({
                    "schema_version": 1, "status": "pass",
                    "source": {"sha256": sha256_file(source)},
                    "transcript": {"sha256": sha256_file(transcript)},
                    "representative_frames": [],
                    "display": {"orientation": "portrait", "width": 1080, "height": 1920},
                    "design_tokens": {"palette": []},
                }), encoding="utf-8")
                return output

            with patch("director.acquire_evidence", side_effect=fake_acquire):
                with patch.object(director.adapter_runner, "run", return_value={
                    "status": "complete", "outputs": []
                }) as run:
                    director._start("evidence_acquisition")
                    director.stage_evidence_acquisition()

            names = [call.kwargs["name"] for call in run.call_args_list]
            self.assertIn("subject_tracking", names)
            command = next(call.kwargs["command"] for call in run.call_args_list
                           if call.kwargs["name"] == "subject_tracking")
            self.assertIn("analyze_subject_track.py", " ".join(command))

    def test_evidence_stage_rejects_missing_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"fixture")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "version": 1, "video_id": "fixture",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4", "input_mode": "raw"},
            }), encoding="utf-8")
            director = Director(project)
            transcript = director.video_use_dir / "transcripts" / "input.json"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "type": "word", "text": "内容", "start": 0, "end": 1}
            ]}), encoding="utf-8")

            def fake_acquire(**kwargs):
                output = kwargs["output_dir"] / "evidence-bundle.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({"schema_version": 1, "source": {}}), encoding="utf-8")
                return output

            director._start("evidence_acquisition")
            with patch("director.acquire_evidence", side_effect=fake_acquire):
                with self.assertRaisesRegex(DirectorContractError, "source hash"):
                    director.stage_evidence_acquisition()

    def test_semantic_brief_is_bound_to_current_transcript_and_declared_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "input.json"
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "type": "word", "text": "audit", "start": 1.0, "end": 1.4},
                {"id": "w2", "type": "word", "text": "trail", "start": 1.5, "end": 2.0},
            ]}), encoding="utf-8")
            frame = root / "frame.png"
            frame.write_bytes(b"frame")
            bundle_path = root / "evidence-bundle.json"
            bundle_path.write_text(json.dumps({
                "transcript": {"sha256": sha256_file(transcript), "term_evidence": [
                    {"word_id": "w1", "text": "audit", "start": 1.0, "end": 1.4},
                    {"word_id": "w2", "text": "trail", "start": 1.5, "end": 2.0},
                ]},
                "representative_frames": [{"path": str(frame), "sha256": sha256_file(frame)}],
            }), encoding="utf-8")
            brief = {
                "schema_version": 2,
                "transcript_sha256": sha256_file(transcript),
                "evidence_bundle_sha256": sha256_file(bundle_path),
                "evidence_frames": [str(frame)],
                "events": [{
                    "id": "event-1", "transcript_word_ids": ["w1", "w2"],
                    "transcript_quote": "audit trail", "source_start": 1.0, "source_end": 2.0,
                    "target_frame_evidence": [str(frame)],
                }],
            }
            self.assertEqual(validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path), [])

            brief["events"][0]["target_frame_evidence"] = [str(root / "stale.png")]
            errors = validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path)
            self.assertTrue(any("undeclared target frame" in error for error in errors))
            brief["events"][0]["target_frame_evidence"] = [str(frame)]
            brief["transcript_sha256"] = "0" * 64
            errors = validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path)
            self.assertTrue(any("current transcript" in error for error in errors))

    def test_frame_extraction_removes_stale_managed_frames_before_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            frame_dir = output / "frames"
            frame_dir.mkdir()
            stale = frame_dir / "frame-99-stale.png"
            stale.write_bytes(b"stale")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"fresh")

            with patch("evidence_acquisition.subprocess.run", side_effect=fake_run):
                frames = extract_frames(Path("source.mp4"), [0.5], output)
            self.assertFalse(stale.exists())
            self.assertEqual(len(frames), 1)

    def test_configured_scene_and_ocr_adapters_are_merged_into_evidence_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"fixture")
            scene = root / "work" / "scene.json"
            ocr = root / "work" / "ocr.json"
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "schema_version": 5, "version": 5, "video_id": "fixture",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4", "input_mode": "raw"},
                "analysis": {"adapters": {
                    "pyscenedetect": {"enabled": True, "command": ["scene"], "outputs": [str(scene)]},
                    "paddleocr": {"enabled": True, "command": ["ocr"], "outputs": [str(ocr)]},
                }},
            }), encoding="utf-8")
            director = Director(project)
            transcript = director.video_use_dir / "transcripts" / "input.json"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "type": "word", "text": "content", "start": 0, "end": 1}
            ]}), encoding="utf-8")

            def fake_acquire(**kwargs):
                output = kwargs["output_dir"] / "evidence-bundle.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({
                    "schema_version": 1, "source": {"sha256": sha256_file(source)},
                    "transcript": {"sha256": sha256_file(transcript)},
                    "representative_frames": [], "optional_adapters": {},
                    "design_tokens": {}, "display": {"orientation": "landscape"},
                }), encoding="utf-8")
                return output

            def fake_run(**kwargs):
                output = kwargs["outputs"][0]
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({"status": "pass", "name": kwargs["name"]}), encoding="utf-8")
                return {"status": "complete"}

            director._start("evidence_acquisition")
            with patch("director.acquire_evidence", side_effect=fake_acquire), \
                    patch.object(director.adapter_runner, "run", side_effect=fake_run):
                director.stage_evidence_acquisition()
            bundle = json.loads(director.evidence_bundle_path.read_text(encoding="utf-8"))
            self.assertEqual(bundle["optional_adapters"]["pyscenedetect"]["status"], "complete")
            self.assertEqual(bundle["scene_evidence"]["name"], "scene_detection")
            self.assertEqual(bundle["ocr"]["name"], "ocr")


if __name__ == "__main__":
    unittest.main()
