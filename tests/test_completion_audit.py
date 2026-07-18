from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from completion_audit import build  # noqa: E402
from director_contracts import STAGES  # noqa: E402


class CompletionAuditTests(unittest.TestCase):
    def test_audit_is_honestly_pending_when_full_render_is_paused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
                "delivery": {"mode": "single_universal_export", "output": "exports/audit-universal.mp4"},
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            director_root.mkdir(parents=True)
            state = {
                "single_universal_output": True,
                "stages": {name: {"status": "complete" if name in {
                    "inspect", "video_use_timeline", "semantic_brief", "hyperframes_storyboard", "sample_qa"
                } else "pending"} for name in STAGES},
            }
            (director_root / "director-state.json").write_text(json.dumps(state), encoding="utf-8")
            (director_root / "legacy-script-audit.json").write_text(
                json.dumps({"execution_allowed": False, "status": "legacy_quarantined"}), encoding="utf-8"
            )
            video_use = root / "edit" / "video-use"
            video_use.mkdir(parents=True)
            for name, content in {
                "edl.json": {}, "captions.json": {}, "caption-sync-report.json": {"passed": True}
            }.items():
                (video_use / name).write_text(json.dumps(content), encoding="utf-8")
            sample = root / "hyperframes-director"
            sample.mkdir()
            events = []
            for index in range(4):
                events.append({"id": f"e{index}", "visual_structure": {
                    "dom_structure": f"dom-{index}", "information_hierarchy": f"hierarchy-{index}",
                    "layout_archetype": f"layout-{index}", "animation_choreography": f"motion-{index}",
                    "use_case": f"case-{index}",
                }})
            (sample / "storyboard.json").write_text(json.dumps({"events": events}), encoding="utf-8")
            (sample / "visual-vocabulary-audit.json").write_text("{}", encoding="utf-8")
            sample_qa = director_root / "sample-qa"
            sample_qa.mkdir()
            (sample_qa / "gate-report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
            tests = root / "test-report.json"
            tests.write_text(json.dumps({"passed": True, "test_count": 5}), encoding="utf-8")

            report = build(project, tests)
            self.assertEqual(report["overall"], "pending")
            self.assertEqual(report["criteria"]["4_actual_hyperframes_final_render"]["status"], "pending")
            self.assertEqual(report["criteria"]["8_single_universal_delivery"]["status"], "pending")
            self.assertTrue(any("has not completed" in item for item in report["limitations"]))

    def test_completed_render_does_not_report_stale_paused_limitation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
                "delivery": {"mode": "single_universal_export", "output": "exports/audit-universal.mp4"},
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            director_root.mkdir(parents=True)
            state = {
                "single_universal_output": True,
                "stages": {name: {"status": "complete" if name in {
                    "full_hyperframes_qa", "final_render"
                } else "pending"} for name in STAGES},
            }
            (director_root / "director-state.json").write_text(json.dumps(state), encoding="utf-8")
            full = root / "hyperframes-director-full"
            full.mkdir()
            render = director_root / "render" / "full.mp4"
            render.parent.mkdir()
            render.write_bytes(b"render")
            (director_root / "full-hyperframes-commands.json").write_text(json.dumps({
                "final_motion_render": {"expected_artifact": str(render)}
            }), encoding="utf-8")
            qa = director_root / "full-qa"
            qa.mkdir()
            (qa / "verified-evidence.json").write_text("{}", encoding="utf-8")
            (director_root / "final-render-authorization.json").write_text("{}", encoding="utf-8")

            report = build(project)
            self.assertEqual(report["criteria"]["4_actual_hyperframes_final_render"]["status"], "pass")
            self.assertFalse(any("has not completed" in item for item in report["limitations"]))

    def test_manual_finish_audit_rejects_unbound_placeholder_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            returned = root / "exports" / "audit-manual-finish.mp4"
            returned.parent.mkdir()
            returned.write_bytes(b"manual")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
                "delivery": {
                    "mode": "single_universal_export",
                    "output": "exports/audit-universal.mp4",
                    "manual_finish": {
                        "enabled": True,
                        "backend": "opencut",
                        "returned_final": "exports/audit-manual-finish.mp4",
                    },
                },
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            manual_dir = director_root / "manual-finish"
            manual_dir.mkdir(parents=True)
            state = {
                "single_universal_output": True,
                "stages": {name: {"status": "complete" if name == "manual_finish_handoff" else "pending"}
                           for name in STAGES},
            }
            (director_root / "director-state.json").write_text(json.dumps(state), encoding="utf-8")
            for name in (
                "handoff-manifest.json", "correction-ledger.json", "return-receipt.json",
                "manual-final-media-report.json", "manual-final-qa.json",
            ):
                (manual_dir / name).write_text("{}", encoding="utf-8")

            report = build(project)

            self.assertEqual(report["criteria"]["11_optional_manual_finish_handoff"]["status"], "pending")
            self.assertTrue(any("fresh revalidation" in item for item in report["limitations"]))


if __name__ == "__main__":
    unittest.main()
