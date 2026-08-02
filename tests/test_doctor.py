from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from doctor import HYPERFRAMES_SKILLS, run_doctor  # noqa: E402


def toolchain_report(*, available: bool = True) -> dict:
    return {
        "mutates_toolchain": False,
        "tools": {
            name: {"available": available, "path": f"C:/tools/{name}.exe" if available else None}
            for name in ("python", "ffmpeg", "ffprobe", "node", "npm", "npx", "hyperframes")
        },
        "skill_roots": {
            "video-use": {"available": available, "path": "C:/skills/video-use"},
        },
        "required_hyperframes_skills": {
            name: {"available": available, "path": f"C:/skills/{name}"}
            for name in HYPERFRAMES_SKILLS
        },
    }


class DoctorTests(unittest.TestCase):
    def test_reports_each_hyperframes_skill_and_video_use_separately(self) -> None:
        report = run_doctor(toolchain_report=toolchain_report())
        by_id = {status["id"]: status for status in report["statuses"]}

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(
            {f"skill.{name}" for name in HYPERFRAMES_SKILLS},
            {status_id for status_id in by_id if status_id.startswith("skill.hyperframes")},
        )
        self.assertEqual(by_id["skill.video-use"]["status"], "pass")
        self.assertEqual(by_id["tool.python"]["availability"], "available")
        self.assertEqual(by_id["tool.npm"]["availability"], "available")
        self.assertTrue(all(set(row) >= {"id", "status", "required", "message"}
                            for row in report["statuses"]))

    def test_missing_required_skill_produces_a_structured_failure(self) -> None:
        toolchain = toolchain_report()
        toolchain["required_hyperframes_skills"]["hyperframes-cli"]["available"] = False

        report = run_doctor(toolchain_report=toolchain)
        by_id = {status["id"]: status for status in report["statuses"]}

        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "fail")
        self.assertEqual(by_id["skill.hyperframes-cli"]["status"], "fail")

    def test_diagnostic_does_not_create_state_or_expose_environment_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            secret = "DO-NOT-EXPOSE-THIS-TOKEN"
            with patch.dict(os.environ, {"HYPERFRAMES_API_KEY": secret}):
                with patch("doctor.build_toolchain_report", return_value=toolchain_report()):
                    report = run_doctor()

            self.assertFalse((root / "director-state.json").exists())
            self.assertNotIn(secret, json.dumps(report))
            self.assertFalse(report["mutates_environment"])
            self.assertFalse(report["network_access"])


if __name__ == "__main__":
    unittest.main()
