"""Graph persistence layer.

Two interchangeable implementations:

* ``InMemoryGraphRepository`` – seeded, zero-dependency store used by demo mode and tests.
* ``Neo4jGraphRepository``    – production store with startup constraints and batch UNWIND writes.

Both expose the same async interface, so the API, reasoning engine and simulator are
agnostic to where the graph physically lives.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import networkx as nx

from app.config import settings
from app.schemas.graph import (
    Community,
    EntitySearchResult,
    GraphEdge,
    GraphNode,
    GraphStats,
    GraphViewport,
    NeighborResponse,
    TemporalSlice,
)
from app.schemas.types import EntityType

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEED_PATH = DATA_DIR / "seed_graph.json"

COMMUNITY_PALETTE = [
    "#3B82F6",
    "#10B981",
    "#A855F7",
    "#F59E0B",
    "#EC4899",
    "#06B6D4",
    "#F43F5E",
    "#8B5CF6",
]

VALID_TYPES: set[str] = {
    "PERSON",
    "COMPANY",
    "PRODUCT",
    "TECHNOLOGY",
    "LOCATION",
    "REGULATION",
    "EVENT",
    "ORGANIZATION",
}


def load_seed() -> dict[str, Any]:
    with SEED_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or uuid.uuid4().hex[:12]


def year_of(date: str | None) -> int | None:
    if not date:
        return None
    match = re.match(r"^(\d{4})", str(date))
    return int(match.group(1)) if match else None


def clean_type(value: str | None) -> EntityType:
    candidate = (value or "ORGANIZATION").upper().strip()
    return candidate if candidate in VALID_TYPES else "ORGANIZATION"  # type: ignore[return-value]


class GraphRepository(ABC):
    """Common graph storage contract."""

    source: str = "abstract"

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def get_viewport(self, limit: int | None = None) -> GraphViewport: ...

    @abstractmethod
    async def get_all(self) -> tuple[list[GraphNode], list[GraphEdge]]: ...

    @abstractmethod
    async def get_node(self, node_id: str) -> GraphNode | None: ...

    @abstractmethod
    async def get_neighbors(self, node_id: str, hops: int = 1) -> NeighborResponse: ...

    @abstractmethod
    async def search_entities(self, query: str, limit: int = 8) -> list[EntitySearchResult]: ...

    @abstractmethod
    async def get_temporal_slice(self, year: int) -> TemporalSlice: ...

    @abstractmethod
    async def upsert_graph(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        *,
        source_doc: str,
        source_chunk_id: str,
        source_page: int | None = None,
    ) -> dict[str, int]: ...

    @abstractmethod
    async def refresh_analytics(self) -> None: ...

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...

    async def stats(self) -> GraphStats:
        viewport = await self.get_viewport()
        return viewport.stats


class InMemoryGraphRepository(GraphRepository):
    source = "memory"

    def __init__(
        self,
        seed: bool = True,
        *,
        persist: bool | None = None,
        snapshot_path: Path | None = None,
    ) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._communities: dict[int, Community] = {}
        # Every ingested document is tracked, even when it only repeats entities and
        # adds no relationships — otherwise it silently disappears from the count.
        self._documents: set[str] = set()
        # Each upload replaces the previous one: the first write for a new
        # source_doc clears the graph so only that document's graph remains.
        self._active_document: str | None = None
        self._lock = asyncio.Lock()
        self._save_lock = asyncio.Lock()
        self._seed = seed
        self._persist = settings.graph_persist if persist is None else persist
        self._snapshot_path = snapshot_path or settings.graph_snapshot_file

    async def initialize(self) -> None:
        # A runtime snapshot (from a previous ingest) always wins over the seed so
        # uploaded documents survive a backend restart.
        if self._persist and await self._load_snapshot():
            logger.info(
                "Restored runtime graph: %d nodes, %d edges, %d communities",
                len(self._nodes),
                len(self._edges),
                len(self._communities),
            )
            return
        if not self._seed:
            return
        payload = load_seed()
        for community in payload.get("communities", []):
            model = Community(**community)
            self._communities[model.id] = model
        for raw in payload.get("nodes", []):
            node = self._node_from_raw(raw)
            self._nodes[node.id] = node
        for raw in payload.get("edges", []):
            edge = self._edge_from_raw(raw)
            if edge.source in self._nodes and edge.target in self._nodes:
                self._edges[edge.id] = edge
        self._documents = {
            edge.source_doc for edge in self._edges.values() if edge.source_doc
        }
        self._active_document = None
        self._attach_source_documents()
        await self.refresh_analytics()
        logger.info(
            "Loaded demo graph: %d nodes, %d edges, %d communities",
            len(self._nodes),
            len(self._edges),
            len(self._communities),
        )

    async def close(self) -> None:
        return None

    # ------------------------------------------------------------------ persistence
    async def _load_snapshot(self) -> bool:
        path = self._snapshot_path
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            nodes = [GraphNode.model_validate(raw) for raw in payload.get("nodes", [])]
            # An empty node list is valid when a document was ingested but produced
            # no entities; only a snapshot with no document context is unusable.
            if not nodes and not payload.get("documents") and not payload.get("active_document"):
                return False
            edges = [GraphEdge.model_validate(raw) for raw in payload.get("edges", [])]
            communities = [Community.model_validate(raw) for raw in payload.get("communities", [])]
        except Exception as exc:
            logger.warning("Ignoring unreadable graph snapshot %s: %s", path, exc)
            return False

        self._nodes = {node.id: node for node in nodes}
        self._edges = {
            edge.id: edge
            for edge in edges
            if edge.source in self._nodes and edge.target in self._nodes
        }
        self._communities = {community.id: community for community in communities}
        stored_documents = payload.get("documents") or []
        self._documents = set(stored_documents) or {
            edge.source_doc for edge in self._edges.values() if edge.source_doc
        }
        self._active_document = payload.get("active_document")
        self._attach_source_documents()
        return True

    async def save_snapshot(self) -> None:
        """Atomically persist the live graph so restarts don't drop ingested documents."""
        if not self._persist:
            return
        payload = {
            "version": 1,
            "saved_at": datetime.now(UTC).isoformat(),
            "nodes": [node.model_dump(mode="json") for node in self._nodes.values()],
            "edges": [edge.model_dump(mode="json") for edge in self._edges.values()],
            "documents": sorted(self._documents),
            "active_document": self._active_document,
            "communities": [
                community.model_dump(mode="json") for community in self._communities.values()
            ],
        }
        path = self._snapshot_path

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)

        async with self._save_lock:
            try:
                await asyncio.to_thread(write)
            except Exception as exc:  # pragma: no cover - disk dependent
                logger.warning("Could not persist graph snapshot: %s", exc)

    async def reset_to_seed(self) -> None:
        """Drop the runtime snapshot and reload the bundled demo graph."""
        self._nodes.clear()
        self._edges.clear()
        self._communities.clear()
        self._documents.clear()
        self._active_document = None
        self._seed = True
        if self._snapshot_path.exists():
            self._snapshot_path.unlink(missing_ok=True)
        await self.initialize()

    async def reset_for_document(self, source_doc: str) -> None:
        """Clear the previous document's graph before a new one is ingested.

        Each upload owns the canvas: the previous file's nodes, edges, communities
        and document names are dropped so only the newest document's graph remains.
        """
        async with self._lock:
            if self._nodes and source_doc == self._active_document:
                return
            self._nodes.clear()
            self._edges.clear()
            self._communities.clear()
            self._documents.clear()
            self._active_document = source_doc

    # ------------------------------------------------------------------ helpers
    def _attach_source_documents(self) -> None:
        """Tag nodes with the documents that mention them (derived from their edges)."""
        for edge in self._edges.values():
            if not edge.source_doc:
                continue
            for node_id in (edge.source, edge.target):
                node = self._nodes.get(node_id)
                if node is not None and edge.source_doc not in node.documents:
                    node.documents.append(edge.source_doc)

    @staticmethod
    def _node_from_raw(raw: dict[str, Any]) -> GraphNode:
        return GraphNode(
            id=raw.get("id") or slugify(raw["name"]),
            name=raw["name"],
            type=clean_type(raw.get("type")),
            description=raw.get("description", ""),
            community_id=int(raw.get("community_id", 0)),
            mention_count=int(raw.get("mention_count", 1)),
            pagerank=float(raw.get("pagerank", 0.0)),
            betweenness=float(raw.get("betweenness", 0.0)),
            degree=int(raw.get("degree", 0)),
            year=raw.get("year") or year_of(raw.get("date")),
            aliases=list(raw.get("aliases") or []),
            documents=list(raw.get("documents") or []),
        )

    @staticmethod
    def _edge_from_raw(raw: dict[str, Any]) -> GraphEdge:
        return GraphEdge(
            id=raw.get("id")
            or f"{raw['source']}__{raw.get('type', 'RELATED_TO')}__{raw['target']}".lower(),
            source=raw["source"],
            target=raw["target"],
            type=(raw.get("type") or "RELATED_TO").upper(),
            description=raw.get("description", ""),
            strength=int(raw.get("strength", 5)),
            date=raw.get("date"),
            date_confidence=raw.get("date_confidence", "unknown"),
            source_doc=raw.get("source_doc"),
            source_chunk_id=raw.get("source_chunk_id"),
            source_page=raw.get("source_page"),
            status=raw.get("status", "ACTIVE"),
            year=raw.get("year") or year_of(raw.get("date")),
        )

    def _to_graph(self, edges: Iterable[GraphEdge] | None = None) -> nx.Graph:
        graph = nx.Graph()
        graph.add_nodes_from(self._nodes.keys())
        for edge in edges if edges is not None else self._edges.values():
            if edge.source in self._nodes and edge.target in self._nodes:
                graph.add_edge(edge.source, edge.target, weight=max(1, edge.strength))
        return graph

    # ------------------------------------------------------------------ reads
    async def get_viewport(self, limit: int | None = None) -> GraphViewport:
        nodes = sorted(
            self._nodes.values(),
            key=lambda node: (node.betweenness, node.pagerank, node.mention_count),
            reverse=True,
        )
        if limit:
            allowed = {node.id for node in nodes[:limit]}
            nodes = [node for node in nodes if node.id in allowed]
            edges = [
                edge
                for edge in self._edges.values()
                if edge.source in allowed and edge.target in allowed
            ]
        else:
            edges = list(self._edges.values())

        doc_count = len(self._documents)
        type_counts = Counter(node.type for node in self._nodes.values())
        return GraphViewport(
            nodes=[node.model_copy(deep=True) for node in nodes],
            edges=[edge.model_copy(deep=True) for edge in edges],
            communities=[c.model_copy(deep=True) for c in self._communities.values()],
            stats=GraphStats(
                node_count=len(self._nodes),
                edge_count=len(self._edges),
                community_count=len(self._communities),
                document_count=doc_count,
                entity_type_counts=dict(type_counts),
            ),
            source=self.source,
            documents=sorted(self._documents),
            generated_at=datetime.now(UTC).isoformat(),
        )

    async def get_all(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        return (
            [node.model_copy(deep=True) for node in self._nodes.values()],
            [edge.model_copy(deep=True) for edge in self._edges.values()],
        )

    async def get_node(self, node_id: str) -> GraphNode | None:
        node = self._nodes.get(node_id)
        return node.model_copy(deep=True) if node else None

    async def get_neighbors(self, node_id: str, hops: int = 1) -> NeighborResponse:
        center = self._nodes.get(node_id)
        if not center:
            return NeighborResponse(hops=hops)

        graph = self._to_graph()
        if node_id not in graph:
            return NeighborResponse(center=center.model_copy(deep=True), hops=hops)
        lengths = nx.single_source_shortest_path_length(graph, node_id, cutoff=max(1, hops))
        ids = set(lengths)
        nodes = [self._nodes[n].model_copy(deep=True) for n in ids if n in self._nodes]
        edges = [
            edge.model_copy(deep=True)
            for edge in self._edges.values()
            if edge.source in ids and edge.target in ids
        ]
        return NeighborResponse(
            center=center.model_copy(deep=True), nodes=nodes, edges=edges, hops=hops
        )

    async def search_entities(self, query: str, limit: int = 8) -> list[EntitySearchResult]:
        needle = query.strip().lower()
        if not needle:
            return []
        scored: list[tuple[float, GraphNode]] = []
        for node in self._nodes.values():
            haystack = node.search_text.lower()
            if needle in node.name.lower():
                score = 3.0 if node.name.lower().startswith(needle) else 2.0
            elif needle in haystack:
                score = 1.0
            else:
                continue
            score += min(node.mention_count / 500, 0.5)
            scored.append((score, node))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            EntitySearchResult(id=n.id, name=n.name, type=n.type, description=n.description)
            for _, n in scored[:limit]
        ]

    async def get_temporal_slice(self, year: int) -> TemporalSlice:
        visible_edges = [
            edge for edge in self._edges.values() if (edge.year is None or edge.year <= year)
        ]
        node_ids = {edge.source for edge in visible_edges} | {
            edge.target for edge in visible_edges
        }
        nodes = [self._nodes[nid].model_copy(deep=True) for nid in node_ids if nid in self._nodes]
        return TemporalSlice(
            year=year,
            nodes=nodes,
            edges=[edge.model_copy(deep=True) for edge in visible_edges],
            new_edge_ids=[edge.id for edge in visible_edges if edge.year == year],
            dissolved_edge_ids=[
                edge.id
                for edge in visible_edges
                if edge.status == "DISSOLVED" and edge.year == year
            ],
            node_ids=sorted(node_ids),
        )

    # ------------------------------------------------------------------ writes
    async def upsert_graph(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        *,
        source_doc: str,
        source_chunk_id: str,
        source_page: int | None = None,
    ) -> dict[str, int]:
        created_nodes = 0
        created_edges = 0
        async with self._lock:
            # A new document replaces the previous graph: only the newest upload is
            # kept on the canvas, so the previous file's nodes never linger.
            if source_doc and source_doc != self._active_document:
                self._nodes.clear()
                self._edges.clear()
                self._communities.clear()
                self._documents.clear()
                self._active_document = source_doc
            if source_doc:
                self._documents.add(source_doc)
            for raw in entities:
                node_id = raw.get("id") or slugify(raw.get("name", ""))
                existing = self._nodes.get(node_id)
                if existing is None:
                    self._nodes[node_id] = GraphNode(
                        id=node_id,
                        name=raw["name"],
                        type=clean_type(raw.get("type")),
                        description=raw.get("description", ""),
                        community_id=int(raw.get("community_id", 0)),
                        mention_count=int(raw.get("mention_count", 1)),
                        aliases=list(raw.get("aliases") or []),
                        year=raw.get("year") or year_of(raw.get("date")),
                        documents=[source_doc] if source_doc else [],
                    )
                    created_nodes += 1
                else:
                    existing.mention_count += int(raw.get("mention_count", 1))
                    description = raw.get("description") or ""
                    if len(description) > len(existing.description):
                        existing.description = description
                    if source_doc and source_doc not in existing.documents:
                        existing.documents.append(source_doc)

            for raw in relationships:
                source = raw.get("source")
                target = raw.get("target")
                if source not in self._nodes or target not in self._nodes:
                    continue
                edge_id = raw.get("id") or (
                    f"{source}__{raw.get('type', 'RELATED_TO')}__{target}".lower()
                )
                if edge_id in self._edges:
                    edge = self._edges[edge_id]
                    edge.strength = max(edge.strength, int(raw.get("strength", 5)))
                    if raw.get("description"):
                        edge.description = raw["description"]
                    continue
                self._edges[edge_id] = GraphEdge(
                    id=edge_id,
                    source=source,
                    target=target,
                    type=(raw.get("type") or "RELATED_TO").upper(),
                    description=raw.get("description", ""),
                    strength=int(raw.get("strength", 5)),
                    date=raw.get("date"),
                    date_confidence=raw.get("date_confidence", "unknown"),
                    source_doc=raw.get("source_doc") or source_doc,
                    source_chunk_id=raw.get("source_chunk_id") or source_chunk_id,
                    source_page=raw.get("source_page") or source_page,
                    status=raw.get("status", "ACTIVE"),
                    year=raw.get("year") or year_of(raw.get("date")),
                )
                created_edges += 1

        await self.refresh_analytics()
        await self.save_snapshot()

        return {
            "entities_created": created_nodes,
            "entities_updated": len(entities) - created_nodes,
            "relationships_created": created_edges,
            "relationships_updated": len(relationships) - created_edges,
        }

    async def refresh_analytics(self) -> None:
        if not self._nodes:
            return
        graph = self._to_graph()
        if graph.number_of_edges() > 0:
            pagerank = nx.pagerank(graph, alpha=0.85, weight="weight")
            betweenness = nx.betweenness_centrality(graph, weight="weight", normalized=True)
        else:
            pagerank = {}
            betweenness = {}
        degrees = dict(graph.degree())
        for node_id, node in self._nodes.items():
            node.pagerank = round(float(pagerank.get(node_id, 0.0)), 6)
            node.betweenness = round(float(betweenness.get(node_id, 0.0)), 6)
            node.degree = int(degrees.get(node_id, 0))

    async def recompute_communities(self) -> None:
        """Local, incremental-friendly community refresh (Louvain on the active graph)."""
        graph = self._to_graph(edge for edge in self._edges.values() if edge.status != "DISSOLVED")
        if graph.number_of_edges() == 0:
            return
        try:
            groups = list(nx.community.louvain_communities(graph, weight="weight", seed=42))
        except Exception:  # pragma: no cover - defensive for exotic networkx builds
            groups = list(nx.community.greedy_modularity_communities(graph))
        groups.sort(key=len, reverse=True)
        for index, group in enumerate(groups):
            color = COMMUNITY_PALETTE[index % len(COMMUNITY_PALETTE)]
            members = [self._nodes[node_id] for node_id in group if node_id in self._nodes]
            dominant_type = Counter(node.type for node in members).most_common(1)
            label = dominant_type[0][0].title() if dominant_type else "Cluster"
            self._communities[index] = Community(
                id=index,
                name=f"{label} Cluster {index + 1}",
                color=color,
                summary="Auto-generated community from the latest ingestion batch.",
            )
            for node_id in group:
                if node_id in self._nodes:
                    self._nodes[node_id].community_id = index
        await self.save_snapshot()

    async def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": "memory",
            "nodes": len(self._nodes),
            "edges": len(self._edges),
        }


