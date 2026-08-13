from __future__ import annotations

from copy import deepcopy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portrait_motion_recipes import (  # noqa: E402
    DEFAULT_PORTRAIT_RECIPE_REGISTRY,
    PortraitRecipeError,
    compile_portrait_motion_contracts,
    load_portrait_recipe_registry,
    materialize_portrait_component_assets,
    build_portrait_renderer_payload,
    portrait_choreography_by_event,
    recipe_fingerprint,
    validate_storyboard_portrait_binding,
    validate_portrait_recipe_registry,
)
from portrait_brand_contracts import validate_portrait_contract_schema  # noqa: E402
from director_contracts import sha256_file  # noqa: E402
from brand_motion_playbook import compile_playbook  # noqa: E402


def _hash(value: object) -> str:
    return sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


class PortraitMotionRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile.json"
        self.energy = self.root / "energy.json"
        self.profile.write_text(
            (ROOT / "references" / "portrait-brand-profiles" / "hongrun-portrait-brand-v2.0.0.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.asset = self.root / "semantic-asset.png"
        Image.new("RGB", (64, 64), (34, 211, 238)).save(self.asset)
        self.events = [
            self._event("e1", "mark", "micro", ["重点"]),
            self._event("e2", "explain", "meso", ["核心逻辑"], subject=True),
            self._event("e3", "mark", "micro", ["三步"], gesture=True),
            self._event("e4", "relate", "meso", ["过去", "现在"]),
            self._event("e5", "transition", "macro", ["下一章"], subject=True, camera=True),
            self._event("e6", "prove", "meso", ["真实证据"], asset=True),
            self._event("e7", "transition", "macro", ["转折"], boundary=True),
            self._event("e8", "resolve", "meso", ["继续向前"]),
        ]
        for event in self.events:
            request = event.get("asset_request")
            if isinstance(request, dict):
                request["asset_ref"] = {
                    "path": str(self.asset.resolve()),
                    "sha256": sha256_file(self.asset),
                }
        self.brief = {"schema_version": 3, "opportunity_model": "decision_complete_v1", "events": self.events}
        authorities = []
        for row in self.events:
            for evidence_id, kind in (
                (row.get("subject_track_id"), "subject_track"),
                (row["portrait_energy_intent"]["signals"].get("gesture_evidence_id"), "gesture_track"),
                (row["portrait_energy_intent"]["signals"].get("chapter_boundary_evidence_id"), "chapter_boundary"),
            ):
                if evidence_id:
                    authority = {
                        "evidence_id": evidence_id, "kind": kind, "status": "current",
                        "source": "test", "source_sha256": _hash("authority-source"),
                        "window": {"start_seconds": row["source_start"], "end_seconds": row["source_end"]},
                        "time_domain": "source",
                    }
                    if kind == "subject_track":
                        authority.update({"visible": True, "face": {"x": .35, "y": .2, "w": .3, "h": .3}, "crop": {"x": .2, "y": .1, "w": .6, "h": .8}})
                    if kind == "gesture_track":
                        authority.update({
                            "visible": True,
                            "points": [[0.2, 0.4], [0.5, 0.3]],
                            "source_apex_seconds": row["source_start"] + 0.2,
                            "output_apex_seconds": row["output_start"] + 0.2,
                        })
                    if kind == "chapter_boundary":
                        authority["structural"] = True
                    authority["authority_sha256"] = _hash(authority)
                    authorities.append(authority)
        self.energy.write_text(json.dumps({
            "schema_version": 1,
            "project_id": "portrait-fixture",
            "source_media": {"path": str((self.root / "source.mp4").resolve()), "sha256": _hash("source")},
            "input_hashes": {"edl": _hash("edl"), "transcript": _hash("transcript"), "semantic_brief": _hash(self.brief), "evidence": _hash("evidence")},
            "chapters": [{
                "chapter_id": "chapter-1", "output_window": {"start_seconds": 0.1, "end_seconds": 10.0},
                "entry_energy": 0.2, "exit_energy": 0.8, "intent": "rise",
                "evidence_refs": ["subject:e2"],
            }],
            "evidence_authorities": authorities,
            "opportunities": [{
                "semantic_event_id": row["id"],
                "chapter_id": "chapter-1",
                "tier": row["portrait_energy_intent"]["tier"],
                "transition_intent": "rise",
                "max_attention_layers": row["portrait_energy_intent"]["max_attention_layers"],
                "rationale": "Explicit fixture energy decision for deterministic recipe selection.",
                "evidence_refs": [
                    value for value in (
                        row.get("subject_track_id"),
                        row["portrait_energy_intent"]["signals"].get("gesture_evidence_id"),
                        row["portrait_energy_intent"]["signals"].get("chapter_boundary_evidence_id"),
                    ) if value
                ] or ["subject:e2"],
                **({"gesture_evidence_id": row["portrait_energy_intent"]["signals"]["gesture_evidence_id"]} if row["portrait_energy_intent"]["signals"].get("gesture_evidence_id") else {}),
                **({"chapter_boundary_evidence_id": row["portrait_energy_intent"]["signals"]["chapter_boundary_evidence_id"]} if row["portrait_energy_intent"]["signals"].get("chapter_boundary_evidence_id") else {}),
                "fallback_tier": "meso" if row["portrait_energy_intent"]["tier"] == "macro" else "micro",
            } for row in self.events],
            "selection_policy": {"fixed_cadence": False, "minimum_event_quota": False, "random_rotation": False, "density_is_diagnostic_only": True},
        }), encoding="utf-8")
        self.base = {"opportunities": [{
            "semantic_event_id": row["id"], "decision": "render",
            "approved_visible_copy": row["approved_visible_copy"],
            "output_window": {"start_seconds": row["output_start"], "end_seconds": row["output_end"]},
        } for row in self.events]}
        design_tokens = self.root / "design-tokens.json"
        design_tokens.write_text(json.dumps({"sampling": {"dimensions": {"width": 1080, "height": 1920}}}), encoding="utf-8")
        brief_path = self.root / "brief.json"
        brief_path.write_text(json.dumps(self.brief), encoding="utf-8")
        project = {
            "schema_version": 11, "video_id": "portrait-fixture",
            "identity": {"mode": "self"}, "source": {"content_type": "talking_head"},
            "motion_quality": {"enabled": True, "portrait_brand": {
                "enabled": True, "grammar_version": 2,
                "style_direction": "luminous_intelligence",
                "require_user_brand_approval": True,
            }},
        }
        self.playbook = compile_playbook(
            project=project, design_tokens_path=design_tokens,
            semantic_brief_path=brief_path, profile_path=self.profile,
            output_dir=self.root / "playbook",
        )[0]

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _event(
        event_id: str, role: str, tier: str, copy: list[str], *,
        subject: bool = False, gesture: bool = False, asset: bool = False,
        boundary: bool = False, camera: bool = False,
    ) -> dict:
        index = int(event_id[1:])
        signals = {
            "semantic_pressure": 0.8, "emotional_turn": "rise",
            "speech_rate_wpm": 150.0, "pause_seconds": 0.2,
            "gesture_evidence_id": f"gesture:{event_id}" if gesture else None,
            "chapter_boundary_evidence_id": f"boundary:{event_id}" if boundary else None,
        }
        event = {
            "id": event_id, "semantic_role": role,
            "approved_visible_copy": copy,
            "source_start": float(index), "source_end": float(index) + 0.8,
            "output_start": float(index), "output_end": float(index) + 0.8,
            "portrait_energy_intent": {
                "chapter_id": "chapter-1", "tier": tier,
                "transition_intent": "rise", "max_attention_layers": 2,
                "rationale": "Explicit fixture energy decision for deterministic recipe selection.",
                "evidence_refs": [value for value in (
                    f"subject:{event_id}" if subject else None,
                    signals.get("gesture_evidence_id"), signals.get("chapter_boundary_evidence_id"),
                ) if value] or ["subject:e2"],
                "fallback_tier": "meso" if tier == "macro" else "micro",
                "signals": signals,
            },
        }
        if subject:
            event["subject_track_id"] = f"subject:{event_id}"
            event["subject_region_id"] = f"region:{event_id}"
            event["source_target_id"] = "source-media"
        if asset:
            event["asset_request_id"] = f"asset:{event_id}"
            event["asset_request"] = {
                "id": f"asset:{event_id}",
                "asset_ref": {"path": "__ASSET_PATH__", "sha256": "__ASSET_SHA__"},
            }
        if camera:
            event["camera_intent"] = True
        return event

    def compile(self) -> dict:
        return compile_portrait_motion_contracts(
            semantic_brief=self.brief, base_motion_contract=self.base,
            profile_path=self.profile, energy_map_path=self.energy,
            registry_path=DEFAULT_PORTRAIT_RECIPE_REGISTRY,
            brand_playbook_path=self.playbook,
        )

    def test_registry_has_eight_distinct_seek_safe_non_card_recipes(self) -> None:
        registry = load_portrait_recipe_registry()
        self.assertEqual(validate_portrait_recipe_registry(registry), [])
        self.assertEqual([row["recipe_id"] for row in registry["recipes"]], [
            f"PBM-{index:02d}" for index in range(1, 9)
        ])
        fingerprints = [recipe_fingerprint(row)["composite_sha256"] for row in registry["recipes"]]
        self.assertEqual(len(fingerprints), len(set(fingerprints)))
        self.assertTrue(all(row["post_exit"].endswith(("only", "clear", "identity")) for row in registry["recipes"]))

    def test_all_eight_recipes_compile_deterministically(self) -> None:
        first = self.compile()
        second = self.compile()
        self.assertEqual(first, second)
        self.assertEqual([row["primary_recipe_id"] for row in first["contracts"]], [
            "PBM-01", "PBM-02", "PBM-03", "PBM-04",
            "PBM-05", "PBM-06", "PBM-07", "PBM-08",
        ])
        self.assertTrue(all(not validate_portrait_contract_schema(
            "portrait-motion-contract", row
        ) for row in first["contracts"]))
        choreography = portrait_choreography_by_event(
            first, load_portrait_recipe_registry(),
        )
        self.assertEqual(set(choreography), {f"e{index}" for index in range(1, 9)})
        renderer = build_portrait_renderer_payload(first, load_portrait_recipe_registry())
        by_recipe = {row["recipeId"]: row for row in renderer["events"]}
        self.assertEqual(by_recipe["PBM-03"]["bindings"]["gestureBinding"]["points"], [[0.2, 0.4], [0.5, 0.3]])
        self.assertTrue(by_recipe["PBM-06"]["bindings"]["assetUrl"].startswith("file:"))
        project_renderer = build_portrait_renderer_payload(
            first, load_portrait_recipe_registry(), project_root=self.root / "hf-project",
        )
        project_asset = {
            row["recipeId"]: row for row in project_renderer["events"]
        }["PBM-06"]["bindings"]
        self.assertTrue(project_asset["assetUrl"].startswith("./assets/portrait-brand-v2/media/"))
        self.assertTrue(project_asset["assetRuntimeUrl"].startswith("file:"))
        self.assertTrue(Path(project_asset["renderAssetRef"]["path"]).is_file())

    def test_gesture_and_chapter_recipes_fail_closed_without_evidence(self) -> None:
        self.events[2]["portrait_energy_intent"]["signals"]["gesture_evidence_id"] = None
        energy = json.loads(self.energy.read_text(encoding="utf-8"))
        energy["opportunities"][2].pop("gesture_evidence_id", None)
        energy["opportunities"][2]["evidence_refs"] = [
            value for value in energy["opportunities"][2]["evidence_refs"]
            if value != "gesture:e3"
        ] or ["subject:e2"]
        self.events[2]["portrait_energy_intent"]["evidence_refs"] = list(
            energy["opportunities"][2]["evidence_refs"]
        )
        energy["input_hashes"]["semantic_brief"] = _hash(self.brief)
        self.energy.write_text(json.dumps(energy), encoding="utf-8")
        result = self.compile()
        self.assertEqual(result["contracts"][2]["primary_recipe_id"], "PBM-01")
        self.events[6]["portrait_energy_intent"]["signals"]["chapter_boundary_evidence_id"] = None
        with self.assertRaises(PortraitRecipeError):
            self.compile()

    def test_registry_rejects_card_cadence_random_and_dirty_exit(self) -> None:
        registry = load_portrait_recipe_registry()
        for mutate in (
            lambda row: row.__setitem__("events_per_minute", 12),
            lambda row: row.__setitem__("layout", "rounded_card_shell"),
            lambda row: row.__setitem__("post_exit", "overlay_retained"),
        ):
            changed = deepcopy(registry)
            mutate(changed["recipes"][0])
            self.assertTrue(validate_portrait_recipe_registry(changed))

    def test_component_bundle_is_reusable_and_contains_no_project_copy(self) -> None:
        project = self.root / "hyperframes"
        manifest = materialize_portrait_component_assets(project)
        self.assertEqual(len(manifest["outputs"]), 2)
        for row in manifest["outputs"]:
            output = Path(row["output"]["path"])
            self.assertTrue(output.is_file())
            self.assertEqual(row["output"]["sha256"], sha256_file(output))
        javascript = Path(manifest["outputs"][0]["output"]["path"]).read_text(encoding="utf-8")
        stylesheet = Path(manifest["outputs"][1]["output"]["path"]).read_text(encoding="utf-8")
        self.assertIn("PBM-08", javascript)
        self.assertNotIn("继续向前", javascript)
        self.assertNotIn("pointerEvents = \"none\"", javascript)
        self.assertNotIn("pointer-events:none", stylesheet.replace(" ", ""))

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_component_materializer_rejects_project_asset_junction(self) -> None:
        with tempfile.TemporaryDirectory() as outside_folder:
            project = self.root / "junction-project"
            assets = project / "assets"
            assets.mkdir(parents=True)
            outside = Path(outside_folder).resolve()
            junction = assets / "portrait-brand-v2"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            with self.assertRaisesRegex(PortraitRecipeError, "redirected"):
                materialize_portrait_component_assets(project)
            self.assertEqual(list(outside.iterdir()), [])

    def test_renderer_payload_rejects_undecodable_semantic_asset(self) -> None:
        bundle = self.compile()
        self.asset.write_bytes(b"not-an-image")
        bundle["contracts"][5]["asset_ref"]["sha256"] = sha256_file(self.asset)
        with self.assertRaisesRegex(PortraitRecipeError, "decodable image"):
            build_portrait_renderer_payload(
                bundle, load_portrait_recipe_registry(),
            )

    def test_storyboard_must_bind_exact_portrait_recipe_component_and_phases(self) -> None:
        bundle = self.compile()
        registry = load_portrait_recipe_registry()
        choreography = portrait_choreography_by_event(bundle, registry)
        storyboard = {"events": [{
            "semantic_event_id": row["semantic_event_id"],
            **choreography[row["semantic_event_id"]],
            "visible_copy_manifest": row["approved_visible_copy"],
        } for row in bundle["contracts"]]}
        self.assertEqual(validate_storyboard_portrait_binding(storyboard, bundle), [])
        for key, value in (
            ("portrait_energy_tier", "FORGED"),
            ("supporting_layers", ["icon_burst"]),
            ("protected_region_ids", []),
            ("seek_safe", False),
            ("portrait_fingerprints", {"composite_sha256": "0" * 64}),
        ):
            changed = deepcopy(storyboard)
            changed["events"][0][key] = value
            with self.subTest(key=key):
                self.assertTrue(validate_storyboard_portrait_binding(changed, bundle))

    def test_compiler_revalidates_profile_energy_and_playbook(self) -> None:
        original = self.profile.read_text(encoding="utf-8")
        self.profile.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(PortraitRecipeError, "profile"):
            self.compile()
        self.profile.write_text(original, encoding="utf-8")

        energy = json.loads(self.energy.read_text(encoding="utf-8"))
        energy.pop("evidence_authorities")
        self.energy.write_text(json.dumps(energy), encoding="utf-8")
        with self.assertRaisesRegex(PortraitRecipeError, "energy"):
            self.compile()

    def test_energy_fields_must_exactly_inherit_semantic_intent(self) -> None:
        payload = json.loads(self.energy.read_text(encoding="utf-8"))
        payload["opportunities"][0]["tier"] = "meso"
        self.energy.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(PortraitRecipeError, "energy.*semantic"):
            self.compile()

    def test_base_motion_copy_and_output_window_must_inherit_semantic_brief(self) -> None:
        self.base["opportunities"][0]["approved_visible_copy"] = ["伪造文案"]
        with self.assertRaisesRegex(PortraitRecipeError, "approved visible copy"):
            self.compile()

        self.base["opportunities"][0]["approved_visible_copy"] = list(
            self.events[0]["approved_visible_copy"]
        )
        self.base["opportunities"][0]["output_window"]["end_seconds"] += 0.25
        with self.assertRaisesRegex(PortraitRecipeError, "output window"):
            self.compile()

    def test_unusable_subject_binding_uses_declared_recipe_fallback(self) -> None:
        payload = json.loads(self.energy.read_text(encoding="utf-8"))
        authority = next(
            row for row in payload["evidence_authorities"]
            if row["evidence_id"] == "subject:e2"
        )
        authority.update({"status": "fallback_center", "visible": False})
        authority["authority_sha256"] = _hash({
            key: value for key, value in authority.items() if key != "authority_sha256"
        })
        self.energy.write_text(json.dumps(payload), encoding="utf-8")
        result = self.compile()
        self.assertEqual(result["contracts"][1]["primary_recipe_id"], "PBM-01")

    def test_recipe_specific_bindings_are_typed_and_current(self) -> None:
        bundle = self.compile()
        by_recipe = {row["primary_recipe_id"]: row for row in bundle["contracts"]}
        self.assertEqual(by_recipe["PBM-03"]["gesture_binding"]["kind"], "gesture_track")
        gesture_event = next(row for row in self.events if row["id"] == "e3")
        self.assertEqual(
            by_recipe["PBM-03"]["gesture_binding"]["output_apex_seconds"],
            gesture_event["output_start"] + 0.2,
        )
        self.assertEqual(by_recipe["PBM-05"]["subject_binding"]["kind"], "subject_track")
        self.assertEqual(by_recipe["PBM-07"]["chapter_boundary_binding"]["kind"], "chapter_boundary")
        self.assertEqual(by_recipe["PBM-06"]["asset_ref"]["sha256"], sha256_file(self.asset))

        energy = json.loads(self.energy.read_text(encoding="utf-8"))
        for authority in energy["evidence_authorities"]:
            if authority["evidence_id"] == "gesture:e3":
                authority["kind"] = "transcript_word"
                authority["authority_sha256"] = _hash({
                    key: value for key, value in authority.items() if key != "authority_sha256"
                })
        self.energy.write_text(json.dumps(energy), encoding="utf-8")
        result = self.compile()
        self.assertEqual(result["contracts"][2]["primary_recipe_id"], "PBM-01")

    def test_public_payloads_fail_closed(self) -> None:
        self.assertTrue(validate_storyboard_portrait_binding({}, []))
        with self.assertRaisesRegex(PortraitRecipeError, "semantic_brief"):
            compile_portrait_motion_contracts(
                semantic_brief=[], base_motion_contract={}, profile_path=self.profile,
                energy_map_path=self.energy, registry_path=DEFAULT_PORTRAIT_RECIPE_REGISTRY,
                brand_playbook_path=self.playbook,
            )
        self.assertTrue(validate_storyboard_portrait_binding(
            {"events": [{"semantic_event_id": "e1"}]},
            {"contracts": [{"semantic_event_id": "e1"}], "diagnostics": []},
        ))
