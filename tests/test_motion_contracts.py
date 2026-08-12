from __future__ import annotations

from copy import deepcopy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from motion_contracts import (  # noqa: E402
    CONTRACT_SCHEMA_NAMES,
    DEFAULT_RECIPE_REGISTRY,
    load_recipe_registry,
    validate_all_schema_definitions,
    validate_motion_design_contract,
    validate_recipe_registry,
    validate_storyboard_motion_binding,
)
from motion_quality_engine import choreography_fingerprint  # noqa: E402


class MotionContractTests(unittest.TestCase):
    def test_all_seven_frozen_contract_schemas_are_valid_draft_2020_12(self) -> None:
        self.assertEqual(len(CONTRACT_SCHEMA_NAMES), 7)
        self.assertEqual(validate_all_schema_definitions(), [])

    def test_registry_contains_exactly_the_sixteen_approved_recipes(self) -> None:
        registry = load_recipe_registry(DEFAULT_RECIPE_REGISTRY)
        self.assertEqual(validate_recipe_registry(registry), [])
        self.assertEqual(
            [row["recipe_id"] for row in registry["recipes"]],
            [f"MQE-{index:02d}" for index in range(1, 17)],
        )
        serialized = json.dumps(registry, ensure_ascii=False).lower()
        for forbidden in (
            "events_per_minute", "minimum_event_count", "keyword_score",
            "random_family", "random_template", "random_sfx",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_recipe_schema_rejects_incomplete_phase_contract(self) -> None:
        registry = load_recipe_registry(DEFAULT_RECIPE_REGISTRY)
        broken = deepcopy(registry)
        broken["recipes"][0]["phases"] = broken["recipes"][0]["phases"][:3]
        errors = validate_recipe_registry(broken)
        self.assertTrue(any("phases" in error for error in errors), errors)

    def test_cross_contract_validation_rejects_wrong_selection_and_stale_hash(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"media")
            artifacts = {}
            for name in ("semantic_brief", "production_contract", "evidence_bundle", "brand_playbook"):
                path = root / f"{name}.json"
                path.write_text(json.dumps({"name": name}), encoding="utf-8")
                artifacts[name] = path
            contract = {
                "schema_version": "1.0.0",
                "contract_id": "motion-test",
                "project_id": "project-test",
                "created_at": "2026-08-11T00:00:00Z",
                "producer": "content-preserving-video-editor",
                "source_media": {
                    "path": str(source.resolve()), "sha256": sha256_file(source),
                    "duration_seconds": 12.0, "width": 1920, "height": 1080,
                    "orientation": "landscape", "source_type": "screen_recording",
                },
                "identity_mode": "generic",
                "input_hashes": {
                    "semantic_brief_sha256": sha256_file(artifacts["semantic_brief"]),
                    "production_contract_sha256": sha256_file(artifacts["production_contract"]),
                    "evidence_bundle_sha256": sha256_file(artifacts["evidence_bundle"]),
                    "brand_playbook_sha256": "0" * 64,
                },
                "opportunities": [{
                    "semantic_event_id": "event-1", "decision": "render",
                    "rationale": "explain the approved relation",
                    "source_window": {"start_seconds": 1.0, "end_seconds": 4.0},
                    "output_window": {"start_seconds": 1.0, "end_seconds": 4.0},
                    "transcript_word_ids": ["word-1"],
                    "approved_visible_copy": ["核心关系"],
                    "viewer_takeaway": "understand the relation",
                    "semantic_role": "relate", "recipe_id": "MQE-06",
                    "audio_decision_id": "audio-event-1", "evidence_refs": ["frame-1"],
                }],
                "selected_event_ids": [],
                "constraints": {
                    "max_concurrent_primary_events": 1, "max_attention_units": 2,
                    "caption_safe_zone": {"x": 0.0, "y": 0.8, "width": 1.0, "height": 0.2},
                    "platform_safe_zone": {"x": 0.05, "y": 0.05, "width": 0.9, "height": 0.9},
                },
            }
            errors = validate_motion_design_contract(
                contract,
                artifact_paths=artifacts,
                recipe_registry=load_recipe_registry(DEFAULT_RECIPE_REGISTRY),
            )
            self.assertTrue(any("selected_event_ids" in error for error in errors), errors)
            self.assertTrue(any("brand_playbook" in error for error in errors), errors)

    def test_third_party_identity_rejects_personal_ip_recipe(self) -> None:
        registry = load_recipe_registry(DEFAULT_RECIPE_REGISTRY)
        recipe = next(row for row in registry["recipes"] if row["recipe_id"] == "MQE-14")
        self.assertTrue(any("identity.self" == rule for rule in recipe["preconditions"]))
        self.assertTrue(any("identity.third_party" == rule for rule in recipe["contraindications"]))

    def test_storyboard_cannot_reselect_recipe_or_choreography(self) -> None:
        registry = load_recipe_registry(DEFAULT_RECIPE_REGISTRY)
        recipe = next(row for row in registry["recipes"] if row["recipe_id"] == "MQE-01")
        contract = {
            "contract_id": "motion-bound",
            "opportunities": [{
                "semantic_event_id": "event-1", "decision": "render",
                "recipe_id": "MQE-01", "target_binding_ids": [],
            }],
        }
        storyboard = {"events": [{
            "semantic_event_id": "event-1", "motion_design_contract_id": "motion-bound",
            "recipe_id": "MQE-02", "target_binding_ids": [],
            "choreography_fingerprint_sha256": choreography_fingerprint(recipe),
        }]}
        errors = validate_storyboard_motion_binding(storyboard, contract, registry)
        self.assertTrue(any("recipe_id" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
