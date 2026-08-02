from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clip_factory import build_clip_manifest, validate_clip_manifest  # noqa: E402


class ClipFactoryTests(unittest.TestCase):
    def _fixture(self, orientation: str, independent: bool = True) -> dict:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "text": "这是", "start": 10, "end": 10.5},
                {"id": "w2", "text": "完整结论", "start": 10.5, "end": 18},
            ]}), encoding="utf-8")
            edl = root / "edl.json"; edl.write_text('{"ranges":[{"start":0,"end":60}]}', encoding="utf-8")
            brief = root / "brief.json"; brief.write_text(json.dumps({"events": [{
                "id": "e1", "source_start": 10, "source_end": 18,
                "output_start": 10, "output_end": 18, "transcript_word_ids": ["w1", "w2"],
                "transcript_quote": "这是完整结论", "viewer_takeaway": "可独立理解" if independent else "",
                "clip_candidate": independent, "cut_reason": "self-contained explanation",
            }]}), encoding="utf-8")
            contract = root / "contract.json"; contract.write_text('{"schema_version":1}', encoding="utf-8")
            output = root / "clips.json"
            report = build_clip_manifest(
                transcript_path=transcript, edl_path=edl, semantic_brief_path=brief,
                output_timeline_path=edl, hook_path=None, production_contract_path=contract,
                orientation=orientation, output=output,
            )
            self.assertEqual(validate_clip_manifest(report), [])
            return report

    def test_landscape_tutorial_candidate_is_evidence_bound(self) -> None:
        report = self._fixture("landscape")
        self.assertEqual(report["status"], "selected")
        self.assertEqual(report["candidates"][0]["orientation"], "landscape")
        self.assertEqual(report["candidates"][0]["word_ids"], ["w1", "w2"])

    def test_portrait_talking_head_candidate_is_evidence_bound(self) -> None:
        report = self._fixture("portrait")
        self.assertEqual(report["candidates"][0]["orientation"], "portrait")

    def test_no_independent_segment_is_legal_not_selected(self) -> None:
        report = self._fixture("portrait", independent=False)
        self.assertEqual(report["status"], "not_selected")
        self.assertEqual(report["candidates"], [])

    def test_semantic_times_outside_word_and_edl_mapping_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": [
                {"id": "w1", "text": "完整", "start": 10, "end": 11},
                {"id": "w2", "text": "结论", "start": 11, "end": 12},
            ]}), encoding="utf-8")
            edl = root / "edl.json"
            edl.write_text('{"ranges":[{"start":10,"end":20,"timeline_start":0}]}', encoding="utf-8")
            brief = root / "brief.json"
            brief.write_text(json.dumps({"events": [{
                "id": "e1", "source_start": 0, "source_end": 50,
                "output_start": 30, "output_end": 80,
                "transcript_word_ids": ["w1", "w2"], "transcript_quote": "完整结论",
                "viewer_takeaway": "可独立理解", "clip_candidate": True,
            }]}), encoding="utf-8")
            contract = root / "contract.json"; contract.write_text('{}', encoding="utf-8")

            report = build_clip_manifest(
                transcript_path=transcript, edl_path=edl, semantic_brief_path=brief,
                output_timeline_path=edl, hook_path=None, production_contract_path=contract,
                orientation="landscape", output=root / "clips.json",
            )

            self.assertEqual(report["status"], "not_selected")
            self.assertIn("timing", report["rejected"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
