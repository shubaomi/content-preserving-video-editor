from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from nle_handoff_v2 import (  # noqa: E402
    NleHandoffError,
    build_nle_handoff_package,
    validate_compatibility_report,
    validate_layer_asset,
    validate_layer_timeline,
    validate_nle_handoff_package,
)


class NleHandoffV2Tests(unittest.TestCase):
    def _authorities(self, root: Path) -> dict[str, Path]:
        values: dict[str, Path] = {}
        for name, content in {
            "project.yaml": "schema_version: 12\n",
            "source.mp4": "source",
            "automatic.mp4": "automatic",
            "edl.json": json.dumps({
                "owner": "video-use",
                "sources": {"input": str(root / "source.mp4")},
                "ranges": [{
                    "id": "c1", "source": "input", "start": 0.0, "end": 2.0,
                    "timeline_start": 0.0,
                }],
                "gaps": [], "transitions": [], "metadata": {"video_id": "fixture"},
            }),
        }.items():
            path = root / name
            path.write_text(content, encoding="utf-8")
            values[name] = path
        return values

    def test_layer_asset_rejects_unavailable_hash_nan_and_fake_alpha_mp4(self) -> None:
        unavailable = {
            "schema_version": 2, "asset_id": "motion", "role": "motion_event",
            "status": "unavailable", "editability_class": "unavailable",
            "path": None, "sha256": "0" * 64, "size_bytes": None, "media_type": None,
            "purpose": "motion", "provenance": "none", "rights_status": "unavailable",
            "reason": "not rendered",
        }
        self.assertTrue(validate_layer_asset(unavailable, package_root=Path.cwd()))

        available = dict(unavailable)
        available.update({
            "status": "available", "editability_class": "media_layer_editable",
            "path": "overlay.mp4", "sha256": "0" * 64, "size_bytes": 1,
            "media_type": "video/mp4", "rights_status": "project_authorized",
            "timeline": {"start_seconds": 0.0, "end_seconds": math.nan, "frame_rate": 25.0},
            "video": {"width": 100, "height": 100, "pixel_format": "yuv420p",
                      "alpha_status": "verified"},
        })
        errors = validate_layer_asset(available, package_root=Path.cwd())
        self.assertTrue(any("finite" in row for row in errors))
        self.assertTrue(any("MP4" in row for row in errors))

    def test_timeline_rejects_bool_numbers_duplicate_ids_and_wrong_ranges(self) -> None:
        timeline = {
            "schema_version": 2, "authority": "video-use-output-timeline",
            "origin_seconds": 0, "duration_seconds": 2.0, "frame_rate": 25.0,
            "canvas": {"width": True, "height": 1920},
            "tracks": [{
                "track_id": "v1", "role": "base_video", "order": 0,
                "clips": [
                    {"clip_id": "c", "asset_id": "base", "timeline_start": 1.0,
                     "timeline_end": 0.5, "source_start": 0.0, "source_end": 1.0},
                    {"clip_id": "c", "asset_id": "base", "timeline_start": 0.0,
                     "timeline_end": 1.0, "source_start": 0.0, "source_end": 1.0},
                ],
            }],
            "markers": [],
        }
        errors = validate_layer_timeline(timeline)
        self.assertTrue(any("canvas" in row for row in errors))
        self.assertTrue(any("duplicate" in row for row in errors))
        self.assertTrue(any("range" in row for row in errors))

    def test_compatibility_never_claims_native_editor_automation(self) -> None:
        report = {
            "schema_version": 2, "status": "pending",
            "package_profile": "jianying_desktop_compatible_v1",
            "editor": {"name": "Jianying Desktop", "version": "unverified",
                       "platform": "Windows", "observed_at": "2026-08-13T00:00:00Z"},
            "capabilities": {"native_draft": True, "api": False, "cli": False,
                             "headless_render": False, "srt_import": False},
            "format_results": [{
                "format_id": "srt", "asset_sha256": "0" * 64, "imported": False,
                "decoded": True, "editable_class": "reference_only",
                "finding": "human canary pending",
            }],
            "human_canary": {"actor": "HongRun", "status": "pending",
                             "tasks": [{"task_id": str(i), "status": "pending"}
                                       for i in range(5)],
                             "reason": "not run"},
        }
        self.assertTrue(any("native" in row for row in validate_compatibility_report(report)))

    def test_builds_deterministic_balanced_package_and_detects_nested_drift(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            auth = self._authorities(root)
            clean = root / "clean.mp4"; clean.write_bytes(b"clean")
            captions = root / "master.srt"; captions.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nhello\n", encoding="utf-8",
            )
            sfx = root / "cue.wav"; sfx.write_bytes(b"cue")
            package = root / "manual-finish" / "nle-package-v2"
            receipt = build_nle_handoff_package(
                package_root=package,
                authorized_root=root,
                project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"),
                package_level="balanced", frame_rate=25.0, width=1080, height=1920,
                assets={"clean_a_roll": clean, "caption_srt": captions, "sfx_event": [{
                    "path": sfx, "semantic_event_id": "semantic-1", "render_event_id": "event-1",
                    "timeline": {"start_seconds": 0.5, "end_seconds": 1.0,
                                 "frame_rate": 25.0},
                }]},
            )
            receipt_path = package / "10-evidence" / "nle-handoff-package.json"
            self.assertEqual(receipt["status"], "action_required")
            self.assertEqual(validate_nle_handoff_package(receipt_path), [])
            self.assertTrue((package / "08-timeline" / "import-order.md").is_file())
            self.assertFalse(receipt["capability_claims"]["native_draft"])
            timeline = json.loads((package / "08-timeline" / "layer-timeline.json").read_text(encoding="utf-8"))
            sfx_track = next(row for row in timeline["tracks"] if row["role"] == "sfx")
            self.assertEqual(sfx_track["clips"][0]["timeline_start"], 0.5)

            copied = package / "02-captions" / "master.srt"
            copied.write_text("changed", encoding="utf-8")
            self.assertTrue(any("stale" in row for row in validate_nle_handoff_package(receipt_path)))

    def test_disabled_builder_does_not_create_package(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            auth = self._authorities(root)
            package = root / "manual-finish" / "nle-package-v2"
            with self.assertRaisesRegex(NleHandoffError, "disabled"):
                build_nle_handoff_package(
                    package_root=package, authorized_root=root,
                    project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                    automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                    implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"), package_level="balanced",
                    frame_rate=25.0, width=1080, height=1920, assets={}, enabled=False,
                )
            self.assertFalse(package.exists())

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_package_root_junction_is_rejected_without_external_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as external:
            root = Path(folder)
            outside = Path(external)
            auth = self._authorities(root)
            clean = root / "clean.mp4"; clean.write_bytes(b"clean")
            captions = root / "master.srt"; captions.write_text("caption", encoding="utf-8")
            package = root / "manual-finish" / "nle-package-v2"
            package.parent.mkdir(parents=True)
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(package), str(outside)],
                capture_output=True, text=True,
            )
            if result.returncode:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            with self.assertRaisesRegex(NleHandoffError, "redirected"):
                build_nle_handoff_package(
                    package_root=package, authorized_root=root,
                    project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                    automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                    implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"), package_level="balanced",
                    frame_rate=25.0, width=1080, height=1920,
                    assets={"clean_a_roll": clean, "caption_srt": captions},
                )
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
