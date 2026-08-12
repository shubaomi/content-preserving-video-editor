from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capture_hyperframes_runtime_evidence import (  # noqa: E402
    compute_phase_times,
    measurement_overlay_distance_pixels,
    normalize_event_visible_text,
    resolve_browser_executable,
    select_target_observation,
)


class RuntimeScriptContractTests(unittest.TestCase):
    def test_measurement_uses_get_element_by_id_for_colon_event_ids(self) -> None:
        from capture_hyperframes_runtime_evidence import MEASURE_SCRIPT
        self.assertIn("document.getElementById(eventId)", MEASURE_SCRIPT)
        self.assertNotIn("querySelector(eventSelector)", MEASURE_SCRIPT)


class CaptureHyperFramesRuntimeEvidenceTests(unittest.TestCase):
    def test_scene_bounded_event_uses_verified_target_window(self) -> None:
        opportunity = {
            "output_window": {"start_seconds": 1.0, "end_seconds": 4.0},
        }
        binding = {
            "active_windows": [{"start_seconds": 1.0, "end_seconds": 2.0}],
        }

        phases = compute_phase_times(opportunity, [binding], fps=30)

        self.assertEqual(phases, {
            "entrance": 1.25,
            "mid": 1.5,
            "pre_exit": 1.8,
            "post_exit": 2.033333,
        })

    def test_targetless_event_uses_semantic_output_window(self) -> None:
        phases = compute_phase_times({
            "output_window": {"start_seconds": 10.0, "end_seconds": 20.0},
        }, [], fps=25)

        self.assertEqual(phases, {
            "entrance": 12.5,
            "mid": 15.0,
            "pre_exit": 18.0,
            "post_exit": 20.04,
        })

    def test_visible_text_is_ordered_unique_across_runtime_phases(self) -> None:
        self.assertEqual(
            normalize_event_visible_text([
                ["趋势：看变化"],
                ["趋势：看变化", "多指标：看关系"],
                ["多指标：看关系"],
                [],
            ]),
            ["趋势：看变化", "多指标：看关系"],
        )

    def test_target_observation_uses_latest_visible_state_at_or_before_phase(self) -> None:
        binding = {
            "observations": [
                {"timestamp_seconds": 1.0, "visible": True, "target_id": "tile", "bbox": {"x": .1}},
                {"timestamp_seconds": 2.0, "visible": True, "target_id": "tile", "bbox": {"x": .2}},
                {"timestamp_seconds": 3.0, "visible": False, "target_id": "tile"},
            ],
        }

        self.assertEqual(select_target_observation(binding, 2.5)["bbox"]["x"], .2)
        self.assertEqual(select_target_observation(binding, .5)["bbox"]["x"], .1)
        self.assertIsNone(select_target_observation(binding, 3.1))

    def test_target_distance_compares_normalized_edge_geometry_in_pixels(self) -> None:
        distance = measurement_overlay_distance_pixels(
            {"x": .1, "y": .2, "width": .2, "height": .1},
            {"x": .11, "y": .19, "width": .18, "height": .12},
            width=1000,
            height=500,
        )

        self.assertEqual(distance, 10.0)

    def test_existing_playwright_chromium_is_used_when_headless_shell_is_absent(self) -> None:
        bundled = ROOT / "tests" / "fake-chrome.exe"
        bundled.write_bytes(b"browser")
        self.addCleanup(bundled.unlink)

        self.assertEqual(resolve_browser_executable(None, bundled), bundled.resolve())

    def test_hyperframes_browser_path_is_used_when_playwright_browser_is_missing(self) -> None:
        hyperframes_browser = ROOT / "tests" / "fake-hyperframes-chrome.exe"
        hyperframes_browser.write_bytes(b"browser")
        self.addCleanup(hyperframes_browser.unlink)
        calls: list[list[str]] = []

        def runner(command):
            calls.append(list(command))
            return 0, str(hyperframes_browser), ""

        resolved = resolve_browser_executable(
            None,
            ROOT / "tests" / "missing-playwright-chrome.exe",
            runner=runner,
        )

        self.assertEqual(resolved, hyperframes_browser.resolve())
        self.assertEqual(calls, [["npx", "hyperframes", "browser", "path"]])

    def test_default_browser_command_resolves_windows_cmd_shim(self) -> None:
        hyperframes_browser = ROOT / "tests" / "fake-hyperframes-chrome.exe"
        hyperframes_browser.write_bytes(b"browser")
        self.addCleanup(hyperframes_browser.unlink)

        with (
            patch(
                "capture_hyperframes_runtime_evidence.shutil.which",
                return_value="C:/tools/npx.CMD",
            ),
            patch(
                "capture_hyperframes_runtime_evidence.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=str(hyperframes_browser),
                    stderr="",
                ),
            ) as run,
        ):
            resolved = resolve_browser_executable(
                None,
                ROOT / "tests" / "missing-playwright-chrome.exe",
            )

        self.assertEqual(resolved, hyperframes_browser.resolve())
        self.assertEqual(run.call_args.args[0][0], "C:/tools/npx.CMD")


if __name__ == "__main__":
    unittest.main()
