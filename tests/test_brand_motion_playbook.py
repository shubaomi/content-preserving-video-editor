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

    def test_portrait_v2_profile_compiles_role_specific_brand_language(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tokens = root / "tokens.json"
            tokens.write_text(json.dumps({
                "sampling": {"dimensions": {"width": 1080, "height": 1920}},
                "surface": {"color": "#f8fafc", "text_color": "#172033"},
                "accent": {"color": "#22d3ee"}, "shape": {}, "shadow": {},
                "typography": {}, "safe_zones": {},
            }), encoding="utf-8")
            brief = root / "brief.json"
            brief.write_text('{"topic":"portrait","events":[]}', encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": 1,
                "profile_id": "hongrun",
                "profile_version": "2.0.0",
                "identity_mode": "self",
                "status": "proposed",
                "direction": "luminous_intelligence",
                "signature_primitives": ["pulse_dot", "orbit_trace", "focus_beam"],
                "palettes": {
                    "light": {"canvas": "#F7F7F2", "ink": "#102A2A", "mint": "#2DD4BF", "cyan": "#22D3EE"},
                    "dark": {"canvas": "#071A1A", "ink": "#F8FAFC", "mint": "#34D399", "cyan": "#22D3EE"},
                },
                "typography": {
                    "font_family": "HongRun Sans", "fallback": "sans-serif",
                    "techniques": ["variable_weight", "masked_reveal"], "max_phrase_characters": 10,
                },
                "motion_character": {
                    "traits": ["intelligent", "energetic", "human"],
                    "energy_tiers": ["quiet", "micro", "meso", "macro"],
                    "reduced_motion_fallback": "opacity and weight only",
                },
                "sonic_family_ids": ["PBM-S01", "PBM-S03", "PBM-S05"],
                "forbidden_defaults": ["product_card", "fixed_cadence", "random_rotation", "caption_duplication"],
                "promotion": {"required_real_project_count": 2, "required_named_user": "HongRun", "golden_required": True},
            }), encoding="utf-8")
            project = {
                "schema_version": 11,
                "version": 11,
                "video_id": "portrait",
                "identity": {"mode": "self"},
                "source": {"content_type": "talking_head"},
                "motion_quality": {"enabled": True, "portrait_brand": {
                    "enabled": True,
                    "profile_path": str(profile),
                    "grammar_version": 2,
                    "style_direction": "luminous_intelligence",
                    "require_user_brand_approval": True,
                    "style_reel": {"enabled": True, "target_duration_seconds": 38.0, "directions": [
                        "luminous_intelligence", "high_energy_creator", "humanist_cinema",
                    ]},
                }},
            }
            playbook_path, _, _ = compile_playbook(
                project=project,
                design_tokens_path=tokens,
                semantic_brief_path=brief,
                profile_path=profile,
                output_dir=root / "out",
            )
            playbook = json.loads(playbook_path.read_text(encoding="utf-8"))
            portrait = playbook["portrait_brand"]
            self.assertEqual(portrait["grammar_id"], "hongrun-portrait-expressive-v2")
            self.assertEqual(portrait["direction"], "luminous_intelligence")
            self.assertEqual(set(portrait["role_motion_grammar"]), {
                "mark", "explain", "relate", "sequence", "prove", "resolve", "transition",
            })
            self.assertNotEqual(
                portrait["role_motion_grammar"]["mark"],
                portrait["role_motion_grammar"]["transition"],
            )
            self.assertIn("product_card", portrait["forbidden_defaults"])
            self.assertEqual(validate_playbook(playbook, project=project), [])


if __name__ == "__main__":
    unittest.main()
