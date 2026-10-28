"""PDF upload and SSE ingestion telemetry."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.config import settings
from app.core import job_store
from app.ingestion.tasks import dispatch_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingestion"])

TERMINAL = {"COMPLETED", "FAILED"}
ALLOWED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown", ".csv"}


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    filename = Path(file.filename or "document.pdf").name
    settings.ensure_upload_dir()
    destination = settings.upload_dir / f"{__import__('uuid').uuid4().hex}_{filename}"

    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    with destination.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {settings.max_upload_mb} MB limit",
                )
            handle.write(chunk)
    await file.close()

    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        with destination.open("rb") as handle:
            magic = handle.read(4)
        if magic != b"%PDF":
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Unsupported file type '{Path(filename).suffix or filename}'. "
                    "Upload a PDF, Markdown, CSV or plain-text document."
                ),
            )

    job = job_store.new_job(filename)
    await job_store.save(job)
    mode = await dispatch_ingestion(job["job_id"], str(destination), filename)
    job = await job_store.get(job["job_id"]) or job

    base = request.url_for("upload_status", job_id=job["job_id"])
    return {
        "job_id": job["job_id"],
        "filename": filename,
        "size_bytes": size,
        "status": job.get("status", "QUEUED"),
        "dispatch": mode,
        "status_url": str(base),
        "stream_url": str(request.url_for("upload_stream", job_id=job["job_id"])),
    }


@router.get("/upload/{job_id}/status", name="upload_status")
async def upload_status(job_id: str) -> dict:
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/upload/{job_id}/stream", name="upload_stream")
async def upload_stream(job_id: str) -> StreamingResponse:
    if await job_store.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def generator():
        last_signature: str | None = None
        idle_ticks = 0
        yield ": connected\n\n"
        while True:
            job = await job_store.get(job_id)
            if job is None:
                yield _sse("error", {"message": "Job disappeared"})
                return
            signature = json.dumps(
                {key: job.get(key) for key in ("percent", "status", "processed_chunks", "entities_extracted", "relationships_extracted")},
                sort_keys=True,
            )
            if signature != last_signature:
                yield _sse("progress", job)
                last_signature = signature
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 30 == 0:
                    yield ": keep-alive\n\n"
            if job.get("status") in TERMINAL:
                return
            await asyncio.sleep(0.35)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
