from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portrait_style_reel import (  # noqa: E402
    DIRECTIONS,
    StyleReelError,
    _context_audio_audition_errors,
    _context_approved_copy_errors,
    _direction_contract_errors,
    build_style_reel_plan,
    build_style_reel_audition_receipt,
    build_style_reel_render_requests,
    build_style_reel_review,
    create_style_reel_window_confirmation,
    generate_style_reel_dashboard,
    mark_style_reel_stale,
    record_style_reel_user_decision,
    validate_style_reel_plan,
    validate_style_reel_authority_manifest,
    validate_style_reel_context,
    validate_style_reel_review,
    validate_style_reel_window_confirmation,
    validate_style_reel_user_decision_receipt,
    validate_wp6_real_style_reel_review_package,
    write_style_reel_fixture_phase_image,
)
from portrait_sonic import (  # noqa: E402
    DEFAULT_PORTRAIT_SONIC_REGISTRY,
    compile_portrait_sonic_plan,
    materialize_portrait_sonic_library,
    project_portrait_sonic_plan,
)


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path.resolve()


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.resolve()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha(path)}


class PortraitStyleReelTests(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg and ffprobe are required for Style Reel authority tests")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = (self.root / "source.mp4").resolve()
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=160x90:r=1:d=45",
            "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=48000:duration=45",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "40",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "32k", "-shortest",
            str(self.source),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, result.returncode, result.stderr)
        self.edl = _write_json(self.root / "edl.json", {
            "owner": "video-use",
            "sources": {self.source.name: _ref(self.source)},
            "ranges": [
                {"source": self.source.name, "start": 0.0, "end": 14.0, "timeline_start": 0.0},
                {"source": self.source.name, "start": 14.0, "end": 45.0, "timeline_start": 14.0},
            ],
        })
        self.transcript = _write_json(self.root / "transcript.json", {"words": [
            {"id": "w1", "text": "第一句话", "start": 6.0, "end": 7.0},
            {"id": "w2", "text": "第二句话", "start": 14.0, "end": 15.0},
        ]})
        self.output_transcript = _write_json(self.root / "output-transcript.json", {
            "words": [{"id": "w1", "text": "第一句话", "start": 6.0, "end": 7.0},
                      {"id": "w2", "text": "第二句话", "start": 14.0, "end": 15.0}],
        })
        self.captions = _write(self.root / "master.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhello")
        self.audio_policy = _write_json(self.root / "audio-policy.json", {"voice": "same"})
        self.voice_stem = (self.root / "voice-stem.wav").resolve()
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=180:sample_rate=48000:duration=45",
            "-ac", "1", "-c:a", "pcm_s16le", str(self.voice_stem),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, result.returncode, result.stderr)
        self.subject_evidence = _write_json(self.root / "subject-evidence.json", {
            "status": "pass", "subject": "HongRun", "orientation": "portrait",
        })
        self.profile = (self.root / "profile.json").resolve()
        self.profile.write_bytes((
            ROOT / "references" / "portrait-brand-profiles" / "hongrun-portrait-brand-v2.0.0.json"
        ).read_bytes())
        self.events = ["event-1", "event-2"]
        self.semantic_brief = _write_json(self.root / "semantic-brief.json", {"events": [
            {
                "id": "event-1", "semantic_event_id": "event-1", "output_start": 6.0, "output_end": 7.0,
                "decision": "render", "decision_rationale": "fixture render event",
                "source_sentence": "<script>alert(1)</script>",
                "approved_visible_copy": ["核心观点"], "viewer_takeaway": "理解变化",
                "portrait_energy_intent": {"tier": "meso", "rationale": "解释而非复述"},
                "audio_decision": {"type": "cue"},
            },
            {
                "id": "event-2", "semantic_event_id": "event-2", "output_start": 14.0, "output_end": 15.0,
                "decision": "render", "decision_rationale": "fixture render event",
                "source_sentence": "第二句话", "approved_visible_copy": ["第二观点"],
                "viewer_takeaway": "理解变化",
                "portrait_energy_intent": {"tier": "meso", "rationale": "解释而非复述"},
                "audio_decision": {"type": "cue"},
            },
        ]})
        semantic_payload = json.loads(self.semantic_brief.read_text(encoding="utf-8"))
        semantic_hash = sha256(json.dumps(
            semantic_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        self.motion_contracts = _write_json(self.root / "portrait-motion-contracts.json", {
            "schema_version": 1,
            "contracts": [
                {"semantic_event_id": event_id, "primary_recipe_id": "PBM-01",
                 "energy_tier": "meso", "output_window": {"start_seconds": start, "end_seconds": start + 1.0},
                 "input_hashes": {"semantic_brief": semantic_hash}}
                for event_id, start in (("event-1", 6.0), ("event-2", 14.0))
            ],
        })
        self.storyboard = _write_json(self.root / "storyboard.json", {"events": [
            {"id": event_id, "semantic_event_id": event_id}
            for event_id in self.events
        ]})
        library = materialize_portrait_sonic_library(
            DEFAULT_PORTRAIT_SONIC_REGISTRY, self.root / "sonic-library",
        )
        compiled = compile_portrait_sonic_plan(
            project_id="fixture-project", profile_path=self.profile,
            motion_contracts_path=self.motion_contracts, semantic_brief=semantic_payload,
            library_manifest_path=library,
        )
        self.sonic_plan = _write_json(self.root / "portrait-sonic-plan.json", compiled["plan"])
        projected = project_portrait_sonic_plan(
            compiled["plan"], {
                "schema_version": 3,
                "speech_track": {"source": "source.wav", "dominant": True, "immutable": True},
                "motion_sfx": {"event_decisions": [], "mix_audibility_check": {"status": "not_applicable"}},
                "background_music": {"mode": "disabled", "enabled": False, "reason": "fixture"},
                "provenance": {"source_audio": "source.wav"},
            }, base_dir=self.root, motion_contracts_path=self.motion_contracts,
            storyboard=json.loads(self.storyboard.read_text(encoding="utf-8")),
        )
        self.audio_plan = _write_json(self.root / "audio-plan.json", projected)
        first_decision = projected["motion_sfx"]["event_decisions"][0]
        self.cue = (self.root / first_decision["asset"]).resolve()
        cue_duration = float(first_decision["duration_seconds"])
        self.voice_off = (self.root / "auditions" / "voice-sfx-off.wav").resolve()
        self.sfx_on = (self.root / "auditions" / "sfx-on.wav").resolve()
        self.voice_off.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-ss", "6", "-t", str(cue_duration),
            "-i", str(self.voice_stem), "-ac", "1", "-c:a", "pcm_s16le", str(self.voice_off),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, result.returncode, result.stderr)
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(self.voice_off),
            "-i", str(self.cue),
            "-filter_complex", f"[1:a]volume={first_decision['volume']}[cue];[0:a][cue]amix=inputs=2:normalize=0", "-ac", "1",
            "-c:a", "pcm_s16le", str(self.sfx_on),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, result.returncode, result.stderr)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _authorities(self) -> dict[str, Path]:
        return {
            "source": self.source,
            "edl": self.edl,
            "transcript": self.transcript,
            "output_transcript": self.output_transcript,
            "semantic_brief": self.semantic_brief,
            "captions": self.captions,
            "audio_policy": self.audio_policy,
            "voice_stem": self.voice_stem,
            "subject_evidence": self.subject_evidence,
            "profile": self.profile,
            "audio_plan": self.audio_plan,
            "sonic_plan": self.sonic_plan,
            "motion_contracts": self.motion_contracts,
            "storyboard": self.storyboard,
        }

    def _build_kwargs(self) -> dict[str, object]:
        return {
            "project_id": "fixture-project", "source_path": self.source,
            "edl_path": self.edl, "transcript_path": self.transcript,
            "output_transcript_path": self.output_transcript,
            "semantic_brief_path": self.semantic_brief,
            "captions_path": self.captions, "audio_policy_path": self.audio_policy,
            "voice_stem_path": self.voice_stem,
            "subject_evidence_path": self.subject_evidence,
            "profile_path": self.profile, "semantic_event_ids": self.events,
            "audio_plan_path": self.audio_plan, "sonic_plan_path": self.sonic_plan,
            "motion_contracts_path": self.motion_contracts, "storyboard_path": self.storyboard,
            "start_seconds": 2.0, "end_seconds": 38.0,
            "authorized_root": self.root,
        }

    def _plan(self) -> tuple[Path, dict]:
        path = self.root / "style-reel" / "style-reel-plan.json"
        payload = build_style_reel_plan(**self._build_kwargs(), output=path)
        return path.resolve(), payload

    def _authority_manifest(self, plan_path: Path) -> Path:
        return plan_path.with_name("style-reel-authorities.json").resolve()

    def _review_inputs(self, plan: dict) -> tuple[dict[str, Path], dict[str, Path], dict[str, list[Path]], Path]:
        media: dict[str, Path] = {}
        contracts: dict[str, Path] = {}
        phases: dict[str, list[Path]] = {}
        for index, direction in enumerate(DIRECTIONS):
            media[direction] = _write(self.root / f"{direction}.mp4", f"media-{index}".encode())
            phases[direction] = []
            for event_index, event_id in enumerate(self.events):
                for phase in ("entrance", "mid", "pre_exit", "post_exit"):
                    image = self.root / "phases" / direction / f"{event_id}-{phase}.png"
                    write_style_reel_fixture_phase_image(
                        image, direction_id=direction, event_index=event_index, phase=phase,
                    )
                    phases[direction].append(image.resolve())
            contracts[direction] = _write_json(self.root / f"{direction}-contract.json", {
                "schema_version": 1,
                "direction_id": direction,
                "comparison_basis_sha256": sha256(json.dumps(
                    plan["comparison_basis"], sort_keys=True, separators=(",", ":"),
                ).encode()).hexdigest(),
                "event_ids": self.events,
                "event_decisions": [
                    {"event_id": event_id, "decision": "render"}
                    for event_id in self.events
                ],
                "event_recipes": [
                    {"event_id": event_id, "recipe_id": plan["directions"][index]["recipe_ids"][
                        event_index % len(plan["directions"][index]["recipe_ids"])
                    ]}
                    for event_index, event_id in enumerate(self.events)
                ],
                "structural_fingerprint": plan["directions"][index]["structural_fingerprint"],
                "phase_inventory": [
                    {"event_id": event_id, "phase": phase, "evidence": _ref(path)}
                    for event_id in self.events
                    for phase, path in zip(
                        ("entrance", "mid", "pre_exit", "post_exit"),
                        phases[direction][
                            self.events.index(event_id) * 4:
                            self.events.index(event_id) * 4 + 4
                        ],
                    )
                ],
            })
        report = _write_json(self.root / "automated-report.json", {})
        return media, contracts, phases, report

    def _write_automated_report(
        self, report: Path, plan_path: Path, plan: dict,
        media: dict[str, Path], contracts: dict[str, Path], phases: dict[str, list[Path]],
    ) -> None:
        report.write_text(json.dumps({
            "schema_version": 1, "status": "pass", "plan": _ref(plan_path),
            "comparison_basis_sha256": sha256(json.dumps(
                plan["comparison_basis"], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "directions": [{
                "direction_id": direction,
                "media": _ref(media[direction]),
                "contract": _ref(contracts[direction]),
                "phase_evidence": [_ref(path) for path in phases[direction]],
            } for direction in DIRECTIONS],
            "checks": {
                "full_decode": True, "duration_alignment": True,
                "stream_signature": True, "event_alignment": True,
                "phase_inventory": True,
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _context_events(self, contracts: dict[str, Path], plan_path: Path) -> list[dict[str, object]]:
        semantic = json.loads(self.semantic_brief.read_text(encoding="utf-8"))["events"]
        result: list[dict[str, object]] = []
        for index, event_id in enumerate(self.events):
            row = semantic[index]
            decisions = json.loads(self.audio_plan.read_text(encoding="utf-8"))["motion_sfx"]["event_decisions"]
            decision = next(value for value in decisions if value.get("semantic_event_id", value["event_id"]) == event_id)
            off_path = self.root / "auditions" / f"{event_id}-off.wav"
            on_path = self.root / "auditions" / f"{event_id}-on.wav"
            cue_path = (self.audio_plan.parent / decision["asset"]).resolve()
            for command in (
                ["ffmpeg", "-y", "-v", "error", "-ss", str(row["output_start"]), "-t",
                 str(decision["duration_seconds"]), "-i", str(self.voice_stem), "-ac", "1",
                 "-c:a", "pcm_s16le", str(off_path)],
                ["ffmpeg", "-y", "-v", "error", "-i", str(off_path), "-i", str(cue_path),
                 "-filter_complex", f"[1:a]volume={decision['volume']}[cue];[0:a][cue]amix=inputs=2:normalize=0",
                 "-ac", "1", "-c:a", "pcm_s16le", str(on_path)],
            ):
                completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
                self.assertEqual(0, completed.returncode, completed.stderr)
            receipt_path = self.root / "auditions" / f"{event_id}-receipt.json"
            build_style_reel_audition_receipt(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                event_id=event_id, voice_sfx_off_path=off_path,
                sfx_on_path=on_path, output=receipt_path, authorized_root=self.root,
            )
            result.append({
                "event_id": event_id,
                "marker_seconds": round(float(row["output_start"]) - 2.0, 6),
                "source_sentence": row["source_sentence"],
                "approved_visible_copy": row["approved_visible_copy"],
                "viewer_takeaway": row["viewer_takeaway"],
                "energy_tier": row["portrait_energy_intent"]["tier"],
                "rationale": row["portrait_energy_intent"]["rationale"],
                "decision": row.get("decision", "render"),
                "recipes": {
                    direction: json.loads(contracts[direction].read_text(encoding="utf-8"))[
                        "event_recipes"
                    ][index]["recipe_id"] for direction in DIRECTIONS
                },
                "audio_auditions": {
                    "voice_sfx_off": _ref(off_path), "sfx_on": _ref(on_path),
                    "receipt": _ref(receipt_path),
                },
            })
        return result

    def test_plan_is_deterministic_and_binds_common_basis(self) -> None:
        path, first = self._plan()
        second_path = self.root / "second-plan.json"
        second = build_style_reel_plan(**self._build_kwargs(), output=second_path)
        self.assertEqual(first, second)
        self.assertEqual(list(DIRECTIONS), [row["direction_id"] for row in first["directions"]])
        self.assertEqual(3, len({row["structural_fingerprint"] for row in first["directions"]}))
        self.assertEqual([], validate_style_reel_plan(
            first, authority_paths=self._authorities(), expected_event_ids=self.events,
        ))
        self.assertEqual(first, json.loads(path.read_text(encoding="utf-8")))
        self.assertTrue(all(
            row["macro_applicability"] == "not_applicable"
            for row in first["directions"]
        ))
        self.assertTrue(all(
            "PBM-07" not in row["recipe_ids"] for row in first["directions"]
        ))

    def test_real_direction_contract_preserves_render_reuse_and_quiet_decisions(self) -> None:
        _, plan = self._plan()
        direction = DIRECTIONS[0]
        render_event = self.events[0]
        quiet_event = self.events[1]
        evidence = _write(self.root / "render-phase.png", b"phase")
        contract = {
            "schema_version": 1,
            "direction_id": direction,
            "comparison_basis_sha256": sha256(json.dumps(
                plan["comparison_basis"], sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest(),
            "event_ids": self.events,
            "event_decisions": [
                {"event_id": render_event, "decision": "render"},
                {"event_id": quiet_event, "decision": "quiet_source"},
            ],
            "event_recipes": [{
                "event_id": render_event,
                "recipe_id": plan["directions"][0]["recipe_ids"][0],
            }],
            "structural_fingerprint": plan["directions"][0]["structural_fingerprint"],
            "phase_inventory": [
                {"event_id": render_event, "phase": phase, "evidence": _ref(evidence)}
                for phase in ("entrance", "mid", "pre_exit", "post_exit")
            ],
        }
        decisions = {render_event: "render", quiet_event: "quiet_source"}
        self.assertEqual([], _direction_contract_errors(
            contract, direction_id=direction, plan=plan, event_ids=self.events,
            event_decisions=decisions,
        ))

        forged = deepcopy(contract)
        forged["event_recipes"].append({
            "event_id": quiet_event,
            "recipe_id": plan["directions"][0]["recipe_ids"][1],
        })
        self.assertIn("event recipe set is stale", "\n".join(_direction_contract_errors(
            forged, direction_id=direction, plan=plan, event_ids=self.events,
            event_decisions=decisions,
        )))

    def test_non_render_context_requires_reasoned_not_applicable_audio(self) -> None:
        self.assertEqual([], _context_audio_audition_errors(
            {"status": "not_applicable", "reason": "quiet_source preserves source-only audio"},
            expected_decision="quiet_source", event_index=1,
            plan_path=self.root / "unused-plan.json",
            authority_manifest_path=self.root / "unused-authorities.json",
            event_id="event-2",
        ))
        self.assertIn("not_applicable", "\n".join(_context_audio_audition_errors(
            {"voice_sfx_off": _ref(self.voice_off), "sfx_on": _ref(self.sfx_on)},
            expected_decision="reuse_source", event_index=1,
            plan_path=self.root / "unused-plan.json",
            authority_manifest_path=self.root / "unused-authorities.json",
            event_id="event-2",
        )))
        self.assertIn("reason", "\n".join(_context_audio_audition_errors(
            {"status": "not_applicable", "reason": ""},
            expected_decision="quiet_source", event_index=1,
            plan_path=self.root / "unused-plan.json",
            authority_manifest_path=self.root / "unused-authorities.json",
            event_id="event-2",
        )))

    def test_non_render_context_does_not_invent_approved_visible_copy(self) -> None:
        self.assertEqual([], _context_approved_copy_errors(
            None, expected_decision="quiet_source", event_index=1,
        ))
        self.assertIn("must not invent", "\n".join(_context_approved_copy_errors(
            ["额外文案"], expected_decision="reuse_source", event_index=1,
        )))
        self.assertEqual([], _context_approved_copy_errors(
            ["核心观点"], expected_decision="render", event_index=0,
        ))

    def test_macro_is_selected_only_from_current_independent_boundary_evidence(self) -> None:
        boundary = _write_json(self.root / "chapter-boundary.json", {
            "schema_version": 1, "kind": "chapter_boundary", "status": "pass",
            "boundary_id": "boundary-1", "chapter_id": "chapter-1", "event_id": "event-2",
            "structural": True, "source": _ref(self.source), "edl": _ref(self.edl),
            "owner": "video-use", "basis_kind": "edl_cut",
            "source_seconds": 14.0, "output_seconds": 14.0,
        })
        output = self.root / "with-boundary-plan.json"
        plan = build_style_reel_plan(
            **self._build_kwargs(), output=output, chapter_boundary_evidence_path=boundary,
        )
        applicability = {
            row["direction_id"]: row["macro_applicability"] for row in plan["directions"]
        }
        self.assertEqual("selected", applicability[DIRECTIONS[0]])
        self.assertEqual("selected", applicability[DIRECTIONS[1]])
        self.assertEqual("not_applicable", applicability[DIRECTIONS[2]])
        recipes = {
            row["direction_id"]: row["recipe_ids"] for row in plan["directions"]
        }
        self.assertIn("PBM-07", recipes[DIRECTIONS[0]])
        self.assertIn("PBM-07", recipes[DIRECTIONS[1]])
        self.assertNotIn("PBM-07", recipes[DIRECTIONS[2]])
        boundary.write_text("{}", encoding="utf-8")
        manifest = json.loads(self._authority_manifest(output).read_text(encoding="utf-8"))
        self.assertIn("chapter_boundary", "\n".join(
            validate_style_reel_authority_manifest(manifest, plan_path=output)
        ))

    def test_window_and_boundary_must_come_from_current_typed_timeline_evidence(self) -> None:
        invalid_window = self._build_kwargs()
        invalid_window.update({"start_seconds": 1000.0, "end_seconds": 1036.0})
        with self.assertRaisesRegex(StyleReelError, "window"):
            build_style_reel_plan(**invalid_window, output=self.root / "outside-window.json")
        empty_boundary = _write_json(self.root / "empty-boundary.json", {})
        with self.assertRaisesRegex(StyleReelError, "chapter boundary"):
            build_style_reel_plan(
                **self._build_kwargs(), output=self.root / "empty-boundary-plan.json",
                chapter_boundary_evidence_path=empty_boundary,
            )
        invented = _write_json(self.root / "invented-boundary.json", {
            "schema_version": 1, "kind": "chapter_boundary", "status": "pass",
            "boundary_id": "invented", "chapter_id": "chapter-1", "event_id": "event-1",
            "structural": True, "owner": "video-use", "basis_kind": "edl_cut",
            "source": _ref(self.source), "edl": _ref(self.edl),
            "source_seconds": 30.0, "output_seconds": 30.0,
        })
        with self.assertRaisesRegex(StyleReelError, "semantic event start|EDL cut"):
            build_style_reel_plan(
                **self._build_kwargs(), output=self.root / "invented-boundary-plan.json",
                chapter_boundary_evidence_path=invented,
            )

    def test_audition_receipt_requires_decodable_bound_voice_window(self) -> None:
        plan_path, _ = self._plan()
        bad_off = _write(self.root / "auditions" / "bad-off.wav", b"not audio")
        bad_on = _write(self.root / "auditions" / "bad-on.wav", b"not audio either")
        with self.assertRaisesRegex(StyleReelError, "decodable audio"):
            build_style_reel_audition_receipt(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                event_id="event-1", voice_sfx_off_path=bad_off, sfx_on_path=bad_on,
                output=self.root / "auditions" / "bad-receipt.json",
                authorized_root=self.root,
            )
        silence = self.root / "auditions" / "silence.wav"
        cue_duration = json.loads(self.audio_plan.read_text(encoding="utf-8"))["motion_sfx"][
            "event_decisions"
        ][0]["duration_seconds"]
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "anullsrc=r=48000:cl=mono", "-t", str(cue_duration), "-c:a", "pcm_s16le", str(silence),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, result.returncode, result.stderr)
        with self.assertRaisesRegex(StyleReelError, "authorized audible cue"):
            build_style_reel_audition_receipt(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                event_id="event-1", voice_sfx_off_path=self.voice_off, sfx_on_path=silence,
                output=self.root / "auditions" / "silence-receipt.json",
                authorized_root=self.root,
            )

    def test_audition_receipt_rejects_extra_sfx_outside_the_canonical_cue_window(self) -> None:
        plan_path, _ = self._plan()
        decision = json.loads(self.audio_plan.read_text(encoding="utf-8"))["motion_sfx"][
            "event_decisions"
        ][0]
        duration = float(decision["duration_seconds"])
        extended_off = self.root / "auditions" / "extended-off.wav"
        extended_on = self.root / "auditions" / "extended-on.wav"
        commands = (
            ["ffmpeg", "-y", "-v", "error", "-ss", "6", "-t", str(duration * 2),
             "-i", str(self.voice_stem), "-ac", "1", "-c:a", "pcm_s16le", str(extended_off)],
            ["ffmpeg", "-y", "-v", "error", "-i", str(extended_off), "-i", str(self.cue),
             "-f", "lavfi", "-i", f"sine=frequency=1500:sample_rate=48000:duration={duration}",
             "-filter_complex",
             f"[1:a]volume={decision['volume']}[cue];[2:a]adelay={round(duration * 1000)}[tail];"
             "[0:a][cue][tail]amix=inputs=3:normalize=0", "-ac", "1", "-c:a", "pcm_s16le",
             str(extended_on)],
        )
        for command in commands:
            completed = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
        with self.assertRaisesRegex(StyleReelError, "authorized audible cue"):
            build_style_reel_audition_receipt(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                event_id="event-1", voice_sfx_off_path=extended_off,
                sfx_on_path=extended_on, output=self.root / "auditions" / "extended-receipt.json",
                authorized_root=self.root,
            )

    def test_plan_public_inputs_fail_closed_with_domain_errors(self) -> None:
        for malformed in (None, True, "event-1"):
            kwargs = self._build_kwargs()
            kwargs["semantic_event_ids"] = malformed
            with self.assertRaisesRegex(StyleReelError, "semantic event IDs"):
                build_style_reel_plan(**kwargs, output=self.root / f"malformed-{malformed}.json")
        kwargs = self._build_kwargs()
        kwargs["authorized_root"] = None
        with self.assertRaisesRegex(StyleReelError, "output root/path"):
            build_style_reel_plan(**kwargs, output=self.root / "malformed-root.json")

    def test_plan_and_authority_manifest_are_preflighted_as_one_package(self) -> None:
        output = self.root / "atomic" / "style-reel-plan.json"
        output.parent.mkdir()
        manifest = output.with_name("style-reel-authorities.json")
        manifest.mkdir()
        with self.assertRaisesRegex(StyleReelError, "must not be a directory"):
            build_style_reel_plan(**self._build_kwargs(), output=output)
        self.assertFalse(output.exists())

    def test_plan_rejects_basis_profile_duration_and_structural_drift(self) -> None:
        _, plan = self._plan()
        self.captions.write_text("changed", encoding="utf-8")
        plan["comparison_basis"]["end_seconds"] = 50.0
        plan["directions"][1]["structural_fingerprint"] = plan["directions"][0]["structural_fingerprint"]
        plan["directions"][2]["profile"]["sha256"] = "0" * 64
        errors = validate_style_reel_plan(
            plan, authority_paths=self._authorities(), expected_event_ids=list(reversed(self.events)),
        )
        joined = "\n".join(errors)
        self.assertIn("caption", joined)
        self.assertIn("30 to 45 seconds", joined)
        self.assertIn("structural", joined)
        self.assertIn("profile", joined)
        self.assertIn("event", joined)

    def test_authority_manifest_detects_caption_drift_after_plan_creation(self) -> None:
        plan_path, _ = self._plan()
        manifest_path = self._authority_manifest(plan_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.captions.write_text("later caption drift", encoding="utf-8")
        errors = validate_style_reel_authority_manifest(manifest, plan_path=plan_path)
        self.assertIn("caption", "\n".join(errors))

    def test_render_requests_are_isolated_blocked_and_never_authorize_full_video(self) -> None:
        plan_path, _ = self._plan()
        paths = build_style_reel_render_requests(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            output_dir=self.root / "style-reel",
        )
        self.assertEqual(3, len(paths))
        for path in paths:
            request = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("hyperframes", request["owner"])
            self.assertEqual("blocked_by_user_window_confirmation", request["status"])
            self.assertIsNone(request["command"])
            self.assertFalse(request["output_policy"]["full_video_render_authorized"])
            self.assertFalse(request["output_policy"]["may_replace_automatic_master"])
        with self.assertRaisesRegex(StyleReelError, "synthetic"):
            create_style_reel_window_confirmation(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                actor="HongRun", output=self.root / "window-confirmation.json",
                authorized_root=self.root,
            )

    def test_real_window_confirmation_needs_no_secret_and_is_drift_evident(self) -> None:
        plan_path = self.root / "real-style-reel" / "style-reel-plan.json"
        build_style_reel_plan(
            **self._build_kwargs(), evidence_class="real_project", output=plan_path,
        )
        manifest_path = self._authority_manifest(plan_path)
        receipt_path = self.root / "window-confirmation.json"
        receipt = create_style_reel_window_confirmation(
            plan_path=plan_path,
            authority_manifest_path=manifest_path,
            actor="HongRun",
            output=receipt_path,
            authorized_root=self.root,
        )
        self.assertEqual([], validate_style_reel_window_confirmation(
            receipt, plan_path=plan_path, authority_manifest_path=manifest_path,
        ))
        self.captions.write_text("caption drift after confirmation", encoding="utf-8")
        self.assertIn("caption", "\n".join(validate_style_reel_window_confirmation(
            receipt, plan_path=plan_path, authority_manifest_path=manifest_path,
        )))
        for field, changed in (
            ("actor", "Agent"),
            ("start_seconds", 3.0),
            ("comparison_basis_sha256", "0" * 64),
        ):
            tampered = deepcopy(receipt)
            tampered[field] = changed
            errors = validate_style_reel_window_confirmation(
                tampered, plan_path=plan_path, authority_manifest_path=manifest_path,
            )
            self.assertIn("integrity", "\n".join(errors), field)

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_render_request_children_cannot_escape_through_junction(self) -> None:
        plan_path, _ = self._plan()
        output = plan_path.parent / "junction-requests"
        output.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(output / "requests"), str(outside)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
        with self.assertRaisesRegex(StyleReelError, "escaped"):
            build_style_reel_render_requests(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                output_dir=output,
            )
        self.assertEqual([], list(outside.iterdir()))

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_plan_writer_and_render_request_package_are_junction_safe_and_transactional(self) -> None:
        with tempfile.TemporaryDirectory() as external_temp:
            outside = Path(external_temp).resolve()
            escaped = self.root / "escaped-plan-dir"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(escaped), str(outside)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            try:
                with self.assertRaisesRegex(StyleReelError, "escaped|inside"):
                    build_style_reel_plan(
                        **self._build_kwargs(), output=escaped / "style-reel-plan.json",
                    )
                self.assertEqual([], list(outside.iterdir()))
            finally:
                if escaped.exists():
                    escaped.rmdir()

        plan_path, _ = self._plan()
        output = plan_path.parent
        outside = self.root / "outside-phase"
        outside.mkdir()
        phase_parent = output / "phases"
        phase_parent.mkdir(exist_ok=True)
        escaped_phase = phase_parent / DIRECTIONS[1]
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(escaped_phase), str(outside)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
        try:
            with self.assertRaisesRegex(StyleReelError, "escaped"):
                build_style_reel_render_requests(
                    plan_path=plan_path,
                    authority_manifest_path=self._authority_manifest(plan_path),
                    output_dir=output,
                )
            request_dir = output / "requests"
            self.assertFalse(request_dir.exists() and any(request_dir.iterdir()))
            self.assertEqual([], list(outside.iterdir()))
        finally:
            if escaped_phase.exists():
                escaped_phase.rmdir()

    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_review_is_pending_and_binds_three_aligned_reels(self, _probe, _decode, _signature) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        review_path = self.root / "style-reel-review.json"
        review = build_style_reel_review(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            media_paths=media, contract_paths=contracts,
            phase_evidence_paths=phases, automated_report_path=report,
            output=review_path, authorized_root=self.root,
        )
        self.assertEqual("pending", review["status"])
        self.assertEqual("pending", review["user"]["decision"])
        self.assertEqual([], validate_style_reel_review(
            review, plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            contract_paths=contracts,
        ))

    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_review_rejects_contract_event_phase_and_media_hash_drift(self, _probe, _decode, _signature) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        review = build_style_reel_review(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            media_paths=media, contract_paths=contracts,
            phase_evidence_paths=phases, automated_report_path=report,
            output=self.root / "style-reel-review.json", authorized_root=self.root,
        )
        changed = deepcopy(review)
        changed["reels"][0]["event_ids"] = ["event-1", "other"]
        changed["reels"][1]["phase_evidence"] = changed["reels"][1]["phase_evidence"][:-1]
        media[DIRECTIONS[2]].write_bytes(b"drifted")
        contracts[DIRECTIONS[0]].write_text("{}", encoding="utf-8")
        errors = validate_style_reel_review(
            changed, plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            contract_paths=contracts,
        )
        joined = "\n".join(errors)
        self.assertIn("event", joined)
        self.assertIn("phase", joined)
        self.assertIn("media", joined)
        self.assertIn("contract", joined)
        non_finite = deepcopy(review)
        non_finite["reels"][0]["duration_seconds"] = float("nan")
        self.assertIn("duration", "\n".join(validate_style_reel_review(
            non_finite, plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            contract_paths=contracts,
        )))

    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_review_rejects_three_self_declared_but_visually_identical_phase_sets(
        self, _probe, _decode, _signature,
    ) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        source_bytes = phases[DIRECTIONS[0]][0].read_bytes()
        for direction in DIRECTIONS:
            for path in phases[direction]:
                path.write_bytes(source_bytes)
            contract = json.loads(contracts[direction].read_text(encoding="utf-8"))
            for row, path in zip(contract["phase_inventory"], phases[direction]):
                row["evidence"] = _ref(path)
            _write_json(contracts[direction], contract)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        with self.assertRaisesRegex(
            StyleReelError,
            "deterministic direction-specific WP4 fixture|distinct phase structure|choreography changes",
        ):
            build_style_reel_review(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                media_paths=media, contract_paths=contracts,
                phase_evidence_paths=phases, automated_report_path=report,
                output=self.root / "identical-review.json", authorized_root=self.root,
            )

    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_review_rejects_palette_or_tiny_marker_only_direction_differences(
        self, _probe, _decode, _signature,
    ) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        for direction_index, direction in enumerate(DIRECTIONS):
            for image_index, path in enumerate(phases[direction]):
                phase_index = image_index % 4
                canvas = Image.new("RGB", (320, 180), (10 + direction_index * 30,) * 3)
                draw = ImageDraw.Draw(canvas)
                if phase_index != 3:
                    x = 30 + phase_index * 55
                    tone = 210 - direction_index * 35
                    draw.rectangle((x, 45, x + 105, 145), outline=(tone,) * 3, width=10)
                    draw.rectangle((5 + direction_index * 8, 5, 10 + direction_index * 8, 10), fill="white")
                canvas.save(path)
            contract = json.loads(contracts[direction].read_text(encoding="utf-8"))
            for row, path in zip(contract["phase_inventory"], phases[direction]):
                row["evidence"] = _ref(path)
            _write_json(contracts[direction], contract)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        with self.assertRaisesRegex(
            StyleReelError,
            "deterministic direction-specific WP4 fixture|trivial visual marker|distinct phase structure",
        ):
            build_style_reel_review(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                media_paths=media, contract_paths=contracts,
                phase_evidence_paths=phases, automated_report_path=report,
                output=self.root / "tiny-marker-review.json", authorized_root=self.root,
            )

    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_review_rejects_phase_sets_rotated_between_frozen_directions(
        self, _probe, _decode, _signature,
    ) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        original = {direction: [path.read_bytes() for path in phases[direction]] for direction in DIRECTIONS}
        for index, direction in enumerate(DIRECTIONS):
            donor = DIRECTIONS[(index + 1) % len(DIRECTIONS)]
            for path, data in zip(phases[direction], original[donor]):
                path.write_bytes(data)
            contract = json.loads(contracts[direction].read_text(encoding="utf-8"))
            for row, path in zip(contract["phase_inventory"], phases[direction]):
                row["evidence"] = _ref(path)
            _write_json(contracts[direction], contract)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        with self.assertRaisesRegex(
            StyleReelError, "deterministic direction-specific WP4 fixture",
        ):
            build_style_reel_review(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                media_paths=media, contract_paths=contracts,
                phase_evidence_paths=phases, automated_report_path=report,
                output=self.root / "rotated-review.json", authorized_root=self.root,
            )

    def test_only_explicit_real_project_review_can_select_and_stale_clears_decision(self) -> None:
        _, plan = self._plan()
        pending = {
            "schema_version": 1,
            "status": "pending",
            "user": {"actor": "HongRun", "decision": "pending"},
        }
        with self.assertRaises(StyleReelError):
            record_style_reel_user_decision(
                pending, actor="Agent", decision="select",
                selected_direction_id="luminous_intelligence",
                answers={key: "yes" for key in (
                    "format_fit", "person_primary", "expressive_not_noisy",
                    "semantic_help", "sonic_fit", "repeat_use_willingness",
                )}, reason="Looks good.", plan_path=self.root / "missing-plan.json",
                pending_review_path=self.root / "missing-review.json",
                authority_manifest_path=self.root / "missing-authorities.json",
                contract_paths={}, decision_receipt_output=self.root / "decision.json",
                authorized_root=self.root,
            )
        stale = mark_style_reel_stale(pending, ["candidate media hash changed"])
        self.assertEqual("stale", stale["status"])
        self.assertEqual("pending", stale["user"]["decision"])
        self.assertNotIn("stale_reasons", stale)
        errors = validate_style_reel_user_decision_receipt(
            {}, review=pending, plan_path=self.root / "missing-plan.json",
            authority_manifest_path=self.root / "missing-authorities.json",
            contract_paths={},
        )
        self.assertIn("contract path inventory", "\n".join(errors))

    def test_real_pending_review_selection_binds_current_wp6_package(self) -> None:
        pending_path = _write_json(self.root / "pending-review.json", {
            "status": "pending",
            "user": {"actor": "HongRun", "decision": "pending"},
            "reels": [],
        })
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        plan_path = _write_json(self.root / "plan.json", {"plan": "current"})
        authority_path = _write_json(
            self.root / "authorities.json", {"evidence_class": "real_project"},
        )
        package_path = _write_json(self.root / "wp6-review-package.json", {"current": True})
        contracts = {
            direction: _write_json(self.root / f"{direction}.json", {"direction": direction})
            for direction in DIRECTIONS
        }
        receipt_path = self.root / "decision.json"
        answers = {field: "yes" for field in (
            "format_fit", "person_primary", "expressive_not_noisy",
            "semantic_help", "sonic_fit", "repeat_use_willingness",
        )}
        with (
            patch("portrait_style_reel.validate_style_reel_review", return_value=[]),
            patch(
                "portrait_style_reel.validate_wp6_real_style_reel_review_package",
                return_value=[],
            ),
            patch(
                "portrait_style_reel.validate_style_reel_authority_manifest",
                return_value=[],
            ),
        ):
            approved = record_style_reel_user_decision(
                pending, actor="HongRun", decision="select",
                selected_direction_id="luminous_intelligence", answers=answers,
                reason="整体感觉都还可以", pending_review_path=pending_path,
                plan_path=plan_path, authority_manifest_path=authority_path,
                contract_paths=contracts, decision_receipt_output=receipt_path,
                authorized_root=self.root, wp6_review_package_path=package_path,
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            errors = validate_style_reel_user_decision_receipt(
                receipt, review=approved, plan_path=plan_path,
                authority_manifest_path=authority_path, contract_paths=contracts,
                wp6_review_package_path=package_path,
            )
        self.assertEqual("approved", approved["status"])
        self.assertEqual("luminous_intelligence", approved["user"]["selected_direction_id"])
        self.assertEqual(str(package_path), receipt["wp6_review_package"]["path"])
        self.assertEqual([], errors)

    def test_wp6_package_validator_rejects_non_package_bytes(self) -> None:
        package_path = _write_json(self.root / "not-a-package.json", {"status": "pass"})
        errors = validate_wp6_real_style_reel_review_package(
            package_path, pending_review_path=self.root / "missing-review.json",
            plan_path=self.root / "missing-plan.json",
            authority_manifest_path=self.root / "missing-authorities.json",
            contract_paths={},
        )
        self.assertTrue(errors)
        self.assertIn("package", "\n".join(errors).lower())

    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_synthetic_fixture_cannot_cross_named_user_brand_gate(
        self, _probe, _decode, _signature,
    ) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        review = build_style_reel_review(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            media_paths=media, contract_paths=contracts,
            phase_evidence_paths=phases, automated_report_path=report,
            output=self.root / "style-reel-review.json", authorized_root=self.root,
        )
        answers = {key: "yes" for key in (
            "format_fit", "person_primary", "expressive_not_noisy",
            "semantic_help", "sonic_fit", "repeat_use_willingness",
        )}
        with self.assertRaisesRegex(StyleReelError, "synthetic"):
            record_style_reel_user_decision(
                review, actor="HongRun", decision="select",
                selected_direction_id="luminous_intelligence", answers=answers,
                reason="这套表达适合未来个人口播。", pending_review_path=self.root / "style-reel-review.json",
                plan_path=plan_path, authority_manifest_path=self._authority_manifest(plan_path),
                contract_paths=contracts, decision_receipt_output=self.root / "decision.json",
                authorized_root=self.root,
            )
        forged = deepcopy(review)
        forged["status"] = "approved"
        forged["user"] = {
            "actor": "HongRun", "decision": "select",
            "selected_direction_id": "luminous_intelligence",
            **answers, "reason": "forged", "reviewed_at": "2026-08-12T00:00:00Z",
        }
        forged_errors = validate_style_reel_review(
            forged, plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            contract_paths=contracts,
        )
        self.assertIn("synthetic", "\n".join(forged_errors))
        self.assertIn("explicit", "\n".join(forged_errors))
        media[DIRECTIONS[0]].write_bytes(b"later drift")
        with self.assertRaisesRegex(StyleReelError, "synthetic"):
            record_style_reel_user_decision(
                review, actor="HongRun", decision="select",
                selected_direction_id="luminous_intelligence", answers=answers,
                reason="旧决定不可重放。", plan_path=plan_path,
                pending_review_path=self.root / "style-reel-review.json",
                authority_manifest_path=self._authority_manifest(plan_path),
                contract_paths=contracts, decision_receipt_output=self.root / "decision.json",
                authorized_root=self.root,
            )

    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_dashboard_has_synchronized_abcs_events_audio_questions_and_escapes_xss(self, _probe, _decode, _signature) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        review_path = self.root / "style-reel-review.json"
        build_style_reel_review(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            media_paths=media, contract_paths=contracts,
            phase_evidence_paths=phases, automated_report_path=report,
            output=review_path, authorized_root=self.root,
        )
        context_path = _write_json(self.root / "style-reel-context.json", {
            "schema_version": 1,
            "plan": _ref(plan_path),
            "authority_manifest": _ref(self._authority_manifest(plan_path)),
            "review": _ref(review_path),
            "comparison_basis_sha256": sha256(json.dumps(
                plan["comparison_basis"], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "baseline_media": _ref(_write(self.root / "baseline.mp4", b"baseline")),
            "baseline_duration_seconds": 36.0,
            "events": self._context_events(contracts, plan_path),
        })
        output = self.root / "portrait-style-review.html"
        manifest = generate_style_reel_dashboard(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            review_path=review_path, context_path=context_path,
            contract_paths=contracts, output=output,
        )
        document = output.read_text(encoding="utf-8")
        self.assertIn("Source / Baseline", document)
        for direction in DIRECTIONS:
            self.assertIn(direction, document)
        self.assertIn("syncAll", document)
        self.assertIn("SFX", document)
        self.assertIn("是否愿意反复使用", document)
        self.assertIn("@media(max-width:760px)", document)
        self.assertNotIn("<script>alert(1)</script>", document)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", document)
        self.assertEqual("pending_only", manifest["interaction_policy"])
        self.assertEqual(_sha(output), manifest["html"]["sha256"])
        interactive_output = self.root / "portrait-style-review-interactive.html"
        interactive_manifest = generate_style_reel_dashboard(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            review_path=review_path,
            context_path=context_path,
            contract_paths=contracts,
            output=interactive_output,
            interactive_api_url="http://127.0.0.1:8765/api/proposals",
            interactive_session={"authorization": "ephemeral-a", "csrf": "ephemeral-c"},
        )
        interactive_document = interactive_output.read_text(encoding="utf-8")
        self.assertEqual("pending_proposals_only", interactive_manifest["interaction_policy"])
        self.assertNotIn("DIRECTOR_REVIEW_TOKEN", interactive_document)
        self.assertNotIn("DIRECTOR_REVIEW_CSRF_TOKEN", interactive_document)
        self.assertNotIn("window.prompt", interactive_document)
        stale_context = json.loads(context_path.read_text(encoding="utf-8"))
        stale_context["events"][0]["source_sentence"] = "invented sentence"
        stale_context["events"][0]["audio_auditions"]["voice_sfx_off"] = _ref(self.voice_stem)
        stale_context["events"][0]["audio_auditions"]["sfx_on"] = _ref(self.voice_stem)
        stale_path = _write_json(self.root / "stale-context.json", stale_context)
        context_errors = validate_style_reel_context(
            json.loads(stale_path.read_text(encoding="utf-8")), plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            review_path=review_path, contract_paths=contracts,
        )
        self.assertIn("semantic projection", "\n".join(context_errors))
        self.assertIn("displayed off audition", "\n".join(context_errors))
        self.assertIn("displayed on audition", "\n".join(context_errors))
        with self.assertRaisesRegex(StyleReelError, "loopback"):
            generate_style_reel_dashboard(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                review_path=review_path, context_path=context_path,
                contract_paths=contracts, output=self.root / "unsafe.html",
                interactive_api_url="https://evil.example/api/proposals",
            )

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    @patch("portrait_style_reel._probe_signature", return_value={"same": True})
    @patch("portrait_style_reel._full_decode", return_value=[])
    @patch("portrait_style_reel._probe_duration", return_value=36.0)
    def test_dashboard_output_cannot_escape_through_junction(
        self, _probe, _decode, _signature,
    ) -> None:
        _probe.side_effect = lambda path: 45.0 if Path(path).resolve() == self.source else 36.0
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        review_path = self.root / "style-reel-review.json"
        build_style_reel_review(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            media_paths=media, contract_paths=contracts,
            phase_evidence_paths=phases, automated_report_path=report,
            output=review_path, authorized_root=self.root,
        )
        context_path = _write_json(self.root / "style-reel-context.json", {
            "schema_version": 1,
            "plan": _ref(plan_path),
            "authority_manifest": _ref(self._authority_manifest(plan_path)),
            "review": _ref(review_path),
            "comparison_basis_sha256": sha256(json.dumps(
                plan["comparison_basis"], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "baseline_media": _ref(_write(self.root / "baseline-junction.mp4", b"baseline")),
            "baseline_duration_seconds": 36.0,
            "events": self._context_events(contracts, plan_path),
        })
        review_dir = plan_path.parent.parent / "review"
        with tempfile.TemporaryDirectory() as external_temp:
            outside = Path(external_temp).resolve()
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(review_dir), str(outside)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            try:
                with self.assertRaisesRegex(StyleReelError, "inside the Director root|escaped"):
                    generate_style_reel_dashboard(
                        plan_path=plan_path,
                        authority_manifest_path=self._authority_manifest(plan_path),
                        review_path=review_path, context_path=context_path,
                        contract_paths=contracts, output=review_dir / "portrait-style-review.html",
                    )
                self.assertEqual([], list(outside.iterdir()))
            finally:
                if review_dir.exists():
                    review_dir.rmdir()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
    def test_real_short_synthetic_media_passes_probe_full_decode_and_signature_gate(self) -> None:
        plan_path, plan = self._plan()
        media, contracts, phases, report = self._review_inputs(plan)
        colors = {
            "baseline": ("black", 310),
            DIRECTIONS[0]: ("navy", 350),
            DIRECTIONS[1]: ("teal", 390),
            DIRECTIONS[2]: ("maroon", 430),
        }
        generated: dict[str, Path] = {}
        for name, (color, frequency) in colors.items():
            target = self.root / "real-media" / f"{name}.mp4"
            target.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=5:d=36",
                "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration=36",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "36",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "48k",
                "-shortest", str(target),
            ], capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(0, result.returncode, result.stderr)
            generated[name] = target.resolve()
        media = {direction: generated[direction] for direction in DIRECTIONS}
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        review_path = self.root / "real-style-reel-review.json"
        review = build_style_reel_review(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            media_paths=media, contract_paths=contracts,
            phase_evidence_paths=phases, automated_report_path=report,
            output=review_path, authorized_root=self.root,
        )
        self.assertEqual([], validate_style_reel_review(
            review, plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            contract_paths=contracts,
        ))
        extra_audio = self.root / "real-media" / "extra-audio.mp4"
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(generated[DIRECTIONS[0]]),
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=36",
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "48k", "-shortest", str(extra_audio),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, result.returncode, result.stderr)
        extra_media = dict(media)
        extra_media[DIRECTIONS[0]] = extra_audio.resolve()
        self._write_automated_report(report, plan_path, plan, extra_media, contracts, phases)
        with self.assertRaisesRegex(StyleReelError, "exactly one video and one audio"):
            build_style_reel_review(
                plan_path=plan_path,
                authority_manifest_path=self._authority_manifest(plan_path),
                media_paths=extra_media, contract_paths=contracts,
                phase_evidence_paths=phases, automated_report_path=report,
                output=self.root / "invalid-extra-stream-review.json", authorized_root=self.root,
            )
        self._write_automated_report(report, plan_path, plan, media, contracts, phases)
        context_path = _write_json(self.root / "real-style-reel-context.json", {
            "schema_version": 1,
            "plan": _ref(plan_path),
            "authority_manifest": _ref(self._authority_manifest(plan_path)),
            "review": _ref(review_path),
            "comparison_basis_sha256": sha256(json.dumps(
                plan["comparison_basis"], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "baseline_media": _ref(generated["baseline"]),
            "baseline_duration_seconds": 36.0,
            "events": self._context_events(contracts, plan_path),
        })
        dashboard = self.root / "real-style-review.html"
        manifest = generate_style_reel_dashboard(
            plan_path=plan_path,
            authority_manifest_path=self._authority_manifest(plan_path),
            review_path=review_path, context_path=context_path,
            contract_paths=contracts, output=dashboard,
        )
        self.assertEqual("pending_user_review", manifest["status"])
        self.assertTrue(dashboard.is_file())
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Python Playwright is required for responsive Style Reel review")
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        if not npx:
            self.skipTest("npx is unavailable")
        browser_result = subprocess.run(
            [npx, "hyperframes", "browser", "path"], capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        if browser_result.returncode != 0:
            self.skipTest("HyperFrames browser is unavailable")
        executable = browser_result.stdout.strip().splitlines()[-1]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=executable,
                args=["--allow-file-access-from-files"],
            )
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(dashboard.resolve().as_uri(), wait_until="domcontentloaded")
                desktop = page.evaluate("""() => ({
                  videos: document.querySelectorAll('video').length,
                  overflow: document.documentElement.scrollWidth - window.innerWidth,
                  columns: getComputedStyle(document.querySelector('.reels')).gridTemplateColumns.split(' ').length,
                  heading: document.querySelector('h1').getBoundingClientRect().height
                })""")
                self.assertEqual(4, desktop["videos"])
                self.assertLessEqual(desktop["overflow"], 1)
                self.assertEqual(4, desktop["columns"])
                self.assertGreater(desktop["heading"], 0)
                page.screenshot(path=str(self.root / "style-reel-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.reload(wait_until="domcontentloaded")
                mobile = page.evaluate("""() => {
                  const cards=[...document.querySelectorAll('.reel')].map(e=>e.getBoundingClientRect());
                  return {overflow:document.documentElement.scrollWidth-window.innerWidth,
                    columns:getComputedStyle(document.querySelector('.reels')).gridTemplateColumns.split(' ').length,
                    stacked:cards.every((r,i)=>i===0||r.top>=cards[i-1].bottom-1)};
                }""")
                self.assertLessEqual(mobile["overflow"], 1)
                self.assertEqual(1, mobile["columns"])
                self.assertTrue(mobile["stacked"])
                page.screenshot(path=str(self.root / "style-reel-mobile.png"), full_page=True)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
