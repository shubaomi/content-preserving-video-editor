from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import STAGES  # noqa: E402
from state_migrations import (  # noqa: E402
    CURRENT_STATE_SCHEMA_VERSION,
    StateRecoveryRequired,
    load_and_migrate_state,
    migrate_state,
)


def pending_stages() -> dict:
    return {name: {"status": "pending", "artifact_records": []} for name in STAGES}


class StateMigrationTests(unittest.TestCase):
    def test_v6_to_current_migration_is_idempotent(self) -> None:
        original = {
            "schema_version": 6,
            "director_version": "2.2.0",
            "project_file": "C:/project/project.yaml",
            "project_root": "C:/project",
            "stages": pending_stages(),
        }
        migrated = migrate_state(original)
        self.assertEqual(original["schema_version"], 6)
        self.assertEqual(migrated["schema_version"], CURRENT_STATE_SCHEMA_VERSION)
        self.assertEqual(migrated["dependency_state"], {
            "schema_version": 1,
            "event_fingerprints": {},
            "last_plan": None,
        })
        self.assertEqual(migrate_state(migrated), migrated)

    def test_future_state_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "newer than supported"):
            migrate_state({"schema_version": CURRENT_STATE_SCHEMA_VERSION + 1})

    def test_corrupt_state_is_quarantined_and_recovery_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "director-state.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(StateRecoveryRequired) as raised:
                load_and_migrate_state(path)
            self.assertFalse(path.exists())
            quarantine = raised.exception.quarantine_path
            self.assertTrue(quarantine.is_file())
            self.assertEqual(quarantine.read_text(encoding="utf-8"), "{broken")

    def test_load_migrates_valid_state_without_rewriting_until_caller_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "director-state.json"
            raw = {"schema_version": 6, "stages": pending_stages()}
            path.write_text(json.dumps(raw), encoding="utf-8")
            migrated = load_and_migrate_state(path)
            self.assertEqual(migrated["schema_version"], CURRENT_STATE_SCHEMA_VERSION)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), raw)


if __name__ == "__main__":
    unittest.main()
