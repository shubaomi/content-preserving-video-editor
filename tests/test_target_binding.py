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
from select_motion_safe_zones import (  # noqa: E402
    build_adaptive_layout_constraints,
    subject_track_face_regions,
)
from target_binding import (  # noqa: E402
    resolve_for_render,
    validate_binding,
    validate_storyboard_bindings,
)
from target_binding_qa import build_report, validate_report  # noqa: E402


def bbox(x: float = 0.2, y: float = 0.2, width: float = 0.3, height: float = 0.25) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


class TargetBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.frame = self.root / "frame.png"
        self.frame.write_bytes(b"frame")
        self.binding = {
            "schema_version": "1.0.0",
            "binding_id": "binding-chart",
            "semantic_event_id": "event-chart",
            "created_at": "2026-08-11T12:00:00Z",
            "producer": "test-detector",
            "target_kind": "chart_region",
            "tracking_mode": "static",
            "target_ids": ["chart"],
            "source_window": {"start_seconds": 10.0, "end_seconds": 20.0},
            "output_window": {"start_seconds": 2.0, "end_seconds": 12.0},
            "active_windows": [{"start_seconds": 2.0, "end_seconds": 12.0}],
            "observations": [
                self._observation(10.0, "a", bbox()),
                self._observation(15.0, "a", bbox()),
                self._observation(20.0, "a", bbox()),
            ],
            "state_events": [],
            "invalidation_policy": {
                "on_state_change": "action_required",
                "on_target_lost": "exit",
                "minimum_confidence": 0.8,
            },
            "status": "resolved",
            "input_hashes": {
                "source_media_sha256": "1" * 64,
                "evidence_bundle_sha256": "2" * 64,
            },
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _observation(
        self, timestamp: float, state_character: str, box: dict | None, *,
        visible: bool = True,
    ) -> dict:
        row = {
            "timestamp_seconds": timestamp,
            "target_id": "chart",
            "source_state_sha256": state_character * 64,
            "visible": visible,
            "confidence": 0.95,
            "useful_content_ratio": 0.8,
            "evidence": {
                "path": str(self.frame.resolve()),
                "sha256": sha256_file(self.frame),
                "source": "browser_dom_geometry_v1",
            },
        }
        if box is not None:
            row["bbox"] = box
        return row

    def test_static_binding_requires_equivalent_state_and_geometry(self) -> None:
        self.assertEqual(validate_binding(self.binding, require_resolved=True), [])

        changed_state = deepcopy(self.binding)
        changed_state["observations"][1]["source_state_sha256"] = "b" * 64
        self.assertTrue(any(
            "static" in error and "state" in error
            for error in validate_binding(changed_state, require_resolved=True)
        ))

        moved = deepcopy(self.binding)
        moved["observations"][1]["bbox"]["x"] = 0.35
        self.assertTrue(any(
            "static" in error and "geometry" in error
            for error in validate_binding(moved, require_resolved=True)
        ))

    def test_every_material_state_change_invalidates_static_binding(self) -> None:
        for kind in ("scene", "route", "modal", "scroll", "zoom", "layout", "visibility", "rotation"):
            with self.subTest(kind=kind):
                binding = deepcopy(self.binding)
                binding["state_events"] = [{
                    "timestamp_seconds": 15.0,
                    "kind": kind,
                    "before_state_sha256": "a" * 64,
                    "after_state_sha256": "b" * 64,
                }]
                errors = validate_binding(binding, require_resolved=True)
                self.assertTrue(any("static" in error and kind in error for error in errors), errors)

    def test_scene_bounded_binding_exits_before_mapped_state_boundary(self) -> None:
        binding = deepcopy(self.binding)
        binding["tracking_mode"] = "scene_bounded"
        binding["state_events"] = [{
            "timestamp_seconds": 15.0,
            "kind": "modal",
            "before_state_sha256": "a" * 64,
            "after_state_sha256": "b" * 64,
        }]
        binding["active_windows"] = [{"start_seconds": 2.0, "end_seconds": 7.0}]
        binding["observations"] = binding["observations"][:2]
        self.assertEqual(validate_binding(binding, require_resolved=True), [])

        binding["active_windows"][0]["end_seconds"] = 8.0
        errors = validate_binding(binding, require_resolved=True)
        self.assertTrue(any("scene_bounded" in error and "boundary" in error for error in errors), errors)

    def test_keyframed_binding_covers_both_sides_of_every_state_change(self) -> None:
        binding = deepcopy(self.binding)
        binding["tracking_mode"] = "keyframed"
        binding["invalidation_policy"]["on_state_change"] = "rebind"
        binding["state_events"] = [{
            "timestamp_seconds": 15.0,
            "kind": "scroll",
            "before_state_sha256": "a" * 64,
            "after_state_sha256": "b" * 64,
        }]
        binding["observations"] = [
            self._observation(10.0, "a", bbox()),
            self._observation(14.9, "a", bbox()),
            self._observation(15.1, "b", bbox(0.25, 0.3)),
            self._observation(20.0, "b", bbox(0.25, 0.3)),
        ]
        self.assertEqual(validate_binding(binding, require_resolved=True), [])

        binding["observations"] = [row for row in binding["observations"] if row["timestamp_seconds"] <= 15.0]
        errors = validate_binding(binding, require_resolved=True)
        self.assertTrue(any("keyframed" in error and "after" in error for error in errors), errors)

    def test_lost_target_omits_bbox_and_cannot_hold_last_geometry(self) -> None:
        binding = deepcopy(self.binding)
        binding["tracking_mode"] = "keyframed"
        binding["observations"] = [
            self._observation(10.0, "a", bbox()),
            self._observation(15.9, "a", bbox()),
            self._observation(16.0, "b", None, visible=False),
        ]
        binding["active_windows"] = [{"start_seconds": 2.0, "end_seconds": 8.0}]
        self.assertEqual(validate_binding(binding, require_resolved=True), [])

        stale = deepcopy(binding)
        stale["active_windows"][0]["end_seconds"] = 10.0
        errors = validate_binding(stale, require_resolved=True)
        self.assertTrue(any("lost target" in error and "active window" in error for error in errors), errors)

        invented = deepcopy(binding)
        invented["observations"][-1]["bbox"] = bbox()
        errors = validate_binding(invented, require_resolved=True)
        self.assertTrue(any("lost" in error and "omit bbox" in error for error in errors), errors)

    def test_missing_or_unresolved_binding_uses_declared_fallback_not_guessed_coordinates(self) -> None:
        unresolved = deepcopy(self.binding)
        unresolved["status"] = "unresolved"
        unresolved["invalidation_policy"].update({
            "on_target_lost": "fallback", "fallback_recipe_id": "MQE-01-fallback",
        })
        self.assertEqual(resolve_for_render(unresolved)["action"], "fallback")
        self.assertEqual(resolve_for_render(unresolved)["fallback_recipe_id"], "MQE-01-fallback")

        del unresolved["invalidation_policy"]["fallback_recipe_id"]
        resolution = resolve_for_render(unresolved)
        self.assertEqual(resolution["action"], "action_required")
        self.assertNotIn("bbox", resolution)

    def test_binding_rejects_hash_drift_and_bbox_outside_canvas(self) -> None:
        drift = deepcopy(self.binding)
        drift["observations"][0]["evidence"]["sha256"] = "f" * 64
        self.assertTrue(any("evidence hash" in error for error in validate_binding(drift)))

        outside = deepcopy(self.binding)
        outside["observations"][0]["bbox"] = bbox(0.9, 0.2, 0.2, 0.2)
        self.assertTrue(any("canvas" in error for error in validate_binding(outside)))

    def test_connector_and_target_geometry_must_pass_every_review_phase(self) -> None:
        binding_path = self.root / "binding.json"
        binding_path.write_text(json.dumps(self.binding), encoding="utf-8")
        phases = []
        for phase in ("entrance", "mid_hold", "pre_exit"):
            target = bbox()
            phases.append({
                "phase": phase,
                "timestamp_seconds": {"entrance": 2.2, "mid_hold": 7.0, "pre_exit": 11.8}[phase],
                "targets": [{
                    "target_id": "chart", "expected_bbox": target,
                    "overlay_bbox": target, "visible": True,
                    "clipped": False, "offscreen": False, "caption_collision": False,
                }],
                "connectors": [{
                    "from_target_id": "chart", "to_target_id": "chart",
                    "attachment_edge": "right-to-left",
                    "from_endpoint": {"x": 0.5, "y": 0.325},
                    "from_attachment": {"x": 0.5, "y": 0.325},
                    "to_endpoint": {"x": 0.2, "y": 0.325},
                    "to_attachment": {"x": 0.2, "y": 0.325},
                }],
            })
        phases.append({
            "phase": "post_exit", "timestamp_seconds": 12.0,
            "targets": [{"target_id": "chart", "visible": False}], "connectors": [],
        })
        report = build_report(
            binding_path=binding_path, phase_observations=phases,
            endpoint_tolerance=0.02, bbox_tolerance=0.02,
        )
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(validate_report(report, binding_path), [])

        broken = deepcopy(phases)
        broken[1]["connectors"][0]["from_endpoint"]["x"] = 0.4
        failed = build_report(
            binding_path=binding_path, phase_observations=broken,
            endpoint_tolerance=0.02, bbox_tolerance=0.02,
        )
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(any("connector" in row["code"] for row in failed["findings"]))

        forged = deepcopy(phases)
        forged[1]["targets"][0]["overlay_bbox"] = bbox(0.6, 0.2, 0.2, 0.2)
        forged[1]["targets"][0]["expected_bbox"] = bbox(0.6, 0.2, 0.2, 0.2)
        forged_report = build_report(
            binding_path=binding_path, phase_observations=forged,
            endpoint_tolerance=0.02, bbox_tolerance=0.02,
        )
        self.assertEqual(forged_report["status"], "failed")
        self.assertTrue(any("bbox" in row["code"] for row in forged_report["findings"]))

    def test_landscape_ui_and_portrait_person_layout_contracts_are_distinct(self) -> None:
        landscape = build_adaptive_layout_constraints({
            "display": {"orientation": "landscape", "width": 1920, "height": 1080,
                        "rotation_degrees": 0},
            "protected_regions": {
                "critical_ui": [{"bbox": bbox(0.0, 0.0, 1.0, 0.12)}],
                "captions": [{"bbox": bbox(0.05, 0.82, 0.9, 0.12)}],
                "status": "reviewed",
            },
        }, content_type="screen_tutorial", identity_mode="generic")
        portrait = build_adaptive_layout_constraints({
            "display": {"orientation": "portrait", "width": 1080, "height": 1920,
                        "rotation_degrees": 90},
            "protected_regions": {
                "faces": [{"bbox": bbox(0.25, 0.12, 0.5, 0.35)}],
                "hands": [{"bbox": bbox(0.15, 0.48, 0.7, 0.3)}],
                "captions": [{"bbox": bbox(0.05, 0.78, 0.9, 0.14)}],
                "status": "reviewed",
            },
        }, content_type="talking_head", identity_mode="third_party")

        self.assertEqual(landscape["layout_family"], "landscape_ui_safe")
        self.assertEqual(portrait["layout_family"], "portrait_person_safe")
        self.assertNotEqual(landscape["constraints"], portrait["constraints"])
        self.assertIn("hands", portrait["protected_region_types"])
        self.assertEqual(portrait["identity_mode"], "third_party")

    def test_portrait_person_without_face_hand_evidence_fails_safe(self) -> None:
        contract = build_adaptive_layout_constraints({
            "display": {"orientation": "portrait", "width": 1080, "height": 1920,
                        "rotation_degrees": 0},
            "protected_regions": {"faces": [], "hands": [], "captions": [],
                                  "status": "candidate_only"},
        }, content_type="talking_head", identity_mode="third_party")

        self.assertEqual(contract["status"], "action_required")
        self.assertEqual(contract["fallback"], "caption_only")
        self.assertFalse(contract["guessed_coordinates_allowed"])

    def test_portrait_talking_head_preset_uses_portrait_person_layout(self) -> None:
        contract = build_adaptive_layout_constraints({
            "display": {"orientation": "portrait", "width": 544, "height": 960,
                        "rotation_degrees": 0},
            "protected_regions": {
                "faces": [{"bbox": bbox(0.2, 0.08, 0.6, 0.34)}],
                "hands": [{"bbox": bbox(0.1, 0.48, 0.8, 0.24)}],
                "captions": [], "status": "reviewed",
            },
        }, content_type="portrait_talking_head", identity_mode="self")

        self.assertEqual(contract["layout_family"], "portrait_person_safe")
        self.assertEqual(contract["status"], "resolved")

    def test_portrait_person_accepts_hash_bound_observed_absent_hands(self) -> None:
        contract = build_adaptive_layout_constraints({
            "display": {"orientation": "portrait", "width": 544, "height": 960,
                        "rotation_degrees": 0},
            "protected_regions": {
                "faces": [{"bbox": bbox(0.2, 0.08, 0.6, 0.34)}],
                "hands": [],
                "captions": [],
                "observations": {
                    "hands": {
                        "status": "observed_absent",
                        "evidence_sha256": ["a" * 64, "b" * 64],
                    },
                },
                "status": "reviewed",
            },
        }, content_type="portrait_talking_head", identity_mode="self")

        self.assertEqual(contract["status"], "resolved")
        self.assertEqual(
            contract["constraints"]["protected_region_observations"]["hands"]["status"],
            "observed_absent",
        )

    def test_portrait_person_rejects_unbound_observed_absent_hands(self) -> None:
        contract = build_adaptive_layout_constraints({
            "display": {"orientation": "portrait", "width": 544, "height": 960,
                        "rotation_degrees": 0},
            "protected_regions": {
                "faces": [{"bbox": bbox(0.2, 0.08, 0.6, 0.34)}],
                "hands": [],
                "captions": [],
                "observations": {"hands": {"status": "observed_absent"}},
                "status": "reviewed",
            },
        }, content_type="portrait_talking_head", identity_mode="self")

        self.assertEqual(contract["status"], "action_required")
        self.assertIn("hands", contract["missing_evidence"])

    def test_subject_track_faces_are_normalized_and_hash_bound(self) -> None:
        regions = subject_track_face_regions({
            "tracking": {
                "detector": "opencv_haar_frontalface",
                "status": "tracked",
                "series": [
                    {"time": 1.2, "status": "tracked",
                     "face": {"x": 0.2, "y": 0.1, "w": 0.5, "h": 0.3}},
                    {"time": 1.6, "status": "fallback_center", "face": None},
                ],
            },
        }, report_path=self.root / "subject-track.json", report_sha256="c" * 64)

        self.assertEqual(len(regions), 1)
        self.assertEqual(
            regions[0]["bbox"],
            {"x": 0.2, "y": 0.1, "width": 0.5, "height": 0.3},
        )
        self.assertEqual(regions[0]["timestamp_seconds"], 1.2)
        self.assertEqual(regions[0]["evidence_sha256"], "c" * 64)

    def test_storyboard_source_bound_event_requires_exact_resolved_binding(self) -> None:
        binding_dir = self.root / "bindings"
        binding_dir.mkdir()
        binding_path = binding_dir / "binding-chart.json"
        binding_path.write_text(json.dumps(self.binding), encoding="utf-8")
        storyboard = {"events": [{
            "id": "render-chart",
            "semantic_event_id": "event-chart",
            "source_start": 10.0,
            "source_end": 20.0,
            "output_start": 2.0,
            "output_end": 12.0,
            "target_binding_required": True,
            "target_binding_ids": ["binding-chart"],
        }]}

        self.assertEqual(validate_storyboard_bindings(storyboard, binding_dir), [])

        missing = deepcopy(storyboard)
        missing["events"][0]["target_binding_ids"] = []
        self.assertTrue(any(
            "requires at least one target binding" in error
            for error in validate_storyboard_bindings(missing, binding_dir)
        ))

        mismatched = deepcopy(self.binding)
        mismatched["semantic_event_id"] = "other-event"
        binding_path.write_text(json.dumps(mismatched), encoding="utf-8")
        self.assertTrue(any(
            "semantic event" in error
            for error in validate_storyboard_bindings(storyboard, binding_dir)
        ))

    def test_storyboard_targetless_event_must_explicitly_declare_no_binding(self) -> None:
        targetless = {"events": [{
            "id": "chapter-title",
            "semantic_event_id": "chapter-title",
            "source_start": 1.0,
            "source_end": 2.0,
            "output_start": 1.0,
            "output_end": 2.0,
            "target_binding_required": False,
            "target_binding_ids": [],
        }]}
        self.assertEqual(validate_storyboard_bindings(targetless, self.root / "bindings"), [])

        undeclared = deepcopy(targetless)
        del undeclared["events"][0]["target_binding_required"]
        self.assertTrue(any(
            "target_binding_required" in error
            for error in validate_storyboard_bindings(undeclared, self.root / "bindings")
        ))

        falsely_targetless = deepcopy(targetless)
        falsely_targetless["events"][0]["form"] = "focus"
        self.assertTrue(any(
            "source-bound" in error
            for error in validate_storyboard_bindings(falsely_targetless, self.root / "bindings")
        ))

    def test_target_binding_qa_report_cannot_remove_recomputed_findings(self) -> None:
        binding_path = self.root / "binding.json"
        binding_path.write_text(json.dumps(self.binding), encoding="utf-8")
        timestamps = (2.1, 7.0, 11.8, 12.0)
        phases = [
            {"phase": phase, "timestamp_seconds": timestamps[index],
             "targets": ([{"target_id": "chart", "visible": False}]
                         if phase == "post_exit" else [{
                             "target_id": "chart", "visible": True,
                             "expected_bbox": bbox(), "overlay_bbox": bbox(0.6, 0.2),
                             "clipped": False, "offscreen": False,
                             "caption_collision": False,
                         }]), "connectors": []}
            for index, phase in enumerate(("entrance", "mid_hold", "pre_exit", "post_exit"))
        ]
        report = build_report(
            binding_path=binding_path, phase_observations=phases,
            endpoint_tolerance=0.02, bbox_tolerance=0.02,
        )
        self.assertEqual(report["status"], "failed")

        tampered = deepcopy(report)
        tampered["findings"] = []
        tampered["status"] = "pass"
        self.assertTrue(any(
            "recomputed" in error for error in validate_report(tampered, binding_path)
        ))


if __name__ == "__main__":
    unittest.main()
