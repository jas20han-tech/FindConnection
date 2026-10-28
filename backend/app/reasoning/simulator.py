"""In-memory NetworkX cascade / node-severance simulator (target < 150 ms).

Nothing is written back to Neo4j: the graph is reconstructed from the cached
node/edge payload, mutated in memory, and the structural deltas are measured.
"""

from __future__ import annotations

import logging
import time

import networkx as nx

from app.schemas.graph import GraphEdge, GraphNode
from app.schemas.impact import (
    CentralitySurge,
    ImpactResult,
    OrphanedNode,
    SeveredEdge,
)

logger = logging.getLogger(__name__)


def _build_graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> nx.Graph:
    graph = nx.Graph()
    for node in nodes:
        graph.add_node(node.id, name=node.name, type=node.type)
    for edge in edges:
        if edge.status == "DISSOLVED":
            continue
        if edge.source in graph and edge.target in graph:
            graph.add_edge(edge.source, edge.target, weight=max(1, edge.strength), type=edge.type)
    return graph


def _betweenness(graph: nx.Graph) -> dict[str, float]:
    if graph.number_of_nodes() < 2 or graph.number_of_edges() == 0:
        return {node: 0.0 for node in graph.nodes}
    # Exact betweenness is fine for demo/medium graphs; sample on very large ones.
    k = None if graph.number_of_nodes() <= 700 else min(120, graph.number_of_nodes())
    try:
        return nx.betweenness_centrality(graph, k=k, weight="weight", normalized=True, seed=42)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Betweenness computation failed: %s", exc)
        return {node: 0.0 for node in graph.nodes}


def simulate_impact(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    node_id: str,
) -> ImpactResult:
    started = time.perf_counter()
    node_map = {node.id: node for node in nodes}
    target = node_map.get(node_id)
    if target is None:
        raise KeyError(f"Unknown entity: {node_id}")

    graph = _build_graph(nodes, edges)
    if node_id not in graph:
        raise KeyError(f"Entity {node_id} is not connected to the graph")

    baseline_betweenness = _betweenness(graph)
    baseline_components = nx.number_connected_components(graph)
    baseline_nodes = graph.number_of_nodes()

    direct_neighbours = list(graph.neighbors(node_id))
    severed_edges = [
        SeveredEdge(
            id=f"{edge.source}__{edge.type.lower()}__{edge.target}",
            source=node_map[edge.source].name if edge.source in node_map else edge.source,
            target=node_map[edge.target].name if edge.target in node_map else edge.target,
            type=edge.type,
        )
        for edge in edges
        if edge.status != "DISSOLVED" and node_id in (edge.source, edge.target)
    ]

    graph.remove_node(node_id)

    projected_betweenness = _betweenness(graph)
    components = list(nx.connected_components(graph))
    component_sizes = sorted((len(component) for component in components), reverse=True)
    total_after = max(1, graph.number_of_nodes())
    largest_ratio = (component_sizes[0] / total_after) if component_sizes else 1.0
    isolated_after = sum(1 for degree in dict(graph.degree()).values() if degree == 0)

    disruption_ratio = 1.0 - largest_ratio
    # Weight orphan creation and isolated nodes into overall risk.
    orphan_ratio = isolated_after / total_after
    risk_score = min(1.0, disruption_ratio * 0.7 + orphan_ratio * 0.3)

    if risk_score >= 0.55:
        severity = "CRITICAL"
    elif risk_score >= 0.3:
        severity = "HIGH"
    elif risk_score >= 0.12:
        severity = "MODERATE"
    else:
        severity = "LOW"

    orphaned: list[OrphanedNode] = []
    directly_disrupted: list[dict[str, str]] = []
    for neighbour in direct_neighbours:
        if neighbour not in graph:
            continue
        entity = node_map.get(neighbour)
        directly_disrupted.append(
            {
                "id": neighbour,
                "name": entity.name if entity else neighbour,
                "type": entity.type if entity else "UNKNOWN",
            }
        )
        if graph.degree(neighbour) == 0:
            orphaned.append(
                OrphanedNode(
                    id=neighbour,
                    name=entity.name if entity else neighbour,
                    type=entity.type if entity else "UNKNOWN",
                    previous_degree=1,
                )
            )

    surges: list[CentralitySurge] = []
    for candidate, projected in projected_betweenness.items():
        baseline = baseline_betweenness.get(candidate, 0.0)
        if projected <= baseline:
            continue
        if baseline > 0:
            delta_pct = ((projected - baseline) / baseline) * 100.0
        else:
            delta_pct = 100.0
        entity = node_map.get(candidate)
        surges.append(
            CentralitySurge(
                id=candidate,
                name=entity.name if entity else candidate,
                type=entity.type if entity else "UNKNOWN",
                baseline=round(baseline, 5),
                projected=round(projected, 5),
                delta_pct=round(delta_pct, 1),
            )
        )
    surges.sort(key=lambda item: item.delta_pct, reverse=True)

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return ImpactResult(
        removed_node={"id": target.id, "name": target.name, "type": target.type},
        severity=severity,
        risk_score=round(risk_score, 4),
        disruption_ratio=round(disruption_ratio, 4),
        component_count_before=baseline_components,
        component_count_after=len(components),
        largest_component_ratio_after=round(largest_ratio, 4),
        directly_disrupted=directly_disrupted,
        orphaned=orphaned,
        centrality_surge=surges[:6],
        severed_edges=severed_edges,
        duration_ms=duration_ms,
    )
