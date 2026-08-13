from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from platform_occlusion_gate import evaluate_geometry  # noqa: E402


def product_authority(
    *, event_id: str = "product-demo-1", semantic_id: str = "semantic-product-1",
    start: float = 0.0, end: float = 0.9,
) -> tuple[dict, dict]:
    return ({"events": [{
        "id": semantic_id, "decision": "render", "output_start": start, "output_end": end,
        "occlusion_focus": {"primary": "product", "status": "approved"},
    }]}, {"events": [{
        "id": event_id, "semantic_event_id": semantic_id,
        "output_start": start, "output_end": end,
    }]})


class PlatformOcclusionGateTests(unittest.TestCase):
    def test_safe_geometry_passes_both_platforms(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"landscape": [{"id": "controls", "x0": .9, "y0": 0, "x1": 1, "y1": 1}]},
            "wechat_channels": {"landscape": [{"id": "controls", "x0": .9, "y0": 0,
                                                  "x1": 1, "y1": 1}]},
        }}
        report = evaluate_geometry({"orientation": "landscape", "events": [{
            "event_id": "e1", "elements": [{"id": "card", "x0": .1, "y0": .1,
                                                "x1": .3, "y1": .3, "z": 2, "opacity": .9}],
            "protected_zones": [{"id": "face", "x0": .6, "y0": .2, "x1": .8, "y1": .6}],
            "cropped": False, "caption_occluded": False,
        }]}, templates)
        self.assertTrue(report["passed"])

    def test_platform_and_face_collisions_are_blocking(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": [{"id": "buttons", "x0": .8, "y0": .2, "x1": 1, "y1": .9}]},
            "wechat_channels": {"portrait": []},
        }}
        report = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "e1", "elements": [{"id": "card", "x0": .75, "y0": .3,
                                                "x1": .95, "y1": .7, "z": 2, "opacity": 1}],
            "protected_zones": [{"id": "face", "x0": .7, "y0": .25, "x1": .9, "y1": .65}],
            "cropped": False, "caption_occluded": False,
        }]}, templates)
        codes = {row["code"] for row in report["findings"]}
        self.assertIn("platform_ui_collision", codes)
        self.assertIn("protected_region_collision", codes)
        self.assertFalse(report["passed"])

    def test_product_focus_allows_one_bounded_soft_region_near_the_product(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        semantic, storyboard = product_authority()
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "product-demo-1",
            "semantic_focus": {
                "primary": "product", "status": "approved",
                "evidence_event_id": "semantic-product-1",
            },
            "occlusion_policy": {
                "mode": "semantic_priority", "intent": "product_emphasis",
                "maximum_soft_overlap_ratio": 0.18,
                "maximum_soft_occlusion_seconds": 1.2,
                "event_duration_seconds": 0.9,
                "maximum_product_gap": 0.12,
                "clean_exit": True,
            },
            "phases": {"post_exit": {"elements": []}},
            "elements": [{
                "id": "product-callout", "x0": .38, "y0": .47, "x1": .54, "y1": .54,
                "z": 3, "opacity": 1, "target_region_id": "product",
            }],
            "protected_zones": [
                {"id": "face", "kind": "face", "x0": .48, "y0": .20, "x1": .72, "y1": .47},
                {"id": "hands", "kind": "hands", "x0": .52, "y0": .46, "x1": .68, "y1": .66},
                {"id": "product", "kind": "product", "x0": .62, "y0": .45, "x1": .82, "y1": .66},
                {"id": "captions", "kind": "captions", "x0": .08, "y0": .78, "x1": .92, "y1": .91},
            ],
            "cropped": False, "caption_occluded": False,
        }]}, templates, semantic, storyboard)
        self.assertTrue(result["passed"], result["findings"])

    def test_product_focus_never_weakens_product_or_caption_protection(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        semantic, storyboard = product_authority(end=.8)
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "product-demo-1",
            "semantic_focus": {"primary": "product", "status": "approved",
                               "evidence_event_id": "semantic-product-1"},
            "occlusion_policy": {"mode": "semantic_priority", "intent": "product_emphasis",
                                 "maximum_soft_overlap_ratio": .18,
                                 "maximum_soft_occlusion_seconds": 1.2,
                                 "event_duration_seconds": .8, "maximum_product_gap": .12,
                                 "clean_exit": True},
            "phases": {"post_exit": {"elements": []}},
            "elements": [{"id": "card", "x0": .4, "y0": .45, "x1": .85, "y1": .88,
                          "z": 3, "opacity": 1, "target_region_id": "product"}],
            "protected_zones": [
                {"id": "product", "kind": "product", "x0": .6, "y0": .45, "x1": .82, "y1": .65},
                {"id": "captions", "kind": "captions", "x0": .08, "y0": .78, "x1": .92, "y1": .91},
            ],
            "cropped": False, "caption_occluded": True,
        }]}, templates, semantic, storyboard)
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("protected_region_collision", codes)
        self.assertIn("caption_occlusion", codes)
        self.assertFalse(result["passed"])

    def test_soft_occlusion_rejects_made_up_authority_and_two_distinct_hands(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        semantic, storyboard = product_authority()
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "product-demo-1",
            "semantic_focus": {"primary": "product", "status": "approved",
                               "evidence_event_id": "made-up"},
            "occlusion_policy": {"mode": "semantic_priority", "intent": "product_emphasis",
                                 "maximum_soft_overlap_ratio": .18,
                                 "maximum_soft_occlusion_seconds": 1.2,
                                 "maximum_product_gap": .12},
            "phases": {"post_exit": {"elements": []}},
            "elements": [{"id": "callout", "x0": .40, "y0": .40, "x1": .60, "y1": .60,
                          "target_region_id": "product"}],
            "protected_zones": [
                {"id": "hand-left", "kind": "hand", "x0": .38, "y0": .40,
                 "x1": .45, "y1": .60},
                {"id": "hand-right", "kind": "hand", "x0": .55, "y0": .40,
                 "x1": .62, "y1": .60},
                {"id": "product", "kind": "product", "x0": .62, "y0": .44,
                 "x1": .82, "y1": .66},
            ], "cropped": False, "caption_occluded": False,
        }]}, templates, semantic, storyboard)
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("soft_occlusion_authority_missing", codes)
        self.assertIn("soft_occlusion_multiple_regions", codes)
        self.assertFalse(result["passed"])

    def test_soft_occlusion_uses_authoritative_window_and_actual_post_exit_geometry(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        semantic, storyboard = product_authority(end=2.0)
        element = {"id": "callout", "x0": .40, "y0": .40, "x1": .60, "y1": .60,
                   "target_region_id": "product"}
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "product-demo-1",
            "semantic_focus": {"primary": "product", "status": "approved",
                               "evidence_event_id": "semantic-product-1"},
            "occlusion_policy": {"mode": "semantic_priority", "intent": "product_emphasis",
                                 "maximum_soft_overlap_ratio": .18,
                                 "maximum_soft_occlusion_seconds": 1.2,
                                 "event_duration_seconds": .1,
                                 "maximum_product_gap": .12, "clean_exit": True},
            "phases": {"post_exit": {"elements": [dict(element)]}},
            "elements": [element],
            "protected_zones": [
                {"id": "hand-left", "kind": "hand", "x0": .38, "y0": .40,
                 "x1": .45, "y1": .60},
                {"id": "product", "kind": "product", "x0": .62, "y0": .44,
                 "x1": .82, "y1": .66},
            ], "cropped": False, "caption_occluded": False,
        }]}, templates, semantic, storyboard)
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("soft_occlusion_duration_exceeded", codes)
        self.assertIn("soft_occlusion_clean_exit_missing", codes)
        self.assertFalse(result["passed"])

    def test_post_exit_renaming_cannot_hide_geometry_and_region_ids_must_be_unique(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        semantic, storyboard = product_authority()
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "product-demo-1",
            "semantic_focus": {"primary": "product", "status": "approved",
                               "evidence_event_id": "semantic-product-1"},
            "occlusion_policy": {"mode": "semantic_priority", "intent": "product_emphasis",
                                 "maximum_soft_overlap_ratio": .18,
                                 "maximum_soft_occlusion_seconds": 1.2,
                                 "maximum_product_gap": .12},
            "elements": [{"id": "callout", "x0": .40, "y0": .40, "x1": .60, "y1": .60,
                          "target_region_id": "product"}],
            "phases": {"post_exit": {"elements": [{
                "id": "renamed-callout", "x0": .40, "y0": .40, "x1": .60, "y1": .60,
            }]}},
            "protected_zones": [
                {"id": "hand", "kind": "hand", "x0": .38, "y0": .40,
                 "x1": .45, "y1": .60},
                {"id": "hand", "kind": "hand", "x0": .55, "y0": .40,
                 "x1": .62, "y1": .60},
                {"id": "product", "kind": "product", "x0": .62, "y0": .44,
                 "x1": .82, "y1": .66},
            ], "cropped": False, "caption_occluded": False,
        }]}, templates, semantic, storyboard)
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("protected_region_id_duplicate", codes)
        self.assertIn("soft_occlusion_clean_exit_missing", codes)
        self.assertFalse(result["passed"])

    def test_soft_occlusion_requires_product_evidence_duration_and_clean_exit(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "bad-soft-occlusion",
            "semantic_focus": {"primary": "product", "status": "draft"},
            "occlusion_policy": {"mode": "semantic_priority", "intent": "product_emphasis",
                                 "maximum_soft_overlap_ratio": .18,
                                 "maximum_soft_occlusion_seconds": .5,
                                 "event_duration_seconds": 1.0,
                                 "maximum_product_gap": .12, "clean_exit": False},
            "elements": [{"id": "card", "x0": .45, "y0": .40, "x1": .67, "y1": .62,
                          "z": 3, "opacity": 1, "target_region_id": "product"}],
            "protected_zones": [
                {"id": "face", "kind": "face", "x0": .48, "y0": .2, "x1": .72, "y1": .5},
                {"id": "product", "kind": "product", "x0": .7, "y0": .48, "x1": .86, "y1": .68},
            ],
            "cropped": False, "caption_occluded": False,
        }]}, templates)
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("soft_occlusion_authority_missing", codes)
        self.assertIn("soft_occlusion_duration_exceeded", codes)
        self.assertIn("soft_occlusion_clean_exit_missing", codes)
        self.assertFalse(result["passed"])

    def test_malformed_geometry_fails_closed_without_an_exception(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        result = evaluate_geometry({"orientation": "portrait", "events": [
            "bad-event",
            {"event_id": "bad-box", "elements": [{"id": "card", "x0": float("nan")}],
             "protected_zones": [], "caption_occluded": False},
        ]}, templates)
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("geometry_event_invalid", codes)
        self.assertIn("geometry_element_invalid", codes)
        self.assertFalse(result["passed"])

    def test_authoritative_geometry_inventory_must_match_the_storyboard(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        semantic = {"events": [
            {"id": "s1", "decision": "render", "output_start": 0.0, "output_end": 1.0},
            {"id": "s2", "decision": "render", "output_start": 1.0, "output_end": 2.0},
        ]}
        storyboard = {"events": [
            {"id": "e1", "semantic_event_id": "s1", "output_start": 0.0, "output_end": 1.0},
            {"id": "e2", "semantic_event_id": "s2", "output_start": 1.0, "output_end": 2.0},
        ]}
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "e1", "elements": [], "protected_zones": [],
            "cropped": False, "caption_occluded": False,
        }]}, templates, semantic, storyboard)
        codes = {row["code"] for row in result["findings"]}
        self.assertIn("geometry_event_inventory_mismatch", codes)
        self.assertFalse(result["passed"])

        extra = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "fake", "elements": [], "protected_zones": [],
            "cropped": False, "caption_occluded": False,
        }]}, templates, semantic, storyboard)
        self.assertIn("geometry_event_inventory_mismatch", {
            row["code"] for row in extra["findings"]
        })

        omitted_from_both = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "e1", "elements": [], "protected_zones": [],
            "cropped": False, "caption_occluded": False,
        }]}, templates, semantic, {"events": [storyboard["events"][0]]})
        self.assertIn("storyboard_render_inventory_mismatch", {
            row["code"] for row in omitted_from_both["findings"]
        })
        self.assertFalse(omitted_from_both["passed"])

    def test_required_safety_flags_are_strict_booleans(self) -> None:
        templates = {"template_version": "test", "verified_on": "2026-01-01", "templates": {
            "douyin": {"portrait": []}, "wechat_channels": {"portrait": []},
        }}
        result = evaluate_geometry({"orientation": "portrait", "events": [{
            "event_id": "e1", "elements": [], "protected_zones": [],
            "cropped": "no", "caption_occluded": 0,
        }]}, templates)
        self.assertIn("geometry_event_invalid", {row["code"] for row in result["findings"]})
        self.assertFalse(result["passed"])

    def test_malformed_templates_and_layer_numbers_fail_closed(self) -> None:
        report = {"orientation": "portrait", "events": [{
            "event_id": "e1",
            "elements": [{"id": "card", "x0": .1, "y0": .1, "x1": .3, "y1": .3,
                          "z": "front", "opacity": []}],
            "protected_zones": [], "cropped": False, "caption_occluded": False,
        }]}
        for templates in ({"templates": [1]}, {"templates": {"douyin": []}}):
            with self.subTest(templates=templates):
                result = evaluate_geometry(report, templates)
                self.assertFalse(result["passed"])
                self.assertTrue(result["findings"])


if __name__ == "__main__":
    unittest.main()
