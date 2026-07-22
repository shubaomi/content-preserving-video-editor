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

from capability_registry import (  # noqa: E402
    CAPABILITY_LEVELS,
    build_capability_inventory,
    build_toolchain_report,
)
from director import Director  # noqa: E402


class CapabilityRegistryTests(unittest.TestCase):
    def test_inventory_declares_complete_adapter_contract_and_truthful_levels(self) -> None:
        project = {
            "schema_version": 3,
            "workflow": {"capabilities": {"design_tokens": {"enabled": True}}},
        }
        inventory = build_capability_inventory(project)
        by_name = {row["name"]: row for row in inventory["capabilities"]}

        self.assertTrue({"design_tokens", "render_cache", "asr_router", "otio_timeline"} <= set(by_name))
        required = {
            "name", "owner", "dependencies", "compatibility", "inputs", "outputs",
            "optional", "cache_key_fields", "failure_fallback", "enabled", "route_reason",
            "maturity", "capability_version", "configuration_route",
        }
        self.assertTrue(all(required <= set(row) for row in by_name.values()))
        self.assertEqual(by_name["design_tokens"]["maturity"], "director_integrated")
        self.assertTrue(by_name["design_tokens"]["enabled"])
        self.assertFalse(by_name["otio_timeline"]["enabled"])
        self.assertIn(by_name["otio_timeline"]["maturity"], CAPABILITY_LEVELS)
        minimum = CAPABILITY_LEVELS.index("director_integrated")
        self.assertTrue(all(CAPABILITY_LEVELS.index(row["maturity"]) >= minimum
                            for row in by_name.values()))

    def test_toolchain_report_records_versions_without_installing_or_updating(self) -> None:
        with patch("capability_registry.shutil.which", side_effect=lambda name: f"C:/tools/{name}.exe"):
            with patch("capability_registry._command_version", return_value="1.2.3"):
                report = build_toolchain_report(probe_versions=True)

        self.assertFalse(report["mutates_toolchain"])
        self.assertEqual(report["update_policy"], "never_silent")
        self.assertTrue(report["tools"]["ffmpeg"]["available"])
        self.assertEqual(report["tools"]["ffmpeg"]["detected_version"], "1.2.3")
        self.assertIn("supported_range", report["tools"]["hyperframes"])
        self.assertIn("npx", report["tools"])
        self.assertEqual(report["tools"]["hyperframes"]["invocation_fallback"], "npx hyperframes")
        required_skills = report["required_hyperframes_skills"]
        self.assertEqual(set(required_skills), {
            "hyperframes", "hyperframes-core", "hyperframes-creative",
            "hyperframes-animation", "hyperframes-cli",
        })
        self.assertTrue(all("available" in row and "path" in row
                            for row in required_skills.values()))

    def test_inventory_uses_canonical_schema_paths_for_optional_backends(self) -> None:
        inventory = build_capability_inventory({
            "transcription": {"router": {"enabled": True}},
            "timeline": {"otio": {"enabled": True}},
            "render": {"cache": {"enabled": True}},
            "extensions": {"b_roll": {"enabled": True}},
            "renderer": {"remotion": {"enabled": True}},
            "feedback": {"metrics_import": {"enabled": True}},
            "analysis": {"hook_pacing": {"enabled": True}},
            "publishing": {"copy": {"enabled": True}},
            "assets": {"media_catalog": {"enabled": True}},
        })
        enabled = {row["name"] for row in inventory["capabilities"] if row["enabled"]}
        self.assertTrue({"asr_router", "otio_timeline", "render_cache", "b_roll",
                         "remotion_renderer", "post_publish_metrics"} <= enabled)
        self.assertTrue({"hook_pacing", "publishing_copy", "media_catalog"} <= enabled)
        self.assertIn("evidence_acquisition", enabled)
        self.assertIn("design_tokens", enabled)

    def test_analysis_adapters_and_legacy_catalog_have_truthful_distinct_routes(self) -> None:
        inventory = build_capability_inventory({
            "analysis": {"adapters": {
                "pyscenedetect": {"enabled": True},
                "mediapipe": {"enabled": True},
                "paddleocr": {"enabled": True},
            }},
            "assets": {"use_media_catalog": True},
        })
        by_name = {row["name"]: row for row in inventory["capabilities"]}
        self.assertTrue(by_name["scene_detection"]["enabled"])
        self.assertTrue(by_name["mediapipe_tracking"]["enabled"])
        self.assertTrue(by_name["ocr"]["enabled"])
        self.assertTrue(by_name["media_catalog"]["enabled"])
        self.assertEqual(by_name["scene_detection"]["configuration_route"],
                         "analysis.adapters.pyscenedetect")
        self.assertEqual(by_name["mediapipe_tracking"]["configuration_route"],
                         "analysis.adapters.mediapipe")
        self.assertEqual(by_name["subject_tracking"]["configuration_route"],
                         "analysis.subject_tracking")

    def test_inspect_writes_inventory_and_compatibility_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "published.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source-media")
            project_file = root / "project.yaml"
            project_file.write_text(yaml.safe_dump({
                "version": 1,
                "video_id": "sample",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/published.mp4", "input_mode": "existing_edit_polish"},
            }), encoding="utf-8")

            director = Director(project_file)
            director._start("inspect")
            director.stage_inspect()

            inventory_path = director.root / "capability-inventory.json"
            toolchain_path = director.root / "toolchain-compatibility.json"
            self.assertTrue(inventory_path.is_file())
            self.assertTrue(toolchain_path.is_file())
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            self.assertEqual(inventory["schema_version"], 1)
            artifacts = director.state["stages"]["inspect"]["artifacts"]
            self.assertIn(str(inventory_path), artifacts)
            self.assertIn(str(toolchain_path), artifacts)


if __name__ == "__main__":
    unittest.main()
