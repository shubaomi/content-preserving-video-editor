from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from sample_caption_delivery import (  # noqa: E402
    _replace_with_retry,
    build_caption_filter,
    validate_receipt,
)


class SampleCaptionDeliveryTests(unittest.TestCase):
    def test_receipt_validator_fails_closed_for_malformed_top_level(self) -> None:
        for malformed in ([], "bad", None):
            self.assertTrue(validate_receipt(malformed))

    def test_filter_escapes_windows_drive_and_quotes(self) -> None:
        value = build_caption_filter(Path("E:/Reviewer's Captions/master.srt"))
        self.assertIn("subtitles=filename='E\\:/Reviewer\\'s Captions/master.srt'", value)
        self.assertIn("charenc=UTF-8", value)

    def test_receipt_binds_same_captions_to_aligned_baseline_and_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {}
            for name, content in {
                "baseline-raw.mp4": b"baseline-raw",
                "candidate-raw.mp4": b"candidate-raw",
                "master.srt": b"caption-track",
                "baseline-captioned.mp4": b"baseline-captioned",
                "candidate-captioned.mp4": b"candidate-captioned",
            }.items():
                path = root / name
                path.write_bytes(content)
                files[name] = path

            def artifact(name: str) -> dict:
                path = files[name].resolve()
                return {"path": str(path), "sha256": sha256_file(path)}

            receipt = {
                "schema_version": 1,
                "mode": "burned_in_last_for_paired_review",
                "caption_source": artifact("master.srt"),
                "baseline": {
                    "input": artifact("baseline-raw.mp4"),
                    "output": {**artifact("baseline-captioned.mp4"), "duration_seconds": 75.0},
                    "argv": ["ffmpeg", "-vf", build_caption_filter(files["master.srt"]),
                             str(files["baseline-captioned.mp4"].resolve())],
                    "full_decode": True,
                },
                "candidate": {
                    "input": artifact("candidate-raw.mp4"),
                    "output": {**artifact("candidate-captioned.mp4"), "duration_seconds": 75.0},
                    "argv": ["ffmpeg", "-vf", build_caption_filter(files["master.srt"]),
                             str(files["candidate-captioned.mp4"].resolve())],
                    "full_decode": True,
                },
            }
            self.assertEqual(validate_receipt(receipt), [])

            files["master.srt"].write_bytes(b"changed")
            self.assertTrue(any("caption source hash is stale" in error
                                for error in validate_receipt(receipt)))

    def test_receipt_rejects_missing_filter_decode_or_duration_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("raw-a.mp4", "raw-b.mp4", "a.mp4", "b.mp4", "master.srt"):
                (root / name).write_bytes(name.encode("utf-8"))

            def artifact(name: str, *, duration: float | None = None) -> dict:
                path = (root / name).resolve()
                record = {"path": str(path), "sha256": sha256_file(path)}
                if duration is not None:
                    record["duration_seconds"] = duration
                return record

            receipt = {
                "schema_version": 1,
                "mode": "burned_in_last_for_paired_review",
                "caption_source": artifact("master.srt"),
                "baseline": {
                    "input": artifact("raw-a.mp4"),
                    "output": artifact("a.mp4", duration=75.0),
                    "argv": ["ffmpeg", str((root / "a.mp4").resolve())],
                    "full_decode": False,
                },
                "candidate": {
                    "input": artifact("raw-b.mp4"),
                    "output": artifact("b.mp4", duration=77.0),
                    "argv": ["ffmpeg", str((root / "b.mp4").resolve())],
                    "full_decode": True,
                },
            }
            errors = validate_receipt(receipt)
            self.assertTrue(any("subtitles filter" in error for error in errors), errors)
            self.assertTrue(any("full decode" in error for error in errors), errors)
            self.assertTrue(any("aligned" in error for error in errors), errors)

    def test_caption_output_replace_retries_a_transient_windows_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.tmp"
            destination = root / "destination.mp4"
            source.write_bytes(b"new")
            attempts = {"count": 0}

            def flaky_replace(src, dst):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise PermissionError("locked")
                Path(dst).write_bytes(Path(src).read_bytes())
                Path(src).unlink()

            from unittest.mock import patch
            with patch("sample_caption_delivery.os.replace", side_effect=flaky_replace):
                _replace_with_retry(source, destination, timeout_seconds=0.5)

            self.assertEqual(destination.read_bytes(), b"new")
            self.assertEqual(attempts["count"], 2)


if __name__ == "__main__":
    unittest.main()
