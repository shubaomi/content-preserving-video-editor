from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from project_initializer import PRESETS, detect_source, initialize_project  # noqa: E402


class ProjectInitializerTests(unittest.TestCase):
    def test_declares_the_six_supported_project_presets(self) -> None:
        self.assertEqual(set(PRESETS), {
            "auto",
            "landscape_screen_tutorial",
            "portrait_talking_head",
            "published_edit_polish",
            "interview",
            "screen_plus_camera",
        })

    def test_all_six_presets_create_migrated_project_configs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"source")

            for preset in PRESETS:
                with self.subTest(preset=preset):
                    project_file = initialize_project(
                        root / "projects", preset, source, preset=preset,
                    )
                    project = yaml.safe_load(project_file.read_text(encoding="utf-8"))
                    self.assertEqual(project["preset"], preset)
                    self.assertEqual(project["schema_version"], project["version"])

            auto = yaml.safe_load(
                (root / "projects" / "auto" / "project.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(auto["source"]["input_mode"], "needs_analysis")

    def test_detects_one_media_file_in_a_directory_and_copies_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            incoming = root / "incoming"
            incoming.mkdir()
            source = incoming / "Demo.MOV"
            source.write_bytes(b"source-video")
            (incoming / "notes.txt").write_text("ignore me", encoding="utf-8")

            self.assertEqual(detect_source(incoming), source.resolve())
            project_file = initialize_project(
                root / "projects", "demo", incoming, preset="screen_tutorial",
            )

            project = yaml.safe_load(project_file.read_text(encoding="utf-8"))
            copied = project_file.parent / project["source"]["primary_video"]
            self.assertEqual(copied.read_bytes(), b"source-video")
            self.assertEqual(project["preset"], "landscape_screen_tutorial")
            self.assertEqual(project["content_type"], "screen_tutorial")
            self.assertEqual(project["source"]["input_mode"], "raw")
            self.assertEqual(source.read_bytes(), b"source-video")

    def test_rejects_ambiguous_source_directories_without_creating_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            incoming = root / "incoming"
            incoming.mkdir()
            (incoming / "one.mp4").write_bytes(b"one")
            (incoming / "two.mov").write_bytes(b"two")

            with self.assertRaisesRegex(ValueError, "multiple media files"):
                initialize_project(root / "projects", "demo", incoming)

            self.assertFalse((root / "projects" / "demo").exists())

    def test_refuses_to_overwrite_even_an_empty_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            destination = root / "projects" / "demo"
            destination.mkdir(parents=True)

            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                initialize_project(root / "projects", "demo", root / "missing.mp4")

            self.assertEqual(list(destination.iterdir()), [])

    def test_copy_failure_rolls_back_staging_and_final_directories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            projects = root / "projects"

            with patch("project_initializer.shutil.copy2", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    initialize_project(projects, "demo", source)

            self.assertFalse((projects / "demo").exists())
            self.assertEqual(list(projects.glob(".demo.*.tmp")), [])

    def test_preset_aliases_are_normalized_to_the_canonical_name(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"source")

            project_file = initialize_project(
                root / "projects", "demo", source, preset="two_person_interview",
            )
            project = yaml.safe_load(project_file.read_text(encoding="utf-8"))

            self.assertEqual(project["preset"], "interview")
            self.assertEqual(project["content_type"], "interview")
            self.assertEqual(project["transcription"]["router"]["preferred_backend"], "whisperx")

    def test_initialization_records_probe_evidence_and_human_summary(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            evidence = {
                "status": "available", "width": 1080, "height": 1920,
                "display_width": 1080, "display_height": 1920,
                "orientation": "portrait", "display_rotation": 0,
                "aspect_ratio": 0.5625, "duration_seconds": 31.2,
                "video_streams": 1, "audio_streams": 1, "subtitle_streams": 0,
                "existing_edit_evidence": ["encoder_metadata"],
            }
            with patch("project_initializer.probe_media", return_value=evidence):
                project_file = initialize_project(root / "projects", "demo", source)
            report = yaml.safe_load(
                (project_file.parent / "initialization-report.json").read_text(encoding="utf-8")
            )
            summary = (project_file.parent / "INITIALIZATION.md").read_text(encoding="utf-8")
            project = yaml.safe_load(project_file.read_text(encoding="utf-8"))
            self.assertEqual(report["media"]["orientation"], "portrait")
            self.assertEqual(report["status"], "initialized")
            self.assertEqual(project["source"]["probe"]["display_height"], 1920)
            self.assertIn("portrait", summary)


if __name__ == "__main__":
    unittest.main()
