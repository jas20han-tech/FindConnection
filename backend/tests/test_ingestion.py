from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.graph.repository import InMemoryGraphRepository
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _wait_for_completion(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 30
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/v1/upload/{job_id}/status").json()
        if body.get("status") in {"COMPLETED", "FAILED"}:
            return body
        time.sleep(0.2)
    return body


def test_upload_txt_adds_nodes_and_reports_delta(client: TestClient):
    document = (
        "Zephyr Quantum acquired Lumen Fabrication in 2025. "
        "Zephyr Quantum develops quantum annealing hardware and supplies CERN. "
        "Lumen Fabrication operates a photonics foundry in Portugal."
    ).encode("utf-8")

    response = client.post(
        "/api/v1/upload",
        files={"file": ("zephyr.txt", io.BytesIO(document), "text/plain")},
    )
    assert response.status_code == 200
    job = _wait_for_completion(client, response.json()["job_id"])

    assert job["status"] == "COMPLETED", job.get("error_message")
    assert job["nodes_added"] >= 1
    assert job["edges_added"] >= 1

    after = client.get("/api/v1/graph/viewport").json()
    # The upload replaces the seed graph, so the canvas holds only this document.
    assert after["stats"]["node_count"] == job["nodes_added"]
    assert after["stats"]["document_count"] == 1
    assert any(node["name"] == "Zephyr Quantum" for node in after["nodes"])


def test_upload_rejects_unsupported_type(client: TestClient):
    response = client.post(
        "/api/v1/upload",
        files={"file": ("deck.pptx", io.BytesIO(b"PK\x03\x04fake"), "application/vnd.ms-powerpoint")},
    )
    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


def test_second_upload_replaces_previous_document(client: TestClient):
    """A new document must wipe the previous graph, never extend it."""
    documents = {
        "onyx.txt": (
            "Onyx Aerospace acquired Tidal Systems in 2025. "
            "Onyx Aerospace builds stratospheric drones for NATO. "
            "Tidal Systems operates sonar laboratories in Lisbon."
        ),
        "verdant.txt": (
            "Verdant Bio licensed Helix Foundry in 2026. "
            "Verdant Bio develops algal proteins for Unilever. "
            "Helix Foundry runs fermentation plants in Brazil."
        ),
    }

    for filename, text in documents.items():
        response = client.post(
            "/api/v1/upload",
            files={"file": (filename, io.BytesIO(text.encode("utf-8")), "text/plain")},
        )
        assert response.status_code == 200
        job = _wait_for_completion(client, response.json()["job_id"])
        assert job["status"] == "COMPLETED", job.get("error_message")
        assert job["nodes_added"] >= 2

    after = client.get("/api/v1/graph/viewport").json()
    names = {node["name"] for node in after["nodes"]}

    # Only the newest document's graph remains; the previous file is gone.
    assert "Verdant Bio" in names
    assert "Helix Foundry" in names
    assert "Onyx Aerospace" not in names
    assert "Tidal Systems" not in names

    assert after["stats"]["document_count"] == 1
    assert after["documents"] == ["Verdant"]
    assert all(node["documents"] == ["Verdant"] for node in after["nodes"])


def test_document_without_new_relationships_is_still_counted(tmp_path: Path):
    """A document that only repeats entities still replaces the graph and counts as one doc."""
    snapshot = tmp_path / "graph.json"

    async def scenario() -> tuple[int, int, int]:
        repository = InMemoryGraphRepository(seed=True, persist=True, snapshot_path=snapshot)
        await repository.initialize()
        before = (await repository.stats()).document_count
        await repository.upsert_graph(
            [],
            [],
            source_doc="repeat-mentions.pdf",
            source_chunk_id="chunk-1",
        )
        stats = await repository.stats()
        after = stats.document_count

        reloaded = InMemoryGraphRepository(seed=True, persist=True, snapshot_path=snapshot)
        await reloaded.initialize()
        assert (await reloaded.stats()).document_count == after
        return before, after, stats.node_count

    before, after, node_count = asyncio.run(scenario())
    assert before > 1
    assert after == 1
    assert node_count == 0


def test_in_memory_snapshot_survives_restart(tmp_path: Path):
    snapshot = tmp_path / "graph.json"

    async def scenario() -> tuple[int, str | None]:
        first = InMemoryGraphRepository(seed=True, persist=True, snapshot_path=snapshot)
        await first.initialize()
        await first.upsert_graph(
            [
                {
                    "id": "aurora_labs",
                    "name": "Aurora Labs",
                    "type": "COMPANY",
                    "description": "Persisted across restarts.",
                }
            ],
            [],
            source_doc="persistence-test",
            source_chunk_id="chunk-1",
        )

        second = InMemoryGraphRepository(seed=True, persist=True, snapshot_path=snapshot)
        await second.initialize()
        node = await second.get_node("aurora_labs")
        stats = await second.stats()
        return stats.node_count, node.name if node else None

    count, name = asyncio.run(scenario())
    assert name == "Aurora Labs"
    # The replacement snapshot holds only the uploaded document's graph.
    assert count == 1
