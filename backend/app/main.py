from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import settings
from app.runtime import init_runtime, runtime_health, shutdown_runtime

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("graphrag")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s (demo_mode=%s)", settings.app_name, settings.demo_mode)
    await init_runtime()
    settings.ensure_upload_dir()
    logger.info("Runtime ready at http://localhost:8000%s", settings.api_v1_prefix)
    yield
    await shutdown_runtime()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Graph RAG intelligence API: hybrid ingestion, Personalized PageRank retrieval, "
        "multi-hop paths, cascade simulation and streaming grounded synthesis."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["system"])
async def health() -> dict:
    return await runtime_health()


@app.get("/", tags=["system"])
async def root() -> dict:
    return {
        "app": settings.app_name,
        "version": "1.0.0",
        "demo_mode": settings.demo_mode,
        "docs": "/docs",
        "api": settings.api_v1_prefix,
        "health": "/health",
    }
