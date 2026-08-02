from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dependency_graph import DependencyGraph, DependencyGraphError  # noqa: E402


class DependencyGraphTests(unittest.TestCase):
    def test_rejects_unknown_dependency_duplicate_id_self_dependency_and_cycle(self) -> None:
        invalid = (
            [{"id": "a", "depends_on": ["missing"]}],
            [{"id": "a"}, {"id": "a"}],
            [{"id": "a", "depends_on": ["a"]}],
            [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}],
        )
        for nodes in invalid:
            with self.subTest(nodes=nodes), self.assertRaises(DependencyGraphError):
                DependencyGraph(nodes)

    def test_unrelated_branch_survives_dependency_invalidation(self) -> None:
        graph = DependencyGraph([
            {"id": "semantic-a"},
            {"id": "motion-a", "depends_on": ["semantic-a"]},
            {"id": "semantic-b"},
            {"id": "motion-b", "depends_on": ["semantic-b"]},
            {"id": "compose", "depends_on": ["motion-a", "motion-b"]},
        ])
        self.assertEqual(
            graph.invalidated_by({"semantic-a"}),
            {"semantic-a", "motion-a", "compose"},
        )
        self.assertNotIn("motion-b", graph.invalidated_by({"semantic-a"}))

    def test_topological_order_is_stable(self) -> None:
        graph = DependencyGraph([
            {"id": "b"},
            {"id": "a"},
            {"id": "c", "depends_on": ["a", "b"]},
        ])
        self.assertEqual(graph.topological_order(), ["b", "a", "c"])


if __name__ == "__main__":
    unittest.main()
