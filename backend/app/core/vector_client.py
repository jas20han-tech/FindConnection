"""ChromaDB vector store wrapper (1536-dim embeddings, metadata filtering)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_available = False
_last_error: str | None = None
_chunks: Any = None
_entities: Any = None


async def init_vector_store() -> bool:
    global _client, _available, _last_error, _chunks, _entities
    try:
        import chromadb

        def _connect() -> Any:
            return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)

        _client = await asyncio.to_thread(_connect)
        await asyncio.to_thread(_client.heartbeat)
        _chunks = await asyncio.to_thread(
            _client.get_or_create_collection, settings.chroma_collection_chunks
        )
        _entities = await asyncio.to_thread(
            _client.get_or_create_collection, settings.chroma_collection_entities
        )
        _available = True
        _last_error = None
        logger.info("ChromaDB connected")
        return True
    except Exception as exc:
        _available = False
        _last_error = str(exc)
        logger.warning("ChromaDB unavailable (%s) — vector search disabled", exc)
        return False


def is_available() -> bool:
    return _available


async def upsert_chunks(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
) -> bool:
    if not _available or _chunks is None or not ids:
        return False
    try:
        await asyncio.to_thread(
            _chunks.upsert,
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return True
    except Exception as exc:
        logger.warning("Chunk upsert failed: %s", exc)
        return False


async def upsert_entities(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
) -> bool:
    if not _available or _entities is None or not ids:
        return False
    try:
        await asyncio.to_thread(
            _entities.upsert,
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return True
    except Exception as exc:
        logger.warning("Entity vector upsert failed: %s", exc)
        return False


async def query_chunks(embedding: list[float], n_results: int = 8) -> list[dict[str, Any]]:
    if not _available or _chunks is None:
        return []
    try:
        result = await asyncio.to_thread(
            _chunks.query, query_embeddings=[embedding], n_results=n_results
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            {"document": doc, "metadata": meta or {}, "distance": dist}
            for doc, meta, dist in zip(documents, metadatas, distances)
        ]
    except Exception as exc:
        logger.warning("Chunk query failed: %s", exc)
        return []


async def close_vector_store() -> None:
    global _client, _available
    _client = None
    _available = False


async def health() -> dict[str, Any]:
    return {
        "status": "ok" if _available else "degraded",
        "backend": "chromadb",
        "error": None if _available else _last_error,
    }
