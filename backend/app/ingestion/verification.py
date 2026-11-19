"""Evidence-backed network export for an ingested document.

Every node and edge in the exported JSON carries a page number and a quote taken
from the parsed document. ``quote_verified`` is computed by searching the extracted
page text instead of trusting the extractor, so a human — or a separate verification
agent — can compare the network against the source PDF without sharing the
extractor's reasoning.

The export is written as a standalone JSON file per upload under
``backend/data/networks`` and is also stored in the upload job telemetry.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.ingestion.chunker import Chunk
from app.ingestion.extractor import ExtractionReport
from app.ingestion.parser import ParsedDocument
from app.ingestion.resolver import ResolvedGraph

MAX_EVIDENCE_PER_ITEM = 3
MAX_QUOTE_CHARS = 800

# Typographic variants are folded so a quote still verifies when PyMuPDF emits
# curly quotes or en/em dashes that the extractor copied differently.
_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


# --------------------------------------------------------------------------- text helpers
def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").translate(_TRANSLATION)).strip().casefold()


def _clean_quote(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").translate(_TRANSLATION)).strip()[:MAX_QUOTE_CHARS]


def _name_pattern(names: list[str]) -> re.Pattern[str] | None:
    parts: list[str] = []
    for name in names:
        cleaned = (name or "").strip()
        if not cleaned:
            continue
        escaped = re.escape(cleaned).replace(r"\ ", r"\s+")
        parts.append(rf"(?<!\w){escaped}(?!\w)")
    if not parts:
        return None
    return re.compile("|".join(parts), re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text or "") if part.strip()]


def _contains_any(sentence: str, pattern: re.Pattern[str] | None) -> bool:
    return bool(pattern and pattern.search(sentence))


def _pick_quote(
    chunk_text: str,
    name_groups: list[list[str]],
    page_text: str,
) -> str:
    """Choose the best source-text quote for one node or edge.

    Preference order: a sentence containing every endpoint, then a sentence
    containing any endpoint, then an excerpt around the first mention. The quote
    is always copied from the chunk, never paraphrased from the extractor output.
    """
    patterns = [pattern for names in name_groups if (pattern := _name_pattern(names))]
    sentences = _sentences(chunk_text)

    if patterns:
        both = [
            sentence
            for sentence in sentences
            if all(_contains_any(sentence, pattern) for pattern in patterns)
        ]
        if both:
            return _clean_quote(both[0])
        any_match = [
            sentence for sentence in sentences if any(_contains_any(sentence, p) for p in patterns)
        ]
        if any_match:
            return _clean_quote(any_match[0])

    if patterns:
        for pattern in patterns:
            match = pattern.search(chunk_text)
            if match:
                start = max(0, match.start() - 120)
                excerpt = chunk_text[start : start + MAX_QUOTE_CHARS]
                return _clean_quote(excerpt)
    return _clean_quote(chunk_text)


def _evidence_item(
    quote: str,
    preferred_page: int | None,
    page_texts: dict[int, str],
    *,
    doc: str | None = None,
    chunk_id: str | None = None,
) -> dict[str, Any] | None:
    quote = _clean_quote(quote)
    if not quote:
        return None

    normalized_quote = _normalize(quote)
    candidate_pages: list[int] = []
    if preferred_page is not None and preferred_page in page_texts:
        candidate_pages.append(preferred_page)
    candidate_pages.extend(page for page in page_texts if page not in candidate_pages)

    for page in candidate_pages:
        if normalized_quote in _normalize(page_texts.get(page, "")):
            item: dict[str, Any] = {
                "page": page,
                "quote": quote,
                "quote_verified": True,
            }
            if doc:
                item["doc"] = doc
            if chunk_id:
                item["chunk_id"] = chunk_id
            return item

    item = {"page": preferred_page, "quote": quote, "quote_verified": False}
    if doc:
        item["doc"] = doc
    if chunk_id:
        item["chunk_id"] = chunk_id
    return item


def _collect_node_evidence(
    names: list[str],
    chunks: list[Chunk],
    page_texts: dict[int, str],
    *,
    doc: str | None = None,
) -> list[dict[str, Any]]:
    pattern = _name_pattern(names)
    if pattern is None:
        return []

    evidence: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for chunk in chunks:
        if not pattern.search(chunk.text):
            continue
        quote = _pick_quote(chunk.text, [names], page_texts.get(chunk.page_number, ""))
        item = _evidence_item(
            quote,
            chunk.page_number,
            page_texts,
            doc=doc,
            chunk_id=chunk.id,
        )
        if item is None:
            continue
        key = (item["page"], item["quote"])
        if key in seen:
            continue
        seen.add(key)
        evidence.append(item)
        if len(evidence) >= MAX_EVIDENCE_PER_ITEM:
            break
    return evidence


def _edge_evidence(
    relationship: dict[str, Any],
    entities_by_id: dict[str, dict[str, Any]],
    chunks_by_id: dict[str, Chunk],
    page_texts: dict[int, str],
    *,
    doc: str | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Return the relationship's source quote and the page it belongs to."""
    source_id = relationship.get("source", "")
    target_id = relationship.get("target", "")
    source_entity = entities_by_id.get(source_id, {"name": source_id, "aliases": []})
    target_entity = entities_by_id.get(target_id, {"name": target_id, "aliases": []})
    source_names = [
        source_entity.get("name", ""),
        *list(source_entity.get("aliases") or []),
    ]
    target_names = [
        target_entity.get("name", ""),
        *list(target_entity.get("aliases") or []),
    ]

    chunk = chunks_by_id.get(relationship.get("source_chunk_id") or "")
    preferred_page = relationship.get("source_page")
    if preferred_page is None and chunk is not None:
        preferred_page = chunk.page_number

    if chunk is not None:
        quote = _pick_quote(
            chunk.text,
            [source_names, target_names],
            page_texts.get(chunk.page_number, ""),
        )
    else:
        # No chunk context: only the extractor's own description is available.
        # It verifies only when the extractor copied source text verbatim.
        quote = relationship.get("description", "")
    item = _evidence_item(
        quote,
        preferred_page,
        page_texts,
        doc=doc,
        chunk_id=relationship.get("source_chunk_id"),
    )
    return ([item] if item is not None else []), preferred_page


