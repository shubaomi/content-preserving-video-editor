from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from preview_render_parity import validate  # noqa: E402


def parity_report(root: Path) -> dict:
    studio = root / "studio.png"
    rendered = root / "render.png"
    studio.write_bytes(b"studio")
    rendered.write_bytes(b"render")
    return {
        "schema_version": 1,
        "status": "pass",
        "tolerances": {"position_px": 4, "size_px": 4, "time_seconds": 0.05},
        "samples": [{
            "event_id": "event-1",
            "time_seconds": 12.5,
            "studio_time_seconds": 12.5,
            "render_time_seconds": 12.52,
            "studio_snapshot": str(studio),
            "render_snapshot": str(rendered),
            "studio_snapshot_sha256": sha256_file(studio),
            "render_snapshot_sha256": sha256_file(rendered),
            "animation_phase": {"studio": "midpoint", "render": "midpoint"},
            "elements": [{
                "selector": "#callout",
                "studio": {"x": 100, "y": 200, "width": 300, "height": 120, "visible": True},
                "render": {"x": 102, "y": 198, "width": 301, "height": 121, "visible": True},
            }],
            "connectors": {
                "expected_count": 2,
                "studio_count": 2,
                "render_count": 2,
                "all_endpoints_attached": True,
                "clipped": False,
            },
            "cropping": {"studio_clipped": False, "render_clipped": False},
            "caption_occlusion": {"studio": False, "render": False},
        }],
    }


