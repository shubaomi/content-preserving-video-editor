from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "video_project.py"
SPEC = importlib.util.spec_from_file_location("video_project", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class VideoProjectTests(unittest.TestCase):
    def test_init_uses_advisory_motion_and_sfx_ceilings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.mp4"
            source.write_bytes(b"fixture")
            args = argparse.Namespace(
                root=str(base / "videos"),
                video_id="example",
                source=str(source),
                profile=None,
                title=None,
                mode="preserve",
                dry_run=False,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(MODULE.init_project(args), 0)
            project_file = base / "videos" / "example" / "project.yaml"
            project = MODULE.load_yaml(project_file)
            self.assertEqual(project["editable_motion"]["event_rate_policy"], "advisory_ceiling")
            self.assertEqual(project["editable_motion"]["recommended_events_per_minute"]["screen_tutorial"], [4, 10])
            self.assertNotIn("density_targets", project["editable_motion"])
            self.assertEqual(project["audio"]["sfx"]["max_event_ratio"], 1.0)
            self.assertEqual(project["audio"]["sfx"]["target_event_coverage"], 1.0)
            self.assertNotIn("min_cues_per_minute", project["audio"]["sfx"])
            self.assertTrue(project["cover"]["editorial"]["enabled"])
            self.assertEqual(project["cover"]["editorial"]["mode"], "auto")
            self.assertEqual(MODULE.validate_project(project_file), [])


if __name__ == "__main__":
    unittest.main()
