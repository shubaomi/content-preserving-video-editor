from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "slice_attention_plan.py"


class SliceAttentionPlanTests(unittest.TestCase):
    def test_nonzero_slice_supports_events_schema_and_rebases_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "plan.json"
            output = root / "slice.json"
            source.write_text(json.dumps({"duration": 100, "events": [
                {"id": "before", "start": 5, "end": 8, "duration": 3},
                {"id": "inside", "start": 21, "end": 24, "duration": 3},
                {"id": "cross", "start": 39, "end": 43, "duration": 4},
            ]}), encoding="utf-8")
            subprocess.run([sys.executable, str(SCRIPT), "--plan", str(source), "--start", "20", "--end", "40", "--out", str(output)], check=True)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["duration"], 20)
            self.assertEqual([event["id"] for event in result["events"]], ["inside", "cross"])
            self.assertEqual(result["events"][0]["start"], 1)
            self.assertEqual(result["events"][1]["end"], 20)


if __name__ == "__main__":
    unittest.main()
