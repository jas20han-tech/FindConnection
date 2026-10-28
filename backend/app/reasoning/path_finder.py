"""Multi-hop path traversal (BFS over the active relationship graph)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.schemas.graph import GraphEdge, GraphNode


@dataclass(slots=True)
class PathResult:
    found: bool
    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    hops: int = 0
    explanation: str = ""

    @property
    def length(self) -> int:
        return len(self.node_ids)


def build_adjacency(edges: list[GraphEdge]) -> dict[str, list[tuple[str, GraphEdge]]]:
    adjacency: dict[str, list[tuple[str, GraphEdge]]] = {}
    for edge in edges:
        if edge.status == "DISSOLVED":
            continue
        adjacency.setdefault(edge.source, []).append((edge.target, edge))
        adjacency.setdefault(edge.target, []).append((edge.source, edge))
    return adjacency


def shortest_path(
    edges: list[GraphEdge],
    source_id: str,
    target_id: str,
    *,
    max_hops: int = 5,
    max_year: int | None = None,
) -> PathResult:
    if source_id == target_id:
        return PathResult(found=True, node_ids=[source_id], edge_ids=[], hops=0)

    adjacency = build_adjacency(edges)
    queue: deque[tuple[str, list[str], list[str]]] = deque([(source_id, [source_id], [])])
    visited = {source_id}

    while queue:
        current, node_path, edge_path = queue.popleft()
        if len(edge_path) >= max_hops:
            continue
        for neighbour, edge in adjacency.get(current, []):
            if max_year is not None and edge.year is not None and edge.year > max_year:
                continue
            if neighbour in visited:
                continue
            next_nodes = [*node_path, neighbour]
            next_edges = [*edge_path, edge.id]
            if neighbour == target_id:
                return PathResult(
                    found=True,
                    node_ids=next_nodes,
                    edge_ids=next_edges,
                    hops=len(next_edges),
                    explanation=f"Shortest reasoning route found in {len(next_edges)} hop(s)",
                )
            visited.add(neighbour)
            queue.append((neighbour, next_nodes, next_edges))

    return PathResult(
        found=False,
        explanation=f"No path within {max_hops} hop(s) — consider expanding the time range",
    )


def all_simple_paths(
    edges: list[GraphEdge],
    source_id: str,
    target_id: str,
    *,
    max_hops: int = 4,
    limit: int = 5,
) -> list[PathResult]:
    """Enumerate a handful of alternative routes (DFS, bounded)."""
    adjacency = build_adjacency(edges)
    results: list[PathResult] = []

    def walk(current: str, node_path: list[str], edge_path: list[str]) -> None:
        if len(results) >= limit or len(edge_path) >= max_hops:
            return
        for neighbour, edge in adjacency.get(current, []):
            if neighbour in node_path:
                continue
            next_nodes = [*node_path, neighbour]
            next_edges = [*edge_path, edge.id]
            if neighbour == target_id:
                results.append(
                    PathResult(
                        found=True,
                        node_ids=next_nodes,
                        edge_ids=next_edges,
                        hops=len(next_edges),
                    )
                )
                if len(results) >= limit:
                    return
            else:
                walk(neighbour, next_nodes, next_edges)

    walk(source_id, [source_id], [])
    return results


def describe_path(path: PathResult, node_map: dict[str, GraphNode], edge_map: dict[str, GraphEdge]) -> str:
    if not path.found:
        return path.explanation
    segments: list[str] = []
    for index, edge_id in enumerate(path.edge_ids):
        edge = edge_map.get(edge_id)
        source = node_map.get(path.node_ids[index])
        target = node_map.get(path.node_ids[index + 1])
        if not edge or not source or not target:
            continue
        segments.append(
            f"{source.name} --[{edge.type}{f' {edge.year}' if edge.year else ''}]--> {target.name}"
        )
    return " → ".join(segments) if segments else path.explanation
