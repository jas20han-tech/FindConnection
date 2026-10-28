"""Async PostgreSQL client for ingestion telemetry, snapshots and audit trails.

SQLAlchemy is an optional dependency: when it is not installed (or the database is
unreachable) the platform keeps working in demo mode and logs a degraded status.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.config import settings

logger = logging.getLogger(__name__)

_engine: Any = None
_session_factory: Any = None
_available = False
_last_error: str | None = None


def is_available() -> bool:
    return _available


def last_error() -> str | None:
    return _last_error


async def init_postgres() -> bool:
    """Create the engine and tables. Safe to call repeatedly."""
    global _engine, _session_factory, _available, _last_error

    if _available:
        return True
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.models.base import Base

        _engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True, pool_size=5)
        async with _engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _available = True
        _last_error = None
        logger.info("PostgreSQL connected")
        return True
    except Exception as exc:  # optional dependency or server offline
        _available = False
        _last_error = str(exc)
        logger.warning("PostgreSQL unavailable (%s) — telemetry persistence disabled", exc)
        return False


@asynccontextmanager
async def session() -> AsyncIterator[Any]:
    if not _available or _session_factory is None:
        raise RuntimeError("PostgreSQL is not available")
    async with _session_factory() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def close_postgres() -> None:
    global _engine, _available
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _available = False


async def health() -> dict[str, Any]:
    if not _available or _engine is None:
        return {"status": "degraded", "backend": "postgres", "error": _last_error}
    try:
        from sqlalchemy import text

        async with _engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "ok", "backend": "postgres"}
    except Exception as exc:
        return {"status": "error", "backend": "postgres", "error": str(exc)}
