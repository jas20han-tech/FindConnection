"""Three-tier entity resolution and deduplication.

Tier 1 — legal-suffix stripping + normalization (exact match)
Tier 2 — RapidFuzz token-sort ratio within the same entity type (>= 88)
Tier 3 — embedding cosine similarity for still-ambiguous entities (>= 0.92)

The result is a canonical id per entity plus a name -> id map used to rewire every
relationship before it reaches the graph store.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.config import settings
from app.core import llm
from app.graph.repository import merge_type, slugify
from app.ingestion.extractor import ExtractionReport
from app.schemas.graph import GraphNode

logger = logging.getLogger(__name__)

try:  # optional dependency
    from rapidfuzz import fuzz

    def _ratio(a: str, b: str) -> float:
        return float(fuzz.token_sort_ratio(a, b))

except Exception:  # pragma: no cover - optional dependency
    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100.0


LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "l.l.c.",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "co",
    "company",
    "plc",
    "gmbh",
    "ag",
    "sa",
    "s.a.",
    "bv",
    "nv",
    "pty",
    "holdings",
}

TYPE_ALIASES: dict[str, str] = {
    "ORG": "ORGANIZATION",
    "ORGANISATION": "ORGANIZATION",
    "GPE": "LOCATION",
    "TECH": "TECHNOLOGY",
    "MODEL": "TECHNOLOGY",
}

KNOWN_ALIASES: dict[str, str] = {
    "tsucchi": "Keita Amano",
    "mono": "Chiaki Hoshinomori",
    "nobe pro": "Konoha Hoshinomori",
    "nobe-pro": "Konoha Hoshinomori",
    "chiaki nobe-ge indie": "Chiaki Hoshinomori",
    "chiaki nobe ge indie": "Chiaki Hoshinomori",
    "nobe-ge indie": "Chiaki Hoshinomori",
    "nobe ge indie": "Chiaki Hoshinomori",
    "gamers rehab alliance": "Gamers Rehabilitation Alliance",
}

FUZZY_THRESHOLD = 88.0
COSINE_THRESHOLD = 0.92

# When the same name is extracted with different types, the LLM is inconsistent
# rather than describing two entities. Pick the type with the most votes; ties
# fall back to this specificity order.
TYPE_PRIORITY: dict[str, int] = {
    name: index
    for index, name in enumerate(
        [
            "PERSON",
            "ORGANIZATION",
            "COMPANY",
            "LOCATION",
            "EVENT",
            "PRODUCT",
            "TECHNOLOGY",
            "REGULATION",
            "FACTION",
            "ARTIFACT",
            "CONCEPT",
            "CHARACTER",
        ]
    )
}


@dataclass(slots=True)
class ResolvedGraph:
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    merged: int = 0
    created: int = 0
    name_to_id: dict[str, str] = field(default_factory=dict)


def normalize_name(name: str) -> str:
    value = name.lower().strip()
    value = re.sub(r"[''`]s\b", "", value)
    value = re.sub(r"[^\w\s&.-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    words = value.split()
    while words and words[-1].rstrip(".") in LEGAL_SUFFIXES:
        words.pop()
    value = " ".join(words).replace(".", "")
    return value.strip()


def normalize_type(value: str) -> str:
    upper = (value or "ORGANIZATION").upper()
    return TYPE_ALIASES.get(upper, upper)


class EntityResolver:
    def __init__(self, existing_nodes: list[GraphNode]) -> None:
        self._by_normalized: dict[tuple[str, str], GraphNode] = {}
        self._by_name: dict[str, GraphNode] = {}
        self._by_id: dict[str, GraphNode] = {}
        self._used_ids: set[str] = set()
        self._used_normalized: set[str] = set()
        for node in existing_nodes:
            self._by_id[node.id] = node
            self._used_ids.add(node.id)
            for candidate in [node.name, *node.aliases]:
                normalized = normalize_name(candidate)
                if not normalized:
                    continue
                key = (normalized, normalize_type(node.type))
                self._by_normalized.setdefault(key, node)
                self._by_name.setdefault(normalized, node)
                self._used_normalized.add(normalized)

    async def resolve(self, report: ExtractionReport) -> ResolvedGraph:
        graph = ResolvedGraph()
        candidates: dict[str, dict[str, Any]] = {}

        for result in report.results:
            chunk = result.chunk
            for entity in result.extraction.entities:
                raw_name = entity.name.strip()
                normalized = normalize_name(raw_name)
                canonical_override = KNOWN_ALIASES.get(normalized)
                if canonical_override:
                    alias_name = raw_name
                    display_name = canonical_override
                    normalized = normalize_name(canonical_override)
                    from app.ingestion.extractor import KNOWN_TYPES
                    canon_type = KNOWN_TYPES.get(normalized)
                    entity_type = normalize_type(canon_type or entity.type)
                else:
                    alias_name = None
                    display_name = raw_name
                    entity_type = normalize_type(entity.type)
                if not normalized:
                    continue
                # Bucket by normalized name only: the same entity can arrive with
                # different type labels from different chunks.
                bucket = candidates.get(normalized)
                if bucket is None:
                    candidates[normalized] = {
                        "name": display_name,
                        "type": entity_type,
                        "type_votes": {entity_type: 1},
                        "description": entity.description,
                        "mention_count": 1,
                        "aliases": [alias_name] if alias_name and alias_name.lower() != display_name.lower() else [],
                        "chunks": [chunk.id],
                        "page": chunk.page_number,
                    }
                else:
                    bucket["mention_count"] += 1
                    bucket["type_votes"][entity_type] = bucket["type_votes"].get(entity_type, 0) + 1
                    bucket["chunks"].append(chunk.id)
                    if alias_name and alias_name not in bucket["aliases"] and alias_name.lower() != bucket["name"].lower():
                        bucket["aliases"].append(alias_name)
                    # Prefer the most complete surface form as the display name.
                    if display_name.lower() != bucket["name"].lower():
                        if len(display_name) > len(bucket["name"]):
                            bucket["aliases"].append(bucket["name"])
                            bucket["name"] = display_name
                        elif display_name not in bucket["aliases"]:
                            bucket["aliases"].append(display_name)
                    if len(entity.description) > len(bucket["description"]):
                        bucket["description"] = entity.description

        for bucket in candidates.values():
            bucket["type"] = self._pick_type(bucket["type_votes"])

        # Tier 1 + 2 resolution against the existing graph.
        unresolved: list[dict[str, Any]] = []
        for bucket in candidates.values():
            normalized = normalize_name(bucket["name"])
            entity_type = bucket["type"]
            # Exact name/alias matches merge regardless of type label; only the
            # fuzzy and embedding tiers stay type-scoped to avoid false merges.
            existing = self._by_name.get(normalized)
            if existing is None:
                existing = self._by_normalized.get((normalized, entity_type))
            if existing is None:
                existing = self._fuzzy_match(normalized, entity_type, bucket["name"])
            if existing is not None:
                graph.merged += 1
                bucket["id"] = existing.id
                # A specific label replaces a generic fallback, but once a stable
                # label exists it is not flipped by later documents.
                bucket["type"] = merge_type(existing.type, bucket["type"])
                bucket["canonical_name"] = existing.name
                graph.entities.append(self._resolved_entity(bucket, existing.id, existing.name))
                self._register_name(graph, bucket["name"], existing.id)
                self._register_name(graph, existing.name, existing.id)
                for alias in existing.aliases:
                    self._register_name(graph, alias, existing.id)
            else:
                unresolved.append(bucket)

        # Tier 3 + allocate canonical ids for genuinely new entities.
        await self._vector_dedupe(unresolved)
        for bucket in unresolved:
            canonical_name = self._pick_display_name(bucket)
            entity_id = self._allocate_id(canonical_name, bucket)
            bucket["id"] = entity_id
            bucket["canonical_name"] = canonical_name
            graph.created += 1
            graph.entities.append(self._resolved_entity(bucket, entity_id, canonical_name))
            self._used_ids.add(entity_id)
            self._register_name(graph, bucket["name"], entity_id)
            self._register_name(graph, canonical_name, entity_id)
            for alias in bucket.get("aliases", []):
                self._register_name(graph, alias, entity_id)

        graph.relationships = self._rewire_relationships(report, graph)
        logger.info(
            "Resolved %d entities (%d merged into existing, %d new) and %d relationships",
            len(graph.entities),
            graph.merged,
            graph.created,
            len(graph.relationships),
        )
        return graph

    # ------------------------------------------------------------------ tiers
    def _fuzzy_match(self, normalized: str, entity_type: str, display: str) -> GraphNode | None:
        best: tuple[float, GraphNode] | None = None
        for node in self._by_id.values():
            if normalize_type(node.type) != entity_type:
                continue
            for candidate in [node.name, *node.aliases]:
                score = _ratio(normalized, normalize_name(candidate))
                if score >= FUZZY_THRESHOLD and (best is None or score > best[0]):
                    best = (score, node)
        if best:
            logger.debug("Fuzzy merged '%s' with '%s' (%.1f)", display, best[1].name, best[0])
        return best[1] if best else None

    async def _vector_dedupe(self, buckets: list[dict[str, Any]]) -> None:
        """Merge near-identical *new* entities using embedding cosine similarity."""
        if len(buckets) < 2 or not settings.llm_enabled:
            return
        try:
            texts = [f"{bucket['name']}. {bucket['description']}" for bucket in buckets]
            vectors = await llm.embed_texts(texts)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("Vector dedupe skipped: %s", exc)
            return
        if len(vectors) != len(buckets):
            return

        merged_into: dict[int, int] = {}
        for i in range(len(buckets)):
            if i in merged_into:
                continue
            for j in range(i + 1, len(buckets)):
                if j in merged_into:
                    continue
                if buckets[i]["type"] != buckets[j]["type"]:
                    continue
                similarity = _cosine(vectors[i], vectors[j])
                if similarity >= COSINE_THRESHOLD:
                    merged_into[j] = i
                    buckets[i]["mention_count"] += buckets[j]["mention_count"]
                    buckets[i]["aliases"].append(buckets[j]["name"])
                    if len(buckets[j]["description"]) > len(buckets[i]["description"]):
                        buckets[i]["description"] = buckets[j]["description"]
                    logger.debug(
                        "Vector merged '%s' into '%s' (cosine %.3f)",
                        buckets[j]["name"],
                        buckets[i]["name"],
                        similarity,
                    )

        if merged_into:
            kept = [bucket for index, bucket in enumerate(buckets) if index not in merged_into]
            buckets[:] = kept

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _pick_display_name(bucket: dict[str, Any]) -> str:
        names = [bucket["name"], *bucket["aliases"]]
        names.sort(key=lambda value: (len(value.split()), len(value)), reverse=True)
        return names[0].strip()

    @staticmethod
    def _pick_type(type_votes: dict[str, int]) -> str:
        """Majority type, with a specificity tie-break for inconsistent labels."""
        return sorted(
            type_votes.items(),
            key=lambda item: (-item[1], TYPE_PRIORITY.get(item[0], 99)),
        )[0][0]

    def _allocate_id(self, name: str, bucket: dict[str, Any]) -> str:
        base = slugify(name)
        candidate = base
        suffix = 2
        key = normalize_name(name)
        while candidate in self._used_ids or key in self._used_normalized:
            candidate = f"{base}_{suffix}"
            suffix += 1
        self._used_normalized.add(key)
        return candidate

    def _resolved_entity(
        self, bucket: dict[str, Any], entity_id: str, canonical_name: str
    ) -> dict[str, Any]:
        aliases = sorted({alias for alias in bucket["aliases"] if alias and alias != canonical_name})
        return {
            "id": entity_id,
            "name": canonical_name,
            "type": bucket["type"],
            "description": bucket["description"],
            "mention_count": bucket["mention_count"],
            "aliases": aliases,
            "year": bucket.get("year"),
        }

    @staticmethod
    def _register_name(graph: ResolvedGraph, name: str, entity_id: str) -> None:
        for key in {name.lower().strip(), normalize_name(name)}:
            if key:
                graph.name_to_id.setdefault(key, entity_id)

    def _rewire_relationships(
        self, report: ExtractionReport, graph: ResolvedGraph
    ) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for result in report.results:
            chunk = result.chunk
            for relationship in result.extraction.relationships:
                source_id = graph.name_to_id.get(relationship.source.lower().strip()) or graph.name_to_id.get(
                    normalize_name(relationship.source)
                )
                target_id = graph.name_to_id.get(relationship.target.lower().strip()) or graph.name_to_id.get(
                    normalize_name(relationship.target)
                )
                if not source_id or not target_id or source_id == target_id:
                    continue
                rel_type = re.sub(r"[^A-Z0-9_]+", "_", relationship.type.upper()).strip("_") or "RELATED_TO"
                key = (source_id, rel_type, target_id)
                existing = merged.get(key)
                if existing is None:
                    merged[key] = {
                        "id": f"{source_id}__{rel_type.lower()}__{target_id}",
                        "source": source_id,
                        "target": target_id,
                        "type": rel_type,
                        "description": relationship.description,
                        "strength": int(relationship.strength),
                        "sentiment": getattr(relationship, "sentiment", "NEUTRAL"),
                        "date": _normalize_date(relationship.date),
                        "date_confidence": relationship.date_confidence,
                        "source_doc": chunk.doc_title,
                        "source_chunk_id": chunk.id,
                        "source_page": chunk.page_number,
                        "status": "ACTIVE",
                    }
                else:
                    existing["strength"] = max(existing["strength"], int(relationship.strength))
                    if getattr(relationship, "sentiment", None) and relationship.sentiment != "NEUTRAL":
                        existing["sentiment"] = relationship.sentiment
                    if len(relationship.description) > len(existing["description"]):
                        existing["description"] = relationship.description
        return list(merged.values())


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(value))
    if not match:
        return None
    year, month, day = match.group(1), match.group(2) or "01", match.group(3) or "01"
    return f"{year}-{month}-{day}"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def entity_type_histogram(entities: list[dict[str, Any]]) -> Counter[str]:
    return Counter(entity["type"] for entity in entities)
