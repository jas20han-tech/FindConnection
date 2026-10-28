from __future__ import annotations

from pydantic import BaseModel, Field


class ImpactRequest(BaseModel):
    node_id: str
    hops: int = Field(default=2, ge=1, le=4)


class OrphanedNode(BaseModel):
    id: str
    name: str
    type: str
    previous_degree: int


class CentralitySurge(BaseModel):
    id: str
    name: str
    type: str
    baseline: float
    projected: float
    delta_pct: float


class SeveredEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str


class ImpactResult(BaseModel):
    removed_node: dict[str, str]
    severity: str
    risk_score: float
    disruption_ratio: float
    component_count_before: int
    component_count_after: int
    largest_component_ratio_after: float
    directly_disrupted: list[dict[str, str]] = Field(default_factory=list)
    orphaned: list[OrphanedNode] = Field(default_factory=list)
    centrality_surge: list[CentralitySurge] = Field(default_factory=list)
    severed_edges: list[SeveredEdge] = Field(default_factory=list)
    duration_ms: float = 0.0
