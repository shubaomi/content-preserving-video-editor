from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from action_required_contract import create_action_packet  # noqa: E402
from director import _dispatch, build_next_action_summary, parser  # noqa: E402


class DirectorCommandTests(unittest.TestCase):
    def test_nontechnical_command_surface_is_available(self) -> None:
        command_parser = parser()
        cases = {
            "resume": ["resume", "--project", "project.yaml"],
            "open-preview": ["open-preview", "--project", "project.yaml"],
            "open-studio": ["open-studio", "--project", "project.yaml", "--full"],
            "approve": ["approve", "--project", "project.yaml"],
            "authorize-render": ["authorize-render", "--project", "project.yaml"],
            "deliver": ["deliver", "--project", "project.yaml"],
            "review": ["review", "--project", "project.yaml"],
            "apply-correction": ["apply-correction", "--project", "project.yaml",
                                 "--proposal", "proposal.json", "--approved-by", "user"],
            "import-metrics": ["import-metrics", "--project", "project.yaml",
                               "--input", "metrics.json"],
            "init-project": ["init-project", "--root", "videos", "--video-id", "demo",
                             "--source", "source.mp4"],
            "doctor": ["doctor"],
            "preflight": ["preflight", "--project", "project.yaml"],
            "next": ["next", "--project", "project.yaml"],
        }
        for expected, argv in cases.items():
            with self.subTest(command=expected):
                self.assertEqual(command_parser.parse_args(argv).command, expected)

    def test_next_action_summary_surfaces_only_the_current_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            action = root / "action-required.json"
            create_action_packet(
                action,
                stage="semantic_brief",
                owner="director_with_llm",
                reason="semantic direction required",
                actions=[{
                    "id": "author-semantic-brief",
                    "owner": "director_with_llm", "instruction": "author the brief",
                    "command": [], "inputs": [],
                    "expected_outputs": ["semantic-brief.json"],
                }],
                resume_command="director.py resume --project project.yaml",
            )
            director = unittest.mock.MagicMock()
            director.action_path = action
            director.context.project_file = root / "project.yaml"
            director.state = {
                "status": "action_required", "current_stage": "semantic_brief",
                "stages": {
                    "inspect": {"status": "complete", "readiness": "ready"},
                    "semantic_brief": {"status": "action_required", "readiness": "action_required"},
                },
            }

            summary = build_next_action_summary(director)

            self.assertEqual(summary["stage"], "semantic_brief")
            self.assertEqual(summary["owner"], "director_with_llm")
            self.assertEqual(summary["expected_outputs"], ["semantic-brief.json"])
            self.assertNotIn("stages", summary)

            packet = json.loads(action.read_text(encoding="utf-8"))
            packet["reason"] = "tampered"
            action.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "action packet"):
                build_next_action_summary(director)

    def test_next_action_summary_does_not_hide_failed_or_packetless_blocked_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            director = unittest.mock.MagicMock()
            director.action_path = root / "missing-action-required.json"
            director.context.project_file = root / "project.yaml"
            director.state = {
                "stages": {
                    "inspect": {"status": "failed", "readiness": "failed",
                                "error": "ffprobe failed"},
                },
            }

            failed = build_next_action_summary(director)

            self.assertEqual(failed["status"], "failed")
            self.assertIn("ffprobe failed", failed["reason"])
            self.assertNotEqual(failed.get("status"), "ready_to_run")

            director.state["stages"]["inspect"] = {
                "status": "action_required", "readiness": "action_required",
                "error": "missing semantic brief",
            }
            blocked = build_next_action_summary(director)
            self.assertEqual(blocked["status"], "action_required")
            self.assertIn("missing semantic brief", blocked["reason"])
            self.assertEqual(blocked["command"], [])

    def test_diagnostic_commands_do_not_construct_or_mutate_director(self) -> None:
        command_parser = parser()
        with patch("director.Director", side_effect=AssertionError("must not construct")), \
             patch("director.run_doctor", return_value={"ok": True, "status": "pass"}):
            self.assertEqual(_dispatch(command_parser.parse_args(["doctor"])), 0)
        with patch("director.Director", side_effect=AssertionError("must not construct")), \
             patch("director.run_preflight", return_value={"ok": True, "status": "pass"}):
            self.assertEqual(_dispatch(command_parser.parse_args([
                "preflight", "--project", "project.yaml",
            ])), 0)

    def test_interactive_review_requires_explicit_enablement(self) -> None:
        command_parser = parser()
        args = command_parser.parse_args([
            "review", "--project", "project.yaml", "--interactive",
        ])
        director = unittest.mock.MagicMock()
        director.project = {"review": {"dashboard": {"enabled": True},
                                        "interactive": {"enabled": False}}}
        director.context.root = Path(".").resolve()
        director.root = Path("director").resolve()
        with patch("director.Director", return_value=director):
            with self.assertRaisesRegex(Exception, "review.interactive.enabled"):
                _dispatch(args)

    def test_apply_correction_writes_ledger_only_after_explicit_approval(self) -> None:
        command_parser = parser()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "storyboard.json"
            target.write_text('{"events": []}', encoding="utf-8")
            from director_contracts import sha256_file
            proposal = root / "proposal.json"
            proposal.write_text(json.dumps({
                "schema_version": 1, "proposal_id": "p1", "status": "pending",
                "action": "move", "event_id": "e1", "target_path": str(target),
                "target_sha256": sha256_file(target), "selector": "#e1",
                "before_value": {"x": 10}, "after_value": {"x": 20},
                "reason": "safe-zone alignment", "approver": "reviewer",
                "timestamp": "2026-08-02T00:00:00+00:00",
                "related_files": [{"path": str(target), "sha256": sha256_file(target)}],
                "applied": False,
            }), encoding="utf-8")
            director = unittest.mock.MagicMock()
            director.context.root = root
            director.manual_finish_dir = root / "manual-finish"
            director.root = root / "director"
            director.state_path = director.root / "state.json"
            director.project = {
                "video_id": "demo",
                "preferences": {"learning": {
                    "enabled": True, "minimum_samples": 2, "default_scope": "video",
                }},
            }
            args = command_parser.parse_args([
                "apply-correction", "--project", str(root / "project.yaml"),
                "--proposal", str(proposal), "--approved-by", "user",
            ])
            with patch("director.Director", return_value=director), \
                 patch("director.reset_stage") as reset:
                self.assertEqual(_dispatch(args), 0)
            ledger = json.loads((director.manual_finish_dir / "correction-ledger.json")
                                .read_text(encoding="utf-8"))
            self.assertEqual(ledger["entries"][0]["event_id"], "e1")
            self.assertEqual(ledger["entries"][0]["property"], "position")
            self.assertEqual(json.loads(proposal.read_text(encoding="utf-8"))["status"], "applied")
            candidates = json.loads((director.root / "preferences" / "preference-candidates.json")
                                    .read_text(encoding="utf-8"))
            self.assertEqual(candidates["status"], "pending_review")
            self.assertFalse(candidates["candidates"][0]["eligible_for_approval"])
            reset.assert_called()

    def test_feedback_import_is_release_bound_and_never_auto_changes_preferences(self) -> None:
        command_parser = parser()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            director_root = root / "work" / "director"
            release_dir = root / "exports" / "release-pack"
            full_project = root / "edit" / "hyperframes-full"
            release_dir.mkdir(parents=True)
            director_root.mkdir(parents=True)
            full_project.mkdir(parents=True)
            storyboard = full_project / "storyboard.json"
            storyboard.write_text('{"events":[]}', encoding="utf-8")
            contract = director_root / "delivery-contract.json"
            contract.write_text('{"status":"pass"}', encoding="utf-8")
            (release_dir / "release-pack.json").write_text(json.dumps({
                "publication": {"id": "pub-1"},
                "release_bindings": {
                    "video_sha256": "a" * 64, "cover_sha256": "b" * 64,
                    "copy_sha256": "c" * 64,
                },
            }), encoding="utf-8")
            source = root / "metrics.json"
            source.write_text(json.dumps({
                "platform": "douyin", "published_at": "2026-08-01T00:00:00Z",
                "observed_at": "2026-08-02T00:00:00Z", "metrics": {"views": 50},
            }), encoding="utf-8")
            director = unittest.mock.MagicMock()
            director.project = {
                "feedback": {"metrics_import": {"enabled": True}, "learning_loop": {
                    "enabled": True, "minimum_snapshots": 2, "minimum_views": 200,
                    "minimum_elapsed_hours": 24.0,
                }},
                "delivery": {"release_pack": {"output_dir": "exports/release-pack"}},
            }
            director.root = director_root
            director.full_hyperframes_project = full_project
            director._optional_project_path.return_value = release_dir
            args = command_parser.parse_args([
                "import-metrics", "--project", str(root / "project.yaml"),
                "--input", str(source),
            ])
            with patch("director.Director", return_value=director):
                self.assertEqual(_dispatch(args), 0)
            analysis = json.loads((director_root / "feedback" / "analysis.json")
                                  .read_text(encoding="utf-8"))
            self.assertEqual(analysis["status"], "insufficient_evidence")
            self.assertEqual(analysis["preference_candidates"], [])
            snapshot = next((director_root / "feedback" / "snapshots").glob("*.json"))
            self.assertEqual(json.loads(snapshot.read_text(encoding="utf-8"))
                             ["binding"]["publication_id"], "pub-1")


if __name__ == "__main__":
    unittest.main()
