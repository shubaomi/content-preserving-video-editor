from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rights_authorization_manifest import create_rights_authorization_report  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RightsAuthorizationManifestTests(unittest.TestCase):
    def test_authorized_assets_are_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "music.wav"
            asset.write_bytes(b"licensed music")
            manifest = root / "rights.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "assets": [{
                    "id": "bgm", "type": "music", "path": asset.name,
                    "sha256": digest(asset), "status": "authorized",
                    "rights_basis": "licensed", "authorized_by": "producer",
                    "authorized_at": "2026-07-20T00:00:00Z",
                    "usage_scope": "video and cover release",
                }],
            }), encoding="utf-8")
            report = create_rights_authorization_report(manifest, root / "report.json")
            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["fail_closed"])

    def test_missing_or_pending_authorization_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "photo.png"
            asset.write_bytes(b"photo")
            manifest = root / "rights.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "assets": [{"id": "photo", "type": "photo", "path": asset.name,
                            "sha256": digest(asset), "status": "pending"}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "authorized"):
                create_rights_authorization_report(manifest, root / "report.json")


if __name__ == "__main__":
    unittest.main()
