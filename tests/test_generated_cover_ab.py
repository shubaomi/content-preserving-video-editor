from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("cover_ab", ROOT / "scripts" / "compare_generated_covers.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def manifest(path: Path, output: Path, strategy: str):
    data = {
        "generation_mode": "reference_guided_regeneration",
        "output": str(output),
        "identity_references": ["a.jpg", "b.jpg"],
        "identity_qa": {"agent_visual_review_passed": True},
        "topic_evidence": "transcript",
        "communication_strategy": strategy,
        "rights_basis": "authorized",
        "typography": {"method": "Pillow local deterministic text", "title": "标题", "label": "洪润", "subtitle": "主题"},
    }
    path.write_text(json.dumps(data), encoding="utf-8")


class GeneratedCoverABTests(unittest.TestCase):
    def test_distinct_valid_strategies_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a_image = root / "a.jpg"
            b_image = root / "b.jpg"
            Image.new("RGB", (1080, 1920), "black").save(a_image)
            Image.new("RGB", (1080, 1920), "white").save(b_image)
            a_manifest = root / "a.json"
            b_manifest = root / "b.json"
            manifest(a_manifest, a_image, "topic clarity")
            manifest(b_manifest, b_image, "human curiosity")
            result = MODULE.compare(a_manifest, b_manifest, "A", "A communicates the product transformation more directly.", root / "sheet.jpg")
            self.assertTrue(result["passed"])
            self.assertEqual(result["performance_claim"].split(";")[0], "none")

    def test_cosmetic_duplicate_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("a.jpg", "b.jpg"):
                Image.new("RGB", (1080, 1920), "black").save(root / name)
            manifest(root / "a.json", root / "a.jpg", "same")
            manifest(root / "b.json", root / "b.jpg", "same")
            result = MODULE.compare(root / "a.json", root / "b.json", "A", "editorial", root / "sheet.jpg")
            self.assertFalse(result["passed"])
            self.assertFalse(result["checks"]["different_communication_strategies"])

    def test_corrupted_typography_metadata_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, color in (("a.jpg", "black"), ("b.jpg", "white")):
                Image.new("RGB", (1080, 1920), color).save(root / name)
            manifest(root / "a.json", root / "a.jpg", "topic clarity")
            manifest(root / "b.json", root / "b.jpg", "human curiosity")
            data = json.loads((root / "b.json").read_text(encoding="utf-8"))
            data["typography"]["title"] = "损坏\ufffd标题"
            (root / "b.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = MODULE.compare(root / "a.json", root / "b.json", "A", "editorial", root / "sheet.jpg")
            self.assertFalse(result["passed"])
            self.assertFalse(result["variants"]["B"]["checks"]["typography_text_is_valid_utf8"])


if __name__ == "__main__":
    unittest.main()
