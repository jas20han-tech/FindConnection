"""Optional Neo4j driver helpers.

The graph repository owns its driver for the query hot path. This module exposes a
small, reusable connection surface for health checks and maintenance scripts.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_driver: Any = None


async def get_driver() -> Any:
    global _driver
    if _driver is not None:
        return _driver
    try:
        from neo4j import AsyncGraphDatabase
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("neo4j driver is not installed") from exc
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _driver.verify_connectivity()
    return _driver


async def ping() -> bool:
    try:
        driver = await get_driver()
        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run("RETURN 1 AS ok")
            record = await result.single()
            return bool(record and record["ok"] == 1)
    except Exception as exc:
        logger.debug("Neo4j ping failed: %s", exc)
        return False


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
    _driver = None


async def health() -> dict[str, Any]:
    ok = await ping()
    return {
        "status": "ok" if ok else "degraded",
        "backend": "neo4j",
        "uri": settings.neo4j_uri,
    }