class Neo4jGraphRepository(GraphRepository):
    """Production repository backed by Neo4j 5.23+ (APOC + GDS optional)."""

    source = "neo4j"

    def __init__(self) -> None:
        self._driver = None

    async def initialize(self) -> None:
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "neo4j driver is not installed. Install the 'graph' extra or set DEMO_MODE=true."
            ) from exc

        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        await self._driver.verify_connectivity()
        await self._run_constraints()
        if getattr(settings, "seed_on_startup", True):
            count = await self._count_nodes()
            if count == 0:
                logger.info("Neo4j is empty — importing demo seed graph")
                payload = load_seed()
                await self.upsert_graph(
                    payload.get("nodes", []),
                    [
                        {**edge, "source": edge["source"], "target": edge["target"]}
                        for edge in payload.get("edges", [])
                    ],
                    source_doc="seed",
                    source_chunk_id="seed",
                )
                await self.refresh_analytics()

    async def _run_constraints(self) -> None:
        statements = [
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE FULLTEXT INDEX entity_search_idx IF NOT EXISTS "
            "FOR (e:Entity) ON EACH [e.name, e.aliases, e.description]",
            "CREATE INDEX rel_date_idx IF NOT EXISTS FOR ()-[r:RELATED_TO]-() ON (r.date)",
            "CREATE INDEX entity_community_idx IF NOT EXISTS FOR (e:Entity) ON (e.community_id)",
        ]
        for statement in statements:
            try:
                await self._write(statement)
            except Exception as exc:  # pragma: no cover - server-version dependent
                logger.warning("Constraint setup skipped: %s", exc)

    async def _count_nodes(self) -> int:
        rows = await self._read("MATCH (n:Entity) RETURN count(n) AS count")
        return int(rows[0]["count"]) if rows else 0

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()

    async def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        assert self._driver is not None
        async with self._driver.session(database=settings.neo4j_database) as session:
            result = await session.run(query, **params)
            return [record.data() async for record in result]

    async def _write(self, query: str, **params: Any) -> list[dict[str, Any]]:
        return await self._read(query, **params)

    # ------------------------------------------------------------------ mapping
    @staticmethod
    def _map_node(props: dict[str, Any]) -> GraphNode:
        return GraphNode(
            id=props["id"],
            name=props.get("name", props["id"]),
            type=clean_type(props.get("type")),
            description=props.get("description", ""),
            community_id=int(props.get("community_id", 0) or 0),
            mention_count=int(props.get("mentionCount", 1) or 1),
            pagerank=float(props.get("pagerank", 0.0) or 0.0),
            betweenness=float(props.get("betweenness", 0.0) or 0.0),
            degree=int(props.get("degree", 0) or 0),
            year=int(props["year"]) if props.get("year") else None,
            aliases=list(props.get("aliases") or []),
        )

    @staticmethod
    def _map_edge(props: dict[str, Any], source: str, target: str) -> GraphEdge:
        return GraphEdge(
            id=props.get("id") or f"{source}__{props.get('type')}__{target}".lower(),
            source=source,
            target=target,
            type=props.get("type", "RELATED_TO"),
            description=props.get("description", ""),
            strength=int(props.get("strength", 5) or 5),
            date=props.get("date"),
            date_confidence=props.get("dateConfidence", "unknown"),
            source_doc=props.get("sourceDoc"),
            source_chunk_id=props.get("sourceChunkId"),
            source_page=props.get("sourcePage"),
            status=props.get("status", "ACTIVE"),
            year=year_of(props.get("date")),
        )

    async def get_viewport(self, limit: int | None = None) -> GraphViewport:
        limit = limit or 5000
        node_rows = await self._read(
            "MATCH (n:Entity) RETURN properties(n) AS node "
            "ORDER BY coalesce(n.betweenness, 0) DESC LIMIT $limit",
            limit=limit,
        )
        nodes = [self._map_node(row["node"]) for row in node_rows]
        allowed = {node.id for node in nodes}
        edge_rows = await self._read(
            "MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity) "
            "WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN properties(r) AS rel, a.id AS source, b.id AS target",
            ids=list(allowed),
        )
        edges = [self._map_edge(row["rel"], row["source"], row["target"]) for row in edge_rows]
        community_rows = await self._read(
            "MATCH (n:Entity) RETURN coalesce(n.community_id, 0) AS id, count(n) AS size"
        )
        communities = [
            Community(
                id=int(row["id"]),
                name=f"Community {int(row['id']) + 1}",
                color=COMMUNITY_PALETTE[int(row["id"]) % len(COMMUNITY_PALETTE)],
                summary=f"{row['size']} entities",
            )
            for row in community_rows
        ]
        doc_rows = await self._read(
            "MATCH ()-[r:RELATED_TO]->() WHERE r.sourceDoc IS NOT NULL "
            "RETURN count(DISTINCT r.sourceDoc) AS count"
        )
        type_rows = await self._read("MATCH (n:Entity) RETURN n.type AS type, count(*) AS count")
        stats = GraphStats(
            node_count=sum(row["count"] for row in await self._read(
                "MATCH (n:Entity) RETURN count(n) AS count"
            )),
            edge_count=sum(row["count"] for row in await self._read(
                "MATCH ()-[r:RELATED_TO]->() RETURN count(r) AS count"
            )),
            community_count=len(communities),
            document_count=int(doc_rows[0]["count"]) if doc_rows else 0,
            entity_type_counts={row["type"] or "UNKNOWN": row["count"] for row in type_rows},
        )
        return GraphViewport(
            nodes=nodes,
            edges=edges,
            communities=communities,
            stats=stats,
            source=self.source,
            generated_at=datetime.now(UTC).isoformat(),
        )

    async def get_all(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        node_rows = await self._read("MATCH (n:Entity) RETURN properties(n) AS node")
        edge_rows = await self._read(
            "MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity) "
            "RETURN properties(r) AS rel, a.id AS source, b.id AS target"
        )
        return (
            [self._map_node(row["node"]) for row in node_rows],
            [self._map_edge(row["rel"], row["source"], row["target"]) for row in edge_rows],
        )

    async def get_node(self, node_id: str) -> GraphNode | None:
        rows = await self._read(
            "MATCH (n:Entity {id: $id}) RETURN properties(n) AS node", id=node_id
        )
        return self._map_node(rows[0]["node"]) if rows else None

    async def get_neighbors(self, node_id: str, hops: int = 1) -> NeighborResponse:
        hops = max(1, min(int(hops), 4))
        center = await self.get_node(node_id)
        rows = await self._read(
            f"MATCH (n:Entity {{id: $id}}) "
            f"MATCH p=(n)-[:RELATED_TO*1..{hops}]-(m:Entity) "
            "WITH n, m, relationships(p) AS rels "
            "UNWIND rels AS r "
            "WITH n, m, r, startNode(r) AS s, endNode(r) AS t "
            "RETURN properties(n) AS center, properties(m) AS neighbor, properties(r) AS rel, "
            "s.id AS source, t.id AS target",
            id=node_id,
        )
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        for row in rows:
            nodes[row["neighbor"]["id"]] = self._map_node(row["neighbor"])
            edge = self._map_edge(row["rel"], row["source"], row["target"])
            edges[edge.id] = edge
        return NeighborResponse(center=center, nodes=list(nodes.values()), edges=list(edges.values()), hops=hops)

    async def search_entities(self, query: str, limit: int = 8) -> list[EntitySearchResult]:
        rows = await self._read(
            "CALL db.index.fulltext.queryNodes('entity_search_idx', $q) YIELD node, score "
            "RETURN node.id AS id, node.name AS name, node.type AS type, "
            "node.description AS description, score ORDER BY score DESC LIMIT $limit",
            q=query,
            limit=limit,
        )
        if not rows:
            rows = await self._read(
                "MATCH (n:Entity) WHERE toLower(n.name) CONTAINS toLower($q) "
                "RETURN n.id AS id, n.name AS name, n.type AS type, "
                "n.description AS description, 1.0 AS score LIMIT $limit",
                q=query,
                limit=limit,
            )
        return [
            EntitySearchResult(
                id=row["id"], name=row["name"], type=clean_type(row["type"]), description=row["description"] or ""
            )
            for row in rows
        ]

    async def get_temporal_slice(self, year: int) -> TemporalSlice:
        node_rows = await self._read("MATCH (n:Entity) RETURN properties(n) AS node")
        edge_rows = await self._read(
            "MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity) "
            "RETURN properties(r) AS rel, a.id AS source, b.id AS target"
        )
        nodes = [self._map_node(row["node"]) for row in node_rows]
        edges = [self._map_edge(row["rel"], row["source"], row["target"]) for row in edge_rows]
        visible = [edge for edge in edges if edge.year is None or edge.year <= year]
        node_ids = {edge.source for edge in visible} | {edge.target for edge in visible}
        return TemporalSlice(
            year=year,
            nodes=[node for node in nodes if node.id in node_ids],
            edges=visible,
            new_edge_ids=[edge.id for edge in visible if edge.year == year],
            dissolved_edge_ids=[
                edge.id for edge in visible if edge.status == "DISSOLVED" and edge.year == year
            ],
            node_ids=sorted(node_ids),
        )

    async def upsert_graph(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        *,
        source_doc: str,
        source_chunk_id: str,
        source_page: int | None = None,
    ) -> dict[str, int]:
        rows = [
            {
                "id": entity.get("id") or slugify(entity["name"]),
                "name": entity["name"],
                "type": clean_type(entity.get("type")),
                "description": entity.get("description", ""),
                "communityId": int(entity.get("community_id", 0)),
                "year": entity.get("year") or year_of(entity.get("date")),
                "aliases": list(entity.get("aliases") or []),
            }
            for entity in entities
        ]
        node_count = 0
        if rows:
            result = await self._write(
                "UNWIND $rows AS row "
                "MERGE (e:Entity {id: row.id}) "
                "ON CREATE SET e.name = row.name, e.type = row.type, e.description = row.description, "
                "  e.community_id = row.communityId, e.year = row.year, e.aliases = row.aliases, "
                "  e.mentionCount = 1, e.createdAt = datetime() "
                "ON MATCH SET e.mentionCount = coalesce(e.mentionCount, 1) + 1, "
                "  e.description = CASE WHEN size(coalesce(row.description, '')) > "
                "    size(coalesce(e.description, '')) THEN row.description ELSE e.description END "
                "RETURN count(e) AS count",
                rows=rows,
            )
            node_count = int(result[0]["count"]) if result else 0

        rel_rows = [
            {
                "id": rel.get("id")
                or f"{rel['source']}__{rel.get('type', 'RELATED_TO')}__{rel['target']}".lower(),
                "sourceId": rel["source"],
                "targetId": rel["target"],
                "type": (rel.get("type") or "RELATED_TO").upper(),
                "description": rel.get("description", ""),
                "strength": int(rel.get("strength", 5)),
                "date": rel.get("date"),
                "dateConfidence": rel.get("date_confidence", "unknown"),
                "sourceChunkId": rel.get("source_chunk_id") or source_chunk_id,
                "sourceDoc": rel.get("source_doc") or source_doc,
                "sourcePage": rel.get("source_page") or source_page,
                "status": rel.get("status", "ACTIVE"),
            }
            for rel in relationships
            if rel.get("source") and rel.get("target")
        ]
        rel_count = 0
        if rel_rows:
            result = await self._write(
                "UNWIND $rows AS rel "
                "MATCH (a:Entity {id: rel.sourceId}) "
                "MATCH (b:Entity {id: rel.targetId}) "
                "MERGE (a)-[r:RELATED_TO {type: rel.type}]->(b) "
                "ON CREATE SET r.id = rel.id, r.description = rel.description, "
                "  r.strength = rel.strength, r.date = rel.date, r.dateConfidence = rel.dateConfidence, "
                "  r.sourceChunkId = rel.sourceChunkId, r.sourceDoc = rel.sourceDoc, "
                "  r.sourcePage = rel.sourcePage, r.status = rel.status, r.createdAt = datetime() "
                "ON MATCH SET r.strength = CASE WHEN rel.strength > coalesce(r.strength, 0) "
                "  THEN rel.strength ELSE r.strength END, "
                "  r.sourcePage = coalesce(r.sourcePage, rel.sourcePage) "
                "RETURN count(r) AS count",
                rows=rel_rows,
            )
            rel_count = int(result[0]["count"]) if result else 0

        return {
            "entities_created": node_count,
            "relationships_created": rel_count,
            "entities_updated": max(0, len(rows) - node_count),
            "relationships_updated": max(0, len(rel_rows) - rel_count),
        }

    async def refresh_analytics(self) -> None:
        nodes, edges = await self.get_all()
        if not nodes:
            return
        graph = nx.Graph()
        graph.add_nodes_from(node.id for node in nodes)
        for edge in edges:
            if edge.status != "DISSOLVED":
                graph.add_edge(edge.source, edge.target, weight=max(1, edge.strength))
        try:
            pagerank = nx.pagerank(graph, alpha=0.85, weight="weight")
            betweenness = nx.betweenness_centrality(graph, weight="weight", normalized=True)
            degrees = dict(graph.degree())
        except Exception as exc:  # pragma: no cover
            logger.warning("Analytics computation failed: %s", exc)
            return
        rows = [
            {
                "id": node_id,
                "pagerank": float(pagerank.get(node_id, 0.0)),
                "betweenness": float(betweenness.get(node_id, 0.0)),
                "degree": int(degrees.get(node_id, 0)),
            }
            for node_id in graph.nodes
        ]
        await self._write(
            "UNWIND $rows AS row MATCH (e:Entity {id: row.id}) "
            "SET e.pagerank = row.pagerank, e.betweenness = row.betweenness, e.degree = row.degree",
            rows=rows,
        )

    async def recompute_communities(self) -> None:
        nodes, edges = await self.get_all()
        graph = nx.Graph()
        graph.add_nodes_from(node.id for node in nodes)
        for edge in edges:
            if edge.status != "DISSOLVED":
                graph.add_edge(edge.source, edge.target, weight=max(1, edge.strength))
        if graph.number_of_edges() == 0:
            return
        try:
            groups = list(nx.community.louvain_communities(graph, weight="weight", seed=42))
        except Exception:
            groups = list(nx.community.greedy_modularity_communities(graph))
        rows = [
            {"id": node_id, "communityId": index}
            for index, group in enumerate(groups)
            for node_id in group
        ]
        await self._write(
            "UNWIND $rows AS row MATCH (e:Entity {id: row.id}) SET e.community_id = row.communityId",
            rows=rows,
        )

    async def health(self) -> dict[str, Any]:
        try:
            count = await self._count_nodes()
            return {"status": "ok", "backend": "neo4j", "nodes": count}
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "backend": "neo4j", "error": str(exc)}
