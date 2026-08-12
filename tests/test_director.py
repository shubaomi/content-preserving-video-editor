from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director import (  # noqa: E402
    Director,
    ROLE_CONTRACT,
    _cover_delivery_gate,
    _json_sha256,
    _review_evidence_files,
    _semantic_inheritance_contract,
    _target_binding_request_contract,
    approve_sample,
    authorize_final_render,
)
from director_contracts import DirectorContractError, STAGES, VISUAL_VOCABULARY, sha256_file  # noqa: E402
from editorial_regression import create_baseline  # noqa: E402


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

    @staticmethod
    def _write_master_srt(director: Director) -> Path:
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        captions = director.video_use_dir / "master.srt"
        captions.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8"
        )
        return captions

    def _write_full_hyperframes_contract(self, director: Director, duration: float = 100.0) -> None:
        project = director.full_hyperframes_project
        project.mkdir(parents=True)
        transcript = director.video_use_dir / "transcripts" / f"{director.context.source_video.stem}.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        words = [
            {"id": f"w{index}", "type": "word", "text": f"proof{index}",
             "start": float(index * 20), "end": float(index * 20 + 1)}
            for index in range(4)
        ]
        transcript.write_text(json.dumps({"words": words}), encoding="utf-8")
        frame = director.root / "evidence" / "frames" / "frame-00.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"frame")
        director.evidence_bundle_path.write_text(json.dumps({
            "transcript": {"sha256": sha256_file(transcript), "term_evidence": [
                {"word_id": row["id"], "text": row["text"], "start": row["start"], "end": row["end"]}
                for row in words
            ]},
            "representative_frames": [{"path": str(frame), "sha256": sha256_file(frame)}],
        }), encoding="utf-8")
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
            "schema_version": 2,
            "generated_by": "test-llm",
            "content_reading": "raw_word_transcript_and_evidence_frames",
            "transcript_sha256": sha256_file(transcript),
            "evidence_bundle_sha256": sha256_file(director.evidence_bundle_path),
            "evidence_frames": [str(frame)],
            "opening_hook": {"status": "not_selected", "evidence": ["direct opening"]},
            "scope": {"source_start": 0, "source_end": 100.0},
            "events": [
                {
                    **event,
                    "anchor": f"anchor-{index}",
                    "transcript_quote": f"proof{index}",
                    "transcript_word_ids": [f"w{index}"],
                    "source_start": float(index * 20),
                    "source_end": float(index * 20 + 1),
                    "output_start": float(index * 20), "output_end": float(index * 20 + 1),
                    "viewer_job": "understand", "viewer_takeaway": f"proof{index}",
                    "visual_mechanism": f"mechanism-{index}",
                    "target_frame_evidence": [str(frame)],
                    "protected_zones": {"face": [], "ui": [], "caption": [], "cursor": []},
                    "form": "process", "placement": "left", "size": "medium",
                    "background": "transparent", "read_time": 1.0,
                    "motion": {"entrance": "fade", "reveal": "step", "hold": "steady", "exit": "fade"},
                    "audio_decision": {"type": "intentionally_silent", "reason": "test fixture"},
                    "deduplication": {"semantic": "unique", "visual": "unique"},
                    "relevance_rationale": "verified semantic event",
                }
                for index, event in enumerate(events)
            ] + [{
                "id": "quiet-tail", "treatment": "quiet_source",
                "source_start": 61.0, "source_end": 100.0,
                "output_start": 61.0, "output_end": 100.0,
                "source_activity_evidence": ["source screen activity continues"],
            }],
        }
        director.full_semantic_brief_path.write_text(json.dumps(full_brief), encoding="utf-8")
        storyboard_events = []
        for semantic_event in full_brief["events"]:
            storyboard_event = {
                "id": semantic_event["id"],
                "semantic_event_id": semantic_event["id"],
                "treatment": semantic_event["treatment"],
                "source_start": semantic_event["source_start"],
                "source_end": semantic_event["source_end"],
                "output_start": semantic_event["output_start"],
                "output_end": semantic_event["output_end"],
                "visible_copy_manifest": (
                    [semantic_event["approved_visible_copy"]]
                    if semantic_event.get("approved_visible_copy") else []
                ),
            }
            if semantic_event["treatment"] == "quiet_source":
                storyboard_event["source_activity_evidence"] = semantic_event[
                    "source_activity_evidence"
                ]
            else:
                storyboard_event.update({
                    "anchor": semantic_event["anchor"],
                    "transcript_word_ids": semantic_event["transcript_word_ids"],
                    "viewer_takeaway": semantic_event["viewer_takeaway"],
                    "visual_structure": semantic_event["visual_structure"],
                })
            storyboard_events.append(storyboard_event)
        storyboard = {
            "renderer": "hyperframes",
            "motion_output": "hyperframes_render",
            "capability_skills": ["hyperframes", "hyperframes-core", "hyperframes-creative",
                                  "hyperframes-animation", "hyperframes-cli"],
            "composition": {"duration": duration},
            "events": storyboard_events,
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
        director.semantic_brief_path.write_text(json.dumps(full_brief), encoding="utf-8")
        director._start("production_contract")
        director.stage_production_contract()

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
        check_path = qa / "hyperframes-check.json"
        check_path.write_text(json.dumps(check), encoding="utf-8")
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
                "connector_target_geometry_measurement", "composite_readability",
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
                "studio_snapshot_sha256": sha256_file(studio),
                "render_snapshot_sha256": sha256_file(rendered),
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
        commands_path = director.root / "full-hyperframes-commands.json"
        command = json.loads(commands_path.read_text(encoding="utf-8"))["check"]
        toolchain_path = director.root / "toolchain-compatibility.json"
        toolchain_path.write_text(json.dumps({"fixture": True}), encoding="utf-8")
        stdout = qa / "hyperframes-check-stdout.log"
        stderr = qa / "hyperframes-check-stderr.log"
        stdout.write_text(json.dumps(check), encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        (qa / "hyperframes-check-receipt.json").write_text(json.dumps({
            "schema_version": 1, "owner": "director", "capability": "hyperframes_check",
            "status": "pass", "exit_code": 0,
            "command_sha256": _json_sha256(command["argv"]),
            "cwd": str(Path(command["cwd"]).resolve()),
            "storyboard_sha256": sha256_file(director.full_hyperframes_project / "storyboard.json"),
            "visual_vocabulary_sha256": sha256_file(
                director.full_hyperframes_project / "visual-vocabulary-audit.json"
            ),
            "commands_sha256": sha256_file(commands_path),
            "toolchain_sha256": sha256_file(toolchain_path),
            "check_report_sha256": sha256_file(check_path),
            "stdout_log": str(stdout), "stdout_sha256": sha256_file(stdout),
            "stderr_log": str(stderr), "stderr_sha256": sha256_file(stderr),
        }), encoding="utf-8")
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

    def test_production_contract_is_a_real_stage_before_hyperframes(self) -> None:
        self.assertLess(STAGES.index("semantic_brief"), STAGES.index("production_contract"))
        self.assertLess(STAGES.index("production_contract"), STAGES.index("hyperframes_storyboard"))
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
        edl = director.video_use_dir / "edl.json"
        edl.write_text(json.dumps({"ranges": []}), encoding="utf-8")
        director.semantic_brief_path.write_text(json.dumps({"events": []}), encoding="utf-8")

        director._start("production_contract")
        director.stage_production_contract()

        self.assertEqual(director.state["stages"]["production_contract"]["status"], "complete")
        contract = json.loads(director.production_contract_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["project_mode"], "polish_existing")
        self.assertEqual(contract["delivery"]["default_output"], "single_universal_mp4")
        self.assertEqual(len(contract["inputs"]["source"]["sha256"]), 64)

    def test_provider_governance_stage_writes_hash_bound_decision_and_cost_ledger(self) -> None:
        director = Director(self.project)
        director._start("provider_governance")
        director.stage_provider_governance()
        decision = director.root / "provider-decision.json"
        ledger = director.root / "cost-ledger.json"
        self.assertTrue(decision.is_file())
        self.assertTrue(ledger.is_file())
        self.assertEqual(director.state["stages"]["provider_governance"]["status"], "complete")
        self.assertEqual(json.loads(ledger.read_text(encoding="utf-8"))["totals"]["actual"], 0.0)

    def test_enabled_semantic_confidence_is_a_real_hash_bound_director_gate(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["analysis"] = {"semantic_confidence": {
            "enabled": True, "low_confidence_threshold": 0.7,
        }}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        frame = director.root / "evidence" / "frame.png"
        frame.parent.mkdir(parents=True)
        frame.write_bytes(b"frame")
        candidate = {
            "event_id": "event-1", "anchor": "request validation path",
            "raw_word_ids": ["w1"], "raw_quote": "request validation path",
            "source_timing": {"start": 1.0, "end": 2.0},
            "output_timing": {"start": 1.0, "end": 2.0},
            "frame_evidence": [{"path": str(frame), "sha256": sha256_file(frame),
                                "timestamp": 1.5}],
            "anchor_specificity": 0.9, "claim_grounding": 0.9,
            "explanatory_value": 0.9, "asr_confidence": 0.9,
            "term_confidence": 0.9, "caption_duplication": 0.1,
            "motion_duplication": 0.0, "ip_duplication": 0.0,
            "counterexamples": [], "conflicts": [], "semantic_effect": "emphasis",
        }
        director._start("semantic_brief")
        artifacts = director._semantic_confidence_gate({
            "events": [{"id": "event-1", "treatment": "structure"}],
            "confidence_candidates": [candidate],
        })
        report = json.loads(artifacts[0].read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["semantic_deletion_authority"])
        frame.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash is stale"):
            director._semantic_confidence_gate({
                "events": [{"id": "event-1", "treatment": "structure"}],
                "confidence_candidates": [candidate],
            })

    def test_enabled_motion_quality_requests_decision_complete_semantic_opportunities(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)

        director._start("semantic_brief")
        with self.assertRaisesRegex(DirectorContractError, "LLM-authored semantic brief"):
            director.stage_semantic_brief()

        request = json.loads(
            (director.root / "semantic-brief-request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(request["schema_version"], 3)
        self.assertEqual(request["opportunity_model"], "decision_complete_v1")
        self.assertEqual(
            request["allowed_decisions"],
            [
                "render", "annotation", "caption_only", "reuse_source",
                "quiet_source", "action_required",
            ],
        )
        self.assertTrue(request["one_decision_per_opportunity"])
        self.assertFalse(request["fixed_cadence_or_event_family_quota"])

    def test_enabled_editorial_intent_adds_evidence_bound_request_contract(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["editorial_intent"] = {
            "enabled": True,
            "mode": "explicit",
            "audience": "knowledge workers",
            "viewer_job": "assess the workflow",
            "single_promise": "understand the verified workflow",
            "proof_event_ids": [],
            "cta": "try it on one task",
            "tone": "clear",
            "prohibited_claims": ["ten times faster"],
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)

        director._start("semantic_brief")
        with self.assertRaisesRegex(DirectorContractError, "LLM-authored semantic brief"):
            director.stage_semantic_brief()

        request = json.loads(
            (director.root / "semantic-brief-request.json").read_text(encoding="utf-8")
        )
        intent = request["editorial_intent"]
        self.assertEqual(intent["mode"], "explicit")
        self.assertEqual(intent["single_promise"], "understand the verified workflow")
        self.assertEqual(intent["prohibited_claims"], ["ten times faster"])
        self.assertTrue(request["promise_ledger_required"])

    def test_motion_quality_storyboard_request_serializes_only_render_decisions(self) -> None:
        brief = {"schema_version": 3, "opportunity_model": "decision_complete_v1", "events": [
            {"id": "render-1", "decision": "render"},
            {"id": "quiet-1", "decision": "quiet_source"},
            {"id": "caption-1", "decision": "caption_only"},
        ]}

        contract = _semantic_inheritance_contract(brief, motion_quality_enabled=True)

        self.assertEqual(contract["selected_semantic_event_ids"], ["render-1"])
        self.assertTrue(contract["nonrender_opportunities_must_not_be_serialized"])
        self.assertIsNone(contract["event_or_family_quota"])
        self.assertIsNone(contract["fixed_cadence"])
        self.assertIn("target_frame_evidence", contract["bind"])

    def test_motion_quality_target_binding_request_is_evidence_bound_and_fail_closed(self) -> None:
        layout = self.root / "work" / "director" / "evidence" / "adaptive-layout.json"
        binding_dir = self.root / "work" / "director" / "target-bindings"
        schema = ROOT / "references" / "p0-p2-design" / "schemas" / "target-binding.schema.json"
        layout.parent.mkdir(parents=True, exist_ok=True)
        layout.write_text(json.dumps({"status": "resolved"}), encoding="utf-8")

        contract = _target_binding_request_contract(
            layout_path=layout,
            binding_dir=binding_dir,
            schema_path=schema,
            identity_mode="third_party",
        )

        self.assertEqual(contract["mode"], "stateful_target_binding_v1")
        self.assertEqual(contract["adaptive_layout_sha256"], sha256_file(layout))
        self.assertFalse(contract["guessed_coordinates_allowed"])
        self.assertEqual(contract["unresolved_source_bound_event"], "do_not_render")
        self.assertEqual(contract["identity_mode"], "third_party")
        self.assertEqual(contract["personal_assets"], "forbidden")

    def test_motion_quality_evidence_stage_writes_adaptive_layout_contract(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        config["identity"] = {"mode": "third_party"}
        config["source"]["content_type"] = "talking_head"
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": []}), encoding="utf-8")

        def fake_acquire(**kwargs):
            output = kwargs["output_dir"] / "evidence-bundle.json"
            frame = kwargs["output_dir"] / "frame.png"
            frame.parent.mkdir(parents=True, exist_ok=True)
            frame.write_bytes(b"frame")
            output.write_text(json.dumps({
                "source": {"sha256": sha256_file(director.context.source_video)},
                "transcript": {"sha256": sha256_file(transcript)},
                "display": {"orientation": "portrait", "width": 1080, "height": 1920,
                            "rotation_degrees": 0},
                "representative_frames": [{"path": str(frame)}],
                "protected_regions": {
                    "faces": [{"bbox": {"x": 0.3, "y": 0.1, "width": 0.4, "height": 0.3}}],
                    "hands": [{"bbox": {"x": 0.2, "y": 0.45, "width": 0.6, "height": 0.3}}],
                    "captions": [], "status": "reviewed",
                },
            }), encoding="utf-8")
            return output

        with patch("director.acquire_evidence", side_effect=fake_acquire), patch.object(
            director, "_run_capability", return_value={"status": "disabled"},
        ):
            director._start("evidence_acquisition")
            director.stage_evidence_acquisition()

        layout = json.loads(director.adaptive_layout_path.read_text(encoding="utf-8"))
        self.assertEqual(layout["status"], "resolved")
        self.assertEqual(layout["layout_family"], "portrait_person_safe")
        self.assertEqual(layout["identity_mode"], "third_party")
        self.assertFalse(layout["guessed_coordinates_allowed"])
        self.assertIn(
            str(director.adaptive_layout_path.resolve()),
            director.state["stages"]["evidence_acquisition"]["artifacts"],
        )

    def test_subject_tracking_is_merged_before_portrait_layout_is_built(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        config["identity"] = {"mode": "self"}
        config["content_type"] = "portrait_talking_head"
        config.setdefault("content", {})["type"] = "portrait_talking_head"
        config["source"].pop("content_type", None)
        config.setdefault("workflow", {}).setdefault("capabilities", {})[
            "subject_tracking"
        ] = {"enabled": True}
        review_dir = self.root / "edit" / "protected-region-review"
        review_dir.mkdir(parents=True, exist_ok=True)
        review_frames = []
        for name in ("start.png", "middle.png"):
            frame = review_dir / name
            frame.write_bytes(name.encode("utf-8"))
            review_frames.append({
                "path": str(frame.relative_to(self.root)),
                "sha256": sha256_file(frame),
            })
        review_manifest = review_dir / "review.json"
        review_manifest.write_text(json.dumps({
            "schema_version": 1,
            "source_sha256": sha256_file(self.root / "source" / "published.mp4"),
            "reviewer": "fixture-reviewer",
            "reviewed_at": "2026-08-11T00:00:00Z",
            "observations": {
                "hands": {"status": "observed_absent", "evidence": review_frames},
            },
        }), encoding="utf-8")
        config.setdefault("analysis", {})["protected_region_review"] = {
            "enabled": True,
            "manifest": str(review_manifest.relative_to(self.root)),
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": []}), encoding="utf-8")

        def fake_acquire(**kwargs):
            output = kwargs["output_dir"] / "evidence-bundle.json"
            frame = kwargs["output_dir"] / "frame.png"
            frame.parent.mkdir(parents=True, exist_ok=True)
            frame.write_bytes(b"frame")
            output.write_text(json.dumps({
                "source": {"sha256": sha256_file(director.context.source_video)},
                "transcript": {"sha256": sha256_file(transcript)},
                "display": {"orientation": "portrait", "width": 544, "height": 960,
                            "rotation_degrees": 0},
                "representative_frames": [{"path": str(frame)}],
                "protected_regions": {
                    "faces": [],
                    "hands": [],
                    "captions": [], "status": "candidate_only",
                },
            }), encoding="utf-8")
            return output

        def fake_capability(name, **kwargs):
            if name == "subject_tracking":
                output = kwargs["outputs"][0]
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({
                    "tracking": {
                        "detector": "opencv_haar_frontalface",
                        "status": "tracked",
                        "series": [{
                            "time": 1.2,
                            "status": "tracked",
                            "face": {"x": 0.2, "y": 0.1, "w": 0.5, "h": 0.3},
                        }],
                    },
                }), encoding="utf-8")
                return {"status": "complete"}
            return {"status": "disabled"}

        with patch("director.acquire_evidence", side_effect=fake_acquire), patch.object(
            director, "_run_capability", side_effect=fake_capability,
        ):
            director._start("evidence_acquisition")
            director.stage_evidence_acquisition()

        bundle = json.loads(director.evidence_bundle_path.read_text(encoding="utf-8"))
        layout = json.loads(director.adaptive_layout_path.read_text(encoding="utf-8"))
        self.assertEqual(len(bundle["protected_regions"]["faces"]), 1)
        self.assertEqual(
            bundle["protected_regions"]["observations"]["hands"]["status"],
            "observed_absent",
        )
        self.assertEqual(layout["layout_family"], "portrait_person_safe")
        self.assertEqual(layout["status"], "resolved")

    def test_motion_quality_hyperframes_request_carries_target_binding_contract(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        config["identity"] = {"mode": "third_party"}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.semantic_brief_path.write_text(json.dumps({
            "schema_version": 3,
            "opportunity_model": "decision_complete_v1",
            "events": [{
                "id": "event-mark", "decision": "render",
                "decision_rationale": "mark a verified detail",
                "source_start": 1.0, "source_end": 2.0,
                "output_start": 1.0, "output_end": 2.0,
                "transcript_word_ids": ["w1"],
                "approved_visible_copy": ["关键指标"],
                "viewer_takeaway": "notice the verified metric",
                "target_frame_evidence": ["frame-1"],
                "semantic_role": "mark", "form": "semantic_mark",
            }],
        }), encoding="utf-8")
        director.adaptive_layout_path.parent.mkdir(parents=True, exist_ok=True)
        director.adaptive_layout_path.write_text(json.dumps({
            "schema_version": "1.0.0", "status": "resolved", "constraints": {},
            "fallback": None, "guessed_coordinates_allowed": False,
        }), encoding="utf-8")
        director.evidence_bundle_path.write_text(json.dumps({
            "duration_seconds": 100.0,
            "display": {"orientation": "landscape", "width": 1920, "height": 1080},
        }), encoding="utf-8")
        director.production_contract_path.write_text(json.dumps({"status": "test"}), encoding="utf-8")
        brand = director.root / "brand-motion" / "brand-motion-playbook.json"
        brand.parent.mkdir(parents=True, exist_ok=True)
        brand.write_text(json.dumps({"status": "test"}), encoding="utf-8")

        director._start("hyperframes_storyboard")
        with self.assertRaisesRegex(DirectorContractError, "HyperFrames-authored storyboard"):
            director.stage_hyperframes_storyboard()

        request = json.loads((director.root / "hyperframes-request.json").read_text(encoding="utf-8"))
        target = request["target_binding_contract"]
        self.assertEqual(target["binding_directory"], str(director.sample_target_binding_dir))
        self.assertEqual(target["unresolved_source_bound_event"], "do_not_render")
        self.assertEqual(target["personal_assets"], "forbidden")
        self.assertEqual(target["adaptive_layout_sha256"], sha256_file(director.adaptive_layout_path))
        self.assertEqual(request["motion_design"]["selection_owner"], "director_motion_quality_engine")
        renderer_evidence = request["renderer_evidence"]
        self.assertTrue(renderer_evidence["actual_runtime_export_required"])
        self.assertEqual(
            renderer_evidence["required_phases"],
            ["entrance", "mid", "pre_exit", "post_exit"],
        )
        self.assertTrue(Path(renderer_evidence["runtime_capture_tool"]).is_file())
        self.assertEqual(
            renderer_evidence["runtime_capture_args"]["project"],
            str(director.sample_hyperframes_project),
        )
        self.assertEqual(
            renderer_evidence["runtime_capture_args"]["target_binding_dir"],
            str(director.sample_target_binding_dir),
        )
        self.assertEqual(
            renderer_evidence["browser_resolution"],
            ["npx", "hyperframes", "browser", "path"],
        )
        self.assertIn("renderer-export.json", request["required_outputs"])
        self.assertIn("keyframe-receipts/*.json", request["required_outputs"])
        motion_contract = Path(request["motion_design"]["contract"])
        choreography = Path(request["motion_design"]["typed_choreography"])
        self.assertTrue(motion_contract.is_file())
        self.assertTrue(choreography.is_file())
        self.assertEqual(
            json.loads(motion_contract.read_text(encoding="utf-8"))["selected_event_ids"],
            ["event-mark"],
        )

    def test_runtime_capture_request_is_scope_specific_and_executable(self) -> None:
        director = Director(self.project)

        sample = director._runtime_capture_request("sample")
        full = director._runtime_capture_request("full")

        self.assertTrue(Path(sample["runtime_capture_tool"]).is_file())
        self.assertEqual(
            sample["runtime_capture_args"]["project"],
            str(director.sample_hyperframes_project),
        )
        self.assertEqual(
            sample["runtime_capture_args"]["target_binding_dir"],
            str(director.sample_target_binding_dir),
        )
        self.assertEqual(
            full["runtime_capture_args"]["project"],
            str(director.full_hyperframes_project),
        )
        self.assertEqual(
            full["runtime_capture_args"]["target_binding_dir"],
            str(director.full_target_binding_dir),
        )
        self.assertEqual(
            full["browser_resolution"],
            ["npx", "hyperframes", "browser", "path"],
        )
        self.assertTrue(Path(full["receipt_builder_tool"]).is_file())
        self.assertEqual(
            full["receipt_builder_args"]["renderer_export"],
            str(director.renderer_export_path("full")),
        )
        self.assertEqual(
            full["receipt_builder_args"]["output_dir"],
            str(director.keyframe_receipt_dir("full")),
        )
        self.assertEqual(full["missing_runtime_behavior"], "action_required")

    def test_source_bound_motion_requests_target_bindings_before_compilation(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        config["identity"] = {"mode": "generic"}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.semantic_brief_path.write_text(json.dumps({
            "schema_version": 3,
            "opportunity_model": "decision_complete_v1",
            "events": [{
                "id": "event-ui", "decision": "render",
                "decision_rationale": "focus one verified UI target",
                "source_start": 1.0, "source_end": 2.0,
                "output_start": 1.0, "output_end": 2.0,
                "transcript_word_ids": ["w1"],
                "approved_visible_copy": ["入口"],
                "viewer_takeaway": "notice the entry point",
                "target_frame_evidence": ["frame-1"],
                "semantic_role": "mark", "form": "ui_focus",
                "target_binding_ids": ["binding-entry"],
            }],
        }), encoding="utf-8")
        director.adaptive_layout_path.parent.mkdir(parents=True, exist_ok=True)
        director.adaptive_layout_path.write_text(json.dumps({
            "schema_version": "1.0.0", "status": "resolved", "constraints": {},
            "fallback": None, "guessed_coordinates_allowed": False,
        }), encoding="utf-8")
        director.evidence_bundle_path.write_text(json.dumps({
            "duration_seconds": 100.0,
            "display": {"orientation": "landscape", "width": 1920, "height": 1080},
        }), encoding="utf-8")
        director.production_contract_path.write_text(json.dumps({"status": "test"}), encoding="utf-8")
        brand = director.root / "brand-motion" / "brand-motion-playbook.json"
        brand.parent.mkdir(parents=True, exist_ok=True)
        brand.write_text(json.dumps({"status": "test"}), encoding="utf-8")

        director._start("hyperframes_storyboard")
        with self.assertRaisesRegex(DirectorContractError, "target bindings are required"):
            director.stage_hyperframes_storyboard()

        request_path = director.root / "target-binding-request.json"
        self.assertTrue(request_path.is_file())
        request = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(request["required_binding_ids"], ["binding-entry"])
        self.assertEqual(request["expected_outputs"], [
            str((director.sample_target_binding_dir / "binding-entry.json").resolve())
        ])
        self.assertFalse((director.motion_design_dir("sample") / "motion-design-contract.json").exists())

    def test_motion_quality_sample_qa_refuses_request_metadata_without_renderer_evidence(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        config["editing"] = {"caption_delivery": "none"}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        sample = director.sample_hyperframes_project
        sample.mkdir(parents=True, exist_ok=True)
        (sample / "storyboard.json").write_text(json.dumps({
            "renderer": "hyperframes", "events": [],
        }), encoding="utf-8")
        (sample / "audio-plan.json").write_text(json.dumps({}), encoding="utf-8")
        review = director.root / "sample-qa" / "aesthetic-review.json"
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")

        director._start("sample_qa")
        with patch.object(director, "_validate_current_production_contract"):
            with self.assertRaisesRegex(DirectorContractError, "Evidence-backed"):
                director.stage_sample_qa()

        request = json.loads(
            (director.root / "sample-qa-request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(request["schema_version"], 3)
        self.assertTrue(request["renderer_evidence_errors"])
        self.assertIn("renderer-export.json", request["renderer_export"])
        self.assertEqual(director.state["stages"]["sample_qa"]["status"], "action_required")

    def test_motion_quality_preview_approval_requests_paired_media_and_audio_evidence(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)

        director._start("preview_approval")
        with self.assertRaisesRegex(DirectorContractError, "Paired baseline/candidate"):
            director.stage_preview_approval()

        request_path = director.root / "sample-qa" / "creative-review-request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(request["user_decision_default"], "pending")
        self.assertEqual(
            request["candidate_requirement"],
            "actual 60-90 second HyperFrames sample render",
        )
        self.assertIn(str(director.sample_candidate_path), request["missing"])
        self.assertEqual(
            director.state["stages"]["preview_approval"]["status"], "action_required",
        )

    def test_unresolved_semantic_opportunity_remains_action_required(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["motion_quality"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
        frame = director.root / "evidence" / "frame.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"frame")
        director.evidence_bundle_path.write_text(json.dumps({
            "transcript": {
                "sha256": sha256_file(transcript),
                "term_evidence": [{
                    "word_id": "w1", "text": "需要确认", "start": 1.0, "end": 2.0,
                }],
            },
            "representative_frames": [{
                "path": str(frame), "sha256": sha256_file(frame),
            }],
        }), encoding="utf-8")
        director.semantic_brief_path.write_text(json.dumps({
            "schema_version": 3,
            "opportunity_model": "decision_complete_v1",
            "generated_by": "test-llm",
            "content_reading": "raw_word_transcript_and_evidence_frames",
            "transcript_sha256": sha256_file(transcript),
            "evidence_bundle_sha256": sha256_file(director.evidence_bundle_path),
            "evidence_frames": [str(frame)],
            "opening_hook": {"status": "not_selected", "evidence": ["direct opening"]},
            "events": [{
                "id": "needs-choice",
                "decision": "action_required",
                "decision_rationale": "Two materially different explanations remain.",
                "source_start": 1.0,
                "source_end": 2.0,
                "output_start": 1.0,
                "output_end": 2.0,
                "anchor": "需要确认",
                "transcript_quote": "需要确认",
                "transcript_word_ids": ["w1"],
                "target_frame_evidence": [str(frame)],
                "viewer_takeaway": "等待真实编辑决定",
            }],
        }), encoding="utf-8")

        director._start("semantic_brief")
        with self.assertRaisesRegex(
            DirectorContractError, "material editorial decision",
        ):
            director.stage_semantic_brief()

        action = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["stage"], "semantic_brief")
        self.assertEqual(action["actions"][0]["opportunity_ids"], ["needs-choice"])

    def test_metered_provider_call_reconciles_real_production_wrapper(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["provider_governance"] = {"enabled": True, "mode": "cap",
            "currency": "USD", "budget_total": 1.0, "providers": {"sfx": [{
                "name": "local-sfx", "available": True, "task_fit": 1.0,
                "incremental_cost": 0.2, "cost_basis": "user configured local call",
                "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.1,
                "failure_incremental_cost": 0.0,
                "paid_call_authorized": True, "verified_pricing_basis": True,
                "pricing_source": "user_plan", "remaining_quota": 10,
                "evidence_timestamp": "2026-08-01T00:00:00+00:00",
                "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
            }]}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director._start("provider_governance"); director.stage_provider_governance()
        produced = director.context.root / "sfx.wav"
        produced.write_bytes(b"sfx")

        result = director._metered_provider_call(
            ("sfx",), lambda: [produced], stage="audio",
        )
        ledger = json.loads((director.root / "cost-ledger.json").read_text(encoding="utf-8"))

        self.assertEqual(len(result), 1)
        self.assertEqual(ledger["reservations"][0]["status"], "success")
        self.assertEqual(ledger["totals"]["actual"], 0.1)
        resumed = Director(self.project)
        self.assertEqual(
            resumed.state["stages"]["provider_governance"]["status"], "complete",
        )

    def test_metered_provider_call_rejects_unselected_provider_before_callback(self) -> None:
        director = Director(self.project)
        director._start("provider_governance")
        director.stage_provider_governance()
        called = False

        def callback() -> None:
            nonlocal called
            called = True

        with self.assertRaisesRegex(DirectorContractError, "authorized provider"):
            director._metered_provider_call(("sfx",), callback, stage="sample_qa")

        self.assertFalse(called)

    def test_metered_provider_call_does_not_repeat_an_inflight_reservation(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["provider_governance"] = {"providers": {"sfx": [{
            "name": "local-sfx", "available": True, "task_fit": 1.0,
            "incremental_cost": 0.0, "cost_basis": "local idempotent adapter",
            "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
            "failure_incremental_cost": 0.0,
        }]}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director._start("provider_governance"); director.stage_provider_governance()
        reservation = director._ensure_provider_reservation(
            "sfx", stage="sample_qa", allow_create=True,
        )
        called = False

        def callback() -> None:
            nonlocal called
            called = True

        with self.assertRaisesRegex(DirectorContractError, "in-flight provider reservation"):
            director._metered_provider_call(("sfx",), callback, stage="sample_qa")

        ledger = json.loads((director.root / "cost-ledger.json").read_text(encoding="utf-8"))
        self.assertFalse(called)
        self.assertEqual(len(ledger["reservations"]), 1)
        self.assertEqual(ledger["reservations"][0]["id"], reservation["id"])

    def test_brand_motion_playbook_is_compiled_before_hyperframes(self) -> None:
        self.assertLess(STAGES.index("brand_motion_playbook"), STAGES.index("hyperframes_storyboard"))
        director = Director(self.project)
        tokens = director.context.edit_dir / "design-tokens.json"
        tokens.parent.mkdir(parents=True, exist_ok=True)
        tokens.write_text(json.dumps({
            "sampling": {"dimensions": {"width": 1920, "height": 1080}},
            "surface": {"color": "#fff", "text_color": "#111"},
            "accent": {"color": "#0a8"}, "shape": {}, "shadow": {},
            "typography": {}, "safe_zones": {},
        }), encoding="utf-8")
        director.semantic_brief_path.write_text(json.dumps({"events": []}), encoding="utf-8")
        director._start("brand_motion_playbook")
        director.stage_brand_motion_playbook()
        playbook = director.root / "brand-motion" / "brand-motion-playbook.json"
        self.assertTrue(playbook.is_file())
        self.assertEqual(json.loads(playbook.read_text(encoding="utf-8"))["orientation"], "landscape")

    def test_sample_approval_creates_golden_editorial_baseline_when_enabled(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["editorial_regression"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.semantic_brief_path.write_text(json.dumps({"events": []}), encoding="utf-8")
        self._write_passing_sample_evidence(director)
        approve_sample(director, "hongr")
        baseline = director.root / "editorial-regression" / "golden-baseline.json"
        self.assertTrue(baseline.is_file())
        self.assertEqual(json.loads(baseline.read_text(encoding="utf-8"))["approved_by"], "hongr")
        approval = json.loads((director.root / "preview-approval.json").read_text(encoding="utf-8"))
        self.assertEqual(approval["golden_baseline_sha256"], sha256_file(baseline))

    def test_approved_golden_baseline_replacement_invalidates_preview_stage(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["editorial_regression"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.semantic_brief_path.write_text(json.dumps({"events": []}), encoding="utf-8")
        self._write_passing_sample_evidence(director)
        approve_sample(director, "hongr")
        director = Director(self.project)
        director._start("preview_approval"); director.stage_preview_approval()
        baseline = director.root / "editorial-regression" / "golden-baseline.json"
        payload = json.loads(baseline.read_text(encoding="utf-8"))
        payload["signature"]["cover_route"] = "unapproved replacement"
        payload["integrity_sha256"] = _json_sha256({
            key: value for key, value in payload.items() if key != "integrity_sha256"
        })
        baseline.write_text(json.dumps(payload), encoding="utf-8")

        resumed = Director(self.project)

        self.assertEqual(resumed.state["stages"]["preview_approval"]["status"], "pending")
        self.assertEqual(resumed.state["last_invalidation"]["from_stage"], "preview_approval")
        baseline.write_text('{"schema_version":1,"tampered":true}', encoding="utf-8")
        director._start("preview_approval")
        with self.assertRaises(DirectorContractError):
            director.stage_preview_approval()

    def test_sample_qa_writes_and_binds_visual_dynamics_report(self) -> None:
        director = Director(self.project)
        storyboard = director.sample_hyperframes_project / "storyboard.json"
        storyboard.parent.mkdir(parents=True, exist_ok=True)
        storyboard.write_text(json.dumps({
            "composition": {"duration": 0},
            "events": [],
        }), encoding="utf-8")
        director.semantic_brief_path.write_text(json.dumps({"events": []}), encoding="utf-8")
        transcript = director.video_use_dir / "transcripts" / f"{director.context.source_video.stem}.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
        edl = director.video_use_dir / "edl.json"
        edl.write_text(json.dumps({"ranges": []}), encoding="utf-8")
        director._start("production_contract")
        director.stage_production_contract()
        review = director.root / "sample-qa" / "aesthetic-review.json"
        review.parent.mkdir(parents=True, exist_ok=True)
        snapshot = review.parent / "structured-snapshot.png"
        snapshot.write_bytes(b"snapshot-v1")
        review.write_text(json.dumps({
            "verdict": "pass",
            "snapshots": {"e0": {"entrance": {
                "path": str(snapshot), "sha256": sha256_file(snapshot),
            }}},
        }), encoding="utf-8")
        audio = director.sample_hyperframes_project / "audio-plan.json"
        audio.write_text(json.dumps({}), encoding="utf-8")

        with patch("director.validate_aesthetic_review", return_value=[]), \
                patch("director.validate_audio_plan", return_value=[]):
            director._start("sample_qa")
            director.stage_sample_qa()

        dynamics = director.root / "sample-qa" / "visual-dynamics-qa.json"
        gate = json.loads((director.root / "sample-qa" / "gate-report.json").read_text(encoding="utf-8"))
        self.assertTrue(dynamics.is_file())
        self.assertEqual(gate["visual_dynamics_sha256"], sha256_file(dynamics))
        self.assertEqual(json.loads(dynamics.read_text(encoding="utf-8"))["status"], "pass")
        self.assertIn(
            str(snapshot.resolve()), director.state["stages"]["sample_qa"]["artifacts"],
        )

        snapshot.write_bytes(b"snapshot-v2")
        resumed = Director(self.project)
        self.assertEqual(resumed.state["stages"]["sample_qa"]["status"], "pending")
        self.assertEqual(resumed.state["last_invalidation"]["from_stage"], "sample_qa")

    def test_structured_review_evidence_requires_sha256(self) -> None:
        snapshot = self.root / "snapshot.png"
        snapshot.write_bytes(b"snapshot")

        with self.assertRaisesRegex(DirectorContractError, "requires sha256"):
            _review_evidence_files({"snapshots": {"e0": {"entrance": {
                "path": str(snapshot),
            }}}})

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

    def test_old_state_migration_invalidates_all_unverifiable_completed_work(self) -> None:
        director = Director(self.project)
        inspect_artifact = director.root / "inspect.json"
        timeline_artifact = director.root / "timeline.json"
        inspect_artifact.write_text("inspect", encoding="utf-8")
        timeline_artifact.write_text("timeline", encoding="utf-8")
        director._complete("inspect", [inspect_artifact])
        director._complete("video_use_timeline", [timeline_artifact])
        for name in STAGES[STAGES.index("evidence_acquisition"):]:
            director.state["stages"][name]["status"] = "complete"
        director.state["schema_version"] = 3
        director.state["stages"].pop("evidence_acquisition")
        director._save()

        migrated = Director(self.project)

        for name in STAGES:
            self.assertEqual(migrated.state["stages"][name]["status"], "pending")

    def test_existing_complete_contract_stages_receive_truthful_readiness(self) -> None:
        director = Director(self.project)
        audio_contract = director.root / "audio-contract.json"
        cover_contract = director.root / "cover-contract.json"
        audio_contract.write_text("{}", encoding="utf-8")
        cover_contract.write_text("{}", encoding="utf-8")
        director._complete("audio", [audio_contract])
        director._complete("cover", [cover_contract])
        del director.state["stages"]["audio"]["readiness"]
        del director.state["stages"]["cover"]["readiness"]
        director._save()

        resumed = Director(self.project)

        self.assertEqual(resumed.state["stages"]["audio"]["readiness"], "contract_ready")
        self.assertEqual(resumed.state["stages"]["cover"]["readiness"], "contract_ready")

    def test_delivery_qa_blocks_required_audio_that_is_only_contract_ready(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config.setdefault("delivery", {})["required_assets"] = {
            "audio": {
                "stage": "audio",
                "applicability": "required",
                "required_readiness": "asset_ready",
            },
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.delivery_output.parent.mkdir(parents=True, exist_ok=True)
        director.delivery_output.write_bytes(b"universal-video")
        for stage in ("video_use_timeline", "production_contract", "final_compose"):
            director.state["stages"][stage].update({
                "status": "complete", "readiness": "ready",
            })
        director.state["stages"]["audio"].update({
            "status": "complete", "readiness": "contract_ready",
        })

        with self.assertRaisesRegex(
            DirectorContractError, "Required delivery assets are not deliverable"
        ):
            director.stage_delivery_qa()

        self.assertEqual(director.state["stages"]["delivery_qa"]["status"], "action_required")
        packet = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertTrue(any(
            "audio" in error and "contract_ready" in error
            for error in packet["actions"][0]["readiness_errors"]
        ))

    def test_changed_completed_stage_artifact_reopens_that_stage_and_downstream(self) -> None:
        director = Director(self.project)
        inspect_artifact = director.root / "inspect.json"
        timeline_artifact = director.root / "timeline.json"
        inspect_artifact.write_text("inspect-v1", encoding="utf-8")
        timeline_artifact.write_text("timeline-v1", encoding="utf-8")
        director._complete("inspect", [inspect_artifact])
        director._complete("video_use_timeline", [timeline_artifact])
        timeline_artifact.write_text("timeline-v2", encoding="utf-8")

        reopened = Director(self.project)
        self.assertEqual(reopened.state["stages"]["inspect"]["status"], "complete")
        self.assertEqual(reopened.state["stages"]["video_use_timeline"]["status"], "pending")
        self.assertEqual(reopened.state["stages"]["delivery_qa"]["status"], "pending")

    def test_changed_source_bytes_reopen_entire_workflow(self) -> None:
        director = Director(self.project)
        artifact = director.root / "inspect.json"
        artifact.write_text("inspect", encoding="utf-8")
        director._complete("inspect", [artifact])
        director.context.source_video.write_bytes(b"changed-source")

        reopened = Director(self.project)
        self.assertTrue(all(row["status"] == "pending"
                            for row in reopened.state["stages"].values()))
        self.assertEqual(reopened.state["input_fingerprints"]["source_video"]["sha256"],
                         sha256_file(director.context.source_video))

    def test_changed_source_with_preserved_size_and_mtime_still_reopens_workflow(self) -> None:
        director = Director(self.project)
        artifact = director.root / "inspect.json"
        artifact.write_text("inspect", encoding="utf-8")
        director._complete("inspect", [artifact])
        source = director.context.source_video
        original_stat = source.stat()
        self.assertEqual(len(b"source-media"), len(b"changed-data"))
        source.write_bytes(b"changed-data")
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

        reopened = Director(self.project)
        self.assertTrue(all(row["status"] == "pending"
                            for row in reopened.state["stages"].values()))

    def test_changed_project_bytes_reopen_entire_workflow(self) -> None:
        director = Director(self.project)
        artifact = director.root / "inspect.json"
        artifact.write_text("inspect", encoding="utf-8")
        director._complete("inspect", [artifact])
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["delivery"]["title"] = "changed configuration"
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")

        reopened = Director(self.project)
        self.assertTrue(all(row["status"] == "pending"
                            for row in reopened.state["stages"].values()))
        self.assertEqual(reopened.state["input_fingerprints"]["project_file"]["sha256"],
                         sha256_file(self.project))

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
                    "burned_in": {
                        "detected": True,
                        "verification_status": "verified",
                        "confidence": 0.91,
                    },
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

    def test_unverified_burned_caption_heuristic_cannot_switch_to_polish_mode(self) -> None:
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

        def fake_analysis(command, **_kwargs):
            output = Path(command[command.index("--out") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({
                "captions": {
                    "subtitle_streams": [],
                    "burned_in": {
                        "detected": False,
                        "candidate_detected": True,
                        "verification_status": "heuristic_unverified",
                        "confidence": 1.0,
                    },
                }
            }), encoding="utf-8")

        director._start("inspect")
        with patch("director.subprocess.run", side_effect=fake_analysis):
            director.stage_inspect()

        self.assertEqual(director.context.input_mode, "preserve")
        evidence = json.loads((director.root / "input-mode-evidence.json").read_text(encoding="utf-8"))
        self.assertNotIn("high_confidence_burned_captions", evidence["signals"])

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

        def fake_run(command: list[str], *, cwd: str, **_kwargs):
            self.assertEqual(command[0], r"C:\node\npx.CMD")
            self.assertEqual(cwd, command_record["cwd"])
            rendered = Path(command[-1])
            rendered.parent.mkdir(parents=True, exist_ok=True)
            rendered.write_bytes(b"render")
            return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

        director._start("final_render")
        with patch("director.shutil.which", return_value=r"C:\node\npx.CMD") as which:
            with patch("director.subprocess.run", side_effect=fake_run):
                director.stage_final_render()

        which.assert_called_once_with("npx")
        self.assertEqual(director.state["stages"]["final_render"]["status"], "complete")

    def test_successful_noop_render_cannot_receipt_preexisting_output(self) -> None:
        director = Director(self.project, approve_final_render=True)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        authorize_final_render(Director(self.project), "hongr")
        director = Director(self.project, approve_final_render=True, execute_external=True)
        output = Path(json.loads((director.root / "full-hyperframes-commands.json")
                                 .read_text(encoding="utf-8"))
                      ["final_motion_render"]["expected_artifact"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"old-render")
        no_op = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        director._start("final_render")
        with patch("director.subprocess.run", return_value=no_op):
            with self.assertRaisesRegex(DirectorContractError, "did not create"):
                director.stage_final_render()
        self.assertFalse((director.root / "final-render-receipt.json").exists())

    def test_stale_hyperframes_check_receipt_is_rerun_when_execution_is_enabled(self) -> None:
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        storyboard = director.full_hyperframes_project / "storyboard.json"
        payload = json.loads(storyboard.read_text(encoding="utf-8"))
        payload["review_revision"] = 2
        storyboard.write_text(json.dumps(payload), encoding="utf-8")
        resumed = Director(self.project, execute_external=True)
        check = json.loads((resumed.root / "full-qa" / "hyperframes-check.json")
                           .read_text(encoding="utf-8"))
        result = type("Result", (), {
            "returncode": 0, "stdout": json.dumps(check), "stderr": "",
        })()
        resumed._start("full_hyperframes_qa")
        with patch("director.subprocess.run", return_value=result) as run:
            resumed.stage_full_hyperframes_qa()
        self.assertEqual(run.call_count, 1)
        receipt = json.loads((resumed.root / "full-qa" / "hyperframes-check-receipt.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(receipt["storyboard_sha256"], sha256_file(storyboard))

    def test_state_migration_adds_new_stages_and_invalidates_unverifiable_completion(self) -> None:
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
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        (director.video_use_dir / "edl.json").write_text(json.dumps({
            "owner": "video-use", "sources": {"input": str(director.context.source_video)},
            "ranges": [{"id": "c1", "source": "input", "start": 0.0,
                        "end": 1.0, "timeline_start": 0.0}],
            "gaps": [], "transitions": [], "metadata": {"video_id": "sample"},
        }), encoding="utf-8")
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
        typed = json.loads(
            (director.root / "manual-finish" / "typed-nle-handoff.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(typed["status"], "action_required")
        self.assertEqual(typed["authoritative_edl"]["sha256"], sha256_file(
            director.video_use_dir / "edl.json"
        ))
        self.assertFalse(typed["capability_report"]["editor_api_verified"])

    def test_optional_media_adapters_create_no_artifact_when_disabled(self) -> None:
        director = Director(self.project)
        director._start("semantic_brief")
        # The full semantic stage needs many unrelated owner artifacts, so exercise
        # its P2 adapter helper directly to prove the default-off no-artifact boundary.
        self.assertEqual(director._optional_media_adapter_artifacts(), [])
        self.assertFalse((director.root / "optional-media-adapters.json").exists())

    def test_enabled_optional_media_adapter_is_action_required_until_real_execution(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["extensions"] = {"optional_media_adapters": [{
            "enabled": True, "kind": "ocr", "provider": "local",
            "rights_approved": True, "privacy_approved": True,
            "budget_approved": True, "provenance_enabled": True,
            "human_review_required": True,
        }]}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)

        artifacts = director._optional_media_adapter_artifacts()
        report = json.loads(artifacts[0].read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "action_required")
        self.assertEqual(report["adapters"][0]["execution_status"], "not_run")

    def test_openmontage_handoff_reuses_manual_finish_contract_and_never_claims_api(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["delivery"]["openmontage_handoff"] = {
            "enabled": True, "backend": "openmontage", "modifications": [], "assets": {},
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        director.delivery_output.parent.mkdir(parents=True)
        director.delivery_output.write_bytes(b"automatic")
        director._start("manual_finish_handoff")
        with self.assertRaisesRegex(DirectorContractError, "human manual finishing"):
            director.stage_manual_finish_handoff()
        manifest = director.manual_finish_dir / "openmontage-handoff-manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertFalse(payload["runtime_dependency_required"])
        self.assertEqual(payload["automation_capabilities_claimed"], [])
        self.assertEqual(payload["assets"]["production_contract"]["status"], "unavailable")

    def test_enabled_clip_factory_runs_as_optional_derived_stage(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["derived_content"] = {
            "clip_factory": {"enabled": True},
            "podcast": {"enabled": False}, "localization": {"enabled": False},
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": [
            {"id": "w1", "text": "完整解释", "start": 1, "end": 7},
        ]}), encoding="utf-8")
        edl = director.video_use_dir / "edl.json"
        edl.write_text('{"ranges":[{"start":0,"end":10}]}', encoding="utf-8")
        director.full_semantic_brief_path.write_text(json.dumps({"events": [{
            "id": "e1", "clip_candidate": True, "source_start": 1, "source_end": 7,
            "output_start": 1, "output_end": 7, "transcript_word_ids": ["w1"],
            "transcript_quote": "完整解释", "viewer_takeaway": "完整解释",
        }]}), encoding="utf-8")
        director.production_contract_path.write_text('{"schema_version":1}', encoding="utf-8")
        director._start("derived_content")
        director.stage_derived_content()
        manifest = director.root / "derived-content" / "clip-factory-manifest.json"
        self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["status"], "selected")

    def test_invalid_localization_result_reconciles_reserved_provider_as_failed(self) -> None:
        result = self.root / "work" / "translation-result.json"
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["derived_content"] = {
            "clip_factory": {"enabled": False}, "podcast": {"enabled": False},
            "localization": {
                "enabled": True, "target_language": "en", "glossary": {},
                "provider": {"backend": "result_file", "name": "translator",
                             "result": str(result), "authorized": True},
            },
        }
        config["provider_governance"] = {
            "enabled": True, "mode": "cap", "currency": "USD", "budget_total": 1.0,
            "providers": {"translation": [{
                "name": "translator", "available": True, "task_fit": 1.0,
                "incremental_cost": 0.2, "cost_basis": "user configured call",
                "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.2,
                "failure_incremental_cost": 0.05,
                "paid_call_authorized": True, "verified_pricing_basis": True,
                "pricing_source": "user_plan", "remaining_quota": 10,
                "evidence_timestamp": "2026-08-01T00:00:00+00:00",
                "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
            }]},
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": [
            {"id": "w1", "text": "你好", "start": 0, "end": 1, "type": "word"},
        ]}, ensure_ascii=False), encoding="utf-8")
        director._start("provider_governance"); director.stage_provider_governance()
        reservation = director._ensure_provider_reservation(
            "translation", stage="derived_content", allow_create=True,
        )
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({
            "provider": "translator", "target_language": "en",
            "translations": {"w1": {"translated": "hello", "back_translation": "你好"}},
        }, ensure_ascii=False), encoding="utf-8")

        director._start("derived_content")
        with self.assertRaisesRegex(DirectorContractError, "localization manifest"):
            director.stage_derived_content()

        ledger = json.loads((director.root / "cost-ledger.json").read_text(encoding="utf-8"))
        row = next(item for item in ledger["reservations"] if item["id"] == reservation["id"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["actual"], 0.05)

    def test_malformed_localization_result_reconciles_before_parse_error(self) -> None:
        result = self.root / "work" / "translation-result.json"
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["derived_content"] = {
            "clip_factory": {"enabled": False}, "podcast": {"enabled": False},
            "localization": {
                "enabled": True, "target_language": "en", "glossary": {},
                "provider": {"backend": "result_file", "name": "translator",
                             "result": str(result), "authorized": True},
            },
        }
        config["provider_governance"] = {
            "providers": {"translation": [{
                "name": "translator", "available": True, "task_fit": 1.0,
                "incremental_cost": 0.0, "cost_basis": "local fixture",
                "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
                "failure_incremental_cost": 0.0,
            }]},
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        transcript = director.video_use_dir / "transcripts" / "published.json"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"words": [
            {"id": "w1", "text": "你好", "start": 0, "end": 1, "type": "word"},
        ]}, ensure_ascii=False), encoding="utf-8")
        director._start("provider_governance"); director.stage_provider_governance()
        reservation = director._ensure_provider_reservation(
            "translation", stage="derived_content", allow_create=True,
        )
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text("{not-json", encoding="utf-8")

        director._start("derived_content")
        with self.assertRaises(json.JSONDecodeError):
            director.stage_derived_content()

        ledger = json.loads((director.root / "cost-ledger.json").read_text(encoding="utf-8"))
        row = next(item for item in ledger["reservations"] if item["id"] == reservation["id"])
        self.assertEqual(row["status"], "failed")

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

        returned_stat = returned.stat()
        returned.write_bytes(b"manual-v2")
        os.utime(returned, ns=(returned_stat.st_atime_ns, returned_stat.st_mtime_ns))
        reopened = Director(self.project)
        self.assertEqual(reopened.state["stages"]["manual_finish_handoff"]["status"], "pending")
        self.assertEqual(reopened.state["stages"]["delivery_qa"]["status"], "pending")
        self.assertEqual(reopened.state["last_invalidation"]["from_stage"],
                         "manual_finish_handoff")
        self.assertIn("artifact changed", reopened.state["last_invalidation"]["reason"])

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
        self._write_master_srt(director)
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

    def test_final_compose_burns_video_use_captions_last_for_source_first_video(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["source"]["input_mode"] = "raw"
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"hyperframes-render")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        captions = director.video_use_dir / "master.srt"
        captions.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")

        with self.assertRaisesRegex(DirectorContractError, "not present"):
            director.stage_final_compose()

        plan = json.loads((director.root / "final-compose-command.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["caption_delivery"]["mode"], "burned_in_last")
        self.assertEqual(plan["caption_delivery"]["source_sha256"], sha256_file(captions))
        self.assertIn("-vf", plan["argv"])
        self.assertIn("subtitles=", plan["argv"][plan["argv"].index("-vf") + 1])

    def test_sample_review_requires_same_caption_track_on_baseline_and_candidate(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["source"]["input_mode"] = "raw"
        config["editing"] = {"caption_delivery": "auto"}
        config["motion_quality"] = {"enabled": True}
        config["motion_quality"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        self._write_master_srt(director)
        director.sample_hyperframes_project.mkdir(parents=True, exist_ok=True)
        director.sample_baseline_raw_path.write_bytes(b"baseline-raw")
        director.sample_candidate_raw_path.write_bytes(b"candidate-raw")

        with self.assertRaisesRegex(DirectorContractError, "captioned paired sample"):
            director._ensure_sample_caption_delivery()

        request = json.loads(director.action_path.read_text(encoding="utf-8"))
        outputs = request["actions"][0]["expected_outputs"]
        self.assertIn(str(director.sample_baseline_path), outputs)
        self.assertIn(str(director.sample_candidate_path), outputs)
        self.assertNotEqual(director.sample_baseline_path, director.sample_baseline_raw_path)
        self.assertNotEqual(director.sample_candidate_path, director.sample_candidate_raw_path)
        self.assertFalse(director.sample_candidate_path.is_relative_to(
            director.sample_hyperframes_project
        ))

    def test_polish_existing_without_verified_captions_still_burns_master_srt_last(self) -> None:
        director = Director(self.project)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"hyperframes-render")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        captions = director.video_use_dir / "master.srt"
        captions.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")

        with self.assertRaisesRegex(DirectorContractError, "not present"):
            director.stage_final_compose()

        plan = json.loads((director.root / "final-compose-command.json").read_text(
            encoding="utf-8"
        ))
        self.assertEqual(plan["caption_delivery"]["mode"], "burned_in_last")
        self.assertEqual(plan["caption_delivery"]["source_sha256"], sha256_file(captions))
        self.assertIn("subtitles=", plan["argv"][plan["argv"].index("-vf") + 1])

    def test_audio_stage_executes_real_asset_production_when_external_execution_is_enabled(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {"production": {"enabled": True}}
        config["provider_governance"] = {"providers": {
            task: [{"name": f"local-{task}", "available": True, "task_fit": 1.0,
                    "incremental_cost": 0.0, "cost_basis": "test local provider",
                    "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
                    "failure_incremental_cost": 0.0}]
            for task in ("sfx", "bgm")
        }}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, execute_external=True)
        director._start("provider_governance"); director.stage_provider_governance()
        director.sample_hyperframes_project.mkdir(parents=True, exist_ok=True)
        storyboard = director.sample_hyperframes_project / "storyboard.json"
        storyboard.write_text(json.dumps({"events": []}), encoding="utf-8")
        audio_plan = director.sample_hyperframes_project / "audio-plan.json"

        def fake_produce(**kwargs):
            self.assertEqual(kwargs["storyboard"], storyboard)
            audio_plan.write_text(json.dumps({
                "schema_version": 3,
                "speech_track": {"dominant": True},
                "motion_sfx": {"event_decisions": []},
                "background_music": {
                    "mode": "disabled", "enabled": False,
                    "reason": "no authorized BGM is available",
                },
                "provenance": {"source_audio": str(director.context.source_video)},
            }), encoding="utf-8")
            return [audio_plan]

        director._start("audio")
        with patch("director.produce_audio_assets", side_effect=fake_produce) as produce:
            director.stage_audio()
        self.assertEqual(produce.call_count, 1)
        self.assertIn(str(audio_plan), director.state["stages"]["audio"]["artifacts"])
        self.assertEqual(director.state["stages"]["audio"]["readiness"], "asset_ready")

    def test_audio_stage_does_not_meter_deterministic_local_sfx_when_bgm_is_disabled(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {
            "production": {"enabled": True},
            "sfx": {"enabled": True},
            "bgm": {"enabled": False},
        }
        config["provider_governance"] = {"providers": {}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, execute_external=True)
        director.sample_hyperframes_project.mkdir(parents=True, exist_ok=True)
        storyboard = director.sample_hyperframes_project / "storyboard.json"
        storyboard.write_text(json.dumps({"events": []}), encoding="utf-8")
        audio_plan = director.sample_hyperframes_project / "audio-plan.json"

        def fake_produce(**kwargs):
            self.assertEqual(kwargs["storyboard"], storyboard)
            audio_plan.write_text(json.dumps({
                "schema_version": 3,
                "speech_track": {"dominant": True},
                "motion_sfx": {
                    "event_decisions": [],
                    "mix_audibility_check": {"status": "not_applicable"},
                },
                "background_music": {
                    "mode": "disabled",
                    "enabled": False,
                    "reason": "explicitly disabled",
                    "explicitly_disabled": True,
                },
                "provenance": {"source_audio": str(director.context.source_video)},
            }), encoding="utf-8")
            return [audio_plan]

        director._start("audio")
        with patch("director.produce_audio_assets", side_effect=fake_produce) as produce, \
                patch.object(
                    director,
                    "_metered_provider_call",
                    side_effect=AssertionError("local deterministic SFX must not be metered"),
                ):
            director.stage_audio()

        self.assertEqual(produce.call_count, 1)
        self.assertEqual(director.state["stages"]["audio"]["readiness"], "asset_ready")

    def test_audio_stage_measures_rendered_raw_candidate_before_caption_delivery(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {
            "production": {"enabled": True},
            "sfx": {"enabled": True},
            "bgm": {"enabled": False},
        }
        config["editing"] = {"caption_delivery": "auto"}
        config["motion_quality"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, execute_external=True)
        input_analysis = director.root / "input-mode-analysis.json"
        input_analysis.parent.mkdir(parents=True, exist_ok=True)
        input_analysis.write_text(json.dumps({
            "captions": {"subtitle_streams": [], "burned_in": {"detected": False}},
        }), encoding="utf-8")
        project = director.sample_hyperframes_project
        project.mkdir(parents=True, exist_ok=True)
        storyboard = project / "storyboard.json"
        storyboard.write_text(json.dumps({"events": [{
            "id": "e1", "semantic_event_id": "semantic-1",
            "start": 1.0, "end": 3.0, "treatment": "structure",
        }]}), encoding="utf-8")
        raw_candidate = director.sample_candidate_raw_path
        raw_candidate.write_bytes(b"rendered-candidate")
        self.assertNotEqual(director.sample_candidate_path, raw_candidate)
        audio_plan = project / "audio-plan.json"
        audio_plan.write_text(json.dumps({
            "speech_track": {"dominant": True},
            "motion_sfx": {
                "event_decisions": [{
                    "event_id": "e1", "decision": "cue", "asset": "assets/e1.wav",
                    "family": "structure", "start": 1.1, "duration_seconds": 1.2,
                    "volume": 0.2, "post_gain_mean_dbfs": -28.0,
                }],
                "mix_audibility_check": {"status": "pending_render_measurement"},
            },
            "background_music": {"mode": "disabled", "enabled": False,
                                 "reason": "explicitly disabled", "explicitly_disabled": True},
        }), encoding="utf-8")

        director._start("audio")
        with patch("director.materialize_sample_audio_evidence", return_value=[audio_plan]) as measure, \
                patch("director.materialize_sample_review_mix"):
            director.stage_audio()

        self.assertEqual(measure.call_count, 1)
        self.assertEqual(measure.call_args.kwargs["candidate_media"], raw_candidate)

    def test_audio_stage_materializes_sfx_mixed_candidate_for_caption_last_review(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {
            "production": {"enabled": True},
            "sfx": {"enabled": True},
            "bgm": {"enabled": False},
        }
        config["editing"] = {"caption_delivery": "auto"}
        config["motion_quality"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, execute_external=True)
        project = director.sample_hyperframes_project
        project.mkdir(parents=True, exist_ok=True)
        storyboard = project / "storyboard.json"
        storyboard.write_text(json.dumps({"events": [{
            "id": "e1", "semantic_event_id": "semantic-1",
            "start": 1.0, "end": 3.0, "treatment": "structure",
        }]}), encoding="utf-8")
        director.sample_candidate_raw_path.write_bytes(b"raw-hyperframes")
        cue = project / "assets" / "e1.wav"
        cue.parent.mkdir(parents=True, exist_ok=True)
        cue.write_bytes(b"cue")
        audio_plan = project / "audio-plan.json"
        audio_plan.write_text(json.dumps({
            "speech_track": {"dominant": True},
            "motion_sfx": {
                "event_decisions": [{
                    "event_id": "e1", "decision": "cue", "asset": "assets/e1.wav",
                    "family": "structure", "start": 1.1, "duration_seconds": 1.2,
                    "volume": 0.2, "post_gain_mean_dbfs": -28.0,
                }],
                "mix_audibility_check": {"status": "pending_render_measurement"},
            },
            "background_music": {"mode": "disabled", "enabled": False,
                                 "reason": "explicitly disabled", "explicitly_disabled": True},
        }), encoding="utf-8")

        def fake_audibility(**kwargs):
            payload = json.loads(audio_plan.read_text(encoding="utf-8"))
            payload["motion_sfx"]["mix_audibility_check"] = {"status": "pass"}
            audio_plan.write_text(json.dumps(payload), encoding="utf-8")
            return [audio_plan]

        def fake_mix(**kwargs):
            kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["receipt_path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output"].write_bytes(b"raw-plus-sfx")
            kwargs["receipt_path"].write_text("{}", encoding="utf-8")
            return {}

        director._start("audio")
        with patch("director.materialize_sample_audio_evidence", side_effect=fake_audibility), \
                patch("director.materialize_sample_review_mix", side_effect=fake_mix) as mix:
            director.stage_audio()

        self.assertEqual(mix.call_count, 1)
        self.assertEqual(mix.call_args.kwargs["candidate_media"], director.sample_candidate_raw_path)
        self.assertEqual(mix.call_args.kwargs["audio_plan"], audio_plan)
        self.assertEqual(mix.call_args.kwargs["output"], director.sample_candidate_sfx_path)
        self.assertEqual(director.sample_candidate_review_raw_path, director.sample_candidate_sfx_path)
        self.assertFalse(director.sample_candidate_sfx_path.is_relative_to(
            director.sample_hyperframes_project,
        ))
        self.assertFalse(director.sample_review_mix_receipt_path.is_relative_to(
            director.sample_hyperframes_project,
        ))
        self.assertTrue(director.creative_review_audio_dir.is_relative_to(director.root))
        self.assertFalse(director.creative_review_audio_dir.is_relative_to(
            director.sample_hyperframes_project,
        ))

    def test_audio_stage_rebuilds_legacy_mix_evidence_inside_hyperframes_project(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {"production": {"enabled": True}, "sfx": {"enabled": True}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, execute_external=True)
        project = director.sample_hyperframes_project
        (project / "assets" / "sfx").mkdir(parents=True, exist_ok=True)
        (project / "storyboard.json").write_text(json.dumps({"events": [{
            "id": "e1", "semantic_event_id": "chapter:1", "start": 1.0, "end": 3.0,
            "treatment": "structure",
        }]}), encoding="utf-8")
        director.sample_candidate_raw_path.write_bytes(b"raw-hyperframes")
        legacy_evidence = project / "mix-audibility.json"
        legacy_evidence.write_text("{}", encoding="utf-8")
        plan = project / "audio-plan.json"
        plan.write_text(json.dumps({
            "motion_sfx": {
                "event_decisions": [{
                    "event_id": "e1", "decision": "cue", "asset": "assets/sfx/e1.wav",
                    "start": 1.1, "duration_seconds": 1.0, "volume": 0.2,
                }],
                "mix_audibility_check": {
                    "status": "pass", "evidence": "mix-audibility.json",
                    "evidence_sha256": sha256_file(legacy_evidence),
                },
            },
        }), encoding="utf-8")

        def fake_audibility(**kwargs):
            self.assertEqual(kwargs["output_dir"], director.creative_review_audio_dir)
            return [plan]

        director._start("audio")
        with patch("director.materialize_sample_audio_evidence", side_effect=fake_audibility) as measure, \
                patch("director.materialize_sample_review_mix"):
            director.stage_audio()

        self.assertEqual(measure.call_count, 1)

    def test_sample_review_without_cue_decisions_keeps_raw_hyperframes_candidate(self) -> None:
        director = Director(self.project)
        project = director.sample_hyperframes_project
        project.mkdir(parents=True, exist_ok=True)
        director.sample_candidate_raw_path.write_bytes(b"raw-hyperframes")
        (project / "audio-plan.json").write_text(json.dumps({
            "motion_sfx": {"event_decisions": [{
                "event_id": "e1", "decision": "intentionally_silent",
                "reason": "source sound already carries the beat",
            }]},
        }), encoding="utf-8")

        self.assertEqual(director.sample_candidate_review_raw_path, director.sample_candidate_raw_path)
        self.assertEqual(director.sample_candidate_path, director.sample_candidate_raw_path)

    def test_creative_review_finds_safe_audition_files_for_colon_event_id(self) -> None:
        from audio_production import audition_filename_stem

        director = Director(self.project)
        director.creative_review_audio_dir.mkdir(parents=True, exist_ok=True)
        stem = audition_filename_stem("chapter:1")
        for suffix in ("sfx-off", "sfx-on"):
            (director.creative_review_audio_dir / f"{stem}-{suffix}.wav").write_bytes(b"audio")

        auditions, missing = director._creative_review_audio_auditions(["chapter:1"])

        self.assertEqual(missing, [])
        self.assertEqual(set(auditions["chapter:1"]), {"sfx_off", "sfx_on"})

    def test_invalid_audio_plan_file_cannot_claim_asset_ready(self) -> None:
        director = Director(self.project)
        director.sample_hyperframes_project.mkdir(parents=True, exist_ok=True)
        (director.sample_hyperframes_project / "storyboard.json").write_text(
            json.dumps({"events": []}), encoding="utf-8"
        )
        (director.sample_hyperframes_project / "audio-plan.json").write_text(
            json.dumps({"schema_version": 3}), encoding="utf-8"
        )

        director._start("audio")
        director.stage_audio()

        stage = director.state["stages"]["audio"]
        self.assertEqual(stage["readiness"], "contract_ready")
        readiness = json.loads((director.root / "audio-readiness.json").read_text(
            encoding="utf-8"
        ))
        self.assertEqual(readiness["status"], "contract_ready")
        self.assertTrue(readiness["validation_errors"])

    def test_non_object_audio_plan_and_storyboard_fail_closed(self) -> None:
        for plan_payload, storyboard_payload in (([], {"events": []}), ({}, [])):
            director = Director(self.project)
            director.sample_hyperframes_project.mkdir(parents=True, exist_ok=True)
            (director.sample_hyperframes_project / "storyboard.json").write_text(
                json.dumps(storyboard_payload), encoding="utf-8"
            )
            (director.sample_hyperframes_project / "audio-plan.json").write_text(
                json.dumps(plan_payload), encoding="utf-8"
            )

            director._start("audio")
            director.stage_audio()

            self.assertEqual(director.state["stages"]["audio"]["readiness"], "contract_ready")

    def test_legacy_unbound_audio_evidence_cannot_claim_asset_ready_or_hash_assets(self) -> None:
        director = Director(self.project)
        project = director.sample_hyperframes_project
        cue = project / "assets" / "sfx" / "cue.wav"
        cue.parent.mkdir(parents=True, exist_ok=True)
        cue.write_bytes(b"cue-audio")
        mix = project / "mix-audibility.json"
        mix.write_text("{}", encoding="utf-8")
        (project / "storyboard.json").write_text(json.dumps({"events": [{
            "id": "e1", "start": 1.0, "end": 3.0, "treatment": "structure",
        }]}), encoding="utf-8")
        (project / "audio-plan.json").write_text(json.dumps({
            "speech_track": {"dominant": True},
            "motion_sfx": {
                "event_decisions": [{
                    "event_id": "e1", "decision": "cue", "asset": "assets/sfx/cue.wav",
                    "family": "explain", "start": 1.1, "duration_seconds": 1.2,
                    "volume": 0.2, "post_gain_mean_dbfs": -28.0,
                }],
                "mix_audibility_check": {"status": "pass", "evidence": "mix-audibility.json"},
            },
            "background_music": {
                "mode": "unavailable", "enabled": False,
                "reason": "no authorized provider", "attempts": [],
            },
            "provenance": {"source_audio": str(director.context.source_video)},
        }), encoding="utf-8")

        director._start("audio")
        director.stage_audio()

        stage = director.state["stages"]["audio"]
        self.assertEqual(stage["readiness"], "contract_ready")
        self.assertNotIn(str(cue.resolve()), stage["artifacts"])
        self.assertFalse(any(
            row["path"] == str(cue.resolve()) for row in stage["artifact_records"]
        ))

    def test_explicitly_disabled_cover_is_evidenced_not_applicable(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["cover"] = {"enabled": False}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)

        director._start("cover")
        director.stage_cover()

        self.assertEqual(director.state["stages"]["cover"]["readiness"], "not_applicable")
        decision = json.loads((director.root / "cover-decision.json").read_text(encoding="utf-8"))
        self.assertEqual(decision["status"], "disabled")

    def test_audio_and_cover_contracts_do_not_claim_assets_are_ready(self) -> None:
        director = Director(self.project)
        director._start("audio")
        director.stage_audio()
        director._start("cover")
        director.stage_cover()

        self.assertEqual(director.state["stages"]["audio"]["status"], "complete")
        self.assertEqual(director.state["stages"]["audio"]["readiness"], "contract_ready")
        self.assertEqual(director.state["stages"]["cover"]["status"], "complete")
        self.assertEqual(director.state["stages"]["cover"]["readiness"], "contract_ready")

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
        self._write_master_srt(director)
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

    def test_final_compose_uses_successful_bgm_from_full_audio_plan(self) -> None:
        bgm = self.root / "edit" / "audio" / "bgm" / "selected.wav"
        bgm.parent.mkdir(parents=True)
        bgm.write_bytes(b"generated-authorized-music")
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {"bgm": {"enabled_by_default": True}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"hyperframes-render")
        director.full_hyperframes_project.mkdir(parents=True)
        (director.full_hyperframes_project / "storyboard.json").write_text(
            json.dumps({"composition": {"duration": 20.0}}), encoding="utf-8"
        )
        (director.full_hyperframes_project / "audio-plan.json").write_text(json.dumps({
            "background_music": {"mode": "authorized_asset", "enabled": True,
                                 "source": str(bgm), "preview_volume": 0.08,
                                 "provenance": {"provider": "minimax", "sha256": sha256_file(bgm)}}
        }), encoding="utf-8")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        director._start("final_compose")
        with self.assertRaisesRegex(ValueError, "universal"):
            director.stage_final_compose()
        plan = json.loads((director.root / "final-compose-command.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["audio_mix"]["bgm_asset"], str(bgm))
        self.assertEqual(plan["audio_mix"]["source"], "full_audio_plan")
        self.assertEqual(plan["audio_mix"]["provider"], "minimax")

    def test_final_compose_runs_full_technical_qa_bound_to_output(self) -> None:
        director = Director(self.project, execute_external=True)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"motion")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        (director.video_use_dir / "edl.json").write_text(json.dumps({
            "ranges": [{"start": 0, "end": 4}, {"start": 8, "end": 12}]
        }), encoding="utf-8")

        def fake_qa(media, *, output, evidence_dir, cut_boundaries, true_peak_ceiling):
            self.assertEqual(media, director.delivery_output)
            self.assertEqual(cut_boundaries, [4.0])
            report = {"status": "pass", "file_sha256": sha256_file(media),
                      "decode": {"status": "pass"}, "blocking_errors": []}
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report), encoding="utf-8")
            return report

        def fake_compose(command, **_kwargs):
            target = Path(command[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"universal")

        director._start("final_compose")
        with patch("director.subprocess.run", side_effect=fake_compose), \
             patch("director.run_technical_qa", side_effect=fake_qa) as run:
            director.stage_final_compose()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(director.state["stages"]["final_compose"]["status"], "complete")

    def test_enabled_two_pass_normalization_is_hash_bound_and_keeps_one_delivery_output(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {"normalization": {"enabled": True, "target_lufs": -14.0,
                                                   "true_peak_dbtp": -1.5, "lra": 11.0}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, execute_external=True)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"motion")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")

        def fake_run(command, **kwargs):
            target = Path(command[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"pre-normalized")

        def fake_normalize(source, output, target_i, target_tp, lra):
            self.assertNotEqual(source, output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"normalized")
            return {"source": str(source), "source_sha256": sha256_file(source),
                    "output": str(output), "output_sha256": sha256_file(output),
                    "target": {"integrated_lufs": target_i, "true_peak_dbtp": target_tp,
                               "lra": lra},
                    "first_pass": {"input_i": "-19.0", "input_tp": "-4.0",
                                   "input_lra": "6.0", "input_thresh": "-29.0",
                                   "target_offset": "0.1"},
                    "post_measurement": {"input_i": str(target_i),
                                         "input_tp": str(target_tp),
                                         "input_lra": "6.0"},
                    "status": "pass"}

        def fake_qa(media, **kwargs):
            report = {"status": "pass", "file_sha256": sha256_file(media),
                      "decode": {"status": "pass"}, "blocking_errors": []}
            kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output"].write_text(json.dumps(report), encoding="utf-8")
            return report

        director._start("final_compose")
        with patch("director.subprocess.run", side_effect=fake_run), \
             patch("director.normalize_social_audio", side_effect=fake_normalize) as normalize, \
             patch("director.run_technical_qa", side_effect=fake_qa):
            director.stage_final_compose()

        self.assertEqual(normalize.call_count, 1)
        plan = json.loads((director.root / "final-compose-command.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["output"], str(director.delivery_output))
        self.assertTrue(plan["single_universal_output"])
        report = json.loads((director.root / "audio-normalization-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["output_sha256"], sha256_file(director.delivery_output))

    def test_final_compose_rebuilds_when_motion_hash_changes(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {"normalization": {"enabled": True}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, execute_external=True)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"motion-v1")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        compose_calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            compose_calls.append(command)
            target = Path(command[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"pre-" + motion.read_bytes())

        def fake_normalize(source, output, target_i, target_tp, lra):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"normalized-" + source.read_bytes())
            return {
                "status": "pass", "source_sha256": sha256_file(source),
                "output_sha256": sha256_file(output),
                "target": {"integrated_lufs": target_i,
                           "true_peak_dbtp": target_tp, "lra": lra},
                "first_pass": {"input_i": "-19", "input_tp": "-4",
                               "input_lra": "6", "input_thresh": "-29",
                               "target_offset": "0"},
                "post_measurement": {"input_i": str(target_i),
                                     "input_tp": str(target_tp), "input_lra": "6"},
            }

        def fake_qa(media, **kwargs):
            report = {"status": "pass", "file_sha256": sha256_file(media),
                      "decode": {"status": "pass"}, "blocking_errors": []}
            kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output"].write_text(json.dumps(report), encoding="utf-8")
            return report

        with patch("director.subprocess.run", side_effect=fake_run), \
             patch("director.normalize_social_audio", side_effect=fake_normalize), \
             patch("director.run_technical_qa", side_effect=fake_qa):
            director._start("final_compose")
            director.stage_final_compose()
            motion.write_bytes(b"motion-v2")
            director.stage_final_compose()
        self.assertEqual(len(compose_calls), 2)
        plan = json.loads((director.root / "final-compose-command.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["compose_input_sha256"], sha256_file(motion))
        self.assertEqual(plan["compose_output_sha256"], sha256_file(
            director.root / "final-compose-pre-normalized.mp4"
        ))

    def test_final_compose_adopts_exact_manual_command_output_on_resume(self) -> None:
        director = Director(self.project)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"motion")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        with self.assertRaisesRegex(DirectorContractError, "not present"):
            director.stage_final_compose()
        pending = json.loads((director.root / "final-compose-command.json").read_text(
            encoding="utf-8"
        ))
        self.assertEqual(pending["execution_status"], "awaiting_external_execution")
        director.delivery_output.parent.mkdir(parents=True, exist_ok=True)
        director.delivery_output.write_bytes(b"manually-composed")

        def fake_qa(media, **kwargs):
            report = {"status": "pass", "file_sha256": sha256_file(media),
                      "decode": {"status": "pass"}, "blocking_errors": []}
            kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output"].write_text(json.dumps(report), encoding="utf-8")
            return report

        resumed = Director(self.project)
        resumed._start("final_compose")
        with patch("director.run_technical_qa", side_effect=fake_qa):
            resumed.stage_final_compose()
        completed = json.loads((resumed.root / "final-compose-command.json").read_text(
            encoding="utf-8"
        ))
        self.assertEqual(completed["execution_status"], "adopted_external_output")
        self.assertEqual(completed["compose_output_sha256"], sha256_file(resumed.delivery_output))

    def test_full_audio_plan_bgm_hash_drift_blocks_composition(self) -> None:
        bgm = self.root / "edit" / "audio" / "bgm" / "selected.wav"
        bgm.parent.mkdir(parents=True)
        bgm.write_bytes(b"approved")
        approved_hash = sha256_file(bgm)
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["audio"] = {"bgm": {"enabled_by_default": True}}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        self._write_master_srt(director)
        motion = director.root / "render" / "full-hyperframes.mp4"
        motion.parent.mkdir(parents=True)
        motion.write_bytes(b"motion")
        director.full_hyperframes_project.mkdir(parents=True)
        (director.full_hyperframes_project / "storyboard.json").write_text(
            json.dumps({"composition": {"duration": 20.0}}), encoding="utf-8"
        )
        (director.full_hyperframes_project / "audio-plan.json").write_text(json.dumps({
            "background_music": {"mode": "authorized_asset", "enabled": True,
                                 "source": str(bgm),
                                 "provenance": {"provider": "minimax",
                                                "sha256": approved_hash}}
        }), encoding="utf-8")
        bgm.write_bytes(b"changed-after-approval")
        (director.root / "full-hyperframes-commands.json").write_text(json.dumps({
            "final_motion_render": {"expected_artifact": str(motion)}
        }), encoding="utf-8")
        with self.assertRaisesRegex(DirectorContractError, "BGM.*hash"):
            director.stage_final_compose()

    def test_enabled_render_cache_executes_hyperframes_through_cache_pipeline(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["render"] = {"cache": {"enabled": True}}
        config["provider_governance"] = {"providers": {
            task: [{"name": f"local-{task}", "available": True, "task_fit": 1.0,
                    "incremental_cost": 0.0, "cost_basis": "test local provider",
                    "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
                    "failure_incremental_cost": 0.0}]
            for task in ("sfx", "bgm")
        }}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, approve_final_render=True, execute_external=True)
        director._start("provider_governance"); director.stage_provider_governance()
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        authorize_final_render(Director(self.project), "tester")
        director = Director(self.project, approve_final_render=True, execute_external=True)
        output = director.root / "render" / "full-hyperframes.mp4"

        def fake_pipeline(config, root, cache, status_path, stop_after):
            stage = config["stages"][0]
            self.assertEqual(len(stage["atomic_outputs"]), 1)
            self.assertNotEqual(stage["atomic_outputs"][0]["working"],
                                stage["atomic_outputs"][0]["final"])
            self.assertIn(stage["atomic_outputs"][0]["working"], stage["partial_outputs"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"render")
            status_path.write_text(json.dumps({"state": "completed"}), encoding="utf-8")
            return {"state": "completed", "stages": {"graphics_render": {"state": "completed"}}}

        director._start("final_render")
        with patch("director.run_cached_pipeline", side_effect=fake_pipeline) as run:
            director.stage_final_render()
        self.assertEqual(run.call_count, 1)
        self.assertIn(str(director.root / "render-cache-status.json"),
                      director.state["stages"]["final_render"]["artifacts"])

    def test_event_render_cache_is_used_only_with_explicit_hyperframes_contract(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["render"] = {"cache": {"enabled": True, "event_level": {
            "enabled": True, "fallback_to_full_render": True,
        }}}
        config["provider_governance"] = {"providers": {
            task: [{"name": f"local-{task}", "available": True, "task_fit": 1.0,
                    "incremental_cost": 0.0, "cost_basis": "test local provider",
                    "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
                    "failure_incremental_cost": 0.0}]
            for task in ("sfx", "bgm")
        }}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, approve_final_render=True, execute_external=True)
        director._start("provider_governance"); director.stage_provider_governance()
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        authorize_final_render(Director(self.project), "tester")
        director = Director(self.project, approve_final_render=True, execute_external=True)

        def fake_event_render(**kwargs):
            output = Path(kwargs["output"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"event-render")
            return {"schema_version": 1, "mode": "hyperframes_event_cache",
                    "fingerprints": {}, "output_sha256": sha256_file(output)}

        director._start("final_render")
        with patch("director.execute_event_render_pipeline", side_effect=fake_event_render) as event_run, \
             patch("director.run_cached_pipeline") as full_run:
            director.stage_final_render()
        self.assertEqual(event_run.call_count, 1)
        full_run.assert_not_called()
        receipt = json.loads((director.root / "final-render-receipt.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(receipt["execution_mode"], "hyperframes_event_cache")

    def test_event_render_cache_safely_falls_back_to_full_hyperframes_render(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["render"] = {"cache": {"enabled": True, "event_level": {
            "enabled": True, "fallback_to_full_render": True,
        }}}
        config["provider_governance"] = {"providers": {
            task: [{"name": f"local-{task}", "available": True, "task_fit": 1.0,
                    "incremental_cost": 0.0, "cost_basis": "test local provider",
                    "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
                    "failure_incremental_cost": 0.0}]
            for task in ("sfx", "bgm")
        }}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project, approve_final_render=True, execute_external=True)
        director._start("provider_governance"); director.stage_provider_governance()
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        self._pass_full_hyperframes_qa(director)
        authorize_final_render(Director(self.project), "tester")
        director = Director(self.project, approve_final_render=True, execute_external=True)
        output = director.root / "render" / "full-hyperframes.mp4"

        def fake_full(config, root, cache, status_path, stop_after):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"full-render")
            status_path.write_text(json.dumps({"state": "completed"}), encoding="utf-8")
            return {"state": "completed"}

        director._start("final_render")
        with patch("director.execute_event_render_pipeline",
                   side_effect=__import__("event_render_pipeline").EventRenderUnavailable(
                       "missing event commands")), \
             patch("director.run_cached_pipeline", side_effect=fake_full):
            director.stage_final_render()
        fallback = json.loads((director.root / "event-render-cache-fallback.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(fallback["status"], "fallback_full_render")
        self.assertTrue(fallback["no_ffmpeg_or_static_motion_substitute"])

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
        (final_qa / "aesthetic-review.json").write_text(json.dumps({
            "reviewed_output_sha256": output_hash,
        }), encoding="utf-8")
        (final_qa / "cover-review.json").write_text(json.dumps({
            "status": "pending_user_identity_approval",
            "identity_reference_count": 2,
            "topic_relevant": True,
            "natural_expression_and_energy": True,
            "identity_approved_by_user": False,
            "cover_sha256": sha256_file(cover),
        }), encoding="utf-8")
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        (director.video_use_dir / "final-edit-correctness.json").write_text(json.dumps({}), encoding="utf-8")
        (director.video_use_dir / "edl.json").write_text(json.dumps({"ranges": []}), encoding="utf-8")
        (director.root / "final-media-report.json").write_text(json.dumps({"decode_status": "pass"}), encoding="utf-8")
        for platform in ("douyin", "wechat_channels"):
            (final_qa / f"platform-{platform}.json").write_text(json.dumps({
                "status": "pass",
                "file_sha256": output_hash,
                "cover_sha256": sha256_file(cover),
            }), encoding="utf-8")
        director.production_contract_path.write_text(json.dumps({}), encoding="utf-8")
        (director.root / "provider-decision.json").write_text(json.dumps({}), encoding="utf-8")
        (director.root / "cost-ledger.json").write_text(json.dumps({}), encoding="utf-8")
        for stage in ("video_use_timeline", "production_contract", "final_compose"):
            director.state["stages"][stage].update({
                "status": "complete", "readiness": "ready",
            })
        for path in (
            director.root / "sample-qa" / "visual-dynamics-qa.json",
            director.root / "full-qa" / "visual-dynamics-qa.json",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        with patch("director.validate_aesthetic_review", return_value=[]), \
                patch("director.validate_audio_plan", return_value=[]), \
                patch("director.validate_visual_dynamics_report", return_value=[]), \
                patch.object(director, "_validate_current_production_contract"), \
                patch.object(director, "_validate_provider_governance"), \
                patch("director.validate_video_use_final_correctness", return_value=[]), \
                patch("director.validate_technical_report", return_value=[]), \
                patch("director.validate_platform_report", return_value=[]):
            with self.assertRaisesRegex(DirectorContractError, "explicit user approval"):
                director.stage_delivery_qa()
        self.assertEqual(director.state["stages"]["delivery_qa"]["status"], "action_required")
        packet = json.loads(director.action_path.read_text(encoding="utf-8"))
        self.assertEqual(packet["actions"][0]["owner"], "user")

    def test_generic_cover_does_not_require_identity_references_or_user_likeness_approval(self) -> None:
        errors, identity_required = _cover_delivery_gate({
            "status": "pass",
            "identity_applicable": False,
            "identity_reference_count": 0,
            "identity_approved_by_user": False,
            "topic_relevant": True,
            "natural_expression_and_energy": True,
        })
        self.assertEqual(errors, [])
        self.assertFalse(identity_required)

    def test_optional_missing_cover_does_not_block_universal_delivery(self) -> None:
        director = Director(self.project)
        output = director.delivery_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"final-universal-video")
        output_hash = sha256_file(output)
        full = director.full_hyperframes_project
        full.mkdir(parents=True, exist_ok=True)
        (full / "storyboard.json").write_text(json.dumps({"events": []}), encoding="utf-8")
        (full / "audio-plan.json").write_text("{}", encoding="utf-8")
        final_qa = director.root / "final-qa"
        final_qa.mkdir(parents=True, exist_ok=True)
        (final_qa / "aesthetic-review.json").write_text(json.dumps({
            "reviewed_output_sha256": output_hash,
        }), encoding="utf-8")
        director.video_use_dir.mkdir(parents=True, exist_ok=True)
        (director.video_use_dir / "edl.json").write_text(
            json.dumps({"ranges": []}), encoding="utf-8"
        )
        (director.video_use_dir / "final-edit-correctness.json").write_text(
            "{}", encoding="utf-8"
        )
        (director.root / "final-media-report.json").write_text("{}", encoding="utf-8")
        director.production_contract_path.write_text("{}", encoding="utf-8")
        (director.root / "provider-decision.json").write_text("{}", encoding="utf-8")
        (director.root / "cost-ledger.json").write_text("{}", encoding="utf-8")
        for scope in ("sample-qa", "full-qa"):
            path = director.root / scope / "visual-dynamics-qa.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        for platform in ("douyin", "wechat_channels"):
            (final_qa / f"platform-{platform}.json").write_text(json.dumps({
                "status": "pass", "file_sha256": output_hash, "cover_sha256": None,
            }), encoding="utf-8")
        for stage in ("video_use_timeline", "production_contract", "final_compose"):
            director.state["stages"][stage].update({
                "status": "complete", "readiness": "ready",
            })

        with patch("director.validate_aesthetic_review", return_value=[]), \
                patch("director.validate_audio_plan", return_value=[]), \
                patch("director.validate_visual_dynamics_report", return_value=[]), \
                patch.object(director, "_validate_current_production_contract"), \
                patch.object(director, "_validate_provider_governance"), \
                patch("director.validate_video_use_final_correctness", return_value=[]), \
                patch("director.validate_technical_report", return_value=[]), \
                patch("director.validate_platform_report", return_value=[]):
            director.stage_delivery_qa()

        contract = json.loads((director.root / "delivery-contract.json").read_text(
            encoding="utf-8"
        ))
        self.assertEqual(contract["cover_applicability"], "optional_unavailable")
        self.assertIsNone(contract["cover"])
        self.assertEqual(director.state["stages"]["delivery_qa"]["status"], "complete")

    def test_optional_portable_audit_bundle_is_director_integrated_and_relocatable(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config.setdefault("delivery", {})["audit_bundle"] = {
            "enabled": True, "output_dir": "work/director/portable-audit-bundle",
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        contract = director.root / "delivery-contract.json"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(json.dumps({"status": "pass", "project": str(self.root)}),
                            encoding="utf-8")
        output = director.context.exports_dir / "video.mp4"
        cover = director.context.exports_dir / "cover.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        cover.write_bytes(b"cover")
        artifacts = director._build_optional_delivery_packages(
            output=output, cover=cover, delivery_contract=contract,
            required_evidence=[contract],
        )
        manifest = next(path for path in artifacts if path.name == "audit-bundle.json")
        self.assertTrue(manifest.is_file())
        verification = json.loads((director.root / "portable-audit-verification.json")
                                  .read_text(encoding="utf-8"))
        self.assertEqual(verification["status"], "pass")
        bundled_contract = manifest.parent / "artifacts" / contract.relative_to(self.root)
        self.assertNotIn(str(self.root), bundled_contract.read_text(encoding="utf-8"))

    def test_portable_audit_bundle_rejects_output_outside_project_root(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config.setdefault("delivery", {})["audit_bundle"] = {
            "enabled": True,
            "output_dir": str(self.root.parent / "outside-audit-bundle"),
        }
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        contract = director.root / "delivery-contract.json"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text("{}", encoding="utf-8")
        output = director.context.exports_dir / "video.mp4"
        cover = director.context.exports_dir / "cover.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        cover.write_bytes(b"cover")
        with self.assertRaisesRegex(DirectorContractError, "inside the project root"):
            director._build_optional_delivery_packages(
                output=output, cover=cover, delivery_contract=contract,
                required_evidence=[contract],
            )

    def test_platform_validation_generates_two_reports_for_same_universal_bytes(self) -> None:
        director = Director(self.project, execute_external=True)
        output = director.delivery_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"one-universal-file")
        cover = self.root / "cover.png"
        cover.write_bytes(b"cover")
        paths = {
            name: director.root / "final-qa" / f"platform-{name}.json"
            for name in ("douyin", "wechat_channels")
        }

        def fake_run(command, **_kwargs):
            report = Path(command[command.index("--out") + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({
                "status": "pass", "file_sha256": sha256_file(output),
                "cover_sha256": sha256_file(cover),
                "media": str(output),
            }), encoding="utf-8")
            return type("Result", (), {"returncode": 0, "stderr": ""})()

        with patch("director.subprocess.run", side_effect=fake_run) as run:
            director._ensure_platform_validations(output, cover, paths)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(path.is_file() for path in paths.values()))
        self.assertTrue(all(str(output) in call.args[0] for call in run.call_args_list))

    def test_platform_validation_rebuilds_reports_when_cover_bytes_change(self) -> None:
        director = Director(self.project, execute_external=True)
        output = director.delivery_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"one-universal-file")
        cover = self.root / "cover.png"
        cover.write_bytes(b"cover-v1")
        paths = {
            name: director.root / "final-qa" / f"platform-{name}.json"
            for name in ("douyin", "wechat_channels")
        }

        def fake_run(command, **_kwargs):
            report = Path(command[command.index("--out") + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({
                "status": "pass",
                "file_sha256": sha256_file(output),
                "cover_sha256": sha256_file(cover),
            }), encoding="utf-8")
            return type("Result", (), {"returncode": 0, "stderr": ""})()

        with patch("director.subprocess.run", side_effect=fake_run) as run:
            director._ensure_platform_validations(output, cover, paths)
            self.assertEqual(run.call_count, 2)
            cover.write_bytes(b"cover-v2")
            director._ensure_platform_validations(output, cover, paths)
            self.assertEqual(run.call_count, 4)

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

    def test_full_hyperframes_qa_runs_enabled_golden_editorial_regression(self) -> None:
        config = yaml.safe_load(self.project.read_text(encoding="utf-8"))
        config["editorial_regression"] = {"enabled": True}
        self.project.write_text(yaml.safe_dump(config), encoding="utf-8")
        director = Director(self.project)
        self._write_full_hyperframes_contract(director)
        director._start("full_hyperframes_storyboard")
        director.stage_full_hyperframes_storyboard()
        baseline = director.root / "editorial-regression" / "golden-baseline.json"
        create_baseline(
            storyboard_path=director.full_hyperframes_project / "storyboard.json",
            semantic_brief_path=director.full_semantic_brief_path,
            audio_plan_path=None, cover_plan_path=None, correction_ledger_path=None,
            approved_by="hongr", output=baseline,
        )
        self._pass_full_hyperframes_qa(director)
        report = director.root / "full-qa" / "editorial-regression.json"
        self.assertTrue(report.is_file())
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "pass")

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
