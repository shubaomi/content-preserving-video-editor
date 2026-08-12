from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from delivery_readiness import asset_is_required  # noqa: E402


class DeliveryReadinessTests(unittest.TestCase):
    def test_optional_cover_is_not_required_without_a_publish_package(self) -> None:
        project = {"delivery": {"required_assets": {"cover": {
            "stage": "cover", "applicability": "optional",
            "required_readiness": "asset_ready",
        }}}}
        self.assertFalse(asset_is_required(project, "cover"))

    def test_enabled_release_pack_makes_cover_required(self) -> None:
        project = {"delivery": {
            "required_assets": {"cover": {
                "stage": "cover", "applicability": "optional",
                "required_readiness": "asset_ready",
            }},
            "release_pack": {"enabled": True},
        }}
        self.assertTrue(asset_is_required(project, "cover"))

    def test_explicit_required_audio_remains_required(self) -> None:
        project = {"delivery": {"required_assets": {"audio": {
            "stage": "audio", "applicability": "required",
            "required_readiness": "asset_ready",
        }}}}
        self.assertTrue(asset_is_required(project, "audio"))


if __name__ == "__main__":
    unittest.main()
