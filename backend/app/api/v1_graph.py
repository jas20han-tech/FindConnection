"""Graph read endpoints: viewport, ego network, entity autocomplete, temporal slices."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import repository_dependency
from app.graph.repository import GraphRepository
from app.reasoning.community import community_overview
from app.schemas.graph import (
    EntitySearchResult,
    GraphViewport,
    NeighborResponse,
    TemporalSlice,
)

router = APIRouter(tags=["graph"])


@router.get("/graph/viewport", response_model=GraphViewport)
async def get_viewport(
    limit: int | None = Query(default=None, ge=50, le=50000),
    repository: GraphRepository = Depends(repository_dependency),
) -> GraphViewport:
    """Initial backbone graph, ordered by betweenness when a limit is supplied."""
    return await repository.get_viewport(limit=limit)


@router.get("/graph/node/{node_id}", response_model=dict)
async def get_node(
    node_id: str,
    repository: GraphRepository = Depends(repository_dependency),
) -> dict:
    node = await repository.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Entity '{node_id}' not found")
    return node.model_dump()


@router.get("/graph/node/{node_id}/neighbors", response_model=NeighborResponse)
async def get_neighbors(
    node_id: str,
    hops: int = Query(default=1, ge=1, le=4),
    repository: GraphRepository = Depends(repository_dependency),
) -> NeighborResponse:
    response = await repository.get_neighbors(node_id, hops=hops)
    if response.center is None:
        raise HTTPException(status_code=404, detail=f"Entity '{node_id}' not found")
    return response


@router.get("/entity/search", response_model=list[EntitySearchResult])
async def search_entities(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=8, ge=1, le=25),
    repository: GraphRepository = Depends(repository_dependency),
) -> list[EntitySearchResult]:
    return await repository.search_entities(q, limit=limit)


@router.get("/graph/temporal", response_model=TemporalSlice)
async def get_temporal_slice(
    year: int = Query(ge=1990, le=2100),
    repository: GraphRepository = Depends(repository_dependency),
) -> TemporalSlice:
    return await repository.get_temporal_slice(year)


@router.get("/graph/communities", response_model=list[dict])
async def get_communities(
    repository: GraphRepository = Depends(repository_dependency),
) -> list[dict]:
    nodes, edges = await repository.get_all()
    viewport = await repository.get_viewport()
    return community_overview(nodes, edges, viewport.communities)


@router.post("/graph/reset", response_model=dict)
async def reset_graph(
    repository: GraphRepository = Depends(repository_dependency),
) -> dict:
    """Discard ingested documents and restore the bundled demo graph (memory backend)."""
    reset = getattr(repository, "reset_to_seed", None)
    if reset is None:
        raise HTTPException(
            status_code=409,
            detail="Reset is only available for the in-memory demo graph",
        )
    await reset()
    stats = await repository.stats()
    return {
        "status": "reset",
        "node_count": stats.node_count,
        "edge_count": stats.edge_count,
    }
