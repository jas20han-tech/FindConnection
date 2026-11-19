"""Incremental (self-evolving) graph tests: accumulate, dedupe, evidence."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.graph.repository import InMemoryGraphRepository
from app.ingestion import verification
from app.ingestion.chunker import Chunk
from app.ingestion.parser import ParsedDocument
from app.ingestion.resolver import ResolvedGraph


def _document(pages: list[str], filename: str = "doc.pdf", title: str = "Doc") -> ParsedDocument:
    return ParsedDocument(
        doc_hash="c" * 64,
        filename=filename,
        title=title,
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


def _evidence(doc: str, page: int, quote: str) -> dict:
    return {
        "doc": doc,
        "page": page,
        "quote": quote,
        "quote_verified": True,
        "chunk_id": f"{doc}-chunk",
    }


# --------------------------------------------------------------------------- repository
def test_two_documents_accumulate_without_replacing(tmp_path: Path):
    snapshot = tmp_path / "graph.json"

    async def scenario():
        repository = InMemoryGraphRepository(seed=False, persist=True, snapshot_path=snapshot)
        await repository.initialize()

        await repository.upsert_graph(
            [
                {
                    "id": "alice",
                    "name": "Alice",
                    "type": "PERSON",
                    "description": "Alice founded Beta Labs.",
                    "evidence": [_evidence("first.pdf", 1, "Alice founded Beta Labs.")],
                },
                {
                    "id": "beta_labs",
                    "name": "Beta Labs",
                    "type": "COMPANY",
                    "evidence": [_evidence("first.pdf", 1, "Beta Labs was founded by Alice.")],
                },
            ],
            [
                {
                    "id": "alice__founded__beta_labs",
                    "source": "alice",
                    "target": "beta_labs",
                    "type": "FOUNDED",
                    "description": "Alice founded Beta Labs.",
                    "evidence": [_evidence("first.pdf", 1, "Alice founded Beta Labs.")],
                }
            ],
            source_doc="First",
            source_chunk_id="first-1",
        )

        await repository.upsert_graph(
            [
                {
                    "id": "alice",
                    "name": "Alice",
                    "type": "PERSON",
                    "description": "Alice leads Beta Labs.",
                    "evidence": [_evidence("second.pdf", 2, "Alice leads Beta Labs.")],
                },
                {
                    "id": "carol",
                    "name": "Carol",
                    "type": "PERSON",
                    "evidence": [_evidence("second.pdf", 2, "Carol works with Alice.")],
                },
            ],
            [
                {
                    "id": "alice__related_to__carol",
                    "source": "alice",
                    "target": "carol",
                    "type": "RELATED_TO",
                    "description": "Carol works with Alice.",
                    "evidence": [_evidence("second.pdf", 2, "Carol works with Alice.")],
                },
                {
                    # Reverse of the same symmetric relation: must merge, not duplicate.
                    "id": "carol__related_to__alice",
                    "source": "carol",
                    "target": "alice",
                    "type": "RELATED_TO",
                    "description": "Alice and Carol collaborate.",
                    "evidence": [_evidence("second.pdf", 2, "Alice and Carol collaborate.")],
                },
            ],
            source_doc="Second",
            source_chunk_id="second-1",
        )

        nodes, edges = await repository.get_all()
        stats = await repository.stats()

        reloaded = InMemoryGraphRepository(
            seed=False, persist=True, snapshot_path=snapshot
        )
        await reloaded.initialize()
        reloaded_nodes, reloaded_edges = await reloaded.get_all()
        return nodes, edges, stats, reloaded_nodes, reloaded_edges

    nodes, edges, stats, reloaded_nodes, reloaded_edges = asyncio.run(scenario())

    assert stats.node_count == 3
    assert stats.document_count == 2

    alice = next(node for node in nodes if node.id == "alice")
    assert alice.mention_count == 2
    assert {"First", "Second"} == set(alice.documents)
    assert {item["doc"] for item in alice.evidence} == {"first.pdf", "second.pdf"}

    symmetric = [edge for edge in edges if edge.type == "RELATED_TO"]
    assert len(symmetric) == 1
    assert symmetric[0].documents == ["Second"]
    assert len(symmetric[0].evidence) == 2

    assert len(reloaded_edges) == 2
    reloaded_alice = next(node for node in reloaded_nodes if node.id == "alice")
    assert len(reloaded_alice.evidence) == 2


# --------------------------------------------------------------------------- export
def test_attach_evidence_merges_previous_documents(tmp_path: Path):
    document = _document(
        ["Alice founded Beta Labs in 2020."],
        filename="second.pdf",
        title="Second",
    )
    resolved = ResolvedGraph(
        entities=[
            {"id": "alice", "name": "Alice", "type": "PERSON", "aliases": []},
            {"id": "beta_labs", "name": "Beta Labs", "type": "COMPANY", "aliases": []},
        ],
        relationships=[
            {
                "id": "alice__founded__beta_labs",
                "source": "alice",
                "target": "beta_labs",
                "type": "FOUNDED",
                "description": "Alice founded Beta Labs in 2020.",
                "strength": 9,
                "source_chunk_id": "chunk-1",
                "source_page": 1,
            }
        ],
    )
    chunks = [_chunk("chunk-1", "Alice founded Beta Labs in 2020.", 1)]

    verification.attach_resolved_evidence(document, resolved, chunks)
    assert resolved.entities[0]["evidence"][0]["doc"] == "second.pdf"

    network = verification.build_verification_network(document, resolved, chunks)
    assert network["summary"]["items_without_evidence"] == 0

    older_node = {
        "id": "alice",
        "name": "Alice",
        "documents": ["First"],
        "evidence": [_evidence("first.pdf", 1, "Alice founded Beta Labs.")],
    }
    older_edge = {
        "id": "alice__founded__beta_labs",
        "source": "alice",
        "target": "beta_labs",
        "type": "FOUNDED",
        "documents": ["First"],
        "evidence": [_evidence("first.pdf", 1, "Alice founded Beta Labs.")],
    }
    verification.attach_evidence(network, [older_node], [older_edge])

    alice = next(node for node in network["nodes"] if node["id"] == "alice")
    assert {item["doc"] for item in alice["evidence"]} == {"first.pdf", "second.pdf"}
    assert alice["documents"] == ["First", "Second"]

    edge = network["edges"][0]
    assert {item["doc"] for item in edge["evidence"]} == {"first.pdf", "second.pdf"}
    assert edge["documents"] == ["First", "Second"]
    assert network["documents"] == ["First", "Second"]
    assert network["summary"]["items_with_verified_evidence"] == len(
        network["nodes"]
    ) + len(network["edges"])


# --------------------------------------------------------------------------- merge quality
def test_specific_type_and_clean_description_replace_generic_artifact(tmp_path: Path):
    """A later, specific extraction upgrades a generic label and parser artifact."""
    snapshot = tmp_path / "graph.json"
    artifact = "A L I C E : T H E F O U N D E R O F B E T A L A B S \u2026"

    async def scenario():
        repository = InMemoryGraphRepository(seed=False, persist=True, snapshot_path=snapshot)
        await repository.initialize()

        await repository.upsert_graph(
            [
                {
                    "id": "alice",
                    "name": "Alice",
                    "type": "ORGANIZATION",
                    "description": artifact,
                    "evidence": [_evidence("first.pdf", 1, "Alice founded Beta Labs.")],
                }
            ],
            [],
            source_doc="first.pdf",
            source_chunk_id="first-chunk",
        )
        await repository.upsert_graph(
            [
                {
                    "id": "alice",
                    "name": "Alice",
                    "type": "PERSON",
                    "description": "Alice founded Beta Labs in 2020.",
                    "evidence": [_evidence("second.pdf", 1, "Alice founded Beta Labs in 2020.")],
                }
            ],
            [],
            source_doc="second.pdf",
            source_chunk_id="second-chunk",
        )

        nodes, _ = await repository.get_all()
        alice = next(node for node in nodes if node.id == "alice")
        assert alice.type == "PERSON"
        assert alice.description == "Alice founded Beta Labs in 2020."
        assert alice.documents == ["first.pdf", "second.pdf"]

    asyncio.run(scenario())


def test_reset_for_document_clears_even_when_the_title_repeats(tmp_path: Path):
    """Replace mode: every upload starts clean, including a re-upload of the same file."""
    snapshot = tmp_path / "graph.json"

    async def scenario():
        repository = InMemoryGraphRepository(seed=False, persist=True, snapshot_path=snapshot)
        await repository.initialize()
        await repository.upsert_graph(
            [
                {
                    "id": "alice",
                    "name": "Alice",
                    "type": "PERSON",
                    "evidence": [_evidence("first.pdf", 1, "Alice founded Beta Labs.")],
                }
            ],
            [],
            source_doc="Doc",
            source_chunk_id="first-chunk",
        )
        nodes, _ = await repository.get_all()
        assert nodes

        await repository.reset_for_document("Doc")

        nodes, edges = await repository.get_all()
        assert nodes == []
        assert edges == []
        assert (await repository.stats()).document_count == 0

    asyncio.run(scenario())


