"""Production projection contracts: pure derivation never owns an edit."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import editorial_projection as ep


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.edl = {"owner": "video-use", "sources": {"cam": "source.mp4"}, "ranges": [
            {"source": "cam", "start": 0, "end": 4, "timeline_start": 2},
            {"source": "cam", "start": 8, "end": 12, "timeline_start": 8},
        ], "total_duration_s": 12}
        self.words = {"words": [
            {"id": 1, "text": "真实", "start": 1, "end": 2},
            {"id": 2, "text": "讲解", "start": 2, "end": 3},
            {"id": 3, "text": "结果", "start": 9, "end": 10},
        ]}
        self.hashes = {key: str(i) * 64 for i, key in enumerate(
            ("source", "transcript", "base_edl", "candidate_edl", "hook_plan"), 1)}

    def build(self, **kwargs):
        args = dict(baseline_edl=self.edl, candidate_edl=copy.deepcopy(self.edl),
                    transcript=self.words, fps={"numerator": 30000, "denominator": 1001},
                    input_hashes={k: v for k, v in self.hashes.items() if k != "hook_plan"})
        args.update(kwargs)
        return ep.build_projection(**args)

    def duplicate(self):
        candidate = copy.deepcopy(self.edl)
        for row in candidate["ranges"]:
            row["timeline_start"] += 3
        candidate["ranges"].insert(0, {"source": "cam", "start": 8, "end": 11,
                                           "timeline_start": 0, "role": "hook"})
        candidate["total_duration_s"] += 3
        plan = {"state": "proposed", "candidates": [{
            "id": "h1", "source_ref": "cam", "source_range": {"start": 8, "end": 11},
            "word_ids": [3], "quote": "结果", "context_before": "介绍产品", "context_after": "解释结果",
            "promise": "看到真实结果", "payoff_semantic_ids": ["result"], "frame_refs": ["frame1"],
        }]}
        approval = {"kind": "hook_excerpt", "scope": "short_preview", "candidate_id": "h1",
                    "original_user_message": "批准此精确短片", "operator": "human", "timestamp": "2026-10-12T00:00:00Z",
                    "input_hashes": {k: v for k, v in self.hashes.items() if k != "candidate_edl"}}
        return dict(candidate_edl=candidate, hook_plan=plan, approval=approval,
                    mode="approved_duplicate", input_hashes=self.hashes, authority=lambda *_: True)

    def test_preserve_order_keeps_gaps_and_does_not_mutate(self):
        before = copy.deepcopy((self.edl, self.words))
        p = self.build()
        self.assertEqual((self.edl, self.words), before)
        self.assertEqual(p["summary"], {"mode": "preserve_order", "output_duration": 12.0})
        self.assertNotIn("approval", p)
        self.assertEqual([s["output_start"] for s in p["segments"]], [2, 8])
        self.assertEqual([w["output_start"] for w in p["words"]], [3, 4, 9])
        self.assertEqual(len({w["occurrence_id"] for w in p["words"]}), 3)

    def test_ranges_segments_and_implicit_cursor(self):
        edl = {"source": "cam", "segments": [{"start": 0, "end": 4}, {"start": 8, "end": 12}]}
        p = self.build(baseline_edl=edl, candidate_edl=copy.deepcopy(edl), fps="24000/1001")
        self.assertEqual([s["output_start"] for s in p["segments"]], [0, 4])
        self.assertEqual(p["fps"], {"numerator": 24000, "denominator": 1001})

    def test_half_up_not_bankers_rounding(self):
        self.assertEqual(ep.seconds_to_frame(0.05, {"numerator": 30, "denominator": 1}), 2)
        self.assertEqual(ep.seconds_to_frame(0.15, "30/1"), 5)

    def test_preserve_order_rejects_edl_tampering(self):
        mutations = [lambda e: e["ranges"].pop(), lambda e: e["ranges"].reverse(),
                     lambda e: e["ranges"].append(copy.deepcopy(e["ranges"][0])),
                     lambda e: e["ranges"][0].update(start=.5),
                     lambda e: e["ranges"][0].update(speed=2),
                     lambda e: e["ranges"][1].update(timeline_start=6),
                     lambda e: e.update(total_duration_s=13),
                     lambda e: e["sources"].update(cam="other.mp4"),
                     lambda e: e["ranges"][0].update(role="hook"),
                     lambda e: e.update(approval_ref="not-allowed")]
        for mutate in mutations:
            candidate = copy.deepcopy(self.edl); mutate(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.build(candidate_edl=candidate)

    def test_no_hook_authority_fields_in_preserve_mode(self):
        for fields in ({"hook_plan": {}}, {"approval": {}}, {"authority": lambda *_: True},
                       {"input_hashes": self.hashes}):
            with self.subTest(fields=fields), self.assertRaises(ValueError): self.build(**fields)

    def test_invalid_numbers_modes_fps_ids_hashes(self):
        for fields in ({"mode": "automatic"}, {"fps": 29.97}, {"fps": "1/0"},
                       {"fps": True}, {"input_hashes": {}},
                       {"input_hashes": dict(self.hashes, source="not-a-hash")}):
            with self.subTest(fields=fields), self.assertRaises(ValueError): self.build(**fields)
        for value in (float("nan"), float("inf"), True, -1):
            edl = copy.deepcopy(self.edl); edl["ranges"][0]["start"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): self.build(baseline_edl=edl, candidate_edl=edl)
        words = copy.deepcopy(self.words); words["words"][1]["id"] = 1
        with self.assertRaises(ValueError): self.build(transcript=words)

    def test_half_word_and_duplicate_segment_ids_rejected(self):
        edl = copy.deepcopy(self.edl); edl["ranges"][0]["start"] = 1.5
        with self.assertRaises(ValueError): self.build(baseline_edl=edl, candidate_edl=edl)
        edl = copy.deepcopy(self.edl)
        for row in edl["ranges"]: row["segment_id"] = "same"
        with self.assertRaises(ValueError): self.build(baseline_edl=edl, candidate_edl=edl)

    def test_duplicate_creates_unique_occurrences_and_preserves_body(self):
        p = self.build(**self.duplicate())
        self.assertEqual([s["output_start"] for s in p["segments"]], [0, 5, 11])
        self.assertEqual(p["output_duration"], 15)
        self.assertEqual([w["source_word_id"] for w in p["words"]], ["3", "1", "2", "3"])
        self.assertEqual(len({w["occurrence_id"] for w in p["words"]}), 4)

    def test_duplicate_requires_exact_external_authority(self):
        for mutate in (lambda a: a.update(authority=None), lambda a: a.update(authority=lambda *_: False),
                       lambda a: a["approval"].update(scope="full_render"),
                       lambda a: a["approval"]["input_hashes"].update(source="f" * 64),
                       lambda a: a["approval"].update(candidate_id="unknown"),
                       lambda a: a["hook_plan"]["candidates"][0]["source_range"].update(end=12),
                       lambda a: a["hook_plan"]["candidates"][0].update(quote="虚构"),
                       lambda a: a["candidate_edl"]["ranges"][1].update(timeline_start=4)):
            a = self.duplicate(); mutate(a)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.build(**a)

    def test_callback_context_has_exact_bound_inputs_not_shared_mutables(self):
        args = self.duplicate(); observed = []
        def authority(receipt, context):
            observed.append(context)
            self.assertEqual(context["input_hashes"], self.hashes)
            self.assertEqual(context["hook_plan"], args["hook_plan"])
            context["hook_plan"]["candidates"].clear()
            return True
        args["authority"] = authority
        self.build(**args)
        self.assertEqual(len(args["hook_plan"]["candidates"]), 1)
        self.assertEqual(observed[0]["scope"], "short_preview")

    def test_multisource_requires_unambiguous_transcripts(self):
        edl = copy.deepcopy(self.edl); edl["ranges"][1]["source"] = "other"
        edl["sources"]["other"] = "other.mp4"
        with self.assertRaises(ValueError): self.build(baseline_edl=edl, candidate_edl=edl)
        p = self.build(baseline_edl=edl, candidate_edl=edl, transcript={"cam": self.words, "other": self.words})
        self.assertEqual({w["source_ref"] for w in p["words"]}, {"cam", "other"})

    def test_instances_and_v4_keep_source_and_sort_output_instances(self):
        p = self.build(**self.duplicate())
        brief = {"schema_version": 3, "events": [
            {"id": "first", "source_start": 1, "source_end": 3, "transcript_word_ids": [1, 2]},
            {"id": "result", "source_start": 9, "source_end": 10, "transcript_word_ids": [3]},
        ]}
        old = copy.deepcopy(brief); out = ep.project_semantics(brief, p)
        self.assertEqual(brief, old)
        self.assertEqual(out["schema_version"], 4)
        self.assertEqual([e["source_semantic_id"] for e in out["events"]], ["result", "first", "result"])
        self.assertEqual([e["output_start"] for e in out["events"]], [1, 6, 12])
        self.assertEqual(len({e["id"] for e in out["events"]}), 3)
        for kind in ("caption", "sfx", "target", "promise", "nle"):
            rows = [{"event_id": kind, "source_start": 9, "source_end": 10, "word_ids": [3]}]
            projected = ep.project_instances(rows, p)
            self.assertEqual([r["output_start"] for r in projected], [1, 12])
            self.assertEqual([r["source_event_id"] for r in projected], [kind, kind])

    def test_instance_unknown_word_partial_or_ambiguous_time_rejected(self):
        p = self.build()
        rows = [{"event_id": "a", "source_start": 1, "source_end": 3, "word_ids": ["fake"]}]
        with self.assertRaises(ValueError): ep.project_instances(rows, p)
        rows[0].update(source_end=10, word_ids=[])
        with self.assertRaises(ValueError): ep.project_instances(rows, p)
        with self.assertRaises(ValueError): ep.project_instances([{"event_id": "b", "start": 1, "end": 2}], p)
        with self.assertRaises(ValueError): ep.project_semantics({"schema_version": 4, "events": []}, p)

    def test_downstream_rejects_tampered_projection(self):
        for mutate in (lambda p: p["words"][0].update(output_start=3.5),
                       lambda p: p["segments"][0].update(output_end_frame=1),
                       lambda p: p.update(full_render_authorized=True),
                       lambda p: p["segments"][0].update(role="hook"),
                       lambda p: p["words"].append(copy.deepcopy(p["words"][0]))):
            p = self.build(); mutate(p)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                ep.project_instances([], p)

    def test_v4_validator_recomputes_without_changing_legacy_source(self):
        p = self.build()
        brief = {"schema_version": 3, "events": [
            {"id": "first", "source_start": 1, "source_end": 3, "transcript_word_ids": [1, 2]}]}
        out = ep.project_semantics(brief, p)
        self.assertEqual(ep.validate_output_semantics(out, brief, p), [])
        self.assertEqual(ep.validate_output_semantics(out), [])
        out["events"][0]["source_semantic_id"] = "invented"
        self.assertTrue(ep.validate_output_semantics(out, brief, p))
        self.assertTrue(ep.validate_output_semantics(out))

    def test_path_source_key_is_not_confused_with_occurrence_separator(self):
        edl = {"source": "E:/recordings/test.mp4", "ranges": [{"start": 0, "end": 4}]}
        p = self.build(baseline_edl=edl, candidate_edl=edl)
        self.assertEqual(p["words"][0]["source_ref"], "E:/recordings/test.mp4")

    def test_hook_cannot_reintroduce_previously_unretained_source(self):
        args = self.duplicate()
        args["candidate_edl"]["ranges"][0].update(start=5, end=8)
        args["hook_plan"]["candidates"][0]["source_range"] = {"start": 5, "end": 8}
        with self.assertRaisesRegex(ValueError, "retained body"):
            self.build(**args)

    def test_output_word_references_must_remain_in_source_order(self):
        with self.assertRaisesRegex(ValueError, "source order"):
            ep.project_instances([{"event_id": "a", "source_start": 1, "source_end": 3,
                                   "word_ids": [2, 1]}], self.build())

    def test_promise_proof_ids_expand_to_exact_output_occurrences(self):
        p = self.build(**self.duplicate())
        brief = {"schema_version": 3, "events": [
            {"id": "result", "source_start": 9, "source_end": 10, "transcript_word_ids": [3]}],
            "editorial_intent": {"proof_event_ids": ["result"]},
            "single_promise": {"proof_event_ids": ["result"]}}
        out = ep.project_semantics(brief, p)
        for key in ("editorial_intent", "single_promise"):
            self.assertEqual(out[key]["proof_event_ids"], [event["id"] for event in out["events"]])
            self.assertEqual(out[key]["source_proof_event_ids"], ["result"])
        self.assertEqual(out["events"][0]["transcript_word_ids"], [3])
        self.assertEqual(ep.validate_output_semantics(out), [])
        brief["single_promise"]["proof_event_ids"] = ["unknown"]
        with self.assertRaises(ValueError): ep.project_semantics(brief, p)

    def linked_brief(self):
        return {"schema_version": 3, "events": [
            {"id": "result", "source_start": 9, "source_end": 10,
             "transcript_word_ids": [3], "target_binding_ids": ["chart"],
             "explanation": {"proof_event_ids": ["result"]}}],
            "cover_direction": {"evidence_event_ids": ["result"]},
            "proof_event_ids": ["result"],
            "claims": [{"proof_event_ids": ["result"]}]}

    def test_target_cover_and_nested_proofs_follow_duplicate_instances(self):
        brief = self.linked_brief(); original = copy.deepcopy(brief)
        out = ep.project_semantics(brief, self.build(**self.duplicate()))
        ids = [e["id"] for e in out["events"]]
        self.assertEqual(brief, original)
        self.assertEqual(out["cover_direction"]["evidence_event_ids"], ids)
        self.assertEqual(out["cover_direction"]["source_evidence_event_ids"], ["result"])
        self.assertEqual(out["claims"][0]["proof_event_ids"], ids)
        self.assertEqual(out["proof_event_ids"], ids)
        for event in out["events"]:
            self.assertEqual(event["target_binding_ids"], [f'chart@{event["segment_id"]}'])
            self.assertEqual(event["source_target_binding_ids"], ["chart"])
            self.assertEqual(event["explanation"]["proof_event_ids"], [event["id"]])
            self.assertEqual(event["explanation"]["source_proof_event_ids"], ["result"])
        self.assertEqual(ep.validate_output_semantics(out), [])

    def test_linked_ids_reject_unknown_duplicates_and_preprojected_sources(self):
        mutations = [lambda b: b["cover_direction"].update(evidence_event_ids=["missing"]),
                     lambda b: b["claims"][0].update(proof_event_ids=["missing"]),
                     lambda b: b["events"][0].update(target_binding_ids=["chart", "chart"]),
                     lambda b: b["events"][0].update(target_binding_ids=["chart@segment"]),
                     lambda b: b["claims"][0].update(source_proof_event_ids=["forged"])]
        for mutate in mutations:
            brief = self.linked_brief(); mutate(brief)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                ep.project_semantics(brief, self.build())

    def test_local_proof_does_not_guess_across_segments(self):
        brief = self.linked_brief()
        brief["events"].insert(0, {"id": "earlier", "source_start": 1, "source_end": 3,
                                    "transcript_word_ids": [1, 2]})
        brief["events"][1]["explanation"]["proof_event_ids"] = ["earlier"]
        with self.assertRaisesRegex(ValueError, "segment"):
            ep.project_semantics(brief, self.build(**self.duplicate()))

    def test_projected_target_and_cover_drift_invalidates_binding(self):
        for mutate in (lambda b: b["events"][0]["target_binding_ids"].append("chart@stale"),
                       lambda b: b["cover_direction"].update(evidence_event_ids=["result"]),
                       lambda b: b["claims"][0].update(proof_event_ids=[])):
            out = ep.project_semantics(self.linked_brief(), self.build())
            mutate(out)
            self.assertTrue(ep.validate_output_semantics(out))

    def test_source_only_copy_policy_preserves_source_and_word_authority(self):
        brief = self.linked_brief()
        brief["events"][0].update(decision="render", approved_visible_copy=["真实结果"],
                                  editorial_copy_policy="source_only")
        original = copy.deepcopy(brief)
        out = ep.project_semantics(brief, self.build(**self.duplicate()))
        self.assertEqual(brief, original)
        for event in out["events"]:
            self.assertEqual(event["approved_visible_copy"], [])
            self.assertEqual(event["source_approved_visible_copy"], ["真实结果"])
            self.assertEqual(event["transcript_word_ids"], [3])
            self.assertEqual((event["source_start"], event["source_end"]), (9, 10))
        self.assertEqual([e["output_start"] for e in out["events"]], [1, 12])
        self.assertEqual(ep.validate_output_semantics(out), [])
        out["events"][0]["approved_visible_copy"] = ["真实结果"]
        self.assertTrue(ep.validate_output_semantics(out))

    def test_source_only_copy_policy_rejects_unknown_forged_or_nonrender(self):
        for fields in ({"editorial_copy_policy": "guess"},
                       {"editorial_copy_policy": None},
                       {"editorial_copy_policy": "source_only", "decision": "quiet_source"},
                       {"source_approved_visible_copy": ["forged"]}):
            brief = self.linked_brief()
            brief["events"][0].update(decision="render", approved_visible_copy=["真实结果"])
            brief["events"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ep.project_semantics(brief, self.build())

    def test_omitted_copy_policy_keeps_legacy_visible_copy(self):
        brief = self.linked_brief()
        brief["events"][0].update(decision="render", approved_visible_copy=["真实结果"])
        event = ep.project_semantics(brief, self.build())["events"][0]
        self.assertEqual(event["approved_visible_copy"], ["真实结果"])
        self.assertNotIn("source_approved_visible_copy", event)


if __name__ == "__main__":
    unittest.main()
