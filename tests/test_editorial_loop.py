from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from editorial_loop import (  # noqa: E402
    binding, validate_envelope, project_intent, build_platform_packages,
    build_learning_candidates,
)
from project_config import migrate_project_config  # noqa: E402


def fact(value=None, basis="unknown", evidence=()):
    return {"value": value, "basis": basis, "evidence_ids": list(evidence)}


class EditorialLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"real-source")
        self.record = self.root / "user.json"
        self.record.write_text('{}', encoding="utf-8")
        self.refs = [binding("source", self.source, "source"),
                     binding("user", self.record, "user_record")]

    def tearDown(self):
        self.temp.cleanup()

    def envelope(self, kind, payload):
        return {"schema_version": 1, "id": kind, "kind": kind,
                "status": "validated", "bindings": copy.deepcopy(self.refs), "payload": payload}

    def strategy(self):
        return self.envelope("strategy", {
            "identity_mode": "generic", "audience": fact(), "promise": fact(),
            "pillars": [], "tone": fact(), "boundaries": [], "series_id": None,
        })

    def test_valid_unknown_is_not_an_approval(self):
        doc = self.strategy()
        self.assertEqual(validate_envelope(doc, self.root), doc)
        doc["payload"]["audience"]["value"] = "invented"
        with self.assertRaises(ValueError):
            validate_envelope(doc, self.root)

    def test_unknown_fields_ids_and_evidence_roles_fail(self):
        for change in (
            lambda d: d.update(approved=True),
            lambda d: d["bindings"].append(d["bindings"][0]),
            lambda d: d["payload"].update(audience=fact("audience", "user_confirmed", ["source"])),
            lambda d: d["payload"].update(audience=fact("audience", "source_observed", ["missing"])),
            lambda d: d["payload"].update(audience=fact("audience", "source_observed", ["user"])),
        ):
            with self.subTest(change=change):
                doc = self.strategy()
                change(doc)
                with self.assertRaises(ValueError):
                    validate_envelope(doc, self.root)

    def test_stale_and_external_and_link_paths_fail(self):
        doc = self.strategy()
        self.source.write_bytes(b"fake-source")
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_envelope(doc, self.root)
        with tempfile.TemporaryDirectory() as external:
            path = Path(external) / "file"
            path.write_bytes(b"private")
            doc = self.strategy()
            doc["bindings"] = [binding("x", path, "source")]
            with self.assertRaisesRegex(ValueError, "outside"):
                validate_envelope(doc, self.root)
            validate_envelope(doc, self.root, allowed_read_paths=[path])
            link = self.root / "escape"
            try:
                link.symlink_to(Path(external), target_is_directory=True)
            except OSError:
                self.skipTest("symlink privilege unavailable")
            doc["bindings"][0]["path"] = str(link / "file")
            with self.assertRaisesRegex(ValueError, "outside"):
                validate_envelope(doc, self.root)

    def proof_inputs(self):
        words = [{"id": "w1", "start": 0, "end": 1},
                 {"id": "w2", "start": 2, "end": 3}]
        brief = {"events": [{"id": "e1", "transcript_word_ids": ["w1"],
                             "source_time_range": [0, 1], "viewer_takeaway": "产品演示"}]}
        proof = self.envelope("proof", {"claims": [{
            "claim_id": "c1", "claim": "产品演示", "word_ids": ["w1"],
            "event_ids": ["e1"], "evidence_ids": ["source"], "support": "supported",
        }]})
        episode = self.envelope("episode", {
            "viewer_job": fact(), "thesis": fact("产品演示", "source_observed", ["source"]),
            "takeaway": fact(), "proof_ids": ["c1"], "cta": fact(), "series_id": None,
        })
        return words, brief, proof, episode

    def test_projection_uses_existing_promise_and_keeps_words(self):
        words, brief, proof, episode = self.proof_inputs()
        before = copy.deepcopy((words, brief))
        intent = project_intent(self.strategy(), episode, proof, words, brief, identity_mode="generic")
        self.assertEqual(intent["proof_event_ids"], ["e1"])
        self.assertEqual(intent["single_promise"], "产品演示")
        self.assertEqual((words, brief), before)

    def test_wrong_identity_missing_proof_and_wrong_word_occurrence_fail(self):
        words, brief, proof, episode = self.proof_inputs()
        strategy = self.strategy()
        strategy["payload"]["identity_mode"] = "self"
        with self.assertRaisesRegex(ValueError, "identity"):
            project_intent(strategy, episode, proof, words, brief, identity_mode="third_party")
        episode["payload"]["proof_ids"] = ["absent"]
        with self.assertRaisesRegex(ValueError, "proof"):
            project_intent(self.strategy(), episode, proof, words, brief, identity_mode="generic")
        episode["payload"]["proof_ids"] = ["c1"]
        proof["payload"]["claims"][0]["word_ids"] = ["w2"]
        with self.assertRaisesRegex(ValueError, "word"):
            project_intent(self.strategy(), episode, proof, words, brief, identity_mode="generic")

    def test_all_legacy_versions_migrate_without_mutation_default_off(self):
        for version in range(1, 14):
            original = {"schema_version": version}
            migrated = migrate_project_config(original)
            self.assertEqual(original, {"schema_version": version})
            self.assertEqual(migrated["schema_version"], 14)
            self.assertEqual(migrated["editorial_loop"], {"enabled": False, "strategy_path": None})
        for cfg in ({"enabled": "yes"}, {"enabled": True, "command": "run"}, {"strategy_path": 1}):
            with self.assertRaises(ValueError):
                migrate_project_config({"editorial_loop": cfg})

    def test_no_observations_is_not_zero_or_approval(self):
        result = build_learning_candidates([], self.root, self.record)
        self.assertEqual(result["status"], "no_observations")
        self.assertEqual(result["payload"]["observations"], [])
        self.assertFalse(result["payload"]["automatic_apply"])

    def snapshot_row(self, publication, hours=24, *, video=None, views=500, traffic="organic"):
        path = self.root / f"{publication}-{hours}.json"
        published = datetime(2026, 10, 1, tzinfo=timezone.utc)
        path.write_text(json.dumps({
            "schema_version": 1, "platform": "douyin", "published_at": published.isoformat(),
            "observed_at": (published + timedelta(hours=hours)).isoformat(),
            "metrics": {"views": views, "completion_rate": 0.2},
            "binding": {"publication_id": publication, "version_id": "v1",
                        "release_manifest_sha256": "a" * 64,
                        "video_sha256": (video or publication[0]) * 64},
        }), encoding="utf-8")
        return {"snapshot": str(path), "window_hours": hours,
                "metric_definition": "completion_rate/views/v1", "denominator": views,
                "traffic_source": traffic}

    def test_learning_deduplicates_independent_videos_and_requires_comparability(self):
        first = self.snapshot_row("a", 24)
        repeated = self.snapshot_row("a", 48)
        result = build_learning_candidates([first, repeated], self.root, self.record)
        self.assertEqual(result["status"], "insufficient_evidence")
        second = self.snapshot_row("b", 24)
        result = build_learning_candidates([first, second], self.root, self.record)
        self.assertEqual(result["status"], "pending_user_review")
        self.assertFalse(result["payload"]["automatic_apply"])
        self.assertTrue(all(h["basis"] == "editorial_inference" for h in result["payload"]["hypotheses"]))
        for field, value in (("traffic_source", None), ("traffic_source", "paid"),
                             ("denominator", None), ("metric_definition", "different")):
            changed = {**second, field: value}
            self.assertEqual(build_learning_candidates([first, changed], self.root, self.record)["status"],
                             "insufficient_evidence")
        duplicate_video = self.snapshot_row("c", 24, video="a")
        self.assertEqual(build_learning_candidates([first, duplicate_video], self.root, self.record)["status"],
                         "insufficient_evidence")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_learning_candidates([first, first], self.root, self.record)
        with self.assertRaisesRegex(ValueError, "window"):
            build_learning_candidates([{**first, "window_hours": 48}], self.root, self.record)

    def test_learning_zero_is_observed_not_absent_and_raw_comments_are_rejected(self):
        row = self.snapshot_row("a", views=0)
        result = build_learning_candidates([row], self.root, self.record)
        self.assertEqual(result["payload"]["observations"][0]["denominator"], 0)
        self.assertEqual(result["status"], "insufficient_evidence")
        comments = self.root / "comments.json"
        comments.write_text('{"author":"private","text":"hello"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "anonymized"):
            build_learning_candidates([], self.root, self.record, comments_path=comments)
        comments.write_text('{"categories":{"questions":3}}', encoding="utf-8")
        result = build_learning_candidates([], self.root, self.record, comments_path=comments)
        self.assertNotIn("private", json.dumps(result))

    def test_platforms_share_master_and_reject_new_promises(self):
        from editorial_promise import build_promise_ledger
        words, brief, proof, episode = self.proof_inputs()
        intent = project_intent(self.strategy(), episode, proof, words, brief, identity_mode="generic")
        ledger = build_promise_ledger({**brief, "editorial_intent": intent})
        ledger_path = self.root / "promise.json"
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        copy_path = self.root / "copy.json"
        copy_doc = {p: {"recommended": {"title": "产品演示详解", "description": "一起看产品演示"}}
                    for p in ("douyin", "wechat_channels")}
        copy_path.write_text(json.dumps(copy_doc), encoding="utf-8")
        packages = build_platform_packages(copy_path, ledger_path, self.source, self.root)
        masters = [next(r for r in p["bindings"] if r["role"] == "master") for p in packages]
        self.assertEqual(masters[0], masters[1])
        self.assertTrue(all(not p["payload"]["publish_authorized"] for p in packages))
        copy_doc["douyin"]["recommended"]["title"] = "产品保证翻倍"
        copy_path.write_text(json.dumps(copy_doc), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "promise"):
            build_platform_packages(copy_path, ledger_path, self.source, self.root)

    def make_director(self, enabled=True):
        import yaml
        from director import Director
        project = self.root / "project.yaml"
        project.write_text(yaml.safe_dump({"schema_version": 13, "video_id": "test",
            "paths": {"root": str(self.root), "work": "work", "edit": "edit", "exports": "exports"},
            "source": {"primary_video": str(self.source), "input_mode": "existing_edit_polish"},
            "editorial_loop": {"enabled": enabled},
        }), encoding="utf-8")
        return Director(project)

    def install_bundle(self, director):
        words, brief, proof, episode = self.proof_inputs()
        directory = director.root / "editorial-loop"
        directory.mkdir()
        transcript = director.video_use_dir / "transcripts" / "source.json"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"words": words}), encoding="utf-8")
        edl = director.video_use_dir / "edl.json"
        edl.write_text('{}', encoding="utf-8")
        director.semantic_brief_path.write_text(json.dumps(brief), encoding="utf-8")
        director.evidence_bundle_path.parent.mkdir(parents=True)
        director.evidence_bundle_path.write_text('{"representative_frames":[]}', encoding="utf-8")
        refs = [binding("source", self.source, "source"), binding("transcript", transcript, "transcript"),
                binding("edl", edl, "edl"), binding("semantic", director.semantic_brief_path, "semantic_brief")]
        docs = {"strategy-snapshot.json": self.strategy(), "episode-brief.json": episode,
                "proof-map.json": proof, "content-readiness.json": self.envelope("readiness", {
                    "recommendation": "sample", "reasons": [fact("需要观看样片", "editorial_inference")],
                    "missing_evidence": [], "automatic_mutation": False})}
        for name, doc in docs.items():
            doc["bindings"] = refs
            (directory / name).write_text(json.dumps(doc), encoding="utf-8")
        return directory, transcript, edl

    def test_disabled_director_never_reads_or_creates_sidecars(self):
        from unittest.mock import patch
        director = self.make_director(False)
        with patch("editorial_loop.load_bundle", side_effect=AssertionError("should not read")):
            self.assertEqual(director._editorial_loop_gate("semantic_brief"), (None, []))
            self.assertEqual(director._editorial_platform_packages(self.source), [])
        self.assertFalse((director.root / "editorial-loop").exists())
        self.assertEqual(len(director.state["stages"]), 19)

    def test_enabled_director_missing_sidecars_action_required_not_approval(self):
        from director_contracts import DirectorContractError
        director = self.make_director()
        director._start("semantic_brief")
        with self.assertRaises(DirectorContractError):
            director._editorial_loop_gate("semantic_brief")
        self.assertEqual(director.state["stages"]["semantic_brief"]["status"], "action_required")
        request = json.loads((director.root / "editorial-loop/editorial-request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["identity_mode"], "generic")

    def test_resume_sidecar_hash_change_invalidates_semantic_not_asr(self):
        from director import Director
        from action_required_contract import sha256_file
        director = self.make_director()
        directory, transcript, edl = self.install_bundle(director)
        intent, dependencies = director._editorial_loop_gate("semantic_brief")
        hashes = [sha256_file(p) for p in (transcript, edl)]
        for stage in ("inspect", "provider_governance", "video_use_timeline", "evidence_acquisition"):
            director._complete(stage, [self.source])
        director._complete("semantic_brief", dependencies)
        resumed = Director(director.context.project_file)
        self.assertEqual(resumed.state["stages"]["semantic_brief"]["status"], "complete")
        proof_path = directory / "proof-map.json"
        content = proof_path.read_bytes()
        proof_path.write_bytes(content.replace(b'"supported"', b'"unsupport"'))  # same size
        resumed = Director(director.context.project_file)
        self.assertEqual(resumed.state["last_invalidation"]["from_stage"], "semantic_brief")
        self.assertEqual(resumed.state["stages"]["video_use_timeline"]["status"], "complete")
        self.assertEqual(hashes, [sha256_file(p) for p in (transcript, edl)])

    def test_production_contract_binds_sidecars_and_preserves_source(self):
        from editorial_promise import build_promise_ledger
        from production_contract import build_contract, validate_contract
        director = self.make_director()
        directory, transcript, edl = self.install_bundle(director)
        intent, _ = director._editorial_loop_gate("semantic_brief")
        brief = json.loads(director.semantic_brief_path.read_text(encoding="utf-8"))
        (director.root / "editorial-promise-ledger.json").write_text(json.dumps(
            build_promise_ledger({**brief, "editorial_intent": intent})), encoding="utf-8")
        args = dict(project=director.project, source_path=self.source, transcript_path=transcript,
                    edl_path=edl, semantic_brief_path=director.semantic_brief_path, input_mode=director.context.input_mode)
        contract = build_contract(**args)
        self.assertIn("editorial_loop", contract)
        self.assertEqual(validate_contract(contract, **args), [])
        path = directory / "content-readiness.json"
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.assertTrue(validate_contract(contract, **args))

    def test_real_semantic_stage_projects_ledger_without_changing_transcript(self):
        from action_required_contract import sha256_file
        director = self.make_director()
        directory, transcript, edl = self.install_bundle(director)
        frame = director.evidence_bundle_path.parent / "frame.png"
        frame.write_bytes(b"synthetic-frame-evidence")
        words = json.loads(transcript.read_text(encoding="utf-8"))["words"]
        for word in words:
            word["text"] = "产品演示"
        transcript.write_text(json.dumps({"words": words}), encoding="utf-8")
        bundle = {"transcript": {"sha256": sha256_file(transcript), "term_evidence": [
            {"word_id": w["id"], "text": w["text"], "start": w["start"], "end": w["end"]} for w in words]},
            "representative_frames": [{"path": str(frame), "sha256": sha256_file(frame)}]}
        director.evidence_bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        brief = {"schema_version": 3, "opportunity_model": "decision_complete_v1",
                 "generated_by": "fixture-llm", "content_reading": "raw_word_transcript_and_evidence_frames",
                 "transcript_sha256": sha256_file(transcript), "evidence_bundle_sha256": sha256_file(director.evidence_bundle_path),
                 "evidence_frames": [str(frame)], "opening_hook": {"status": "not_selected", "evidence": ["direct"]},
                 "events": [{"id": "e1", "decision": "reuse_source", "decision_rationale": "Source demonstrates the product",
                    "source_start": 0, "source_end": 1, "output_start": 0, "output_end": 1,
                    "anchor": "产品演示", "transcript_quote": "产品演示", "transcript_word_ids": ["w1"],
                    "viewer_takeaway": "产品演示", "target_frame_evidence": [str(frame)]}]}
        director.semantic_brief_path.write_text(json.dumps(brief), encoding="utf-8")
        for path in directory.glob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for ref in doc["bindings"]:
                ref["sha256"] = sha256_file(Path(ref["path"]))
            path.write_text(json.dumps(doc), encoding="utf-8")
        before = [sha256_file(p) for p in (transcript, edl, director.semantic_brief_path)]
        director._start("semantic_brief")
        director.stage_semantic_brief()
        self.assertEqual(director.state["stages"]["semantic_brief"]["status"], "complete")
        ledger = json.loads((director.root / "editorial-promise-ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["single_promise"]["proof_event_ids"], ["e1"])
        self.assertEqual(before, [sha256_file(p) for p in (transcript, edl, director.semantic_brief_path)])
        director._start("production_contract")
        director.stage_production_contract()
        self.assertEqual(director.state["stages"]["production_contract"]["status"], "complete")

    def test_nonfinite_duplicate_json_and_generated_proof_are_rejected(self):
        from editorial_loop import read
        path = self.root / "bad.json"
        for content in ('{"x":NaN}', '{"x":1,"x":2}'):
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                read(path)
        words, brief, proof, episode = self.proof_inputs()
        proof["bindings"][0]["role"] = "brief"
        with self.assertRaisesRegex(ValueError, "non-source"):
            project_intent(self.strategy(), episode, proof, words, brief, identity_mode="generic")
        proof["bindings"][0]["role"] = "edl"
        with self.assertRaisesRegex(ValueError, "EDL"):
            project_intent(self.strategy(), episode, proof, words, brief, identity_mode="generic")

    def test_shared_strategy_changes_reopen_semantics_without_writing_original(self):
        from action_required_contract import sha256_file
        from editorial_loop import load_bundle
        director = self.make_director()
        directory, transcript, edl = self.install_bundle(director)
        shared = self.root / "shared-strategy.json"
        strategy = json.loads((directory / "strategy-snapshot.json").read_text(encoding="utf-8"))
        shared.write_text(json.dumps(strategy), encoding="utf-8")
        original_hash = sha256_file(shared)
        strategy["bindings"].append(binding("shared", shared, "strategy"))
        (directory / "strategy-snapshot.json").write_text(json.dumps(strategy), encoding="utf-8")
        args = dict(transcript=transcript, edl=edl, source=self.source,
                    semantic_brief=director.semantic_brief_path, evidence_bundle=director.evidence_bundle_path,
                    project_file=director.context.project_file, identity_mode="generic", strategy_path=shared)
        load_bundle(directory, self.root, **args)
        self.assertEqual(sha256_file(shared), original_hash)
        shared.write_bytes(shared.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "stale"):
            load_bundle(directory, self.root, **args)

    def test_explicit_configured_intent_cannot_be_silently_replaced(self):
        from director_contracts import DirectorContractError
        director = self.make_director()
        self.install_bundle(director)
        director.project["editorial_intent"].update({"mode": "explicit", "single_promise": "different"})
        director._start("semantic_brief")
        with self.assertRaisesRegex(DirectorContractError, "conflicts"):
            director._editorial_loop_gate("semantic_brief")

    def test_new_learning_files_do_not_invalidate_completed_video_stage(self):
        from director import Director
        director = self.make_director()
        self.install_bundle(director)
        _, dependencies = director._editorial_loop_gate("semantic_brief")
        director._complete("semantic_brief", dependencies)
        path = director.root / "editorial-loop" / "learning-candidates.json"
        path.write_text(json.dumps(build_learning_candidates([], self.root, self.record)), encoding="utf-8")
        resumed = Director(director.context.project_file)
        self.assertEqual(resumed.state["stages"]["semantic_brief"]["status"], "complete")

    def test_v13_completed_contract_reopens_without_repeating_analysis(self):
        from director import Director
        director = self.make_director(False)
        for stage in ("inspect", "provider_governance", "video_use_timeline", "evidence_acquisition", "semantic_brief"):
            director._complete(stage, [self.source])
        director.production_contract_path.write_text('{"project_schema_version":13}', encoding="utf-8")
        director._complete("production_contract", [director.production_contract_path])
        before = director.context.project_file.read_bytes()
        resumed = Director(director.context.project_file)
        self.assertEqual(resumed.state["last_invalidation"]["from_stage"], "production_contract")
        self.assertEqual(resumed.state["stages"]["semantic_brief"]["status"], "complete")
        self.assertEqual(before, director.context.project_file.read_bytes())

    def test_production_stage_cannot_adopt_a_different_promise_ledger(self):
        from director_contracts import DirectorContractError
        director = self.make_director()
        self.install_bundle(director)
        (director.root / "editorial-promise-ledger.json").write_text('{"promise_id":"forged"}', encoding="utf-8")
        director._start("production_contract")
        with self.assertRaisesRegex(DirectorContractError, "promise ledger"):
            director.stage_production_contract()
        self.assertEqual(director.state["stages"]["production_contract"]["status"], "action_required")
