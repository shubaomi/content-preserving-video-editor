"""Output-instance delivery linkage must never guess source-ID duplicates."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import editorial_projection as ep
import editorial_handoff as eh


class HandoffTests(unittest.TestCase):
    def setUp(self):
        edl = {'source': 'cam', 'ranges': [{'start': 0, 'end': 6}]}
        self.projection = ep.build_projection(
            baseline_edl=edl, candidate_edl=copy.deepcopy(edl), fps=30,
            transcript={'words': [{'id': 1, 'text': '真实', 'start': 1, 'end': 2},
                                  {'id': 2, 'text': '产品', 'start': 3, 'end': 4}]},
            input_hashes={k: '1' * 64 for k in ('source', 'transcript', 'base_edl', 'candidate_edl')})
        self.source = {'schema_version': 3, 'events': [
            {'id': 'proof', 'source_start': 1, 'source_end': 4,
             'transcript_word_ids': [1, 2], 'decision': 'render'}]}
        self.brief = ep.project_semantics(self.source, self.projection)
        self.event = self.brief['events'][0]
        self.captions = {'version': 2, 'segments': [
            {'start': 1, 'end': 2, 'text': '真实', 'timeline': 'output'},
            {'start': 3, 'end': 4, 'text': '产品', 'timeline': 'output'}]}

    def build(self, **kw):
        args = dict(projection=self.projection, output_brief=self.brief, captions=self.captions)
        args.update(kw)
        return eh.build_handoff(**args)

    def test_captions_bind_output_occurrences_without_mutation(self):
        before = copy.deepcopy((self.projection, self.brief, self.captions))
        bundle = self.build()
        self.assertEqual(before, (self.projection, self.brief, self.captions))
        self.assertEqual(bundle['captions']['status'], 'linked')
        self.assertEqual(bundle['captions']['rows'][0]['word_occurrence_ids'],
                         [self.projection['words'][0]['occurrence_id']])
        self.assertFalse(bundle['native_editor_verified'])
        self.assertEqual(bundle['audio']['status'], 'not_provided')

    def test_file_current_hash_and_expected_hash_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'captions.json'
            path.write_text(json.dumps(self.captions), encoding='utf-8')
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            bundle = self.build(captions={'path': str(path), 'sha256': sha})
            self.assertEqual(bundle['inputs']['captions']['sha256'], sha)
            self.assertEqual(bundle['inputs']['captions']['hash_scope'], 'current_file_bytes')
            path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash'):
                self.build(captions={'path': str(path), 'sha256': sha})

    def test_json_duplicates_and_overflow_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'captions.json'
            for value in ('{"segments":[],"segments":[]}', '{"segments":[],"x":1e999}'):
                path.write_text(value, encoding='utf-8')
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.build(captions=path)

    def test_caption_crossing_cut_source_time_or_overlap_rejected(self):
        for rows in ([{'start': 5, 'end': 7, 'text': '越界'}],
                     [{'start': 1, 'end': 2, 'text': '源', 'timeline': 'source'}],
                     [{'start': 1, 'end': 3, 'text': '一'}, {'start': 2, 'end': 4, 'text': '二'}],
                     [{'start': True, 'end': 2, 'text': '布尔'}],
                     [{'start': 1, 'end': float('nan'), 'text': '无效'}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.build(captions=rows)

    def test_stale_output_semantics_rejected(self):
        brief = copy.deepcopy(self.brief)
        brief['events'][0]['output_start'] = 0
        with self.assertRaises(ValueError):
            self.build(output_brief=brief)

    def test_audio_exact_instance_linkage_and_window(self):
        cue = {'event_id': 'sfx1', 'semantic_event_id': self.event['id'],
               'decision': 'cue', 'start': 1, 'duration_seconds': .25, 'asset': 'audio.wav'}
        bundle = self.build(audio_plan={'motion_sfx': {'event_decisions': [cue]}})
        row = bundle['audio']['rows'][0]
        self.assertEqual(row['semantic_event_id'], self.event['id'])
        self.assertEqual(row['semantic_output_window'], {'start': 1.0, 'end': 4.0})
        cue['start'] = 5
        with self.assertRaisesRegex(ValueError, 'window'):
            self.build(audio_plan={'motion_sfx': {'event_decisions': [cue]}})

    def test_legacy_optional_ids_are_unavailable_not_guessed(self):
        audio = {'motion_sfx': {'event_decisions': [
            {'event_id': 'sfx1', 'semantic_event_id': 'proof', 'decision': 'intentionally_silent'}]}}
        bundle = self.build(audio_plan=audio, target_bindings=[{'semantic_event_id': 'proof'}],
                            promise_ledger={'single_promise': {'proof_event_ids': ['proof']}})
        for key in ('audio', 'targets', 'promises'):
            self.assertEqual(bundle[key]['status'], 'unavailable')
            self.assertEqual(bundle[key]['rows'], [])

    def test_target_requires_exact_window_and_no_source_fallback(self):
        binding = {'binding_id': 'target1', 'semantic_event_id': self.event['id'],
                   'source_window': {'start_seconds': 1, 'end_seconds': 4},
                   'output_window': {'start_seconds': 1, 'end_seconds': 4},
                   'active_windows': [{'start_seconds': 1, 'end_seconds': 3}]}
        self.assertEqual(self.build(target_bindings=[binding])['targets']['status'], 'linked')
        binding['output_window']['start_seconds'] = 0
        with self.assertRaisesRegex(ValueError, 'window'):
            self.build(target_bindings=[binding])

    def test_promise_uses_instance_occurrences_and_canonical_binding(self):
        ledger = {'single_promise': {'proof_event_ids': [self.event['id']]}}
        a = self.build(promise_ledger=ledger)
        b = self.build(promise_ledger=copy.deepcopy(ledger))
        self.assertEqual(a['bundle_sha256'], b['bundle_sha256'])
        self.assertEqual(a['promises']['rows'][0]['word_occurrence_ids'],
                         self.event['word_occurrence_ids'])
        self.assertEqual(a['inputs']['captions']['hash_scope'], 'canonical_json_integrity_only')

    def test_duplicate_occurrences_do_not_collapse(self):
        baseline = {'source': 'cam', 'ranges': [{'start': 0, 'end': 6}]}
        candidate = {'source': 'cam', 'ranges': [
            {'start': 0, 'end': 4, 'timeline_start': 0, 'role': 'hook'},
            {'start': 0, 'end': 6, 'timeline_start': 4}]}
        hashes = {key: '1' * 64 for key in ('source', 'transcript', 'base_edl', 'candidate_edl', 'hook_plan')}
        plan = {'state': 'proposed', 'candidates': [{
            'id': 'h1', 'source_ref': 'cam', 'source_range': {'start': 0, 'end': 4},
            'word_ids': [1], 'quote': '结果', 'context_before': '产品', 'context_after': '说明',
            'promise': '结果', 'payoff_semantic_ids': ['proof'], 'frame_refs': ['frame1']}]}
        receipt = {'kind': 'hook_excerpt', 'scope': 'short_preview', 'candidate_id': 'h1',
                   'original_user_message': '批准此精确短片', 'operator': 'human',
                   'timestamp': '2026-10-12T00:00:00Z',
                   'input_hashes': {k: v for k, v in hashes.items() if k != 'candidate_edl'}}
        p = ep.build_projection(baseline_edl=baseline, candidate_edl=candidate,
                                transcript={'words': [{'id': 1, 'text': '结果', 'start': 1, 'end': 2}]},
                                fps=30, mode='approved_duplicate', input_hashes=hashes,
                                hook_plan=plan, approval=receipt, authority=lambda *_: True)
        brief = ep.project_semantics({'schema_version': 3, 'events': [
            {'id': 'proof', 'source_start': 1, 'source_end': 2, 'transcript_word_ids': [1]}]}, p)
        rows = [{'start': e['output_start'], 'end': e['output_end'], 'text': '结果'}
                for e in brief['events']]
        ledger = {'single_promise': {'proof_event_ids': [e['id'] for e in brief['events']]}}
        bundle = eh.build_handoff(p, brief, rows, promise_ledger=ledger)
        occurrences = [r['word_occurrence_ids'][0] for r in bundle['captions']['rows']]
        self.assertEqual(len(set(occurrences)), 2)
        self.assertEqual(len(bundle['promises']['rows']), 2)

    def test_unknown_instance_and_forged_audio_event_window_fail(self):
        row = {'event_id': 'sfx', 'semantic_event_id': self.event['id'],
               'decision': 'cue', 'start': 1, 'duration_seconds': .2,
               'output_start': 0, 'output_end': 4}
        with self.assertRaises(ValueError):
            self.build(audio_plan={'motion_sfx': {'event_decisions': [row]}})
        with self.assertRaisesRegex(ValueError, 'unknown output'):
            self.build(promise_ledger={'single_promise': {'proof_event_ids': ['proof@stale']}})

    def test_optional_unsupported_shapes_are_reported(self):
        bundle = self.build(audio_plan=[], target_bindings={'unexpected': []}, promise_ledger={})
        for key in ('audio', 'targets', 'promises'):
            self.assertEqual(bundle[key]['status'], 'unavailable')

    def test_legacy_split_word_has_unavailable_linkage_without_caption_rewrite(self):
        rows = [{'start': 1, 'end': 1.5, 'text': '真'}, {'start': 1.5, 'end': 2, 'text': '实'}]
        bundle = self.build(captions=rows)
        self.assertEqual(bundle['captions']['status'], 'partial')
        self.assertEqual(len(bundle['captions']['unavailable']), 2)
        for before, after in zip(rows, bundle['captions']['rows']):
            self.assertEqual({k: after[k] for k in before}, before)
            self.assertEqual(after['word_occurrence_ids'], [])
            self.assertEqual(after['word_linkage_basis'], 'unavailable')

    def test_video_use_declared_occurrences_preserved_and_validated(self):
        occurrence = self.projection['words'][0]['occurrence_id']
        segment = self.projection['words'][0]['segment_id']
        rows = [{'start': 1, 'end': 1.5, 'text': '真', 'segment_id': segment,
                 'word_occurrence_ids': [occurrence]},
                {'start': 1.5, 'end': 2, 'text': '实', 'segment_id': segment,
                 'word_occurrence_ids': [occurrence]}]
        bundle = self.build(captions=rows)
        self.assertEqual(bundle['captions']['status'], 'linked')
        self.assertEqual(bundle['captions']['rows'][0]['word_occurrence_ids'], [occurrence])
        self.assertEqual(bundle['captions']['rows'][0]['word_linkage_basis'], 'video_use_declared_occurrence_ids')
        rows[0]['word_occurrence_ids'] = ['other-segment:w1']
        with self.assertRaises(ValueError):
            self.build(captions=rows)

    def test_alternative_caption_container_and_required_inputs(self):
        bundle = self.build(captions={'captions': self.captions['segments']})
        self.assertEqual(bundle['captions']['status'], 'linked')
        with self.assertRaises(ValueError):
            self.build(captions=None)


if __name__ == '__main__':
    unittest.main()
