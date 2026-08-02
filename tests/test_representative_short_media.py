from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from representative_short_media import validate  # noqa: E402


class RepresentativeShortMediaTests(unittest.TestCase):
    def test_retained_landscape_and_portrait_media_are_current_and_decodable(self) -> None:
        manifest = ROOT / "references" / "validation" / "representative-short-media" / "manifest.json"
        self.assertEqual(validate(manifest), [])

    def test_tampered_media_fails_hash_gate(self) -> None:
        source = ROOT / "references" / "validation" / "representative-short-media"
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "evidence"
            shutil.copytree(source, target)
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            media = target / manifest["scenarios"][0]["media"]
            media.write_bytes(media.read_bytes() + b"tamper")
            self.assertTrue(any("hash" in error for error in validate(target / "manifest.json")))


if __name__ == "__main__":
    unittest.main()
