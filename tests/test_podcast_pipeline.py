from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from podcast_pipeline import build_podcast_manifest, validate_podcast_manifest  # noqa: E402


class PodcastPipelineTests(unittest.TestCase):
    def test_pcm_package_records_decode_duration_loudness_peak_and_source_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "clean.wav"
            with wave.open(str(audio), "wb") as handle:
                handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(8000)
                samples = [int(8000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(8000)]
                handle.writeframes(b"".join(struct.pack("<h", value) for value in samples))
            transcript = root / "transcript.json"
            transcript.write_text(json.dumps({"words": [{"id": "w1", "text": "开始", "start": 0, "end": 1}]}), encoding="utf-8")
            output = root / "podcast.json"
            report = build_podcast_manifest(
                audio_path=audio, transcript_path=transcript,
                chapters=[{"title": "开始", "source_start": 0, "source_end": 1,
                           "word_ids": ["w1"]}], title="测试播客", description="来源明确",
                output=output,
            )
            self.assertEqual(report["status"], "pass")
            self.assertAlmostEqual(report["audio_qa"]["duration_seconds"], 1.0, places=2)
            self.assertEqual(validate_podcast_manifest(report), [])


if __name__ == "__main__":
    unittest.main()
