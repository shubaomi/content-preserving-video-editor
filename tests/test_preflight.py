from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from doctor import HYPERFRAMES_SKILLS  # noqa: E402
from preflight import run_preflight  # noqa: E402
from project_config import CURRENT_PROJECT_SCHEMA_VERSION  # noqa: E402


def toolchain_report() -> dict:
    return {
        "mutates_toolchain": False,
        "tools": {
            name: {"available": True, "path": f"C:/tools/{name}.exe"}
            for name in ("python", "ffmpeg", "ffprobe", "node", "npm", "npx", "hyperframes")
        },
        "skill_roots": {"video-use": {"available": True, "path": "C:/skills/video-use"}},
        "required_hyperframes_skills": {
            name: {"available": True, "path": f"C:/skills/{name}"}
            for name in HYPERFRAMES_SKILLS
        },
    }


class PreflightTests(unittest.TestCase):
    def _project(self, root: Path, *, source_exists: bool = True) -> Path:
        for name in ("source", "edit", "hyperframes", "scripts", "work", "exports"):
            (root / name).mkdir(parents=True)
        if source_exists:
            (root / "source" / "input.mp4").write_bytes(b"video")
        project_file = root / "project.yaml"
        project_file.write_text(yaml.safe_dump({
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "version": CURRENT_PROJECT_SCHEMA_VERSION,
            "video_id": "demo",
            "paths": {"root": str(root)},
            "source": {"primary_video": "source/input.mp4"},
            "private_api_key": "SHOULD-NOT-LEAK",
        }), encoding="utf-8")
        return project_file

    def test_valid_project_reports_read_only_structured_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_file = self._project(root)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

            with patch("preflight.build_toolchain_report", return_value=toolchain_report()):
                report = run_preflight(project_file)

            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            by_id = {status["id"]: status for status in report["statuses"]}
            self.assertTrue(report["ok"])
            self.assertEqual(report["status"], "pass")
            self.assertEqual(before, after)
            self.assertFalse((root / "director-state.json").exists())
            self.assertEqual(by_id["project.config"]["status"], "pass")
            self.assertEqual(by_id["project.source"]["status"], "pass")
            self.assertEqual(by_id["skill.video-use"]["status"], "pass")
            self.assertTrue(all(f"skill.{name}" in by_id for name in HYPERFRAMES_SKILLS))
            self.assertNotIn("SHOULD-NOT-LEAK", json.dumps(report))
            self.assertFalse(report["mutates_project"])
            self.assertFalse(report["network_access"])

    def test_missing_source_is_a_failure_without_creating_any_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_file = self._project(root, source_exists=False)

            with patch("preflight.build_toolchain_report", return_value=toolchain_report()):
                report = run_preflight(project_file)

            by_id = {status["id"]: status for status in report["statuses"]}
            self.assertFalse(report["ok"])
            self.assertEqual(by_id["project.source"]["status"], "fail")
            self.assertFalse((root / "director-state.json").exists())

    def test_invalid_yaml_returns_a_status_instead_of_raising_or_leaking_content(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project_file = Path(folder) / "project.yaml"
            project_file.write_text("secret: TOP-SECRET\ninvalid: [", encoding="utf-8")

            with patch("preflight.build_toolchain_report", return_value=toolchain_report()):
                report = run_preflight(project_file)

            config_status = next(row for row in report["statuses"] if row["id"] == "project.config")
            self.assertEqual(config_status["status"], "fail")
            self.assertNotIn("TOP-SECRET", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
