from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director import parser  # noqa: E402


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
            "import-metrics": ["import-metrics", "--project", "project.yaml",
                               "--input", "metrics.json"],
        }
        for expected, argv in cases.items():
            with self.subTest(command=expected):
                self.assertEqual(command_parser.parse_args(argv).command, expected)


if __name__ == "__main__":
    unittest.main()
