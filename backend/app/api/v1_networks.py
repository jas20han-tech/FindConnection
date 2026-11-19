"""Verification network endpoints.

Each PDF/Markdown upload writes a standalone JSON network with page + quote
evidence under ``backend/data/networks``. These endpoints list, read and download
those files so the network can be checked against the source document by a human
or by a separate verification agent.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.ingestion.verification import (
    latest_network_name,
    list_networks,
    load_network,
    network_path,
    networks_dir,
)

router = APIRouter(tags=["networks"])


@router.get("/networks")
def list_saved_networks() -> dict:
    """Saved verification networks, newest first."""
    return {"networks": list_networks(), "directory": str(networks_dir())}


@router.get("/networks/latest")
def get_latest_network() -> dict:
    """Return the most recent verification network."""
    name = latest_network_name()
    if name is None:
        raise HTTPException(status_code=404, detail="No verification networks have been saved yet")
    try:
        return load_network(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/networks/{name}")
def get_saved_network(name: str) -> dict:
    """Return a saved verification network by filename."""
    try:
        return load_network(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Network file not found: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Network file is not valid JSON: {exc}") from exc


@router.get("/networks/{name}/download")
def download_saved_network(name: str) -> FileResponse:
    """Download the raw verification network JSON."""
    try:
        path = network_path(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Network file not found: {exc}") from exc
    return FileResponse(path, media_type="application/json", filename=path.name)
