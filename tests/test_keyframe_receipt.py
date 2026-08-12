from __future__ import annotations

from copy import deepcopy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from build_keyframe_receipts import _default_runner, build_receipts  # noqa: E402
from keyframe_receipt import (  # noqa: E402
    _verified_render_window,
    recipe_sha256,
    validate_keyframe_receipt,
    validate_renderer_export,
)
from motion_contracts import DEFAULT_RECIPE_REGISTRY, load_recipe_registry  # noqa: E402
from renderer_project_manifest import build_manifest  # noqa: E402


class KeyframeReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_dir = self.root / "hyperframes"
        self.project_dir.mkdir()
        (self.project_dir / "index.html").write_text(
            "<main id='event-1'>motion</main>", encoding="utf-8",
        )
        (self.project_dir / "storyboard.json").write_text("{}", encoding="utf-8")
        self.project = self.project_dir / "renderer-project-manifest.json"
        build_manifest(self.project_dir, self.project)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"source-media")
        self.motion_contract = self.root / "motion-design-contract.json"
        self.motion_contract.write_text(json.dumps({
            "contract_id": "motion-sample",
            "source_media": {"path": str(self.source), "sha256": sha256_file(self.source)},
            "opportunities": [{
                "semantic_event_id": "event-1",
                "decision": "render",
                "recipe_id": "MQE-01",
                "output_window": {"start_seconds": 1.0, "end_seconds": 4.0},
                "approved_visible_copy": ["核心关系"],
                "target_binding_ids": [],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.recipe = load_recipe_registry(DEFAULT_RECIPE_REGISTRY)["recipes"][0]
        self.snapshots: dict[str, Path] = {}
        for index, phase in enumerate(("entrance", "mid", "pre_exit", "post_exit")):
            path = self.root / f"{phase}.png"
            Image.new("RGB", (640, 360), (240 - index, 245, 250)).save(path)
            self.snapshots[phase] = path
        self.renderer_export = self.root / "renderer-export.json"
        self.strict_artifact = self.root / "strict-check.json"
        self.animation_artifact = self.root / "animation-map.json"
        self.parity = self.root / "preview-render-parity.json"
        self.parity.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        self._write_renderer_export()
        self._write_tool_artifacts()
        self.receipt = self._receipt()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_tool_runner_resolves_windows_cmd_shim(self) -> None:
        with (
            patch(
                "build_keyframe_receipts.shutil.which",
                return_value="C:/tools/npx.CMD",
            ),
            patch(
                "build_keyframe_receipts.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""),
            ) as run,
        ):
            result = _default_runner(
                ["npx", "hyperframes", "check", ".", "--json"],
                self.project_dir,
                10,
            )

        self.assertEqual(result, (0, "{}", ""))
        self.assertEqual(run.call_args.args[0][0], "C:/tools/npx.CMD")

    def _phase(self, phase: str, timestamp: float, *, visible: bool) -> dict:
        return {
            "phase": phase,
            "timestamp_seconds": timestamp,
            "snapshot": {
                "path": str(self.snapshots[phase].resolve()),
                "sha256": sha256_file(self.snapshots[phase]),
            },
            "visible": visible,
            "overlay_bbox": (
                {"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.2}
                if visible else {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
            ),
            "animation_phase": phase,
            "source_state_sha256": "a" * 64,
            "target_observations": [],
            "crop_status": "inside" if visible else "not_applicable",
            "caption_overlap_ratio": 0.0,
            "composite_contrast_ratio": 7.0 if visible else 0.0,
        }

    def _renderer_phases(self) -> list[dict]:
        return [{
            "phase": phase["phase"],
            "timestamp_seconds": phase["timestamp_seconds"],
            "snapshot": phase["snapshot"],
            "visible": phase["visible"],
            "overlay_bbox": phase["overlay_bbox"],
            "animation_phase": phase["animation_phase"],
            "source_state_sha256": phase["source_state_sha256"],
            "target_observations": phase["target_observations"],
            "connectors": [],
            "crop_status": phase["crop_status"],
            "caption_overlap_ratio": phase["caption_overlap_ratio"],
            "composite_contrast_ratio": phase["composite_contrast_ratio"],
        } for phase in self.receipt["phase_observations"]] if hasattr(self, "receipt") else [
            {
                "phase": name,
                "timestamp_seconds": timestamp,
                "snapshot": {
                    "path": str(self.snapshots[name].resolve()),
                    "sha256": sha256_file(self.snapshots[name]),
                },
                "visible": name != "post_exit",
                "overlay_bbox": (
                    {"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.2}
                    if name != "post_exit" else
                    {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
                ),
                "animation_phase": name,
                "source_state_sha256": "a" * 64,
                "target_observations": [],
                "connectors": [],
                "crop_status": "inside" if name != "post_exit" else "not_applicable",
                "caption_overlap_ratio": 0.0,
                "composite_contrast_ratio": 7.0 if name != "post_exit" else 0.0,
            }
            for name, timestamp in (("entrance", 1.2), ("mid", 2.2), ("pre_exit", 3.8), ("post_exit", 4.1))
        ]

    def _write_renderer_export(self, *, visible_text: list[str] | None = None) -> None:
        payload = {
            "schema_version": 1,
            "producer": "hyperframes-project-runtime",
            "project_artifact": {"path": str(self.project.resolve()), "sha256": sha256_file(self.project)},
            "motion_design_contract_sha256": sha256_file(self.motion_contract),
            "source_media_sha256": sha256_file(self.source),
            "events": [{
                "event_id": "event-1",
                "recipe_id": "MQE-01",
                "animation_targets": ["#event-1-motion"],
                "visible_text": ["核心关系"] if visible_text is None else visible_text,
                "phases": self._renderer_phases(),
            }],
        }
        self.renderer_export.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _write_tool_artifacts(self) -> None:
        common = {
            "status": "pass",
            "project_artifact_sha256": sha256_file(self.project),
            "motion_design_contract_sha256": sha256_file(self.motion_contract),
            "renderer_export_sha256": sha256_file(self.renderer_export),
        }
        self.strict_artifact.write_text(json.dumps({**common, "kind": "strict_check"}), encoding="utf-8")
        self.animation_artifact.write_text(json.dumps({**common, "kind": "animation_map"}), encoding="utf-8")

    def _receipt(self) -> dict:
        phases = [
            self._phase("entrance", 1.2, visible=True),
            self._phase("mid", 2.2, visible=True),
            self._phase("pre_exit", 3.8, visible=True),
            self._phase("post_exit", 4.1, visible=False),
        ]
        return {
            "schema_version": "1.0.0",
            "receipt_id": "receipt-event-1",
            "event_id": "event-1",
            "recipe_id": "MQE-01",
            "created_at": "2026-08-11T00:00:00Z",
            "producer": "content-preserving-video-editor-keyframe-validator",
            "renderer": {"name": "hyperframes", "version": "0.1.2", "fps": 30, "width": 640, "height": 360},
            "project_artifact": {"path": str(self.project.resolve()), "sha256": sha256_file(self.project)},
            "input_hashes": {
                "motion_design_contract_sha256": sha256_file(self.motion_contract),
                "motion_recipe_sha256": recipe_sha256(self.recipe),
                "target_binding_sha256s": [],
            },
            "phase_observations": phases,
            "strict_check": {
                "command": ["npx", "hyperframes", "check", ".", "--strict", "--json"],
                "exit_code": 0,
                "artifact": {"path": str(self.strict_artifact.resolve()), "sha256": sha256_file(self.strict_artifact)},
            },
            "animation_map": {
                "command": ["npx", "hyperframes", "keyframes", ".", "--json"],
                "exit_code": 0,
                "artifact": {"path": str(self.animation_artifact.resolve()), "sha256": sha256_file(self.animation_artifact)},
            },
            "preview_render_parity_receipt": {"path": str(self.parity.resolve()), "sha256": sha256_file(self.parity)},
            "status": "pass",
        }

    def _validate(self, receipt: dict | None = None) -> list[str]:
        return validate_keyframe_receipt(
            receipt or self.receipt,
            motion_design_contract_path=self.motion_contract,
            recipe_registry_path=DEFAULT_RECIPE_REGISTRY,
            target_binding_paths=[],
            renderer_export_path=self.renderer_export,
            parity_path=self.parity,
            maximum_caption_overlap_ratio=0.0,
            minimum_composite_contrast_ratio=4.5,
            maximum_connector_error_pixels=4.0,
        )

    def test_real_four_phase_project_bound_receipt_passes(self) -> None:
        self.assertEqual(self._validate(), [])

    def test_receipt_does_not_hash_bind_the_downstream_parity_gate(self) -> None:
        receipt = deepcopy(self.receipt)
        receipt.pop("preview_render_parity_receipt")

        errors = validate_keyframe_receipt(
            receipt,
            motion_design_contract_path=self.motion_contract,
            recipe_registry_path=DEFAULT_RECIPE_REGISTRY,
            target_binding_paths=[],
            renderer_export_path=self.renderer_export,
            parity_path=None,
        )

        self.assertEqual(errors, [])

    def test_scene_bounded_target_uses_verified_active_window_for_exit(self) -> None:
        binding_path = self.root / "binding-ui.json"
        binding = {
            "binding_id": "binding-ui",
            "status": "resolved",
            "target_ids": ["application-tile"],
            "active_windows": [{"start_seconds": 1.0, "end_seconds": 2.0}],
        }
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        contract = json.loads(self.motion_contract.read_text(encoding="utf-8"))
        contract["opportunities"][0]["target_binding_ids"] = ["binding-ui"]
        self.motion_contract.write_text(json.dumps(contract), encoding="utf-8")

        self.receipt = self._receipt()
        for phase, timestamp in zip(
            self.receipt["phase_observations"], (1.1, 1.5, 1.9, 2.1), strict=True,
        ):
            phase["timestamp_seconds"] = timestamp
            phase["target_observations"] = (
                [{
                    "target_id": "application-tile",
                    "target_bbox": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1},
                    "overlay_distance_pixels": 2.0,
                }]
                if phase["phase"] != "post_exit" else []
            )
        self.receipt["input_hashes"]["motion_design_contract_sha256"] = sha256_file(
            self.motion_contract,
        )
        self.receipt["input_hashes"]["target_binding_sha256s"] = [
            sha256_file(binding_path),
        ]
        self._write_renderer_export()
        self._write_tool_artifacts()
        for key, artifact in (
            ("strict_check", self.strict_artifact),
            ("animation_map", self.animation_artifact),
        ):
            self.receipt[key]["artifact"]["sha256"] = sha256_file(artifact)

        errors = validate_keyframe_receipt(
            self.receipt,
            motion_design_contract_path=self.motion_contract,
            recipe_registry_path=DEFAULT_RECIPE_REGISTRY,
            target_binding_paths=[binding_path],
            renderer_export_path=self.renderer_export,
            parity_path=self.parity,
            maximum_caption_overlap_ratio=0.0,
            minimum_composite_contrast_ratio=4.5,
            maximum_connector_error_pixels=4.0,
        )

        self.assertEqual(errors, [])

    def test_disjoint_target_active_windows_fail_closed(self) -> None:
        start, end, errors = _verified_render_window(
            {"output_window": {"start_seconds": 1.0, "end_seconds": 4.0}},
            [{"active_windows": [
                {"start_seconds": 1.0, "end_seconds": 1.5},
                {"start_seconds": 2.0, "end_seconds": 2.5},
            ]}],
        )

        self.assertIsNone(start)
        self.assertIsNone(end)
        self.assertTrue(any("contiguous active window" in error for error in errors))

    def test_midpoint_only_or_post_exit_remnant_cannot_pass(self) -> None:
        midpoint_only = deepcopy(self.receipt)
        midpoint_only["phase_observations"] = [midpoint_only["phase_observations"][1]]
        self.assertTrue(any("phase_observations" in error for error in self._validate(midpoint_only)))

        remnant = deepcopy(self.receipt)
        remnant["phase_observations"][3]["visible"] = True
        self.assertTrue(any("post_exit" in error and "visible" in error for error in self._validate(remnant)))

    def test_clipping_caption_collision_and_low_contrast_fail(self) -> None:
        broken = deepcopy(self.receipt)
        broken["phase_observations"][1]["crop_status"] = "clipped"
        broken["phase_observations"][1]["caption_overlap_ratio"] = 0.2
        broken["phase_observations"][1]["composite_contrast_ratio"] = 2.0
        errors = self._validate(broken)
        self.assertTrue(any("clipped" in error for error in errors), errors)
        self.assertTrue(any("caption" in error for error in errors), errors)
        self.assertTrue(any("contrast" in error for error in errors), errors)

    def test_renderer_export_not_request_metadata_is_visible_copy_authority(self) -> None:
        self._write_renderer_export(visible_text=["打开"])
        self._write_tool_artifacts()
        self.receipt = self._receipt()
        errors = self._validate()
        self.assertTrue(any("renderer visible text" in error for error in errors), errors)

        self.renderer_export.unlink()
        errors = self._validate()
        self.assertTrue(any("renderer export" in error for error in errors), errors)

    def test_stale_project_contract_source_or_renderer_state_fails(self) -> None:
        (self.project_dir / "index.html").write_text("changed", encoding="utf-8")
        errors = self._validate()
        self.assertTrue(any("project" in error and "stale" in error for error in errors), errors)

        (self.project_dir / "index.html").write_text(
            "<main id='event-1'>motion</main>", encoding="utf-8",
        )
        build_manifest(self.project_dir, self.project)
        self._write_renderer_export()
        self._write_tool_artifacts()
        self.receipt = self._receipt()
        export = json.loads(self.renderer_export.read_text(encoding="utf-8"))
        export["events"][0]["phases"][1]["source_state_sha256"] = "b" * 64
        self.renderer_export.write_text(json.dumps(export), encoding="utf-8")
        self._write_tool_artifacts()
        self.receipt = self._receipt()
        errors = self._validate()
        self.assertTrue(any("source state" in error for error in errors), errors)

    def test_tool_receipts_must_bind_exact_project_and_renderer_export(self) -> None:
        strict = json.loads(self.strict_artifact.read_text(encoding="utf-8"))
        strict["project_artifact_sha256"] = "0" * 64
        self.strict_artifact.write_text(json.dumps(strict), encoding="utf-8")
        self.receipt["strict_check"]["artifact"]["sha256"] = sha256_file(self.strict_artifact)
        errors = self._validate()
        self.assertTrue(any("strict_check" in error and "project" in error for error in errors), errors)

    def test_animation_map_requires_real_hyperframes_keyframes_command(self) -> None:
        self.receipt["animation_map"]["command"] = [
            "npx", "hyperframes", "animation-map", ".", "--json",
        ]

        errors = self._validate()

        self.assertTrue(
            any("animation_map command" in error for error in errors),
            errors,
        )

    def test_builder_runs_real_command_shapes_and_writes_valid_receipt(self) -> None:
        (self.project_dir / "index.html").write_text(
            '<main data-composition-id="main" data-width="640" '
            'data-height="360" data-fps="30">motion</main>',
            encoding="utf-8",
        )
        build_manifest(self.project_dir, self.project)
        self._write_renderer_export()

        def runner(command, _cwd, _timeout):
            if "check" in command:
                payload = {"ok": True, "_meta": {"version": "0.7.106"}}
            else:
                payload = {
                    "compositions": [{
                        "composition": "index.html",
                        "tweens": [{
                            "id": "event-1-motion",
                            "target": "#event-1-motion",
                            "start": 1.1,
                            "end": 3.9,
                        }],
                    }],
                    "_meta": {"version": "0.7.106"},
                }
            return 0, json.dumps(payload), ""

        receipts = build_receipts(
            project=self.project_dir,
            motion_design_contract_path=self.motion_contract,
            renderer_project_manifest_path=self.project,
            renderer_export_path=self.renderer_export,
            target_binding_dir=self.root / "target-bindings",
            parity_path=None,
            output_dir=self.root / "receipts",
            runner=runner,
        )

        self.assertEqual([path.name for path in receipts], ["event-1.json"])
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["animation_map"]["command"],
            ["npx", "hyperframes", "keyframes", ".", "--json"],
        )
        self.assertNotIn("preview_render_parity_receipt", receipt)
        animation_artifact = json.loads(
            Path(receipt["animation_map"]["artifact"]["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(animation_artifact["event_coverage"]["event-1"], ["event-1-motion"])

    def test_builder_rejects_keyframes_that_do_not_cover_render_event(self) -> None:
        (self.project_dir / "index.html").write_text(
            '<main data-composition-id="main" data-width="640" '
            'data-height="360" data-fps="30">motion</main>',
            encoding="utf-8",
        )
        build_manifest(self.project_dir, self.project)
        self._write_renderer_export()

        def runner(command, _cwd, _timeout):
            payload = (
                {"ok": True, "_meta": {"version": "0.7.106"}}
                if "check" in command else
                {"compositions": [{"tweens": [{
                    "id": "late",
                    "target": "#event-1-motion",
                    "start": 8.0,
                    "end": 9.0,
                }]}]}
            )
            return 0, json.dumps(payload), ""

        with self.assertRaisesRegex(RuntimeError, "do not cover render event event-1"):
            build_receipts(
                project=self.project_dir,
                motion_design_contract_path=self.motion_contract,
                renderer_project_manifest_path=self.project,
                renderer_export_path=self.renderer_export,
                target_binding_dir=self.root / "target-bindings",
                parity_path=self.parity,
                output_dir=self.root / "receipts",
                runner=runner,
            )

    def test_builder_rejects_unrelated_tween_inside_render_window(self) -> None:
        (self.project_dir / "index.html").write_text(
            '<main data-composition-id="main" data-width="640" '
            'data-height="360" data-fps="30">motion</main>',
            encoding="utf-8",
        )
        build_manifest(self.project_dir, self.project)
        self._write_renderer_export()

        def runner(command, _cwd, _timeout):
            payload = (
                {"ok": True, "_meta": {"version": "0.7.106"}}
                if "check" in command else
                {"compositions": [{"tweens": [{
                    "id": "other-global-motion",
                    "target": "#unrelated-global-layer",
                    "start": 1.1,
                    "end": 3.9,
                }]}]}
            )
            return 0, json.dumps(payload), ""

        with self.assertRaisesRegex(
            RuntimeError, "do not cover render event event-1",
        ):
            build_receipts(
                project=self.project_dir,
                motion_design_contract_path=self.motion_contract,
                renderer_project_manifest_path=self.project,
                renderer_export_path=self.renderer_export,
                target_binding_dir=self.root / "target-bindings",
                parity_path=self.parity,
                output_dir=self.root / "receipts",
                runner=runner,
            )

    def test_renderer_export_schema_rejects_missing_dom_phase_measurements(self) -> None:
        payload = json.loads(self.renderer_export.read_text(encoding="utf-8"))
        del payload["events"][0]["phases"][0]["overlay_bbox"]
        errors = validate_renderer_export(
            payload,
            project_artifact=self.project,
            motion_design_contract_path=self.motion_contract,
        )
        self.assertTrue(any("overlay_bbox" in error for error in errors), errors)

    def test_renderer_export_requires_event_owned_animation_targets(self) -> None:
        payload = json.loads(self.renderer_export.read_text(encoding="utf-8"))
        del payload["events"][0]["animation_targets"]

        errors = validate_renderer_export(
            payload,
            project_artifact=self.project,
            motion_design_contract_path=self.motion_contract,
        )

        self.assertTrue(
            any("animation_targets" in error for error in errors),
            errors,
        )

    def test_renderer_export_rejects_extra_unapproved_event(self) -> None:
        payload = json.loads(self.renderer_export.read_text(encoding="utf-8"))
        extra = deepcopy(payload["events"][0])
        extra["event_id"] = "unapproved-global-overlay"
        payload["events"].append(extra)

        errors = validate_renderer_export(
            payload,
            project_artifact=self.project,
            motion_design_contract_path=self.motion_contract,
        )

        self.assertTrue(
            any("event order differs" in error for error in errors),
            errors,
        )

    def test_renderer_export_requires_hash_bound_phase_snapshots(self) -> None:
        payload = json.loads(self.renderer_export.read_text(encoding="utf-8"))
        del payload["events"][0]["phases"][0]["snapshot"]

        errors = validate_renderer_export(
            payload,
            project_artifact=self.project,
            motion_design_contract_path=self.motion_contract,
        )

        self.assertTrue(any("snapshot" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
