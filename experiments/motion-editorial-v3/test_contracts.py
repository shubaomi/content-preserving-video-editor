"""WP0 regression fixtures; never real media or approval evidence."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "scripts"))
import audit_hook_pacing as legacy
import contracts as c


class HookRegression(unittest.TestCase):
    def test_production_words_only_defect_fixed_in_wp3(self):
        result = legacy.audit({"words": [{"id": "1", "word": "介绍", "start": 2, "end": 3}]})
        self.assertEqual(result["measurements"]["first_speech"], 2)
        self.assertIsNone(result["heuristic_judgments"]["visible_evidence_score_0_5"])

    def test_words_only_now_measured_without_fake_visual_score(self):
        result = c.audit_opening({"words": [{"id": "1", "word": "介绍", "start": 2, "end": 3}]})
        self.assertEqual(result["first_speech"], 2)
        self.assertEqual(result["duration"], 3)
        self.assertIsNone(result["visible_evidence_score"])

    def test_segments_and_mixed_do_not_double_count(self):
        segment = {"text": "介绍", "start": 2, "end": 3}
        self.assertEqual(c.audit_opening({"segments": [segment]})["speech_units"], 1)
        self.assertEqual(c.audit_opening({"segments": [segment], "words": [{"id": "1", "text": "介绍", "start": 2, "end": 3}]})["speech_units"], 1)

    def test_empty_unknown_not_zero(self):
        result = c.audit_opening({"words": []})
        self.assertEqual(result["state"], "unknown")
        self.assertIsNone(result["first_speech"])
        self.assertIsNone(result["first_value_cue"])

    def test_bad_words_rejected(self):
        for word in [dict(id="1", text="", start=0, end=1), dict(id="1", text="x", start=1, end=0), dict(id="1", text="x", start=0, end=float("nan"))]:
            with self.subTest(word=word), self.assertRaises(c.ContractError):
                c.audit_opening({"words": [word]})

    def test_duplicate_word_ids_rejected(self):
        word = dict(id="1", text="x", start=0, end=1)
        with self.assertRaises(c.ContractError):
            c.normalize_speech({"words": [word, word]})


class Contracts(unittest.TestCase):
    def setUp(self):
        self.examples = c.load_json(ROOT / "references/motion-editorial-v3-design/examples/contracts.json")["examples"]

    def test_design_examples_pass_structure(self):
        for artifact in self.examples:
            c.validate_contract(artifact)

    def test_no_fixture_promoted_to_runtime(self):
        with self.assertRaises(c.ContractError):
            c.verify_evidence(self.examples[0], [ROOT])

    def test_no_self_approval_fields(self):
        a = copy.deepcopy(self.examples[0]); a["payload"]["approved"] = True
        with self.assertRaises(c.ContractError): c.validate_contract(a)

    def test_strict_json(self):
        for value in ['{"x": NaN}', '{"x": Infinity}', '{"x":1,"x":2}', '{"x":1e999}']:
            with self.subTest(value=value), self.assertRaises(c.ContractError): c.loads_strict(value)

    def test_bad_ranges_and_references(self):
        mutations = [lambda a: a["payload"]["candidates"][0]["source_range"].update(end=1), lambda a: a["payload"]["candidates"][0].update(source_ref="transcript"), lambda a: a["payload"]["candidates"][0].update(frame_refs=["absent"]), lambda a: a["inputs"].append(copy.deepcopy(a["inputs"][0])), lambda a: a["inputs"].pop()]
        for mutate in mutations:
            a = copy.deepcopy(self.examples[0]); mutate(a)
            with self.subTest(a=a), self.assertRaises(c.ContractError): c.validate_contract(a)

    def test_hook_duration_not_stretched(self):
        a = copy.deepcopy(self.examples[0]); a["payload"]["candidates"][0]["source_range"]["end"] = 18
        with self.assertRaises(c.ContractError): c.validate_contract(a)

    def test_word_mapping_and_identity(self):
        for change in [dict(occurrence_id="bad"), dict(output_range={"start": 1, "end": 2}), dict(segment_id="bad"), dict(source_range={"start": 9, "end": 11})]:
            a = copy.deepcopy(self.examples[1]); a["payload"]["words"][0].update(change)
            with self.subTest(change=change), self.assertRaises(c.ContractError): c.validate_contract(a)

    def test_segment_overlap_and_total(self):
        for change in [lambda p: p["segments"][1].update(output_start=2), lambda p: p.update(output_duration=24), lambda p: p["segments"][1].update(segment_id="hook1")]:
            a = copy.deepcopy(self.examples[1]); change(a["payload"])
            with self.assertRaises(c.ContractError): c.validate_contract(a)

    def test_crop_and_recipe_constraints(self):
        a = copy.deepcopy(self.examples[2]); a["payload"]["events"][0]["source_crop"] = dict(x=0,y=0,w=1,h=1)
        with self.assertRaises(c.ContractError): c.validate_contract(a)
        event = a["payload"]["events"][0]; event.update(decision="shot", recipe="B01", source_crop=dict(x=.5,y=0,w=.6,h=1), phases=[dict(phase=p,start=i/4,end=(i+1)/4,behavior="test") for i,p in enumerate(c.PHASES)])
        with self.assertRaises(c.ContractError): c.validate_contract(a)
        event.update(recipe="A01", source_crop=dict(x=0,y=0,w=1,h=1)); c.validate_contract(a)
        event["phases"][2]["start"] = .1
        with self.assertRaises(c.ContractError): c.validate_contract(a)

    def test_motion_sample_not_opening(self):
        a = copy.deepcopy(self.examples[3]); a["payload"].update(purpose="opening_edit", duration=50, comparison="opening_structure_review")
        with self.assertRaises(c.ContractError): c.validate_contract(a)
        a["payload"]["output_start"] = 0; c.validate_contract(a)

    def test_budget_and_full_render_flags(self):
        for change in [dict(duration=16), dict(max_new_motion_seconds=61), dict(max_attempts_per_direction=3), dict(full_render_authorized=True), dict(user_review="pass")]:
            a = copy.deepcopy(self.examples[3]); a["payload"].update(change)
            with self.assertRaises(c.ContractError): c.validate_contract(a)

    def test_current_hash_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); f = root / "evidence.txt"; f.write_text("fixture", encoding="utf-8")
            a = copy.deepcopy(self.examples[0]); a["evidence_tier"] = "runtime"
            for entry in a["inputs"]: entry.update(path=str(f), sha256=c.sha256(f))
            c.verify_evidence(a, [root])
            with self.assertRaises(c.ContractError): c.verify_evidence(a, [root / "other"])
            a["inputs"][0]["path"] = "evidence.txt"
            with self.assertRaises(c.ContractError): c.verify_evidence(a, [root])

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); allowed = root / "allowed"; allowed.mkdir()
            outside = root / "outside.txt"; outside.write_text("fixture", encoding="utf-8")
            link = allowed / "link.txt"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"OS denies symlink creation: {exc}")
            a = copy.deepcopy(self.examples[0]); a["evidence_tier"] = "runtime"
            for entry in a["inputs"]: entry.update(path=str(link), sha256=c.sha256(outside))
            with self.assertRaises(c.ContractError): c.verify_evidence(a, [allowed])

    def test_stale_hash_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            f = root / "evidence.txt"
            f.write_text("fixture", encoding="utf-8")
            a = copy.deepcopy(self.examples[0])
            a["evidence_tier"] = "runtime"
            for entry in a["inputs"]:
                entry.update(path=str(f), sha256=c.sha256(f))
            f.write_text("changed", encoding="utf-8")
            with self.assertRaises(c.ContractError):
                c.verify_evidence(a, [root])


class ProjectionBindings(unittest.TestCase):
    def setUp(self):
        self.a = c.load_json(ROOT / "references/motion-editorial-v3-design/examples/contracts.json")["examples"][1]
        self.p = self.a["payload"]
        self.base = [dict(segment_id="original1", source_ref="source", source_range=dict(start=0,end=20), output_start=0, speed=1)]
        self.words = [dict(id="w1", text="测试", start=10,end=11)]

    def verify(self):
        c.validate_projection_bindings(self.a, self.base, self.words, self.p["segments"])

    def test_duplicate_occurrences_are_valid(self): self.verify()

    def test_baseline_gaps_preserved(self):
        self.base[0]["output_start"] = 2
        with self.assertRaises(c.ContractError): self.verify()
        self.p["segments"][1]["output_start"] = 5; self.p["output_duration"] = 25; self.p["words"][1]["output_range"] = dict(start=15,end=16)
        self.verify()

    def test_missing_word_rejected(self):
        self.p["words"].pop()
        with self.assertRaises(c.ContractError): self.verify()

    def test_half_word_rejected(self):
        self.words[0]["start"] = 9.5
        with self.assertRaises(c.ContractError): self.verify()

    def test_changed_body_rejected(self):
        self.base[0]["source_range"]["end"] = 19
        with self.assertRaises(c.ContractError): self.verify()

    def test_second_hook_rejected(self):
        self.p["segments"][1]["role"] = "hook"
        with self.assertRaises(c.ContractError): self.verify()

    def test_changed_edl_rejected(self):
        edl = copy.deepcopy(self.p["segments"]); edl[1]["output_start"] = 8
        with self.assertRaises(c.ContractError): c.validate_projection_bindings(self.a, self.base, self.words, edl)

    def test_receipt_needs_external_authority_not_boolean(self):
        receipt = {"approved": True}
        with self.assertRaises(c.ContractError): c.validate_hook_authority(self.a, receipt, None)

    def test_receipt_hash_scope_candidate_and_external_decision(self):
        plan = c.load_json(ROOT / "references/motion-editorial-v3-design/examples/contracts.json")["examples"][0]
        receipt = dict(kind="hook_excerpt", scope="short_preview", candidate_id="h1", original_user_message="SYNTHETIC only", operator="synthetic", timestamp="synthetic", input_hashes={i["id"]:i["sha256"] for i in self.a["inputs"]})
        c.validate_hook_authority(self.a, receipt, lambda *_: True, plan)
        with self.assertRaises(c.ContractError): c.validate_hook_authority(self.a, receipt, lambda *_: False, plan)
        for change in [dict(scope="full_render"), dict(candidate_id="not-h1"), dict(input_hashes={}), dict(original_user_message="")]:
            altered = copy.deepcopy(receipt); altered.update(change)
            with self.subTest(change=change), self.assertRaises(c.ContractError): c.validate_hook_authority(self.a, altered, lambda *_: True, plan)
        plan["payload"]["candidates"][0]["source_range"]["end"] = 14
        with self.assertRaises(c.ContractError): c.validate_hook_authority(self.a, receipt, lambda *_: True, plan)


class HookContentBindings(unittest.TestCase):
    def setUp(self):
        self.hook = c.load_json(ROOT / "references/motion-editorial-v3-design/examples/contracts.json")["examples"][0]
        self.words = {"source": [dict(id="w1",text="合成测试",start=10,end=11)]}
        self.frames = {"evidence": dict(source_ref="source",timestamp=12)}
        self.durations = {"source":20}

    def verify(self):
        c.validate_hook_bindings(self.hook,self.words,self.frames,self.durations,{"s1"})

    def test_hook_binds_words_quote_frames_and_payoff(self): self.verify()

    def test_invented_word_or_quote_rejected(self):
        candidate = self.hook["payload"]["candidates"][0]
        candidate["word_ids"] = ["madeup"]
        with self.assertRaises(c.ContractError): self.verify()
        candidate["word_ids"] = ["w1"]; candidate["quote"] = "invented"
        with self.assertRaises(c.ContractError): self.verify()

    def test_halfword_and_outside_source_rejected(self):
        self.words["source"][0]["start"] = 9.9
        with self.assertRaises(c.ContractError): self.verify()
        self.words["source"][0]["start"] = 10; self.durations["source"] = 12
        with self.assertRaises(c.ContractError): self.verify()

    def test_missing_or_unrelated_frame_rejected(self):
        for frame in [dict(source_ref="source",timestamp=13), dict(source_ref="other",timestamp=12), dict(source_ref="source",timestamp=float("nan"))]:
            self.frames["evidence"] = frame
            with self.assertRaises(c.ContractError): self.verify()
        self.frames.clear()
        with self.assertRaises(c.ContractError): self.verify()

    def test_missing_retained_payoff_rejected(self):
        with self.assertRaises(c.ContractError): c.validate_hook_bindings(self.hook,self.words,self.frames,self.durations,set())


class Migration(unittest.TestCase):
    def test_legacy_versions_disabled_and_input_unchanged(self):
        for version in range(1,15):
            source = {"schema_version": version, "other": {"unchanged": True}}
            before = copy.deepcopy(source); result = c.migrate_fixture(source)
            self.assertEqual(source,before); self.assertEqual(result["schema_version"],15)
            self.assertFalse(result["motion_editorial"]["enabled"])
            self.assertEqual(result["other"],source["other"])

    def test_unknown_versions_and_injected_legacy_config_rejected(self):
        for source in [{"schema_version":0}, {"schema_version":16}, {"schema_version":True}, {"schema_version":14,"motion_editorial":{"enabled":True}}]:
            with self.assertRaises(c.ContractError): c.migrate_fixture(source)

    def test_wp0_cannot_enable_runtime(self):
        source = c.migrate_fixture({"schema_version":14}); source["motion_editorial"]["enabled"] = True
        with self.assertRaises(c.ContractError): c.migrate_fixture(source)

    def test_disabled_settings_do_not_accept_loose_python_equality(self):
        for key,value in [("enabled",0), ("version",1.0), ("version",True)]:
            source = c.migrate_fixture({"schema_version":14}); source["motion_editorial"][key] = value
            with self.subTest(key=key,value=value), self.assertRaises(c.ContractError): c.migrate_fixture(source)


if __name__ == "__main__": unittest.main()
