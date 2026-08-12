from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from aesthetic_qa import (  # noqa: E402
    HUMAN_ANATOMY_CRITERION,
    REQUIRED_ANATOMY_CHECKS,
    REQUIRED_CRITERIA,
    REQUIRED_PHASES,
    validate,
)
from director_contracts import sha256_file  # noqa: E402


def structure(name: str) -> dict:
    return {
        "dom_structure": name + "-dom",
        "information_hierarchy": name + "-hierarchy",
        "layout_archetype": name,
        "animation_choreography": name + "-motion",
        "use_case": name + "-case",
    }


class AestheticQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        events = [{"id": f"e{i}", "visual_structure": structure(f"s{i}")} for i in range(4)]
        self.storyboard = {"events": events}
        snapshots = {}
        for event in events:
            snapshots[event["id"]] = {}
            for phase in REQUIRED_PHASES:
                path = root / f"{event['id']}-{phase}.png"
                Image.new("RGB", (320, 180), "white").save(path)
                snapshots[event["id"]][phase] = str(path)
        self.review = {
            "verdict": "pass",
            "reviewed_event_ids": [event["id"] for event in events],
            "criteria": {name: {"status": "pass", "evidence": ["review-note"]}
                         for name in REQUIRED_CRITERIA},
            "technical_qa": {name: {"status": "pass"}
                             for name in ("hyperframes_check", "caption_sync", "overlap", "overflow", "decode")},
            "snapshots": snapshots,
            "composite_contrast": {
                event["id"]: self._composite_contrast_record(
                    Path(snapshots[event["id"]]["midpoint"]),
                    Path(snapshots[event["id"]]["post_exit"]),
                )
                for event in events
            },
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_complete_evidence_backed_review_passes(self) -> None:
        self.assertEqual(validate(self.review, self.storyboard), [])

    def test_decision_complete_review_does_not_invent_four_events(self) -> None:
        event_id = "e0"
        one_event_storyboard = {"events": [self.storyboard["events"][0]]}
        one_event_review = json.loads(json.dumps(self.review))
        one_event_review["reviewed_event_ids"] = [event_id]
        one_event_review["snapshots"] = {
            event_id: self.review["snapshots"][event_id],
        }
        one_event_review["composite_contrast"] = {
            event_id: self.review["composite_contrast"][event_id],
        }

        self.assertEqual(
            validate(one_event_review, one_event_storyboard, decision_complete=True),
            [],
        )

    def test_tests_cannot_replace_missing_aesthetic_criterion(self) -> None:
        del self.review["criteria"][REQUIRED_CRITERIA[0]]
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("missing aesthetic criterion" in error for error in errors))

    @staticmethod
    def _composite_contrast_record(composite: Path, source: Path) -> dict:
        return {
            "status": "pass",
            "method": "source_frame_alpha_composite_v1",
            "composite_evidence": {
                "path": str(composite), "sha256": sha256_file(composite),
            },
            "source_evidence": {
                "path": str(source), "sha256": sha256_file(source),
            },
            "overlay_bbox": [20, 20, 240, 100],
            "foreground_rgb": [20, 35, 45],
            "panel_rgb": [250, 252, 248],
            "panel_alpha": 0.94,
        }

    def test_composited_low_contrast_overlay_fails_even_when_internal_check_claims_pass(self) -> None:
        self.review["composite_contrast"]["e0"]["foreground_rgb"] = [245, 245, 245]

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("composited contrast" in error for error in errors), errors)

    def test_missing_motion_phase_is_blocking(self) -> None:
        del self.review["snapshots"]["e0"]["post_exit"]
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("post_exit snapshot" in error for error in errors))

    def test_keyframe_receipt_snapshots_must_be_the_exact_images_reviewed(self) -> None:
        receipt_paths = {}
        for event in self.storyboard["events"]:
            path = Path(self.temp.name) / f"{event['id']}-receipt.json"
            path.write_text(json.dumps({
                "event_id": event["id"],
                "phase_observations": [
                    {
                        "phase": phase,
                        "snapshot": {
                            "path": self.review["snapshots"][event["id"]][
                                "midpoint" if phase == "mid" else phase
                            ],
                            "sha256": sha256_file(Path(
                                self.review["snapshots"][event["id"]][
                                    "midpoint" if phase == "mid" else phase
                                ]
                            )),
                        },
                    }
                    for phase in ("entrance", "mid", "pre_exit", "post_exit")
                ],
            }), encoding="utf-8")
            receipt_paths[event["id"]] = path

        self.assertEqual(
            validate(self.review, self.storyboard, keyframe_receipt_paths=receipt_paths),
            [],
        )

        replacement = Path(self.temp.name) / "replacement.png"
        Image.new("RGB", (320, 180), "white").save(replacement)
        self.review["snapshots"]["e0"]["midpoint"] = str(replacement)
        errors = validate(
            self.review, self.storyboard, keyframe_receipt_paths=receipt_paths,
        )
        self.assertTrue(any("keyframe receipt" in error and "midpoint" in error for error in errors), errors)

    def test_corrupt_or_tiny_snapshot_cannot_fake_visual_review(self) -> None:
        corrupt = Path(self.review["snapshots"]["e0"]["midpoint"])
        corrupt.write_bytes(b"not-an-image")
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("midpoint snapshot evidence is not a decodable image" in error
                            for error in errors))

        Image.new("RGB", (8, 8), "white").save(corrupt)
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("midpoint snapshot evidence is too small" in error
                            for error in errors))

        Image.new("RGB", (128, 128), "white").save(corrupt)
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("midpoint snapshot evidence is too small" in error
                            for error in errors))

    def test_human_asset_requires_anatomy_evidence_and_checks(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        errors = validate(self.review, self.storyboard)
        self.assertIn(f"missing aesthetic criterion: {HUMAN_ANATOMY_CRITERION}", errors)

    def test_complete_human_anatomy_review_passes(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        root = Path(self.temp.name)
        evidence = []
        for index, (name, role) in enumerate((
            ("full", "full_frame"),
            ("left-hand", "left_hand"),
            ("right-hand", "right_hand"),
        )):
            path = root / f"anatomy-{name}.png"
            Image.new("RGB", (512, 512), (230 - index * 20, 240, 245)).save(path)
            evidence.append({"path": str(path), "sha256": sha256_file(path), "role": role})
        self.review["criteria"][HUMAN_ANATOMY_CRITERION] = {
            "status": "pass",
            "evidence": evidence,
            "checks": {name: True for name in REQUIRED_ANATOMY_CHECKS},
        }
        self.assertEqual(validate(self.review, self.storyboard), [])

    def test_human_anatomy_evidence_requires_unique_roles_and_images(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        path = Path(self.temp.name) / "one-view.png"
        Image.new("RGB", (512, 512), "white").save(path)
        record = {"path": str(path), "sha256": sha256_file(path), "role": "full_frame"}
        self.review["criteria"][HUMAN_ANATOMY_CRITERION] = {
            "status": "pass",
            "evidence": [record, record, record],
            "checks": {name: True for name in REQUIRED_ANATOMY_CHECKS},
        }

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("roles" in error or "unique" in error for error in errors), errors)

    def test_required_anatomy_roles_cannot_borrow_an_extra_image_for_uniqueness(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "anatomy_contract": {"person_count": 1, "arm_count": 2, "hand_count": 2}
        }
        root = Path(self.temp.name)
        paths = []
        for index, color in enumerate(("white", "gray", "black")):
            path = root / f"role-{index}.png"
            Image.new("RGB", (512, 512), color).save(path)
            paths.append(path)
        evidence = [
            {"path": str(paths[0]), "sha256": sha256_file(paths[0]), "role": "full_frame"},
            {"path": str(paths[0]), "sha256": sha256_file(paths[0]), "role": "left_hand"},
            {"path": str(paths[1]), "sha256": sha256_file(paths[1]), "role": "right_hand"},
            {"path": str(paths[2]), "sha256": sha256_file(paths[2]), "role": "extra"},
        ]
        self.review["criteria"][HUMAN_ANATOMY_CRITERION] = {
            "status": "pass", "evidence": evidence,
            "checks": {name: True for name in REQUIRED_ANATOMY_CHECKS},
        }

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("unique role-specific" in error for error in errors), errors)

    def test_structured_visual_evidence_requires_a_matching_sha256(self) -> None:
        snapshot = Path(self.review["snapshots"]["e0"]["midpoint"])
        self.review["snapshots"]["e0"]["midpoint"] = {"path": str(snapshot)}

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("requires sha256" in error for error in errors), errors)

    def test_declared_connector_contract_requires_per_event_geometry_evidence(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "connector_contract": {
                "required_connector_count": 3,
                "relations": ["source->a", "source->b", "source->c"],
            }
        }
        errors = validate(self.review, self.storyboard)
        self.assertTrue(any("connector geometry review" in error for error in errors))

    def test_complete_connector_geometry_review_passes(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "connector_contract": {
                "required_connector_count": 3,
                "relations": ["source->a", "source->b", "source->c"],
            }
        }
        evidence = Path(self.temp.name) / "e0-connectors.png"
        Image.new("RGB", (320, 180), "white").save(evidence)
        self.review["connector_geometry"] = {
            "e0": {
                "status": "pass",
                "required_connector_count": 3,
                "observed_connector_count": 3,
                "all_endpoints_attached": True,
                "optically_aligned": True,
                "no_clipped_paths": True,
                "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
                "measurement_receipt": {
                    "method": "browser_dom_geometry_v1",
                    "snapshot_sha256": sha256_file(evidence),
                    "canvas": {"width": 320, "height": 180},
                    "maximum_endpoint_distance_px": 6,
                    "relations": [
                        {
                            "relation": f"source->{target}",
                            "attachment_edge": "right-to-left",
                            "from_bbox": [20, 40 + index * 35, 40, 20],
                            "to_bbox": [200, 40 + index * 35, 50, 20],
                            "path_start": [60, 50 + index * 35],
                            "path_end": [200, 50 + index * 35],
                            "clipped": False,
                        }
                        for index, target in enumerate(("a", "b", "c"))
                    ],
                },
            }
        }
        self.assertEqual(validate(self.review, self.storyboard), [])

    def test_connector_boolean_claims_without_replayable_measurements_fail(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "connector_contract": {
                "required_connector_count": 1,
                "relations": ["source->target"],
            }
        }
        evidence = Path(self.temp.name) / "e0-connectors.png"
        Image.new("RGB", (320, 180), "white").save(evidence)
        self.review["connector_geometry"] = {"e0": {
            "status": "pass", "required_connector_count": 1,
            "observed_connector_count": 1, "all_endpoints_attached": True,
            "optically_aligned": True, "no_clipped_paths": True,
            "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
        }}

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("measurement receipt" in error for error in errors), errors)

    def test_connector_measurement_rejects_non_finite_canvas(self) -> None:
        self.storyboard["events"][0]["geometry_contract"] = {
            "connector_contract": {
                "required_connector_count": 1,
                "relations": ["source->target"],
            }
        }
        evidence = Path(self.temp.name) / "e0-connectors-nan.png"
        Image.new("RGB", (320, 180), "white").save(evidence)
        self.review["connector_geometry"] = {"e0": {
            "status": "pass", "required_connector_count": 1,
            "observed_connector_count": 1, "all_endpoints_attached": True,
            "optically_aligned": True, "no_clipped_paths": True,
            "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
            "measurement_receipt": {
                "method": "browser_dom_geometry_v1",
                "snapshot_sha256": sha256_file(evidence),
                "canvas": {"width": float("nan"), "height": 180},
                "maximum_endpoint_distance_px": 6,
                "relations": [{
                    "relation": "source->target", "attachment_edge": "right-to-left",
                    "from_bbox": [20, 40, 40, 20], "to_bbox": [200, 40, 50, 20],
                    "path_start": [60, 50], "path_end": [200, 50], "clipped": False,
                }],
            },
        }}

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("canvas or tolerance is invalid" in error for error in errors), errors)

    def _add_target_region_contract(self, colors: tuple[str, str, str]) -> None:
        root = Path(self.temp.name)
        source_state_evidence = []
        for phase, timestamp, color in zip(
            ("entrance", "midpoint", "pre_exit"), (1.2, 2.0, 2.8), colors,
        ):
            path = root / f"e0-source-{phase}.png"
            Image.new("RGB", (640, 360), color).save(path)
            source_state_evidence.append({
                "phase": phase,
                "timestamp_seconds": timestamp,
                "path": str(path),
                "sha256": sha256_file(path),
            })
        self.storyboard["events"][0]["visual_structure"]["layout_archetype"] = (
            "source-ui-highlight-overlay"
        )
        self.storyboard["events"][0]["geometry_contract"] = {
            "target_region_contract": {
                "tracking_mode": "scene_bounded",
                "active_selector": "#e0 .source-target",
                "required_target_count": 1,
                "target_ids": ["primary-chart"],
                "minimum_useful_content_ratio": 0.35,
                "maximum_static_state_delta": 0.12,
                "active_output_start": 1.0,
                "active_output_end": 3.0,
                "active_source_start": 1.0,
                "active_source_end": 3.0,
                "source_state_evidence": source_state_evidence,
            }
        }

    def test_target_bound_visual_requires_per_event_region_review(self) -> None:
        self._add_target_region_contract(("white", "white", "white"))

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("target region review" in error for error in errors), errors)

    def test_static_geometry_cannot_span_a_source_state_change(self) -> None:
        self._add_target_region_contract(("white", "black", "white"))
        evidence = Path(self.temp.name) / "e0-target-review.png"
        Image.new("RGB", (640, 360), "white").save(evidence)
        self.review["target_region_geometry"] = {
            "e0": {
                "status": "pass",
                "tracking_mode": "scene_bounded",
                "required_target_count": 1,
                "observed_target_count": 1,
                "all_targets_contain_source_content": True,
                "no_empty_highlight_regions": True,
                "no_orphan_geometry": True,
                "event_window_matches_visible_source_state": True,
                "minimum_observed_useful_content_ratio": 0.6,
                "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
                "measurement_receipt": self._target_measurement(evidence),
            }
        }

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("source-state change" in error for error in errors), errors)

    def test_complete_stable_target_region_review_passes(self) -> None:
        self._add_target_region_contract(("white", "white", "white"))
        evidence = Path(self.temp.name) / "e0-target-review.png"
        Image.new("RGB", (640, 360), "white").save(evidence)
        self.review["target_region_geometry"] = {
            "e0": {
                "status": "pass",
                "tracking_mode": "scene_bounded",
                "required_target_count": 1,
                "observed_target_count": 1,
                "all_targets_contain_source_content": True,
                "no_empty_highlight_regions": True,
                "no_orphan_geometry": True,
                "event_window_matches_visible_source_state": True,
                "minimum_observed_useful_content_ratio": 0.6,
                "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
                "measurement_receipt": self._target_measurement(evidence),
            }
        }

        self.assertEqual(validate(self.review, self.storyboard), [])

    def test_malformed_target_region_counts_return_errors_instead_of_crashing(self) -> None:
        self._add_target_region_contract(("white", "white", "white"))
        evidence = Path(self.temp.name) / "e0-target-review.png"
        Image.new("RGB", (640, 360), "white").save(evidence)
        self.review["target_region_geometry"] = {
            "e0": {
                "status": "pass",
                "tracking_mode": "scene_bounded",
                "required_target_count": "not-a-number",
                "observed_target_count": None,
                "all_targets_contain_source_content": True,
                "no_empty_highlight_regions": True,
                "no_orphan_geometry": True,
                "event_window_matches_visible_source_state": True,
                "minimum_observed_useful_content_ratio": 0.6,
                "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
                "measurement_receipt": self._target_measurement(evidence),
            }
        }

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("target count" in error for error in errors), errors)

    @staticmethod
    def _target_measurement(evidence: Path) -> dict:
        return {
            "method": "browser_dom_geometry_v1",
            "snapshot_sha256": sha256_file(evidence),
            "canvas": {"width": 640, "height": 360},
            "active_selector": "#e0 .source-target",
            "measured_at_phase": "midpoint",
            "targets": [{
                "target_id": "primary-chart",
                "overlay_bbox": [80, 60, 300, 180],
                "useful_content_bbox": [80, 60, 300, 108],
            }],
        }

    def test_target_region_self_report_cannot_hide_an_empty_measured_box(self) -> None:
        self._add_target_region_contract(("white", "white", "white"))
        evidence = Path(self.temp.name) / "e0-empty-target.png"
        Image.new("RGB", (640, 360), "white").save(evidence)
        measurement = self._target_measurement(evidence)
        measurement["targets"][0]["useful_content_bbox"] = [500, 300, 20, 20]
        self.review["target_region_geometry"] = {"e0": {
            "status": "pass", "tracking_mode": "scene_bounded",
            "required_target_count": 1, "observed_target_count": 1,
            "all_targets_contain_source_content": True,
            "no_empty_highlight_regions": True, "no_orphan_geometry": True,
            "event_window_matches_visible_source_state": True,
            "minimum_observed_useful_content_ratio": 0.99,
            "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
            "measurement_receipt": measurement,
        }}

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("measured useful-content ratio" in error for error in errors), errors)

    def test_target_region_measurement_rejects_non_finite_canvas(self) -> None:
        self._add_target_region_contract(("white", "white", "white"))
        evidence = Path(self.temp.name) / "e0-target-nan.png"
        Image.new("RGB", (640, 360), "white").save(evidence)
        measurement = self._target_measurement(evidence)
        measurement["canvas"]["width"] = float("nan")
        self.review["target_region_geometry"] = {"e0": {
            "status": "pass", "tracking_mode": "scene_bounded",
            "required_target_count": 1, "observed_target_count": 1,
            "all_targets_contain_source_content": True,
            "no_empty_highlight_regions": True, "no_orphan_geometry": True,
            "event_window_matches_visible_source_state": True,
            "minimum_observed_useful_content_ratio": 0.6,
            "evidence": {"path": str(evidence), "sha256": sha256_file(evidence)},
            "measurement_receipt": measurement,
        }}

        errors = validate(self.review, self.storyboard)

        self.assertTrue(any("canvas is invalid" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
