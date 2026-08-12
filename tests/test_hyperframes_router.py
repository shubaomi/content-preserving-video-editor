from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hyperframes_router import route_hyperframes  # noqa: E402
from director_contracts import sha256_file  # noqa: E402


class HyperFramesRouterTests(unittest.TestCase):
    def test_task_specific_routes_are_evidence_driven(self) -> None:
        self.assertEqual(route_hyperframes({}, {"content_type": "talking_head"})["route"],
                         "talking-head-recut")
        self.assertEqual(route_hyperframes({}, {"content_type": "interview"})["route"],
                         "talking-head-recut")
        self.assertEqual(route_hyperframes({}, {"task": "captions_only"})["route"],
                         "embedded-captions")
        self.assertEqual(route_hyperframes({}, {"task": "standalone_motion"})["route"],
                         "motion-graphics")
        self.assertEqual(route_hyperframes({}, {"content_type": "screen_tutorial"})["route"],
                         "general-video")

    def test_default_is_general_video_and_semantic_authority_stays_with_director(self) -> None:
        result = route_hyperframes({}, {})
        self.assertEqual(result["route"], "general-video")
        self.assertEqual(result["semantic_selection_owner"], "director_with_llm")
        self.assertFalse(result["fixed_card_count"])
        self.assertFalse(result["density_formula_authority"])

    def test_remotion_requires_explicit_enable_and_react_component_evidence(self) -> None:
        denied = route_hyperframes({"renderer": {"remotion": {"enabled": True}}}, {})
        self.assertEqual(denied["renderer"], "hyperframes")
        self.assertIn("missing React", denied["renderer_reason"])
        legacy = route_hyperframes({"renderer": {"remotion": {
            "enabled": True, "react_component_paths": ["brand/Title.tsx"],
            "selected_event_ids": ["event-2"], "parity_evidence": True,
            "license_evidence": "verified-commercial-use.md",
        }}}, {})
        self.assertEqual(legacy["renderer"], "hyperframes")
        self.assertIsNone(legacy["optional_event_renderer"])
        self.assertEqual(legacy["remotion_status"], "action_required")

    def test_remotion_rejects_selected_events_without_parity_and_license_evidence(self) -> None:
        denied = route_hyperframes({"renderer": {"remotion": {
            "enabled": True, "react_component_paths": ["brand/Title.tsx"],
            "selected_event_ids": ["event-2"],
            "parity_evidence": False, "license_evidence": None,
        }}}, {})
        self.assertIsNone(denied["optional_event_renderer"])
        self.assertIn("parity", denied["renderer_reason"])

    def test_remotion_requires_real_hash_bound_component_parity_and_license_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            component = root / "Title.tsx"; component.write_text("export const Title=()=>null", encoding="utf-8")
            component_manifest = root / "component.json"
            component_manifest.write_text(json.dumps({
                "schema_version": 1, "kind": "remotion_component", "status": "pass",
                "event_id": "event-2", "component_path": str(component.resolve()),
                "component_sha256": sha256_file(component),
                "render_contract": {
                    "output_kind": "visual_only", "audio_policy": "forbidden",
                },
            }), encoding="utf-8")
            from PIL import Image
            reference = root / "reference.png"
            rendered = root / "rendered.png"
            Image.new("RGB", (64, 64), (0, 0, 0)).save(reference)
            rendered.write_bytes(reference.read_bytes())
            parity = root / "parity.json"; parity.write_text(json.dumps({
                "schema_version": 1, "kind": "remotion_parity", "status": "pass",
                "selected_event_ids": ["event-2"],
                "component_manifest_sha256_by_event": {"event-2": sha256_file(component_manifest)},
                "measurements": [{
                    "event_id": "event-2", "status": "pass", "frame_delta": 0,
                    "audio_applicable": False, "audio_sample_delta": 0,
                    "reference_artifact": str(reference.resolve()),
                    "reference_sha256": sha256_file(reference),
                    "rendered_artifact": str(rendered.resolve()),
                    "rendered_sha256": sha256_file(rendered),
                }],
            }), encoding="utf-8")
            license_file = root / "license.json"; license_file.write_text(json.dumps({
                "schema_version": 1, "kind": "remotion_license", "status": "pass",
                "authorized_event_ids": ["event-2"], "rights_basis": "project-owned",
            }), encoding="utf-8")
            config = {"renderer": {"remotion": {
                "enabled": True,
                "react_components": [{
                    "event_id": "event-2", "path": str(component), "sha256": sha256_file(component),
                    "manifest_path": str(component_manifest),
                    "manifest_sha256": sha256_file(component_manifest),
                }],
                "selected_event_ids": ["event-2"],
                "parity_evidence": {"path": str(parity), "sha256": sha256_file(parity)},
                "license_evidence": {"path": str(license_file), "sha256": sha256_file(license_file)},
            }}}

            contract = {"selected_event_ids": ["event-2"]}
            selected = route_hyperframes(config, {}, motion_design_contract=contract)
            Image.new("RGB", (64, 64), (255, 255, 255)).save(rendered)
            parity_payload = json.loads(parity.read_text(encoding="utf-8"))
            parity_payload["measurements"][0]["rendered_sha256"] = sha256_file(rendered)
            parity.write_text(json.dumps(parity_payload), encoding="utf-8")
            config["renderer"]["remotion"]["parity_evidence"]["sha256"] = sha256_file(parity)
            wrong_measurement = route_hyperframes(config, {}, motion_design_contract=contract)
            component.write_text("changed", encoding="utf-8")
            stale = route_hyperframes(config, {}, motion_design_contract=contract)

            self.assertEqual(selected["optional_event_renderer"], "remotion")
            self.assertEqual(selected["remotion_status"], "ready")
            self.assertIsNone(wrong_measurement["optional_event_renderer"])
            self.assertEqual(wrong_measurement["remotion_status"], "action_required")
            self.assertIsNone(stale["optional_event_renderer"])
            self.assertEqual(stale["remotion_status"], "action_required")

    def test_remotion_does_not_trust_audio_delta_without_audio_applicability_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            component = root / "Title.tsx"
            component.write_text("export const Title=()=>null", encoding="utf-8")
            component_manifest = root / "component.json"
            component_manifest.write_text(json.dumps({
                "schema_version": 1, "kind": "remotion_component", "status": "pass",
                "event_id": "event-2", "component_path": str(component.resolve()),
                "component_sha256": sha256_file(component),
            }), encoding="utf-8")
            from PIL import Image
            reference = root / "reference.png"
            rendered = root / "rendered.png"
            Image.new("RGB", (64, 64), (0, 0, 0)).save(reference)
            rendered.write_bytes(reference.read_bytes())
            parity = root / "parity.json"
            parity.write_text(json.dumps({
                "schema_version": 1, "kind": "remotion_parity", "status": "pass",
                "selected_event_ids": ["event-2"],
                "component_manifest_sha256_by_event": {"event-2": sha256_file(component_manifest)},
                "measurements": [{
                    "event_id": "event-2", "status": "pass", "frame_delta": 0,
                    "audio_sample_delta": 0,
                    "reference_artifact": str(reference.resolve()),
                    "reference_sha256": sha256_file(reference),
                    "rendered_artifact": str(rendered.resolve()),
                    "rendered_sha256": sha256_file(rendered),
                }],
            }), encoding="utf-8")
            license_file = root / "license.json"
            license_file.write_text(json.dumps({
                "schema_version": 1, "kind": "remotion_license", "status": "pass",
                "authorized_event_ids": ["event-2"], "rights_basis": "project-owned",
            }), encoding="utf-8")
            result = route_hyperframes({"renderer": {"remotion": {
                "enabled": True, "selected_event_ids": ["event-2"],
                "react_components": [{
                    "event_id": "event-2", "path": str(component),
                    "sha256": sha256_file(component),
                    "manifest_path": str(component_manifest),
                    "manifest_sha256": sha256_file(component_manifest),
                }],
                "parity_evidence": {"path": str(parity), "sha256": sha256_file(parity)},
                "license_evidence": {"path": str(license_file), "sha256": sha256_file(license_file)},
            }}}, {}, motion_design_contract={"selected_event_ids": ["event-2"]})

            self.assertEqual(result["remotion_status"], "action_required")

    def test_remotion_rejects_non_audio_bytes_as_audio_parity(self) -> None:
        measurement = {
            "audio_applicable": True, "audio_sample_delta": 0,
            "reference_audio_artifact": str((self.root if hasattr(self, "root") else ROOT) / "none"),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before = root / "before.txt"; before.write_text("not audio", encoding="utf-8")
            after = root / "after.txt"; after.write_text("not audio", encoding="utf-8")
            measurement.update({
                "reference_audio_artifact": str(before.resolve()),
                "reference_audio_sha256": sha256_file(before),
                "rendered_audio_artifact": str(after.resolve()),
                "rendered_audio_sha256": sha256_file(after),
            })
            from hyperframes_router import _audio_parity_valid
            self.assertFalse(_audio_parity_valid(measurement, {}))

    def test_remotion_rejects_unknown_event_and_hash_bound_text_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            component = root / "Title.tsx"; component.write_text("component", encoding="utf-8")
            sidecar = root / "sidecar.txt"; sidecar.write_text("not evidence", encoding="utf-8")
            config = {"renderer": {"remotion": {
                "enabled": True, "selected_event_ids": ["does-not-exist"],
                "react_components": [{
                    "event_id": "does-not-exist", "path": str(component),
                    "sha256": sha256_file(component), "manifest_path": str(sidecar),
                    "manifest_sha256": sha256_file(sidecar),
                }],
                "parity_evidence": {"path": str(sidecar), "sha256": sha256_file(sidecar)},
                "license_evidence": {"path": str(sidecar), "sha256": sha256_file(sidecar)},
            }}}
            result = route_hyperframes(
                config, {}, motion_design_contract={"selected_event_ids": ["event-2"]},
            )
            self.assertEqual(result["remotion_status"], "action_required")

    def test_motion_quality_route_binds_compiler_contract_without_transferring_selection(self) -> None:
        result = route_hyperframes(
            {"motion_quality": {"enabled": True}}, {},
            motion_design_contract={"contract_id": "motion-123", "selected_event_ids": ["e1"]},
        )
        self.assertEqual(result["motion_quality"]["contract_id"], "motion-123")
        self.assertEqual(result["motion_quality"]["selected_event_ids"], ["e1"])
        self.assertEqual(result["motion_quality"]["selection_owner"], "director_motion_quality_engine")
        self.assertEqual(result["motion_quality"]["renderer_authority"], "typed_choreography_only")


if __name__ == "__main__":
    unittest.main()
