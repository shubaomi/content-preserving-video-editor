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

from director import Director, ROLE_CONTRACT, approve_sample, authorize_final_render  # noqa: E402
from director_contracts import DirectorContractError, VISUAL_VOCABULARY, sha256_file  # noqa: E402


class DirectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = self.root / "source" / "published.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"source-media")
        self.project = self.root / "project.yaml"
        self.project.write_text(yaml.safe_dump({
            "version": 1,
            "video_id": "sample",
            "paths": {"root": str(self.root), "work": "work", "edit": "edit", "exports": "exports"},
            "source": {"primary_video": "source/published.mp4", "input_mode": "existing_edit_polish"},
            "delivery": {"output": "exports/sample-universal.mp4"},
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_full_hyperframes_contract(self, director: Director, duration: float = 100.0) -> None:
        project = director.full_hyperframes_project
        project.mkdir(parents=True)
        transcript = director.video_use_dir / "transcripts" / f"{director.context.source_video.stem}.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": [{"type": "word", "text": "proof", "start": 0, "end": 1}]}), encoding="utf-8")
        events = []
        for index in range(4):
            events.append({
                "id": f"full-{index}",
                "treatment": "structure",
                "visual_structure": {
                    "dom_structure": f"dom-{index}",
                    "information_hierarchy": f"hierarchy-{index}",
                    "layout_archetype": f"layout-{index}",
                    "animation_choreography": f"motion-{index}",
                    "use_case": f"case-{index}",
                },
            })
        full_brief = {
            "schema_version": 1,
            "generated_by": "test-llm",
            "content_reading": "raw_word_transcript_and_evidence_frames",
            "transcript_sha256": sha256_file(transcript),
            "evidence_frames": ["frame.png"],
            "scope": {"source_start": 0, "source_end": 100.0},
            "events": [
                {
                    **event,
                    "anchor": f"anchor-{index}",
                    "transcript_quote": "direct transcript evidence",
                    "transcript_word_ids": [index],
                    "source_start": float(index * 20),
                    "relevance_rationale": "verified semantic event",
                }
                for index, event in enumerate(events)
            ],
        }
        director.full_semantic_brief_path.write_text(json.dumps(full_brief), encoding="utf-8")
        storyboard = {
            "renderer": "hyperframes",
            "motion_output": "hyperframes_render",
            "capability_skills": ["hyperframes", "hyperframes-core", "hyperframes-creative",
                                  "hyperframes-animation", "hyperframes-cli"],
            "composition": {"duration": duration},
            "events": events,
        }
        (project / "storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")
        categories = {}
        for index, name in enumerate(VISUAL_VOCABULARY):
            if index < 4:
                categories[name] = {"status": "selected", "event_ids": [f"full-{index}"],
                                    "evidence": [f"snapshot-{index}.png"]}
            else:
                categories[name] = {"status": "not_applicable", "rationale": "not in verified transcript",
                                    "evidence": ["transcript.json"]}
        audit = {
            "categories": categories,
            "chapter_decisions": [{"chapter_id": "chapter-1", "evidence": ["transcript.json"],
                                   "selected_categories": [VISUAL_VOCABULARY[0]]}],
        }
        (project / "visual-vocabulary-audit.json").write_text(json.dumps(audit), encoding="utf-8")
        (project / "index.html").write_text("<main data-composition></main>", encoding="utf-8")
        (project / "frame.md").write_text("# Design", encoding="utf-8")
        edl = director.video_use_dir / "edl.json"
        edl.parent.mkdir(parents=True, exist_ok=True)
        edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 100}]}), encoding="utf-8")

    def _write_passing_sample_evidence(self, director: Director) -> tuple[Path, Path, Path]:
        sample = director.sample_hyperframes_project
        sample.mkdir(parents=True, exist_ok=True)
        storyboard = sample / "storyboard.json"
        storyboard.write_text(json.dumps({"renderer": "hyperframes", "events": []}), encoding="utf-8")
        qa = director.root / "sample-qa"
        qa.mkdir(parents=True, exist_ok=True)
        review = qa / "aesthetic-review.json"
        review.write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")
        gate = qa / "gate-report.json"
        gate.write_text(json.dumps({"passed": True}), encoding="utf-8")
        director.state["stages"]["sample_qa"]["status"] = "complete"
        director._save()
        return storyboard, review, gate

    def _pass_full_hyperframes_qa(self, director: Director) -> None:
        qa = director.root / "full-qa"
        qa.mkdir(parents=True, exist_ok=True)
        check = {
            "ok": True,
            "lint": {"ok": True, "errorCount": 0},
            "runtime": {"ok": True, "errorCount": 0},
            "layout": {"ok": True, "errorCount": 0},
            "motion": {"ok": True, "errorCount": 0, "enabled": True},
            "contrast": {"ok": True, "errorCount": 0},
        }
        (qa / "hyperframes-check.json").write_text(json.dumps(check), encoding="utf-8")
        snapshots = []
        for index in range(4):
            path = qa / f"snapshot-{index}.png"
            path.write_bytes(b"png")
            snapshots.append(str(path))
        review = {
            "status": "pass",
            "reviewed_snapshots": snapshots,
            "checks": {name: "pass" for name in (
                "content_relevance", "visual_variety", "overlap", "overflow",
                "caption_face_cursor_ui_safety", "motion_rhythm",
            )},
        }
        (qa / "snapshot-review.json").write_text(json.dumps(review), encoding="utf-8")
        studio = qa / "parity-studio.png"
        rendered = qa / "parity-render.png"
        studio.write_bytes(b"png")
        rendered.write_bytes(b"png")
        parity = {
            "schema_version": 1,
            "status": "pass",
            "tolerances": {"position_px": 4, "size_px": 4, "time_seconds": 0.05},
            "samples": [{
                "event_id": "full-0", "time_seconds": 10.0,
                "studio_snapshot": str(studio), "render_snapshot": str(rendered),
                "animation_phase": {"studio": "midpoint", "render": "midpoint"},
                "elements": [{
                    "selector": "#event",
                    "studio": {"x": 1, "y": 2, "width": 100, "height": 50, "visible": True},
                    "render": {"x": 2, "y": 2, "width": 100, "height": 51, "visible": True},
                }],
                "connectors": {"expected_count": 0, "studio_count": 0, "render_count": 0,
                               "all_endpoints_attached": True, "clipped": False},
                "cropping": {"studio_clipped": False, "render_clipped": False},
                "caption_occlusion": {"studio": False, "render": False},
            }],
        }
        (qa / "preview-render-parity.json").write_text(json.dumps(parity), encoding="utf-8")
        director._start("full_hyperframes_qa")
        director.stage_full_hyperframes_qa()

    def test_state_is_resumable_and_records_professional_roles(self) -> None:
        director = Director(self.project)
        director._start("inspect")
        director.stage_inspect()
        resumed = Director(self.project)
        self.assertEqual(resumed.state["stages"]["inspect"]["status"], "complete")
        contract = json.loads((self.root / "work" / "director" / "workflow-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["roles"], ROLE_CONTRACT)
        self.assertEqual(contract["project_scripts_execution"], "forbidden")
        self.assertEqual(contract["motion_renderer"], "hyperframes")

    def test_revalidating_upstream_stage_preserves_downstream_action_required(self) -> None:
        director = Director(self.project)
        director._start("preview_approval")
        with self.assertRaisesRegex(ValueError, "User approval"):
            director.stage_preview_approval()
        action_before = json.loads(director.action_path.read_text(encoding="utf-8"))
        director._start("inspect")
        director.stage_inspect()
        state = json.loads(director.state_path.read_text(encoding="utf-8"))
        action_after = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "action_required")
        self.assertEqual(state["current_stage"], "preview_approval")
        self.assertEqual(action_before["stage"], action_after["stage"])

    def test_undeclared_input_mode_runs_analysis_and_caches_hash_bound_decision(self) -> None:
        recording = self.root / "source" / "recording.mp4"
        recording.write_bytes(b"source-media")
        project = self.root / "auto-project.yaml"
        project.write_text(yaml.safe_dump({
            "version": 1,
            "video_id": "auto",
            "paths": {"root": str(self.root), "work": "auto-work", "edit": "edit", "exports": "exports"},
            "source": {"primary_video": "source/recording.mp4"},
        }), encoding="utf-8")
        director = Director(project)
        self.assertEqual(director.context.input_mode, "needs_analysis")

        def fake_analysis(command, **_kwargs):
            output = Path(command[command.index("--out") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({
                "captions": {
                    "subtitle_streams": [],
                    "burned_in": {"detected": True, "confidence": 0.91},
                }
            }), encoding="utf-8")

        director._start("inspect")
        with patch("director.subprocess.run", side_effect=fake_analysis) as run:
            director.stage_inspect()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(director.context.input_mode, "polish_existing")
        evidence = json.loads((director.root / "input-mode-evidence.json").read_text(encoding="utf-8"))
        self.assertIn("high_confidence_burned_captions", evidence["signals"])
        resumed = Director(project)
        self.assertEqual(resumed.context.input_mode, "polish_existing")

    def test_missing_word_transcript_stops_at_exact_stage_with_action_packet(self) -> None:
        director = Director(self.project)
        director._start("video_use_timeline")
        with self.assertRaisesRegex(ValueError, "valid video-use"):
            director.stage_video_use_timeline()
        state = json.loads(director.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["stages"]["video_use_timeline"]["status"], "action_required")
        action = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["actions"][0]["owner"], "video-use")

    def test_missing_edl_is_delegated_to_video_use_instead_of_authored_by_director(self) -> None:
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"words": [
            {"type": "word", "text": "原话", "start": 0.1, "end": 0.5}
        ]}, ensure_ascii=False), encoding="utf-8")
        director._start("video_use_timeline")
        with patch("director._ffprobe_duration", return_value=100.0):
            with self.assertRaisesRegex(ValueError, "video-use must author the EDL"):
                director.stage_video_use_timeline()
        self.assertFalse((director.video_use_dir / "edl.json").exists())
        request = json.loads((director.video_use_dir / "edl-request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["delegate_to"], "video-use")
        action = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["actions"][0]["owner"], "video-use")

    def test_director_rejects_edl_that_claims_its_own_cut_decisions(self) -> None:
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"words": [
            {"type": "word", "text": "原话", "start": 0.1, "end": 0.5}
        ]}, ensure_ascii=False), encoding="utf-8")
        edl = director.video_use_dir / "edl.json"
        edl.write_text(json.dumps({
            "owner": "director", "sources": {"published": "source/published.mp4"},
            "ranges": [{"source": "published", "start": 0, "end": 100}],
            "cut_policy": {"word_boundary_padding_ms": [30, 100], "audio_fade_ms": 30},
        }), encoding="utf-8")
        director._start("video_use_timeline")
        with patch("director._ffprobe_duration", return_value=100.0):
            with self.assertRaisesRegex(ValueError, "owner must be video-use"):
                director.stage_video_use_timeline()

    def test_missing_media_analysis_and_correctness_are_delegated_to_video_use(self) -> None:
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"words": [
            {"type": "word", "text": "原话", "start": 0.1, "end": 0.5}
        ]}, ensure_ascii=False), encoding="utf-8")
        edl = director.video_use_dir / "edl.json"
        edl.write_text(json.dumps({
            "owner": "video-use", "sources": {"published": "source/published.mp4"},
            "ranges": [{"source": "published", "start": 0, "end": 100}],
            "cut_policy": {"word_boundary_padding_ms": [30, 100], "audio_fade_ms": 30},
        }), encoding="utf-8")
        director._start("video_use_timeline")
        with patch("director._ffprobe_duration", return_value=100.0):
            with self.assertRaisesRegex(ValueError, "media analysis and EDL correctness"):
                director.stage_video_use_timeline()
        request = json.loads((director.video_use_dir / "analysis-request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["delegate_to"], "video-use")
        self.assertEqual(len(request["timeline_view_commands"]), 3)
        self.assertEqual(float(request["timeline_view_commands"][-1][3]), 97.0)
        self.assertEqual(float(request["timeline_view_commands"][-1][4]), 99.9)

    def test_final_render_is_explicitly_gated(self) -> None:
        director = Director(self.project)
        director._start("final_render")
        with self.assertRaisesRegex(ValueError, "disabled"):
            director.stage_final_render()
        self.assertFalse(director.approve_final_render)

    def test_final_render_command_can_only_target_separate_full_project(self) -> None:
        director = Director(self.project, approve_final_render=True)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        authorize_final_render(Director(self.project), "hongr")
        director = Director(self.project, approve_final_render=True)
        director._start("final_render")
        with self.assertRaisesRegex(ValueError, "not present"):
            director.stage_final_render()
        action = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["actions"][0]["command"]["cwd"], str(director.full_hyperframes_project))
        self.assertNotEqual(director.full_hyperframes_project, director.sample_hyperframes_project)

    def test_final_render_resolves_command_shims_before_subprocess_launch(self) -> None:
        director = Director(self.project, approve_final_render=True)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        authorize_final_render(Director(self.project), "hongr")

        director = Director(
            self.project,
            approve_final_render=True,
            execute_external=True,
        )
        command_record = json.loads(
            (director.root / "full-hyperframes-commands.json").read_text(encoding="utf-8")
        )["final_motion_render"]
        output = Path(command_record["expected_artifact"])

        def fake_run(command: list[str], *, cwd: str, check: bool) -> None:
            self.assertEqual(command[0], r"C:\node\npx.CMD")
            self.assertEqual(cwd, command_record["cwd"])
            self.assertTrue(check)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"render")

        director._start("final_render")
        with patch("director.shutil.which", return_value=r"C:\node\npx.CMD") as which:
            with patch("director.subprocess.run", side_effect=fake_run):
                director.stage_final_render()

        which.assert_called_once_with("npx")
        self.assertEqual(director.state["stages"]["final_render"]["status"], "complete")

    def test_state_migration_adds_new_full_and_compose_stages_without_losing_completed_work(self) -> None:
        director = Director(self.project)
        director._start("inspect")
        director.stage_inspect()
        old = json.loads(director.state_path.read_text(encoding="utf-8"))
        old["stages"].pop("full_hyperframes_storyboard")
        old["stages"].pop("full_hyperframes_qa")
        old["stages"].pop("final_compose")
        director.state_path.write_text(json.dumps(old), encoding="utf-8")
        resumed = Director(self.project)
        self.assertEqual(resumed.state["stages"]["inspect"]["status"], "complete")
        self.assertEqual(resumed.state["stages"]["full_hyperframes_storyboard"]["status"], "pending")
        self.assertEqual(resumed.state["stages"]["full_hyperframes_qa"]["status"], "pending")
        self.assertEqual(resumed.state["stages"]["final_compose"]["status"], "pending")
        self.assertEqual(resumed.state["stages"]["manual_finish_handoff"]["status"], "pending")

    def test_manual_finish_disabled_is_a_noop_and_does_not_create_handoff_manifest(self) -> None:
        director = Director(self.project)
        director._start("manual_finish_handoff")
        director.stage_manual_finish_handoff()
        self.assertEqual(director.state["stages"]["manual_finish_handoff"]["status"], "complete")
        self.assertFalse((director.root / "manual-finish" / "handoff-manifest.json").exists())
        decision = json.loads((director.root / "manual-finish" / "decision.json").read_text(encoding="utf-8"))
        self.assertFalse(decision["enabled"])
        self.assertEqual(director.delivery_qa_output, director.delivery_output)

    def test_enabled_opencut_handoff_is_human_facing_and_action_required(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["delivery"]["manual_finish"] = {
            "enabled": True,
            "backend": "opencut",
            "modifications": [{"event_id": "event-1", "request": "move callout right"}],
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        output = director.delivery_output
        output.parent.mkdir(parents=True)
        output.write_bytes(b"automatic")
        director._start("manual_finish_handoff")
        with self.assertRaisesRegex(DirectorContractError, "human manual finishing"):
            director.stage_manual_finish_handoff()
        manifest = json.loads(
            (director.root / "manual-finish" / "handoff-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["backend"], "opencut")
        self.assertFalse(manifest["runtime_dependency_required"])
        self.assertEqual(manifest["automation_capabilities_claimed"], [])
        action = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["stage"], "manual_finish_handoff")
        self.assertEqual(action["actions"][0]["owner"], "human_editor")

    def test_returned_manual_file_invalidates_old_delivery_qa_and_requires_fresh_evidence(self) -> None:
        returned = self.root / "exports" / "sample-manual.mp4"
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["delivery"]["manual_finish"] = {
            "enabled": True,
            "backend": "other_nle",
            "returned_final": str(returned),
            "modifications": [],
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.delivery_output.parent.mkdir(parents=True)
        director.delivery_output.write_bytes(b"automatic")
        returned.write_bytes(b"manual")
        director.state["stages"]["delivery_qa"]["status"] = "complete"
        director._save()
        media_report = director.root / "manual-finish" / "manual-final-media-report.json"
        media_report.parent.mkdir(parents=True, exist_ok=True)
        media_report.write_text(json.dumps({
            "decode_status": "pass", "sha256": sha256_file(returned),
        }), encoding="utf-8")

        director._start("manual_finish_handoff")
        with patch.object(director, "_ensure_manual_return_media_report", return_value=media_report):
            with self.assertRaisesRegex(DirectorContractError, "revalidation"):
                director.stage_manual_finish_handoff()

        self.assertEqual(director.state["stages"]["delivery_qa"]["status"], "pending")
        receipt = json.loads(
            (director.root / "manual-finish" / "return-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["returned_final_sha256"], sha256_file(returned))
        self.assertEqual(director.delivery_qa_output, returned)

    def test_revalidated_manual_return_completes_and_later_byte_change_reopens_qa(self) -> None:
        returned = self.root / "exports" / "sample-manual.mp4"
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["delivery"]["manual_finish"] = {
            "enabled": True,
            "backend": "other_nle",
            "returned_final": str(returned),
            "modifications": [],
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.delivery_output.parent.mkdir(parents=True)
        director.delivery_output.write_bytes(b"automatic")
        returned.write_bytes(b"manual-v1")
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        (director.video_use_dir / "edl.json").write_text(json.dumps({
            "ranges": [{"start": 0, "end": 1}],
        }), encoding="utf-8")
        views = []
        for name in ("first", "middle", "last"):
            path = self.root / f"{name}.png"
            path.write_bytes(b"png")
            views.append(str(path))
        (director.video_use_dir / "final-edit-correctness.json").write_text(json.dumps({
            "owner": "video-use",
            "status": "pass",
            "output_sha256": sha256_file(returned),
            "expected_output_duration": 1,
            "actual_output_duration": 1,
            "boundary_reviews": [],
            "overview_timeline_views": views,
        }), encoding="utf-8")
        qa_evidence = []
        for name in ("captions", "audio", "visual"):
            path = self.root / f"{name}-qa.json"
            path.write_text("{}", encoding="utf-8")
            qa_evidence.append(str(path))
        manual_dir = director.manual_finish_dir
        manual_dir.mkdir(parents=True, exist_ok=True)
        (manual_dir / "manual-final-qa.json").write_text(json.dumps({
            "schema_version": 1,
            "status": "pass",
            "output_sha256": sha256_file(returned),
            "reviews": {
                "captions": {"status": "pass", "sample_count": 3, "evidence": [qa_evidence[0]]},
                "audio": {"status": "pass", "integrated_lufs": -14,
                          "true_peak_dbtp": -1.2, "evidence": [qa_evidence[1]]},
                "visual": {"status": "pass", "representative_frame_count": 3,
                           "evidence": [qa_evidence[2]]},
            },
        }), encoding="utf-8")
        media_report = manual_dir / "manual-final-media-report.json"
        media_report.write_text(json.dumps({
            "decode_status": "pass", "sha256": sha256_file(returned),
        }), encoding="utf-8")

        director._start("manual_finish_handoff")
        with patch.object(director, "_ensure_manual_return_media_report", return_value=media_report):
            director.stage_manual_finish_handoff()
        self.assertEqual(director.state["stages"]["manual_finish_handoff"]["status"], "complete")

        returned.write_bytes(b"manual-v2")
        reopened = Director(self.project)
        self.assertEqual(reopened.state["stages"]["manual_finish_handoff"]["status"], "pending")
        self.assertEqual(reopened.state["stages"]["delivery_qa"]["status"], "pending")
        invalidation = json.loads(
            (reopened.manual_finish_dir / "return-change-invalidation.json").read_text(encoding="utf-8")
        )
        self.assertIn("bytes changed", invalidation["reason"])

    def test_project_hardcoded_event_scripts_are_quarantined_not_executed(self) -> None:
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "legacy.py").write_text("events = [\n    {'id': 'old'}\n]\n", encoding="utf-8")
        director = Director(self.project)
        director._start("inspect")
        director.stage_inspect()
        audit = json.loads((director.root / "legacy-script-audit.json").read_text(encoding="utf-8"))
        self.assertFalse(audit["execution_allowed"])
        self.assertEqual(audit["findings"][0]["disposition"], "legacy_quarantined")
        self.assertNotIn(str(scripts / "legacy.py"), audit["director_execution_sources"])

    def test_final_compose_plans_exactly_one_universal_output(self) -> None:
        director = Director(self.project)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"hyperframes-render")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        director._start("final_compose")
        with self.assertRaisesRegex(ValueError, "universal"):
            director.stage_final_compose()
        plan = json.loads((director.root / "final-compose-command.json").read_text(encoding="utf-8"))
        self.assertTrue(plan["single_universal_output"])
        self.assertEqual(Path(plan["output"]), director.delivery_output)
        self.assertIn("loudnorm=I=-14:TP=-1.5:LRA=11", plan["argv"])
        self.assertEqual(plan["argv"][-1], str(director.delivery_output))

    def test_final_compose_adds_authorized_bgm_with_speech_ducking(self) -> None:
        bgm = self.root / "assets" / "bgm.wav"
        bgm.parent.mkdir(parents=True)
        bgm.write_bytes(b"authorized-music")
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {
            "bgm": {
                "enabled_by_default": True,
                "asset": str(bgm),
                "preview_volume": 0.1,
                "ducking": {
                    "enabled": True,
                    "method": "sidechaincompress",
                    "threshold": 0.03,
                    "ratio": 8,
                    "attack_ms": 200,
                    "release_ms": 400,
                },
            }
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"hyperframes-render")
        director.full_hyperframes_project.mkdir(parents=True)
        (director.full_hyperframes_project / "storyboard.json").write_text(
            json.dumps({"composition": {"duration": 100.0}}), encoding="utf-8"
        )
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        director._start("final_compose")
        with self.assertRaisesRegex(ValueError, "universal"):
            director.stage_final_compose()
        plan = json.loads((director.root / "final-compose-command.json").read_text(encoding="utf-8"))
        self.assertTrue(plan["audio_mix"]["bgm_enabled"])
        self.assertEqual(plan["audio_mix"]["bgm_asset"], str(bgm))
        filter_graph = plan["argv"][plan["argv"].index("-filter_complex") + 1]
        self.assertIn("sidechaincompress", filter_graph)
        self.assertIn("amix=inputs=2", filter_graph)
        self.assertIn("loudnorm=I=-14:TP=-1.5:LRA=11", filter_graph)

    def test_cover_likeness_waits_as_action_required_instead_of_failing(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["delivery"]["cover"] = "cover.png"
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        output = director.delivery_output
        output.parent.mkdir(parents=True)
        output.write_bytes(b"final-universal-video")
        output_hash = sha256_file(output)
        project = director.full_hyperframes_project
        project.mkdir(parents=True)
        (project / "storyboard.json").write_text(json.dumps({"events": []}), encoding="utf-8")
        (project / "audio-plan.json").write_text(json.dumps({
            "speech_track": {"dominant": True},
            "provenance": ["source-audio"],
        }), encoding="utf-8")
        cover = self.root / "cover.png"
        cover.write_bytes(b"cover")
        final_qa = director.root / "final-qa"
        final_qa.mkdir(parents=True)
        (final_qa / "aesthetic-review.json").write_text(json.dumps({}), encoding="utf-8")
        (final_qa / "cover-review.json").write_text(json.dumps({
            "status": "pending_user_identity_approval",
            "identity_reference_count": 2,
            "topic_relevant": True,
            "natural_expression_and_energy": True,
            "identity_approved_by_user": False,
        }), encoding="utf-8")
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        (director.video_use_dir / "final-edit-correctness.json").write_text(json.dumps({}), encoding="utf-8")
        (director.video_use_dir / "edl.json").write_text(json.dumps({"ranges": []}), encoding="utf-8")
        (director.root / "final-media-report.json").write_text(json.dumps({"decode_status": "pass"}), encoding="utf-8")
        for platform in ("douyin", "wechat_channels"):
            (final_qa / f"platform-{platform}.json").write_text(json.dumps({
                "status": "pass",
                "file_sha256": output_hash,
            }), encoding="utf-8")
        with patch("director.validate_aesthetic_review", return_value=[]), \
                patch("director.validate_audio_plan", return_value=[]), \
                patch("director.validate_video_use_final_correctness", return_value=[]):
            with self.assertRaisesRegex(DirectorContractError, "explicit user approval"):
                director.stage_delivery_qa()
        self.assertEqual(director.state["stages"]["delivery_qa"]["status"], "action_required")
        packet = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(packet["actions"][0]["owner"], "user")

    def test_full_storyboard_creates_render_authority_for_full_project_only(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        commands = json.loads((director.root / "full-hyperframes-commands.json").read_text(encoding="utf-8"))
        render = commands["final_motion_render"]
        check = commands["check"]
        self.assertEqual(render["cwd"], str(director.full_hyperframes_project))
        self.assertNotEqual(render["cwd"], str(director.sample_hyperframes_project))
        self.assertEqual(render["argv"][:4], ["npx", "hyperframes", "render", "."])
        self.assertIn("--strict", check["argv"])
        self.assertIn("--at-transitions", check["argv"])
        self.assertNotIn("--strict-all", check["argv"])

    def test_full_storyboard_rejects_sample_length_composition(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director, duration=73.0)
        director._start("full_hyperframes_storyboard")
        with self.assertRaisesRegex(ValueError, "does not cover"):
            director.stage_full_hyperframes_storyboard()

    def test_full_storyboard_requires_full_timeline_semantic_brief(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        director.full_semantic_brief_path.unlink()
        director._start("full_hyperframes_storyboard")
        with self.assertRaisesRegex(ValueError, "separate full-duration"):
            director.stage_full_hyperframes_storyboard()
        request = json.loads((director.root / "full-hyperframes-request.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(request["full_semantic_brief"]), director.full_semantic_brief_path)

    def test_full_storyboard_rejects_sample_only_semantic_scope(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        brief = json.loads(director.full_semantic_brief_path.read_text(encoding="utf-8"))
        brief["scope"]["source_end"] = 73.0
        director.full_semantic_brief_path.write_text(json.dumps(brief), encoding="utf-8")
        director._start("full_hyperframes_storyboard")
        with self.assertRaisesRegex(ValueError, "95%"):
            director.stage_full_hyperframes_storyboard()

    def test_full_hyperframes_qa_and_render_authorization_bind_exact_project(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        approval = authorize_final_render(Director(self.project), "hongr")
        row = json.loads(approval.read_text(encoding="utf-8"))
        self.assertTrue(row["authorized"])
        self.assertEqual(row["authorized_by"], "hongr")
        resumed = Director(self.project, approve_final_render=True)
        self.assertEqual(resumed._validate_final_render_authorization(), approval)

    def test_preview_render_parity_failure_blocks_full_hyperframes_qa(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        parity_path = director.root / "full-qa" / "preview-render-parity.json"
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
        parity["samples"][0]["elements"][0]["render"]["x"] = 100
        parity_path.write_text(json.dumps(parity), encoding="utf-8")
        director._start("full_hyperframes_qa")
        with self.assertRaisesRegex(DirectorContractError, "position parity"):
            director.stage_full_hyperframes_qa()

    def test_final_render_authorization_expires_when_full_storyboard_changes(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        authorize_final_render(Director(self.project), "hongr")
        storyboard = director.full_hyperframes_project / "storyboard.json"
        data = json.loads(storyboard.read_text(encoding="utf-8"))
        data["composition"]["duration"] = 101
        storyboard.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale"):
            Director(self.project, approve_final_render=True)._validate_final_render_authorization()

    def test_approve_sample_records_hashes_and_resets_resume_point(self) -> None:
        director = Director(self.project)
        storyboard, review, gate = self._write_passing_sample_evidence(director)
        path = approve_sample(director, "hongr")
        approval = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(approval["approved"])
        self.assertEqual(approval["approved_by"], "hongr")
        self.assertEqual(len(approval["storyboard_sha256"]), 64)
        resumed = Director(self.project)
        self.assertEqual(resumed.state["stages"]["preview_approval"]["status"], "pending")
        resumed._start("preview_approval")
        resumed.stage_preview_approval()
        self.assertEqual(resumed.state["stages"]["preview_approval"]["status"], "complete")

    def test_sample_approval_is_invalidated_when_storyboard_changes(self) -> None:
        director = Director(self.project)
        storyboard, _, _ = self._write_passing_sample_evidence(director)
        approve_sample(director, "hongr")
        storyboard.write_text(json.dumps({"renderer": "hyperframes", "events": [{"id": "changed"}]}),
                              encoding="utf-8")
        resumed = Director(self.project)
        resumed._start("preview_approval")
        with self.assertRaisesRegex(ValueError, "stale"):
            resumed.stage_preview_approval()

    def test_cached_nested_word_transcript_is_adopted_without_rewriting(self) -> None:
        cached = self.root / "edit" / "transcripts" / "raw-local.json"
        cached.parent.mkdir(parents=True)
        cached.write_text(json.dumps({"language": "zh", "segments": [{"words": [
            {"word": "原话", "start": 1.2, "end": 1.6},
            {"word": "保留。", "start": 1.6, "end": 2.1},
        ]}]}, ensure_ascii=False), encoding="utf-8")
        director = Director(self.project)
        target = self.root / "edit" / "video-use" / "transcripts" / "published.json"
        source = director._adopt_cached_word_transcript(target)
        self.assertEqual(source, cached)
        adopted = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual([word["text"] for word in adopted["words"]], ["原话", "保留。"])
        self.assertFalse(adopted["adoption"]["text_or_timing_modified"])


if __name__ == "__main__":
    unittest.main()
