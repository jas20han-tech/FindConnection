"""In-memory cascade simulation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import repository_dependency
from app.graph.repository import GraphRepository
from app.reasoning.simulator import simulate_impact
from app.schemas.impact import ImpactRequest, ImpactResult

router = APIRouter(tags=["simulation"])


@router.post("/simulate/impact", response_model=ImpactResult)
async def impact(
    payload: ImpactRequest,
    repository: GraphRepository = Depends(repository_dependency),
) -> ImpactResult:
    nodes, edges = await repository.get_all()
    try:
        return simulate_impact(nodes, edges, payload.node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
