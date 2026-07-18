from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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


if __name__ == "__main__":
    unittest.main()