def attach_resolved_evidence(
    document: ParsedDocument,
    resolved: ResolvedGraph,
    chunks: list[Chunk],
) -> dict[str, int]:
    """Attach per-document evidence to resolved entities and relationships.

    Running this *before* indexing means the graph store accumulates evidence for
    every document, not just the export file. ``doc`` is the original filename so a
    human can open the right PDF, while ``page`` and ``quote`` locate the claim.
    """
    page_texts = {index: text for index, text in enumerate(document.pages, start=1)}
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    entities_by_id = {entity["id"]: entity for entity in resolved.entities}

    nodes_with_evidence = 0
    for entity in resolved.entities:
        names = [entity.get("name", ""), *list(entity.get("aliases") or [])]
        evidence = _collect_node_evidence(
            names,
            chunks,
            page_texts,
            doc=document.filename,
        )
        if evidence:
            entity["evidence"] = evidence
            nodes_with_evidence += 1

    edges_with_evidence = 0
    for relationship in resolved.relationships:
        evidence, preferred_page = _edge_evidence(
            relationship,
            entities_by_id,
            chunks_by_id,
            page_texts,
            doc=document.filename,
        )
        if evidence:
            relationship["evidence"] = evidence
            edges_with_evidence += 1
        if relationship.get("source_page") is None and preferred_page is not None:
            relationship["source_page"] = preferred_page

    return {
        "nodes_with_evidence": nodes_with_evidence,
        "edges_with_evidence": edges_with_evidence,
    }


def _item_evidence(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in item.get("evidence") or [] if isinstance(entry, dict)]


def _merge_evidence(
    target: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    limit: int = 50,
) -> None:
    seen = {
        (
            entry.get("doc") or "",
            entry.get("page"),
            _normalize(entry.get("quote", ""))[:240],
        )
        for entry in target
    }
    for entry in incoming:
        key = (
            entry.get("doc") or "",
            entry.get("page"),
            _normalize(entry.get("quote", ""))[:240],
        )
        if key in seen:
            continue
        seen.add(key)
        target.append(dict(entry))
        if len(target) >= limit:
            break


