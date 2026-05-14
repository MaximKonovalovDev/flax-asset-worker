"""recipe_graph — build adjacency map from recipe.related_recipes fields.

Adds in v1.59.s283 (BIG-SLICE).

Each recipe id maps to a set of ids it points TO (outgoing edges).
The inverse direction (incoming edges) and orphan/dangling detection
are derived from the same scan.

Tolerant of:
- malformed YAML files (skipped silently; can't ID -> can't relate)
- non-string entries in related_recipes (filtered out)
- recipes without related_recipes (empty out-edge set)

This is purely a static analysis pass; no recipe execution required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]


@dataclass
class RecipeGraph:
    """Recipe relation graph.

    Attributes:
        out_edges: maps recipe_id -> set of ids it points TO via related_recipes.
        in_edges:  maps recipe_id -> set of ids that point TO it.
        all_ids:   set of recipe ids actually loaded (the universe).
        dangling:  maps recipe_id -> set of ids it points to that DO NOT
                   exist in all_ids (broken references).
        orphans:   set of recipe ids with both empty out_edges AND empty
                   in_edges (completely disconnected from the graph).
    """

    out_edges: dict[str, set[str]] = field(default_factory=dict)
    in_edges: dict[str, set[str]] = field(default_factory=dict)
    all_ids: set[str] = field(default_factory=set)
    dangling: dict[str, set[str]] = field(default_factory=dict)
    orphans: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly serialization (sets -> sorted lists)."""
        topo = self.topological_sort()
        return {
            "out_edges": {k: sorted(v) for k, v in self.out_edges.items()},
            "in_edges": {k: sorted(v) for k, v in self.in_edges.items()},
            "all_ids": sorted(self.all_ids),
            "dangling": {k: sorted(v) for k, v in self.dangling.items()},
            "orphans": sorted(self.orphans),
            "total_recipes": len(self.all_ids),
            "total_edges": sum(len(v) for v in self.out_edges.values()),
            "dangling_count": sum(len(v) for v in self.dangling.values()),
            "orphan_count": len(self.orphans),
            # v1.60.s285 — cycle detection + topo order.
            "is_acyclic": topo is not None,
            "topo_order": topo,  # None if cycle exists
        }

    def descendants(self, rid: str) -> set[str]:
        """v1.59.s284: transitive closure of out_edges from `rid` (BFS).

        Returns the set of all ids reachable by walking out_edges.
        Does NOT include `rid` itself. Cycles handled by visited-set.
        Returns empty set when `rid` is not in the graph.
        """
        if rid not in self.all_ids:
            return set()
        visited: set[str] = set()
        stack = list(self.out_edges.get(rid, set()))
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(self.out_edges.get(node, set()))
        return visited

    def ancestors(self, rid: str) -> set[str]:
        """v1.59.s284: transitive closure of in_edges to `rid` (BFS).

        Returns the set of all ids that can reach `rid` via out_edges.
        Does NOT include `rid` itself. Cycles handled by visited-set.
        Returns empty set when `rid` is not in the graph.
        """
        if rid not in self.all_ids:
            return set()
        visited: set[str] = set()
        stack = list(self.in_edges.get(rid, set()))
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(self.in_edges.get(node, set()))
        return visited

    def is_acyclic(self) -> bool:
        """v1.60.s285: True when no cycle exists in out_edges (DFS coloring).

        Uses 3-color DFS: WHITE (unvisited), GRAY (on current DFS stack),
        BLACK (fully processed). Encountering a GRAY node means a back-edge,
        which closes a cycle.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {rid: WHITE for rid in self.all_ids}

        def _visit(node: str) -> bool:
            if color[node] == GRAY:
                return False  # back-edge -> cycle
            if color[node] == BLACK:
                return True
            color[node] = GRAY
            for neighbor in self.out_edges.get(node, set()):
                if neighbor not in color:
                    # Dangling target — skip (treated as exiting the graph).
                    continue
                if not _visit(neighbor):
                    return False
            color[node] = BLACK
            return True

        for rid in self.all_ids:
            if color[rid] == WHITE:
                if not _visit(rid):
                    return False
        return True

    def topological_sort(self) -> list[str] | None:
        """v1.60.s285: return ids in topological order, or None on cycle.

        Uses Kahn's algorithm (in-degree decrement). Tie-broken
        alphabetically for reproducible output. Returns None if a cycle
        exists (graph is not a DAG).
        """
        if not self.is_acyclic():
            return None
        # Copy in-degrees (excluding dangling edges, which don't count
        # because dangling targets aren't in all_ids).
        in_deg: dict[str, int] = {
            rid: len(self.in_edges.get(rid, set())) for rid in self.all_ids
        }
        # Initial frontier: zero in-degree nodes, alphabetical.
        from collections import deque
        ready = deque(sorted(rid for rid, d in in_deg.items() if d == 0))
        order: list[str] = []
        while ready:
            node = ready.popleft()
            order.append(node)
            # Decrement in-deg of out-neighbors; sort new-ready alphabetically.
            new_ready = []
            for neighbor in sorted(self.out_edges.get(node, set())):
                if neighbor not in in_deg:
                    continue
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    new_ready.append(neighbor)
            ready.extend(sorted(new_ready))
        if len(order) != len(self.all_ids):
            return None  # defensive — shouldn't hit after is_acyclic check
        return order


def _safe_recipe_id(doc: dict | None) -> str | None:
    """Extract recipe.id; tolerant of missing/malformed docs."""
    if not isinstance(doc, dict):
        return None
    recipe = doc.get("recipe")
    if not isinstance(recipe, dict):
        return None
    rid = recipe.get("id")
    if not isinstance(rid, str) or not rid.strip():
        return None
    return rid.strip()


def _safe_related(doc: dict | None) -> list[str]:
    """Extract recipe.related_recipes as a list[str]; filter non-strings."""
    if not isinstance(doc, dict):
        return []
    recipe = doc.get("recipe")
    if not isinstance(recipe, dict):
        return []
    rr = recipe.get("related_recipes")
    if not isinstance(rr, list):
        return []
    return [x.strip() for x in rr if isinstance(x, str) and x.strip()]


def build_graph(recipes_root: Path) -> RecipeGraph:
    """Walk recipes_root/**/*.yaml; build adjacency map.

    Args:
        recipes_root: directory containing <game>/<recipe>.yaml files.

    Returns:
        RecipeGraph with out_edges, in_edges, all_ids, dangling, orphans
        all populated. Silent on parse errors.
    """
    graph = RecipeGraph()
    if _yaml is None:  # pragma: no cover
        return graph
    if not recipes_root.exists() or not recipes_root.is_dir():
        return graph

    # Pass 1: collect ids + outgoing edges.
    docs: dict[str, list[str]] = {}
    for yml in recipes_root.rglob("*.yaml"):
        try:
            doc = _yaml.safe_load(yml.read_text(encoding="utf-8"))
        except Exception:
            continue
        rid = _safe_recipe_id(doc)
        if rid is None:
            continue
        docs[rid] = _safe_related(doc)
        graph.all_ids.add(rid)

    # Pass 2: build edges, detect dangling + orphans.
    for rid, targets in docs.items():
        graph.out_edges.setdefault(rid, set())
        targets_clean: set[str] = set()
        dangling_set: set[str] = set()
        for tgt in targets:
            if tgt in graph.all_ids:
                targets_clean.add(tgt)
                graph.in_edges.setdefault(tgt, set()).add(rid)
            else:
                dangling_set.add(tgt)
        graph.out_edges[rid] = targets_clean
        if dangling_set:
            graph.dangling[rid] = dangling_set

    # Ensure in_edges has an entry for every id (even if empty).
    for rid in graph.all_ids:
        graph.in_edges.setdefault(rid, set())

    # Orphans: ids with no out AND no in edges.
    for rid in graph.all_ids:
        if (not graph.out_edges.get(rid)
                and not graph.in_edges.get(rid)
                and not graph.dangling.get(rid)):
            graph.orphans.add(rid)

    return graph


__all__ = [
    "RecipeGraph",
    "build_graph",
]
