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
from evidence_acquisition import (  # noqa: E402
    acquire, build_evidence_bundle, extract_frames, representative_timestamps,
)


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
            self.assertIsNone(bundle["representative_frames"][0]["timestamp_seconds"])
            self.assertEqual(
                bundle["representative_frames"][0]["sampling_policy"], "legacy_unspecified",
            )
            self.assertIn("palette", bundle["design_tokens"])
            self.assertEqual(bundle["optional_adapters"]["pyscenedetect"]["status"], "disabled")

    def test_representative_timestamps_cover_medium_videos_without_unbounded_growth(self) -> None:
        short = representative_timestamps(30.0)
        six_minutes = representative_timestamps(6 * 60.0)
        ten_minutes = representative_timestamps(10 * 60.0)
        very_long = representative_timestamps(4 * 60 * 60.0)

        self.assertLessEqual(len(short), 5)
        self.assertGreater(len(six_minutes), 5)
        self.assertGreater(len(ten_minutes), len(six_minutes))
        self.assertLessEqual(len(very_long), 32)
        self.assertEqual(len(ten_minutes), 32)
        for duration, timestamps in ((360.0, six_minutes), (600.0, ten_minutes)):
            self.assertEqual(timestamps, sorted(set(timestamps)))
            self.assertLessEqual(timestamps[0], 0.5)
            self.assertGreaterEqual(timestamps[-1], duration - 0.5)
            self.assertLessEqual(
                max(right - left for left, right in zip(timestamps, timestamps[1:])),
                20.0,
            )

    def test_acquire_records_timestamp_filename_coverage_and_sampling_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "source.mp4"
            media.write_bytes(b"fixture")
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            probe = {
                "format": {"duration": "60.0"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            }

            def fake_run(command, **_kwargs):
                Image.new("RGB", (32, 18), "#335577").save(Path(command[-1]))

            with patch("evidence_acquisition.probe_media", return_value=probe), \
                    patch("evidence_acquisition.subprocess.run", side_effect=fake_run):
                bundle_path = acquire(
                    media=media, transcript_path=transcript, output_dir=root / "evidence",
                )

            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            timestamps = representative_timestamps(60.0)
            sampling = bundle["representative_frame_sampling"]
            self.assertEqual(sampling["policy"], "bounded_uniform_full_duration_v1")
            self.assertEqual(sampling["target_interval_seconds"], 15.0)
            self.assertEqual(sampling["maximum_frame_count"], 32)
            self.assertEqual(sampling["requested_frame_count"], len(timestamps))
            self.assertEqual(sampling["extracted_frame_count"], len(timestamps))
            self.assertEqual(sampling["coverage"]["start_seconds"], 0.0)
            self.assertEqual(sampling["coverage"]["end_seconds"], 60.0)

            records = bundle["representative_frames"]
            self.assertEqual(len(records), len(timestamps))
            for index, (record, timestamp) in enumerate(zip(records, timestamps)):
                self.assertEqual(record["timestamp_seconds"], timestamp)
                self.assertEqual(record["sampling_policy"], sampling["policy"])
                self.assertTrue(record["path"].endswith(f"-{timestamp:08.3f}.png"))
                self.assertLessEqual(record["coverage"]["start_seconds"], timestamp)
                self.assertGreaterEqual(record["coverage"]["end_seconds"], timestamp)
                if index:
                    self.assertEqual(
                        records[index - 1]["coverage"]["end_seconds"],
                        record["coverage"]["start_seconds"],
                    )
            self.assertEqual(records[0]["coverage"]["start_seconds"], 0.0)
            self.assertEqual(records[-1]["coverage"]["end_seconds"], 60.0)

    def test_acquire_fails_closed_when_only_a_subset_of_requested_frames_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "source.mp4"
            media.write_bytes(b"fixture")
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            probe = {
                "format": {"duration": "60.0"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            }

            def partial_extract(_media, timestamps, output_dir):
                frame_dir = output_dir / "frames"
                frame_dir.mkdir(parents=True)
                path = frame_dir / f"frame-00-{timestamps[0]:08.3f}.png"
                Image.new("RGB", (32, 18), "#335577").save(path)
                return [path]

            with patch("evidence_acquisition.probe_media", return_value=probe), \
                    patch("evidence_acquisition.extract_frames", side_effect=partial_extract):
                with self.assertRaisesRegex(RuntimeError, "requested.*extracted"):
                    acquire(
                        media=media, transcript_path=transcript,
                        output_dir=root / "evidence",
                    )
            self.assertFalse((root / "evidence" / "evidence-bundle.json").exists())

    def test_acquire_fails_closed_when_extracted_timestamps_do_not_match_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "source.mp4"
            media.write_bytes(b"fixture")
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            probe = {
                "format": {"duration": "30.0"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            }

            def shifted_extract(_media, timestamps, output_dir):
                frame_dir = output_dir / "frames"
                frame_dir.mkdir(parents=True)
                frames = []
                for index, timestamp in enumerate(timestamps):
                    shifted = timestamp + (0.25 if index == 0 else 0.0)
                    path = frame_dir / f"frame-{index:02d}-{shifted:08.3f}.png"
                    Image.new("RGB", (32, 18), "#335577").save(path)
                    frames.append(path)
                return frames

            with patch("evidence_acquisition.probe_media", return_value=probe), \
                    patch("evidence_acquisition.extract_frames", side_effect=shifted_extract):
                with self.assertRaisesRegex(RuntimeError, "timestamps do not match"):
                    acquire(
                        media=media, transcript_path=transcript,
                        output_dir=root / "evidence",
                    )

    def test_known_partial_frames_report_actual_gap_without_full_duration_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frames = []
            for index in range(2):
                frame = root / f"sample-{index}.png"
                Image.new("RGB", (32, 18), "#335577").save(frame)
                frames.append(frame)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            media = root / "source.mp4"
            media.write_bytes(b"fixture")
            probe = {
                "format": {"duration": "60.0"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            }

            bundle = build_evidence_bundle(
                media, transcript, probe, frames, frame_timestamps=[10.0, 50.0],
            )

            sampling = bundle["representative_frame_sampling"]
            self.assertEqual(bundle["status"], "partial")
            self.assertEqual(sampling["coverage"]["status"], "partial")
            self.assertEqual(sampling["coverage"]["start_seconds"], 10.0)
            self.assertEqual(sampling["coverage"]["end_seconds"], 50.0)
            self.assertEqual(sampling["coverage"]["maximum_sample_gap_seconds"], 40.0)
            self.assertEqual(bundle["representative_frames"][0]["coverage"], {
                "start_seconds": 10.0, "end_seconds": 30.0,
            })
            self.assertEqual(bundle["representative_frames"][1]["coverage"], {
                "start_seconds": 30.0, "end_seconds": 50.0,
            })

    def test_known_single_frame_never_claims_full_duration_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frame = root / "sample.png"
            Image.new("RGB", (32, 18), "#335577").save(frame)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            media = root / "source.mp4"
            media.write_bytes(b"fixture")
            probe = {
                "format": {"duration": "60.0"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            }

            bundle = build_evidence_bundle(
                media, transcript, probe, [frame], frame_timestamps=[30.0],
            )

            sampling = bundle["representative_frame_sampling"]
            self.assertEqual(bundle["status"], "partial")
            self.assertEqual(sampling["coverage"]["status"], "partial")
            self.assertEqual(sampling["coverage"]["start_seconds"], 30.0)
            self.assertEqual(sampling["coverage"]["end_seconds"], 30.0)
            self.assertEqual(bundle["representative_frames"][0]["coverage"], {
                "start_seconds": 30.0, "end_seconds": 30.0,
            })

    def test_unverifiable_sampling_policy_cannot_upgrade_partial_frames_to_full(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frames = []
            for index in range(2):
                frame = root / f"sample-{index}.png"
                Image.new("RGB", (32, 18), "#335577").save(frame)
                frames.append(frame)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            media = root / "source.mp4"
            media.write_bytes(b"fixture")
            probe = {
                "format": {"duration": "60.0"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            }

            bundle = build_evidence_bundle(
                media,
                transcript,
                probe,
                frames,
                frame_timestamps=[10.0, 50.0],
                sampling_policy={
                    "policy": "bounded_uniform_full_duration_v1",
                    "requested_frame_count": 5,
                    "coverage": {"status": "full_duration"},
                },
            )

            sampling = bundle["representative_frame_sampling"]
            self.assertFalse(sampling["timestamps_match_request"])
            self.assertEqual(sampling["requested_frame_count"], 5)
            self.assertEqual(sampling["coverage"]["status"], "partial")
            self.assertEqual(sampling["coverage"]["start_seconds"], 10.0)
            self.assertEqual(sampling["coverage"]["end_seconds"], 50.0)

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
