"""Community overviews (Louvain clusters + deterministic summaries).

The graph-store side computes community assignments (Neo4j/GDS or NetworkX Louvain).
This module turns those memberships into compact, human-readable summaries used by
global queries. An LLM enrichment hook is provided but not required.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any

from app.core import llm
from app.schemas.graph import Community, GraphEdge, GraphNode


def community_overview(
    nodes: list[GraphNode], edges: list[GraphEdge], communities: list[Community]
) -> list[dict[str, Any]]:
    members: dict[int, list[GraphNode]] = defaultdict(list)
    for node in nodes:
        members[node.community_id].append(node)

    edge_counts: Counter[int] = Counter()
    boundary: Counter[int] = Counter()
    for edge in edges:
        source = next((node for node in nodes if node.id == edge.source), None)
        target = next((node for node in nodes if node.id == edge.target), None)
        if not source or not target:
            continue
        if source.community_id == target.community_id:
            edge_counts[source.community_id] += 1
        else:
            boundary[source.community_id] += 1
            boundary[target.community_id] += 1

    palette = {community.id: community for community in communities}
    overview: list[dict[str, Any]] = []
    for community_id, group in sorted(members.items(), key=lambda item: len(item[1]), reverse=True):
        if not group:
            continue
        hubs = sorted(group, key=lambda node: (node.pagerank, node.degree), reverse=True)[:4]
        types = Counter(node.type for node in group)
        label = palette[community_id].name if community_id in palette else f"Community {community_id + 1}"
        type_phrase = ", ".join(f"{count} {name.lower()}" for name, count in types.most_common(3))
        overview.append(
            {
                "id": community_id,
                "name": label,
                "color": palette[community_id].color if community_id in palette else "#64748B",
                "size": len(group),
                "type_mix": type_phrase,
                "internal_edges": edge_counts.get(community_id, 0),
                "boundary_edges": boundary.get(community_id, 0),
                "hubs": [node.name for node in hubs],
                "summary": (
                    f"{label} contains {len(group)} entities ({type_phrase}), anchored by "
                    f"{', '.join(node.name for node in hubs[:3])}, with "
                    f"{edge_counts.get(community_id, 0)} internal and "
                    f"{boundary.get(community_id, 0)} boundary relationship(s)."
                ),
            }
        )
    return overview


async def summarize_with_llm(overview: list[dict[str, Any]], query: str) -> str | None:
    if not llm.is_enabled() or not overview:
        return None
    compact = "\n".join(item["summary"] for item in overview)
    try:
        chunks: list[str] = []
        async for token in llm.stream_chat(
            system_prompt=(
                "You are a graph intelligence analyst. Write a concise, factual brief using "
                "only the supplied community summaries. No bullet points longer than one line."
            ),
            user_prompt=f"User question: {query}\n\nCommunities:\n{compact}",
            max_tokens=500,
        ):
            chunks.append(token)
        return "".join(chunks)
    except Exception:
        return None


def bfs_neighbourhood(edges: list[GraphEdge], start: str, hops: int = 2) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.status == "DISSOLVED":
            continue
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    seen = {start}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= hops:
            continue
        for neighbour in adjacency.get(current, set()):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, depth + 1))
    return seen
