from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_adapters import AdapterRunner  # noqa: E402
from ip_production import IpProductionActionRequired, produce_ip_components  # noqa: E402


class IpProductionTests(unittest.TestCase):
    def test_no_ip_semantic_opportunity_is_explicitly_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            brief = root / "brief.json"
            brief.write_text(json.dumps({"events": [{"id": "e1", "form": "process"}]}), encoding="utf-8")
            artifacts = produce_ip_components(
                project={}, project_root=root, semantic_brief=brief,
                design_tokens=root / "tokens.json", output_dir=root / "ip",
                runner=AdapterRunner(root / "state.json"), execute_external=False,
            )
            decision = json.loads(artifacts[0].read_text(encoding="utf-8"))
            self.assertEqual(decision["status"], "not_applicable")

    def test_missing_theme_asset_for_selected_ip_event_requires_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            brief = root / "brief.json"
            brief.write_text(json.dumps({"events": [{
                "id": "e1", "form": "ip_asset", "viewer_takeaway": "compare two systems",
                "visual_mechanism": "creator balances two choices",
            }]}), encoding="utf-8")
            with self.assertRaises(IpProductionActionRequired) as caught:
                produce_ip_components(
                    project={}, project_root=root, semantic_brief=brief,
                    design_tokens=root / "tokens.json", output_dir=root / "ip",
                    runner=AdapterRunner(root / "state.json"), execute_external=False,
                )
            self.assertEqual(caught.exception.packet["events"][0]["event_id"], "e1")
            self.assertTrue(caught.exception.packet["transparent_or_scene_matched"])

    def test_reviewed_theme_asset_is_prepared_and_bound_to_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "asset.png"
            Image.new("RGB", (320, 320), "white").save(source)
            brief = root / "brief.json"
            brief.write_text(json.dumps({"events": [{
                "id": "e1", "form": "ip_asset", "viewer_takeaway": "compare two systems",
                "visual_mechanism": "creator balances two choices",
            }]}), encoding="utf-8")
            tokens = root / "tokens.json"
            tokens.write_text(json.dumps({"surface": {"color": "#f7f8f4"}}), encoding="utf-8")
            project = {"visuals": {"ip_assets": {"e1": {
                "source": str(source), "role": "character",
                "semantic_match": "compare two systems",
                "information_overlap_with_motion": False,
                "anatomy_review": {"complete_frame": True, "hands_valid": True,
                                   "limbs_valid": True, "no_extra_appendages": True},
            }}}}
            artifacts = produce_ip_components(
                project=project, project_root=root, semantic_brief=brief,
                design_tokens=tokens, output_dir=root / "ip",
                runner=AdapterRunner(root / "state.json"), execute_external=True,
            )
            binding = json.loads((root / "ip" / "ip-asset-binding.json").read_text(encoding="utf-8"))
            self.assertEqual(binding["bindings"][0]["event_id"], "e1")
            self.assertTrue(binding["passed"])
            self.assertTrue(any(path.name == "ip-components.json" for path in artifacts))


if __name__ == "__main__":
    unittest.main()
