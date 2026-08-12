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
from motion_contracts import DEFAULT_RECIPE_REGISTRY, load_recipe_registry  # noqa: E402
from motion_quality_engine import (  # noqa: E402
    MotionCompilationError,
    build_hyperframes_choreography,
    compile_motion_design,
    choreography_fingerprint,
)


def semantic_brief() -> dict:
    return {
        "schema_version": 3,
        "opportunity_model": "decision_complete_v1",
        "events": [
            {
                "id": "event-mark", "decision": "render",
                "decision_rationale": "mark one verified detail",
                "source_start": 1.0, "source_end": 3.0,
                "output_start": 1.0, "output_end": 3.0,
                "transcript_word_ids": ["w1"], "approved_visible_copy": ["关键指标"],
                "viewer_takeaway": "notice the verified metric", "target_frame_evidence": ["frame-1"],
                "semantic_role": "mark", "form": "semantic_mark",
            },
            {
                "id": "event-quiet", "decision": "quiet_source",
                "decision_rationale": "source already demonstrates the state",
                "source_start": 3.0, "source_end": 10.0,
                "output_start": 3.0, "output_end": 10.0,
                "transcript_word_ids": ["w2"], "approved_visible_copy": [],
                "viewer_takeaway": "inspect the source", "target_frame_evidence": ["frame-2"],
            },
        ],
    }


class MotionQualityEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"source-media")
        self.artifacts = {}
        for name in ("semantic_brief", "production_contract", "evidence_bundle", "brand_playbook"):
            path = self.root / f"{name}.json"
            path.write_text(json.dumps({"name": name}), encoding="utf-8")
            self.artifacts[name] = path
        self.artifacts["evidence_bundle"].write_text(json.dumps({
            "source": {"sha256": sha256_file(self.source)},
            "duration_seconds": 12.0,
            "display": {"width": 1920, "height": 1080, "orientation": "landscape"},
        }), encoding="utf-8")
        self.artifacts["production_contract"].write_text(json.dumps({
            "identity": {"mode": "generic"},
        }), encoding="utf-8")
        self.registry = load_recipe_registry(DEFAULT_RECIPE_REGISTRY)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def compile(self, brief: dict | None = None, **overrides: object) -> dict:
        resolved_brief = brief or semantic_brief()
        self.artifacts["semantic_brief"].write_text(
            json.dumps(resolved_brief), encoding="utf-8",
        )
        options = {
            "project_id": "project-test",
            "semantic_brief": resolved_brief,
            "source_media": {
                "path": str(self.source.resolve()), "sha256": sha256_file(self.source),
                "duration_seconds": 12.0, "width": 1920, "height": 1080,
                "orientation": "landscape", "source_type": "screen_recording",
            },
            "identity_mode": "generic",
            "input_artifacts": self.artifacts,
            "adaptive_layout": {"status": "ready", "safe_fallback": "caption_only"},
            "target_bindings": {},
            "advanced_runtimes_enabled": False,
            "recipe_registry": self.registry,
            "created_at": "2026-08-11T00:00:00Z",
        }
        options.update(overrides)
        self.artifacts["production_contract"].write_text(json.dumps({
            "identity": {"mode": options["identity_mode"]},
        }), encoding="utf-8")
        return compile_motion_design(**options)

    def advanced_runtime_evidence(
        self, brief: dict | None = None, *, identity_mode: str = "generic",
    ) -> dict:
        self.artifacts["semantic_brief"].write_text(json.dumps(brief or semantic_brief()), encoding="utf-8")
        self.artifacts["production_contract"].write_text(json.dumps({
            "identity": {"mode": identity_mode},
        }), encoding="utf-8")
        input_hashes = {f"{name}_sha256": sha256_file(path) for name, path in self.artifacts.items()}
        subject_id = __import__("hashlib").sha256(json.dumps({
            "project_id": "project-test", "source_sha256": sha256_file(self.source),
            "input_hashes": input_hashes,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        records = {}
        for name in (
            "seek_safe", "deterministic_2d_fallback", "preview_render_parity",
            "device_support", "license", "cost",
        ):
            path = self.root / f"advanced-{name}.json"
            artifact = self.root / f"advanced-{name}.evidence.json"
            claims = {
                "seek_safe": {"random_access_samples": 5, "seek_error_frames": 0},
                "deterministic_2d_fallback": {"fallback_artifact": str(artifact)},
                "preview_render_parity": {"parity_report": str(artifact)},
                "device_support": {"tested_devices": ["fixture-device"]},
                "license": {"rights_basis": "project-owned", "license_artifact": str(artifact)},
                "cost": {"estimated_cost": 0.0, "currency": "USD"},
            }[name]
            claims_hash = __import__("hashlib").sha256(json.dumps(
                claims, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            proof = {
                "schema_version": 1, "kind": f"advanced_{name}_evidence",
                "status": "pass", "subject_id": subject_id,
                "claims_sha256": claims_hash,
            }
            if name == "seek_safe":
                proof["requested_timestamps_seconds"] = [float(index) for index in range(5)]
                proof["source_duration_seconds"] = 12.0
                proof["samples"] = [
                    {"timestamp_seconds": float(index), "seek_error_frames": 0}
                    for index in range(5)
                ]
            elif name == "deterministic_2d_fallback":
                from PIL import Image
                output = self.root / "fallback.png"
                Image.new("RGB", (64, 64), (10, 20, 30)).save(output)
                proof["fallback_output"] = {
                    "path": str(output.resolve()), "sha256": sha256_file(output),
                }
            elif name == "preview_render_parity":
                from PIL import Image
                reference = self.root / "advanced-reference.png"
                rendered = self.root / "advanced-rendered.png"
                Image.new("RGB", (64, 64), (30, 40, 50)).save(reference)
                rendered.write_bytes(reference.read_bytes())
                proof["measurements"] = [{
                    "status": "pass",
                    "reference": {"path": str(reference.resolve()), "sha256": sha256_file(reference)},
                    "rendered": {"path": str(rendered.resolve()), "sha256": sha256_file(rendered)},
                }]
            elif name == "device_support":
                proof["devices"] = [{"device_id": "fixture-device", "status": "pass"}]
            elif name == "license":
                document = self.root / "license.txt"
                document.write_text("project-owned test fixture", encoding="utf-8")
                proof["rights_basis"] = "project-owned"
                proof["license_document"] = {
                    "path": str(document.resolve()), "sha256": sha256_file(document),
                }
            else:
                proof.update({
                    "estimated_cost": 0.0, "currency": "USD",
                    "calculation_inputs": {"render_seconds": 12.0},
                })
            proof["evidence_sha256"] = __import__("hashlib").sha256(json.dumps(
                proof, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            artifact.write_text(json.dumps(proof), encoding="utf-8")
            payload = {
                "schema_version": 1, "status": "pass", "kind": name,
                "subject_id": subject_id, "tool_version": "fixture-1",
                "claims": claims,
                "artifacts": [{"path": str(artifact.resolve()), "sha256": sha256_file(artifact)}],
            }
            payload["evidence_sha256"] = __import__("hashlib").sha256(json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            path.write_text(json.dumps(payload), encoding="utf-8")
            records[name] = {
                "status": "pass", "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
        return records

    def test_advanced_runtime_rejects_hash_bound_non_evidence_text(self) -> None:
        evidence = self.advanced_runtime_evidence()
        path = Path(evidence["seek_safe"]["path"])
        path.write_text("not evidence", encoding="utf-8")
        evidence["seek_safe"]["sha256"] = sha256_file(path)
        result = self.compile(
            advanced_runtimes_enabled=True, advanced_runtime_evidence=evidence,
        )
        self.assertEqual(result["advanced_runtime"]["status"], "action_required")

    def test_advanced_runtime_rejects_valid_claims_with_unparsed_junk_artifacts(self) -> None:
        evidence = self.advanced_runtime_evidence()
        for row in evidence.values():
            receipt_path = Path(row["path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            artifact_path = Path(receipt["artifacts"][0]["path"])
            artifact_path.write_text("not evidence", encoding="utf-8")
            receipt["artifacts"][0]["sha256"] = sha256_file(artifact_path)
            receipt["evidence_sha256"] = __import__("hashlib").sha256(json.dumps(
                {key: value for key, value in receipt.items() if key != "evidence_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            row["sha256"] = sha256_file(receipt_path)

        result = self.compile(
            advanced_runtimes_enabled=True, advanced_runtime_evidence=evidence,
        )

        self.assertEqual(result["advanced_runtime"]["status"], "action_required")
        self.assertEqual(
            result["advanced_runtime"]["missing_or_invalid_evidence"],
            list(evidence),
        )

    def test_advanced_runtime_rejects_invalid_types_and_repeated_seek_samples(self) -> None:
        for name, mutate in (
            ("device_support", lambda claims, proof: (
                claims.__setitem__("tested_devices", [None]),
                proof.__setitem__("devices", [{"device_id": None, "status": "pass"}]),
            )),
            ("cost", lambda claims, proof: (
                claims.__setitem__("currency", 123), proof.__setitem__("currency", 123),
            )),
            ("license", lambda claims, proof: (
                claims.__setitem__("rights_basis", ["owned"]),
                proof.__setitem__("rights_basis", ["owned"]),
            )),
            ("seek_safe", lambda claims, proof: (
                proof.__setitem__("requested_timestamps_seconds", [0.0] * 5),
                proof.__setitem__("samples", [
                    {"timestamp_seconds": 0.0, "seek_error_frames": 0} for _ in range(5)
                ]),
            )),
        ):
            with self.subTest(name=name):
                evidence = self.advanced_runtime_evidence()
                receipt_path = Path(evidence[name]["path"])
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                artifact_path = Path(receipt["artifacts"][0]["path"])
                proof = json.loads(artifact_path.read_text(encoding="utf-8"))
                mutate(receipt["claims"], proof)
                proof["claims_sha256"] = __import__("hashlib").sha256(json.dumps(
                    receipt["claims"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode()).hexdigest()
                proof["evidence_sha256"] = __import__("hashlib").sha256(json.dumps(
                    {key: value for key, value in proof.items() if key != "evidence_sha256"},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode()).hexdigest()
                artifact_path.write_text(json.dumps(proof), encoding="utf-8")
                receipt["artifacts"][0]["sha256"] = sha256_file(artifact_path)
                receipt["evidence_sha256"] = __import__("hashlib").sha256(json.dumps(
                    {key: value for key, value in receipt.items() if key != "evidence_sha256"},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode()).hexdigest()
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                evidence[name]["sha256"] = sha256_file(receipt_path)
                result = self.compile(
                    advanced_runtimes_enabled=True, advanced_runtime_evidence=evidence,
                )
                self.assertEqual(result["advanced_runtime"]["status"], "action_required")
                self.assertIn(name, result["advanced_runtime"]["missing_or_invalid_evidence"])

    def test_advanced_seek_samples_must_fit_current_source_duration(self) -> None:
        evidence = self.advanced_runtime_evidence()
        receipt_path = Path(evidence["seek_safe"]["path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        artifact_path = Path(receipt["artifacts"][0]["path"])
        proof = json.loads(artifact_path.read_text(encoding="utf-8"))
        proof["source_duration_seconds"] = 1000.0
        proof["requested_timestamps_seconds"] = [100.0, 200.0, 300.0, 400.0, 500.0]
        proof["samples"] = [
            {"timestamp_seconds": value, "seek_error_frames": 0}
            for value in proof["requested_timestamps_seconds"]
        ]
        proof["evidence_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in proof.items() if key != "evidence_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        artifact_path.write_text(json.dumps(proof), encoding="utf-8")
        receipt["artifacts"][0]["sha256"] = sha256_file(artifact_path)
        receipt["evidence_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in receipt.items() if key != "evidence_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        evidence["seek_safe"]["sha256"] = sha256_file(receipt_path)

        result = self.compile(
            advanced_runtimes_enabled=True, advanced_runtime_evidence=evidence,
        )

        self.assertEqual(result["advanced_runtime"]["status"], "action_required")
        self.assertIn("seek_safe", result["advanced_runtime"]["missing_or_invalid_evidence"])

    def test_identical_inputs_compile_to_identical_contract_and_report(self) -> None:
        first = self.compile()
        second = self.compile()
        self.assertEqual(first, second)
        self.assertEqual(first["contract"]["selected_event_ids"], ["event-mark"])
        self.assertEqual(first["contract"]["opportunities"][1]["decision"], "quiet_source")

    def test_absolute_frame_evidence_compiles_to_content_addressed_contract_id(self) -> None:
        frame = self.root / "frame.png"
        frame.write_bytes(b"real-frame-evidence")
        brief = semantic_brief()
        brief["events"][0]["target_frame_evidence"] = [str(frame.resolve())]
        self.artifacts["evidence_bundle"].write_text(json.dumps({
            "source": {"sha256": sha256_file(self.source)},
            "duration_seconds": 12.0,
            "display": {"width": 1920, "height": 1080, "orientation": "landscape"},
            "representative_frames": [{
                "path": str(frame.resolve()), "sha256": sha256_file(frame),
            }],
        }), encoding="utf-8")

        result = self.compile(brief)

        self.assertEqual(
            result["contract"]["opportunities"][0]["evidence_refs"],
            [f"frame-sha256:{sha256_file(frame)}"],
        )

    def test_copy_or_timing_does_not_randomize_recipe_selection(self) -> None:
        first = semantic_brief()
        second = deepcopy(first)
        second["events"][0]["approved_visible_copy"] = ["打开"]
        second["events"][0]["source_start"] = 7.0
        second["events"][0]["source_end"] = 9.0
        second["events"][0]["output_start"] = 7.0
        second["events"][0]["output_end"] = 9.0
        self.assertEqual(
            self.compile(first)["contract"]["opportunities"][0]["recipe_id"],
            self.compile(second)["contract"]["opportunities"][0]["recipe_id"],
        )

    def test_advanced_depth_recipe_uses_declared_deterministic_fallback(self) -> None:
        brief = semantic_brief()
        brief["events"][0].update({"semantic_role": "explain", "form": "depth_stage"})
        result = self.compile(brief)
        event = result["contract"]["opportunities"][0]
        self.assertEqual(event["recipe_id"], "MQE-15")
        self.assertEqual(result["diagnostics"][0]["fallback_chain"], ["MQE-16", "MQE-15"])

    def test_third_party_ip_recipe_falls_back_without_personal_assets(self) -> None:
        brief = semantic_brief()
        brief["events"][0].update({"semantic_role": "explain", "form": "ip_vignette"})
        result = self.compile(brief, identity_mode="third_party")
        self.assertNotEqual(result["contract"]["opportunities"][0]["recipe_id"], "MQE-14")
        self.assertIn("identity.third_party", result["diagnostics"][0]["rejected_rules"])

    def test_target_recipe_without_binding_uses_declared_safe_fallback(self) -> None:
        brief = semantic_brief()
        brief["events"][0].update({"semantic_role": "explain", "form": "ui_focus"})
        result = self.compile(brief)
        self.assertEqual(result["contract"]["opportunities"][0]["recipe_id"], "MQE-12")
        self.assertFalse(result["diagnostics"][0]["guessed_coordinates"])

    def test_target_fallback_drops_unresolved_binding_ids(self) -> None:
        brief = semantic_brief()
        brief["events"][0].update({
            "semantic_role": "explain", "form": "ui_focus",
            "target_binding_ids": ["missing-target"],
        })
        result = self.compile(brief)
        self.assertEqual(result["contract"]["opportunities"][0]["recipe_id"], "MQE-12")
        self.assertEqual(result["contract"]["opportunities"][0]["target_binding_ids"], [])

    def test_compiler_rejects_semantics_that_do_not_match_hashed_brief(self) -> None:
        approved = semantic_brief()
        self.artifacts["semantic_brief"].write_text(json.dumps(approved), encoding="utf-8")
        tampered = deepcopy(approved)
        tampered["events"][0]["approved_visible_copy"] = ["unapproved"]
        with self.assertRaisesRegex(MotionCompilationError, "semantic brief payload"):
            compile_motion_design(
                project_id="project-test", semantic_brief=tampered,
                source_media={
                    "path": str(self.source.resolve()), "sha256": sha256_file(self.source),
                    "duration_seconds": 12.0, "width": 1920, "height": 1080,
                    "orientation": "landscape", "source_type": "screen_recording",
                },
                identity_mode="generic", input_artifacts=self.artifacts,
                adaptive_layout={"status": "ready"}, target_bindings={},
                advanced_runtimes_enabled=False, recipe_registry=self.registry,
                created_at="2026-08-11T00:00:00Z",
            )

    def test_roles_have_distinct_choreography_fingerprints(self) -> None:
        recipes = {row["recipe_id"]: row for row in self.registry["recipes"]}
        fingerprints = {
            choreography_fingerprint(recipes[recipe_id])
            for recipe_id in ("MQE-01", "MQE-05", "MQE-06", "MQE-07", "MQE-11", "MQE-12")
        }
        self.assertEqual(len(fingerprints), 6)

    def test_talking_head_choreography_uses_face_safe_expressive_grammar(self) -> None:
        self.artifacts["evidence_bundle"].write_text(json.dumps({
            "source": {"sha256": sha256_file(self.source)},
            "duration_seconds": 12.0,
            "display": {"width": 1080, "height": 1920, "orientation": "portrait"},
        }), encoding="utf-8")
        result = self.compile(source_media={
            "path": str(self.source.resolve()), "sha256": sha256_file(self.source),
            "duration_seconds": 12.0, "width": 1080, "height": 1920,
            "orientation": "portrait", "source_type": "talking_head",
        })

        choreography = build_hyperframes_choreography(
            result["contract"], advanced_runtime=result["advanced_runtime"],
        )

        grammar = choreography["format_grammar"]
        self.assertEqual(grammar["grammar_id"], "talking-head-expressive-v1")
        self.assertEqual(grammar["primary_subject_priority"], [
            "speaker_face", "speaker_gesture", "spoken_meaning", "captions",
        ])
        self.assertIn("kinetic_typography", grammar["preferred_treatments"])
        self.assertIn("face_safe_side_rail", grammar["preferred_treatments"])
        self.assertIn("floating_product_card", grammar["disallowed_default_treatments"])
        self.assertFalse(grammar["fixed_event_cadence"])
        self.assertFalse(grammar["random_template_rotation"])
        self.assertEqual(
            choreography["events"][0]["format_grammar_id"],
            "talking-head-expressive-v1",
        )

    def test_screen_recording_choreography_uses_target_explanation_grammar(self) -> None:
        result = self.compile()

        choreography = build_hyperframes_choreography(result["contract"])

        grammar = choreography["format_grammar"]
        self.assertEqual(grammar["grammar_id"], "screen-product-explainer-v1")
        self.assertIn("target_relative_callout", grammar["preferred_treatments"])
        self.assertNotIn("floating_product_card", grammar["disallowed_default_treatments"])

    def test_format_grammar_is_deterministic_for_identical_source_type(self) -> None:
        contract = self.compile()["contract"]

        first = build_hyperframes_choreography(contract)
        second = build_hyperframes_choreography(contract)

        self.assertEqual(first, second)
        self.assertEqual(
            first["format_grammar_sha256"], second["format_grammar_sha256"],
        )

    def test_advanced_runtime_requires_seek_device_license_cost_and_fallback_evidence(self) -> None:
        brief = semantic_brief()
        brief["events"][0].update({"semantic_role": "explain", "form": "depth_stage"})
        result = self.compile(brief, advanced_runtimes_enabled=True)

        choreography = build_hyperframes_choreography(result["contract"])

        event = choreography["events"][0]
        self.assertEqual(event["recipe_id"], "MQE-15")
        self.assertNotIn("advanced_runtime_gate", event)
        self.assertEqual(result["advanced_runtime"]["status"], "action_required")
        self.assertEqual(result["advanced_runtime"]["missing_or_invalid_evidence"], [
            "seek_safe", "deterministic_2d_fallback", "preview_render_parity",
            "device_support", "license", "cost",
        ])

    def test_advanced_runtime_is_selected_only_with_current_real_evidence(self) -> None:
        brief = semantic_brief()
        brief["events"][0].update({"semantic_role": "explain", "form": "depth_stage"})
        evidence = self.advanced_runtime_evidence(brief)

        result = self.compile(
            brief, advanced_runtimes_enabled=True,
            advanced_runtime_evidence=evidence,
        )
        choreography = build_hyperframes_choreography(
            result["contract"], advanced_runtime=result["advanced_runtime"],
        )

        event = choreography["events"][0]
        self.assertEqual(event["recipe_id"], "MQE-16")
        self.assertEqual(event["advanced_runtime_gate"]["status"], "ready")
        self.assertEqual(
            event["advanced_runtime_gate"]["evidence_sha256"],
            {name: row["sha256"] for name, row in evidence.items()},
        )

    def test_stale_advanced_runtime_evidence_forces_deterministic_2d_fallback(self) -> None:
        brief = semantic_brief()
        brief["events"][0].update({"semantic_role": "explain", "form": "depth_stage"})
        evidence = self.advanced_runtime_evidence(brief)
        evidence["device_support"]["sha256"] = "0" * 64

        result = self.compile(
            brief, advanced_runtimes_enabled=True,
            advanced_runtime_evidence=evidence,
        )

        self.assertEqual(result["contract"]["opportunities"][0]["recipe_id"], "MQE-15")
        self.assertEqual(
            result["advanced_runtime"]["missing_or_invalid_evidence"], ["device_support"],
        )

    def test_all_sixteen_recipes_compile_from_explicit_structured_forms(self) -> None:
        forms_and_roles = [
            ("semantic_mark", "mark"), ("ui_focus", "explain"),
            ("cursor_causality", "sequence"), ("compare", "relate"),
            ("process", "sequence"), ("relation", "relate"),
            ("metric_proof", "prove"), ("before_after", "transition"),
            ("product_lens", "explain"), ("camera_focus", "explain"),
            ("chapter_bridge", "transition"), ("kinetic_phrase", "resolve"),
            ("evidence_pip", "prove"), ("ip_vignette", "explain"),
            ("architecture", "explain"), ("depth_stage", "explain"),
        ]
        target_recipe_indexes = {2, 3, 7, 9}
        events = []
        target_bindings = {}
        for index, (form, role) in enumerate(forms_and_roles, start=1):
            start = index * 0.5
            target_ids = [f"target-{index}"] if index in target_recipe_indexes else []
            if target_ids:
                target_bindings[target_ids[0]] = {"status": "resolved"}
            events.append({
                "id": f"event-{index}", "decision": "render",
                "decision_rationale": f"explicit recipe fixture {index}",
                "source_start": start, "source_end": start + 0.4,
                "output_start": start, "output_end": start + 0.4,
                "transcript_word_ids": [f"w-{index}"],
                "approved_visible_copy": [f"copy-{index}"],
                "viewer_takeaway": f"takeaway-{index}",
                "target_frame_evidence": [f"frame-{index}"],
                "semantic_role": role, "form": form,
                "target_binding_ids": target_ids,
            })
        brief = {
            "schema_version": 3,
            "opportunity_model": "decision_complete_v1",
            "events": events,
        }
        result = self.compile(
            brief, identity_mode="self", target_bindings=target_bindings,
            advanced_runtimes_enabled=True,
            advanced_runtime_evidence=self.advanced_runtime_evidence(
                brief, identity_mode="self",
            ),
        )
        self.assertEqual(
            [row["recipe_id"] for row in result["contract"]["opportunities"]],
            [f"MQE-{index:02d}" for index in range(1, 17)],
        )


if __name__ == "__main__":
    unittest.main()
