from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from runtime_animation_evidence import (global_interval, validate_runtime_tree,
    validate_runtime_animation_evidence, _artifact, PHASES)
from director_contracts import write_json
from renderer_project_manifest import build_manifest


class RuntimeAnimationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.events = {"event": {"start_seconds": 10, "end_seconds": 14}}
        self.tree = [{"id": "t0", "event_id": "event", "targets": ["#event > div"],
                     "duration": 2, "chain": [{"start": 10, "time_scale": 1}],
                     "start": 10, "end": 12, "gsap_start": 10, "gsap_end": 12,
                     "properties": ["opacity"], "target_ownership": ["event"]}]
        self.probes = [{"tween_id": "t0", "time": t, "direction": direction,
                        "targets": [{"selector": "#event > div", "owner": "event", "state": {"opacity": opacity}}]}
                       for direction in ("forward", "reverse") for t, opacity in ((10.4, "0.2"), (11.6, "0.8"))]

    def test_nested_parent_time_scale_transforms(self):
        self.assertEqual(global_interval(2, [{"start": 3, "time_scale": 2},
                                            {"start": 10, "time_scale": .5}]), (16, 18))

    def test_valid_real_observation_shape(self):
        self.assertEqual(validate_runtime_tree(self.tree, self.events, self.probes), [])

    def test_empty_tree_fails(self):
        self.assertTrue(validate_runtime_tree([], self.events, self.probes))

    def test_missing_target_fails(self):
        self.tree[0]["targets"] = []
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_wrong_owner_fails(self):
        self.tree[0]["target_ownership"] = ["another-event"]
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_wrong_window_fails(self):
        self.events["event"] = {"start_seconds": 20, "end_seconds": 30}
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_static_list_without_dynamic_observation_fails(self):
        for probe in self.probes:
            probe["targets"][0]["state"]["opacity"] = "1"
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_unrelated_attribute_nonce_cannot_prove_declared_opacity_motion(self):
        for index, probe in enumerate(self.probes):
            probe["targets"][0]["state"] = {"opacity": "1", "attributes": [["data-nonce", str(index % 2)]]}
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_nonfinite_visual_measurement_rejected(self):
        for probe in self.probes:
            probe["targets"][0]["state"]["opacity"] = float("nan")
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_string_nan_opacity_rejected(self):
        self.probes[0]["targets"][0]["state"]["opacity"] = "NaN"
        self.probes[2]["targets"][0]["state"]["opacity"] = "NaN"
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_forged_global_interval_fails(self):
        self.tree[0]["end"] = 13
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_reverse_seek_disagreement_fails(self):
        self.probes[-1]["targets"][0]["state"]["opacity"] = "0.7"
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_no_dynamic_properties_fails(self):
        self.tree[0]["properties"] = ["duration", "ease"]
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_wrong_probe_owner_fails(self):
        self.probes[0]["targets"][0]["owner"] = "another-event"
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_missing_reverse_fails(self):
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes[:2]))

    def test_same_time_different_states_cannot_prove_dynamic_change(self):
        for probe in self.probes:
            probe["time"] = 10.4
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_authored_arbitrary_probe_times_fail(self):
        for probe in self.probes:
            probe["time"] += .1
        self.assertTrue(validate_runtime_tree(self.tree, self.events, self.probes))

    def test_unsupported_reversed_scale_fails_closed(self):
        with self.assertRaises(ValueError):
            global_interval(2, [{"start": 3, "time_scale": -1}])

    def evidence_fixture(self, directory):
        import runtime_animation_evidence as module
        root = Path(directory) / "project"
        root.mkdir()
        (root / "index.html").write_text("<html>fixture</html>", encoding="utf-8")
        write_json(root / "storyboard.json", {})
        manifest = root / "renderer-project-manifest.json"
        build_manifest(root, manifest)
        contract = Path(directory) / "contract.json"
        write_json(contract, {"opportunities": [{"semantic_event_id": "event", "decision": "render", "output_window": self.events["event"]}]})
        snapshot = Path(directory) / "fixture.png"
        from PIL import Image
        Image.new("RGB", (2, 2)).save(snapshot)
        export = Path(directory) / "export.json"
        export_phases = [{"phase": phase, "timestamp_seconds": t, "snapshot": _artifact(snapshot)}
                         for phase, t in zip(PHASES, (10.2, 11, 13.8, 14.1))]
        write_json(export, {"project_artifact": _artifact(manifest), "motion_design_contract_sha256": _artifact(contract)["sha256"],
                            "events": [{"event_id": "event", "phases": export_phases}]})
        evidence = {"schema_version": 1, "kind": "runtime_gsap_animation_map", "producer": "playwright_live_gsap_collector",
            "project_artifact": _artifact(manifest), "motion_contract": _artifact(contract), "renderer_export": _artifact(export),
            "collector": _artifact(Path(module.__file__)), "browser": {"executable": _artifact(root / "index.html"), "version": "synthetic-unit-fixture"},
            "playwright_version": "unit-fixture", "gsap_version": "unit-fixture", "tweens": self.tree, "probes": self.probes,
            "phase_observations": [{"event_id": "event", "phase": p["phase"], "timestamp_seconds": p["timestamp_seconds"],
                "direction": direction, "export_snapshot": p["snapshot"], "snapshot": p["snapshot"],
                "targets": copy.deepcopy(self.probes[0]["targets"])} for p in export_phases for direction in ("forward", "reverse")]}
        kwargs = {"project_artifact":manifest,"motion_contract_path":contract,"renderer_export_path":export}
        return evidence, kwargs

    def test_bound_fixture_shape_and_current_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, kwargs = self.evidence_fixture(directory)
            self.assertEqual(validate_runtime_animation_evidence(evidence, **kwargs), [])

    def test_stale_collector_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, kwargs = self.evidence_fixture(directory)
            evidence["collector"]["sha256"] = "0" * 64
            self.assertIn("stale or missing collector", validate_runtime_animation_evidence(evidence, **kwargs))

    def test_stale_project_inventory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, kwargs = self.evidence_fixture(directory)
            (kwargs["project_artifact"].parent / "index.html").write_text("changed", encoding="utf-8")
            self.assertTrue(validate_runtime_animation_evidence(evidence, **kwargs))

    def test_static_cli_source_cannot_claim_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, kwargs = self.evidence_fixture(directory)
            evidence["producer"] = "authored_tween_list"
            self.assertTrue(validate_runtime_animation_evidence(evidence, **kwargs))

    def test_missing_phase_correspondence_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, kwargs = self.evidence_fixture(directory)
            evidence["phase_observations"].pop()
            self.assertTrue(validate_runtime_animation_evidence(evidence, **kwargs))

    def test_wrong_phase_time_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, kwargs = self.evidence_fixture(directory)
            evidence["phase_observations"][0]["timestamp_seconds"] += 1
            self.assertTrue(validate_runtime_animation_evidence(evidence, **kwargs))


if __name__ == "__main__":
    unittest.main()
