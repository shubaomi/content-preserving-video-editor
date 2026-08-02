from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepublish_privacy_audit import REQUIRED_PRIVACY_CHECKS, create_privacy_audit  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrepublishPrivacyAuditTests(unittest.TestCase):
    def _manifest(self, root: Path) -> Path:
        files = {}
        for name in ("source_video", "final_video", "cover", "publishing_copy"):
            path = root / f"{name}.bin"
            path.write_bytes(name.encode())
            files[name] = {"path": path.name, "sha256": digest(path)}
        manifest = root / "privacy-review.json"
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "artifacts": files,
            "checks": [{
                "id": check, "status": "pass", "reviewer": "human",
                "reviewed_at": "2026-07-20T00:00:00Z", "evidence": ["manual frame review"],
            } for check in REQUIRED_PRIVACY_CHECKS],
        }), encoding="utf-8")
        return manifest

    def test_complete_hash_bound_review_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = create_privacy_audit(self._manifest(root), root / "privacy-audit.json")
            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["fail_closed"])

    def test_missing_check_unresolved_finding_or_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._manifest(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["checks"].pop()
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing privacy checks"):
                create_privacy_audit(manifest, root / "out.json")

            manifest = self._manifest(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["checks"][0]["findings"] = [{"description": "email visible", "resolved": False}]
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unresolved"):
                create_privacy_audit(manifest, root / "out.json")

            manifest = self._manifest(root)
            (root / "final_video.bin").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash"):
                create_privacy_audit(manifest, root / "out.json")


if __name__ == "__main__":
    unittest.main()
