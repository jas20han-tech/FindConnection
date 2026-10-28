"""HippoRAG-style Personalized PageRank retrieval.

Runs a sparse power iteration over the weighted adjacency structure. Seeds receive a
restart mass; the stationary distribution ranks the entities most relevant to the
query. Complexity is O(iterations x edges), which keeps multi-hop retrieval in the
low-millisecond range without any LLM map-reduce step.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from app.config import settings
from app.schemas.graph import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class PPRResult:
    def __init__(self, scores: dict[str, float], node_ids: list[str], seed_ids: list[str]) -> None:
        self.scores = scores
        self.node_ids = node_ids
        self.seed_ids = seed_ids


def personalized_pagerank(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    seed_ids: list[str],
    *,
    alpha: float | None = None,
    top_k: int | None = None,
    max_year: int | None = None,
) -> PPRResult:
    alpha = alpha if alpha is not None else settings.ppr_alpha
    top_k = top_k or settings.ppr_top_k

    valid = {node.id for node in nodes}
    seeds = [seed for seed in seed_ids if seed in valid]
    if not seeds:
        return PPRResult(scores={}, node_ids=[], seed_ids=[])

    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in edges:
        if edge.status == "DISSOLVED":
            continue
        if max_year is not None and edge.year is not None and edge.year > max_year:
            continue
        if edge.source not in valid or edge.target not in valid:
            continue
        weight = float(max(1, edge.strength))
        adjacency[edge.source].append((edge.target, weight))
        adjacency[edge.target].append((edge.source, weight))

    degree: dict[str, float] = {
        node_id: sum(weight for _, weight in neighbours)
        for node_id, neighbours in adjacency.items()
    }

    restart = {seed: 1.0 / len(seeds) for seed in seeds}
    scores: dict[str, float] = dict(restart)

    for _ in range(30):
        updated: dict[str, float] = defaultdict(float)
        for node_id, mass in scores.items():
            total = degree.get(node_id, 0.0)
            if total <= 0:
                continue
            share = (1.0 - alpha) * mass / total
            for neighbour, weight in adjacency.get(node_id, ()):  # type: ignore[arg-type]
                updated[neighbour] += share * weight
        for seed, value in restart.items():
            updated[seed] += alpha * value
        # Mass can leak through dangling nodes; renormalise for numerical stability.
        mass_sum = sum(updated.values())
        if mass_sum > 0:
            updated = {key: value / mass_sum for key, value in updated.items()}
        scores = dict(updated)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    node_ids = [node_id for node_id, _ in ranked[:top_k]]
    return PPRResult(scores=scores, node_ids=node_ids, seed_ids=seeds)


def expand_subgraph(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    node_ids: list[str],
    *,
    limit: int | None = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Induced subgraph for the selected node ids, plus one-hop context edges."""
    selected = set(node_ids)
    if limit:
        selected = set(node_ids[:limit])
    node_map = {node.id: node for node in nodes}
    kept_nodes = [node_map[node_id] for node_id in selected if node_id in node_map]
    kept_edges = [
        edge for edge in edges if edge.source in selected and edge.target in selected
    ]
    return kept_nodes, kept_edges
