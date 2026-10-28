from __future__ import annotations

from fastapi import APIRouter

from app.runtime import runtime_health

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    return await runtime_health()
