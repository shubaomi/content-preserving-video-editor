from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import load_project_context  # noqa: E402
from project_config import CURRENT_PROJECT_SCHEMA_VERSION, migrate_project_config  # noqa: E402


class ProjectConfigMigrationTests(unittest.TestCase):
    def test_rejects_boolean_or_non_finite_numeric_configuration(self) -> None:
        for version in (True, 1.5, "1"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "integers"):
                migrate_project_config({"schema_version": version})
        for value in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be numeric"):
                migrate_project_config({"schema_version": 6, "audio": {
                    "normalization": {"enabled": True, "target_lufs": value},
                }})
        for value in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(parity=value), self.assertRaisesRegex(ValueError, "must be (numeric|finite)"):
                migrate_project_config({"schema_version": 6, "qa": {
                    "preview_render_parity": {"tolerances": {"position_px": value}},
                }})

    def test_new_production_features_are_disabled_for_legacy_projects(self) -> None:
        original = {"version": 1}
        migrated = migrate_project_config(original)
        self.assertFalse(migrated["audio"]["production"]["enabled"])
        self.assertFalse(migrated["audio"]["normalization"]["enabled"])
        self.assertFalse(migrated["cover"]["production"]["enabled"])
        self.assertFalse(migrated["cover"]["editorial"]["enabled"])
        self.assertFalse(migrated["visuals"]["ip_production"]["enabled"])
        self.assertFalse(migrated["assets"]["media_catalog"]["enabled"])
        self.assertFalse(migrated["analysis"]["hook_pacing"]["enabled"])
        self.assertFalse(migrated["publishing"]["copy"]["enabled"])
        self.assertEqual(migrated["editorial_intent"], {
            "enabled": False,
            "mode": "neutral_education",
            "audience": None,
            "viewer_job": None,
            "single_promise": None,
            "proof_event_ids": [],
            "cta": None,
            "tone": "neutral_educational",
            "prohibited_claims": [],
        })
        self.assertFalse(migrated["motion_quality"]["enabled"])
        self.assertFalse(migrated["motion_quality"]["advanced_runtimes"]["enabled"])
        self.assertEqual(migrated["identity"]["mode"], "generic")
        self.assertNotIn("audio", original)

    def test_v1_fixture_migrates_in_memory_without_rewriting_yaml(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "project-v1.yaml"
        original = fixture.read_bytes()
        raw = yaml.safe_load(original.decode("utf-8"))
        raw_copy = copy.deepcopy(raw)

        migrated = migrate_project_config(raw)

        self.assertEqual(raw, raw_copy)
        self.assertEqual(fixture.read_bytes(), original)
        self.assertEqual(migrated["schema_version"], CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(migrated["version"], CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(migrated["delivery"]["manual_finish"], {
            "enabled": False,
            "backend": "none",
            "returned_final": None,
            "modifications": [],
            "assets": {},
        })
        self.assertEqual(migrated["qa"]["preview_render_parity"]["tolerances"], {
            "position_px": 4.0,
            "size_px": 4.0,
            "time_seconds": 0.05,
        })
        self.assertEqual(CURRENT_PROJECT_SCHEMA_VERSION, 10)
        self.assertTrue(migrated["workflow"]["production_contract"]["enabled"])
        self.assertEqual(migrated["provider_governance"]["max_evidence_age_days"], 30)
        self.assertTrue(migrated["qa"]["visual_dynamics"]["enabled"])
        self.assertFalse(migrated["assets"]["local_semantic_corpus"]["enabled"])
        self.assertFalse(migrated["derived_content"]["clip_factory"]["enabled"])
        self.assertFalse(migrated["derived_content"]["podcast"]["enabled"])
        self.assertFalse(migrated["derived_content"]["localization"]["enabled"])
        self.assertFalse(migrated["delivery"]["openmontage_handoff"]["enabled"])
        self.assertEqual(migrated["cover"]["editorial"]["mode"], "auto")
        self.assertEqual(migrated["cover"]["editorial"]["headline_max_characters"], 26)
        self.assertEqual(migrated["workflow"]["capabilities"], {})
        self.assertFalse(migrated["analysis"]["adapters"]["pyscenedetect"]["enabled"])
        self.assertFalse(migrated["timeline"]["otio"]["enabled"])
        self.assertFalse(migrated["extensions"]["b_roll"]["enabled"])
        self.assertEqual(migrated["extensions"]["optional_media_adapters"], [])
        self.assertFalse(migrated["renderer"]["remotion"]["enabled"])
        self.assertFalse(migrated["feedback"]["metrics_import"]["enabled"])
        self.assertFalse(migrated["analysis"]["semantic_confidence"]["enabled"])
        self.assertEqual(migrated["analysis"]["protected_region_review"], {
            "enabled": False,
            "manifest": None,
        })
        self.assertFalse(migrated["render"]["cache"]["event_level"]["enabled"])
        self.assertFalse(migrated["review"]["interactive"]["enabled"])
        self.assertFalse(migrated["cover"]["reference_pack"]["enabled"])
        self.assertFalse(migrated["preferences"]["learning"]["enabled"])
        self.assertFalse(migrated["feedback"]["learning_loop"]["enabled"])
        self.assertFalse(migrated["delivery"]["audit_bundle"]["enabled"])
        self.assertFalse(migrated["delivery"]["release_pack"]["enabled"])
        self.assertEqual(migrated["audio"]["sfx"]["maximum_family_ratio"], 0.5)
        self.assertEqual(migrated["audio"]["sfx"]["perceptual"], {
            "enabled": False,
            "minimum_audible_ratio": 0.35,
            "maximum_audible_ratio": 0.65,
            "maximum_onset_error_ms": 80.0,
        })
        self.assertEqual(migrated["editing"]["caption_delivery"], "auto")
        self.assertEqual(migrated["delivery"]["required_assets"], {
            "captions": {
                "stage": "video_use_timeline",
                "applicability": "required",
                "required_readiness": "ready",
            },
            "audio": {
                "stage": "audio",
                "applicability": "optional",
                "required_readiness": "asset_ready",
            },
            "cover": {
                "stage": "cover",
                "applicability": "optional",
                "required_readiness": "asset_ready",
            },
            "identity": {
                "stage": "production_contract",
                "applicability": "required",
                "required_readiness": "ready",
            },
            "universal_video": {
                "stage": "final_compose",
                "applicability": "required",
                "required_readiness": "ready",
            },
        })

    def test_invalid_caption_delivery_policy_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "editing.caption_delivery"):
            migrate_project_config({
                "schema_version": 9,
                "version": 9,
                "editing": {"caption_delivery": "sometimes"},
            })

    def test_invalid_sfx_family_dominance_limit_is_rejected(self) -> None:
        for value in (True, 0, 1.1, float("nan")):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "audio.sfx.maximum_family_ratio"
            ):
                migrate_project_config({
                    "schema_version": 9,
                    "version": 9,
                    "audio": {"sfx": {"maximum_family_ratio": value}},
                })

    def test_legacy_project_context_runs_with_migrated_defaults_without_yaml_mutation(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "project-v1.yaml"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_file = root / "project.yaml"
            text = fixture.read_text(encoding="utf-8").replace("root: .", f"root: {root}")
            project_file.write_text(text, encoding="utf-8")
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"video")
            before = project_file.read_bytes()

            project, context = load_project_context(project_file)

            self.assertEqual(project["delivery"]["manual_finish"]["backend"], "none")
            self.assertEqual(context.source_video, source)
            self.assertEqual(project_file.read_bytes(), before)

    def test_invalid_manual_finish_backend_is_rejected(self) -> None:
        project = {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "version": CURRENT_PROJECT_SCHEMA_VERSION,
            "delivery": {"manual_finish": {"enabled": True, "backend": "imaginary_nle"}},
        }
        with self.assertRaisesRegex(ValueError, "manual_finish.backend"):
            migrate_project_config(project)

    def test_all_v1_through_v9_configs_migrate_to_v10_without_mutation(self) -> None:
        for version in range(1, 10):
            original = {
                "schema_version": version,
                "version": version,
                "video_id": f"legacy-{version}",
            }
            before = copy.deepcopy(original)
            with self.subTest(version=version):
                migrated = migrate_project_config(original)
                self.assertEqual(original, before)
                self.assertEqual(migrated["schema_version"], 10)
                self.assertEqual(migrated["version"], 10)
                self.assertEqual(migrated["identity"]["mode"], "generic")
                self.assertFalse(migrated["motion_quality"]["enabled"])

    def test_v7_migrates_to_v10_without_mutating_the_source_mapping(self) -> None:
        original = {
            "schema_version": 7,
            "version": 7,
            "assets": {"media_catalog": {"enabled": True}},
        }
        before = copy.deepcopy(original)

        migrated = migrate_project_config(original)

        self.assertEqual(original, before)
        self.assertEqual(migrated["schema_version"], 10)
        self.assertTrue(migrated["assets"]["media_catalog"]["enabled"])
        self.assertFalse(migrated["assets"]["local_semantic_corpus"]["enabled"])
        self.assertEqual(migrated["delivery"]["openmontage_handoff"]["backend"], "openmontage")

    def test_v8_migrates_to_v10_without_rewriting_user_configuration(self) -> None:
        original = {"schema_version": 8, "version": 8, "render": {"cache": {"enabled": True}}}
        before = copy.deepcopy(original)
        migrated = migrate_project_config(original)
        self.assertEqual(original, before)
        self.assertEqual(migrated["schema_version"], 10)
        self.assertTrue(migrated["render"]["cache"]["enabled"])
        self.assertFalse(migrated["render"]["cache"]["event_level"]["enabled"])

    def test_manual_finish_and_openmontage_handoff_cannot_both_be_enabled(self) -> None:
        project = {"version": 8, "schema_version": 8, "delivery": {
            "manual_finish": {"enabled": True, "backend": "opencut"},
            "openmontage_handoff": {"enabled": True, "backend": "openmontage"},
        }}

        with self.assertRaisesRegex(ValueError, "cannot both be enabled"):
            migrate_project_config(project)

    def test_enabled_release_pack_cannot_disable_required_human_gates(self) -> None:
        project = {
            "schema_version": 9,
            "version": 9,
            "delivery": {
                "release_pack": {
                    "enabled": True,
                    "require_privacy_audit": False,
                },
            },
        }
        with self.assertRaisesRegex(ValueError, "release pack requires privacy"):
            migrate_project_config(project)

    def test_provider_evidence_age_must_be_a_positive_integer(self) -> None:
        project = {
            "version": 8,
            "schema_version": 8,
            "provider_governance": {"max_evidence_age_days": 0},
        }

        with self.assertRaisesRegex(ValueError, "max_evidence_age_days"):
            migrate_project_config(project)

    def test_v10_preserves_explicit_identity_and_motion_quality_configuration(self) -> None:
        project = {
            "schema_version": 10,
            "version": 10,
            "identity": {"mode": "third_party"},
            "motion_quality": {"enabled": True, "advanced_runtimes": {"enabled": False}},
        }

        migrated = migrate_project_config(project)

        self.assertEqual(migrated["identity"]["mode"], "third_party")
        self.assertTrue(migrated["motion_quality"]["enabled"])
        self.assertFalse(migrated["motion_quality"]["advanced_runtimes"]["enabled"])

    def test_invalid_identity_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity.mode"):
            migrate_project_config({
                "schema_version": 10,
                "version": 10,
                "identity": {"mode": "workspace_owner"},
            })

    def test_optional_source_content_type_is_validated_without_forcing_a_default(self) -> None:
        migrated = migrate_project_config({
            "schema_version": 10,
            "version": 10,
            "source": {"content_type": "talking_head"},
        })
        self.assertEqual(migrated["source"]["content_type"], "talking_head")

        with self.assertRaisesRegex(ValueError, "source.content_type"):
            migrate_project_config({
                "schema_version": 10,
                "version": 10,
                "source": {"content_type": "marketing_magic"},
            })

    def test_protected_region_review_requires_manifest_when_enabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "protected_region_review.manifest"):
            migrate_project_config({
                "schema_version": 10,
                "version": 10,
                "analysis": {"protected_region_review": {"enabled": True}},
            })

        migrated = migrate_project_config({
            "schema_version": 10,
            "version": 10,
            "analysis": {"protected_region_review": {
                "enabled": True,
                "manifest": "edit/protected-region-review/review.json",
            }},
        })
        self.assertTrue(migrated["analysis"]["protected_region_review"]["enabled"])

    def test_required_asset_contract_rejects_invalid_or_unsafe_readiness(self) -> None:
        invalid_rows = (
            {"stage": "audio", "applicability": "required", "required_readiness": "contract_ready"},
            {"stage": "audio", "applicability": "required", "required_readiness": "ready"},
            {"stage": "audio", "applicability": "sometimes", "required_readiness": "asset_ready"},
            {"stage": "", "applicability": "required", "required_readiness": "asset_ready"},
        )
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaisesRegex(
                ValueError, "delivery.required_assets.audio"
            ):
                migrate_project_config({
                    "schema_version": 10,
                    "version": 10,
                    "delivery": {"required_assets": {"audio": row}},
                })

    def test_explicit_caption_none_migrates_to_evidenced_not_applicable_policy(self) -> None:
        migrated = migrate_project_config({
            "schema_version": 9,
            "version": 9,
            "editing": {"caption_delivery": "none"},
        })
        self.assertEqual(migrated["delivery"]["required_assets"]["captions"], {
            "stage": "video_use_timeline",
            "applicability": "not_applicable",
            "required_readiness": "not_applicable",
            "reason": "editing.caption_delivery is explicitly none",
        })

    def test_mandatory_asset_policies_cannot_be_weakened_or_rebound(self) -> None:
        unsafe = (
            ("captions", {"stage": "video_use_timeline", "applicability": "optional",
                           "required_readiness": "ready"}),
            ("captions", {"stage": "audio", "applicability": "required",
                           "required_readiness": "ready"}),
            ("identity", {"stage": "production_contract", "applicability": "optional",
                           "required_readiness": "ready"}),
            ("universal_video", {"stage": "final_compose", "applicability": "required",
                                  "required_readiness": "asset_ready"}),
        )
        for asset, rule in unsafe:
            with self.subTest(asset=asset, rule=rule), self.assertRaisesRegex(
                ValueError, f"delivery.required_assets.{asset}"
            ):
                migrate_project_config({
                    "schema_version": 10,
                    "version": 10,
                    "delivery": {"required_assets": {asset: rule}},
                })


if __name__ == "__main__":
    unittest.main()
