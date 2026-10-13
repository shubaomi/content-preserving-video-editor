import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from director import Director, _load_protected_region_review
from director_contracts import DirectorContractError, read_json, sha256_file, write_json, validate_semantic_evidence_binding
import test_protected_region_evidence_v2 as fixtures
from motion_contracts import canonical_contract_evidence_refs


class ProtectedDirectorTests(unittest.TestCase):
    def setUp(self):
        fixtures.ProtectedEvidenceTests.setUp(self)
        self.review_path = self.root / 'review.json'
        project = self.root / 'project.yaml'
        project.write_text(yaml.safe_dump(dict(version=1, video_id='fixture', paths={'root': str(self.root)},
            source=dict(primary_video=str(self.source), input_mode='source_first', content_type='talking_head'),
            motion_quality={'enabled': True}, analysis={'protected_region_review': {'enabled': True, 'manifest': str(self.review_path)}})), encoding='utf-8')
        self.director = Director(project)
        self.transcript = self.director.video_use_dir / 'transcripts/source.json'
        write_json(self.transcript, {'words': []})
        write_json(self.director.video_use_dir / 'edl.json', {'ranges': [{'source':'source', 'start':1, 'end':3}]})

    def acquire(self, **kwargs):
        self.assertTrue(kwargs['reuse_existing'])
        path = kwargs['output_dir'] / 'evidence-bundle.json'
        write_json(path, dict(schema_version=1, status='pass', source={'sha256':sha256_file(self.source)},
            transcript={'sha256':sha256_file(self.transcript)}, display={**self.display, 'orientation':'portrait'},
            representative_frames=[], protected_regions={'faces':[], 'hands':[]}))
        return path

    def run_stage(self):
        write_json(self.review_path, self.manifest)
        self.director._start('evidence_acquisition')
        with patch('director.acquire_evidence', side_effect=self.acquire), patch.object(self.director, '_run_capability', return_value={'status':'disabled'}):
            self.director.stage_evidence_acquisition()

    def test_real_schema2_entry_completes_with_verified_present(self):
        self.run_stage()
        self.assertEqual(self.director.state['stages']['evidence_acquisition']['status'], 'complete')
        bundle = read_json(self.director.evidence_bundle_path)
        self.assertEqual(bundle['protected_regions']['provenance']['method'], 'manual_visual_review')
        self.assertEqual(read_json(self.director.adaptive_layout_path)['status'], 'resolved')

    def test_missing_required_hand_type_rejected(self):
        self.manifest['required_region_types'] = ['faces']
        with self.assertRaisesRegex(DirectorContractError, 'omits required'):
            self.run_stage()

    def test_review_frames_are_declared_without_changing_representative_sampling(self):
        self.run_stage()
        bundle = read_json(self.director.evidence_bundle_path)
        self.assertEqual(bundle['representative_frames'], [])
        frames = bundle['supplemental_frames']
        self.assertEqual(len(frames), 3)
        self.assertTrue(all(row['coverage']['status'] == 'unknown' for row in frames))
        brief = dict(schema_version=2, transcript_sha256=sha256_file(self.transcript),
                     evidence_bundle_sha256=sha256_file(self.director.evidence_bundle_path),
                     evidence_frames=[row['path'] for row in frames], events=[])
        self.assertEqual(validate_semantic_evidence_binding(brief,
            transcript_path=self.transcript, evidence_bundle_path=self.director.evidence_bundle_path), [])
        self.assertEqual(canonical_contract_evidence_refs({'id': 'test',
            'target_frame_evidence': [frames[0]['path']]},
            evidence_bundle_path=self.director.evidence_bundle_path),
            ['frame-sha256:' + frames[0]['sha256']])
        Path(frames[0]['path']).write_bytes(b'drift')
        self.assertTrue(any('hash-drifted' in error for error in validate_semantic_evidence_binding(brief,
            transcript_path=self.transcript, evidence_bundle_path=self.director.evidence_bundle_path)))

    def test_unknown_stops_director_despite_valid_face_list(self):
        row = self.manifest['observations']['hands'][0]
        row['status'] = 'unknown'
        del row['bbox']
        with self.assertRaises(DirectorContractError):
            self.run_stage()
        self.assertEqual(self.director.state['stages']['evidence_acquisition']['status'], 'action_required')
        self.assertEqual(read_json(self.director.adaptive_layout_path)['status'], 'action_required')

    def test_supplemental_frame_cannot_relabel_representative_timestamp(self):
        self.run_stage()
        bundle = read_json(self.director.evidence_bundle_path)
        original = dict(bundle['supplemental_frames'][0])
        original['timestamp_seconds'] += 20
        bundle['representative_frames'] = [original]
        write_json(self.director.evidence_bundle_path, bundle)
        brief = dict(schema_version=2, transcript_sha256=sha256_file(self.transcript),
                     evidence_bundle_sha256=sha256_file(self.director.evidence_bundle_path), events=[])
        errors = validate_semantic_evidence_binding(brief, transcript_path=self.transcript,
            evidence_bundle_path=self.director.evidence_bundle_path)
        self.assertTrue(any('conflicting hash or timestamp' in error for error in errors))
        with self.assertRaisesRegex(ValueError, 'conflicting evidence frame'):
            canonical_contract_evidence_refs({'id': 'test', 'target_frame_evidence': [original['path']]},
                evidence_bundle_path=self.director.evidence_bundle_path)

    def test_legacy_absence_contract_unchanged(self):
        self.manifest = dict(schema_version=1, source_sha256=sha256_file(self.source), reviewer='fixture',
            reviewed_at='2026-10-12', observations={kind:{'status':'observed_absent', 'evidence':self.manifest['observations'][kind][0]['evidence'][:2]}
                for kind in ('faces', 'hands')})
        self.run_stage()
        self.assertEqual(self.director.state['stages']['evidence_acquisition']['status'], 'complete')
        self.manifest['observations']['hands']['status'] = 'present'
        write_json(self.review_path, self.manifest)
        with self.assertRaisesRegex(DirectorContractError, 'observed_absent'):
            _load_protected_region_review(self.review_path, project_root=self.root, source_sha256=sha256_file(self.source))


if __name__ == '__main__':
    unittest.main()
