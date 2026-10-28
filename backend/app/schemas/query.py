from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.types import QueryMode


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: QueryMode | None = None
    time_range: tuple[int, int] | None = None
    max_hops: int = Field(default=5, ge=1, le=6)
    max_nodes: int = Field(default=40, ge=5, le=200)


class Citation(BaseModel):
    edge_id: str
    label: str
    document: str
    page: int | None = None
    chunk_id: str | None = None
    date: str | None = None
    cosine_similarity: float | None = None


class GraphContextEvent(BaseModel):
    type: str = "graph_context"
    query: str
    mode: QueryMode
    seed_node_ids: list[str] = Field(default_factory=list)
    highlighted_node_ids: list[str] = Field(default_factory=list)
    highlighted_edge_ids: list[str] = Field(default_factory=list)
    path_node_ids: list[str] = Field(default_factory=list)
    path_edge_ids: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    explanation: str = ""
    elapsed_ms: float = 0.0
    confidence: float = 0.0


class TokenEvent(BaseModel):
    type: str = "token"
    text: str


class CompleteEvent(BaseModel):
    type: str = "complete"
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    duration_ms: float = 0.0
    mode: QueryMode = "GLOBAL"


class ErrorEvent(BaseModel):
    type: str = "error"
    message: str
