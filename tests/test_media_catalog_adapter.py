from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_adapters import AdapterRunner  # noqa: E402
from media_catalog_adapter import run_media_catalog  # noqa: E402


class MediaCatalogAdapterTests(unittest.TestCase):
    def test_disabled_catalog_is_a_noop(self) -> None:
        report = run_media_catalog(project={}, semantic_brief={"events": []}, root=ROOT,
                                   runner=AdapterRunner(ROOT / "unused.json"), execute=True)
        self.assertEqual(report["status"], "disabled")

    def test_enabled_catalog_runs_only_for_evidence_backed_asset_requests(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = root / "asset.png"
            asset.write_bytes(b"licensed")
            tool = root / "tool.py"
            tool.write_text(
                "import json, pathlib, sys\n"
                "manifest=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
                "request=manifest['requests'][0]\n"
                "asset=pathlib.Path(r'" + str(asset).replace("\\", "\\\\") + "')\n"
                "payload={'request_set_sha256': manifest['request_set_sha256'], 'decisions': [{\n"
                "  'event_id': request['event_id'], 'request_sha256': request['request_sha256'],\n"
                "  'query': request['query'], 'purpose': request['purpose'], 'status': 'selected',\n"
                "  'asset': {'path': str(asset), 'sha256': '" + hashlib.sha256(b"licensed").hexdigest() + "',\n"
                "    'type': 'image', 'purpose': request['purpose'], 'provenance': 'local catalog',\n"
                "    'rights_basis': 'project-owned test asset'}}]}\n"
                "pathlib.Path(r'" + str(root / "catalog.json").replace("\\", "\\\\") + "').write_text(json.dumps(payload), encoding='utf-8')\n",
                encoding="utf-8",
            )
            project = {"assets": {"media_catalog": {
                "enabled": True, "command": [sys.executable, str(tool), "{request_manifest}"],
                "outputs": ["catalog.json"],
            }}}
            brief = {"events": [{"id": "e1", "asset_request": {
                "query": "browser tab relationship icon", "purpose": "semantic comparison"
            }}]}
            report = run_media_catalog(
                project=project, semantic_brief=brief, root=root,
                runner=AdapterRunner(root / "adapter-state.json"), execute=True,
            )
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["event_ids"], ["e1"])
            self.assertTrue((root / "catalog.json").is_file())
            manifest = Path(report["request_manifest"])
            self.assertTrue(manifest.is_file())
            self.assertEqual(report["request_manifest_sha256"], hashlib.sha256(
                manifest.read_bytes()
            ).hexdigest())

    def test_empty_catalog_output_cannot_claim_success(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "catalog.json"
            tool = root / "tool.py"
            tool.write_text("import pathlib\npathlib.Path(r'%s').write_text('{}')\n" % output,
                            encoding="utf-8")
            report = run_media_catalog(
                project={"assets": {"media_catalog": {"enabled": True,
                    "command": [sys.executable, str(tool), "{request_manifest}"],
                    "outputs": [str(output)]}}},
                semantic_brief={"events": [{"id": "e1", "asset_request": {
                    "query": "diagram", "purpose": "explain relation"}}]},
                root=root, runner=AdapterRunner(root / "state.json"), execute=True,
            )
            self.assertEqual(report["status"], "unavailable")
            self.assertTrue(report["validation_errors"])

    def test_enabled_catalog_without_semantic_request_is_not_applicable(self) -> None:
        project = {"assets": {"media_catalog": {"enabled": True}}}
        report = run_media_catalog(project=project, semantic_brief={"events": []}, root=ROOT,
                                   runner=AdapterRunner(ROOT / "unused.json"), execute=True)
        self.assertEqual(report["status"], "not_applicable")

    def test_local_semantic_corpus_can_fulfil_immutable_catalog_request(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = root / "tabs.mp4"
            asset.write_bytes(b"owned-tabs")
            project = {"assets": {
                "media_catalog": {"enabled": False},
                "local_semantic_corpus": {
                    "enabled": True, "backend": "fixture", "embedding_model": "fixture-v1",
                    "index": "work/director/semantic-corpus/index.json",
                    "assets": [{
                        "path": str(asset), "type": "video", "source": "HongRun",
                        "purpose": "browser tab organization", "rights_basis": "project-owned",
                        "semantic_text": "browser tabs organization", "motion_score": 0.5,
                    }],
                },
            }}
            report = run_media_catalog(
                project=project,
                semantic_brief={"events": [{"id": "e1", "asset_request": {
                    "query": "browser tabs organization", "purpose": "explain organization",
                }}]},
                root=root, runner=AdapterRunner(root / "state.json"), execute=False,
            )
            self.assertEqual(report["status"], "complete")
            payload = json.loads(Path(report["outputs"][0]).read_text(encoding="utf-8"))
            self.assertEqual(payload["decisions"][0]["asset"]["rights_basis"], "project-owned")

    def test_catalog_command_must_accept_request_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = run_media_catalog(
                project={"assets": {"media_catalog": {"enabled": True,
                    "command": [sys.executable, "tool.py"], "outputs": ["catalog.json"]}}},
                semantic_brief={"events": [{"id": "e1", "asset_request": {
                    "query": "diagram", "purpose": "explain relation"}}]},
                root=root, runner=AdapterRunner(root / "state.json"), execute=True,
            )
            self.assertEqual(report["status"], "unavailable")
            self.assertIn("request_manifest", report["reason"])

    def test_asset_request_cannot_override_canonical_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = run_media_catalog(
                project={"assets": {"media_catalog": {"enabled": True}}},
                semantic_brief={"events": [{"id": "canonical", "asset_request": {
                    "event_id": "spoofed", "query": "diagram",
                    "purpose": "explain relation"}}]},
                root=root, runner=AdapterRunner(root / "state.json"), execute=False,
            )
            self.assertEqual(report["status"], "failed")
            self.assertIn("event_id", report["reason"])

    def test_concurrent_request_sets_use_immutable_distinct_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = {"assets": {"media_catalog": {"enabled": True}}}

            def request(index: int) -> dict:
                return run_media_catalog(
                    project=project,
                    semantic_brief={"events": [{"id": f"e{index}", "asset_request": {
                        "query": f"asset {index}", "purpose": f"purpose {index}",
                    }}]},
                    root=root,
                    runner=AdapterRunner(root / f"state-{index}.json"),
                    execute=False,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                reports = list(pool.map(request, range(24)))
            paths = [Path(report["request_manifest"]) for report in reports]
            self.assertEqual(len(set(paths)), len(paths))
            for index, path in enumerate(paths):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["requests"][0]["event_id"], f"e{index}")
                self.assertEqual(payload["request_set_sha256"], path.stem)

    def test_concurrent_identical_request_set_serializes_manifest_creation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = {"assets": {"media_catalog": {"enabled": True}}}
            brief = {"events": [{"id": "same", "asset_request": {
                "query": "same asset", "purpose": "same purpose",
            }}]}

            def request(index: int) -> dict:
                return run_media_catalog(
                    project=project, semantic_brief=brief, root=root,
                    runner=AdapterRunner(root / f"state-{index}.json"), execute=False,
                )

            with ThreadPoolExecutor(max_workers=12) as pool:
                reports = list(pool.map(request, range(48)))
            self.assertEqual(len({report["request_manifest"] for report in reports}), 1)
            manifest = Path(reports[0]["request_manifest"])
            self.assertTrue(manifest.is_file())
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["requests"][0]["event_id"],
                             "same")


if __name__ == "__main__":
    unittest.main()
