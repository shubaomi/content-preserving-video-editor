from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("delivery", ROOT / "scripts" / "plan_social_delivery.py")
DELIVERY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(DELIVERY)


class SocialDeliveryTests(unittest.TestCase):
    def test_equivalent_platform_media_specs_produce_one_universal_output(self):
        presets = json.loads((ROOT / "references" / "platform-presets.json").read_text(encoding="utf-8"))
        result = DELIVERY.plan_delivery(presets, ["douyin", "wechat_channels"])
        self.assertEqual(result["mode"], "single_universal_export")
        self.assertEqual(result["output_count"], 1)
        self.assertEqual(result["outputs"][0]["platforms"], ["douyin", "wechat_channels"])
        self.assertEqual(result["universal_caption_safe_zone"]["x1"], 0.78)


if __name__ == "__main__":
    unittest.main()
