from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.types import EdgeStatus, EntityType


class Community(BaseModel):
    id: int
    name: str
    color: str
    summary: str = ""


class GraphNode(BaseModel):
    id: str
    name: str
    type: EntityType
    description: str = ""
    community_id: int = 0
    mention_count: int = 1
    pagerank: float = 0.0
    betweenness: float = 0.0
    degree: int = 0
    year: int | None = None
    aliases: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)

    @property
    def search_text(self) -> str:
        return " ".join([self.name, *self.aliases, self.description])


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    description: str = ""
    strength: int = 5
    date: str | None = None
    date_confidence: str = "unknown"
    source_doc: str | None = None
    source_chunk_id: str | None = None
    source_page: int | None = None
    status: EdgeStatus = "ACTIVE"
    year: int | None = None


class GraphStats(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    community_count: int = 0
    document_count: int = 0
    entity_type_counts: dict[str, int] = Field(default_factory=dict)


class GraphViewport(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    communities: list[Community] = Field(default_factory=list)
    stats: GraphStats = Field(default_factory=GraphStats)
    source: str = "memory"
    documents: list[str] = Field(default_factory=list)
    generated_at: str | None = None


class NeighborResponse(BaseModel):
    center: GraphNode | None = None
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    hops: int = 1


class EntitySearchResult(BaseModel):
    id: str
    name: str
    type: EntityType
    description: str = ""


class TemporalSlice(BaseModel):
    year: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    new_edge_ids: list[str] = Field(default_factory=list)
    dissolved_edge_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
