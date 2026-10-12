from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from project_config import migrate_project_config
from audit_hook_pacing import audit


class MotionEditorialConfigTests(unittest.TestCase):
    def config(self):
        return {'schema_version': 15, 'identity': {'mode': 'self'},
                'source': {'content_type': 'talking_head'},
                'motion_quality': {'enabled': True},
                'motion_editorial': {'enabled': True, 'version': 1,
                    'direction': 'authentic_product_editorial',
                    'design_approval_path': 'approval.json'}}

    def test_legacy_disabled_in_memory(self):
        for version in range(1, 15):
            raw = {'schema_version': version}
            before = copy.deepcopy(raw)
            migrated = migrate_project_config(raw)
            self.assertEqual(raw, before)
            self.assertEqual(migrated['schema_version'], 15)
            self.assertFalse(migrated['motion_editorial']['enabled'])

    def test_preserve_order_does_not_require_hook_approval(self):
        result = migrate_project_config(self.config())
        self.assertEqual(result['motion_editorial']['opening'], 'propose_only')
        self.assertIsNone(result['motion_editorial']['hook_approval_path'])

    def test_legacy_schema_cannot_silently_enable_new_route(self):
        config = self.config()
        config['schema_version'] = 14
        with self.assertRaisesRegex(ValueError, 'explicit project schema 15'):
            migrate_project_config(config)

    def test_invalid_and_conflicting_configuration_rejected(self):
        mutations = [({'enabled': 1}, None), ({'version': True}, None),
                     ({'direction': 'glow'}, None), ({'extra': True}, None),
                     ({'opening': 'approved_duplicate'}, None),
                     ({'design_approval_path': None}, None),
                     ({}, 'third_party')]
        for changed, identity in mutations:
            config = self.config()
            config['motion_editorial'].update(changed)
            if identity:
                config['identity']['mode'] = identity
            with self.subTest(changed=changed, identity=identity), self.assertRaises(ValueError):
                migrate_project_config(config)

    def test_hook_words_are_primary_and_visual_unknown(self):
        report = audit({'words': [{'id': 'w1', 'type': 'word', 'text': '介绍',
                                    'start': 2, 'end': 3}],
                        'segments': [{'text': 'stale', 'start': 0, 'end': 100}]})
        self.assertEqual(report['measurements']['first_speech'], 2)
        self.assertEqual(report['measurements']['duration'], 3)
        self.assertIsNone(report['heuristic_judgments']['visible_evidence_score_0_5'])

    def test_invalid_word_times_rejected(self):
        for start in (True, float('nan'), -1):
            with self.subTest(start=start), self.assertRaises(ValueError):
                audit({'words': [{'type': 'word', 'text': 'x', 'start': start, 'end': 2}]})


if __name__ == '__main__':
    unittest.main()
