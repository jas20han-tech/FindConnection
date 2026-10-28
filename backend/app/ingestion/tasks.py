"""Celery task definitions and ingestion dispatch.

``USE_CELERY=false`` (default for local dev) runs ingestion on an in-process asyncio
task. ``USE_CELERY=true`` (docker-compose) hands work to the Celery worker, with job
progress shared through Redis so the SSE endpoint sees cross-process updates.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.ingestion.pipeline import run_ingestion

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()

try:  # optional dependency
    from celery import Celery

    celery_app = Celery(
        "graphrag",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        task_time_limit=900,
        task_soft_time_limit=840,
        worker_max_tasks_per_child=50,
        broker_connection_retry_on_startup=True,
    )

    @celery_app.task(name="ingestion.process_document", bind=True)
    def process_document(self, job_id: str, file_path: str, filename: str) -> dict[str, str]:
        logger.info("Celery worker picked up job %s (%s)", job_id, filename)
        asyncio.run(run_ingestion(job_id, file_path, filename))
        return {"job_id": job_id, "status": "dispatched"}

except Exception:  # pragma: no cover - celery not installed
    celery_app = None

    def process_document(job_id: str, file_path: str, filename: str):  # type: ignore[misc]
        raise RuntimeError("Celery is not installed")


async def dispatch_ingestion(job_id: str, file_path: str, filename: str) -> str:
    """Queue ingestion via Celery when enabled, else run in-process."""
    if settings.use_celery and celery_app is not None:
        try:
            process_document.delay(job_id, file_path, filename)
            return "celery"
        except Exception as exc:
            logger.warning("Celery dispatch failed (%s) — running inline", exc)

    task = asyncio.create_task(run_ingestion(job_id, file_path, filename))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return "inline"
