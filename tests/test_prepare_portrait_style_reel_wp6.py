from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_portrait_style_reel_wp6 import (  # noqa: E402
    Wp6PreparationError,
    prepare_wp6_authorities,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.resolve()


class PreparePortraitStyleReelWp6Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"authorized-source")
        self.transcript = _write_json(self.root / "transcript.json", {"words": [
            {"id": "w0", "text": "outside", "start": 10.0, "end": 11.0},
            {"id": "w1", "text": "inside one", "start": 17.8, "end": 20.0},
            {"id": "w2", "text": "inside two", "start": 38.3, "end": 40.0},
        ]})
        self.brief = _write_json(self.root / "semantic.json", {"events": [
            {"id": "render", "decision": "render", "output_start": 17.71,
             "output_end": 27.81, "approved_visible_copy": ["A"]},
            {"id": "quiet", "decision": "quiet_source", "output_start": 38.21,
             "output_end": 56.29},
            {"id": "outside", "decision": "render", "output_start": 57.0,
             "output_end": 60.0},
        ]})
        import hashlib
        source_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.proposal = _write_json(self.root / "proposal.json", {
            "schema_version": 1,
            "artifact_type": "portrait_style_reel_v2_window_proposal",
            "status": "action_required",
            "project_id": "fixture",
            "authorities": {
                "existing_canary_source": {
                    "path": str(self.source.resolve()), "sha256": source_sha,
                    "original_source_offset_seconds": 66.15,
                },
                "transcript": {"path": str(self.transcript), "sha256": self._sha(self.transcript)},
                "semantic_brief": {"path": str(self.brief), "sha256": self._sha(self.brief)},
            },
            "proposed_window": {
                "original_source": {"start_seconds": 83.86, "end_seconds": 122.44,
                                    "duration_seconds": 38.58},
                "existing_canary_relative": {"start_seconds": 17.71, "end_seconds": 56.29,
                                             "duration_seconds": 38.58},
            },
            "semantic_coverage": [
                {"semantic_event_id": "render", "decision": "render"},
                {"semantic_event_id": "quiet", "decision": "quiet_source"},
            ],
        })

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _sha(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_prepares_scoped_authorities_without_rewriting_inputs(self) -> None:
        before = {path: path.read_bytes() for path in (self.proposal, self.transcript, self.brief)}
        manifest = prepare_wp6_authorities(
            proposal_path=self.proposal,
            confirmed_original_start=83.86,
            confirmed_original_end=122.44,
            output_dir=self.root / "work" / "style-reel" / "authorities",
            authorized_root=self.root,
        )
        self.assertEqual(["render", "quiet"], manifest["semantic_event_ids"])
        self.assertEqual({"render": "render", "quiet": "quiet_source"}, manifest["event_decisions"])
        self.assertEqual({"start_seconds": 17.71, "end_seconds": 56.29}, manifest["source_window"])
        scoped = json.loads(Path(manifest["artifacts"]["semantic_brief"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(["render", "quiet"], [row["id"] for row in scoped["events"]])
        caption_edl = json.loads(Path(manifest["artifacts"]["caption_edl"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(0.0, caption_edl["ranges"][0]["timeline_start"])
        validation_edl = json.loads(Path(manifest["artifacts"]["validation_edl"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(17.71, validation_edl["ranges"][0]["timeline_start"])
        for path, value in before.items():
            self.assertEqual(value, path.read_bytes())

    def test_rejects_unconfirmed_or_stale_window(self) -> None:
        with self.assertRaisesRegex(Wp6PreparationError, "confirmed window"):
            prepare_wp6_authorities(
                proposal_path=self.proposal, confirmed_original_start=83.85,
                confirmed_original_end=122.44, output_dir=self.root / "out",
                authorized_root=self.root,
            )
        proposal = json.loads(self.proposal.read_text(encoding="utf-8"))
        proposal["semantic_coverage"][1]["decision"] = "render"
        _write_json(self.proposal, proposal)
        with self.assertRaisesRegex(Wp6PreparationError, "decision"):
            prepare_wp6_authorities(
                proposal_path=self.proposal, confirmed_original_start=83.86,
                confirmed_original_end=122.44, output_dir=self.root / "out",
                authorized_root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
