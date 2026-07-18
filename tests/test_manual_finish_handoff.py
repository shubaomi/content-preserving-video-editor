from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from manual_finish import (  # noqa: E402
    build_handoff_manifest,
    validate_handoff_manifest,
    validate_returned_final_qa,
)


class ManualFinishHandoffTests(unittest.TestCase):
    def test_manifest_hashes_available_assets_and_marks_missing_optional_assets(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            automatic = root / "automatic.mp4"
            captions = root / "captions.srt"
            for path, content in ((source, b"source"), (automatic, b"automatic"), (captions, b"caption")):
                path.write_bytes(content)
            manifest_path = root / "handoff-manifest.json"
            manifest = build_handoff_manifest(
                manifest_path=manifest_path,
                backend="opencut",
                source_video=source,
                automatic_master=automatic,
                clean_a_roll=root / "missing-clean.mp4",
                captions=captions,
                transparent_motion_layer=None,
                bgm_stem=None,
                sfx_stems=[],
                cover=None,
                modifications=[{"event_id": "event-1", "request": "move callout right"}],
            )
            self.assertEqual(validate_handoff_manifest(manifest), [])
            self.assertEqual(manifest["assets"]["source_video"]["status"], "available")
            self.assertEqual(len(manifest["assets"]["source_video"]["sha256"]), 64)
            self.assertEqual(manifest["assets"]["clean_a_roll"]["status"], "unavailable")
            self.assertIsNone(manifest["assets"]["clean_a_roll"]["sha256"])
            self.assertFalse(manifest["runtime_dependency_required"])
            self.assertEqual(manifest["automation_capabilities_claimed"], [])

    def test_returned_final_qa_must_bind_all_reviews_to_same_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "manual.mp4"
            output.write_bytes(b"manual")
            evidence = []
            for name in ("caption", "audio", "visual"):
                path = root / f"{name}.json"
                path.write_text("{}", encoding="utf-8")
                evidence.append(str(path))
            import hashlib
            output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            report = {
                "schema_version": 1,
                "status": "pass",
                "output_sha256": output_hash,
                "reviews": {
                    "captions": {"status": "pass", "sample_count": 3, "evidence": [evidence[0]]},
                    "audio": {
                        "status": "pass", "integrated_lufs": -14.0,
                        "true_peak_dbtp": -1.2, "evidence": [evidence[1]],
                    },
                    "visual": {"status": "pass", "representative_frame_count": 3,
                               "evidence": [evidence[2]]},
                },
            }
            self.assertEqual(validate_returned_final_qa(report, output), [])
            report["output_sha256"] = "0" * 64
            self.assertTrue(any("output hash" in error for error in validate_returned_final_qa(report, output)))


if __name__ == "__main__":
    unittest.main()
