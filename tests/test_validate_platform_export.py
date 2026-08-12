from __future__ import annotations

import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_platform_export.py"
SPEC = importlib.util.spec_from_file_location("validate_platform_export", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ValidatePlatformExportTests(unittest.TestCase):
    def test_report_binds_exact_universal_output_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "universal.mp4"
            media.write_bytes(b"one universal file")
            report = MODULE.bind_universal_output({"passed": True}, media)
            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["universal_output"])
            self.assertEqual(
                report["file_sha256"],
                "c47ac9a68c64ada77568ffdcf60fb07e0474121106c7f4b50791619c30977055",
            )

    def test_failed_report_cannot_claim_pass_status(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "universal.mp4"
            media.write_bytes(b"x")
            report = MODULE.bind_universal_output({"passed": False}, media)
            self.assertEqual(report["status"], "fail")

    def test_cover_binding_records_exact_cover_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cover = Path(folder) / "cover.png"
            cover.write_bytes(b"cover bytes")
            report = MODULE.bind_cover({}, cover)
            self.assertEqual(report["cover"], str(cover.resolve()))
            self.assertEqual(report["cover_sha256"], __import__("hashlib").sha256(
                b"cover bytes"
            ).hexdigest())

    def test_bound_platform_report_allows_an_explicitly_optional_missing_cover(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / "universal.mp4"
            media.write_bytes(b"one universal file")
            safe = root / "safe.jpg"
            safe.write_bytes(b"safe")
            checks = {
                name: True for name in (
                    "container_mp4", "video_codec", "pixel_format", "minimum_short_edge",
                    "ratio", "audio_present", "full_decode", "true_peak_recommendation",
                )
            }
            report = {
                "schema_version": 1,
                "status": "pass",
                "passed": True,
                "universal_output": True,
                "file_sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
                "cover_sha256": None,
                "preset_version": "fixture",
                "preset_verified_on": "2026-08-11",
                "platform": "fixture",
                "checks": checks,
                "safe_zone_snapshot": str(safe),
                "safe_zone_snapshot_sha256": hashlib.sha256(safe.read_bytes()).hexdigest(),
            }

            self.assertEqual(MODULE.validate_bound_report(report, media, None), [])

    def test_unsafe_true_peak_is_blocking(self) -> None:
        media = Path("universal.mp4")
        preset = {
            "video": {"codec": "h264", "pixel_format": "yuv420p"},
            "minimum_short_edge": 1080,
            "accepted_ratio_range": [1.0, 2.0],
            "file_size_warning_bytes": 10_000_000,
            "audio": {"loudness_lufs": -14, "true_peak_dbtp": -1},
        }
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "10", "size": "1000"},
        }
        with patch.object(MODULE, "probe", return_value=probe):
            report = MODULE.validate(
                media, preset, "douyin",
                {"measured": True, "integrated_lufs": -14.0, "true_peak_dbtp": 2.19},
                decoded=True,
            )
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["true_peak_recommendation"])


if __name__ == "__main__":
    unittest.main()
