from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from event_render_pipeline import EventRenderUnavailable, execute_event_render_pipeline  # noqa: E402


class EventRenderPipelineTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[dict, dict[str, Path]]:
        storyboard = root / "storyboard.json"
        storyboard.write_text(json.dumps({"events": [
            {"event_id": "a", "anchor": "concept"},
            {"event_id": "b", "anchor": "result"},
        ]}), encoding="utf-8")
        files = {name: root / f"{name}.json" for name in
                 ("captions", "safe", "tokens", "provider", "rights")}
        for path in files.values():
            path.write_text("{}", encoding="utf-8")
        segment_a, segment_b, output = root / "a.mov", root / "b.mov", root / "out.mp4"
        evidence = {"frame_accurate": True, "audio_sample_accurate": True,
                    "visual_equivalent": True}
        def write_command(path: Path, value: str) -> list[str]:
            return [sys.executable, "-c",
                    f"import sys;from pathlib import Path;Path(sys.argv[1]).write_bytes({value!r}.encode())",
                    str(path)]
        record = {
            "event_motion_renders": [
                {"event_id": "a", "owner": "hyperframes", "cwd": str(root),
                 "expected_artifact": str(segment_a), "argv": write_command(segment_a, "A"),
                 "renderer_version": "fixture", "equivalence_evidence": evidence},
                {"event_id": "b", "owner": "hyperframes", "cwd": str(root),
                 "expected_artifact": str(segment_b), "argv": write_command(segment_b, "B"),
                 "renderer_version": "fixture", "equivalence_evidence": evidence},
            ],
            "event_motion_assembly": {
                "owner": "hyperframes", "cwd": str(root), "expected_artifact": str(output),
                "argv": [sys.executable, "-c",
                         f"import sys;from pathlib import Path;Path(sys.argv[1]).write_bytes(Path(r'{segment_a}').read_bytes()+Path(r'{segment_b}').read_bytes())",
                         str(output)],
                "renderer_version": "fixture",
                "equivalence_evidence": {**evidence, "ordered_segment_hash_binding": True},
            },
        }
        return record, {"storyboard": storyboard, **files, "output": output}

    def _run(self, root: Path, record: dict, files: dict[str, Path], previous=None):
        return execute_event_render_pipeline(
            command_record=record, storyboard_path=files["storyboard"],
            captions_path=files["captions"], safe_zones_path=files["safe"],
            design_tokens_path=files["tokens"], provider_evidence_path=files["provider"],
            rights_evidence_path=files["rights"], implementation_paths=[Path(__file__)],
            cache_root=root / "cache", output=files["output"],
            previous_fingerprints=previous,
        )

    def test_executes_real_declared_event_commands_then_reuses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record, files = self._fixture(root)
            first = self._run(root, record, files)
            self.assertEqual(first["executed_events"], ["a", "b"])
            files["output"].unlink()
            for row in record["event_motion_renders"]:
                Path(row["expected_artifact"]).unlink()
            second = self._run(root, record, files, first["fingerprints"])
            self.assertEqual(second["cache_hits"], ["a", "b"])
            self.assertTrue(second["assembly_reused"])
            self.assertEqual(files["output"].read_bytes(), b"AB")

    def test_changed_event_invalidates_only_it_while_assembly_is_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record, files = self._fixture(root)
            first = self._run(root, record, files)
            storyboard = json.loads(files["storyboard"].read_text(encoding="utf-8"))
            storyboard["events"][0]["anchor"] = "changed"
            files["storyboard"].write_text(json.dumps(storyboard), encoding="utf-8")
            second = self._run(root, record, files, first["fingerprints"])
            self.assertIn("a", second["plan"]["rebuild"])
            self.assertIn("b", second["cache_hits"])
            self.assertFalse(second["assembly_reused"])

    def test_changed_event_rebuilds_declared_dependents(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record, files = self._fixture(root)
            record["event_motion_renders"][1]["depends_on"] = ["a"]
            first = self._run(root, record, files)
            storyboard = json.loads(files["storyboard"].read_text(encoding="utf-8"))
            storyboard["events"][0]["anchor"] = "changed"
            files["storyboard"].write_text(json.dumps(storyboard), encoding="utf-8")
            second = self._run(root, record, files, first["fingerprints"])
            self.assertEqual(second["plan"]["rebuild"], ["a", "b"])
            self.assertEqual(second["executed_events"], ["a", "b"])
            self.assertEqual(second["cache_hits"], [])

    def test_input_drift_during_render_is_rejected_before_cache_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record, files = self._fixture(root)

            def mutating_runner(command, **kwargs):
                Path(command[-1]).write_bytes(b"render")
                files["captions"].write_text('{"changed":true}', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with self.assertRaisesRegex(EventRenderUnavailable, "changed during"):
                execute_event_render_pipeline(
                    command_record=record, storyboard_path=files["storyboard"],
                    captions_path=files["captions"], safe_zones_path=files["safe"],
                    design_tokens_path=files["tokens"], provider_evidence_path=files["provider"],
                    rights_evidence_path=files["rights"], implementation_paths=[Path(__file__)],
                    cache_root=root / "cache", output=files["output"], runner=mutating_runner,
                )

    def test_storyboard_drift_during_render_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record, files = self._fixture(root)

            def mutating_runner(command, **kwargs):
                Path(command[-1]).write_bytes(b"render")
                files["storyboard"].write_text('{"events":[]}', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with self.assertRaisesRegex(EventRenderUnavailable, "changed during"):
                execute_event_render_pipeline(
                    command_record=record, storyboard_path=files["storyboard"],
                    captions_path=files["captions"], safe_zones_path=files["safe"],
                    design_tokens_path=files["tokens"], provider_evidence_path=files["provider"],
                    rights_evidence_path=files["rights"], implementation_paths=[Path(__file__)],
                    cache_root=root / "cache", output=files["output"], runner=mutating_runner,
                )

    def test_missing_equivalence_proof_is_rejected_instead_of_faking_motion(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record, files = self._fixture(root)
            record["event_motion_renders"][0]["equivalence_evidence"]["visual_equivalent"] = False
            with self.assertRaisesRegex(EventRenderUnavailable, "equivalence"):
                self._run(root, record, files)


if __name__ == "__main__":
    unittest.main()
