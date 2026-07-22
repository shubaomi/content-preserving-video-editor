from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import load_project_context  # noqa: E402
from project_config import CURRENT_PROJECT_SCHEMA_VERSION, migrate_project_config  # noqa: E402


class ProjectConfigMigrationTests(unittest.TestCase):
    def test_rejects_boolean_or_non_finite_numeric_configuration(self) -> None:
        for version in (True, 1.5, "1"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "integers"):
                migrate_project_config({"schema_version": version})
        for value in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be numeric"):
                migrate_project_config({"schema_version": 6, "audio": {
                    "normalization": {"enabled": True, "target_lufs": value},
                }})
        for value in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(parity=value), self.assertRaisesRegex(ValueError, "must be (numeric|finite)"):
                migrate_project_config({"schema_version": 6, "qa": {
                    "preview_render_parity": {"tolerances": {"position_px": value}},
                }})

    def test_new_production_features_are_disabled_for_legacy_projects(self) -> None:
        original = {"version": 1}
        migrated = migrate_project_config(original)
        self.assertFalse(migrated["audio"]["production"]["enabled"])
        self.assertFalse(migrated["audio"]["normalization"]["enabled"])
        self.assertFalse(migrated["cover"]["production"]["enabled"])
        self.assertFalse(migrated["visuals"]["ip_production"]["enabled"])
        self.assertFalse(migrated["assets"]["media_catalog"]["enabled"])
        self.assertFalse(migrated["analysis"]["hook_pacing"]["enabled"])
        self.assertFalse(migrated["publishing"]["copy"]["enabled"])
        self.assertNotIn("audio", original)

    def test_v1_fixture_migrates_in_memory_without_rewriting_yaml(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "project-v1.yaml"
        original = fixture.read_bytes()
        raw = yaml.safe_load(original.decode("utf-8"))
        raw_copy = copy.deepcopy(raw)

        migrated = migrate_project_config(raw)

        self.assertEqual(raw, raw_copy)
        self.assertEqual(fixture.read_bytes(), original)
        self.assertEqual(migrated["schema_version"], CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(migrated["version"], CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(migrated["delivery"]["manual_finish"], {
            "enabled": False,
            "backend": "none",
            "returned_final": None,
            "modifications": [],
            "assets": {},
        })
        self.assertEqual(migrated["qa"]["preview_render_parity"]["tolerances"], {
            "position_px": 4.0,
            "size_px": 4.0,
            "time_seconds": 0.05,
        })
        self.assertEqual(CURRENT_PROJECT_SCHEMA_VERSION, 6)
        self.assertEqual(migrated["workflow"]["capabilities"], {})
        self.assertFalse(migrated["analysis"]["adapters"]["pyscenedetect"]["enabled"])
        self.assertFalse(migrated["timeline"]["otio"]["enabled"])
        self.assertFalse(migrated["extensions"]["b_roll"]["enabled"])
        self.assertFalse(migrated["renderer"]["remotion"]["enabled"])
        self.assertFalse(migrated["feedback"]["metrics_import"]["enabled"])

    def test_legacy_project_context_runs_with_migrated_defaults_without_yaml_mutation(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "project-v1.yaml"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_file = root / "project.yaml"
            text = fixture.read_text(encoding="utf-8").replace("root: .", f"root: {root}")
            project_file.write_text(text, encoding="utf-8")
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"video")
            before = project_file.read_bytes()

            project, context = load_project_context(project_file)

            self.assertEqual(project["delivery"]["manual_finish"]["backend"], "none")
            self.assertEqual(context.source_video, source)
            self.assertEqual(project_file.read_bytes(), before)

    def test_invalid_manual_finish_backend_is_rejected(self) -> None:
        project = {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "version": CURRENT_PROJECT_SCHEMA_VERSION,
            "delivery": {"manual_finish": {"enabled": True, "backend": "imaginary_nle"}},
        }
        with self.assertRaisesRegex(ValueError, "manual_finish.backend"):
            migrate_project_config(project)


if __name__ == "__main__":
    unittest.main()
