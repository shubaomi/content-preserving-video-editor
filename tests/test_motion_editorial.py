from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import motion_editorial as me


class MotionEditorialTests(unittest.TestCase):
    def test_disabled_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(me.prepare_projection(project={'motion_editorial': {'enabled': False}},
                                                  root=root, source=root/'absent.mp4',
                                                  transcript=root/'absent.json', edl=root/'edl.json',
                                                  fps='30000/1001'), (None, []))
            self.assertEqual(list(root.iterdir()), [])

    def test_style_boolean_is_not_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'approval.json'
            p.write_text('{"approved":true}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'approved design'):
                me.validate_design_approval(p, 'authentic_product_editorial')

    def test_opening_purpose_cannot_use_preserve_order(self):
        with self.assertRaisesRegex(ValueError, 'approved_duplicate'):
            me.validate_sample_purpose('opening_edit', 0, 'preserve_order')
        with self.assertRaises(ValueError):
            me.validate_sample_purpose('opening_edit', 2, 'approved_duplicate')
        me.validate_sample_purpose('motion_style', 30, 'preserve_order')

    def test_configuration_change_dependency(self):
        old = {'motion_editorial': {'enabled': True}, 'editing': {}, 'source': {}}
        new = copy.deepcopy(old)
        new['editing']['caption_treatment'] = {'base_color': '#ffffff'}
        self.assertEqual(me.config_invalidation_stage(old, new), 'sample_qa')
        new = copy.deepcopy(old)
        new['motion_editorial']['opening'] = 'approved_duplicate'
        self.assertEqual(me.config_invalidation_stage(old, new), 'video_use_timeline')
        new = copy.deepcopy(old)
        new['source']['primary_video'] = 'other'
        self.assertEqual(me.config_invalidation_stage(old, new), 'inspect')


if __name__ == '__main__':
    unittest.main()
