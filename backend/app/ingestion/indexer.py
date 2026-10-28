"""Graph + vector indexing.

Neo4j writes are batched through a single ``UNWIND`` round-trip. Vector upserts are
best-effort: embeddings are only generated when an OpenAI key and ChromaDB are both
available, so demo mode incurs no external calls.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.core import llm, vector_client
from app.graph.repository import GraphRepository
from app.ingestion.chunker import Chunk
from app.ingestion.resolver import ResolvedGraph

logger = logging.getLogger(__name__)


class GraphIndexer:
    def __init__(self, repository: GraphRepository) -> None:
        self.repository = repository

    async def index(
        self,
        resolved: ResolvedGraph,
        chunks: list[Chunk],
        *,
        source_doc: str,
        source_chunk_id: str,
        source_page: int | None = None,
    ) -> dict[str, int]:
        counts = await self.repository.upsert_graph(
            resolved.entities,
            resolved.relationships,
            source_doc=source_doc,
            source_chunk_id=source_chunk_id,
            source_page=source_page,
        )
        counts["vectors_indexed"] = await self._index_vectors(resolved, chunks)
        return counts

    async def _index_vectors(self, resolved: ResolvedGraph, chunks: list[Chunk]) -> int:
        if not (settings.llm_enabled and vector_client.is_available()):
            return 0

        indexed = 0
        try:
            if chunks:
                chunk_vectors = await llm.embed_texts([chunk.text for chunk in chunks])
                ok = await vector_client.upsert_chunks(
                    ids=[chunk.id for chunk in chunks],
                    documents=[chunk.text for chunk in chunks],
                    embeddings=chunk_vectors,
                    metadatas=[dict(chunk.as_metadata()) for chunk in chunks],
                )
                indexed += len(chunks) if ok else 0

            if resolved.entities:
                texts = [
                    f"{entity['name']}. {entity.get('description', '')}"
                    for entity in resolved.entities
                ]
                entity_vectors = await llm.embed_texts(texts)
                ok = await vector_client.upsert_entities(
                    ids=[entity["id"] for entity in resolved.entities],
                    documents=texts,
                    embeddings=entity_vectors,
                    metadatas=[
                        {
                            "name": entity["name"],
                            "type": entity["type"],
                            "community_id": int(entity.get("community_id", 0)),
                        }
                        for entity in resolved.entities
                    ],
                )
                indexed += len(resolved.entities) if ok else 0
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Vector indexing skipped: %s", exc)

        return indexed


def as_counts(payload: dict[str, Any]) -> dict[str, int]:
    return {key: int(value) for key, value in payload.items() if isinstance(value, (int, float))}
