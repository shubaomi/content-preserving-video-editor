from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cover_production import CoverProductionActionRequired, produce_cover  # noqa: E402
from director_adapters import AdapterRunner  # noqa: E402


class CoverProductionTests(unittest.TestCase):
    def test_missing_reference_guided_bases_returns_truthful_action_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = []
            for index in range(3):
                path = root / f"ref-{index}.jpg"
                Image.new("RGB", (100, 100), "white").save(path)
                refs.append(str(path))
            with self.assertRaises(CoverProductionActionRequired) as caught:
                produce_cover(
                    project={"title": "Topic", "cover": {
                        "enabled": True, "identity_references": refs[:2],
                        "expression_references": refs[2:], "variants": {},
                    }}, project_root=root, semantic_brief=root / "semantic.json",
                    output=root / "cover.jpg", work_dir=root / "work",
                    runner=AdapterRunner(root / "state.json"), execute_external=False,
                )
            packet = caught.exception.packet
            self.assertEqual(packet["generation_mode"], "reference_guided_regeneration")
            self.assertEqual(packet["variant_count"], 2)
            self.assertTrue(packet["no_pasted_cutout"])

    def test_existing_reviewed_bases_run_typography_ab_and_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = []
            for index in range(3):
                path = root / f"ref-{index}.jpg"
                Image.new("RGB", (120, 120), (80 + index * 20, 80, 80)).save(path)
                refs.append(str(path))
            base_a = root / "base-a.png"
            base_b = root / "base-b.png"
            Image.new("RGB", (1080, 1920), "#102030").save(base_a)
            Image.new("RGB", (1080, 1920), "#e0b070").save(base_b)
            semantic = root / "semantic.json"
            semantic.write_text(json.dumps({"topic": "test"}), encoding="utf-8")
            output = root / "exports" / "cover.jpg"
            artifacts = produce_cover(
                project={"title": "Auditable workflow", "cover": {
                    "enabled": True, "identity_references": refs[:2],
                    "expression_references": refs[2:], "label": "CREATOR LAB",
                    "variants": {
                        "A": {"clean_base": str(base_a), "strategy": "topic clarity",
                              "text_side": "top-left", "agent_identity_reviewed": True,
                              "agent_expression_reviewed": True},
                        "B": {"clean_base": str(base_b), "strategy": "human curiosity",
                              "text_side": "top-right", "agent_identity_reviewed": True,
                              "agent_expression_reviewed": True},
                    },
                }}, project_root=root, semantic_brief=semantic, output=output,
                work_dir=root / "work", runner=AdapterRunner(root / "state.json"),
                execute_external=True,
            )
            self.assertTrue(output.is_file())
            self.assertTrue((output.with_suffix(".manifest.json")).is_file())
            self.assertTrue(any(path.name == "cover-ab-report.json" for path in artifacts))


if __name__ == "__main__":
    unittest.main()
