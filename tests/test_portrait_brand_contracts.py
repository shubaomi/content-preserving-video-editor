from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portrait_brand_contracts import (  # noqa: E402
    PORTRAIT_CONTRACT_SCHEMA_NAMES,
    validate_all_portrait_schema_definitions,
    validate_portrait_contract_bundle,
    validate_portrait_contract_schema,
)


SHA = "a" * 64
DIRECTIONS = [
    "luminous_intelligence",
    "high_energy_creator",
    "humanist_cinema",
]


def _write(path: Path, data: bytes = b"evidence") -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.resolve()), "sha256": sha256(data).hexdigest()}


def _write_json(path: Path, payload: dict) -> dict[str, str]:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _write(path, data)


def _authority_row(evidence_id: str) -> dict:
    row = {
        "evidence_id": evidence_id,
        "kind": "chapter_boundary" if evidence_id == "chapter-boundary-1" else (
            "transcript_word" if evidence_id.startswith("word-") else "representative_frame"
        ),
        "status": "current",
        "source": "edl" if evidence_id == "chapter-boundary-1" else "fixture",
        "source_sha256": SHA,
        "time_domain": "output" if evidence_id == "chapter-boundary-1" else "source",
    }
    if evidence_id == "chapter-boundary-1":
        row.update({
            "window": {"start_seconds": 0.1, "end_seconds": 36.0},
            "structural": True,
        })
    row["authority_sha256"] = sha256(json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return row


def _profile() -> dict:
    return {
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
            "font_family": "HongRun Sans",
            "fallback": "sans-serif",
            "techniques": ["variable_weight", "masked_reveal"],
            "max_phrase_characters": 10,
        },
        "motion_character": {
            "traits": ["intelligent", "energetic", "human"],
            "energy_tiers": ["quiet", "micro", "meso", "macro"],
            "reduced_motion_fallback": "opacity and weight only",
        },
        "sonic_family_ids": ["PBM-S01", "PBM-S03", "PBM-S05"],
        "forbidden_defaults": [
            "product_dashboard_card",
            "fixed_cadence",
            "random_rotation",
            "caption_duplication",
        ],
        "promotion": {
            "required_real_project_count": 2,
            "required_named_user": "HongRun",
            "golden_required": True,
        },
    }


def _energy(source_ref: dict[str, str]) -> dict:
    return {
        "schema_version": 1,
        "project_id": "portrait-fixture",
        "source_media": source_ref,
        "input_hashes": {"edl": SHA, "transcript": SHA, "semantic": SHA, "evidence": SHA},
        "chapters": [{
            "chapter_id": "chapter-1",
            "output_window": {"start_seconds": 0.0, "end_seconds": 36.0},
            "entry_energy": 0.2,
            "exit_energy": 0.8,
            "intent": "rise",
            "evidence_refs": ["chapter-boundary-1"],
        }],
        "evidence_authorities": [
            _authority_row(evidence_id)
            for evidence_id in (
                "chapter-boundary-1", "word-1", "frame-1", "word-2", "frame-2", "word-3", "frame-3",
            )
        ],
        "opportunities": [
            {
                "semantic_event_id": "event-1",
                "chapter_id": "chapter-1",
                "tier": "micro",
                "transition_intent": "rise",
                "max_attention_layers": 1,
                "rationale": "A concise evidence-backed idea landing.",
                "evidence_refs": ["word-1", "frame-1"],
                "fallback_tier": "quiet",
            },
            {
                "semantic_event_id": "event-2",
                "chapter_id": "chapter-1",
                "tier": "meso",
                "transition_intent": "contrast",
                "max_attention_layers": 1,
                "rationale": "Two concepts form a real spoken contrast.",
                "evidence_refs": ["word-2", "frame-2"],
                "fallback_tier": "micro",
            },
            {
                "semantic_event_id": "quiet-1",
                "chapter_id": "chapter-1",
                "tier": "quiet",
                "transition_intent": "sustain",
                "max_attention_layers": 0,
                "rationale": "The speaker expression carries this reflective pause.",
                "evidence_refs": ["word-3", "frame-3"],
                "fallback_tier": "quiet",
            },
        ],
        "selection_policy": {
            "fixed_cadence": False,
            "minimum_event_quota": False,
            "random_rotation": False,
            "density_is_diagnostic_only": True,
        },
    }


