#!/usr/bin/env python3
"""Small deterministic dependency graph used for precise workflow invalidation."""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable


class DependencyGraphError(ValueError):
    """Raised when a dependency declaration is unsafe or ambiguous."""


class DependencyGraph:
    def __init__(self, nodes: Iterable[dict[str, Any]]) -> None:
        self._order: list[str] = []
        self._dependencies: dict[str, tuple[str, ...]] = {}
        for node in nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                raise DependencyGraphError("dependency node requires a non-empty id")
            if node_id in self._dependencies:
                raise DependencyGraphError(f"duplicate dependency node id: {node_id}")
            dependencies = tuple(str(value).strip() for value in node.get("depends_on", []))
            if any(not value for value in dependencies):
                raise DependencyGraphError(f"node {node_id} has an empty dependency")
            if len(set(dependencies)) != len(dependencies):
                raise DependencyGraphError(f"node {node_id} repeats a dependency")
            if node_id in dependencies:
                raise DependencyGraphError(f"node {node_id} depends on itself")
            self._order.append(node_id)
            self._dependencies[node_id] = dependencies

        declared = set(self._dependencies)
        for node_id, dependencies in self._dependencies.items():
            unknown = [value for value in dependencies if value not in declared]
            if unknown:
                raise DependencyGraphError(
                    f"node {node_id} has unknown dependencies: {', '.join(unknown)}"
                )
        self._topological = self._build_topological_order()

    def _build_topological_order(self) -> list[str]:
        indegree = {node_id: len(values) for node_id, values in self._dependencies.items()}
        dependents = {node_id: [] for node_id in self._order}
        for node_id, dependencies in self._dependencies.items():
            for dependency in dependencies:
                dependents[dependency].append(node_id)
        ready = deque(node_id for node_id in self._order if indegree[node_id] == 0)
        result: list[str] = []
        while ready:
            node_id = ready.popleft()
            result.append(node_id)
            for dependent in dependents[node_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if len(result) != len(self._order):
            cyclic = [node_id for node_id in self._order if indegree[node_id] > 0]
            raise DependencyGraphError(f"dependency graph contains a cycle: {', '.join(cyclic)}")
        return result

    def topological_order(self) -> list[str]:
        return list(self._topological)

    def invalidated_by(self, changed: set[str]) -> set[str]:
        unknown = changed - set(self._dependencies)
        if unknown:
            raise DependencyGraphError(f"cannot invalidate unknown nodes: {', '.join(sorted(unknown))}")
        invalidated = set(changed)
        for node_id in self._topological:
            if any(dependency in invalidated for dependency in self._dependencies[node_id]):
                invalidated.add(node_id)
        return invalidated
