"""Synthetic current-file and authorization boundaries; never renders media."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import motion_editorial as me
from motion_editorial_review import record_hook_decision
from director_contracts import write_json
from editorial_projection import build_projection, project_semantics
from editorial_schema import runtime_schema
from provider_governance import (build_decision_report, create_cost_ledger,
    reserve_selected_call, validate_cost_ledger)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'synthetic; not decoded')
        self.frame = self.root / 'frame.png'
        self.frame.write_bytes(b'synthetic frame; not visual evidence')
        self.edl = {'sources': {'cam': str(self.source)}, 'ranges': [
            {'source': 'cam', 'segment_id': 'body', 'start': 0, 'end': 8}]}
        self.words = {'words': [{'id': 1, 'text': '结果', 'start': 1, 'end': 2}]}
        self.paths = {key: self.root / (key + '.json') for key in ('transcript', 'base_edl', 'hook_plan')}
        write_json(self.paths['transcript'], self.words)
        write_json(self.paths['base_edl'], self.edl)
        self.hook = {'state': 'proposed', 'frame_evidence': {'f1': me.ref(self.frame)},
            'candidates': [{'id': 'h1', 'source_ref': 'cam', 'source_range': {'start': 0, 'end': 3},
                'word_ids': [1], 'quote': '结果', 'context_before': '此前介绍', 'context_after': '此后说明',
                'promise': '真实结果', 'payoff_semantic_ids': ['e1'], 'frame_refs': ['f1']}]}
        write_json(self.paths['hook_plan'], self.hook)

    def record(self, **overrides):
        args = dict(parent_root=self.root, source=self.source, **self.paths, candidate_id='h1',
                    operator='synthetic-human-fixture', user_message='Fixture exact approval, not user authority', fps='30/1')
        args.update(overrides)
        return record_hook_decision(**args)

    def test_hook_command_is_idempotent_and_never_writes_edl(self):
        original = self.paths['base_edl'].read_bytes()
        request = self.record()
        first = request.read_bytes()
        self.assertEqual(self.record(), request)
        self.assertEqual(first, request.read_bytes())
        self.assertEqual(original, self.paths['base_edl'].read_bytes())
        data = me.load(request)
        self.assertFalse(Path(data['target_variant']).exists())
        self.assertFalse(data['full_render_authorized'])

    def test_hook_requires_named_human_current_source_and_frame(self):
        with self.assertRaisesRegex(ValueError, 'human'):
            self.record(operator='agent')
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            self.record(user_message='')
        self.edl['sources']['cam'] = str(self.root/'other.mp4')
        write_json(self.paths['base_edl'], self.edl)
        with self.assertRaisesRegex(ValueError, 'source file differs'):
            self.record()
        self.edl['sources']['cam'] = str(self.source)
        write_json(self.paths['base_edl'], self.edl)
        self.frame.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.record()

    def shot(self):
        p = build_projection(baseline_edl=self.edl, candidate_edl=self.edl, transcript=self.words,
            fps='30/1', input_hashes={key: str(i)*64 for i,key in enumerate(
                ('source','transcript','base_edl','candidate_edl'),1)})
        brief = project_semantics({'schema_version':3, 'events':[{'id':'e1', 'decision':'render',
            'source_start':0, 'source_end':4, 'output_start':0, 'output_end':4,
            'transcript_word_ids':[1], 'approved_visible_copy':['定位'],
            'target_frame_evidence':[str(self.frame)]}]}, p)
        event = {'instance_id':'e1@body','decision':'overlay','recipe_id':'B01',
            'viewer_task':'Find real control','information_gain':'Position','primary_focus':'control',
            'rationale':'real UI only','source_crop':None,'approved_visible_copy':['定位'],
            'output_start':0,'output_end':4,'overlay_box':{'x':10,'y':10,'width':100,'height':60},
            'phases':{name:{'start':i,'end':i+1} for i,name in enumerate(('entrance','explain','hold','exit'))},
            'evidence':{'frame_refs':[me.ref(self.frame)]},
            'sound':{'decision':'intentionally_silent','reason':'speech first'}}
        plan = {'schema_version':2,'kind':'shot_motion_plan','direction':'professional_software_demo',
                'projection_sha256':me.digest(p),'semantic_sha256':me.digest(brief),
                'events':[event],'default_decorations':False}
        return plan, dict(projection=p, output_brief=brief, direction=plan['direction'], roots=[self.root])

    def test_compiler_materializes_active_end_and_requires_semantic_frame(self):
        plan, args = self.shot()
        result = me.compile_shot_plan(plan, **args)
        self.assertEqual(result['events'][0]['active_end'], 4)
        other = self.root/'unrelated.png'
        other.write_bytes(b'other')
        plan['events'][0]['evidence']['frame_refs'] = [me.ref(other)]
        with self.assertRaisesRegex(ValueError, 'semantic instance frames'):
            me.compile_shot_plan(plan, **args)

    def test_steps_current_hash_and_exit_boundary_are_enforced(self):
        plan, args = self.shot()
        event = plan['events'][0]
        event['steps'] = [{'frame_ref':{'path':str(self.frame),'sha256':'0'*64}}]
        with self.assertRaisesRegex(ValueError, 'stale'):
            me.compile_shot_plan(plan, **args)
        event.pop('steps')
        event['active_end'] = 3
        with self.assertRaisesRegex(ValueError, 'exit'):
            me.compile_shot_plan(plan, **args)

    def test_governance_rebind_preserves_reservations_and_totals(self):
        config = {'providers':{'sfx':[{'name':'fixture-local','available':True,
            'incremental_cost':0,'cost_basis':'local fixture','actual_cost_strategy':'fixed'}]}}
        old, new = 'a'*64, 'b'*64
        decision = build_decision_report(config=config, project_hash=old)
        ledger = create_cost_ledger(config=config, project_hash=old)
        reservation = reserve_selected_call(ledger, decision, task='sfx')
        write_json(self.root/'provider-decision.json', decision)
        write_json(self.root/'cost-ledger.json', ledger)
        artifacts = me.refresh_unchanged_governance(self.root, config, old, new)
        updated = me.load(self.root/'cost-ledger.json')
        self.assertEqual(updated['totals'], ledger['totals'])
        self.assertEqual(updated['reservations'][0]['id'], reservation['id'])
        self.assertEqual(validate_cost_ledger(updated,new), [])
        self.assertEqual(me.load(artifacts[2])['ledger'], ledger)
        with self.assertRaises(ValueError):
            me.refresh_unchanged_governance(self.root, {}, new, 'c'*64)

    def test_instance_schema_is_additive_not_legacy_mutation(self):
        frozen = {'$id':'example/1.0.0','properties':{'schema_version':{'const':'1.0.0'}},
                  '$defs':{'id':{'pattern':'^[a-z]+$'}}}
        before = copy.deepcopy(frozen)
        self.assertIs(runtime_schema('target-binding',frozen,{'schema_version':'1.0.0'}),frozen)
        new = runtime_schema('target-binding',frozen,{'schema_version':'1.1.0'})
        self.assertEqual(frozen,before)
        self.assertIn('@',new['$defs']['id']['pattern'])

    def test_sample_claim_cannot_disguise_middle_or_long_media(self):
        projection = {'mode':'approved_duplicate','output_duration':100,
                      'fps':{'numerator':30,'denominator':1}}
        plan = {'purpose':'opening_edit','output_start':0}
        storyboard = {'composition':{'timeline_basis':'edl_output','source_start':20,'source_end':70}}
        with self.assertRaisesRegex(ValueError,'actual composition'):
            me.validate_sample_window(plan,projection,storyboard,50)
        storyboard['composition'].update(source_start=0,source_end=50)
        me.validate_sample_window(plan,projection,storyboard,50)
        with self.assertRaisesRegex(ValueError,'measured sample'):
            me.validate_sample_window(plan,projection,storyboard,65)
        plan['purpose'] = 'motion_style'
        with self.assertRaisesRegex(ValueError,'duration bounds'):
            me.validate_sample_window(plan,projection,storyboard,50)


if __name__ == '__main__':
    unittest.main()
