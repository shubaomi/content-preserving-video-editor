from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sys
import tempfile
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import (  # noqa: E402
    VISUAL_VOCABULARY,
    detect_input_mode,
    sha256_file,
    validate_semantic_brief,
    validate_semantic_evidence_binding,
    validate_storyboard,
    validate_video_use_edl,
    validate_video_use_edit_preflight,
    validate_video_use_final_correctness,
    validate_video_use_media_analysis,
    validate_visual_vocabulary_audit,
    read_json,
    write_json,
    exclusive_file_lock,
)


def event(identifier: str, anchor: str, start: float, archetype: str) -> dict:
    return {
        "id": identifier,
        "start": start,
        "end": start + 4,
        "source_start": start,
        "source_end": start + 4,
        "output_start": start,
        "output_end": start + 4,
        "anchor": anchor,
        "transcript_quote": f"这里真正讲的是{anchor}的作用",
        "transcript_word_ids": [identifier + "-w1"],
        "viewer_takeaway": f"理解{anchor}的作用",
        "approved_visible_copy": f"{anchor}的作用",
        "relevance_rationale": "把抽象关系转成可见结构",
        "visual_structure": {
            "dom_structure": archetype + "-dom",
            "information_hierarchy": archetype + "-hierarchy",
            "layout_archetype": archetype,
            "animation_choreography": archetype + "-motion",
            "use_case": archetype + "-case",
        },
    }


def valid_brief() -> dict:
    return {
        "schema_version": 1,
        "generated_by": "agent-llm",
        "content_reading": "raw_word_transcript_and_evidence_frames",
        "transcript_sha256": "a" * 64,
        "evidence_frames": ["frame-001.png"],
        "events": [
            event("e1", "知识关系图", 10, "process-path"),
            event("e2", "免费版与高级版", 30, "comparison-split"),
            event("e3", "三步生成流程", 55, "step-rail"),
            event("e4", "五个核心模块", 75, "numeric-result"),
        ],
    }


def valid_storyboard(brief: dict | None = None) -> dict:
    brief = brief or valid_brief()
    events = deepcopy(brief["events"])
    for storyboard_event in events:
        storyboard_event["semantic_event_id"] = storyboard_event["id"]
        approved_copy = storyboard_event.get("approved_visible_copy")
        storyboard_event["visible_copy_manifest"] = (
            [approved_copy] if isinstance(approved_copy, str) and approved_copy.strip() else []
        )
        if isinstance(approved_copy, list):
            storyboard_event["visible_copy_manifest"] = list(approved_copy)
    return {
        "renderer": "hyperframes",
        "motion_output": "hyperframes_render",
        "capability_skills": [
            "hyperframes", "hyperframes-core", "hyperframes-creative",
            "hyperframes-animation", "hyperframes-cli",
        ],
        "events": events,
    }


def decision_complete_brief() -> dict:
    brief = valid_brief()
    brief.update({
        "schema_version": 3,
        "opportunity_model": "decision_complete_v1",
        "evidence_bundle_sha256": "b" * 64,
        "opening_hook": {"status": "not_selected", "evidence": ["direct opening"]},
    })
    decisions = ("render", "caption_only", "reuse_source", "quiet_source")
    for index, semantic_event in enumerate(brief["events"]):
        semantic_event.update({
            "decision": decisions[index],
            "decision_rationale": f"editorial decision {index}",
            "viewer_job": "understand",
            "visual_mechanism": "source-grounded explanation",
            "target_frame_evidence": ["frame-001.png"],
            "protected_zones": {"face": [], "ui": [], "caption": [], "cursor": []},
            "form": "process",
            "placement": "left",
            "size": "medium",
            "background": "transparent",
            "read_time": 1.0,
            "motion": {
                "entrance": "fade", "reveal": "draw", "hold": "steady", "exit": "fade",
            },
            "audio_decision": {"type": "intentionally_silent", "reason": "test fixture"},
            "deduplication": {"semantic": "unique", "visual": "not rendered"},
        })
        semantic_event["approved_visible_copy"] = [semantic_event["approved_visible_copy"]]
        if semantic_event["decision"] == "quiet_source":
            semantic_event["treatment"] = "quiet_source"
            semantic_event["source_activity_evidence"] = ["source remains explanatory"]
    return brief


