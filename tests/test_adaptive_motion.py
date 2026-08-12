from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


PLANNER = load("attention_planner")
AUDIT = load("motion_density_audit")
ARTIFACTS = load("materialize_dynamic_artifacts")
HYPERFRAMES = load("build_dynamic_hyperframes")
COMPOSITOR = load("composite_dynamic_overlay")
SFX = load("build_local_sfx_library")


class AdaptiveMotionTests(unittest.TestCase):
    @staticmethod
    def resolve_layout(plan):
        for event in plan["events"]:
            event["collision_check"] = {
                "status": "clear",
                "evidence": "fixture geometry review",
                "avoid": ["captions", "face", "cursor", "platform_ui"],
            }
            event["redundancy_check"] = {
                "status": "clear",
                "decision": "source remains primary; overlay adds a distinct cue",
            }
            if event.get("safe_zone") == "unresolved":
                event["safe_zone"] = "top_right"
                event["layout_selector"] = "fixture_geometry"
        return plan

    def test_dynamic_planner_is_repeatable_and_preserves_burned_caption_contract(self):
        segments = [
            {"start": index * 6 + 3, "end": index * 6 + 6,
             "text": f"Step {index + 1}: click the button because this is the key difference."}
            for index in range(20)
        ]
        first = PLANNER.plan_attention_events(segments, 125, content_type="polish_existing", seed="fixed", burned_captions=True)
        second = PLANNER.plan_attention_events(segments, 125, content_type="polish_existing", seed="fixed", burned_captions=True)
        self.assertEqual(first, second)
        self.assertTrue(all(event["caption"]["duplicate_full_caption_forbidden"] for event in first["events"]))
        self.assertTrue(all(len(event["caption"]["highlight_terms"]) <= 3 for event in first["events"]))
        self.assertTrue(all(event["tier"] in {"micro", "meso", "macro"} for event in first["events"]))
        self.assertTrue(all(event["render_contract"]["markup_family"] for event in first["events"]))
        self.assertTrue(all(event["sfx"]["enabled"] for event in first["events"]))
        self.assertTrue(all(event["sfx"]["duration_seconds"] >= 0.9 for event in first["events"]))
        self.assertEqual(len({event["sfx"]["variant"] for event in first["events"]}), len(first["events"]))

    def test_density_audit_catches_family_and_sfx_rules(self):
        segments = [
            {"start": index * 5 + 3, "end": index * 5 + 5.5,
             "text": f"Click Module{index + 1} because Result{index + 1} is important."}
            for index in range(24)
        ]
        plan = self.resolve_layout(PLANNER.plan_attention_events(
            segments, 125, content_type="screen_tutorial", seed="audit",
            glossary=[item for index in range(24) for item in (f"Module{index + 1}", f"Result{index + 1}")]))
        report = AUDIT.audit(plan)
        self.assertIn("snapshot_plan", report)
        self.assertTrue(report["passed"], report["checks"])

    def test_ui_operation_requires_an_object_instead_of_using_the_verb_as_the_anchor(self):
        for verb in ("delete", "refresh", "verify"):
            purpose, terms, score = PLANNER._anchor(f"Now {verb} the record.")
            self.assertEqual(purpose, "ui_action")
            self.assertNotIn(verb, terms)
            self.assertIn("record", terms)
            self.assertGreater(score, 2)

    def test_low_information_chinese_ui_verbs_are_never_visible_anchors(self):
        purpose, terms, _ = PLANNER._anchor("就是他可以通过这个插件方便的管理所有打开的各种各样的")
        self.assertEqual(purpose, "ui_action")
        self.assertNotIn("打开", terms)
        self.assertTrue(any("插件" in term for term in terms))
        _, empty_terms, score = PLANNER._anchor("然后打开")
        self.assertEqual(empty_terms, [])
        self.assertLess(score, PLANNER.MIN_SEMANTIC_SCORE)

    def test_concrete_chinese_noun_phrases_create_verified_motion_anchors(self):
        cases = {
            "这是一个用来解释复杂概念的网站小工具。": "网站小工具",
            "这里会生成短视频素材和小红书文案。": "短视频素材",
            "可以看到后台完整的请求流程。": "请求流程",
        }
        for text, expected in cases.items():
            _, terms, score = PLANNER._anchor(text)
            self.assertIn(expected, terms)
            self.assertGreaterEqual(score, PLANNER.MIN_SEMANTIC_SCORE)

    def test_explanation_variants_rotate_between_distinct_real_renderers(self):
        even = {"purpose": "explanation", "segment_index": 2, "semantic_anchor": ["语言模型"]}
        odd = {"purpose": "explanation", "segment_index": 3, "semantic_anchor": ["历史记录"]}
        self.assertEqual(PLANNER._variant(even), "icon_pop")
        self.assertEqual(PLANNER._variant(odd), "icon_path")

    def test_multi_anchor_explanation_can_become_a_real_step_structure(self):
        candidate = {
            "purpose": "explanation", "segment_index": 6,
            "semantic_anchor": ["输入", "拆解", "理解"], "text": "输入后完成拆解与理解",
        }
        self.assertEqual(PLANNER._variant(candidate), "step_rail")
        self.assertEqual(PLANNER._family(candidate), "structure")

    def test_unverified_title_case_stt_token_requires_project_glossary(self):
        _, terms, score = PLANNER._anchor("Now open Folk.")
        self.assertEqual(terms, [])
        self.assertLess(score, PLANNER.MIN_SEMANTIC_SCORE)
        _, verified_terms, verified_score = PLANNER._anchor("Now open Fork.", ("Fork",))
        self.assertIn("Fork", verified_terms)
        self.assertGreaterEqual(verified_score, PLANNER.MIN_SEMANTIC_SCORE)

    def test_ui_action_does_not_borrow_an_unrelated_object_from_another_clause(self):
        purpose, terms, score = PLANNER._anchor("刷新一下,关掉还有这个傻瓜和音效的效果。")
        self.assertEqual(purpose, "ui_action")
        self.assertEqual(terms, [])
        self.assertLess(score, PLANNER.MIN_SEMANTIC_SCORE)
        _, fragment_terms, fragment_score = PLANNER._anchor("再打开一个的话,")
        self.assertEqual(fragment_terms, [])
        self.assertLess(fragment_score, PLANNER.MIN_SEMANTIC_SCORE)

    def test_planner_prefers_quiet_over_forced_low_information_fillers(self):
        segments = [
            {"start": index * 8 + 2, "end": index * 8 + 4, "text": "然后打开"}
            for index in range(12)
        ]
        plan = PLANNER.plan_attention_events(segments, 100, seed="quiet")
        self.assertEqual(plan["events"], [])
        self.assertEqual(plan["constraints"]["event_rate_policy"], "quality_bounded_target")
        self.assertTrue(plan["intentional_quiet_sections"])
        self.assertFalse(plan["intentional_quiet_sections"][0]["evidence"]["verified"])

    def test_exact_anchor_repetition_is_cooled_down(self):
        segments = [
            {"start": index * 8 + 2, "end": index * 8 + 5, "text": "现在打开新建标签页进行管理。"}
            for index in range(12)
        ]
        plan = PLANNER.plan_attention_events(segments, 100, seed="repeat")
        starts = [event["start"] for event in plan["events"] if "新建标签页" in event["semantic_anchor"]]
        self.assertLessEqual(len(starts), 2)
        self.assertTrue(all(right - left >= 40 for left, right in zip(starts, starts[1:])))

    def test_density_audit_rejects_unexplained_quiet_and_layer_overflow(self):
        plan = {
            "duration": 30,
            "constraints": {"maximum_visual_quiet_gap_seconds": 12, "max_concurrent_layers": 2,
                            "same_family_max_consecutive": 2, "family_max_share": 1,
                            "normal_window_min_families": 1, "same_sfx_file_cooldown_seconds": 20,
                            "sfx_min_per_minute": 0, "sfx_max_per_minute": 6},
            "attention_events": [
                {"id": "one", "start": 1, "end": 10, "tier": "meso", "visual_family": "structure", "motion_variant": "step_rail", "semantic_anchor": ["step"], "transcript_evidence": {"text": "First step"}, "collision_check": {"status": "pending_geometry_snapshot"}, "sfx": {"enabled": False}},
                {"id": "two", "start": 2, "end": 9, "tier": "micro", "visual_family": "ui_attention", "motion_variant": "focus_ring", "semantic_anchor": ["click"], "transcript_evidence": {"text": "Click"}, "collision_check": {"status": "pending_geometry_snapshot"}, "sfx": {"enabled": False}},
                {"id": "three", "start": 3, "end": 8, "tier": "micro", "visual_family": "semantic_icon", "motion_variant": "icon_pop", "semantic_anchor": ["check"], "transcript_evidence": {"text": "Check"}, "collision_check": {"status": "pending_geometry_snapshot"}, "sfx": {"enabled": False}},
            ],
        }
        report = AUDIT.audit(plan)
        checks = {item["name"]: item for item in report["checks"]}
        self.assertFalse(checks["maximum_visual_quiet_gap"]["passed"])
        self.assertFalse(checks["concurrent_visual_layers"]["passed"])

    def test_density_audit_rejects_pending_geometry_and_low_information_anchor(self):
        plan = {
            "duration": 8,
            "constraints": {"event_rate_policy": "advisory_ceiling", "maximum_events_per_minute": 12,
                            "maximum_visual_quiet_gap_seconds": 12, "max_concurrent_layers": 2,
                            "same_family_max_consecutive": 2, "family_max_share": 1,
                            "normal_window_min_families": 1, "same_sfx_file_cooldown_seconds": 20,
                            "sfx_max_per_minute": 6},
            "events": [{
                "id": "bad", "start": 2, "end": 3.5, "tier": "micro",
                "visual_family": "ui_attention", "motion_variant": "focus_ring",
                "semantic_anchor": ["打开"], "semantic_score": 3.5,
                "transcript_evidence": {"text": "然后打开"},
                "collision_check": {"status": "pending_geometry_snapshot"},
                "redundancy_check": {"status": "pending_visual_inventory"},
                "sfx": {"enabled": False},
            }],
        }
        report = AUDIT.audit(plan)
        checks = {item["name"]: item for item in report["checks"]}
        self.assertFalse(checks["semantic_anchor_quality"]["passed"])
        self.assertFalse(checks["resolved_layout_and_redundancy"]["passed"])
        self.assertFalse(report["passed"])

    def test_generic_quiet_reason_cannot_bypass_density_and_gap_gates(self):
        plan = {
            "duration": 90,
            "constraints": {
                "minimum_events_per_minute": 2.5,
                "maximum_events_per_minute": 5,
                "maximum_visual_quiet_gap_seconds": 20,
                "max_concurrent_layers": 1,
                "family_max_share": 1,
            },
            "events": [],
            "intentional_quiet_sections": [{
                "start": 0, "end": 90,
                "reason": "source UI is primary",
                "evidence": {"kind": "planner_no_candidate", "verified": False, "samples": []},
            }],
        }
        report = AUDIT.audit(plan)
        checks = {item["name"]: item for item in report["checks"]}
        self.assertFalse(checks["attention_event_rate_floor"]["passed"])
        self.assertFalse(checks["maximum_visual_quiet_gap"]["passed"])
        self.assertFalse(report["passed"])

    def test_materialized_artifacts_keep_editable_selectors_and_no_second_bgm(self):
        plan = PLANNER.plan_attention_events(
            [{"start": 3, "end": 7, "text": "First click the button because it is important."}],
            12, seed="artifacts")
        motion = ARTIFACTS.motion_plan(plan, 1920, 1080, 30)
        audio = ARTIFACTS.audio_plan(plan, {"audio": {"existing_bgm": "yes"}})
        visual = ARTIFACTS.visual_audit(plan)
        self.assertTrue(all(item["editableLayer"].endswith(".event-host") for item in motion["beats"]))
        self.assertFalse(audio["tracks"]["bgm"]["enabled"])
        self.assertTrue(visual["sections"])

    def test_key_matte_uses_an_opaque_baseline_while_transparent_source_stays_separate(self):
        plan = self.resolve_layout(PLANNER.plan_attention_events(
            [{"start": 3, "end": 7, "text": "First click the button because it is important."}],
            12, seed="matte"))
        transparent = HYPERFRAMES.build(plan, ROOT / "tests" / "fixture.mp4", "overlay", 1920, 1080, "screen_tutorial", True)
        matte = HYPERFRAMES.build(plan, ROOT / "tests" / "fixture.mp4", "overlay", 1920, 1080, "screen_tutorial")
        self.assertIn("background:transparent", transparent)
        self.assertIn('src="baseline.mp4"', matte)
        self.assertNotIn("data-layout-allow-overflow", matte)
        self.assertNotIn("data-layout-allow-occlusion", matte)

    def test_renderer_blocks_unresolved_layout_outside_layout_preview(self):
        plan = PLANNER.plan_attention_events(
            [{"start": 3, "end": 7, "text": "First click the button because the result matters."}],
            12, seed="pending")
        with self.assertRaisesRegex(ValueError, "unresolved layout"):
            HYPERFRAMES.build(plan, ROOT / "tests" / "fixture.mp4", "overlay", 1920, 1080, "screen_tutorial")

    def test_renderer_has_real_variant_markup_and_css(self):
        event = {
            "id": "ui", "start": 1, "duration": 2, "visual_family": "ui_attention",
            "motion_variant": "cursor_click", "safe_zone": "top_right",
            "purpose": "ui_action", "semantic_anchor": ["新建标签页"],
            "collision_check": {"status": "clear"},
            "redundancy_check": {"status": "clear"},
        }
        plan = {"duration": 5, "events": [event]}
        output = HYPERFRAMES.build(plan, ROOT / "tests" / "fixture.mp4", "overlay", 1920, 1080, "screen_tutorial")
        self.assertIn('data-variant="cursor_click"', output)
        self.assertIn("cursor-pointer", output)
        self.assertIn(".cursor_click .editable-surface", output)

    def test_structural_variants_have_different_markup_not_only_different_names(self):
        base = {
            "start": 1, "duration": 2, "safe_zone": "top_right",
            "purpose": "explanation", "semantic_anchor": ["输入", "理解", "结果"],
        }
        compare = HYPERFRAMES.visual_markup({**base, "id": "compare", "visual_family": "structure", "motion_variant": "compare_split"}, 1, "screen_tutorial")
        flow = HYPERFRAMES.visual_markup({**base, "id": "flow", "visual_family": "structure", "motion_variant": "cause_effect_link"}, 2, "screen_tutorial")
        chapter = HYPERFRAMES.visual_markup({**base, "id": "chapter", "visual_family": "chapter_transition", "motion_variant": "section_reveal"}, 3, "screen_tutorial")
        self.assertIn("compare-grid", compare)
        self.assertIn("flow-nodes", flow)
        self.assertIn("flow-path", flow)
        self.assertIn("chapter-index", chapter)
        self.assertNotEqual(compare, flow)

    def test_matte_compositor_mixes_only_baseline_and_sfx_tracks(self):
        command = COMPOSITOR.command(Path("baseline.mp4"), Path("overlay.webm"), Path("out.mp4"), "0x00ff00")
        filtergraph = command[command.index("-filter_complex") + 1]
        self.assertIn("chromakey=0x00ff00", filtergraph)
        self.assertIn("amix=inputs=2", filtergraph)
        self.assertIn("normalize=0", filtergraph)

    def test_key_color_coverage_rejects_black_and_accepts_green(self):
        green = bytes((0, 255, 0)) * 4
        black = bytes((0, 0, 0)) * 4
        expected = COMPOSITOR.parse_rgb("0x00ff00")
        self.assertEqual(COMPOSITOR.key_color_coverage(green, expected), 1.0)
        self.assertEqual(COMPOSITOR.key_color_coverage(black, expected), 0.0)

    def test_local_sfx_chain_applies_loudness_peak_and_silence_controls(self):
        chain = SFX.filter_for("click_switch", 660)
        self.assertIn("silenceremove", chain)
        self.assertIn("loudnorm=I=-24:TP=-3", chain)
        self.assertIn("alimiter=limit=0.7079", chain)

    def test_event_sfx_is_a_long_multi_note_treatment_specific_motif(self):
        family, chain, duration = SFX.event_filter({"treatment": "chapter_transition"}, 1)
        other_family, other_chain, other_duration = SFX.event_filter({"treatment": "process_nodes"}, 2)
        self.assertEqual(family, "chapter_chime")
        self.assertEqual(other_family, "process_sequence")
        self.assertGreaterEqual(duration, 0.9)
        self.assertGreaterEqual(other_duration, 0.9)
        self.assertIn("aevalsrc=", chain)
        self.assertGreaterEqual(chain.count("between(t"), 4)
        self.assertNotEqual(chain, other_chain)

    def test_unknown_but_semantic_layout_names_do_not_all_fall_back_to_soft_motif(self):
        families = {
            SFX.event_profile({"treatment": treatment}, index)[0]
            for index, treatment in enumerate((
                "source-ui-highlight-overlay",
                "metric-comparison-lens",
                "request-route-connector",
                "product-step-list",
            ), 1)
        }

        self.assertNotIn("soft_motif", families)
        self.assertGreaterEqual(len(families), 3)

    def test_explicit_semantic_audio_family_controls_the_generated_motif(self):
        expected = {
            "soft-focus": "soft_focus",
            "two-note-contrast": "two_note_contrast",
            "phrase": "phrase_rise",
        }

        actual = {
            family: SFX.event_profile({
                "audio_decision": {"type": "cue", "family": family},
                "visual_structure": {"layout_archetype": "upper-safe-band-mark"},
            }, index)[0]
            for index, family in enumerate(expected, 1)
        }

        self.assertEqual(actual, expected)

    def test_hyperframes_sfx_markup_uses_planned_landing_duration_and_volume(self):
        event = {
            "start": 10.0,
            "sfx": {"enabled": True, "family": "chime", "variant": "event.wav",
                    "duration_seconds": 1.24, "landing_offset_seconds": 0.22, "volume": 0.28},
        }
        markup = HYPERFRAMES.sfx_markup(event, 3)
        self.assertIn('data-start="10.220"', markup)
        self.assertIn('data-duration="1.24"', markup)
        self.assertIn('data-volume="0.28"', markup)

    def test_audio_plan_from_manifest_keeps_speech_dominant_and_bgm_ducked(self):
        plan = SFX.audio_plan_from_manifest(
            {"event_decisions": [{"event_id": "one", "decision": "cue"}]},
            source_audio="source.mp4", bgm="audio/bgm.mp3", bgm_file=ROOT / "tests" / "fixture.mp4",
            bgm_provenance={"provider": "test", "authorization": "user-owned", "sha256": "abc"},
            audibility_evidence="qa/audio.json", preview_volume=0.10,
        )
        self.assertTrue(plan["speech_track"]["dominant"])
        self.assertEqual(plan["motion_sfx"]["event_decisions"][0]["event_id"], "one")
        self.assertEqual(plan["background_music"]["mode"], "authorized_asset")
        self.assertEqual(plan["background_music"]["ducking"]["method"], "sidechaincompress")

    def test_polish_markup_uses_compact_keywords_not_caption_clauses(self):
        event = {
            "id": "caption-safe", "start": 1, "duration": 2,
            "visual_family": "semantic_icon", "motion_variant": "icon_path",
            "safe_zone": "top_right", "purpose": "explanation",
            "semantic_anchor": ["我没有人类那种真正的情绪和感受"],
        }
        markup = HYPERFRAMES.visual_markup(event, 1, "polish_existing")
        self.assertIn("情绪和感受", markup)
        self.assertNotIn("我没有人类那种真正的情绪和感受", markup)
        self.assertIn("family-semantic_icon", markup)

    def test_polish_keyword_prefers_compact_domain_phrase(self):
        event = {"semantic_anchor": ["你会介意别人听出你有战疆口音呢"]}
        self.assertEqual(HYPERFRAMES.display_terms(event, "polish_existing"), "战疆口音")

    def test_ip_visual_mounts_approved_asset_instead_of_hr_placeholder(self):
        event = {
            "id": "ip", "start": 1, "duration": 2, "visual_family": "ip_visual",
            "motion_variant": "mini_scene_window", "safe_zone": "top_right",
            "purpose": "explanation", "semantic_anchor": ["模型"],
        }
        markup = HYPERFRAMES.visual_markup(event, 1, "polish_existing", "assets/ip/hongrun.png")
        self.assertIn('class="ip-portrait"', markup)
        self.assertIn('src="assets/ip/hongrun.png"', markup)
        self.assertNotIn(">HR<", markup)

    def test_ip_visual_without_an_approved_asset_is_rejected(self):
        event = {
            "id": "ip", "start": 1, "duration": 2, "visual_family": "ip_visual",
            "motion_variant": "mini_scene_window", "safe_zone": "top_right",
            "purpose": "explanation", "semantic_anchor": ["模型"],
        }
        with self.assertRaisesRegex(ValueError, "approved IP asset"):
            HYPERFRAMES.visual_markup(event, 1, "polish_existing")


if __name__ == "__main__":
    unittest.main()
