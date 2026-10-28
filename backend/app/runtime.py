"""Application runtime container: repository selection and optional service wiring."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.core import postgres_client, redis_client, vector_client
from app.graph.repository import GraphRepository, InMemoryGraphRepository, Neo4jGraphRepository

logger = logging.getLogger(__name__)

_repository: GraphRepository | None = None
_services: dict[str, bool] = {"postgres": False, "redis": False, "vectors": False}


async def init_runtime() -> GraphRepository:
    """Initialise storage. Never raises for optional infrastructure."""
    global _repository

    if _repository is not None:
        return _repository

    if settings.demo_mode:
        repository: GraphRepository = InMemoryGraphRepository(seed=True)
        await repository.initialize()
        logger.info("Demo mode: using in-memory graph repository")
    else:
        try:
            neo = Neo4jGraphRepository()
            await asyncio.wait_for(neo.initialize(), timeout=25)
            repository = neo
            logger.info("Production mode: using Neo4j graph repository")
        except Exception as exc:
            logger.error("Neo4j initialisation failed (%s) — falling back to in-memory graph", exc)
            repository = InMemoryGraphRepository(seed=True)
            await repository.initialize()

    _repository = repository

    # Optional services: connect concurrently with tight timeouts.
    results = await asyncio.gather(
        _safe("postgres", postgres_client.init_postgres()),
        _safe("redis", redis_client.init_redis()),
        _safe("vectors", vector_client.init_vector_store()),
    )
    _services.update(dict(zip(["postgres", "redis", "vectors"], results)))
    return _repository


async def _safe(name: str, coroutine: Any) -> bool:
    try:
        return bool(await asyncio.wait_for(coroutine, timeout=8))
    except Exception as exc:
        logger.info("Optional service %s unavailable: %s", name, exc)
        return False


def get_repository() -> GraphRepository:
    if _repository is None:
        raise RuntimeError("Runtime not initialised")
    return _repository


async def shutdown_runtime() -> None:
    global _repository
    if _repository is not None:
        await _repository.close()
    await asyncio.gather(
        postgres_client.close_postgres(),
        redis_client.close_redis(),
        vector_client.close_vector_store(),
        return_exceptions=True,
    )
    _repository = None


async def runtime_health() -> dict[str, Any]:
    repository = _repository
    graph = await repository.health() if repository else {"status": "uninitialised"}
    postgres, redis, vectors = await asyncio.gather(
        postgres_client.health(),
        redis_client.health(),
        vector_client.health(),
        return_exceptions=True,
    )
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "demo_mode": settings.demo_mode,
        "llm_enabled": settings.llm_enabled,
        "celery_enabled": settings.use_celery,
        "graph": graph,
        "postgres": postgres if isinstance(postgres, dict) else {"status": "error"},
        "redis": redis if isinstance(redis, dict) else {"status": "error"},
        "vectors": vectors if isinstance(vectors, dict) else {"status": "error"},
    }


def service_flags() -> dict[str, bool]:
    return dict(_services)
