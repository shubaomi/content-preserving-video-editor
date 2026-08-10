from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from technical_qa import parse_black_freeze_silence, run_technical_qa, validate_report  # noqa: E402
from six_media_acceptance import generate as generate_six_media, validate_manifest  # noqa: E402


class TechnicalQaTests(unittest.TestCase):
    def test_parses_detector_intervals(self) -> None:
        log = """
[blackdetect] black_start:1.0 black_end:2.5 black_duration:1.5
[freezedetect] freeze_start:3.0
[freezedetect] freeze_duration:2.0
[freezedetect] freeze_end:5.0
[silencedetect] silence_start:6.0
[silencedetect] silence_end:7.2 | silence_duration:1.2
"""
        parsed = parse_black_freeze_silence(log)
        self.assertEqual(parsed["black"][0]["duration"], 1.5)
        self.assertEqual(parsed["freeze"][0], {"start": 3.0, "end": 5.0, "duration": 2.0})
        self.assertEqual(parsed["silence"][0]["duration"], 1.2)

    def test_final_snapshot_uses_video_stream_duration_when_container_is_longer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "fixture.mp4"
            media.write_bytes(b"fixture")
            captured: list[float] = []

            def fake_snapshot(_media: Path, timestamp: float, output: Path) -> None:
                captured.append(timestamp)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"png")

            probe = {
                "streams": [
                    {"codec_type": "video", "duration": "10.000", "avg_frame_rate": "24/1"},
                    {"codec_type": "audio", "duration": "10.100"},
                ],
                "format": {"duration": "10.100"},
            }
            with (
                patch("technical_qa._probe", return_value=probe),
                patch("technical_qa._snapshot", side_effect=fake_snapshot),
                patch("technical_qa._detectors", return_value=(
                    {"black": [], "freeze": [], "silence": []}, [],
                )),
                patch("technical_qa.loudness", return_value={
                    "measured": True, "integrated_lufs": -14.0, "true_peak_dbtp": -2.0,
                }),
                patch("technical_qa.subprocess.run", return_value=SimpleNamespace(
                    returncode=0, stderr="",
                )),
            ):
                report = run_technical_qa(
                    media, output=root / "report.json", evidence_dir=root / "evidence",
                )

            self.assertEqual(report["samples"][-1]["time_seconds"], 9.9)
            self.assertEqual(captured[-1], 9.9)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_real_short_fixture_passes_decode_probe_audio_and_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "fixture.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(media),
            ], check=True, capture_output=True)
            output = root / "technical-qa.json"
            report = run_technical_qa(media, output=output, evidence_dir=root / "evidence")

            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["decode"]["status"], "pass")
            self.assertEqual(report["media"]["video_streams"], 1)
            self.assertEqual(report["media"]["audio_streams"], 1)
            self.assertEqual(len(report["samples"]), 3)
            self.assertTrue(all(Path(row["path"]).is_file() for row in report["samples"]))
            self.assertTrue(output.is_file())
            self.assertIn("integrated_lufs", report["audio"])
            self.assertEqual(validate_report(report, media), [])
            report["audio"]["integrated_lufs"] += 5
            self.assertTrue(any("fresh" in error for error in validate_report(report, media)))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_all_six_acceptance_types_have_real_decodable_short_media_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "six-media-acceptance.json"
            report = generate_six_media(root / "six-media", manifest)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["scenario_count"], 6)
            self.assertEqual(validate_manifest(manifest), [])
            self.assertTrue(all(not Path(path).is_absolute() for path in report["implementation_dependencies"]))
            evidence = [row["characteristic_evidence"] for row in report["scenarios"]]
            self.assertTrue(all(row["status"] == "pass" for row in evidence))
            self.assertTrue(all(row["checks"] and all(check["passed"] for check in row["checks"])
                                for row in evidence))
            self.assertEqual(len({row["visual_fingerprint"] for row in evidence}), 6)
            self.assertEqual(len({row["audio_fingerprint"] for row in evidence}), 6)

            persisted = json.loads(manifest.read_text(encoding="utf-8"))
            persisted["scenarios"][0]["fixture_type"], persisted["scenarios"][1]["fixture_type"] = (
                persisted["scenarios"][1]["fixture_type"], persisted["scenarios"][0]["fixture_type"]
            )
            manifest.write_text(json.dumps(persisted), encoding="utf-8")
            self.assertTrue(any("characteristic" in error for error in validate_manifest(manifest)))

    def test_six_media_manifest_fails_when_evidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "six-media-acceptance.json"
            suite = root / "six-media"
            suite.mkdir()
            manifest.write_text(json.dumps({
                "schema_version": 1, "status": "pass", "scenario_count": 6,
                "skipped": 0, "scenarios": [], "implementation_dependencies": {},
            }), encoding="utf-8")
            self.assertTrue(validate_manifest(manifest))


if __name__ == "__main__":
    unittest.main()
