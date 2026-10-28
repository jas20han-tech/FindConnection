"""Redis cache, pub/sub and Celery broker access.

Every method degrades silently when Redis is unavailable so the API can still serve
demo reads from the in-memory repository.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_available = False
_last_error: str | None = None


async def init_redis() -> bool:
    global _client, _available, _last_error
    try:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await _client.ping()
        _available = True
        _last_error = None
        logger.info("Redis connected")
        return True
    except Exception as exc:
        _available = False
        _last_error = str(exc)
        _client = None
        logger.warning("Redis unavailable (%s) — using in-process cache", exc)
        return False


def is_available() -> bool:
    return _available


async def get(key: str) -> str | None:
    if not _available or _client is None:
        return None
    try:
        return await _client.get(key)
    except Exception:
        return None


async def set(key: str, value: str, ttl: int | None = None) -> bool:
    if not _available or _client is None:
        return False
    try:
        await _client.set(key, value, ex=ttl)
        return True
    except Exception:
        return False


async def get_json(key: str) -> Any | None:
    raw = await get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def set_json(key: str, value: Any, ttl: int | None = None) -> bool:
    return await set(key, json.dumps(value, default=str), ttl)


async def delete(key: str) -> None:
    if _available and _client is not None:
        try:
            await _client.delete(key)
        except Exception:
            pass


async def publish(channel: str, payload: dict[str, Any]) -> None:
    if _available and _client is not None:
        try:
            await _client.publish(channel, json.dumps(payload, default=str))
        except Exception:
            pass


async def close_redis() -> None:
    global _client, _available
    if _client is not None:
        await _client.aclose()
    _client = None
    _available = False


async def health() -> dict[str, Any]:
    if not _available:
        return {"status": "degraded", "backend": "redis", "error": _last_error}
    try:
        await _client.ping()
        return {"status": "ok", "backend": "redis"}
    except Exception as exc:
        return {"status": "error", "backend": "redis", "error": str(exc)}
