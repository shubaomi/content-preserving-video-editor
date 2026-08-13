from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portrait_brand_contracts import validate_portrait_contract_schema  # noqa: E402
from portrait_sonic import (  # noqa: E402
    DEFAULT_PORTRAIT_SONIC_REGISTRY,
    PortraitSonicError,
    compile_portrait_sonic_plan,
    materialize_portrait_sonic_library,
    portrait_sonic_plan_artifacts,
    project_portrait_sonic_plan,
    _relative_asset_copy,
    authorized_portrait_sfx_root,
    validate_portrait_sonic_library,
    validate_portrait_sonic_projection,
    validate_portrait_sonic_registry,
)


class PortraitSonicTests(unittest.TestCase):
    def _profile(self, root: Path) -> Path:
        source = ROOT / "references" / "portrait-brand-profiles" / "hongrun-portrait-brand-v2.0.0.json"
        target = root / "profile.json"
        target.write_bytes(source.read_bytes())
        return target

    def _motion_bundle(self, root: Path, semantic_brief: dict | None = None) -> Path:
        semantic_brief = semantic_brief or self._semantic_brief()
        semantic_hash = hashlib.sha256(json.dumps(
            semantic_brief, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        path = root / "portrait-motion-contracts.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "contracts": [
                {
                    "semantic_event_id": "word-event",
                    "primary_recipe_id": "PBM-01",
                    "energy_tier": "micro",
                    "output_window": {"start_seconds": 1.0, "end_seconds": 2.5},
                    "input_hashes": {"semantic_brief": semantic_hash},
                },
                {
                    "semantic_event_id": "gesture-event",
                    "primary_recipe_id": "PBM-03",
                    "energy_tier": "meso",
                    "output_window": {"start_seconds": 4.0, "end_seconds": 6.0},
                    "input_hashes": {"semantic_brief": semantic_hash},
                    "gesture_binding": {
                        "evidence_id": "gesture-1",
                        "kind": "gesture_track",
                        "output_apex_seconds": 4.7,
                    },
                },
                {
                    "semantic_event_id": "chapter-event",
                    "primary_recipe_id": "PBM-07",
                    "energy_tier": "macro",
                    "output_window": {"start_seconds": 8.0, "end_seconds": 10.0},
                    "input_hashes": {"semantic_brief": semantic_hash},
                    "chapter_boundary_binding": {
                        "evidence_id": "chapter-1",
                        "kind": "chapter_boundary",
                        "window": {"start_seconds": 8.0, "end_seconds": 8.2},
                    },
                },
            ],
        }, ensure_ascii=False), encoding="utf-8")
        return path

    def _semantic_brief(self) -> dict:
        return {
            "events": [
                {
                    "id": "word-event", "semantic_role": "mark",
                    "output_start": 1.0, "output_end": 2.5,
                    "audio_decision": {"type": "cue"},
                },
                {
                    "id": "gesture-event", "semantic_role": "explain",
                    "output_start": 4.0, "output_end": 6.0,
                    "audio_decision": {"type": "cue"},
                },
                {
                    "id": "chapter-event", "semantic_role": "transition",
                    "output_start": 8.0, "output_end": 10.0,
                    "audio_decision": {"type": "intentionally_silent", "reason": "Speech density is already high at this chapter turn."},
                },
            ],
        }

    def test_registry_defines_all_five_families_and_two_original_variants_each(self) -> None:
        registry = json.loads(DEFAULT_PORTRAIT_SONIC_REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(validate_portrait_sonic_registry(registry), [])
        self.assertEqual(
            [row["family_id"] for row in registry["families"]],
            [f"PBM-S0{index}" for index in range(1, 6)],
        )
        self.assertTrue(all(len(row["variants"]) >= 2 for row in registry["families"]))
        self.assertTrue(all(row["production_ready"] is False for row in registry["families"]))

    def test_materialized_library_is_pcm_hash_and_rights_bound_without_claiming_brand_approval(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            library = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(validate_portrait_sonic_library(library, manifest_path), [])
            self.assertEqual(library["status"], "asset_ready_for_style_reel")
            self.assertFalse(library["brand_taste_approved"])
            self.assertEqual(len(library["families"]), 5)
            for family in library["families"]:
                self.assertEqual(len(family["variants"]), 2)
                self.assertEqual(len({row["pcm_fingerprint"] for row in family["variants"]}), 2)

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_library_materializer_rejects_asset_junction_without_external_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            output = Path(folder) / "library"
            output.mkdir()
            outside = Path(outside_folder).resolve()
            junction = output / "assets"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            with self.assertRaisesRegex(PortraitSonicError, "redirected"):
                materialize_portrait_sonic_library(DEFAULT_PORTRAIT_SONIC_REGISTRY, output)
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_library_materializer_rejects_output_root_junction(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            junction = Path(folder) / "library"
            outside = Path(outside_folder).resolve()
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            with self.assertRaisesRegex(PortraitSonicError, "root is redirected"):
                materialize_portrait_sonic_library(DEFAULT_PORTRAIT_SONIC_REGISTRY, junction)
            self.assertEqual(list(outside.iterdir()), [])

    def test_library_rejects_generator_provenance_not_bound_to_current_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            library = json.loads(manifest_path.read_text(encoding="utf-8"))
            forged_generator = root / "not-generator.py"
            forged_generator.write_text("# unrelated\n", encoding="utf-8")
            forged_ref = {
                "path": str(forged_generator.resolve()),
                "sha256": hashlib.sha256(forged_generator.read_bytes()).hexdigest(),
            }
            library["generator"] = forged_ref
            for family in library["families"]:
                for variant in family["variants"]:
                    rights_path = Path(variant["rights"]["path"])
                    rights = json.loads(rights_path.read_text(encoding="utf-8"))
                    rights["generator"] = forged_ref
                    rights_path.write_text(json.dumps(rights), encoding="utf-8")
                    variant["rights"]["sha256"] = hashlib.sha256(
                        rights_path.read_bytes()
                    ).hexdigest()
            manifest_path.write_text(json.dumps(library), encoding="utf-8")

            errors = validate_portrait_sonic_library(library, manifest_path)

            self.assertTrue(any("current compiler" in row for row in errors), errors)

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_asset_copy_rejects_junction_that_escapes_project(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            root = Path(folder)
            outside = Path(outside_folder).resolve()
            source = root / "source.wav"
            source.write_bytes(b"authorized-audio")
            sfx_root = root / "assets" / "sfx"
            sfx_root.mkdir(parents=True)
            junction = sfx_root / "portrait-brand-v2"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            ref = {
                "path": str(source.resolve()),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }

            with self.assertRaisesRegex(PortraitSonicError, "escapes authorized SFX root"):
                _relative_asset_copy(
                    ref, base_dir=root, variant_id="escape", suffix="asset",
                )
            self.assertFalse((outside / "escape.wav").exists())

            with self.assertRaisesRegex(PortraitSonicError, "escapes authorized SFX root"):
                _relative_asset_copy(
                    ref, base_dir=root, variant_id="escape", suffix="rights",
                )
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_top_level_sfx_junction_is_never_an_authorized_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            root = Path(folder)
            outside = Path(outside_folder).resolve()
            assets = root / "assets"
            assets.mkdir()
            junction = assets / "sfx"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            with self.assertRaisesRegex(PortraitSonicError, "redirected"):
                authorized_portrait_sfx_root(root)

    def test_asset_copy_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.wav"
            source.write_bytes(b"authorized-audio")
            target_dir = root / "assets" / "sfx" / "portrait-brand-v2"
            target_dir.mkdir(parents=True)
            target = target_dir / "stable.wav"
            target.write_bytes(b"existing-good-bytes")
            ref = {
                "path": str(source.resolve()),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }

            def partial_copy(_source: Path, temporary: Path) -> None:
                Path(temporary).write_bytes(b"partial")
                raise OSError("simulated interrupted copy")

            with mock.patch("portrait_sonic.shutil.copyfile", side_effect=partial_copy):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    _relative_asset_copy(
                        ref, base_dir=root, variant_id="stable", suffix="asset",
                    )

            self.assertEqual(target.read_bytes(), b"existing-good-bytes")
            self.assertEqual(list(target_dir.glob(".stable.wav.*.tmp")), [])

    def test_compiler_covers_every_event_and_binds_word_gesture_and_silent_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = self._profile(root)
            motion = self._motion_bundle(root)
            library = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            result = compile_portrait_sonic_plan(
                project_id="portrait-fixture",
                profile_path=profile,
                motion_contracts_path=motion,
                semantic_brief=self._semantic_brief(),
                library_manifest_path=library,
            )
            plan = result["plan"]
            self.assertEqual(validate_portrait_contract_schema("portrait-sonic-plan", plan), [])
            self.assertEqual([row["event_id"] for row in plan["decisions"]], [
                "word-event", "gesture-event", "chapter-event",
            ])
            self.assertEqual(plan["decisions"][0]["motif_family_id"], "PBM-S01")
            self.assertEqual(plan["decisions"][0]["landing_seconds"], 1.0)
            self.assertEqual(plan["decisions"][1]["motif_family_id"], "PBM-S02")
            self.assertEqual(plan["decisions"][1]["landing_seconds"], 4.7)
            self.assertEqual(plan["decisions"][2]["decision"], "intentionally_silent")
            self.assertEqual(result["report"]["decision_coverage"], 1.0)
            artifacts = portrait_sonic_plan_artifacts(plan)
            self.assertIn(library.resolve(), artifacts)
            nested_rights = next(path for path in artifacts if path.name.endswith("rights.json"))
            nested_rights.unlink()
            with self.assertRaisesRegex(PortraitSonicError, "library"):
                portrait_sonic_plan_artifacts(plan)

    def test_missing_or_unusable_library_falls_back_to_event_specific_silence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = self._profile(root)
            motion = self._motion_bundle(root)
            library_path = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            library = json.loads(library_path.read_text(encoding="utf-8"))
            library["families"][0]["variants"] = []
            library_path.write_text(json.dumps(library), encoding="utf-8")
            result = compile_portrait_sonic_plan(
                project_id="portrait-fixture", profile_path=profile,
                motion_contracts_path=motion, semantic_brief=self._semantic_brief(),
                library_manifest_path=library_path,
                allow_unavailable_library=True,
            )
            self.assertEqual(result["plan"]["decisions"][0]["decision"], "intentionally_silent")
            self.assertIn("authorized PBM-S01 variants are unavailable", result["plan"]["decisions"][0]["reason"])
            self.assertEqual(result["report"]["status"], "visual_only_audio_unavailable")

    def test_registry_rejects_false_readiness_identical_variants_and_unlicensed_assets(self) -> None:
        registry = json.loads(DEFAULT_PORTRAIT_SONIC_REGISTRY.read_text(encoding="utf-8"))
        one_variant = copy.deepcopy(registry)
        one_variant["families"][0]["production_ready"] = True
        one_variant["families"][0]["variants"] = one_variant["families"][0]["variants"][:1]
        self.assertTrue(any("two variants" in row for row in validate_portrait_sonic_registry(one_variant)))
        falsely_promoted = copy.deepcopy(registry)
        falsely_promoted["families"][0]["production_ready"] = True
        self.assertTrue(any(
            "non-production" in row
            for row in validate_portrait_sonic_registry(falsely_promoted)
        ))
        unlicensed = copy.deepcopy(registry)
        unlicensed["families"][0]["variants"][0]["rights_basis"] = ""
        self.assertTrue(any("rights_basis" in row for row in validate_portrait_sonic_registry(unlicensed)))

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            library = json.loads(manifest_path.read_text(encoding="utf-8"))
            duplicate = copy.deepcopy(library["families"][0]["variants"][0])
            duplicate["variant_id"] = library["families"][0]["variants"][1]["variant_id"]
            library["families"][0]["variants"][1] = duplicate
            manifest_path.write_text(json.dumps(library), encoding="utf-8")
            self.assertTrue(any("perceptually distinct" in row for row in validate_portrait_sonic_library(library, manifest_path)))

    def test_library_rejects_self_signed_asset_that_differs_from_frozen_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            library = json.loads(manifest_path.read_text(encoding="utf-8"))
            target = library["families"][0]["variants"][0]
            replacement = library["families"][4]["variants"][1]
            target_asset = Path(target["asset"]["path"])
            target_asset.write_bytes(Path(replacement["asset"]["path"]).read_bytes())
            from audio_production import perceptual_motif_fingerprint
            from director_contracts import sha256_file
            target["asset"]["sha256"] = sha256_file(target_asset)
            target["pcm_fingerprint"] = perceptual_motif_fingerprint(target_asset)["sha256"]
            target["duration_seconds"] = perceptual_motif_fingerprint(target_asset)["duration_seconds"]
            rights_path = Path(target["rights"]["path"])
            rights = json.loads(rights_path.read_text(encoding="utf-8"))
            rights["asset"] = dict(target["asset"])
            rights_path.write_text(json.dumps(rights), encoding="utf-8")
            target["rights"]["sha256"] = sha256_file(rights_path)
            manifest_path.write_text(json.dumps(library), encoding="utf-8")

            errors = validate_portrait_sonic_library(library, manifest_path)
            self.assertTrue(any("deterministic synthesis" in row for row in errors), errors)

    def test_projection_reuses_existing_audio_plan_and_enforces_landing_tolerances(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = self._profile(root)
            motion = self._motion_bundle(root)
            library = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            result = compile_portrait_sonic_plan(
                project_id="portrait-fixture", profile_path=profile,
                motion_contracts_path=motion, semantic_brief=self._semantic_brief(),
                library_manifest_path=library,
            )
            audio_plan = {
                "schema_version": 3,
                "speech_track": {"source": "source.wav", "dominant": True, "immutable": True},
                "motion_sfx": {"event_decisions": [], "mix_audibility_check": {"status": "not_applicable"}},
                "background_music": {"mode": "disabled", "enabled": False, "reason": "fixture"},
                "provenance": {"source_audio": "source.wav"},
            }
            projected = project_portrait_sonic_plan(
                result["plan"], audio_plan, base_dir=root,
                motion_contracts_path=motion,
                storyboard={"events": [
                    {"id": "word-event", "semantic_event_id": "word-event"},
                    {"id": "gesture-event", "semantic_event_id": "gesture-event"},
                    {"id": "chapter-event", "semantic_event_id": "chapter-event"},
                ]},
            )
            decisions = projected["motion_sfx"]["event_decisions"]
            self.assertEqual(decisions[0]["family"], "PBM-S01")
            self.assertEqual(decisions[0]["portrait_landing_tolerance_ms"], 80.0)
            self.assertEqual(decisions[1]["portrait_landing_tolerance_ms"], 120.0)
            self.assertEqual(decisions[2]["decision"], "intentionally_silent")
            self.assertEqual(projected["provenance"]["portrait_sonic_plan"]["decision_coverage"], 1.0)
            storyboard = {"events": [
                {"id": "word-event", "semantic_event_id": "word-event"},
                {"id": "gesture-event", "semantic_event_id": "gesture-event"},
                {"id": "chapter-event", "semantic_event_id": "chapter-event"},
            ]}
            self.assertEqual(validate_portrait_sonic_projection(
                result["plan"], projected, base_dir=root,
                motion_contracts_path=motion, storyboard=storyboard,
            ), [])
            adjusted = copy.deepcopy(projected)
            adjusted_row = adjusted["motion_sfx"]["event_decisions"][0]
            initial_volume = adjusted_row["volume"]
            initial_post_gain = adjusted_row["post_gain_mean_dbfs"]
            adjusted_row["volume"] = round(initial_volume * 0.8, 3)
            adjusted_row["post_gain_mean_dbfs"] = round(
                initial_post_gain
                + 20.0 * __import__("math").log10(adjusted_row["volume"] / initial_volume),
                1,
            )
            self.assertEqual(validate_portrait_sonic_projection(
                result["plan"], adjusted, base_dir=root,
                motion_contracts_path=motion, storyboard=storyboard,
            ), [])
            stale = copy.deepcopy(projected)
            stale["motion_sfx"]["event_decisions"][0]["family"] = "PBM-S05"
            self.assertTrue(any("family is stale" in row for row in validate_portrait_sonic_projection(
                result["plan"], stale, base_dir=root,
                motion_contracts_path=motion, storyboard=storyboard,
            )))

            for field, value in (
                ("volume", 0.99),
                ("duration_seconds", 2.19),
                ("post_gain_mean_dbfs", -1.0),
                ("reason", "forged"),
                ("asset", "assets/sfx/portrait-brand-v2/other.wav"),
            ):
                stale = copy.deepcopy(projected)
                stale["motion_sfx"]["event_decisions"][0][field] = value
                with self.subTest(field=field):
                    self.assertTrue(validate_portrait_sonic_projection(
                        result["plan"], stale, base_dir=root,
                        motion_contracts_path=motion, storyboard=storyboard,
                    ))

            duplicate_storyboard = {"events": [*storyboard["events"], {
                "id": "duplicate-renderer", "semantic_event_id": "word-event",
            }]}
            self.assertTrue(any("storyboard" in row for row in validate_portrait_sonic_projection(
                result["plan"], projected, base_dir=root,
                motion_contracts_path=motion, storyboard=duplicate_storyboard,
            )))

            substituted = copy.deepcopy(result["plan"])
            first = substituted["decisions"][0]
            replacement = json.loads(library.read_text(encoding="utf-8"))["families"][4]["variants"][1]
            first.update({
                "asset": replacement["asset"],
                "rights": replacement["rights"],
                "pcm_fingerprint": replacement["pcm_fingerprint"],
                "duration_seconds": replacement["duration_seconds"],
            })
            forged_root = root / "forged"
            forged_projection = project_portrait_sonic_plan(
                substituted, audio_plan, base_dir=forged_root,
                motion_contracts_path=motion, storyboard=storyboard,
            )
            self.assertTrue(any(
                "sonic library" in row or "library variant" in row
                for row in validate_portrait_sonic_projection(
                    substituted, forged_projection, base_dir=forged_root,
                    motion_contracts_path=motion, storyboard=storyboard,
                )
            ))

            bad = copy.deepcopy(result["plan"])
            bad["decisions"][1]["landing_seconds"] = 7.0
            with self.assertRaisesRegex(PortraitSonicError, "gesture landing"):
                project_portrait_sonic_plan(
                    bad, audio_plan, base_dir=root,
                    motion_contracts_path=motion,
                )

    def test_word_gesture_and_chapter_landing_windows_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = self._profile(root)
            motion = self._motion_bundle(root)
            library = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            semantic = self._semantic_brief()
            semantic["events"][2]["audio_decision"] = {"type": "cue"}
            motion = self._motion_bundle(root, semantic)
            result = compile_portrait_sonic_plan(
                project_id="portrait-fixture", profile_path=profile,
                motion_contracts_path=motion, semantic_brief=semantic,
                library_manifest_path=library,
            )
            base_audio_plan = {
                "schema_version": 3,
                "speech_track": {"source": "source.wav", "dominant": True, "immutable": True},
                "motion_sfx": {"event_decisions": [], "mix_audibility_check": {"status": "not_applicable"}},
                "background_music": {"mode": "disabled", "enabled": False, "reason": "fixture"},
                "provenance": {"source_audio": "source.wav"},
            }
            projected = project_portrait_sonic_plan(
                result["plan"], base_audio_plan, base_dir=root,
                motion_contracts_path=motion,
            )
            self.assertEqual(
                [row["portrait_landing_tolerance_ms"] for row in projected["motion_sfx"]["event_decisions"]],
                [80.0, 120.0, 180.0],
            )

            for index, delta, expected_error in (
                (0, 0.081, "word landing"),
                (1, 0.121, "gesture landing"),
                (2, -0.181, "chapter landing"),
                (2, 0.001, "chapter landing"),
            ):
                stale = copy.deepcopy(result["plan"])
                stale["decisions"][index]["landing_seconds"] += delta
                with self.subTest(index=index, delta=delta):
                    with self.assertRaisesRegex(PortraitSonicError, expected_error):
                        project_portrait_sonic_plan(
                            stale, base_audio_plan, base_dir=root,
                            motion_contracts_path=motion,
                        )

    def test_compiler_rejects_motion_contract_window_or_semantic_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            semantic = self._semantic_brief()
            profile = self._profile(root)
            library = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            for mutation, expected in (("window", "output window"), ("hash", "authority hash")):
                motion = self._motion_bundle(root, semantic)
                bundle = json.loads(motion.read_text(encoding="utf-8"))
                if mutation == "window":
                    bundle["contracts"][0]["output_window"]["start_seconds"] = 99.0
                else:
                    bundle["contracts"][0]["input_hashes"]["semantic_brief"] = "0" * 64
                motion.write_text(json.dumps(bundle), encoding="utf-8")
                with self.subTest(mutation=mutation):
                    with self.assertRaisesRegex(PortraitSonicError, expected):
                        compile_portrait_sonic_plan(
                            project_id="portrait-fixture", profile_path=profile,
                            motion_contracts_path=motion, semantic_brief=semantic,
                            library_manifest_path=library,
                        )

            missing_render = copy.deepcopy(semantic)
            missing_render["events"].append({
                "id": "unbound-render", "decision": "render",
                "semantic_role": "mark", "output_start": 11.0,
                "output_end": 12.0, "audio_decision": {"type": "cue"},
            })
            motion = self._motion_bundle(root, missing_render)
            with self.assertRaisesRegex(PortraitSonicError, "event set/order"):
                compile_portrait_sonic_plan(
                    project_id="portrait-fixture", profile_path=profile,
                    motion_contracts_path=motion, semantic_brief=missing_render,
                    library_manifest_path=library,
                )

    def test_library_malformed_registry_reference_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = materialize_portrait_sonic_library(
                DEFAULT_PORTRAIT_SONIC_REGISTRY, root / "library",
            )
            library = json.loads(manifest_path.read_text(encoding="utf-8"))
            for malformed in ("bad", 1, []):
                candidate = copy.deepcopy(library)
                candidate["registry"] = malformed
                with self.subTest(malformed=malformed):
                    self.assertTrue(validate_portrait_sonic_library(candidate, manifest_path))


if __name__ == "__main__":
    unittest.main()
