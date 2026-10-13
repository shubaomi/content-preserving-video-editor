import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from evidence_acquisition import acquire, representative_timestamps


class EvidenceFrameCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'source.mp4'
        self.media.write_bytes(b'fixture')
        self.transcript = self.root / 'transcript.json'
        self.transcript.write_text('{"words": []}', encoding='utf-8')
        self.probe = dict(format=dict(duration='10'), streams=[dict(codec_type='video', width=30, height=50)])
        self.extract_count = 0

    def extract(self, media, timestamps, output_dir):
        self.extract_count += 1
        frame_dir = output_dir / 'frames'
        frame_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for index, timestamp in enumerate(timestamps):
            path = frame_dir / f'frame-{index:02d}-{timestamp:08.3f}.png'
            Image.new('RGB', (30, 50), (index * 50, 0, 0)).save(path)
            paths.append(path)
        return paths

    def run_acquire(self, reuse=True):
        with patch('evidence_acquisition.probe_media', return_value=self.probe), patch('evidence_acquisition.extract_frames', side_effect=self.extract):
            result = acquire(media=self.media, transcript_path=self.transcript, output_dir=self.root / 'cache', reuse_existing=reuse)
        return json.loads(result.read_text(encoding='utf-8'))

    def test_reuses_frames_but_rebuilds_current_transcript(self):
        self.run_acquire()
        self.transcript.write_text('{"words": [{"text":"new","start":0,"end":1}]}', encoding='utf-8')
        result = self.run_acquire()
        self.assertEqual(self.extract_count, 1)
        self.assertTrue(result['frame_cache']['source_frames_reused'])
        self.assertEqual(result['transcript']['word_count'], 1)
        self.assertEqual(result['protected_regions']['hands'], [])

    def test_source_and_frame_drift_invalidate(self):
        result = self.run_acquire()
        Path(result['representative_frames'][0]['path']).write_bytes(b'changed')
        self.assertFalse(self.run_acquire()['frame_cache']['source_frames_reused'])
        self.media.write_bytes(b'new source')
        self.assertFalse(self.run_acquire()['frame_cache']['source_frames_reused'])
        self.assertEqual(self.extract_count, 3)

    def test_default_off_reextracts(self):
        self.run_acquire(False)
        self.run_acquire(False)
        self.assertEqual(self.extract_count, 2)

    def test_display_and_policy_drift_invalidate(self):
        self.run_acquire()
        self.probe['streams'][0]['width'] = 40
        self.assertFalse(self.run_acquire()['frame_cache']['source_frames_reused'])

    def test_relative_or_external_cache_path_is_not_reused(self):
        result = self.run_acquire()
        result['representative_frames'][0]['path'] = 'frames/frame-00-0000.500.png'
        manifest = self.root / 'cache/evidence-bundle.json'
        manifest.write_text(json.dumps(result), encoding='utf-8')
        self.assertFalse(self.run_acquire()['frame_cache']['source_frames_reused'])
        self.probe['format']['duration'] = '40'
        self.assertFalse(self.run_acquire()['frame_cache']['source_frames_reused'])


if __name__ == '__main__':
    unittest.main()
