"""Tests for the evidence-backed verification network export."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ingestion import verification
from app.ingestion.chunker import Chunk
from app.ingestion.parser import ParsedDocument
from app.ingestion.resolver import ResolvedGraph
from app.main import app


# --------------------------------------------------------------------------- helpers
def _document(pages: list[str], filename: str = "doc.pdf") -> ParsedDocument:
    return ParsedDocument(
        doc_hash="a" * 64,
        filename=filename,
        title="Doc",
        pages=pages,
        page_count=len(pages),
        text="\n\n".join(pages),
        metadata={},
    )


def _chunk(chunk_id: str, text: str, page: int) -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        index=0,
        page_number=page,
        token_count=len(text) // 4,
        doc_id="doc_test",
        doc_title="Doc",
    )


def _resolved() -> ResolvedGraph:
    return ResolvedGraph(
        entities=[
            {
                "id": "alice",
                "name": "Alice",
                "type": "PERSON",
                "description": "Alice founded Beta Labs.",
                "mention_count": 1,
                "aliases": [],
            },
            {
                "id": "beta_labs",
                "name": "Beta Labs",
                "type": "COMPANY",
                "description": "Beta Labs was founded by Alice.",
                "mention_count": 1,
                "aliases": [],
            },
            {
                "id": "carol",
                "name": "Carol",
                "type": "PERSON",
                "description": "Beta Labs hired Carol.",
                "mention_count": 1,
                "aliases": [],
            },
        ],
        relationships=[
            {
                "id": "alice__founded__beta_labs",
                "source": "alice",
                "target": "beta_labs",
                "type": "FOUNDED",
                "description": "Alice founded Beta Labs in 2020.",
                "strength": 9,
                "sentiment": "NEUTRAL",
                "date": "2020-01-01",
                "date_confidence": "explicit",
                "source_chunk_id": "c1",
                "source_page": 1,
            },
            {
                "id": "beta_labs__hired__carol",
                "source": "beta_labs",
                "target": "carol",
                "type": "HIRED",
                "description": "Beta Labs hired Carol in 2021.",
                "strength": 7,
                "sentiment": "NEUTRAL",
                "date": "2021-01-01",
                "date_confidence": "explicit",
                "source_chunk_id": "c1",
                "source_page": 1,
            },
        ],
    )


# --------------------------------------------------------------------------- building
def test_build_network_attaches_verified_page_quotes():
    pages = ["Alice founded Beta Labs in 2020. Beta Labs hired Carol in 2021."]
    network = verification.build_verification_network(
        _document(pages), _resolved(), [_chunk("c1", pages[0], 1)]
    )

    assert network["summary"]["node_count"] == 3
    assert network["summary"]["edge_count"] == 2
    assert network["summary"]["items_with_verified_evidence"] == 5
    assert network["summary"]["items_with_unverified_evidence"] == 0

    edge = network["edges"][0]
    assert edge["source_name"] == "Alice"
    assert edge["target_name"] == "Beta Labs"
    assert edge["relation"] == "founded"
    assert edge["evidence"][0]["page"] == 1
    assert edge["evidence"][0]["quote_verified"] is True
    assert "Alice founded Beta Labs" in edge["evidence"][0]["quote"]
    assert edge["evidence_verified"] is True

    node = next(node for node in network["nodes"] if node["name"] == "Alice")
    assert node["evidence"][0]["quote_verified"] is True
    assert node["degree"] == 1

    assert network["source_pages"] == [{"page": 1, "text": pages[0]}]
    assert network["extractor"]["mode"] == "unknown"


def test_build_network_flags_fabricated_quote():
    pages = ["Nothing relevant appears on this page."]
    network = verification.build_verification_network(
        _document(pages),
        _resolved(),
        [_chunk("c1", "Fabricated sentence about Alice and Beta Labs.", 1)],
    )

    assert network["summary"]["items_with_unverified_evidence"] > 0
    assert all(edge["evidence_verified"] is False for edge in network["edges"])
    assert any("not verbatim" in warning for warning in network["warnings"])


def test_build_network_corrects_wrong_page_number():
    pages = ["No relation here.", "Alice founded Beta Labs in 2020."]
    network = verification.build_verification_network(
        _document(pages),
        _resolved(),
        [_chunk("c1", "Alice founded Beta Labs in 2020.", 1)],
    )

    edge = network["edges"][0]
    assert edge["evidence"][0]["page"] == 2
    assert edge["evidence"][0]["quote_verified"] is True


def test_build_network_can_omit_source_text():
    pages = ["Alice founded Beta Labs in 2020."]
    network = verification.build_verification_network(
        _document(pages),
        _resolved(),
        [_chunk("c1", pages[0], 1)],
        include_source_text=False,
    )
    assert "source_pages" not in network


# --------------------------------------------------------------------------- storage
def test_save_list_load_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(verification.settings, "network_dir", tmp_path)

    network = {
        "document": {"filename": "contract.pdf", "generated_at": "2026-01-01T00:00:00Z"},
        "summary": {
            "node_count": 2,
            "edge_count": 1,
            "items_with_verified_evidence": 2,
            "items_with_unverified_evidence": 0,
        },
    }
    path = verification.save_verification_network(network, "contract.pdf")
    assert path.is_file()
    assert path.name.startswith("contract-")
    assert json.loads(path.read_text(encoding="utf-8")) == network

    listing = verification.list_networks()
    assert len(listing) == 1
    assert listing[0]["file"] == path.name
    assert listing[0]["node_count"] == 2
    assert verification.latest_network_name() == path.name
    assert verification.load_network(path.name) == network


def test_load_network_refuses_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(verification.settings, "network_dir", tmp_path)
    with pytest.raises(FileNotFoundError):
        verification.load_network("../../../etc/passwd")


# --------------------------------------------------------------------------- API / pipeline
def _wait_for_completion(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 30
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/v1/upload/{job_id}/status").json()
        if body.get("status") in {"COMPLETED", "FAILED"}:
            return body
        time.sleep(0.2)
    return body


def test_upload_writes_verification_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(verification.settings, "network_dir", tmp_path)
    text = (
        "Nova Materials acquired Peak Alloys in 2025. "
        "Nova Materials supplied Airbus with composite panels. "
        "Peak Alloys operates a foundry in Portugal."
    ).encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/upload",
            files={"file": ("nova.txt", io.BytesIO(text), "text/plain")},
        )
        assert response.status_code == 200
        job = _wait_for_completion(client, response.json()["job_id"])

    assert job["status"] == "COMPLETED", job.get("error_message")
    assert job["network_file"], job.get("network_error")
    assert job["network_error"] is None

    path = tmp_path / job["network_file"]
    assert path.is_file()
    network = json.loads(path.read_text(encoding="utf-8"))
    assert network["document"]["filename"] == "nova.txt"
    assert network["summary"]["node_count"] >= 2
    assert network["summary"]["edge_count"] >= 1
    assert network["source_pages"]
    assert any(edge["evidence_verified"] for edge in network["edges"])


def test_network_api_lists_reads_and_downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(verification.settings, "network_dir", tmp_path)
    network = {
        "schema_version": 1,
        "document": {"filename": "contract.pdf", "generated_at": "2026-01-01T00:00:00Z"},
        "summary": {"node_count": 2, "edge_count": 1},
        "nodes": [],
        "edges": [],
        "warnings": [],
    }
    saved = verification.save_verification_network(network, "contract.pdf")

    with TestClient(app) as client:
        listing = client.get("/api/v1/networks")
        assert listing.status_code == 200
        assert listing.json()["networks"][0]["file"] == saved.name

        latest = client.get("/api/v1/networks/latest")
        assert latest.status_code == 200
        assert latest.json()["document"]["filename"] == "contract.pdf"

        single = client.get(f"/api/v1/networks/{saved.name}")
        assert single.status_code == 200
        assert single.json()["summary"]["node_count"] == 2

        download = client.get(f"/api/v1/networks/{saved.name}/download")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/json"

        missing = client.get("/api/v1/networks/does-not-exist.json")
        assert missing.status_code == 404