class PreviewRenderParityTests(unittest.TestCase):
    def test_non_finite_or_boolean_tolerances_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for value in (True, float("nan"), float("inf"), float("-inf")):
                report = parity_report(Path(folder))
                report["tolerances"]["position_px"] = value
                with self.subTest(value=value):
                    self.assertTrue(validate(report, {"events": [{"id": "event-1"}]}))

    def test_representative_event_within_tolerance_passes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = parity_report(Path(folder))
            storyboard = {"events": [{"id": "event-1"}]}
            self.assertEqual(validate(report, storyboard), [])

    def test_geometry_outside_tolerance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = parity_report(Path(folder))
            report["samples"][0]["elements"][0]["render"]["x"] = 120
            errors = validate(report, {"events": [{"id": "event-1"}]})
            self.assertTrue(any("position parity" in error for error in errors))

    def test_visibility_connector_crop_and_caption_mismatch_fail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = parity_report(Path(folder))
            sample = report["samples"][0]
            sample["elements"][0]["render"]["visible"] = False
            sample["connectors"]["render_count"] = 1
            sample["cropping"]["render_clipped"] = True
            sample["caption_occlusion"]["render"] = True
            errors = validate(report, {"events": [{"id": "event-1"}]})
            self.assertTrue(any("visibility parity" in error for error in errors))
            self.assertTrue(any("connector count" in error for error in errors))
            self.assertTrue(any("cropping" in error for error in errors))
            self.assertTrue(any("caption occlusion" in error for error in errors))

    def test_sampling_times_outside_configured_tolerance_fail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = parity_report(Path(folder))
            report["samples"][0]["render_time_seconds"] = 12.7
            errors = validate(
                report,
                {"events": [{"id": "event-1"}]},
                configured_tolerances={"position_px": 4, "size_px": 4, "time_seconds": 0.05},
            )
            self.assertTrue(any("sampling time parity" in error for error in errors))

    def test_report_cannot_relax_project_tolerances(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = parity_report(Path(folder))
            report["tolerances"]["position_px"] = 12
            errors = validate(
                report,
                {"events": [{"id": "event-1"}]},
                configured_tolerances={"position_px": 4, "size_px": 4, "time_seconds": 0.05},
            )
            self.assertTrue(any("exceeds configured position_px" in error for error in errors))

    def test_mqe_parity_binds_project_contract_source_and_all_receipt_phases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / "index.html"
            contract = root / "motion.json"
            source = root / "source.mp4"
            project.write_text("project", encoding="utf-8")
            contract.write_text("{}", encoding="utf-8")
            source.write_bytes(b"media")
            receipt = root / "event-1-keyframe.json"
            phases = []
            samples = []
            for index, (phase, timestamp) in enumerate((
                ("entrance", 1.2), ("mid", 2.0), ("pre_exit", 2.8), ("post_exit", 3.1),
            )):
                studio = root / f"studio-{phase}.png"
                rendered = root / f"render-{phase}.png"
                Image.new("RGB", (640, 360), (240 - index, 245, 250)).save(studio)
                Image.new("RGB", (640, 360), (240 - index, 245, 250)).save(rendered)
                phases.append({"phase": phase, "timestamp_seconds": timestamp})
                samples.append({
                    "event_id": "event-1", "phase": phase,
                    "time_seconds": timestamp, "studio_time_seconds": timestamp,
                    "render_time_seconds": timestamp + 0.01,
                    "studio_snapshot": str(studio), "render_snapshot": str(rendered),
                    "studio_snapshot_sha256": sha256_file(studio),
                    "render_snapshot_sha256": sha256_file(rendered),
                    "animation_phase": {"studio": phase, "render": phase},
                    "elements": [{
                        "selector": "#event-1",
                        "studio": {"x": 10, "y": 20, "width": 200, "height": 100, "visible": phase != "post_exit"},
                        "render": {"x": 11, "y": 20, "width": 200, "height": 100, "visible": phase != "post_exit"},
                    }],
                    "connectors": {"expected_count": 0, "studio_count": 0, "render_count": 0,
                                   "all_endpoints_attached": True, "clipped": False},
                    "cropping": {"studio_clipped": False, "render_clipped": False},
                    "caption_occlusion": {"studio": False, "render": False},
                    "keyframe_receipt": {"path": str(receipt), "sha256": "pending"},
                })
            receipt.write_text(json.dumps({
                "event_id": "event-1", "project_artifact": {
                    "path": str(project), "sha256": sha256_file(project),
                },
                "input_hashes": {"motion_design_contract_sha256": sha256_file(contract)},
                "phase_observations": phases,
            }), encoding="utf-8")
            for sample in samples:
                sample["keyframe_receipt"]["sha256"] = sha256_file(receipt)
            report = {
                "schema_version": 2, "status": "pass",
                "tolerances": {"position_px": 4, "size_px": 4, "time_seconds": 0.05},
                "inputs": {
                    "project_artifact": {"path": str(project), "sha256": sha256_file(project)},
                    "motion_design_contract": {"path": str(contract), "sha256": sha256_file(contract)},
                    "source_media": {"path": str(source), "sha256": sha256_file(source)},
                },
                "samples": samples,
            }

            errors = validate(
                report, {"events": [{"id": "event-1"}]},
                expected_bindings={
                    "project_artifact": project,
                    "motion_design_contract": contract,
                    "source_media": source,
                },
                keyframe_receipt_paths={"event-1": receipt},
            )

            self.assertEqual(errors, [])

    def test_mqe_parity_rejects_mid_only_stale_receipt_and_wrong_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = parity_report(root)
            project = root / "index.html"
            contract = root / "motion.json"
            source = root / "source.mp4"
            receipt = root / "receipt.json"
            for path in (project, contract, source):
                path.write_bytes(b"input")
            receipt.write_text(json.dumps({
                "event_id": "event-1",
                "project_artifact": {"path": str(project), "sha256": sha256_file(project)},
                "input_hashes": {"motion_design_contract_sha256": sha256_file(contract)},
                "phase_observations": [{"phase": "mid", "timestamp_seconds": 12.5}],
            }), encoding="utf-8")
            report["schema_version"] = 2
            report["inputs"] = {
                "project_artifact": {"path": str(project), "sha256": sha256_file(project)},
                "motion_design_contract": {"path": str(contract), "sha256": sha256_file(contract)},
                "source_media": {"path": str(source), "sha256": sha256_file(source)},
            }
            report["samples"][0]["phase"] = "mid"
            report["samples"][0]["keyframe_receipt"] = {
                "path": str(receipt), "sha256": sha256_file(receipt),
            }
            errors = validate(
                report, {"events": [{"id": "event-1"}]},
                expected_bindings={
                    "project_artifact": project, "motion_design_contract": contract,
                    "source_media": source,
                },
                keyframe_receipt_paths={"event-1": receipt},
            )
            self.assertTrue(any("four phases" in error for error in errors), errors)
            self.assertTrue(any("decodable image" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
