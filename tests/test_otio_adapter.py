from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from otio_adapter import edl_to_otio, otio_to_internal, validate_roundtrip  # noqa: E402
from director import Director  # noqa: E402
from director_contracts import DirectorContractError  # noqa: E402


class OtioAdapterTests(unittest.TestCase):
    def test_roundtrip_preserves_sources_clips_gap_transition_and_metadata(self) -> None:
        edl = {
            "owner": "video-use",
            "sources": {"cam": "C:/media/cam.mp4"},
            "ranges": [
                {"id": "c1", "source": "cam", "start": 1.0, "end": 3.0,
                 "timeline_start": 0.0, "metadata": {"chapter": "intro"}},
                {"id": "c2", "source": "cam", "start": 5.0, "end": 8.0,
                 "timeline_start": 2.5, "metadata": {"chapter": "demo"}},
            ],
            "gaps": [{"after_clip_id": "c1", "duration": 0.5}],
            "transitions": [{"from_clip_id": "c1", "to_clip_id": "c2", "type": "dissolve",
                             "duration": 0.2}],
            "metadata": {"video_id": "fixture"},
        }
        otio = edl_to_otio(edl, rate=30.0)
        restored = otio_to_internal(otio)
        self.assertEqual(restored["sources"], edl["sources"])
        self.assertEqual(restored["ranges"], edl["ranges"])
        self.assertEqual(restored["gaps"], edl["gaps"])
        self.assertEqual(restored["transitions"], edl["transitions"])
        self.assertEqual(restored["metadata"], edl["metadata"])
        self.assertEqual(validate_roundtrip(edl, restored), [])
        self.assertEqual(otio["OTIO_SCHEMA"], "Timeline.1")

    def test_roundtrip_detects_authoritative_edl_drift(self) -> None:
        original = {"sources": {"cam": "a.mp4"}, "ranges": [
            {"id": "c1", "source": "cam", "start": 0.0, "end": 1.0, "timeline_start": 0.0}
        ], "gaps": [], "transitions": [], "metadata": {}}
        changed = {**original, "ranges": [{**original["ranges"][0], "end": 2.0}]}
        self.assertIn("ranges changed", validate_roundtrip(original, changed))

    def test_restore_uses_otio_standard_timing_not_embedded_metadata(self) -> None:
        original = {"sources": {"cam": "a.mp4"}, "ranges": [
            {"id": "c1", "source": "cam", "start": 0.0, "end": 1.0, "timeline_start": 0.0}
        ], "gaps": [], "transitions": [], "metadata": {}}
        timeline = edl_to_otio(original, rate=30)
        clip = timeline["tracks"]["children"][0]["children"][0]
        clip["source_range"]["duration"]["value"] = 60.0
        restored = otio_to_internal(timeline)
        self.assertIn("ranges changed", validate_roundtrip(original, restored))

    def test_director_projects_valid_edl_before_later_video_use_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"fixture")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "schema_version": 4, "version": 4, "video_id": "fixture",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4", "input_mode": "raw"},
                "timeline": {"otio": {"enabled": True, "rate": 30}},
            }), encoding="utf-8")
            director = Director(project)
            transcript = director.video_use_dir / "transcripts" / "input.json"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"words": [
                {"type": "word", "text": "内容", "start": 0.1, "end": 0.5}
            ]}), encoding="utf-8")
            edl = director.video_use_dir / "edl.json"
            edl.write_text(json.dumps({
                "owner": "video-use", "sources": {"input": str(source)},
                "ranges": [{"id": "c1", "source": "input", "start": 0.0, "end": 10.0,
                            "timeline_start": 0.0}],
                "cut_policy": {"word_boundary_padding_ms": [30, 100], "audio_fade_ms": 30},
            }), encoding="utf-8")
            director._start("video_use_timeline")
            with patch("director._ffprobe_duration", return_value=10.0):
                with self.assertRaises(DirectorContractError):
                    director.stage_video_use_timeline()
            self.assertTrue((director.video_use_dir / "timeline.otio").is_file())
            roundtrip = json.loads((director.video_use_dir / "otio-roundtrip.json").read_text(encoding="utf-8"))
            self.assertEqual(roundtrip["status"], "pass")


if __name__ == "__main__":
    unittest.main()
