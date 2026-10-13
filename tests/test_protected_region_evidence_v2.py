import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from director_contracts import sha256_file
from protected_region_evidence import load_protected_region_evidence


class ProtectedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'source fixture')
        evidence = []
        for index, timestamp in enumerate((1.0, 2.0, 3.0)):
            path = self.root / f'frame{index}.png'
            Image.new('RGB', (30, 50), (index * 50, 0, 0)).save(path)
            evidence.append(dict(path=str(path), sha256=sha256_file(path), timestamp_seconds=timestamp))
        self.display = dict(width=720, height=1280, rotation_degrees=0)
        self.manifest = dict(schema_version=2, kind='protected_region_evidence',
            source=dict(path=str(self.source), sha256=sha256_file(self.source)),
            display=self.display, coordinate_space='normalized_display_v1',
            provenance=dict(method='manual_visual_review', reviewer='test reviewer', reviewed_at='2026-10-12'),
            required_region_types=['faces', 'hands'], observations={})
        for region_type in ('faces', 'hands'):
            self.manifest['observations'][region_type] = [dict(region_id=region_type + '-1', status='present',
                source_start=1.0, source_end=3.0, bbox=dict(x=.1, y=.2, width=.3, height=.4),
                geometry_method='bounded_review_envelope', evidence=copy.deepcopy(evidence))]

    def load(self, window=(1.0, 3.0)):
        path = self.root / 'review.json'
        path.write_text(json.dumps(self.manifest), encoding='utf-8')
        return load_protected_region_evidence(path, project_root=self.root, source_path=self.source,
            display=self.display, required_window=window)[0]

    def test_manual_provenance_and_regions_preserved(self):
        result = self.load()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['provenance']['method'], 'manual_visual_review')
        self.assertEqual(result['hands'][0]['source_end'], 3.0)
        self.assertNotIn('mediapipe', json.dumps(result))

    def test_one_frame_cannot_claim_conflicting_timestamps(self):
        self.manifest['observations']['hands'][0]['evidence'][1]['timestamp_seconds'] = 2.1
        with self.assertRaisesRegex(ValueError, 'conflicting timestamps'):
            self.load()

    def test_unknown_lost_and_missing_never_unlock(self):
        for status in ('unknown', 'lost'):
            with self.subTest(status=status):
                row = self.manifest['observations']['hands'][0]
                row['status'] = status
                row.pop('bbox', None)
                self.assertEqual(self.load()['status'], 'action_required')
        self.manifest['observations']['hands'] = []
        self.assertEqual(self.load()['status'], 'action_required')

    def test_gap_and_no_window_are_action_required(self):
        self.assertEqual(self.load((.5, 3))['status'], 'action_required')
        self.assertEqual(self.load(None)['status'], 'action_required')

    def test_absent_is_explicit_and_hash_bound(self):
        row = self.manifest['observations']['hands'][0]
        row['status'] = 'absent'
        del row['bbox']
        result = self.load()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['observations']['hands']['status'], 'observed_absent')

    def test_rejects_source_or_frame_drift(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.load()
        self.manifest['source']['sha256'] = sha256_file(self.source)
        (self.root / 'frame0.png').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.load()

    def test_rejects_bad_box_duplicate_and_display(self):
        original = copy.deepcopy(self.manifest)
        for value in (float('nan'), -1, 1.1):
            self.manifest = copy.deepcopy(original)
            self.manifest['observations']['faces'][0]['bbox']['x'] = value
            with self.assertRaises(ValueError): self.load()
        self.manifest = copy.deepcopy(original)
        self.manifest['observations']['hands'].append(copy.deepcopy(self.manifest['observations']['hands'][0]))
        with self.assertRaises(ValueError): self.load()
        self.manifest = copy.deepcopy(original)
        self.manifest['display'] = dict(width=720, height=1280, rotation_degrees=90)
        with self.assertRaises(ValueError): self.load()

    def test_rejects_sparse_or_external_frames(self):
        row = self.manifest['observations']['hands'][0]
        original = copy.deepcopy(row['evidence'])
        row['evidence'] = row['evidence'][:1]
        with self.assertRaises(ValueError): self.load()
        row['evidence'] = original
        with tempfile.TemporaryDirectory() as folder:
            external = Path(folder) / 'frame.png'
            Image.new('RGB', (10, 10)).save(external)
            row['evidence'][0].update(path=str(external), sha256=sha256_file(external))
            with self.assertRaises(ValueError): self.load()

    def test_detector_is_not_renamed_to_manual_or_mediapipe(self):
        self.manifest['provenance'] = dict(method='detector_observation', detector='actual-test-detector', reviewed_at='2026-10-12')
        self.assertEqual(self.load()['provenance']['detector'], 'actual-test-detector')
        del self.manifest['provenance']['detector']
        with self.assertRaises(ValueError): self.load()

    def test_unknown_cannot_carry_bbox_or_hide_between_valid_spans(self):
        row = self.manifest['observations']['hands'][0]
        row['status'] = 'lost'
        with self.assertRaises(ValueError): self.load()
        del row['bbox']
        self.assertEqual(self.load()['observations']['hands']['status'], 'unknown')

    def test_each_hand_identity_needs_full_coverage(self):
        row = copy.deepcopy(self.manifest['observations']['hands'][0])
        row['region_id'] = 'hands-2'
        row['source_start'] = 1.5
        self.manifest['observations']['hands'].append(row)
        self.assertEqual(self.load()['status'], 'action_required')


if __name__ == '__main__':
    unittest.main()
