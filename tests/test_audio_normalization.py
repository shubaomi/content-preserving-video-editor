from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from normalize_social_audio import normalize, validate_report  # noqa: E402


class AudioNormalizationTests(unittest.TestCase):
    def test_report_requires_two_pass_measurements_and_target_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            output = root / "output.mp4"
            source.write_bytes(b"source")
            output.write_bytes(b"output")
            report = {"status": "pass", "source_sha256": __import__("hashlib").sha256(b"source").hexdigest(),
                      "output_sha256": __import__("hashlib").sha256(b"output").hexdigest(),
                      "target": {"integrated_lufs": -14, "true_peak_dbtp": -1.5, "lra": 11},
                      "first_pass": {"input_i": "-20", "input_tp": "-3", "input_lra": "4",
                                     "input_thresh": "-30", "target_offset": "0"},
                      "post_measurement": {"input_i": "-14.1", "input_tp": "-1.6", "input_lra": "5"}}
            self.assertEqual(validate_report(report, source, output, -14, -1.5, 11), [])
            report["post_measurement"]["input_i"] = "-18"
            self.assertTrue(validate_report(report, source, output, -14, -1.5, 11))
            del report["first_pass"]
            self.assertTrue(validate_report(report, source, output, -14, -1.5, 11))

    def test_report_rejects_empty_or_non_finite_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            output = root / "output.mp4"
            source.write_bytes(b"source")
            output.write_bytes(b"output")
            base = {"status": "pass",
                    "source_sha256": __import__("hashlib").sha256(b"source").hexdigest(),
                    "output_sha256": __import__("hashlib").sha256(b"output").hexdigest(),
                    "target": {"integrated_lufs": -14, "true_peak_dbtp": -1.5, "lra": 11},
                    "first_pass": {"input_i": "-20", "input_tp": "-3", "input_lra": "4",
                                   "input_thresh": "-30", "target_offset": "0"},
                    "post_measurement": {"input_i": "-14", "input_tp": "-1.6",
                                         "input_lra": "5"}}
            for invalid in ({}, {**base["first_pass"], "input_i": "nan"}):
                report = {**base, "first_pass": invalid}
                self.assertTrue(validate_report(report, source, output, -14, -1.5, 11))
            for value in ("nan", "inf", "-inf"):
                report = {**base, "post_measurement": {**base["post_measurement"],
                                                        "input_tp": value}}
                self.assertTrue(validate_report(report, source, output, -14, -1.5, 11))

    def test_normalizer_uses_unique_temporary_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            output = root / "output.mp4"
            source.write_bytes(b"source")
            temporary_paths: list[Path] = []

            def fake_run(command, **kwargs):
                temporary = Path(command[-1])
                temporary_paths.append(temporary)
                temporary.write_bytes(b"normalized")

            measurements = [
                {"input_i": "-20", "input_tp": "-3", "input_lra": "4",
                 "input_thresh": "-30", "target_offset": "0"},
                {"input_i": "-14", "input_tp": "-1.6", "input_lra": "4"},
            ]
            with patch("normalize_social_audio.measure", side_effect=measurements * 2), \
                 patch("normalize_social_audio.subprocess.run", side_effect=fake_run):
                self.assertEqual(normalize(source, output)["status"], "pass")
                self.assertEqual(normalize(source, output)["status"], "pass")
            self.assertEqual(len(temporary_paths), 2)
            self.assertNotEqual(temporary_paths[0], temporary_paths[1])
            self.assertTrue(all(path != output for path in temporary_paths))


if __name__ == "__main__":
    unittest.main()
