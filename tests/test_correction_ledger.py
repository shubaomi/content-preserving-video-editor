from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from correction_ledger import (  # noqa: E402
    append_correction,
    new_ledger,
    replay_corrections,
    validate_ledger,
)


class CorrectionLedgerTests(unittest.TestCase):
    def test_correction_is_hashed_validated_and_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "storyboard.json"
            target.write_text('{"targets":{"#callout":{"left":120}}}', encoding="utf-8")
            ledger_path = root / "correction-ledger.json"
            new_ledger(ledger_path, project_root=root)

            append_correction(
                ledger_path,
                event_id="event-1",
                target_file=target,
                selector="#callout",
                property_name="left",
                before_value=120,
                after_value=144,
                reason="optical alignment against the source panel",
                approved_by="hongr",
                approved_at="2026-07-17T12:00:00+00:00",
                related_files=[target],
            )

            ledger = validate_ledger(ledger_path)
            self.assertEqual(len(ledger["entries"]), 1)
            replayed = replay_corrections(
                {"targets": {"#callout": {"left": 120}}},
                ledger,
            )
            self.assertEqual(replayed["targets"]["#callout"]["left"], 144)

    def test_replay_rejects_drift_from_recorded_before_value(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "storyboard.json"
            target.write_text("{}", encoding="utf-8")
            ledger_path = root / "correction-ledger.json"
            new_ledger(ledger_path, project_root=root)
            append_correction(
                ledger_path,
                event_id="event-1",
                target_file=target,
                selector="#callout",
                property_name="left",
                before_value=120,
                after_value=144,
                reason="alignment",
                approved_by="hongr",
                approved_at="2026-07-17T12:00:00+00:00",
                related_files=[target],
            )
            ledger = validate_ledger(ledger_path)
            with self.assertRaisesRegex(ValueError, "before_value"):
                replay_corrections({"targets": {"#callout": {"left": 121}}}, ledger)


if __name__ == "__main__":
    unittest.main()
