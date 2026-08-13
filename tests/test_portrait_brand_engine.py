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

from portrait_brand_engine import (  # noqa: E402
    PortraitBrandCompilationError,
    build_portrait_energy_authorities,
    compile_portrait_energy_map,
    derive_portrait_chapters,
    evaluate_portrait_eligibility,
)


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _authority(
    evidence_id: str, kind: str = "representative_frame", *,
    start: float = 0.0, end: float = 20.0, source: str = "test", **extra: object,
) -> dict:
    row = {
        "evidence_id": evidence_id,
        "kind": kind,
        "status": "current",
        "source": source,
        "source_sha256": _sha("test-source"),
        "window": {"start_seconds": start, "end_seconds": end},
        "time_domain": extra.pop("time_domain", "source"),
        **extra,
    }
    row["authority_sha256"] = sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
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
        "forbidden_defaults": ["product_card", "fixed_cadence", "random_rotation", "caption_duplication"],
        "promotion": {
            "required_real_project_count": 2,
            "required_named_user": "HongRun",
            "golden_required": True,
        },
    }


def _project() -> dict:
    return {
        "schema_version": 11,
        "version": 11,
        "identity": {"mode": "self"},
        "source": {"content_type": "talking_head"},
        "motion_quality": {
            "enabled": True,
            "portrait_brand": {
                "enabled": True,
                "profile_path": "profile.json",
                "grammar_version": 2,
                "style_direction": "luminous_intelligence",
                "require_user_brand_approval": True,
                "style_reel": {
                    "enabled": True,
                    "target_duration_seconds": 38.0,
                    "directions": [
                        "luminous_intelligence",
                        "high_energy_creator",
                        "humanist_cinema",
                    ],
                },
            },
        },
    }


def _brief() -> dict:
    return {
        "schema_version": 3,
        "opportunity_model": "decision_complete_v1",
        "events": [
            {
                "id": "event-1",
                "decision": "render",
                "source_start": 1.0,
                "source_end": 3.0,
                "output_start": 1.0,
                "output_end": 3.0,
                "transcript_word_ids": ["w1", "w2"],
                "portrait_energy_intent": {
                    "chapter_id": "chapter-1",
                    "tier": "micro",
                    "transition_intent": "rise",
                    "max_attention_layers": 1,
                    "rationale": "The concise realization deserves one precise visual landing.",
                    "evidence_refs": ["frame-1", "words-1"],
                    "fallback_tier": "quiet",
                    "signals": {
                        "semantic_pressure": 0.7,
                        "emotional_turn": "realization",
                        "speech_rate_wpm": 168.0,
                        "pause_seconds": 0.2,
                        "gesture_evidence_id": None,
                        "chapter_boundary_evidence_id": None,
                    },
                },
            },
            {
                "id": "event-2",
                "decision": "render",
                "source_start": 7.0,
                "source_end": 11.0,
                "output_start": 7.0,
                "output_end": 11.0,
                "transcript_word_ids": ["w3", "w4", "w5"],
                "portrait_energy_intent": {
                    "chapter_id": "chapter-1",
                    "tier": "meso",
                    "transition_intent": "contrast",
                    "max_attention_layers": 1,
                    "rationale": "A genuine two-part contrast needs spatial structure.",
                    "evidence_refs": ["frame-2", "words-2"],
                    "fallback_tier": "micro",
                    "signals": {
                        "semantic_pressure": 0.85,
                        "emotional_turn": "contrast",
                        "speech_rate_wpm": 142.0,
                        "pause_seconds": 0.45,
                        "gesture_evidence_id": None,
                        "chapter_boundary_evidence_id": None,
                    },
                },
            },
            {
                "id": "quiet-1",
                "decision": "quiet_source",
                "source_start": 12.0,
                "source_end": 17.0,
                "output_start": 12.0,
                "output_end": 17.0,
                "transcript_word_ids": ["w6"],
                "portrait_energy_intent": {
                    "chapter_id": "chapter-1",
                    "tier": "quiet",
                    "transition_intent": "sustain",
                    "max_attention_layers": 0,
                    "rationale": "The reflective expression and pause should remain person-led.",
                    "evidence_refs": ["frame-3", "words-3"],
                    "fallback_tier": "quiet",
                    "signals": {
                        "semantic_pressure": 0.25,
                        "emotional_turn": "reflection",
                        "speech_rate_wpm": 92.0,
                        "pause_seconds": 0.9,
                        "gesture_evidence_id": None,
                        "chapter_boundary_evidence_id": None,
                    },
                },
            },
        ],
    }


