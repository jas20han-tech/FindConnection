"""End-to-end ingestion pipeline with live job telemetry."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from pathlib import Path

from app.config import settings
from app.core import job_store, postgres_client
from app.graph.repository import GraphRepository
from app.ingestion.chunker import chunk_document
from app.ingestion.extractor import ExtractionEngine
from app.ingestion.indexer import GraphIndexer
from app.ingestion.parser import parse_document
from app.ingestion.resolver import EntityResolver
from app.runtime import get_repository

logger = logging.getLogger(__name__)


async def run_ingestion(job_id: str, file_path: str | Path, filename: str | None = None) -> None:
    """Parse -> chunk -> extract -> resolve -> index -> cluster, updating the job store."""
    job = await job_store.get(job_id)
    if job is None:
        logger.warning("Ingestion job %s not found", job_id)
        return

    filename = filename or job.get("filename") or Path(file_path).name
    repository: GraphRepository = get_repository()
    replaced = False

    try:
        # ---------------------------------------------------------- parse
        await job_store.update(job_id, stage_name="PARSING")
        document = await parse_document(Path(file_path), filename)
        await job_store.update(
            job_id,
            document_count=1,
            filename=filename,
            metadata={"pages": document.page_count, "doc_id": document.document_id},
        )

        # ---------------------------------------------------------- chunk
        await job_store.update(job_id, stage_name="CHUNKING")
        chunks = chunk_document(document)
        if not chunks:
            raise ValueError("No chunkable text found in document")
        await job_store.update(job_id, total_chunks=len(chunks), processed_chunks=0)

        # ---------------------------------------------------------- extract
        await job_store.update(job_id, stage_name="EXTRACTING")
        engine = ExtractionEngine()
        last_update = {"completed": 0}

        async def on_progress(completed: int, total: int, entities: int, relationships: int) -> None:
            # Throttle SSE traffic: one update per chunk for small docs, coarser for large.
            step = 1 if total <= 40 else max(1, total // 30)
            if completed - last_update["completed"] < step and completed != total:
                return
            last_update["completed"] = completed
            percent = 32.0 + (26.0 * completed / max(1, total))
            await job_store.update(
                job_id,
                percent=round(percent, 1),
                processed_chunks=completed,
                entities_extracted=entities,
                relationships_extracted=relationships,
            )

        report = await engine.extract(chunks, on_progress=on_progress)
        await job_store.update(
            job_id,
            processed_chunks=len(chunks),
            entities_extracted=sum(len(item.extraction.entities) for item in report.results),
            relationships_extracted=sum(
                len(item.extraction.relationships) for item in report.results
            ),
        )

        # ---------------------------------------------------------- resolve
        await job_store.update(job_id, stage_name="RESOLVING", percent=58.0)
        # Each upload replaces the previous document: clear the old graph before
        # resolving so entities are not matched against nodes that are about to go.
        reset_for_document = getattr(repository, "reset_for_document", None)
        if reset_for_document is not None:
            await reset_for_document(document.title)
            replaced = True
        existing_nodes, _ = await repository.get_all()
        resolver = EntityResolver(existing_nodes)
        resolved = await resolver.resolve(report)
        counts_by_type = Counter(entity["type"] for entity in resolved.entities)
        await job_store.update(
            job_id,
            entities_extracted=len(resolved.entities),
            relationships_extracted=len(resolved.relationships),
            counts_by_type=dict(counts_by_type),
        )

        # ---------------------------------------------------------- index
        await job_store.update(job_id, stage_name="INDEXING", percent=82.0)
        indexer = GraphIndexer(repository)
        first_chunk = chunks[0]
        counts = await indexer.index(
            resolved,
            chunks,
            source_doc=document.title,
            source_chunk_id=first_chunk.id,
            source_page=first_chunk.page_number,
        )
        await job_store.update(
            job_id,
            percent=90.0,
            entities_extracted=len(resolved.entities),
            relationships_extracted=len(resolved.relationships),
            index_counts=counts,
        )

        # ---------------------------------------------------------- cluster
        await job_store.update(job_id, stage_name="CLUSTERING", percent=94.0)
        recompute = getattr(repository, "recompute_communities", None)
        if recompute is not None:
            try:
                await recompute()
            except Exception as exc:
                logger.warning("Community recompute failed: %s", exc)
        await repository.refresh_analytics()
        stats = await repository.stats()
        await job_store.update(
            job_id,
            stage_name="COMPLETED",
            percent=100.0,
            node_count=stats.node_count,
            edge_count=stats.edge_count,
            community_count=stats.community_count,
            document_count=stats.document_count,
            nodes_added=int(counts.get("entities_created", 0)),
            edges_added=int(counts.get("relationships_created", 0)),
        )
        await _persist_job_snapshot(job_id, document.title, stats)
        logger.info(
            "Ingestion complete for %s: %d entities, %d relationships",
            filename,
            len(resolved.entities),
            len(resolved.relationships),
        )

    except Exception as exc:
        logger.exception("Ingestion failed for %s", filename)
        if replaced:
            # Do not leave an empty canvas behind when a replacement fails.
            restore = getattr(repository, "reset_to_seed", None)
            if restore is not None:
                try:
                    await restore()
                except Exception:
                    logger.warning("Could not restore the demo graph after a failed ingest")
        await job_store.fail(job_id, str(exc))


async def _persist_job_snapshot(job_id: str, label: str, stats) -> None:
    """Mirror job + snapshot into PostgreSQL when available (best-effort)."""
    if not postgres_client.is_available():
        return
    try:
        from app.models.job import IngestionJob
        from app.models.snapshot import GraphSnapshot

        job = await job_store.get(job_id)
        async with postgres_client.session() as db:
            record = await db.get(IngestionJob, job_id)
            if record is None:
                record = IngestionJob(id=job_id, filename=(job or {}).get("filename", label))
                db.add(record)
            record.status = (job or {}).get("status", "COMPLETED")
            record.total_chunks = int((job or {}).get("total_chunks", 0))
            record.processed_chunks = int((job or {}).get("processed_chunks", 0))
            record.entities_extracted = int((job or {}).get("entities_extracted", 0))
            record.relationships_extracted = int((job or {}).get("relationships_extracted", 0))
            record.error_message = (job or {}).get("error_message")

            snapshot = GraphSnapshot(
                id=str(uuid.uuid4()),
                snapshot_label=label[:100],
                node_count=stats.node_count,
                edge_count=stats.edge_count,
                community_count=stats.community_count,
                community_summaries={},
                centrality_metrics={},
            )
            db.add(snapshot)
    except Exception as exc:  # pragma: no cover - optional database
        logger.warning("PostgreSQL persistence skipped: %s", exc)
