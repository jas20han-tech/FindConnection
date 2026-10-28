from __future__ import annotations

from fastapi import APIRouter

from app.api import health, v1_graph, v1_query, v1_simulation, v1_upload

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(v1_graph.router)
api_router.include_router(v1_query.router)
api_router.include_router(v1_simulation.router)
api_router.include_router(v1_upload.router)

__all__ = ["api_router"]
