from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("promote", ROOT / "scripts" / "promote_generated_cover.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class PromoteGeneratedCoverTests(unittest.TestCase):
    def test_promotes_recommended_variant_and_preserves_no_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            image = root / "b.jpg"
            Image.new("RGB", (1080, 1920), "navy").save(image)
            manifest = root / "b.json"
            manifest.write_text(json.dumps({"output": str(image), "generation_mode": "reference_guided_regeneration"}), encoding="utf-8")
            report = root / "report.json"
            report.write_text(json.dumps({"passed": True, "recommended_variant": "B", "variants": {"B": {"manifest": str(manifest)}}, "editorial_rationale": "topic fit", "performance_claim": "none"}), encoding="utf-8")
            result = MODULE.promote(report, root / "selected.jpg", root / "selected.json")
            self.assertEqual(result["selection"]["source_variant"], "B")
            self.assertEqual(result["selection"]["performance_claim"], "none")


if __name__ == "__main__":
    unittest.main()