def selected_storyboard(brief: dict) -> dict:
    selected = {
        str(row["id"]): row
        for row in brief["events"]
        if row.get("decision") == "render"
    }
    storyboard = valid_storyboard({"events": list(selected.values())})
    return storyboard


class DirectorContractTests(unittest.TestCase):
    def test_atomic_json_writes_use_unique_temporaries_under_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "shared.json"
            with ThreadPoolExecutor(max_workers=16) as pool:
                list(pool.map(lambda value: write_json(target, {"value": value}), range(200)))
            self.assertIn(read_json(target)["value"], range(200))
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_file_lock_reclaims_verified_stale_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "state.json"
            lock = target.with_suffix(".json.lock")
            lock.write_text('{"pid": 999999}', encoding="utf-8")
            old = time.time() - 10
            os.utime(lock, (old, old))
            with exclusive_file_lock(target, timeout_seconds=0.2, stale_seconds=1):
                self.assertTrue(lock.is_file())
            self.assertFalse(lock.exists())

    def test_semantic_brief_requires_four_real_structures(self) -> None:
        self.assertEqual(validate_semantic_brief(valid_brief(), require_sample_variety=True), [])

    def test_decision_complete_brief_accepts_one_render_and_evidenced_nonrender_decisions(self) -> None:
        brief = decision_complete_brief()

        self.assertEqual(validate_semantic_brief(brief, require_sample_variety=True), [])
        self.assertEqual(validate_storyboard(selected_storyboard(brief), brief), [])

    def test_target_binding_metadata_is_not_misclassified_as_visible_copy(self) -> None:
        brief = decision_complete_brief()
        storyboard = selected_storyboard(brief)
        storyboard["events"][0].update({
            "target_binding_required": True,
            "target_binding_ids": ["binding-e1"],
        })

        self.assertEqual(validate_storyboard(storyboard, brief), [])

    def test_decision_complete_brief_requires_one_decision_and_rationale_per_opportunity(self) -> None:
        for field in ("decision", "decision_rationale"):
            with self.subTest(field=field):
                brief = decision_complete_brief()
                del brief["events"][1][field]
                errors = validate_semantic_brief(brief, require_sample_variety=True)
                self.assertTrue(any(field in error for error in errors), errors)

    def test_every_decision_complete_opportunity_requires_visual_evidence(self) -> None:
        brief = decision_complete_brief()
        del brief["events"][1]["target_frame_evidence"]

        errors = validate_semantic_brief(brief, require_sample_variety=True)

        self.assertTrue(any("target_frame_evidence" in error for error in errors), errors)

    def test_render_decision_requires_approved_copy(self) -> None:
        brief = decision_complete_brief()
        brief["events"][0]["approved_visible_copy"] = []

        errors = validate_semantic_brief(brief, require_sample_variety=True)

        self.assertTrue(any("approved_visible_copy" in error for error in errors), errors)

    def test_optional_product_occlusion_focus_is_typed_and_approved(self) -> None:
        brief = decision_complete_brief()
        brief["events"][0]["occlusion_focus"] = {
            "primary": "product", "status": "approved",
        }
        self.assertEqual(validate_semantic_brief(brief, require_sample_variety=True), [])
        for invalid in (
            {"primary": "face", "status": "approved"},
            {"primary": "product", "status": "draft"},
            {"primary": "product", "status": "approved", "extra": True},
            "product",
        ):
            with self.subTest(invalid=invalid):
                bad = decision_complete_brief()
                bad["events"][0]["occlusion_focus"] = invalid
                errors = validate_semantic_brief(bad, require_sample_variety=True)
                self.assertTrue(any("occlusion_focus" in error for error in errors), errors)

    def test_storyboard_is_ordered_render_subset_not_all_opportunities(self) -> None:
        brief = decision_complete_brief()
        storyboard = selected_storyboard(brief)
        storyboard["events"].append(deepcopy(brief["events"][1]))
        storyboard["events"][-1]["semantic_event_id"] = brief["events"][1]["id"]
        storyboard["events"][-1]["visible_copy_manifest"] = list(
            brief["events"][1]["approved_visible_copy"]
        )

        errors = validate_storyboard(storyboard, brief)

        self.assertTrue(any("render decision" in error for error in errors), errors)

        two_render = decision_complete_brief()
        two_render["events"][1]["decision"] = "render"
        reordered = selected_storyboard(two_render)
        reordered["events"].reverse()
        errors = validate_storyboard(reordered, two_render)
        self.assertTrue(any("order" in error for error in errors), errors)

    def test_nonrender_opportunities_do_not_create_visual_family_quotas(self) -> None:
        brief = decision_complete_brief()
        brief["events"][1]["visual_structure"] = dict(brief["events"][0]["visual_structure"])

        self.assertEqual(validate_semantic_brief(brief, require_sample_variety=True), [])

    def test_decision_complete_opportunities_preserve_source_and_output_order(self) -> None:
        brief = decision_complete_brief()
        brief["events"][0], brief["events"][1] = brief["events"][1], brief["events"][0]

        errors = validate_semantic_brief(brief, require_sample_variety=True)

        self.assertTrue(any("opportunity order" in error for error in errors), errors)

    def test_low_information_anchor_is_blocking(self) -> None:
        brief = valid_brief()
        brief["events"][0]["anchor"] = "打开"
        errors = validate_semantic_brief(brief, require_sample_variety=True)
        self.assertTrue(any("low-information" in error for error in errors))

    def test_duplicate_structure_is_not_variety(self) -> None:
        brief = valid_brief()
        brief["events"][1]["visual_structure"] = dict(brief["events"][0]["visual_structure"])
        errors = validate_semantic_brief(brief, require_sample_variety=True)
        self.assertTrue(any("duplicates a previous visual structure" in error for error in errors))

    def test_storyboard_must_render_with_hyperframes(self) -> None:
        brief = valid_brief()
        storyboard = {
            "renderer": "ffmpeg",
            "motion_output": "preview_only",
            "capability_skills": [],
            "events": brief["events"],
        }
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("renderer must be hyperframes" in error for error in errors))
        self.assertTrue(any("motion_output must be hyperframes_render" in error for error in errors))

    def test_storyboard_accepts_exact_semantic_copy_and_explicit_semantic_ids(self) -> None:
        brief = valid_brief()
        self.assertEqual(validate_storyboard(valid_storyboard(brief), brief), [])

        storyboard = valid_storyboard(brief)
        for index, storyboard_event in enumerate(storyboard["events"]):
            storyboard_event["id"] = f"render-event-{index}"
        self.assertEqual(validate_storyboard(storyboard, brief), [])

        del storyboard["events"][0]["semantic_event_id"]
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("explicit semantic_event_id" in error for error in errors))

    def test_storyboard_rejects_unrelated_or_reordered_semantic_event_ids(self) -> None:
        brief = valid_brief()
        unrelated = valid_storyboard(brief)
        for index, storyboard_event in enumerate(unrelated["events"]):
            storyboard_event["id"] = f"unrelated-{index}"
            storyboard_event["semantic_event_id"] = f"unrelated-{index}"
        errors = validate_storyboard(unrelated, brief)
        self.assertTrue(any("semantic event set" in error for error in errors))

        reordered = valid_storyboard(brief)
        reordered["events"][0], reordered["events"][1] = (
            reordered["events"][1], reordered["events"][0],
        )
        errors = validate_storyboard(reordered, brief)
        self.assertTrue(any("semantic event order" in error for error in errors))

    def test_storyboard_rejects_repeated_open_and_all_semantic_field_drift(self) -> None:
        brief = valid_brief()
        repeated_open = valid_storyboard(brief)
        for storyboard_event in repeated_open["events"]:
            storyboard_event["anchor"] = "打开"
        errors = validate_storyboard(repeated_open, brief)
        self.assertTrue(any("anchor" in error for error in errors))

        mutations = {
            "anchor": "另一个含义",
            "transcript_word_ids": ["unrelated-word"],
            "source_start": 999,
            "source_end": 1000,
            "output_start": 999,
            "output_end": 1000,
            "viewer_takeaway": "无关结论",
            "approved_visible_copy": "未批准文案",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                storyboard = valid_storyboard(brief)
                storyboard["events"][0][field] = value
                errors = validate_storyboard(storyboard, brief)
                self.assertTrue(any(field in error for error in errors), errors)

    def test_quiet_source_still_binds_identity_order_and_time_window(self) -> None:
        brief = valid_brief()
        quiet = {
            "id": "quiet-tail", "treatment": "quiet_source",
            "source_start": 90, "source_end": 100,
            "output_start": 90, "output_end": 100,
            "source_activity_evidence": ["screen remains active"],
        }
        brief["events"].append(quiet)
        storyboard = valid_storyboard(brief)
        self.assertEqual(validate_storyboard(storyboard, brief), [])

        missing_explicit_id = valid_storyboard(brief)
        del missing_explicit_id["events"][-1]["semantic_event_id"]
        errors = validate_storyboard(missing_explicit_id, brief)
        self.assertTrue(any("explicit semantic_event_id" in error for error in errors))

        storyboard["events"][-1]["output_start"] = 91
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("output_start" in error for error in errors))

    def test_storyboard_rejects_quiet_classification_and_render_window_drift(self) -> None:
        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["treatment"] = "quiet_source"
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("quiet_source classification" in error for error in errors))

        quiet = {
            "id": "quiet-tail", "treatment": "quiet_source",
            "source_start": 90, "source_end": 100,
            "output_start": 90, "output_end": 100,
            "source_activity_evidence": ["screen remains active"],
        }
        brief["events"].append(quiet)
        storyboard = valid_storyboard(brief)
        storyboard["events"][-1]["treatment"] = "keyword_typography"
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("quiet_source classification" in error for error in errors))

        for field, value in (("start", 999), ("end", 1000)):
            with self.subTest(field=field):
                storyboard = valid_storyboard(valid_brief())
                storyboard["events"][0][field] = value
                errors = validate_storyboard(storyboard, valid_brief())
                self.assertTrue(any(field in error for error in errors), errors)

        brief = valid_brief()
        brief["events"][0]["treatment"] = "steps"
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["treatment"] = "comparison"
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("treatment" in error for error in errors))

        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["treatment"] = "comparison"
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("unapproved treatment" in error for error in errors))

    def test_storyboard_cannot_add_visible_copy_that_the_brief_did_not_approve(self) -> None:
        brief = valid_brief()
        del brief["events"][0]["approved_visible_copy"]
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["approved_visible_copy"] = "Storyboard 自行添加的文案"

        errors = validate_storyboard(storyboard, brief)

        self.assertTrue(any("unapproved visible copy" in error for error in errors))

    def test_storyboard_rejects_hidden_or_nested_visible_copy_fields(self) -> None:
        brief = valid_brief()
        mutations = (
            {"display_text": "打开"},
            {"headline": "打开"},
            {"heading": "打开"},
            {"content": "打开"},
            {"description": "打开"},
            {"message": "打开"},
            {"innerHTML": "打开"},
            {"components": [{"type": "text", "children": "打开"}]},
            {"components": [{"approved_visible_copy": "打开"}]},
            {"components": [{"visible_copy_manifest": ["打开"]}]},
            {"visible-copy-manifest": ["打开"]},
            {"Visible_Copy_Manifest": ["打开"]},
            {"approved-visible-copy": "打开"},
            {"Approved_Visible_Copy": "打开"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                storyboard = valid_storyboard(brief)
                storyboard["events"][0].update(mutation)
                errors = validate_storyboard(storyboard, brief)
                self.assertTrue(any("visible copy" in error for error in errors), errors)

        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["visible_copy_manifest"] = ["打开"]
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("visible_copy_manifest" in error for error in errors), errors)

    def test_typed_connector_relations_are_nonvisible_metadata(self) -> None:
        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["geometry_contract"] = {
            "connector_contract": {
                "required_connector_count": 1,
                "attachment_intent": "semantic nodes",
                "relations": [{
                    "from": "source-node",
                    "to": "target-node",
                    "attachment_edge": "right-to-left",
                }],
            },
        }

        self.assertEqual(validate_storyboard(storyboard, brief), [])

    def test_motion_compiler_binding_fields_are_nonvisible_metadata(self) -> None:
        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0].update({
            "motion_design_contract_id": "motion-contract-1",
            "recipe_id": "MQE-02",
            "choreography_fingerprint_sha256": "a" * 64,
        })

        self.assertEqual(validate_storyboard(storyboard, brief), [])

    def test_relation_visual_requires_a_typed_connector_contract(self) -> None:
        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["visual_structure"]["layout_archetype"] = (
            "paired-highlight-brace"
        )
        brief["events"][0]["visual_structure"]["layout_archetype"] = (
            "paired-highlight-brace"
        )

        errors = validate_storyboard(storyboard, brief)

        self.assertTrue(any("connector contract" in error for error in errors), errors)

    def test_target_bound_visual_requires_source_state_evidence(self) -> None:
        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["visual_structure"]["layout_archetype"] = (
            "source-ui-highlight-overlay"
        )
        brief["events"][0]["visual_structure"]["layout_archetype"] = (
            "source-ui-highlight-overlay"
        )

        errors = validate_storyboard(storyboard, brief)

        self.assertTrue(any("target region contract" in error for error in errors), errors)

    def test_complete_target_region_contract_is_accepted(self) -> None:
        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["visual_structure"]["layout_archetype"] = (
            "source-ui-highlight-overlay"
        )
        brief["events"][0]["visual_structure"]["layout_archetype"] = (
            "source-ui-highlight-overlay"
        )
        storyboard["events"][0]["geometry_contract"] = {
            "target_region_contract": {
                "tracking_mode": "scene_bounded",
                "active_selector": "#e1 .source-target",
                "required_target_count": 1,
                "target_ids": ["primary-chart"],
                "minimum_useful_content_ratio": 0.35,
                "maximum_static_state_delta": 0.12,
                "active_output_start": 10.5,
                "active_output_end": 13.5,
                "active_source_start": 10.5,
                "active_source_end": 13.5,
                "source_state_evidence": [
                    {
                        "phase": phase,
                        "timestamp_seconds": timestamp,
                        "path": f"C:/evidence/{phase}.png",
                        "sha256": character * 64,
                    }
                    for phase, timestamp, character in (
                        ("entrance", 10.6, "a"),
                        ("midpoint", 12.0, "b"),
                        ("pre_exit", 13.4, "c"),
                    )
                ],
            }
        }

        self.assertEqual(validate_storyboard(storyboard, brief), [])

    def test_target_region_contract_requires_an_active_render_selector(self) -> None:
        brief = valid_brief()
        storyboard = valid_storyboard(brief)
        storyboard["events"][0]["visual_structure"]["layout_archetype"] = (
            "source-ui-highlight-overlay"
        )
        brief["events"][0]["visual_structure"]["layout_archetype"] = (
            "source-ui-highlight-overlay"
        )
        storyboard["events"][0]["geometry_contract"] = {
            "target_region_contract": {
                "tracking_mode": "scene_bounded",
                "required_target_count": 1,
                "target_ids": ["primary-chart"],
                "minimum_useful_content_ratio": 0.35,
                "active_output_start": 10.5,
                "active_output_end": 13.5,
                "active_source_start": 10.5,
                "active_source_end": 13.5,
                "source_state_evidence": [
                    {"phase": phase, "timestamp_seconds": timestamp,
                     "path": f"C:/evidence/{phase}.png", "sha256": "a" * 64}
                    for phase, timestamp in (
                        ("entrance", 10.6), ("midpoint", 12.0), ("pre_exit", 13.4)
                    )
                ],
            }
        }

        errors = validate_storyboard(storyboard, brief)

        self.assertTrue(any("active_selector" in error for error in errors), errors)

    def test_malformed_storyboard_events_return_errors_instead_of_crashing(self) -> None:
        brief = valid_brief()
        for events in ({"e1": {}}, ["bad-event"]):
            with self.subTest(events=events):
                storyboard = valid_storyboard(brief)
                storyboard["events"] = events
                errors = validate_storyboard(storyboard, brief)
                self.assertTrue(any("events" in error for error in errors), errors)

    def test_semantic_target_frame_coverage_must_overlap_event_source_window(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            frame = root / "frame.png"
            frame.write_bytes(b"png")
            bundle_path = root / "evidence-bundle.json"

            def write_bundle(coverage: dict | None) -> dict:
                frame_record = {"path": str(frame.resolve()), "sha256": sha256_file(frame)}
                if coverage is not None:
                    frame_record["coverage"] = coverage
                bundle = {
                    "transcript": {
                        "sha256": sha256_file(transcript),
                        "term_evidence": [{
                            "word_id": "w1", "text": "proof", "start": 10.0, "end": 11.0,
                        }],
                    },
                    "representative_frames": [frame_record],
                }
                bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
                return {
                    "schema_version": 2,
                    "transcript_sha256": sha256_file(transcript),
                    "evidence_bundle_sha256": sha256_file(bundle_path),
                    "evidence_frames": [str(frame)],
                    "events": [{
                        "id": "event-1", "transcript_word_ids": ["w1"],
                        "transcript_quote": "proof", "source_start": 10.0,
                        "source_end": 11.0, "target_frame_evidence": [str(frame)],
                    }],
                }

            brief = write_bundle({"start_seconds": 0.0, "end_seconds": 5.0})
            errors = validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path,
            )
            self.assertTrue(any("target frame coverage" in error for error in errors))

            brief = write_bundle({"start_seconds": 9.0, "end_seconds": 12.0})
            self.assertEqual(validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path,
            ), [])

            malformed_coverages = (
                {"start_seconds": 9.0},
                {"start_seconds": 12.0, "end_seconds": 9.0},
                {"start_seconds": float("nan"), "end_seconds": 12.0},
                {"start_seconds": 9.0, "end_seconds": float("inf")},
            )
            for coverage in malformed_coverages:
                with self.subTest(coverage=coverage):
                    brief = write_bundle(coverage)
                    errors = validate_semantic_evidence_binding(
                        brief, transcript_path=transcript, evidence_bundle_path=bundle_path,
                    )
                    self.assertTrue(any("malformed target frame coverage" in error for error in errors))

            brief = write_bundle({"status": "unknown", "reason": "legacy frame timestamp absent"})
            self.assertEqual(validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path,
            ), [])

            brief = write_bundle(None)
            self.assertEqual(validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path,
            ), [])

            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["representative_frames"][0]["timestamp_seconds"] = 80.0
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            brief["evidence_bundle_sha256"] = sha256_file(bundle_path)
            errors = validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path,
            )
            self.assertTrue(any("target frame timestamp" in error for error in errors), errors)

    def test_every_timestamped_target_frame_must_overlap_the_event(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
            near = root / "near.png"
            far = root / "far.png"
            near.write_bytes(b"near")
            far.write_bytes(b"far")
            bundle_path = root / "evidence-bundle.json"
            bundle = {
                "transcript": {
                    "sha256": sha256_file(transcript),
                    "term_evidence": [{
                        "word_id": "w1", "text": "proof", "start": 10.0, "end": 11.0,
                    }],
                },
                "representative_frames": [
                    {"path": str(near), "sha256": sha256_file(near),
                     "timestamp_seconds": 10.5,
                     "coverage": {"start_seconds": 9.0, "end_seconds": 12.0}},
                    {"path": str(far), "sha256": sha256_file(far),
                     "timestamp_seconds": 80.0,
                     "coverage": {"start_seconds": 0.0, "end_seconds": 100.0}},
                ],
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            brief = {
                "schema_version": 2,
                "transcript_sha256": sha256_file(transcript),
                "evidence_bundle_sha256": sha256_file(bundle_path),
                "evidence_frames": [str(near), str(far)],
                "events": [{
                    "id": "event-1", "transcript_word_ids": ["w1"],
                    "transcript_quote": "proof", "source_start": 10.0, "source_end": 11.0,
                    "target_frame_evidence": [str(near), str(far)],
                }],
            }

            errors = validate_semantic_evidence_binding(
                brief, transcript_path=transcript, evidence_bundle_path=bundle_path,
            )

            self.assertTrue(any("target frame timestamp" in error for error in errors), errors)

    def test_existing_edit_is_detected_without_changing_preservation_policy(self) -> None:
        project = {"source": {"input_mode": "existing_edit_polish"}}
        self.assertEqual(detect_input_mode(project, Path("source.mp4")), "polish_existing")

    def test_undeclared_mode_requires_analysis_instead_of_guessing_preserve(self) -> None:
        self.assertEqual(detect_input_mode({}, Path("recording.mp4")), "needs_analysis")
        self.assertEqual(
            detect_input_mode({}, Path("recording.mp4"), {"selected_mode": "polish_existing"}),
            "polish_existing",
        )
        self.assertEqual(
            detect_input_mode({"source": {"input_mode": "raw"}}, Path("recording.mp4")),
            "preserve",
        )

    def test_visual_vocabulary_requires_an_explicit_decision_for_all_ten_categories(self) -> None:
        brief = valid_brief()
        storyboard = {
            "renderer": "hyperframes",
            "motion_output": "hyperframes_render",
            "capability_skills": ["hyperframes", "hyperframes-core", "hyperframes-creative",
                                  "hyperframes-animation", "hyperframes-cli"],
            "events": brief["events"],
        }
        selected = {
            name: {"status": "selected", "event_ids": [brief["events"][index]["id"]],
                   "evidence": [f"frame-{index}.png"]}
            for index, name in enumerate(VISUAL_VOCABULARY[:4])
        }
        rejected = {
            name: {"status": "not_applicable", "rationale": "not supported by this sample's speech",
                   "evidence": ["transcript.json"]}
            for name in VISUAL_VOCABULARY[4:]
        }
        audit = {"categories": {**selected, **rejected}}
        self.assertEqual(validate_visual_vocabulary_audit(audit, storyboard), [])
        del audit["categories"]["ip_asset"]
        self.assertTrue(any("ip_asset" in error for error in validate_visual_vocabulary_audit(audit, storyboard)))

    def test_full_visual_vocabulary_requires_per_chapter_decisions(self) -> None:
        brief = valid_brief()
        storyboard = {"events": brief["events"]}
        audit = {"categories": {
            name: ({"status": "selected", "event_ids": [brief["events"][index % 4]["id"]],
                    "evidence": ["frame.png"]}
                   if index < 4 else
                   {"status": "not_applicable", "rationale": "not in transcript", "evidence": ["words.json"]})
            for index, name in enumerate(VISUAL_VOCABULARY)
        }}
        errors = validate_visual_vocabulary_audit(audit, storyboard, full_video=True)
        self.assertTrue(any("chapter_decisions" in error for error in errors))

    def test_four_category_labels_cannot_all_claim_one_structure(self) -> None:
        brief = valid_brief()
        storyboard = {"events": brief["events"]}
        audit = {"categories": {
            name: ({"status": "selected", "event_ids": ["e1"], "evidence": ["frame.png"]}
                   if index < 4 else
                   {"status": "not_applicable", "rationale": "not present", "evidence": ["words.json"]})
            for index, name in enumerate(VISUAL_VOCABULARY)
        }}
        errors = validate_visual_vocabulary_audit(audit, storyboard)
        self.assertTrue(any("four distinct storyboard events" in error for error in errors))

    def test_decision_complete_visual_vocabulary_does_not_invent_four_events(self) -> None:
        storyboard = {"events": [{"id": "e1"}]}
        audit = {"categories": {
            name: (
                {"status": "selected", "event_ids": ["e1"], "evidence": ["frame.png"]}
                if index == 0 else
                {"status": "not_applicable", "rationale": "not supported by the content",
                 "evidence": ["words.json"]}
            )
            for index, name in enumerate(VISUAL_VOCABULARY)
        }}

        self.assertEqual(
            validate_visual_vocabulary_audit(
                audit, storyboard, decision_complete=True,
            ),
            [],
        )

    def test_video_use_edl_owns_cut_policy_and_preserves_existing_timeline(self) -> None:
        edl = {
            "owner": "video-use",
            "sources": {"source": "source.mp4"},
            "ranges": [{"source": "source", "start": 0, "end": 100}],
            "cut_policy": {"word_boundary_padding_ms": [30, 100], "audio_fade_ms": 30},
        }
        self.assertEqual(validate_video_use_edl(
            edl, source_name="source", source_duration=100, input_mode="polish_existing"
        ), [])
        edl["owner"] = "director"
        edl["ranges"][0]["end"] = 80
        errors = validate_video_use_edl(
            edl, source_name="source", source_duration=100, input_mode="polish_existing"
        )
        self.assertTrue(any("owner must be video-use" in error for error in errors))
        self.assertTrue(any("source tail" in error for error in errors))
        self.assertTrue(any("established timeline" in error for error in errors))

    def test_video_use_media_and_edit_preflight_require_real_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            views = []
            for index in range(3):
                view = root / f"view-{index}.png"
                view.write_bytes(b"png")
                views.append(str(view))
            media = {
                "owner": "video-use",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "duration_seconds": 100,
                "video_stream": {"width": 1920, "height": 1080},
                "audio_stream": {"codec": "aac"},
                "timeline_views": views,
            }
            self.assertEqual(validate_video_use_media_analysis(
                media, source_path=source, source_duration=100
            ), [])
            transcript = root / "transcript.json"
            transcript.write_text("{}", encoding="utf-8")
            edl_path = root / "edl.json"
            edl = {"ranges": [{"start": 0, "end": 100}]}
            edl_path.write_text(json.dumps(edl), encoding="utf-8")
            preflight = {
                "owner": "video-use", "status": "pass", "boundary_count": 0,
                "boundaries": [], "identity_timeline": True, "tail_covered": True,
                "expected_output_duration": 100,
                "edl_sha256": hashlib.sha256(edl_path.read_bytes()).hexdigest(),
                "transcript_sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
            }
            self.assertEqual(validate_video_use_edit_preflight(
                preflight, edl_path=edl_path, transcript_path=transcript, edl=edl
            ), [])
            preflight["identity_timeline"] = False
            self.assertTrue(any("identity_timeline" in error for error in validate_video_use_edit_preflight(
                preflight, edl_path=edl_path, transcript_path=transcript, edl=edl
            )))

    def test_final_video_use_correctness_binds_universal_output_and_overview_views(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "universal.mp4"
            output.write_bytes(b"final")
            views = []
            for name in ("first", "middle", "last"):
                view = root / f"{name}.png"
                view.write_bytes(b"png")
                views.append(str(view))
            edl = {"ranges": [{"start": 0, "end": 100}]}
            report = {
                "owner": "video-use", "status": "pass",
                "output_sha256": hashlib.sha256(b"final").hexdigest(),
                "expected_output_duration": 100,
                "actual_output_duration": 100.1,
                "boundary_reviews": [],
                "overview_timeline_views": views,
            }
            self.assertEqual(validate_video_use_final_correctness(
                report, output_path=output, edl=edl
            ), [])
            report["output_sha256"] = "0" * 64
            self.assertTrue(any("output hash" in error for error in validate_video_use_final_correctness(
                report, output_path=output, edl=edl
            )))


if __name__ == "__main__":
    unittest.main()
