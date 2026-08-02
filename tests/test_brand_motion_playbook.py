from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brand_motion_playbook import compile_playbook, validate_playbook  # noqa: E402


class BrandMotionPlaybookTests(unittest.TestCase):
    def test_compiler_maps_design_profile_orientation_and_motion_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tokens = root / "design-tokens.json"
            tokens.write_text(json.dumps({
                "schema_version": 1,
                "sampling": {"dimensions": {"width": 1080, "height": 1920}},
                "surface": {"color": "#f8fafc", "text_color": "#172033"},
                "accent": {"color": "#22c55e"},
                "shape": {"border_radius_px": 20, "line_width_px": 2},
                "shadow": {"css": "0 8px 24px rgba(0,0,0,.12)"},
                "typography": {"font_family": "system-ui"},
                "safe_zones": {"content": {"x0": .06, "y0": .08, "x1": .94, "y1": .72}},
            }), encoding="utf-8")
            brief = root / "brief.json"
            brief.write_text(json.dumps({"topic": "ExplainIt", "events": []}), encoding="utf-8")
            profile = root / "profile.yaml"
            profile.write_text("profile_id: hongrun\nvoice: practical\n", encoding="utf-8")
            outputs = compile_playbook(
                project={"video_id": "explainit", "brand": {"motion_playbook": {
                    "enabled": True, "motion": {"speed": "brisk", "easing": "ease-out"},
                }}},
                design_tokens_path=tokens, semantic_brief_path=brief,
                profile_path=profile, output_dir=root / "playbook",
            )
            playbook = json.loads(outputs[0].read_text(encoding="utf-8"))
            self.assertEqual(playbook["orientation"], "portrait")
            self.assertEqual(playbook["tokens"]["radius_px"], 20)
            self.assertEqual(playbook["motion_tokens"]["easing"], "ease-out")
            self.assertIn("--hr-accent: #22c55e", outputs[1].read_text(encoding="utf-8"))
            self.assertEqual(validate_playbook(playbook), [])

    def test_field_mapping_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tokens = root / "tokens.json"
            tokens.write_text(json.dumps({
                "sampling": {"dimensions": {"width": 1920, "height": 1080}},
                "surface": {"color": "#fff", "text_color": "#000"},
                "accent": {"color": "#0f0"}, "shape": {}, "shadow": {},
                "typography": {}, "safe_zones": {},
            }), encoding="utf-8")
            brief = root / "brief.json"
            brief.write_text('{"events":[]}', encoding="utf-8")
            playbook_path, _, _ = compile_playbook(
                project={}, design_tokens_path=tokens, semantic_brief_path=brief,
                profile_path=None, output_dir=root / "out",
            )
            playbook = json.loads(playbook_path.read_text(encoding="utf-8"))
            playbook["field_mapping"].pop("surface.color")
            self.assertTrue(validate_playbook(playbook))


if __name__ == "__main__":
    unittest.main()
