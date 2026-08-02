from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_semantic_corpus import build_index, search_index, validate_index  # noqa: E402


class LocalSemanticCorpusTests(unittest.TestCase):
    def test_fixture_backend_indexes_and_retrieves_authorized_asset(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = root / "browser-tabs.mp4"
            asset.write_bytes(b"owned-video")
            index = root / "index.json"
            config = {"enabled": True, "backend": "fixture", "embedding_model": "fixture-v1"}
            report = build_index(config=config, assets=[{
                "path": str(asset), "type": "video", "source": "HongRun recording",
                "purpose": "explain tab organization", "rights_basis": "project-owned",
                "semantic_text": "browser tabs organization workspace", "motion_score": 0.7,
            }], output=index)
            self.assertEqual(report["status"], "complete")
            self.assertEqual(validate_index(report, config), [])
            result = search_index(
                index=report, query="organize browser tabs", event_id="event-1", limit=3,
            )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["results"][0]["event_id"], "event-1")
            self.assertGreater(result["results"][0]["semantic_similarity"], 0)

    def test_missing_rights_is_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            asset = Path(folder) / "unknown.png"
            asset.write_bytes(b"unknown")
            report = build_index(
                config={"enabled": True, "backend": "fixture", "embedding_model": "fixture-v1"},
                assets=[{"path": str(asset), "type": "image", "semantic_text": "diagram"}],
                output=Path(folder) / "index.json",
            )
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["entries"], [])
            self.assertEqual(report["rejected"][0]["reason"], "missing_rights_basis")

    def test_clip_backend_without_command_is_honestly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = build_index(
                config={"enabled": True, "backend": "clip", "embedding_model": "clip-v1",
                        "command": []},
                assets=[], output=Path(folder) / "index.json",
            )
            self.assertEqual(report["status"], "unavailable")
            self.assertFalse((Path(folder) / "index.json").exists())

    def test_precomputed_backend_is_a_real_no_download_production_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); asset = root / "owned.mp4"; asset.write_bytes(b"owned")
            config = {"enabled": True, "backend": "precomputed",
                      "embedding_model": "user-local-embed", "embedding_version": "2026-08"}
            report = build_index(config=config, assets=[{
                "path": str(asset), "type": "video", "source": "HongRun",
                "purpose": "Explain request flow", "rights_basis": "project-owned",
                "semantic_text": "request flow", "embedding": [0.9, 0.1, 0.0],
                "motion_score": 0.4,
            }], output=root / "index.json")

            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["entries"][0]["embedding"], [0.9, 0.1, 0.0])
            self.assertEqual(validate_index(report, config), [])


if __name__ == "__main__":
    unittest.main()
