from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["graph"]["backend"] == "memory"


def test_viewport(client: TestClient):
    response = client.get("/api/v1/graph/viewport")
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["node_count"] >= 30
    assert len(body["nodes"]) >= 30
    assert len(body["edges"]) >= 40
    assert body["communities"]


def test_entity_search(client: TestClient):
    response = client.get("/api/v1/entity/search", params={"q": "gem"})
    assert response.status_code == 200
    results = response.json()
    assert any(item["id"] == "gemini" for item in results)


def test_neighbors(client: TestClient):
    response = client.get("/api/v1/graph/node/google/neighbors", params={"hops": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["center"]["id"] == "google"
    assert len(body["nodes"]) >= 3


def test_temporal(client: TestClient):
    response = client.get("/api/v1/graph/temporal", params={"year": 2023})
    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2023
    assert body["nodes"]
    assert all((edge["year"] or 0) <= 2023 for edge in body["edges"])


def test_impact(client: TestClient):
    response = client.post("/api/v1/simulate/impact", json={"node_id": "google"})
    assert response.status_code == 200
    body = response.json()
    assert body["removed_node"]["id"] == "google"
    assert body["severity"] in {"LOW", "MODERATE", "HIGH", "CRITICAL"}
    assert body["duration_ms"] >= 0


def test_query_stream(client: TestClient):
    with client.stream(
        "POST",
        "/api/v1/query/stream",
        json={"query": "How does Sundar Pichai connect to the EU AI Act?"},
    ) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    assert "event: graph_context" in text
    assert "event: token" in text
    assert "event: complete" in text

    context_payload = None
    for block in text.split("\n\n"):
        if block.startswith("event: graph_context"):
            data = block.split("data: ", 1)[1]
            context_payload = json.loads(data)
    assert context_payload is not None
    assert context_payload["mode"] == "CONNECTION"
    assert "pichai" in context_payload["path_node_ids"]
    assert "eu_ai_act" in context_payload["path_node_ids"]


def test_query_impact_stream(client: TestClient):
    with client.stream(
        "POST",
        "/api/v1/query/stream",
        json={"query": "What happens if Google LLC ceases operations?"},
    ) as response:
        text = "".join(response.iter_text())
    assert "event: complete" in text
    assert "CRITICAL" in text or "HIGH" in text or "MODERATE" in text or "LOW" in text


def test_communities(client: TestClient):
    response = client.get("/api/v1/graph/communities")
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 3
    assert body[0]["hubs"]