def _motion(
    event_id: str, recipe_id: str, profile_ref: dict[str, str],
    energy_ref: dict[str, str], source_ref: dict[str, str],
) -> dict:
    copy_text = "人生无常" if event_id == "event-1" else "上半辈子与下半辈子"
    return {
        "schema_version": 1,
        "contract_id": f"portrait-{event_id}",
        "semantic_event_id": event_id,
        "brand_profile": profile_ref,
        "energy_map": energy_ref,
        "energy_tier": "micro" if event_id == "event-1" else "meso",
        "primary_recipe_id": recipe_id,
        "supporting_layers": ["ambient_light_field"],
        "approved_visible_copy": [copy_text],
        "source_window": {"start_seconds": 1.0, "end_seconds": 4.0},
        "output_window": {"start_seconds": 1.0, "end_seconds": 4.0},
        "protected_region_ids": ["face", "captions"],
        "required_capabilities": ["dom", "svg", "gsap"],
        "fallback": {"kind": "existing_portrait_typography", "target": "face_safe_phrase"},
        "input_hashes": {
            "semantic": SHA,
            "profile": profile_ref["sha256"],
            "energy": energy_ref["sha256"],
            "regions": SHA,
            "recipes": SHA,
        },
        "source_media": source_ref,
    }


def _sonic(profile_ref: dict[str, str], sonic_library_ref: dict[str, str]) -> dict:
    return {
        "schema_version": 1,
        "project_id": "portrait-fixture",
        "brand_profile": profile_ref,
        "sonic_library": sonic_library_ref,
        "motion_contract_sha256": SHA,
        "decisions": [
            {
                "event_id": "event-1",
                "recipe_id": "PBM-01",
                "decision": "intentionally_silent",
                "reason": "Dense speech makes silence safer for this idea.",
            },
            {
                "event_id": "event-2",
                "recipe_id": "PBM-04",
                "decision": "intentionally_silent",
                "reason": "The spoken contrast already has enough sonic pressure.",
            },
        ],
        "policy": {
            "decision_coverage": 1.0,
            "cue_coverage_is_adaptive": True,
            "speech_is_primary": True,
            "actual_mix_required": True,
        },
    }


def _plan(source_ref: dict[str, str], profile_ref: dict[str, str]) -> dict:
    return {
        "schema_version": 1,
        "plan_id": "style-reel-1",
        "project_id": "portrait-fixture",
        "comparison_basis": {
            "source": source_ref,
            "edl_sha256": SHA,
            "transcript_sha256": SHA,
            "semantic_event_ids": ["event-1", "event-2"],
            "caption_sha256": SHA,
            "start_seconds": 0.0,
            "end_seconds": 36.0,
            "audio_policy_sha256": SHA,
        },
        "directions": [
            {
                "direction_id": direction,
                "profile": profile_ref,
                "structural_fingerprint": sha256(direction.encode("utf-8")).hexdigest(),
                "recipe_ids": recipes,
                "energy_tiers": ["micro", "meso"],
                "macro_applicability": "not_applicable",
                "macro_reason": "The controlled source window has no chapter boundary.",
                "status": "planned",
            }
            for direction, recipes in zip(
                DIRECTIONS,
                (["PBM-01", "PBM-04"], ["PBM-01", "PBM-05"], ["PBM-02", "PBM-08"]),
            )
        ],
        "output_policy": {
            "isolated": True,
            "may_replace_automatic_master": False,
            "full_video_render_authorized": False,
        },
    }


def _review(plan_ref: dict[str, str], evidence_refs: list[dict[str, str]]) -> dict:
    return {
        "schema_version": 1,
        "review_id": "review-1",
        "plan": plan_ref,
        "reels": [
            {
                "direction_id": direction,
                "media": evidence_refs[index],
                "duration_seconds": 36.0,
                "contract_sha256": sha256(direction.encode("utf-8")).hexdigest(),
                "event_ids": ["event-1", "event-2"],
                "phase_evidence": evidence_refs,
            }
            for index, direction in enumerate(DIRECTIONS)
        ],
        "automated": {"status": "pass", "report": evidence_refs[3]},
        "multimodal": {
            "actor": "multimodal-reviewer",
            "recommendation": "recommend",
            "reason": "The comparison is technically coherent.",
            "evidence_refs": ["frame-1"],
        },
        "user": {
            "actor": "HongRun",
            "decision": "pending",
            "format_fit": "pending",
            "person_primary": "pending",
            "expressive_not_noisy": "pending",
            "semantic_help": "pending",
            "sonic_fit": "pending",
            "repeat_use_willingness": "pending",
            "reason": "",
        },
        "status": "awaiting_user",
    }


