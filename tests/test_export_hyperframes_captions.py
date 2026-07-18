from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_hyperframes_captions import slice_captions  # noqa: E402


class ExportHyperframesCaptionTests(unittest.TestCase):
    def test_slice_uses_output_timeline_and_clamps_sample_edges(self) -> None:
        rows = slice_captions({"segments": [
            {"start": 9.5, "end": 10.5, "text": "开头", "mapping_owner": "video-use"},
            {"start": 12.0, "end": 13.0, "text": "中间", "mapping_owner": "video-use"},
            {"start": 19.5, "end": 21.0, "text": "结尾", "mapping_owner": "video-use"},
        ]}, 10.0, 20.0)
        self.assertEqual(rows[0]["start"], 0.0)
        self.assertEqual(rows[0]["duration"], 0.5)
        self.assertEqual(rows[-1]["start"], 9.5)
        self.assertEqual(rows[-1]["duration"], 0.5)
        self.assertTrue(all(row["mapping_owner"] == "video-use" for row in rows))


if __name__ == "__main__":
    unittest.main()

