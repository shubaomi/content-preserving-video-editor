"""Isolated variant creation never adopts, edits or replaces an existing project."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from motion_editorial_review import record_hook_decision
import motion_editorial_variant as mv


class VariantTests(unittest.TestCase):
    def request(self, root):
        source = root/'source.mp4'; source.write_bytes(b'synthetic-no-media-render')
        transcript = root/'words.json'
        transcript.write_text(json.dumps({'words': [{'id': 1, 'text': '真实结果', 'start': 1, 'end': 2}]}), encoding='utf-8')
        edl = root/'edl.json'
        edl.write_text(json.dumps({'owner': 'video-use', 'sources': {'cam': str(source)},
                                  'ranges': [{'source': 'cam', 'start': 0, 'end': 6}]}), encoding='utf-8')
        frame = root/'frame.png'; frame.write_bytes(b'synthetic frame reference')
        import hashlib
        plan = root/'hook.json'
        plan.write_text(json.dumps({'state': 'proposed', 'candidates': [{
            'id': 'h1', 'source_ref': 'cam', 'source_range': {'start': 0, 'end': 4},
            'word_ids': [1], 'quote': '真实结果', 'context_before': '产品介绍', 'context_after': '结果解释',
            'promise': '结果', 'payoff_semantic_ids': ['proof'], 'frame_refs': ['frame1']}],
            'frame_evidence': {'frame1': {'path': str(frame), 'sha256': hashlib.sha256(frame.read_bytes()).hexdigest()}}}), encoding='utf-8')
        return record_hook_decision(parent_root=root, source=source, transcript=transcript,
                                    base_edl=edl, hook_plan=plan, candidate_id='h1',
                                    operator='Synthetic Reviewer', user_message='Synthetic fixture: approve exact h1 only', fps='30/1')

    def authority(self, target):
        path = target/'work'/'director'/'motion-editorial'/'variant-authority.json'
        return path, json.loads(path.read_text(encoding='utf-8'))

    def projection_fixture(self, parent):
        request_path = self.request(parent)
        request = json.loads(request_path.read_text())
        target = mv.initialize_variant(request_path)
        # Only this synthetic fixture simulates a video-use-produced candidate EDL.
        # The initializer itself must never create or rewrite any EDL.
        candidate = json.loads((parent/'edl.json').read_text())
        candidate['ranges'][0]['timeline_start'] = 4
        candidate['ranges'].insert(0, {'source': 'cam', 'start': 0, 'end': 4,
                                       'timeline_start': 0, 'role': 'hook'})
        candidate['total_duration_s'] = 10
        edl = target/'edit'/'video-use'/'edl.json'
        edl.parent.mkdir(parents=True)
        edl.write_text(json.dumps(candidate), encoding='utf-8')
        transcript = edl.parent/'transcripts'/'source.json'
        transcript.parent.mkdir()
        transcript.write_bytes((parent/'words.json').read_bytes())
        project = {'motion_editorial': {
            'enabled': True, 'direction': 'authentic_product_editorial',
            'opening': 'approved_duplicate', 'hook_approval_path': request['approval']['path'],
            'design_approval_path': str(Path(__file__).parents[1]/
                'references/motion-editorial-v3-validation/20261012-wp3/approval-receipt.json')}}
        return target, edl, transcript, project

    def test_new_canonical_variant_only_and_resume_readonly(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp); request = self.request(parent)
            originals = {p: p.read_bytes() for p in parent.rglob('*') if p.is_file()}
            target = mv.initialize_variant(request)
            self.assertEqual(target, parent/'work'/'motion-editorial-variants'/request.stem[:20])
            path, authority = self.authority(target)
            dependencies = mv.validate_variant(target, authority)
            self.assertIn(request, dependencies)
            self.assertIn(path, dependencies)
            self.assertFalse((target/'edit'/'video-use'/'edl.json').exists())
            for p, raw in originals.items():
                self.assertEqual(p.read_bytes(), raw)
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in target.rglob('*') if p.is_file()}
            self.assertEqual(mv.initialize_variant(request), target)
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in target.rglob('*') if p.is_file()})

    def test_foreign_existing_directory_is_not_adopted_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp); request = self.request(parent)
            target = Path(json.loads(request.read_text())['target_variant'])
            target.mkdir(parents=True); marker = target/'keep.txt'; marker.write_text('user project')
            with self.assertRaises(ValueError): mv.initialize_variant(request)
            self.assertEqual(marker.read_text(), 'user project')
            self.assertEqual(list(target.iterdir()), [marker])

    def test_request_target_approval_or_hash_tampering_fails_before_target_creation(self):
        for fault in ('target', 'scope', 'approved_bool', 'input', 'request_id'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                parent = Path(temp); request = self.request(parent)
                data = json.loads(request.read_text())
                target = Path(data['target_variant'])
                if fault == 'target': data['target_variant'] = str(parent/'existing-project')
                elif fault == 'scope': data['scope'] = 'full_render'
                elif fault == 'approved_bool': data['approval'] = {'approved': True}
                elif fault == 'input': (parent/'words.json').write_text('{}')
                else: data['request_id'] = '0'*64
                request.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError): mv.initialize_variant(request)
                self.assertFalse(target.exists())

    def test_approval_receipt_must_be_current_canonical_explicit_decision(self):
        for fault in ('operator', 'kind', 'scope', 'hashes', 'message'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                parent = Path(temp); request = self.request(parent)
                data = json.loads(request.read_text()); approval = Path(data['approval']['path'])
                receipt = json.loads(approval.read_text())
                if fault == 'operator': receipt['operator'] = 'codex'
                elif fault == 'kind': receipt['kind'] = 'style_approval'
                elif fault == 'scope': receipt['scope'] = 'full_render'
                elif fault == 'hashes': receipt['input_hashes']['source'] = '0'*64
                else: receipt['original_user_message'] = ''
                # Even updating the outer hash cannot substitute a different canonical ledger decision.
                approval.write_text(json.dumps(receipt), encoding='utf-8')
                import hashlib
                data['approval']['sha256'] = hashlib.sha256(approval.read_bytes()).hexdigest()
                request.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError): mv.initialize_variant(request)

    def test_validation_rejects_relocation_changed_authority_and_input_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp); request = self.request(parent)
            target = mv.initialize_variant(request); _, authority = self.authority(target)
            with self.assertRaises(ValueError): mv.validate_variant(parent, authority)
            changed = copy.deepcopy(authority); changed['parent_root'] = str(target)
            with self.assertRaises(ValueError): mv.validate_variant(target, changed)
            (parent/'frame.png').write_bytes(b'changed')
            with self.assertRaises(ValueError): mv.validate_variant(target, authority)

    def test_resume_preserves_later_owner_edl_and_rejects_partial_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp); request = self.request(parent)
            target = mv.initialize_variant(request)
            edl = target/'edit'/'video-use'/'edl.json'
            edl.parent.mkdir(parents=True)
            edl.write_text('{"owner":"video-use","fixture":"later work"}', encoding='utf-8')
            before = (edl.read_bytes(), edl.stat().st_mtime_ns)
            mv.initialize_variant(request)
            self.assertEqual(before, (edl.read_bytes(), edl.stat().st_mtime_ns))
            authority_path, _ = self.authority(target)
            authority_path.unlink()  # Simulate an interrupted synthetic initialization.
            with self.assertRaises(ValueError): mv.initialize_variant(request)
            self.assertFalse(authority_path.exists())
            self.assertEqual(before, (edl.read_bytes(), edl.stat().st_mtime_ns))

    def test_request_copy_outside_canonical_ledger_is_not_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp); request = self.request(parent)
            copied = parent/'request-copy.json'; copied.write_bytes(request.read_bytes())
            with self.assertRaisesRegex(ValueError, 'canonical parent ledger'):
                mv.initialize_variant(copied)
            self.assertFalse(Path(json.loads(request.read_text())['target_variant']).exists())

    def test_prepare_projection_accepts_initialized_variant_and_same_byte_transcript_cache(self):
        from motion_editorial import prepare_projection
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            target, edl, transcript, project = self.projection_fixture(parent)
            parent_bytes = (parent/'edl.json').read_bytes()
            candidate_bytes = edl.read_bytes()
            self.assertNotEqual(transcript, parent/'words.json')
            self.assertEqual(transcript.read_bytes(), (parent/'words.json').read_bytes())
            result, dependencies = prepare_projection(project=project, root=target,
                source=parent/'source.mp4', transcript=transcript, edl=edl, fps='30/1')
            self.assertEqual(result['mode'], 'approved_duplicate')
            self.assertEqual(result['output_duration'], 10)
            self.assertEqual([row['output_start'] for row in result['words']], [1, 5])
            self.assertIn(target/mv.INITIALIZATION_NAME, dependencies)
            self.assertEqual((parent/'edl.json').read_bytes(), parent_bytes)
            self.assertEqual(edl.read_bytes(), candidate_bytes)

    def test_prepare_projection_rejects_wrong_root_and_approval_alias(self):
        from motion_editorial import prepare_projection
        for fault in ('root', 'approval', 'transcript_bytes'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                parent = Path(temp)
                target, edl, transcript, project = self.projection_fixture(parent)
                root = target
                if fault == 'root':
                    root = parent
                elif fault == 'approval':
                    original = Path(project['motion_editorial']['hook_approval_path'])
                    alias = target/'approval-alias.json'; alias.write_bytes(original.read_bytes())
                    project['motion_editorial']['hook_approval_path'] = str(alias)
                else:
                    transcript.write_text('{}', encoding='utf-8')
                with self.assertRaises(ValueError):
                    prepare_projection(project=project, root=root, director_root=target/'work'/'director',
                        source=parent/'source.mp4', transcript=transcript, edl=edl, fps='30/1')
                self.assertFalse((target/'work'/'director'/'motion-editorial'/'timeline-projection.json').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows Junction isolation')
    def test_junction_variant_container_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside_temp:
            parent = Path(temp); request = self.request(parent)
            container = parent/'work'/'motion-editorial-variants'
            outside = Path(outside_temp)
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(container), str(outside)],
                           check=True, capture_output=True)
            with self.assertRaises(ValueError): mv.initialize_variant(request)
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
