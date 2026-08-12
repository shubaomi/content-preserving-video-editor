from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_preview_render_parity import build_report  # noqa: E402
from director_contracts import sha256_file  # noqa: E402
from preview_render_parity import validate  # noqa: E402


class BuildPreviewRenderParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "renderer-project-manifest.json"
        self.contract = self.root / "motion-design-contract.json"
        self.source = self.root / "source.mp4"
        self.storyboard = self.root / "storyboard.json"
        self.export = self.root / "renderer-export.json"
        self.render_dir = self.root / "render"
        self.receipt_dir = self.root / "receipts"
        self.render_dir.mkdir()
        self.receipt_dir.mkdir()
        self.project.write_text("{}", encoding="utf-8")
        self.contract.write_text("{}", encoding="utf-8")
        self.source.write_bytes(b"source")
        self.storyboard.write_text(json.dumps({
            "events": [{"id": "render-event-1", "semantic_event_id": "event-1"}],
        }), encoding="utf-8")
        phases = []
        for index, (phase, timestamp) in enumerate((
            ("entrance", 1.2), ("mid", 2.0),
            ("pre_exit", 2.8), ("post_exit", 3.1),
        )):
            studio = self.root / f"studio-{phase}.png"
            rendered = self.render_dir / f"event-1-{phase}.png"
            self._image(studio, offset=0, visible=phase != "post_exit")
            self._image(rendered, offset=0, visible=phase != "post_exit")
            phases.append({
                "phase": phase,
                "timestamp_seconds": timestamp,
                "snapshot": {"path": str(studio), "sha256": sha256_file(studio)},
                "visible": phase != "post_exit",
                "overlay_bbox": (
                    {"x": 0.25, "y": 0.25, "width": 0.25, "height": 0.25}
                    if phase != "post_exit" else
                    {"x": 0, "y": 0, "width": 0, "height": 0}
                ),
                "animation_phase": phase,
                "connectors": [],
                "crop_status": "inside" if phase != "post_exit" else "not_applicable",
                "caption_overlap_ratio": 0,
            })
        self.export.write_text(json.dumps({
            "events": [{
                "event_id": "event-1",
                "animation_targets": ["#event-1"],
                "phases": phases,
            }],
        }), encoding="utf-8")
        receipt = self.receipt_dir / "event-1.json"
        receipt.write_text(json.dumps({
            "event_id": "event-1",
            "project_artifact": {
                "path": str(self.project), "sha256": sha256_file(self.project),
            },
            "input_hashes": {
                "motion_design_contract_sha256": sha256_file(self.contract),
            },
            "phase_observations": [
                {"phase": row["phase"], "timestamp_seconds": row["timestamp_seconds"]}
                for row in phases
            ],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _image(path: Path, *, offset: int, visible: bool) -> None:
        image = Image.new("RGB", (160, 90), "white")
        if visible:
            ImageDraw.Draw(image).rectangle((40 + offset, 22, 80 + offset, 45), fill="black")
        image.save(path)

    def _build(self) -> dict:
        return build_report(
            renderer_export_path=self.export,
            render_snapshot_dir=self.render_dir,
            storyboard_path=self.storyboard,
            project_artifact_path=self.project,
            motion_design_contract_path=self.contract,
            source_media_path=self.source,
            keyframe_receipt_dir=self.receipt_dir,
            tolerances={"position_px": 4.0, "size_px": 4.0, "time_seconds": 0.05},
            minimum_similarity=0.95,
        )

    def test_builds_four_phase_hash_bound_report(self) -> None:
        report = self._build()

        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(len(report["samples"]), 4)
        receipt = self.receipt_dir / "event-1.json"
        self.assertEqual(validate(
            report,
            json.loads(self.storyboard.read_text(encoding="utf-8")),
            configured_tolerances={
                "position_px": 4.0, "size_px": 4.0, "time_seconds": 0.05,
            },
            expected_bindings={
                "project_artifact": self.project,
                "motion_design_contract": self.contract,
                "source_media": self.source,
            },
            keyframe_receipt_paths={"event-1": receipt},
        ), [])

    def test_rejects_render_geometry_shift_beyond_tolerance(self) -> None:
        for phase in ("entrance", "mid", "pre_exit"):
            self._image(
                self.render_dir / f"event-1-{phase}.png",
                offset=10,
                visible=True,
            )

        with self.assertRaisesRegex(ValueError, "registration"):
            self._build()


if __name__ == "__main__":
    unittest.main()
