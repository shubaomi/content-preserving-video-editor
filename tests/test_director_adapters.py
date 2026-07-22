from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_adapters import AdapterExecutionError, AdapterRunner  # noqa: E402


class DirectorAdapterTests(unittest.TestCase):
    def test_existing_output_argument_is_not_mistaken_for_implementation_code(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "result.json"
            tool = root / "tool.py"
            tool.write_text(
                "import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('ok')\n",
                encoding="utf-8",
            )
            runner = AdapterRunner(root / "state.json")
            command = [sys.executable, str(tool), str(output)]
            first = runner.run(name="output-arg", enabled=True, command=command,
                               inputs=[], outputs=[output], blocking=True, cwd=root)
            second = runner.run(name="output-arg", enabled=True, command=command,
                                inputs=[], outputs=[output], blocking=True, cwd=root)
            self.assertEqual(first["status"], "complete")
            self.assertEqual(second["status"], "reused")

    def test_disabled_adapter_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = AdapterRunner(root / "adapter-state.json")
            with patch("director_adapters.subprocess.run") as run:
                result = runner.run(
                    name="optional", enabled=False, command=["python", "tool.py"],
                    inputs=[], outputs=[root / "out.json"], blocking=False,
                )
            self.assertEqual(result["status"], "disabled")
            run.assert_not_called()

    def test_success_is_hash_bound_and_reused_until_an_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.txt"
            tool = root / "tool.py"
            tool.write_text("# v1", encoding="utf-8")
            output = root / "out.json"
            source.write_text("one", encoding="utf-8")
            runner = AdapterRunner(root / "adapter-state.json")

            def fake_run(*_args, **_kwargs):
                output.write_text(json.dumps({"status": "pass"}), encoding="utf-8")

            with patch("director_adapters.subprocess.run", side_effect=fake_run) as run:
                first = runner.run(
                    name="fixture", enabled=True, command=["python", str(tool)],
                    inputs=[source], outputs=[output], blocking=True,
                )
                second = runner.run(
                    name="fixture", enabled=True, command=["python", str(tool)],
                    inputs=[source], outputs=[output], blocking=True,
                )
                source.write_text("two", encoding="utf-8")
                third = runner.run(
                    name="fixture", enabled=True, command=["python", str(tool)],
                    inputs=[source], outputs=[output], blocking=True,
                )

            self.assertEqual(first["status"], "complete")
            self.assertEqual(second["status"], "reused")
            self.assertEqual(third["status"], "complete")
            self.assertEqual(run.call_count, 2)

            tool.write_text("# v2", encoding="utf-8")
            with patch("director_adapters.subprocess.run", side_effect=fake_run) as changed:
                runner.run(
                    name="fixture", enabled=True, command=["python", str(tool)],
                    inputs=[source], outputs=[output], blocking=True,
                )
            self.assertEqual(changed.call_count, 1)

    def test_missing_output_uses_declared_failure_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = AdapterRunner(root / "adapter-state.json")
            with patch("director_adapters.subprocess.run"):
                with self.assertRaises(AdapterExecutionError):
                    runner.run(
                        name="required", enabled=True, command=["python", "tool.py"],
                        inputs=[], outputs=[root / "missing.json"], blocking=True,
                    )
                optional = runner.run(
                    name="optional", enabled=True, command=["python", "tool.py"],
                    inputs=[], outputs=[root / "still-missing.json"], blocking=False,
                )
            self.assertEqual(optional["status"], "unavailable")
            state = json.loads((root / "adapter-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["adapters"]["required"]["status"], "failed")

    def test_corrupt_non_object_state_has_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "adapter-state.json"
            state.write_text("[]", encoding="utf-8")
            with self.assertRaises(AdapterExecutionError):
                AdapterRunner(state)

    def test_two_runners_merge_capability_rows_instead_of_losing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "adapter-state.json"
            first = AdapterRunner(state)
            second = AdapterRunner(state)

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_text("ok", encoding="utf-8")

            with patch("director_adapters.subprocess.run", side_effect=fake_run):
                first.run(name="one", enabled=True, command=["tool", str(root / "one.out")],
                          inputs=[], outputs=[root / "one.out"], blocking=True)
                second.run(name="two", enabled=True, command=["tool", str(root / "two.out")],
                           inputs=[], outputs=[root / "two.out"], blocking=True)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(set(saved["adapters"]), {"one", "two"})

    def test_relative_implementation_path_is_hashed_from_adapter_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts"
            scripts.mkdir()
            tool = scripts / "tool.py"
            tool.write_text("# v1", encoding="utf-8")
            output = root / "out.json"
            runner = AdapterRunner(root / "state.json")

            def fake_run(*_args, **_kwargs):
                output.write_text("{}", encoding="utf-8")

            with patch("director_adapters.subprocess.run", side_effect=fake_run) as run:
                runner.run(name="relative", enabled=True,
                           command=[sys.executable, "scripts/tool.py"], inputs=[],
                           outputs=[output], blocking=True, cwd=root)
                runner.run(name="relative", enabled=True,
                           command=[sys.executable, "scripts/tool.py"], inputs=[],
                           outputs=[output], blocking=True, cwd=root)
                tool.write_text("# v2", encoding="utf-8")
                runner.run(name="relative", enabled=True,
                           command=[sys.executable, "scripts/tool.py"], inputs=[],
                           outputs=[output], blocking=True, cwd=root)
            self.assertEqual(run.call_count, 2)

    def test_same_adapter_execution_is_serialized_and_reused_across_runners(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tool = root / "tool.py"
            output = root / "out.json"
            log = root / "executions.log"
            tool.write_text(
                "import pathlib, sys, time\n"
                "with pathlib.Path(sys.argv[2]).open('a', encoding='utf-8') as h: h.write('run\\n')\n"
                "time.sleep(0.1)\n"
                "pathlib.Path(sys.argv[1]).write_text('{}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            state = root / "state.json"
            runners = [AdapterRunner(state), AdapterRunner(state)]
            barrier = threading.Barrier(2)

            def invoke(runner):
                barrier.wait()
                return runner.run(
                    name="shared", enabled=True,
                    command=[sys.executable, str(tool), str(output), str(log)],
                    inputs=[], outputs=[output], blocking=True, cwd=root,
                )["status"]

            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(invoke, runners))
            self.assertEqual(sorted(statuses), ["complete", "reused"])
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), ["run"])


if __name__ == "__main__":
    unittest.main()