class PortraitBrandEngineTests(unittest.TestCase):
    def test_authorities_and_chapters_are_current_and_deterministic(self) -> None:
        authorities = build_portrait_energy_authorities(
            transcript={"words": [
                {"id": "w1", "text": "one", "start": 1.0, "end": 1.2},
                {"id": "w2", "text": "two", "start": 1.3, "end": 1.5},
            ]},
            evidence_bundle={"representative_frames": [{
                "path": "C:/frame.png", "sha256": _sha("frame"),
                "timestamp_seconds": 1.0,
            }]},
        )
        self.assertIn("w1", authorities["known_evidence_ids"])
        frame_id = f"frame:{_sha('frame')[:16]}"
        self.assertIn(frame_id, authorities["known_evidence_ids"])
        brief = _brief()
        for event in brief["events"]:
            event["portrait_energy_intent"]["evidence_refs"] = ["w1"]
        chapters = derive_portrait_chapters(
            brief, evidence_authorities=authorities["evidence_by_id"],
        )
        self.assertEqual(chapters[0]["chapter_id"], "chapter-1")
        self.assertEqual(chapters[0]["output_window"], {
            "start_seconds": 1.0, "end_seconds": 17.0,
        })
        self.assertEqual(chapters[0]["evidence_refs"], ["w1"])

    def test_eligibility_requires_explicit_hongrun_self_talking_head(self) -> None:
        eligible = evaluate_portrait_eligibility(
            project=_project(),
            profile=_profile(),
            source_media={"orientation": "portrait", "source_type": "talking_head"},
        )
        self.assertEqual(eligible["status"], "eligible")
        self.assertEqual(eligible["grammar_id"], "hongrun-portrait-expressive-v2")

        cases = (
            ({**_project(), "identity": {"mode": "third_party"}}, "identity.mode"),
            (_project(), "source orientation"),
            (_project(), "source type"),
        )
        media = (
            {"orientation": "portrait", "source_type": "talking_head"},
            {"orientation": "landscape", "source_type": "talking_head"},
            {"orientation": "portrait", "source_type": "screen_recording"},
        )
        for (project, reason), source in zip(cases, media):
            with self.subTest(reason=reason):
                result = evaluate_portrait_eligibility(
                    project=project, profile=_profile(), source_media=source,
                )
                self.assertEqual(result["status"], "not_eligible")
                self.assertIn(reason, " ".join(result["reasons"]))

    def test_identical_inputs_compile_to_identical_energy_map(self) -> None:
        kwargs = {
            "project_id": "portrait-fixture",
            "semantic_brief": _brief(),
            "source_media": {"path": "C:/source.mp4", "sha256": _sha("source")},
            "input_hashes": {
                "edl": _sha("edl"),
                "transcript": _sha("transcript"),
                "semantic": _sha("semantic"),
                "evidence": _sha("evidence"),
            },
            "chapters": [{
                "chapter_id": "chapter-1",
                "output_window": {"start_seconds": 0.0, "end_seconds": 20.0},
                "entry_energy": 0.2,
                "exit_energy": 0.7,
                "intent": "rise",
                "evidence_refs": ["chapter-1-evidence"],
            }],
            "evidence_authorities": {
                value: _authority(value)
                for value in {
                    "frame-1", "words-1", "frame-2", "words-2", "frame-3", "words-3",
                    "chapter-1-evidence",
                }
            },
        }
        first = compile_portrait_energy_map(**kwargs)
        second = compile_portrait_energy_map(**copy.deepcopy(kwargs))
        self.assertEqual(first, second)
        self.assertEqual(
            [row["semantic_event_id"] for row in first["energy_map"]["opportunities"]],
            ["event-1", "event-2", "quiet-1"],
        )
        self.assertEqual(first["selection_inputs"], "explicit_portrait_energy_intent_only")
        self.assertFalse(first["fixed_cadence_used"])
        self.assertFalse(first["quota_used"])
        self.assertFalse(first["keyword_selection_used"])
        self.assertFalse(first["random_selection_used"])
        self.assertFalse(first["sfx_selection_used"])

    def test_energy_compiler_rejects_missing_opportunity_or_unknown_evidence(self) -> None:
        brief = _brief()
        brief["events"][1].pop("portrait_energy_intent")
        with self.assertRaisesRegex(PortraitBrandCompilationError, "event-2"):
            compile_portrait_energy_map(
                project_id="portrait-fixture",
                semantic_brief=brief,
                source_media={"path": "C:/source.mp4", "sha256": _sha("source")},
                input_hashes={"edl": _sha("e"), "transcript": _sha("t"), "semantic": _sha("s"), "evidence": _sha("v")},
                chapters=[{
                    "chapter_id": "chapter-1",
                    "output_window": {"start_seconds": 0.0, "end_seconds": 20.0},
                    "entry_energy": 0.2,
                    "exit_energy": 0.7,
                    "intent": "rise",
                    "evidence_refs": ["chapter-1-evidence"],
                }],
                evidence_authorities={
                    value: _authority(value)
                    for value in {
                        "frame-1", "words-1", "frame-2", "words-2",
                        "frame-3", "words-3", "chapter-1-evidence",
                    }
                },
            )

    def test_macro_requires_structural_boundary_evidence(self) -> None:
        brief = _brief()
        intent = brief["events"][0]["portrait_energy_intent"]
        intent["tier"] = "macro"
        intent["fallback_tier"] = "meso"
        with self.assertRaisesRegex(PortraitBrandCompilationError, "macro"):
            self._compile(brief)

        intent["signals"]["chapter_boundary_evidence_id"] = "chapter-boundary-1"
        intent["evidence_refs"].append("chapter-boundary-1")
        result = self._compile(brief, extra_evidence={
            "chapter-boundary-1": _authority(
                "chapter-boundary-1", "chapter_boundary", start=1.0, end=3.0,
                source="edl", time_domain="output", structural=True,
                chapter_id="chapter-1",
            )
        })
        self.assertEqual(result["energy_map"]["opportunities"][0]["tier"], "macro")

    def test_macro_boundary_must_bind_the_same_chapter(self) -> None:
        brief = _brief()
        intent = brief["events"][0]["portrait_energy_intent"]
        intent["tier"] = "macro"
        intent["fallback_tier"] = "meso"
        intent["signals"]["chapter_boundary_evidence_id"] = "wrong-chapter-boundary"
        intent["evidence_refs"].append("wrong-chapter-boundary")
        with self.assertRaisesRegex(PortraitBrandCompilationError, "chapter boundary"):
            self._compile(brief, extra_evidence={
                "wrong-chapter-boundary": _authority(
                    "wrong-chapter-boundary", "chapter_boundary",
                    start=1.0, end=3.0, source="edl", time_domain="output",
                    structural=True, chapter_id="totally-other-chapter",
                )
            })

    def test_energy_compiler_rejects_reversed_source_window(self) -> None:
        brief = _brief()
        brief["events"][0]["source_start"] = 3.0
        brief["events"][0]["source_end"] = 1.0
        with self.assertRaisesRegex(PortraitBrandCompilationError, "source window"):
            self._compile(brief)

    def test_gesture_intent_requires_current_gesture_evidence(self) -> None:
        brief = _brief()
        signals = brief["events"][0]["portrait_energy_intent"]["signals"]
        signals["gesture_evidence_id"] = "gesture-1"
        with self.assertRaisesRegex(PortraitBrandCompilationError, "gesture-1"):
            self._compile(brief)
        brief["events"][0]["portrait_energy_intent"]["evidence_refs"].append("gesture-1")
        result = self._compile(brief, extra_evidence={
            "gesture-1": _authority(
                "gesture-1", "gesture_track", start=1.0, end=3.0,
                status="tracked", visible=True, points=[[0.2, 0.4], [0.4, 0.3]],
            )
        })
        self.assertEqual(
            result["diagnostics"][0]["signals"]["gesture_evidence_id"], "gesture-1"
        )

    def test_speech_rate_changes_do_not_silently_change_authoritative_tier(self) -> None:
        brief = _brief()
        first = self._compile(brief)
        brief["events"][0]["portrait_energy_intent"]["signals"]["speech_rate_wpm"] = 235.0
        second = self._compile(brief)
        self.assertEqual(
            first["energy_map"]["opportunities"][0]["tier"],
            second["energy_map"]["opportunities"][0]["tier"],
        )
        self.assertNotEqual(first["diagnostics"], second["diagnostics"])

    def test_transcript_word_cannot_impersonate_gesture_or_boundary(self) -> None:
        brief = _brief()
        intent = brief["events"][0]["portrait_energy_intent"]
        intent["tier"] = "macro"
        intent["fallback_tier"] = "meso"
        intent["signals"]["gesture_evidence_id"] = "words-1"
        intent["signals"]["chapter_boundary_evidence_id"] = "words-1"
        with self.assertRaisesRegex(PortraitBrandCompilationError, "gesture evidence"):
            self._compile(brief)

    def test_real_tracker_series_is_typed_subject_not_gesture(self) -> None:
        authorities = build_portrait_energy_authorities(
            transcript={"words": []}, evidence_bundle={"representative_frames": []},
            subject_track={"tracking": {"sample_interval": 0.4, "series": [{
                "time": 1.0, "status": "tracked", "face": {"x": 0.3, "y": 0.2, "w": 0.2, "h": 0.2},
                "smoothed_center": [0.4, 0.3], "crop": {"x": 0.1},
            }]}},
        )
        self.assertEqual(authorities["evidence_by_id"]["subject:0"]["kind"], "subject_track")
        self.assertNotEqual(authorities["evidence_by_id"]["subject:0"]["kind"], "gesture_track")
        self.assertEqual(authorities["evidence_by_id"]["subject:0"]["time_domain"], "source")

    def test_gesture_apex_is_mapped_from_source_to_current_output_timeline(self) -> None:
        authorities = build_portrait_energy_authorities(
            transcript={"words": []},
            evidence_bundle={"representative_frames": []},
            subject_track={"gesture_observations": [{
                "id": "gesture-1",
                "window": {"start_seconds": 100.8, "end_seconds": 101.2},
                "apex_seconds": 101.0,
                "visible": True,
                "status": "tracked",
                "points": [[0.2, 0.4], [0.4, 0.3]],
            }]},
            edl={"segments": [{
                "source": "source.mp4", "start": 100.0, "end": 105.0,
                "timeline_start": 2.0,
            }]},
            source_hashes={"subject_track": _sha("track"), "edl": _sha("edl")},
        )
        row = authorities["evidence_by_id"]["gesture-1"]
        self.assertEqual(row["source_apex_seconds"], 101.0)
        self.assertEqual(row["output_apex_seconds"], 3.0)

    def test_semantic_brief_cannot_self_authorize_a_macro_boundary(self) -> None:
        brief = _brief()
        intent = brief["events"][0]["portrait_energy_intent"]
        intent["tier"] = "macro"
        intent["fallback_tier"] = "meso"
        intent["signals"]["chapter_boundary_evidence_id"] = "self-boundary"
        intent["evidence_refs"].append("self-boundary")
        authorities = build_portrait_energy_authorities(
            transcript={"words": []}, evidence_bundle={"representative_frames": []},
            semantic_brief=brief,
        )
        self.assertNotIn("self-boundary", authorities["evidence_by_id"])

    def test_edl_supplies_independent_output_time_boundary_authority(self) -> None:
        authorities = build_portrait_energy_authorities(
            transcript={"words": []}, evidence_bundle={"representative_frames": []},
            edl={"chapter_boundaries": [{
                "id": "boundary-1", "output_time": 1.0, "source_time": 100.0,
                "chapter_id": "chapter-1",
            }]},
            source_hashes={"edl": _sha("edl")},
        )
        row = authorities["evidence_by_id"]["boundary-1"]
        self.assertEqual(row["source"], "edl")
        self.assertEqual(row["time_domain"], "output")
        self.assertTrue(row["structural"])

    def test_source_time_gesture_must_overlap_event_source_window(self) -> None:
        brief = _brief()
        event = brief["events"][0]
        event.update({"source_start": 100.0, "source_end": 102.0, "output_start": 1.0, "output_end": 3.0})
        signals = event["portrait_energy_intent"]["signals"]
        signals["gesture_evidence_id"] = "gesture-wrong-source"
        event["portrait_energy_intent"]["evidence_refs"].append("gesture-wrong-source")
        with self.assertRaisesRegex(PortraitBrandCompilationError, "gesture"):
            self._compile(brief, extra_evidence={
                "gesture-wrong-source": _authority(
                    "gesture-wrong-source", "gesture_track", start=1.4, end=1.6,
                    time_domain="source", status="tracked", visible=True,
                    points=[[0.2, 0.4], [0.4, 0.3]],
                )
            })

    def test_nested_malformed_inputs_fail_closed(self) -> None:
        with self.assertRaisesRegex(PortraitBrandCompilationError, "chapters"):
            compile_portrait_energy_map(
                project_id="portrait-fixture", semantic_brief=_brief(),
                source_media={"path": "C:/source.mp4", "sha256": _sha("source")},
                input_hashes={"a": _sha("a"), "b": _sha("b"), "c": _sha("c"), "d": _sha("d")},
                chapters=None, evidence_authorities={},
            )
        with self.assertRaisesRegex(PortraitBrandCompilationError, "transcript.words"):
            build_portrait_energy_authorities(
                transcript={"words": "oops"}, evidence_bundle={"representative_frames": []},
            )
        for field in ("evidence_refs", "transcript_word_ids"):
            brief = _brief()
            target = (
                brief["events"][0]["portrait_energy_intent"]
                if field == "evidence_refs" else brief["events"][0]
            )
            target[field] = 1
            with self.subTest(field=field), self.assertRaisesRegex(
                PortraitBrandCompilationError, field
            ):
                self._compile(brief)
        for subject_track, expected in (
            ({"tracking": {"series": "oops"}}, "tracking.series"),
            ({"gesture_observations": 1}, "gesture_observations"),
            ({"hand_tracking": {"series": "oops"}}, "hand_tracking.series"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(
                PortraitBrandCompilationError, expected
            ):
                build_portrait_energy_authorities(
                    transcript={"words": []}, evidence_bundle={"representative_frames": []},
                    subject_track=subject_track,
                )

    def test_public_payloads_fail_closed(self) -> None:
        self.assertEqual(
            evaluate_portrait_eligibility(project=[], profile={}, source_media={})["status"],
            "not_eligible",
        )
        with self.assertRaisesRegex(PortraitBrandCompilationError, "transcript"):
            build_portrait_energy_authorities(transcript=[], evidence_bundle={})

    def _compile(self, brief: dict, *, extra_evidence: dict[str, dict] | None = None) -> dict:
        authority_ids = {
            "frame-1", "words-1", "frame-2", "words-2", "frame-3", "words-3",
            "chapter-1-evidence",
        }
        authorities = {value: _authority(value) for value in authority_ids}
        authorities.update(extra_evidence or {})
        return compile_portrait_energy_map(
            project_id="portrait-fixture",
            semantic_brief=brief,
            source_media={"path": "C:/source.mp4", "sha256": _sha("source")},
            input_hashes={
                "edl": _sha("e"),
                "transcript": _sha("t"),
                "semantic": _sha("s"),
                "evidence": _sha("v"),
            },
            chapters=[{
                "chapter_id": "chapter-1",
                "output_window": {"start_seconds": 0.0, "end_seconds": 20.0},
                "entry_energy": 0.2,
                "exit_energy": 0.7,
                "intent": "rise",
                "evidence_refs": ["chapter-1-evidence"],
            }],
            evidence_authorities=authorities,
        )


if __name__ == "__main__":
    unittest.main()
