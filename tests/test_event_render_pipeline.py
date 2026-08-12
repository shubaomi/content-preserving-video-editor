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
        observed_by_scope = {"a": segment_a, "b": segment_b, "assembly": output}
        def equivalence(scope: str) -> dict:
            path = root / f"equivalence-{scope}.json"
            reference = root / f"equivalence-{scope}.reference.mp4"
            observed = observed_by_scope[scope]
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=5:d=0.2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(reference),
            ], check=True)
            command_script = (
                "import sys;from pathlib import Path;"
                f"Path(sys.argv[1]).write_bytes(Path(r'{reference}').read_bytes())"
            )
            observed.write_bytes(reference.read_bytes())
            payload = {
                "schema_version": 1, "kind": "hyperframes_event_equivalence",
                "status": "pass", "scope": scope, "frame_accurate": True,
                "audio_sample_accurate": True, "visual_equivalent": True,
                "ordered_segment_hash_binding": scope == "assembly",
                "reference_artifact": str(reference.resolve()),
                "reference_sha256": __import__("hashlib").sha256(reference.read_bytes()).hexdigest(),
                "observed_artifact": str(observed.resolve()),
                "observed_sha256": __import__("hashlib").sha256(observed.read_bytes()).hexdigest(),
                "full_decode": True,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            return {
                "path": str(path.resolve()), "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
                "scope": scope, "frame_accurate": True, "audio_sample_accurate": True,
                "visual_equivalent": True,
                "_command_script": command_script,
            }
        evidence_a = equivalence("a")
        evidence_b = equivalence("b")
        evidence_assembly = equivalence("assembly")
        record = {
            "event_motion_renders": [
                {"event_id": "a", "owner": "hyperframes", "cwd": str(root),
                 "expected_artifact": str(segment_a), "argv": [sys.executable, "-c", evidence_a.pop("_command_script"), str(segment_a)],
                 "renderer_version": "fixture", "equivalence_evidence": evidence_a},
                {"event_id": "b", "owner": "hyperframes", "cwd": str(root),
                 "expected_artifact": str(segment_b), "argv": [sys.executable, "-c", evidence_b.pop("_command_script"), str(segment_b)],
                 "renderer_version": "fixture", "equivalence_evidence": evidence_b},
            ],
            "event_motion_assembly": {
                "owner": "hyperframes", "cwd": str(root), "expected_artifact": str(output),
                "argv": [sys.executable, "-c", evidence_assembly.pop("_command_script"), str(output)],
                "renderer_version": "fixture",
                "equivalence_evidence": evidence_assembly,
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
            self.assertTrue(files["output"].is_file())
            self.assertGreater(files["output"].stat().st_size, 0)
            self.assertEqual(second["cost_accounting"]["executed_event_count"], 0)
            self.assertEqual(second["cost_accounting"]["cache_hit_count"], 2)
            self.assertEqual(second["cost_accounting"]["retry_count"], 0)
            self.assertGreaterEqual(second["cost_accounting"]["cache_saved_event_seconds"], 0.0)
            self.assertEqual(second["cost_accounting"]["provider_actual_cost"], 0.0)

    def test_cost_accounting_uses_declared_estimates_without_inventing_provider_cost(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record, files = self._fixture(root)
            record["event_motion_renders"][0]["estimated_render_seconds"] = 4.5
            record["event_motion_renders"][1]["estimated_render_seconds"] = 3.0
            first = self._run(root, record, files)
            files["output"].unlink()
            for row in record["event_motion_renders"]:
                Path(row["expected_artifact"]).unlink()
            second = self._run(root, record, files, first["fingerprints"])

            self.assertEqual(second["cost_accounting"]["cache_saved_event_seconds"], 7.5)
            self.assertEqual(second["cost_accounting"]["provider_reservations"], [])
            self.assertEqual(second["cost_accounting"]["provider_actuals"], [])

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
                subprocess.run(command, check=True, capture_output=True, text=True)
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
                subprocess.run(command, check=True, capture_output=True, text=True)
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
