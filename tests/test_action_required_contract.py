from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from action_required_contract import create_action_packet, validate_action_packet  # noqa: E402


def action(action_id: str, instruction: str) -> dict:
    return {
        "id": action_id, "owner": "human_reviewer", "instruction": instruction,
        "command": [], "inputs": [], "expected_outputs": [],
    }


class ActionRequiredContractTests(unittest.TestCase):
    def test_packet_survives_relocation_and_is_bound_to_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "original"
            evidence = root / "evidence" / "review.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text('{"status":"pending"}', encoding="utf-8")
            packet_path = root / "action-required.json"
            packet = create_action_packet(
                packet_path,
                stage="cover",
                owner="human_reviewer",
                reason="Identity approval is required",
                actions=[action("approve_identity", "Review the cover")],
                artifacts=[evidence],
                resume_command="python director.py run --project project.yaml --resume",
            )
            self.assertEqual(packet["schema_version"], 1)
            self.assertEqual(packet["payload"]["artifacts"][0]["path"], "evidence/review.json")

            relocated = Path(temp) / "relocated"
            shutil.copytree(root, relocated)
            validated = validate_action_packet(relocated / "action-required.json")
            self.assertEqual(validated["payload"]["stage"], "cover")

    def test_payload_or_artifact_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "evidence.txt"
            artifact.write_text("original", encoding="utf-8")
            packet_path = root / "action-required.json"
            create_action_packet(
                packet_path, stage="sample_qa", owner="reviewer", reason="Review required",
                actions=[action("review", "Review sample")], artifacts=[artifact],
                resume_command="python director.py run --project project.yaml --resume",
            )
            artifact.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact hash"):
                validate_action_packet(packet_path)

            artifact.write_text("original", encoding="utf-8")
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            packet["payload"]["owner"] = "attacker"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "payload hash"):
                validate_action_packet(packet_path)

    def test_project_root_reference_allows_whole_project_relocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            artifact = project / "exports" / "final.mp4"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"video")
            packet = project / "work" / "director" / "action-required.json"
            create_action_packet(
                packet, stage="publish", owner="publisher", reason="External authorization required",
                actions=[action("authorize", "Authorize publication")],
                artifacts=[artifact], reference_root=project,
                resume_command="python director.py run --project project.yaml --resume",
            )
            moved = Path(temp) / "moved"
            shutil.copytree(project, moved)
            self.assertEqual(validate_action_packet(
                moved / "work" / "director" / "action-required.json"
            )["payload"]["artifacts"][0]["path"], "exports/final.mp4")

    def test_missing_machine_readable_handoff_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "owner.*command.*inputs.*expected_outputs"):
                create_action_packet(
                    Path(temp) / "action-required.json", stage="qa", owner="reviewer",
                    reason="review", actions=[{"id": "review", "instruction": "Review"}],
                    resume_command="python director.py run --project project.yaml --resume",
                )


if __name__ == "__main__":
    unittest.main()
