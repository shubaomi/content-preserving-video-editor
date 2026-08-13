from __future__ import annotations

import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portrait_golden import (  # noqa: E402
    PortraitGoldenError,
    _fresh_phase_snapshot_errors,
    _fresh_renderer_runtime_errors,
    _phase_candidate_binding_errors,
    _renderer_runtime_observation_errors,
    _second_topic_decision_errors,
    _second_topic_technical_errors,
    _stable_hash,
    build_retained_real_project_portrait_validation,
    build_real_project_portrait_validation,
    portrait_implementation_sha256,
    validate_retained_real_project_portrait_validation,
    validate_real_project_portrait_validation,
    validate_portrait_preference_candidate,
    validate_provisional_portrait_golden,
)


def _write(path: Path, value: bytes = b"evidence") -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return {"path": str(path.resolve()), "sha256": sha256(value).hexdigest()}


class PortraitGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _golden(self) -> dict:
        profile_source = _write(self.root / "profile-source.json", b"{}")
        profile_snapshot_path = self.root / "profile-snapshot.json"
        profile_snapshot = {
            "schema_version": 1, "profile_id": "hongrun", "profile_version": "2.0.0",
            "identity_mode": "self", "status": "provisional_golden",
            "direction": "luminous_intelligence", "signature_primitives": ["pulse_dot", "orbit_trace"],
            "palettes": {"light": {"canvas": "#ffffff", "ink": "#111111", "mint": "#00ffaa", "cyan": "#00ccff", "amber": "#ffaa00", "violet": "#8855ff"},
                         "dark": {"canvas": "#000000", "ink": "#ffffff", "mint": "#00ffaa", "cyan": "#00ccff", "warm": "#ffcc88", "violet": "#aa88ff"}},
            "typography": {"font_family": "Noto Sans SC", "fallback": "sans-serif", "techniques": ["variable_weight"], "max_phrase_characters": 10},
            "motion_character": {"traits": ["intelligent"], "energy_tiers": ["quiet", "micro", "meso", "macro"], "reduced_motion_fallback": "opacity only"},
            "sonic_family_ids": ["PBM-S01"], "forbidden_defaults": ["product_dashboard_card"],
            "promotion": {"required_real_project_count": 2, "required_named_user": "HongRun", "golden_required": True},
        }
        profile_snapshot_path.write_text(json.dumps(profile_snapshot), encoding="utf-8")
        profile_snapshot_ref = {
            "path": str(profile_snapshot_path.resolve()),
            "sha256": sha256(profile_snapshot_path.read_bytes()).hexdigest(),
        }
        generic = lambda name: _write(self.root / name)
        phases = [generic(f"phase-{index}.png") for index in range(4)]
        body = {
            "schema_version": 1, "kind": "hongrun_portrait_brand_provisional_golden",
            "status": "provisional_golden", "golden_id": "fixture-golden",
            "created_at": "2026-08-12T00:00:00+00:00", "project_id": "fixture",
            "selected_direction_id": "luminous_intelligence",
            "profile": {"source": profile_source, "snapshot": profile_snapshot_ref,
                        "profile_id": "hongrun", "profile_version": "2.0.0", "status": "provisional_golden"},
            "configuration": generic("project.yaml"),
            "approval": {"pending_review": generic("pending.json"), "approved_review": generic("approved.json"),
                         "decision_receipt": generic("decision.json"), "wp6_review_package": generic("package.json"),
                         "actor": "HongRun", "answers": {"format_fit": "yes"}, "reason": "ok", "reviewed_at": "now"},
            "selected_style_reel": {"plan": generic("plan.json"), "authority_manifest": generic("authorities.json"),
                                    "contract": generic("contract.json"), "media": generic("media.mp4"),
                                    "phase_evidence": phases, "structural_fingerprint": "a" * 64,
                                    "observable_phase_inventory_sha256": _stable_hash(phases),
                                    "technical_evidence": generic("technical.json"), "hyperframes_index": generic("index.html"),
                                    "hyperframes_check": generic("check.json"), "visual_render": generic("render.mp4"), "post_exit": []},
            "audio_identity": {"audio_plan": generic("audio.json"), "sonic_plan": generic("sonic.json"),
                               "auditions": [{"event_id": "e1", "voice_sfx_off": generic("off.wav"),
                                              "sfx_on": generic("on.wav"), "receipt": generic("audition.json")}]},
            "implementation": {"repository": str(ROOT), "base_commit": "a" * 40,
                               "source_tree_sha256": "b" * 64, "commit_contains_current_implementation": False,
                               "portrait_implementation_sha256": "c" * 64,
                               "commit_deferred_until_wp9": True},
            "promotion": {"real_project_validation_count": 1, "required_real_project_count": 2,
                          "production_default": False, "next_gate": "second"},
            "explicit_limitations": ["provisional"],
        }
        return {**body, "integrity_sha256": _stable_hash(body)}

    @patch("portrait_golden._git_head", return_value="a" * 40)
    @patch("portrait_golden._git_is_ancestor", return_value=True)
    @patch("portrait_golden.portrait_implementation_sha256", return_value="c" * 64)
    @patch("portrait_golden.source_tree_sha256", return_value="b" * 64)
    @patch("portrait_golden.validate_portrait_contract_schema", return_value=[])
    def test_provisional_golden_is_current_but_never_production_default(
        self, _schema, _tree, _portrait_tree, _ancestor, _head,
    ) -> None:
        golden = self._golden()
        self.assertEqual([], validate_provisional_portrait_golden(golden, repository_root=ROOT))
        golden["promotion"]["production_default"] = True
        golden["integrity_sha256"] = _stable_hash({
            key: value for key, value in golden.items() if key != "integrity_sha256"
        })
        self.assertIn("promotion boundary", "\n".join(
            validate_provisional_portrait_golden(golden, repository_root=ROOT)
        ))

    def test_preference_candidate_is_explicit_pending_and_never_auto_applies(self) -> None:
        golden_ref = _write(self.root / "golden.json")
        receipt_ref = _write(self.root / "decision.json")
        body = {
            "schema_version": 1, "kind": "hongrun_portrait_brand_preference_candidate",
            "status": "pending_second_topic_validation", "candidate_id": "candidate-1",
            "created_at": "2026-08-12T00:00:00+00:00", "profile_id": "hongrun",
            "profile_version": "2.0.0", "source_golden": golden_ref,
            "explicit_user_inputs": {"selected_direction_id": "luminous_intelligence",
                                     "answers": {"format_fit": "yes"}, "reason": "ok",
                                     "decision_receipt": receipt_ref},
            "inferred_preferences": [], "auto_apply": False,
            "production_default": False, "next_gate": "second",
        }
        candidate = {**body, "integrity_sha256": _stable_hash(body)}
        self.assertEqual([], validate_portrait_preference_candidate(candidate))
        candidate["inferred_preferences"] = ["likes every glow effect"]
        candidate["integrity_sha256"] = _stable_hash({
            key: value for key, value in candidate.items() if key != "integrity_sha256"
        })
        self.assertIn("must not infer", "\n".join(
            validate_portrait_preference_candidate(candidate)
        ))

    def test_second_topic_technical_gate_rejects_junk_evidence(self) -> None:
        junk = self.root / "junk.json"
        junk.write_text("{}", encoding="utf-8")
        snapshots = self.root / "snapshots"
        snapshots.mkdir()
        qa = {
            "evidence": {
                name: str(junk.resolve()) for name in (
                    "semantic_brief", "motion_contracts", "storyboard",
                    "renderer_payload", "hyperframes_index", "hyperframes_check", "audio_evidence",
                    "mix_receipt", "caption_receipt",
                )
            }
        }
        qa["evidence"]["phase_snapshots"] = str(snapshots.resolve())
        qa["evidence"]["final_review_snapshots"] = str(snapshots.resolve())
        candidate = self.root / "candidate.mp4"
        candidate.write_bytes(b"not media")
        errors = _second_topic_technical_errors(qa, candidate_path=candidate)
        self.assertTrue(errors)
        self.assertIn("semantic", "\n".join(errors).lower())

    def test_phase_snapshots_must_match_fresh_hyperframes_capture(self) -> None:
        declared = self.root / "declared"
        declared.mkdir()
        for index, timestamp in enumerate(("1.0", "2.0", "3.0", "4.0")):
            Image.new("RGB", (64, 64), (index * 30, 10, 10)).save(
                declared / f"frame-{index:02d}-at-{timestamp}s.png"
            )

        def fake_capture(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            for index, timestamp in enumerate(("1.0", "2.0", "3.0", "4.0")):
                Image.new("RGB", (64, 64), (10, index * 30, 10)).save(
                    output / f"frame-{index:02d}-at-{timestamp}s.png"
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("portrait_golden.subprocess.run", side_effect=fake_capture):
            errors = _fresh_phase_snapshot_errors(self.root, declared)
        self.assertEqual(4, len(errors))
        self.assertTrue(all("differs from current HyperFrames" in error for error in errors))

    def test_dead_payload_text_and_small_missing_overlay_are_rejected(self) -> None:
        project = self.root / "dead-project"
        project.mkdir()
        payload = {
            "payload_sha256": "a" * 64,
            "events": [{
                "eventId": "event-1", "semanticEventId": "semantic-1",
                "visibleCopy": ["重点"],
                "outputWindow": {"start_seconds": 1.0, "end_seconds": 2.0},
            }],
        }
        compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        (project / "index.html").write_text(
            f'<script type="text/plain">const payload={compact};</script>', encoding="utf-8",
        )
        self.assertTrue(_fresh_renderer_runtime_errors(project, payload))

        phases = self.root / "phase-mask"
        finals = self.root / "final-mask"
        phases.mkdir()
        finals.mkdir()
        black = Image.new("RGB", (100, 100), "black")
        entrance = black.copy()
        mid = black.copy()
        for x in range(20, 40):
            for y in range(20, 40):
                mid.putpixel((x, y), (255, 255, 255))
        pre_exit = mid.copy()
        post_exit = black.copy()
        for index, (image, timestamp) in enumerate(zip(
            (entrance, mid, pre_exit, post_exit), ("1.0", "1.5", "1.8", "2.1"),
        )):
            image.save(phases / f"frame-{index:02d}-at-{timestamp}s.png")
        black.save(finals / "at-1.50.png")
        black.save(finals / "at-2.10.png")
        self.assertIn(
            "changed region is not observable",
            "\n".join(_phase_candidate_binding_errors(phases, finals)),
        )

    def test_portrait_implementation_hash_includes_runtime_authorities(self) -> None:
        root = self.root / "repo"
        (root / "scripts").mkdir(parents=True)
        (root / "tests").mkdir()
        runtime = root / "references" / "portrait-motion-recipes-v2.json"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("one", encoding="utf-8")
        before = portrait_implementation_sha256(root)
        runtime.write_text("two", encoding="utf-8")
        self.assertNotEqual(before, portrait_implementation_sha256(root))

    def test_retained_builder_refuses_unvalidated_live_receipt(self) -> None:
        live = self.root / "forged-live.json"
        live.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        with self.assertRaises(PortraitGoldenError):
            build_retained_real_project_portrait_validation(
                live_validation_path=live,
                output_path=self.root / "retained.json",
                repository_root=self.root,
            )

    def test_public_validators_fail_closed_for_malformed_and_nonfinite_values(self) -> None:
        candidate = {"explicit_user_inputs": {"answers": []}, "integrity_sha256": "bad"}
        self.assertTrue(validate_portrait_preference_candidate(candidate))
        receipt = {"topics": [{}, {}], "integrity_sha256": "bad"}
        self.assertTrue(validate_retained_real_project_portrait_validation(
            receipt, repository_root=self.root,
        ))
        nonfinite = {"created_at": float("nan"), "integrity_sha256": "bad"}
        self.assertTrue(validate_real_project_portrait_validation(
            nonfinite, repository_root=self.root,
        ))
        golden = self._golden()
        golden["selected_style_reel"]["phase_evidence"] = [float("nan")]
        golden["integrity_sha256"] = "invalid-nonfinite-integrity"
        self.assertTrue(validate_provisional_portrait_golden(
            golden, repository_root=self.root,
        ))

    def test_runtime_observation_rejects_nonfinite_or_extra_nodes(self) -> None:
        expected = {
            "payload_sha256": "a" * 64,
            "event_ids": ["semantic-1"],
            "visible_copy": [["重点"]],
            "nodes": [{"event_id": "event-1", "start": 1.0, "duration": 1.0}],
        }
        observed = {
            "candidate": {
                "payloadSha256": "a" * 64,
                "eventIds": ["semantic-1"],
                "visibleCopy": [["重点"]],
            },
            "nodes": [{
                "event_id": "event-1", "hf_id": "event-1",
                "start": float("nan"), "duration": float("inf"), "text": "重点",
            }],
        }
        errors = _renderer_runtime_observation_errors(expected, observed)
        self.assertIn("runtime event start differs", "\n".join(errors))
        self.assertIn("runtime event duration differs", "\n".join(errors))
        observed["nodes"].append(dict(observed["nodes"][0]))
        self.assertIn(
            "painted event inventory differs",
            "\n".join(_renderer_runtime_observation_errors(expected, observed)),
        )

    def test_fresh_runtime_enumerates_and_rejects_extra_painted_event_root(self) -> None:
        project = self.root / "extra-painted-event"
        project.mkdir()
        payload = {
            "payload_sha256": "a" * 64,
            "events": [{
                "eventId": "event-1", "semanticEventId": "semantic-1",
                "visibleCopy": ["重点"],
                "outputWindow": {"start_seconds": 1.0, "end_seconds": 2.0},
            }],
        }
        candidate = {
            "payloadSha256": "a" * 64,
            "eventIds": ["semantic-1"],
            "visibleCopy": [["重点"]],
        }
        (project / "index.html").write_text(
            "<!doctype html><html><body>"
            '<main data-composition-id="main">'
            '<section id="event-1" class="pbm-event" data-hf-id="event-1" '
            'data-start="1" data-duration="1">重点</section>'
            '<section id="extra-event" class="pbm-event" data-hf-id="extra-event" '
            'data-start="1.2" data-duration="0.4">额外</section></main>'
            f"<script>window.__portraitCandidate={json.dumps(candidate, ensure_ascii=False)};</script>"
            "</body></html>",
            encoding="utf-8",
        )
        errors = _fresh_renderer_runtime_errors(project, payload)
        self.assertIn("painted event inventory differs", "\n".join(errors))
        self.assertIn("painted event identities differ", "\n".join(errors))

    @patch("portrait_golden._git_head", return_value="a" * 40)
    @patch("portrait_golden._git_is_ancestor", return_value=True)
    @patch("portrait_golden._second_topic_authority", return_value={
        "source_sha256": "2" * 64, "semantic_event_ids": ["e1"],
        "semantic_inventory_sha256": _stable_hash(["e1"]),
    })
    @patch("portrait_golden._first_topic_authority", return_value={
        "source_sha256": "1" * 64, "semantic_event_ids": ["first"],
        "semantic_inventory_sha256": _stable_hash(["first"]),
    })
    @patch("portrait_golden._second_topic_technical_errors", return_value=[])
    @patch("portrait_golden._probe_video_media", return_value={
        "duration_seconds": 55.48, "width": 544, "height": 960,
        "fps": 25, "audio_present": True,
    })
    @patch("portrait_golden.portrait_implementation_sha256", return_value="c" * 64)
    @patch("portrait_golden.source_tree_sha256", return_value="b" * 64)
    @patch("portrait_golden.validate_portrait_contract_schema", return_value=[])
    def test_second_topic_repeat_use_creates_real_project_validation_not_default(
        self, _schema, _tree, _portrait_tree, _probe, _technical,
        _first_authority, _second_authority, _ancestor, _head,
    ) -> None:
        golden = self._golden()
        golden_path = self.root / "portrait-golden.json"
        golden_path.write_text(json.dumps(golden), encoding="utf-8")
        preference_body = {
            "schema_version": 1,
            "kind": "hongrun_portrait_brand_preference_candidate",
            "status": "pending_second_topic_validation",
            "candidate_id": "candidate-1",
            "created_at": "2026-08-12T00:00:00+00:00",
            "profile_id": "hongrun",
            "profile_version": "2.0.0",
            "source_golden": _write(self.root / "historical-golden.json"),
            "explicit_user_inputs": {
                "selected_direction_id": "luminous_intelligence",
                "answers": {"repeat_use_willingness": "yes"},
                "reason": "first topic approved",
                "decision_receipt": _write(self.root / "first-decision.json"),
            },
            "inferred_preferences": [],
            "auto_apply": False,
            "production_default": False,
            "next_gate": "second_topic_named_user_repeat_use_approval",
        }
        preference = {
            **preference_body,
            "integrity_sha256": _stable_hash(preference_body),
        }
        preference_path = self.root / "preference.json"
        preference_path.write_text(json.dumps(preference), encoding="utf-8")

        candidate_path = self.root / "candidate.mp4"
        candidate_path.write_bytes(b"candidate-media")
        semantic = _write(self.root / "semantic.json", b'{"events": []}')
        check = _write(self.root / "second-check.json", b'{"ok": true}')
        snapshots = self.root / "snapshots"
        _write(snapshots / "event-mid.png", b"png")
        qa = {
            "schema_version": 1,
            "status": "awaiting_named_user_repeat_use_approval",
            "candidate_id": "second-topic",
            "direction": "luminous_intelligence",
            "source_topic": "physical_product_demo",
            "materially_different_from_first_topic": True,
            "candidate": {
                "path": str(candidate_path.resolve()),
                "sha256": sha256(candidate_path.read_bytes()).hexdigest(),
                "duration_seconds": 55.48,
                "width": 544,
                "height": 960,
                "fps": 25,
            },
            "semantic_events": [{"id": "e1", "recipe": "PBM-01"}],
            "gates": {
                "source_full_decode": "pass",
                "hyperframes_strict_check": "pass_zero_findings",
                "phase_snapshot_review": "pass_4_frames",
                "render_full_decode": "pass",
                "caption_last": "pass_4_source_preserving_phrases",
                "caption_receipt": "pass",
                "portrait_sonic_projection": "pass",
                "event_audio_audibility": "pass_1_of_1",
                "full_sample_sfx_mix": "pass",
                "final_full_av_decode": "pass",
                "face_hand_product_caption_occlusion_review": "pass",
                "production_default": False,
            },
            "evidence": {
                "semantic_brief": semantic["path"],
                "motion_contracts": semantic["path"],
                "storyboard": semantic["path"],
                "renderer_payload": semantic["path"],
                "hyperframes_index": semantic["path"],
                "hyperframes_check": check["path"],
                "phase_snapshots": str(snapshots.resolve()),
                "final_review_snapshots": str(snapshots.resolve()),
                "audio_evidence": semantic["path"],
                "mix_receipt": semantic["path"],
                "caption_receipt": semantic["path"],
            },
        }
        qa_path = self.root / "qa.json"
        qa_path.write_text(json.dumps(qa), encoding="utf-8")

        outputs = build_real_project_portrait_validation(
            repository_root=ROOT,
            provisional_golden_path=golden_path,
            preference_candidate_path=preference_path,
            second_topic_qa_path=qa_path,
            candidate_path=candidate_path,
            actor="HongRun",
            repeat_use_willingness="yes",
            preference="candidate",
            reason="效果还可以",
            decision_text="复用意愿：yes 偏好：candidate 理由：效果还可以",
            thread_id="thread-1",
            visual_review={"face_hand_product_caption_occlusion": "yes"},
            output_root=self.root / "promotion",
            media_probe=lambda _path: {
                "duration_seconds": 55.48, "width": 544, "height": 960,
                "fps": 25, "audio_present": True,
            },
        )
        receipt = json.loads(outputs["validation"].read_text(encoding="utf-8"))
        self.assertEqual("real_project_validated", receipt["maturity"])
        self.assertFalse(receipt["promotion"]["production_default"])
        self.assertEqual("separate_explicit_production_default_approval", receipt["promotion"]["next_gate"])
        self.assertEqual([], validate_real_project_portrait_validation(
            receipt, repository_root=ROOT,
            media_probe=lambda _path: {
                "duration_seconds": 55.48, "width": 544, "height": 960,
                "fps": 25, "audio_present": True,
            },
        ))
        receipt["first_topic"]["topic_authority"]["source_sha256"] = "9" * 64
        receipt["integrity_sha256"] = _stable_hash({
            key: value for key, value in receipt.items() if key != "integrity_sha256"
        })
        self.assertIn(
            "differs from current Golden",
            "\n".join(validate_real_project_portrait_validation(
                receipt, repository_root=ROOT,
                media_probe=lambda _path: {
                    "duration_seconds": 55.48, "width": 544, "height": 960,
                    "fps": 25, "audio_present": True,
                },
            )),
        )

    def test_second_topic_decision_rejects_stale_integrity_and_missing_visual_review(self) -> None:
        candidate = _write(self.root / "candidate.mp4")
        qa = _write(self.root / "qa.json", b"{}")
        body = {
            "schema_version": 1,
            "kind": "hongrun_portrait_second_topic_user_decision",
            "actor": "HongRun",
            "confirmation_method": "explicit_user_confirmation_hash_v1",
            "thread_id": "invented-thread",
            "repeat_use_willingness": "yes",
            "preference": "candidate",
            "reason": "invented",
            "decision_text": "invented",
            "decision_text_sha256": sha256(b"invented").hexdigest(),
            "candidate": candidate,
            "qa_report": qa,
            "visual_review": {},
            "decided_at": "2026-08-12T00:00:00+00:00",
        }
        body["integrity_sha256"] = "0" * 64
        errors = _second_topic_decision_errors(
            body, candidate_ref=candidate, qa_ref=qa,
        )
        self.assertIn("integrity hash is invalid", "\n".join(errors))
        self.assertIn("explicit visual review", "\n".join(errors))

    @patch("portrait_golden._git_head", return_value="a" * 40)
    @patch("portrait_golden.portrait_implementation_sha256", return_value="c" * 64)
    @patch("portrait_golden.source_tree_sha256", return_value="b" * 64)
    @patch("portrait_golden.validate_portrait_contract_schema", return_value=[])
    def test_second_topic_validation_rejects_non_candidate_or_default_claim(
        self, _schema, _tree, _portrait_tree, _head,
    ) -> None:
        receipt = {
            "schema_version": 1,
            "kind": "hongrun_portrait_brand_real_project_validation",
            "status": "pass",
            "maturity": "real_project_validated",
            "validation_id": "fixture",
            "created_at": "2026-08-12T00:00:00+00:00",
            "profile_id": "hongrun",
            "profile_version": "2.0.0",
            "direction": "luminous_intelligence",
            "first_topic": {},
            "second_topic": {},
            "named_user_decision": {
                "actor": "HongRun", "repeat_use_willingness": "yes",
                "preference": "baseline", "reason": "no", "thread_id": "thread",
                "decision_text_sha256": "a" * 64,
            },
            "implementation": {"source_tree_sha256": "b" * 64,
                               "portrait_implementation_sha256": "c" * 64},
            "promotion": {
                "real_project_validation_count": 2,
                "required_real_project_count": 2,
                "production_default": True,
                "next_gate": "none",
            },
            "inferred_preferences": [],
            "auto_apply": False,
        }
        receipt["integrity_sha256"] = _stable_hash(receipt)
        errors = "\n".join(validate_real_project_portrait_validation(
            receipt, repository_root=ROOT,
            media_probe=lambda _path: {},
        ))
        self.assertIn("preference", errors)
        self.assertIn("production default", errors)

    @patch("portrait_golden.validate_real_project_portrait_validation", return_value=[])
    @patch("portrait_golden.portrait_implementation_sha256", return_value="c" * 64)
    @patch("portrait_golden.source_tree_sha256", return_value="b" * 64)
    def test_retained_two_topic_receipt_is_current_and_opt_in_only(
        self, _tree, _portrait_tree, _live_validation,
    ) -> None:
        live_path = self.root / "live.json"
        live_path.write_text(json.dumps({
            "kind": "hongrun_portrait_brand_real_project_validation",
            "status": "pass",
            "maturity": "real_project_validated",
            "profile_id": "hongrun",
            "profile_version": "2.0.0",
            "direction": "luminous_intelligence",
            "validation_id": "two-topics",
            "first_topic": {"topic_id": "farewell"},
            "second_topic": {
                "topic_id": "product",
                "candidate": {"sha256": "c" * 64},
                "qa_report": {"sha256": "d" * 64},
            },
            "named_user_decision": {
                "actor": "HongRun", "repeat_use_willingness": "yes",
                "preference": "candidate", "receipt": {"sha256": "e" * 64},
            },
            "implementation": {"source_tree_sha256": "b" * 64,
                               "portrait_implementation_sha256": "c" * 64},
            "promotion": {"real_project_validation_count": 2,
                          "required_real_project_count": 2,
                          "production_default": False,
                          "next_gate": "separate_explicit_production_default_approval"},
        }), encoding="utf-8")
        retained_path = self.root / "retained.json"
        retained = build_retained_real_project_portrait_validation(
            live_validation_path=live_path,
            output_path=retained_path,
            repository_root=self.root,
        )
        self.assertEqual([], validate_retained_real_project_portrait_validation(
            retained, repository_root=self.root,
        ))
        retained["promotion"]["production_default"] = True
        retained["integrity_sha256"] = _stable_hash({
            key: value for key, value in retained.items() if key != "integrity_sha256"
        })
        self.assertIn("production default", "\n".join(
            validate_retained_real_project_portrait_validation(retained, repository_root=self.root)
        ))


if __name__ == "__main__":
    unittest.main()
