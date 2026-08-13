from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capability_registry import (  # noqa: E402
    CAPABILITY_LEVELS,
    build_capability_inventory,
    build_toolchain_report,
    validate_maturity_transition,
)
from director import Director  # noqa: E402


class CapabilityRegistryTests(unittest.TestCase):
    def test_maturity_vocabulary_matches_the_approved_five_states(self) -> None:
        self.assertEqual(CAPABILITY_LEVELS, (
            "documented",
            "director_integrated",
            "fixture_validated",
            "real_project_validated",
            "production_default",
        ))

    def test_fixture_maturity_cannot_jump_to_production_default(self) -> None:
        errors = validate_maturity_transition(
            "fixture_validated", "production_default", evidence={}
        )
        self.assertTrue(any("jump" in error for error in errors), errors)

    def test_director_integration_promotion_requires_route_state_invalidation_and_failure_contract(self) -> None:
        self.assertTrue(validate_maturity_transition(
            "documented", "director_integrated", evidence={}
        ))
        self.assertEqual(validate_maturity_transition(
            "documented",
            "director_integrated",
            evidence={"director_integration": {
                "route": True,
                "state": True,
                "invalidation": True,
                "failure_contract": True,
            }},
        ), [])

    def test_fixture_promotion_requires_zero_failure_hash_bound_test_receipt(self) -> None:
        self.assertTrue(validate_maturity_transition(
            "director_integrated", "fixture_validated", evidence={}
        ))
        self.assertEqual(validate_maturity_transition(
            "director_integrated",
            "fixture_validated",
            evidence={"fixture_validation": {
                "status": "pass",
                "test_count": 4,
                "failures": 0,
                "skipped": 0,
                "source_tree_sha256": "b" * 64,
            }},
        ), [])

    def test_real_project_promotion_requires_both_canaries_and_user_evidence(self) -> None:
        implementation = "a" * 64
        valid_evidence = {
            "real_project_validations": [
                {
                    "canary_role": "landscape_screen",
                    "status": "pass",
                    "implementation_sha256": implementation,
                    "user_review_status": "approved",
                },
                {
                    "canary_role": "portrait_talking_head",
                    "status": "pass",
                    "implementation_sha256": implementation,
                    "user_review_status": "approved",
                },
            ],
        }
        self.assertEqual(validate_maturity_transition(
            "fixture_validated", "real_project_validated", evidence=valid_evidence
        ), [])
        missing_portrait = {
            "real_project_validations": valid_evidence["real_project_validations"][:1],
        }
        self.assertTrue(validate_maturity_transition(
            "fixture_validated", "real_project_validated", evidence=missing_portrait
        ))

    def test_production_default_requires_separate_explicit_promotion(self) -> None:
        self.assertTrue(validate_maturity_transition(
            "real_project_validated", "production_default", evidence={}
        ))
        receipt = {
            "kind": "hongrun_portrait_production_default_approval",
            "actor": "HongRun",
            "decision": "approve_production_default",
            "authentication_method": "codex_authenticated_thread_explicit_statement",
            "thread_id": "thread-1",
            "decision_text": "明确批准作为生产默认",
        }
        receipt["integrity_sha256"] = hashlib.sha256(json.dumps(
            receipt, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        self.assertTrue(validate_maturity_transition(
            "real_project_validated",
            "production_default",
            evidence={"production_promotion": {
                "approved": True,
                "approved_by": "HongRun",
                "approved_at": "2026-08-11T03:00:12-07:00",
                "receipt": receipt,
            }},
        ))
        forged = dict(receipt)
        forged["actor"] = "agent"
        forged["integrity_sha256"] = hashlib.sha256(json.dumps(
            {key: value for key, value in forged.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        self.assertTrue(validate_maturity_transition(
            "real_project_validated", "production_default",
            evidence={"production_promotion": {
                "approved": True, "approved_by": "agent", "approved_at": "now",
                "receipt": forged,
            }},
        ))

    def test_inventory_declares_complete_adapter_contract_and_truthful_levels(self) -> None:
        project = {
            "schema_version": 3,
            "workflow": {"capabilities": {"design_tokens": {"enabled": True}}},
        }
        inventory = build_capability_inventory(project)
        by_name = {row["name"]: row for row in inventory["capabilities"]}

        self.assertTrue({"design_tokens", "render_cache", "asr_router", "otio_timeline"} <= set(by_name))
        self.assertTrue({
            "production_contract", "visual_dynamics_qa", "provider_governance",
            "local_semantic_corpus", "brand_motion_playbook", "editorial_regression",
            "review_dashboard", "clip_factory", "podcast_pipeline",
            "localization_pipeline", "openmontage_handoff",
            "adaptive_layout", "stateful_target_binding",
            "motion_quality_engine",
            "hyperframes_keyframe_evidence",
            "paired_creative_review",
            "content_format_motion_grammar",
            "portrait_brand_motion_v2",
            "perceptual_motion_audio",
            "caption_sync_closure",
            "editorial_promise_closure",
            "current_golden_runtime_evidence",
            "advanced_runtime_gate",
            "typed_nle_handoff",
            "optional_media_adapters",
        } <= set(by_name))
        self.assertEqual(by_name["adaptive_layout"]["declared_maturity"], "fixture_validated")
        self.assertIn(by_name["adaptive_layout"]["maturity"], {"director_integrated", "fixture_validated"})
        self.assertEqual(by_name["stateful_target_binding"]["declared_maturity"], "fixture_validated")
        self.assertEqual(by_name["motion_quality_engine"]["declared_maturity"], "fixture_validated")
        self.assertEqual(by_name["hyperframes_keyframe_evidence"]["declared_maturity"], "fixture_validated")
        self.assertEqual(by_name["paired_creative_review"]["declared_maturity"], "fixture_validated")
        self.assertEqual(
            by_name["portrait_brand_motion_v2"]["declared_maturity"],
            "real_project_validated",
        )
        self.assertIn(
            by_name["portrait_brand_motion_v2"]["maturity"],
            {"director_integrated", "fixture_validated", "real_project_validated"},
        )
        for name in (
            "content_format_motion_grammar", "perceptual_motion_audio",
            "caption_sync_closure", "editorial_promise_closure",
            "current_golden_runtime_evidence", "advanced_runtime_gate",
            "typed_nle_handoff", "optional_media_adapters",
        ):
            self.assertEqual(by_name[name]["declared_maturity"], "fixture_validated")
        self.assertFalse(by_name["openmontage_handoff"]["enabled"])
        self.assertEqual(by_name["production_contract"]["maturity"], "director_integrated")
        required = {
            "name", "owner", "dependencies", "compatibility", "inputs", "outputs",
            "optional", "cache_key_fields", "failure_fallback", "enabled", "route_reason",
            "maturity", "capability_version", "configuration_route",
        }
        self.assertTrue(all(required <= set(row) for row in by_name.values()))
        self.assertEqual(by_name["design_tokens"]["maturity"], "director_integrated")
        self.assertTrue(by_name["design_tokens"]["enabled"])
        self.assertFalse(by_name["otio_timeline"]["enabled"])
        self.assertIn(by_name["otio_timeline"]["maturity"], CAPABILITY_LEVELS)
        minimum = CAPABILITY_LEVELS.index("director_integrated")
        self.assertTrue(all(CAPABILITY_LEVELS.index(row["maturity"]) >= minimum
                            for row in by_name.values()))

    @patch("portrait_golden.validate_retained_real_project_portrait_validation")
    @patch("test_acceptance_report.validate_report", return_value=[])
    def test_action_required_portrait_receipt_skips_expensive_live_validation(
        self, _fixture_validator, retained_validator,
    ) -> None:
        inventory = build_capability_inventory({})
        retained_validator.assert_not_called()
        portrait = next(
            row for row in inventory["capabilities"]
            if row["name"] == "portrait_brand_motion_v2"
        )
        self.assertEqual("fixture_validated", portrait["maturity"])
        self.assertIn("missing or stale", portrait["maturity_reason"])

    def test_toolchain_report_records_versions_without_installing_or_updating(self) -> None:
        with patch("capability_registry.shutil.which", side_effect=lambda name: f"C:/tools/{name}.exe"):
            with patch("capability_registry._command_version", return_value="1.2.3"):
                report = build_toolchain_report(probe_versions=True)

        self.assertFalse(report["mutates_toolchain"])
        self.assertEqual(report["update_policy"], "never_silent")
        self.assertTrue(report["tools"]["ffmpeg"]["available"])
        self.assertEqual(report["tools"]["ffmpeg"]["detected_version"], "1.2.3")
        self.assertIn("supported_range", report["tools"]["hyperframes"])
        self.assertIn("npx", report["tools"])
        self.assertEqual(report["tools"]["hyperframes"]["invocation_fallback"], "npx hyperframes")
        required_skills = report["required_hyperframes_skills"]
        self.assertEqual(set(required_skills), {
            "hyperframes", "hyperframes-core", "hyperframes-creative",
            "hyperframes-animation", "hyperframes-cli",
        })
        self.assertTrue(all("available" in row and "path" in row
                            for row in required_skills.values()))

    def test_inventory_uses_canonical_schema_paths_for_optional_backends(self) -> None:
        inventory = build_capability_inventory({
            "transcription": {"router": {"enabled": True}},
            "timeline": {"otio": {"enabled": True}},
            "render": {"cache": {"enabled": True}},
            "extensions": {"b_roll": {"enabled": True}},
            "renderer": {"remotion": {"enabled": True}},
            "feedback": {"metrics_import": {"enabled": True}},
            "analysis": {"hook_pacing": {"enabled": True}},
            "publishing": {"copy": {"enabled": True}},
            "assets": {"media_catalog": {"enabled": True}},
        })
        enabled = {row["name"] for row in inventory["capabilities"] if row["enabled"]}
        self.assertTrue({"asr_router", "otio_timeline", "render_cache", "b_roll",
                         "remotion_renderer", "post_publish_metrics"} <= enabled)
        self.assertTrue({"hook_pacing", "publishing_copy", "media_catalog"} <= enabled)
        self.assertIn("evidence_acquisition", enabled)
        self.assertIn("design_tokens", enabled)

    def test_p1_p2_capabilities_use_explicit_default_off_routes(self) -> None:
        inventory = build_capability_inventory({
            "motion_quality": {
                "enabled": True,
                "advanced_runtimes": {"enabled": True},
            },
            "editing": {"caption_sync_closure": {"enabled": True}},
            "audio": {"sfx": {"perceptual": {"enabled": True}}},
            "editorial_intent": {"enabled": True},
            "editorial_regression": {"enabled": True},
            "delivery": {"manual_finish": {"enabled": True}},
            "extensions": {"optional_media_adapters": [{"enabled": True}]},
        })
        by_name = {row["name"]: row for row in inventory["capabilities"]}
        for name in (
            "content_format_motion_grammar", "perceptual_motion_audio",
            "caption_sync_closure", "editorial_promise_closure",
            "current_golden_runtime_evidence", "advanced_runtime_gate",
            "typed_nle_handoff", "optional_media_adapters",
        ):
            self.assertTrue(by_name[name]["enabled"], name)
        self.assertEqual(
            by_name["optional_media_adapters"]["configuration_route"],
            "extensions.optional_media_adapters",
        )

    def test_analysis_adapters_and_legacy_catalog_have_truthful_distinct_routes(self) -> None:
        inventory = build_capability_inventory({
            "analysis": {"adapters": {
                "pyscenedetect": {"enabled": True},
                "mediapipe": {"enabled": True},
                "paddleocr": {"enabled": True},
            }},
            "assets": {"use_media_catalog": True},
        })
        by_name = {row["name"]: row for row in inventory["capabilities"]}
        self.assertTrue(by_name["scene_detection"]["enabled"])
        self.assertTrue(by_name["mediapipe_tracking"]["enabled"])
        self.assertTrue(by_name["ocr"]["enabled"])
        self.assertTrue(by_name["media_catalog"]["enabled"])
        self.assertEqual(by_name["scene_detection"]["configuration_route"],
                         "analysis.adapters.pyscenedetect")
        self.assertEqual(by_name["mediapipe_tracking"]["configuration_route"],
                         "analysis.adapters.mediapipe")
        self.assertEqual(by_name["subject_tracking"]["configuration_route"],
                         "analysis.subject_tracking")

    def test_inspect_writes_inventory_and_compatibility_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "published.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source-media")
            project_file = root / "project.yaml"
            project_file.write_text(yaml.safe_dump({
                "version": 1,
                "video_id": "sample",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/published.mp4", "input_mode": "existing_edit_polish"},
            }), encoding="utf-8")

            director = Director(project_file)
            director._start("inspect")
            director.stage_inspect()

            inventory_path = director.root / "capability-inventory.json"
            toolchain_path = director.root / "toolchain-compatibility.json"
            self.assertTrue(inventory_path.is_file())
            self.assertTrue(toolchain_path.is_file())
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            self.assertEqual(inventory["schema_version"], 1)
            artifacts = director.state["stages"]["inspect"]["artifacts"]
            self.assertIn(str(inventory_path), artifacts)
            self.assertIn(str(toolchain_path), artifacts)


if __name__ == "__main__":
    unittest.main()