def attach_evidence(
    network: dict[str, Any],
    graph_nodes: list[Any] | None = None,
    graph_edges: list[Any] | None = None,
) -> dict[str, Any]:
    """Merge accumulated graph evidence into an exported network in place.

    ``build_verification_network`` only sees the current upload. Once the document
    has been indexed, the repository holds evidence from every document that
    asserted the same node or edge. This copies that history into the export and
    recomputes the verified/unverified counters.
    """
    from app.graph.repository import canonical_edge_id

    def _dump(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return {}

    node_sources = {item.get("id"): item for item in map(_dump, graph_nodes or [])}
    edge_sources: dict[str, dict[str, Any]] = {}
    for raw_edge in graph_edges or []:
        edge = _dump(raw_edge)
        edge_id = edge.get("id")
        if edge_id:
            edge_sources[edge_id] = edge
        source, target = edge.get("source"), edge.get("target")
        if source and target:
            edge_sources.setdefault(
                canonical_edge_id(source, target, edge.get("type")),
                edge,
            )

    documents: set[str] = set()

    for node in network.get("nodes") or []:
        source = node_sources.get(node.get("id"))
        if not source:
            continue
        merged = list(_item_evidence(node))
        _merge_evidence(merged, _item_evidence(source))
        node["evidence"] = merged
        node["evidence_verified"] = any(
            entry.get("quote_verified") for entry in merged
        )
        node["mention_count"] = int(
            source.get("mention_count") or node.get("mention_count") or 1
        )
        node["degree"] = int(source.get("degree") or node.get("degree") or 0)
        node_documents = {
            *(node.get("documents") or []),
            *(source.get("documents") or []),
        }
        if node_documents:
            node["documents"] = sorted(node_documents)
            documents.update(node_documents)

    for edge in network.get("edges") or []:
        source_edge = edge_sources.get(edge.get("id") or "")
        if source_edge is None and edge.get("source") and edge.get("target"):
            source_edge = edge_sources.get(
                canonical_edge_id(
                    edge["source"],
                    edge["target"],
                    edge.get("type") or edge.get("relation"),
                )
            )
        if not source_edge:
            continue
        merged = list(_item_evidence(edge))
        _merge_evidence(merged, _item_evidence(source_edge))
        edge["evidence"] = merged
        edge["evidence_verified"] = any(
            entry.get("quote_verified") for entry in merged
        )
        edge["strength"] = max(
            int(edge.get("strength") or 0), int(source_edge.get("strength") or 0)
        ) or int(edge.get("strength") or 5)
        edge_documents = {
            *(edge.get("documents") or []),
            *(source_edge.get("documents") or []),
        }
        if edge_documents:
            edge["documents"] = sorted(edge_documents)
            documents.update(edge_documents)

    items = [*(network.get("nodes") or []), *(network.get("edges") or [])]
    summary = network.setdefault("summary", {})
    summary["items_with_verified_evidence"] = sum(
        1 for item in items if any(e.get("quote_verified") for e in item.get("evidence") or [])
    )
    summary["items_with_unverified_evidence"] = sum(
        1
        for item in items
        if item.get("evidence")
        and not any(e.get("quote_verified") for e in item["evidence"])
    )
    summary["items_without_evidence"] = sum(
        1 for item in items if not item.get("evidence")
    )

    if documents:
        network["documents"] = sorted(documents)
    return network


# --------------------------------------------------------------------------- build
def build_verification_network(
    document: ParsedDocument,
    resolved: ResolvedGraph,
    chunks: list[Chunk],
    report: ExtractionReport | None = None,
    *,
    include_source_text: bool = True,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a self-contained, evidence-backed network description."""
    warnings = list(warnings or [])
    page_texts = {
        index: text for index, text in enumerate(document.pages, start=1)
    }
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    entities_by_id = {entity["id"]: entity for entity in resolved.entities}

    nodes: list[dict[str, Any]] = []
    for entity in resolved.entities:
        names = [entity.get("name", ""), *list(entity.get("aliases") or [])]
        evidence = _item_evidence(entity) or _collect_node_evidence(
            names,
            chunks,
            page_texts,
            doc=document.filename,
        )
        nodes.append(
            {
                "id": entity["id"],
                "name": entity.get("name", ""),
                "type": entity.get("type", "ORGANIZATION"),
                "aliases": list(entity.get("aliases") or []),
                "description": entity.get("description", ""),
                "mention_count": int(entity.get("mention_count", 1)),
                "documents": list(entity.get("documents") or [document.title]),
                "evidence": evidence,
                "evidence_verified": any(item["quote_verified"] for item in evidence),
                "degree": 0,
            }
        )

    from app.graph.repository import canonical_edge_id

    degree: Counter[str] = Counter()
    edge_by_id: dict[str, dict[str, Any]] = {}
    for relationship in resolved.relationships:
        source_id = relationship.get("source", "")
        target_id = relationship.get("target", "")
        source_entity = entities_by_id.get(source_id, {"name": source_id, "aliases": []})
        target_entity = entities_by_id.get(target_id, {"name": target_id, "aliases": []})

        evidence = _item_evidence(relationship)
        preferred_page = relationship.get("source_page")
        if not evidence:
            evidence, preferred_page = _edge_evidence(
                relationship,
                entities_by_id,
                chunks_by_id,
                page_texts,
                doc=document.filename,
            )

        relation_type = str(relationship.get("type") or "RELATED_TO").upper()
        strength = int(relationship.get("strength", 5) or 5)
        edge_id = canonical_edge_id(source_id, target_id, relation_type)

        existing = edge_by_id.get(edge_id)
        if existing is not None:
            # A→B and B→A for a symmetric relation are the same edge.
            _merge_evidence(existing["evidence"], evidence)
            existing["evidence_verified"] = any(
                entry.get("quote_verified") for entry in existing["evidence"]
            )
            continue

        edge_by_id[edge_id] = {
            "id": edge_id,
            "source": source_id,
            "source_name": source_entity.get("name", source_id),
            "target": target_id,
            "target_name": target_entity.get("name", target_id),
            "relation": relation_type.lower(),
            "type": relation_type,
            "label": relation_type.replace("_", " ").lower(),
            "description": relationship.get("description", ""),
            "strength": strength,
            "confidence": round(max(0.1, min(1.0, strength / 10)), 2),
            "sentiment": relationship.get("sentiment", "NEUTRAL"),
            "date": relationship.get("date"),
            "date_confidence": relationship.get("date_confidence", "unknown"),
            "source_chunk_id": relationship.get("source_chunk_id"),
            "source_page": preferred_page,
            "documents": list(relationship.get("documents") or [document.title]),
            "evidence": evidence,
            "evidence_verified": any(item["quote_verified"] for item in evidence),
        }
        degree[source_id] += 1
        degree[target_id] += 1

    edges = list(edge_by_id.values())

    for node in nodes:
        node["degree"] = degree.get(node["id"], 0)

    verified = sum(
        1 for item in [*nodes, *edges] if any(e["quote_verified"] for e in item["evidence"])
    )
    unverified = sum(
        1
        for item in [*nodes, *edges]
        if item["evidence"] and not any(e["quote_verified"] for e in item["evidence"])
    )
    without_evidence = sum(1 for item in [*nodes, *edges] if not item["evidence"])

    if unverified:
        warnings.append(
            f"{unverified} item(s) have a quote that is not verbatim in the extracted page "
            "text — review them manually."
        )
    if without_evidence:
        warnings.append(f"{without_evidence} item(s) have no evidence quote at all.")

    if report is None:
        mode = "unknown"
    elif report.llm_chunks and report.heuristic_chunks:
        mode = "mixed"
    elif report.llm_chunks:
        mode = "llm"
    elif report.heuristic_chunks:
        mode = "heuristic"
    else:
        mode = "unknown"

    pages_with_text = sum(1 for text in document.pages if text.strip())
    network: dict[str, Any] = {
        "schema_version": 1,
        "document": {
            "filename": document.filename,
            "title": document.title,
            "doc_id": document.document_id,
            "page_count": document.page_count,
            "pages_with_text": pages_with_text,
            "text_chars": len(document.text),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "extractor": {
            "mode": mode,
            "chunk_count": len(chunks),
            "llm_chunks": report.llm_chunks if report else 0,
            "heuristic_chunks": report.heuristic_chunks if report else 0,
            "failed_chunks": report.failed_chunks if report else 0,
        },
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "counts_by_type": dict(Counter(node["type"] for node in nodes)),
            "items_with_verified_evidence": verified,
            "items_with_unverified_evidence": unverified,
            "items_without_evidence": without_evidence,
        },
        "verification": {
            "quote_verified": (
                "true means the quote was found verbatim in the extracted text of the "
                "cited page (whitespace normalized); false means the quote needs manual review."
            ),
            "how_to_check": [
                "Open the source document at evidence.page for each node and edge.",
                "Search that page for evidence.quote (whitespace normalized).",
                "Normalize typography before comparing: PDF text often uses curly quotes "
                "and em dashes ('\u2019' vs \"'\", '\u2014' vs '-') where the quote uses ASCII.",
                "A decorative drop cap may print the first letter separately from the rest "
                "of the word (e.g. PDF 'F' + 'rom the ...' vs quote 'From the ...').",
                "Alternatively, compare the quote with the matching page in source_pages, "
                "which holds the exact extracted text used for verification.",
                "Confirm the quote actually states the node or edge.label being claimed.",
                "Treat any item with evidence_verified=false as unconfirmed.",
            ],
        },
        "nodes": nodes,
        "edges": edges,
        "warnings": warnings,
    }
    if include_source_text:
        network["source_pages"] = [
            {"page": page, "text": text}
            for page, text in page_texts.items()
            if text.strip()
        ]
    return network


# --------------------------------------------------------------------------- storage
def networks_dir() -> Path:
    directory = Path(settings.network_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe_stem(filename: str) -> str:
    stem = Path(filename or "document").stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    return stem or "document"


def _unique_path(stem: str) -> Path:
    directory = networks_dir()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    candidate = directory / f"{stem}-{stamp}.json"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{stamp}-{counter}.json"
        counter += 1
    return candidate


def save_verification_network(
    network: dict[str, Any],
    source_filename: str,
    output_path: str | Path | None = None,
) -> Path:
    """Write the network JSON and return its path."""
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = _unique_path(_safe_stem(source_filename))
    path.write_text(
        json.dumps(network, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _resolve(name: str) -> Path:
    """Resolve a saved network filename, refusing path traversal."""
    cleaned = Path(name).name
    if not cleaned.endswith(".json"):
        cleaned += ".json"
    path = networks_dir() / cleaned
    if not path.is_file():
        raise FileNotFoundError(cleaned)
    return path


def list_networks() -> list[dict[str, Any]]:
    """List saved networks newest first with lightweight metadata."""
    directory = networks_dir()
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        entry: dict[str, Any] = {"file": path.name, "size_bytes": path.stat().st_size}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            document = data.get("document") or {}
            summary = data.get("summary") or {}
            entry.update(
                {
                    "source_filename": document.get("filename"),
                    "generated_at": document.get("generated_at"),
                    "node_count": summary.get("node_count"),
                    "edge_count": summary.get("edge_count"),
                    "items_with_verified_evidence": summary.get(
                        "items_with_verified_evidence"
                    ),
                    "items_with_unverified_evidence": summary.get(
                        "items_with_unverified_evidence"
                    ),
                }
            )
        except (OSError, ValueError):
            entry["error"] = "unreadable JSON"
        items.append(entry)
    return items


def latest_network_name() -> str | None:
    listing = list_networks()
    return listing[0]["file"] if listing else None


def load_network(name: str) -> dict[str, Any]:
    path = _resolve(name)
    return json.loads(path.read_text(encoding="utf-8"))


def network_path(name: str) -> Path:
    return _resolve(name)
