from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from renderer_project_manifest import build_manifest, validate_manifest  # noqa: E402


class RendererProjectManifestTests(unittest.TestCase):
    def test_manifest_binds_complete_project_source_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "hyperframes"
            project.mkdir()
            (project / "index.html").write_text("<main></main>", encoding="utf-8")
            (project / "storyboard.json").write_text("{}", encoding="utf-8")
            (project / "style.css").write_text("main{}", encoding="utf-8")
            output = project / "renderer-project-manifest.json"

            manifest = build_manifest(project, output)

            self.assertEqual(validate_manifest(manifest, output), [])
            self.assertEqual(
                [row["relative_path"] for row in manifest["files"]],
                ["index.html", "storyboard.json", "style.css"],
            )
            (project / "style.css").write_text("main{color:red}", encoding="utf-8")
            self.assertTrue(any("hash is stale" in error for error in validate_manifest(manifest, output)))

    def test_new_source_file_invalidates_manifest_but_runtime_evidence_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "hyperframes"
            project.mkdir()
            (project / "index.html").write_text("<main></main>", encoding="utf-8")
            (project / "storyboard.json").write_text("{}", encoding="utf-8")
            output = project / "renderer-project-manifest.json"
            manifest = build_manifest(project, output)
            (project / "component.js").write_text("export default 1", encoding="utf-8")
            self.assertTrue(any("inventory is stale" in error for error in validate_manifest(manifest, output)))

            manifest = build_manifest(project, output)
            (project / "renderer-export.json").write_text("{}", encoding="utf-8")
            (project / "renderer-evidence-contract.json").write_text(
                "{}", encoding="utf-8",
            )
            receipts = project / "keyframe-receipts"
            receipts.mkdir()
            (receipts / "e1.json").write_text("{}", encoding="utf-8")
            self.assertEqual(validate_manifest(manifest, output), [])

    def test_named_sample_render_is_excluded_but_source_media_remains_bound(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "hyperframes"
            project.mkdir()
            (project / "index.html").write_text("<main></main>", encoding="utf-8")
            (project / "storyboard.json").write_text("{}", encoding="utf-8")
            (project / "source.mp4").write_bytes(b"source-media")
            output = project / "renderer-project-manifest.json"

            manifest = build_manifest(project, output)
            (project / "sample-preview.mp4").write_bytes(b"render-output")

            self.assertEqual(validate_manifest(manifest, output), [])
            self.assertIn(
                "source.mp4",
                [row["relative_path"] for row in manifest["files"]],
            )

    def test_audio_production_and_review_evidence_do_not_invalidate_renderer_sources(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "hyperframes"
            project.mkdir()
            (project / "index.html").write_text("<main></main>", encoding="utf-8")
            (project / "storyboard.json").write_text("{}", encoding="utf-8")
            output = project / "renderer-project-manifest.json"
            manifest = build_manifest(project, output)

            for name in (
                "audio-plan.json",
                "audio-sfx-manifest.json",
                "mix-audibility.json",
                "bgm-provenance.json",
            ):
                (project / name).write_text("{}", encoding="utf-8")
            for directory in (project / "assets" / "sfx", project / "review-audio"):
                directory.mkdir(parents=True)
                (directory / "cue.wav").write_bytes(b"audio-evidence")

            self.assertEqual(validate_manifest(manifest, output), [])

    def test_manifest_rejects_escaping_or_duplicate_entries(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "hyperframes"
            project.mkdir()
            (project / "index.html").write_text("<main></main>", encoding="utf-8")
            (project / "storyboard.json").write_text("{}", encoding="utf-8")
            output = project / "renderer-project-manifest.json"
            manifest = build_manifest(project, output)
            manifest["files"][0]["relative_path"] = "../outside.txt"
            manifest["files"].append(dict(manifest["files"][1]))
            errors = validate_manifest(manifest, output)
            self.assertTrue(any("escapes" in error for error in errors), errors)
            self.assertTrue(any("duplicate" in error for error in errors), errors)

    def test_manifest_rejects_missing_or_relative_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "hyperframes"
            project.mkdir()
            (project / "index.html").write_text("<main></main>", encoding="utf-8")
            (project / "storyboard.json").write_text("{}", encoding="utf-8")
            output = project / "renderer-project-manifest.json"
            manifest = build_manifest(project, output)

            for invalid_root in ("", "relative/project"):
                with self.subTest(project_root=invalid_root):
                    invalid = dict(manifest)
                    invalid["project_root"] = invalid_root
                    errors = validate_manifest(invalid, output)
                    self.assertTrue(any("absolute path" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
