"""Job telemetry store.

Redis is the source of truth in production so the FastAPI SSE endpoint can observe
Celery worker progress across processes. An in-process dictionary backs demo mode.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core import redis_client

_TTL_SECONDS = 24 * 60 * 60
_PREFIX = "job:"
_memory: dict[str, dict[str, Any]] = {}

STAGES: list[tuple[str, str, int]] = [
    ("QUEUED", "Queued", 0),
    ("PARSING", "PyMuPDF Page Parser", 8),
    ("CHUNKING", "Semantic Token Chunker", 16),
    ("EXTRACTING", "Structured LLM Extraction", 32),
    ("RESOLVING", "Entity Resolution Cascade", 58),
    ("INDEXING", "Cypher UNWIND + Vector Upsert", 82),
    ("CLUSTERING", "Community Detection", 94),
    ("COMPLETED", "Completed", 100),
]

STAGE_INDEX = {name: index for index, (name, _, _) in enumerate(STAGES)}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_job(filename: str) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "filename": filename,
        "status": "QUEUED",
        "stage": "Queued",
        "stage_index": 0,
        "percent": 0.0,
        "total_chunks": 0,
        "processed_chunks": 0,
        "entities_extracted": 0,
        "relationships_extracted": 0,
        "counts_by_type": {},
        "document_count": 0,
        "error_message": None,
        "created_at": _now(),
        "updated_at": _now(),
        "completed_at": None,
    }
    _memory[job_id] = job
    return job


async def save(job: dict[str, Any]) -> None:
    job_id = job["job_id"]
    job["updated_at"] = _now()
    _memory[job_id] = job
    await redis_client.set_json(f"{_PREFIX}{job_id}", job, ttl=_TTL_SECONDS)
    await redis_client.publish(f"job_progress:{job_id}", job)


async def get(job_id: str) -> dict[str, Any] | None:
    cached = await redis_client.get_json(f"{_PREFIX}{job_id}")
    if cached:
        _memory[job_id] = cached
        return cached
    return _memory.get(job_id)


async def update(job_id: str, **fields: Any) -> dict[str, Any] | None:
    job = await get(job_id)
    if job is None:
        return None
    stage = fields.pop("status", None) or fields.pop("stage_name", None)
    if stage and stage in STAGE_INDEX:
        fields["status"] = stage
        _, label, percent = STAGES[STAGE_INDEX[stage]]
        fields["stage"] = label
        fields["stage_index"] = STAGE_INDEX[stage]
        if stage == "COMPLETED":
            fields["percent"] = 100.0
            fields["completed_at"] = _now()
        else:
            # Keep the floor of the stage; live counters may push it higher.
            fields.setdefault("percent", float(percent))
    job.update(fields)
    await save(job)
    return job


async def fail(job_id: str, message: str) -> dict[str, Any] | None:
    job = await get(job_id)
    if job is None:
        return None
    job.update(
        {
            "status": "FAILED",
            "stage": "Failed",
            "error_message": message,
            "completed_at": _now(),
            "updated_at": _now(),
        }
    )
    await save(job)
    return job