class PortraitBrandContractTests(unittest.TestCase):
    def test_canonical_hongrun_profile_v2_is_schema_valid_and_proposed(self) -> None:
        profile_path = (
            ROOT
            / "references"
            / "portrait-brand-profiles"
            / "hongrun-portrait-brand-v2.0.0.json"
        )
        self.assertTrue(profile_path.is_file())
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual([], validate_portrait_contract_schema("portrait-brand-profile", profile))
        self.assertEqual("proposed", profile["status"])
        self.assertEqual("luminous_intelligence", profile["direction"])

    def _bundle(self, root: Path) -> dict:
        source_ref = _write(root / "source.mp4", b"source")
        profile = _profile()
        profile_ref = _write_json(root / "portrait-brand-profile.json", profile)
        energy = _energy(source_ref)
        energy_ref = _write_json(root / "portrait-energy-map.json", energy)
        motions = [
            _motion("event-1", "PBM-01", profile_ref, energy_ref, source_ref),
            _motion("event-2", "PBM-04", profile_ref, energy_ref, source_ref),
        ]
        sonic_library_ref = _write_json(root / "portrait-sonic-library.json", {
            "fixture": "schema-only library authority",
        })
        sonic = _sonic(profile_ref, sonic_library_ref)
        plan = _plan(source_ref, profile_ref)
        plan_ref = _write_json(root / "style-reel-plan.json", plan)
        evidence_refs = [
            _write(root / f"evidence-{index}.bin", f"evidence-{index}".encode())
            for index in range(4)
        ]
        review = _review(plan_ref, evidence_refs)
        return {
            "portrait-brand-profile": profile,
            "portrait-energy-map": energy,
            "portrait-motion-contracts": motions,
            "portrait-sonic-plan": sonic,
            "style-reel-plan": plan,
            "style-reel-review": review,
            "artifact_paths": {
                "portrait-brand-profile": str((root / "portrait-brand-profile.json").resolve()),
                "portrait-energy-map": str((root / "portrait-energy-map.json").resolve()),
                "style-reel-plan": str((root / "style-reel-plan.json").resolve()),
            },
        }

    def test_all_six_schema_definitions_are_valid(self) -> None:
        self.assertEqual(len(PORTRAIT_CONTRACT_SCHEMA_NAMES), 6)
        self.assertEqual(validate_all_portrait_schema_definitions(), [])

    def test_valid_bundle_passes_schema_and_cross_contract_checks(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bundle = self._bundle(Path(folder))
            errors = validate_portrait_contract_bundle(
                bundle,
                expected_all_event_ids=["event-1", "event-2", "quiet-1"],
                expected_render_event_ids=["event-1", "event-2"],
                expected_visible_copy={
                    "event-1": ["人生无常"],
                    "event-2": ["上半辈子与下半辈子"],
                },
            )
            self.assertEqual(errors, [])

    def test_motion_typed_binding_requires_usable_current_authority_and_time_window(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bundle = self._bundle(Path(folder))
            authority = {
                "evidence_id": "subject-event-1", "kind": "subject_track",
                "status": "fallback_center", "source": "tracker",
                "source_sha256": SHA, "time_domain": "source", "visible": False,
                "window": {"start_seconds": 1.0, "end_seconds": 4.0},
            }
            authority["authority_sha256"] = sha256(json.dumps(
                authority, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            bundle["portrait-energy-map"]["evidence_authorities"].append(authority)
            bundle["portrait-motion-contracts"][0]["subject_binding"] = {
                key: authority[key] for key in (
                    "evidence_id", "kind", "status", "source_sha256",
                    "authority_sha256", "time_domain", "visible", "window",
                )
            }
            errors = validate_portrait_contract_bundle(
                bundle,
                expected_all_event_ids=["event-1", "event-2", "quiet-1"],
                expected_render_event_ids=["event-1", "event-2"],
                expected_visible_copy={
                    "event-1": ["人生无常"],
                    "event-2": ["上半辈子与下半辈子"],
                },
            )
            self.assertTrue(any("subject_binding is not usable" in error for error in errors))

    def test_schema_rejects_unknown_fields_and_malformed_hashes(self) -> None:
        profile = _profile()
        profile["unknown"] = True
        self.assertTrue(validate_portrait_contract_schema("portrait-brand-profile", profile))
        with tempfile.TemporaryDirectory() as folder:
            energy = _energy({"path": str((Path(folder) / "source.mp4").resolve()), "sha256": "bad"})
            self.assertTrue(validate_portrait_contract_schema("portrait-energy-map", energy))

    def test_bundle_rejects_event_drift_cadence_and_product_card_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bundle = self._bundle(Path(folder))
            bundle["portrait-energy-map"]["selection_policy"]["fixed_cadence"] = True
            bundle["portrait-motion-contracts"][0]["fallback"] = {
                "kind": "portrait_recipe",
                "target": "MQE-04-product-card",
            }
            errors = validate_portrait_contract_bundle(
                bundle,
                expected_all_event_ids=["event-1", "event-2", "quiet-1", "missing"],
                expected_render_event_ids=["event-1", "event-2"],
                expected_visible_copy={"event-1": ["人生无常"], "event-2": ["上半辈子与下半辈子"]},
            )
        joined = "\n".join(errors)
        self.assertIn("fixed cadence", joined)
        self.assertIn("semantic opportunity set", joined)
        self.assertIn("product-card fallback", joined)

    def test_bundle_rejects_relative_or_stale_file_references(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bundle = self._bundle(Path(folder))
            bundle["portrait-brand-profile"]["palettes"]["light"]["ink"] = "#111111"
            bundle["style-reel-plan"]["comparison_basis"]["source"]["path"] = "source.mp4"
            errors = validate_portrait_contract_bundle(
                bundle,
                expected_all_event_ids=["event-1", "event-2", "quiet-1"],
                expected_render_event_ids=["event-1", "event-2"],
                expected_visible_copy={"event-1": ["人生无常"], "event-2": ["上半辈子与下半辈子"]},
            )
        joined = "\n".join(errors)
        self.assertIn("hash is stale", joined)
        self.assertIn("must be absolute", joined)

    def test_bundle_rejects_actor_spoof_and_stale_or_incomplete_approval(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bundle = self._bundle(Path(folder))
            review = bundle["style-reel-review"]
            review["user"] = {
                "actor": "Agent",
                "decision": "select",
                "selected_direction_id": "luminous_intelligence",
                "format_fit": "yes",
                "person_primary": "yes",
                "expressive_not_noisy": "yes",
                "semantic_help": "yes",
                "sonic_fit": "yes",
                "repeat_use_willingness": "yes",
                "reason": "Looks reusable.",
                "reviewed_at": "2026-08-12T05:00:00-07:00",
            }
            review["status"] = "approved"
            errors = validate_portrait_contract_bundle(
                bundle,
                expected_all_event_ids=["event-1", "event-2", "quiet-1"],
                expected_render_event_ids=["event-1", "event-2"],
                expected_visible_copy={"event-1": ["人生无常"], "event-2": ["上半辈子与下半辈子"]},
            )
        self.assertIn("HongRun", "\n".join(errors))

    def test_style_reel_comparison_rejects_direction_or_event_drift(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bundle = self._bundle(Path(folder))
            bundle["style-reel-plan"]["directions"][2]["structural_fingerprint"] = (
                bundle["style-reel-plan"]["directions"][1]["structural_fingerprint"]
            )
            bundle["style-reel-review"]["reels"][2]["event_ids"] = ["event-1", "other"]
            errors = validate_portrait_contract_bundle(
                bundle,
                expected_all_event_ids=["event-1", "event-2", "quiet-1"],
                expected_render_event_ids=["event-1", "event-2"],
                expected_visible_copy={"event-1": ["人生无常"], "event-2": ["上半辈子与下半辈子"]},
            )
        joined = "\n".join(errors)
        self.assertIn("structural fingerprints", joined)
        self.assertIn("reel event IDs", joined)


if __name__ == "__main__":
    unittest.main()
