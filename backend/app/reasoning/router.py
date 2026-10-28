"""Semantic intent routing.

Heuristics run first (deterministic, sub-millisecond). Only when the intent is
ambiguous does the router ask the LLM to classify, so most queries never incur a
network round-trip.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.core import llm
from app.graph.repository import GraphRepository
from app.schemas.types import QueryMode

logger = logging.getLogger(__name__)

IMPACT_PATTERNS = [
    r"\bwhat happens if\b",
    r"\bimpact\b",
    r"\bcascade\b",
    r"\bceases? (?:operations|to exist)\b",
    r"\bfails?\b",
    r"\bdisrupt(?:ion|ed|s)?\b",
    r"\bremove[sd]?\b",
    r"\bshuts? down\b",
    r"\bgoes? (?:bankrupt|offline)\b",
    r"\brisk if\b",
    r"\bsever(?:ed|ance)?\b",
]
TEMPORAL_PATTERNS = [
    r"\btimeline\b",
    r"\bover time\b",
    r"\bhistory\b",
    r"\bevolv(?:e|ed|ing|ution)\b",
    r"\bprogression\b",
    r"\bbetween (?:19|20)\d{2} and (?:19|20)\d{2}\b",
    r"\b(?:19|20)\d{2}\b",
    r"\bbefore\b",
    r"\bafter\b",
    r"\bwhen did\b",
    r"\bchanged? (?:since|between)\b",
]
CONNECTION_PATTERNS = [
    r"\bconnect(?:ed|ion|s)?\b",
    r"\brelat(?:ed|ionship|e)\b",
    r"\bpath\b",
    r"\blinked?\b",
    r"\bhow (?:does|do|is|are)\b.+\b(?:to|with)\b",
    r"\bbetween\b.+\band\b",
    r"\bchain\b",
    r"\broute\b",
]
GLOBAL_PATTERNS = [
    r"\bsummari[sz]e\b",
    r"\boverview\b",
    r"\blandscape\b",
    r"\becosystem\b",
    r"\bclusters?\b",
    r"\bmonopol(?:y|ies|istic)\b",
    r"\bthemes?\b",
    r"\bmain (?:players|actors|trends)\b",
    r"\bstate of\b",
]


@dataclass(slots=True)
class RouteDecision:
    mode: QueryMode
    seed_ids: list[str] = field(default_factory=list)
    seed_names: list[str] = field(default_factory=list)
    rationale: str = ""
    confidence: float = 0.5
    used_llm: bool = False

    @property
    def seeds(self) -> list[str]:
        return self.seed_ids


def score_patterns(query: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, query, re.IGNORECASE))


async def extract_seeds(query: str, repository: GraphRepository) -> tuple[list[str], list[str]]:
    """Find graph entities mentioned in the query, ordered by appearance."""
    nodes, _ = await repository.get_all()
    lowered = query.lower()
    hits: list[tuple[int, str, str]] = []
    for node in nodes:
        for name in [node.name, *node.aliases]:
            needle = name.lower().strip()
            if len(needle) < 2:
                continue
            position = lowered.find(needle)
            if position >= 0:
                hits.append((position, node.id, node.name))
                break
    hits.sort(key=lambda item: item[0])
    seen: set[str] = set()
    seed_ids: list[str] = []
    seed_names: list[str] = []
    for _, node_id, name in hits:
        if node_id in seen:
            continue
        seen.add(node_id)
        seed_ids.append(node_id)
        seed_names.append(name)
        if len(seed_ids) >= 4:
            break

    if not seed_ids:
        # Fallback: full-text search on the longest query terms.
        tokens = sorted(
            {token for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", query)},
            key=len,
            reverse=True,
        )[:3]
        for token in tokens:
            for result in await repository.search_entities(token, limit=2):
                if result.id not in seen:
                    seen.add(result.id)
                    seed_ids.append(result.id)
                    seed_names.append(result.name)
            if seed_ids:
                break
    return seed_ids, seed_names


async def classify(query: str, repository: GraphRepository) -> RouteDecision:
    modes = {
        "IMPACT": score_patterns(query, IMPACT_PATTERNS),
        "TEMPORAL": score_patterns(query, TEMPORAL_PATTERNS),
        "CONNECTION": score_patterns(query, CONNECTION_PATTERNS),
        "GLOBAL": score_patterns(query, GLOBAL_PATTERNS),
    }
    seed_ids, seed_names = await extract_seeds(query, repository)

    # Explicit connection phrasing wins ties, since it is the most common graph query.
    if modes["CONNECTION"] and len(seed_ids) >= 2:
        modes["CONNECTION"] += 1

    mode = max(modes, key=lambda key: modes[key])
    confidence = min(0.95, 0.55 + modes[mode] * 0.15)
    rationale = f"Heuristic intent: {mode.lower()} ({modes[mode]} signal(s))"
    used_llm = False

    if modes[mode] == 0:
        llm_mode = await llm.classify_intent(query, ["CONNECTION", "IMPACT", "TEMPORAL", "GLOBAL"])
        if llm_mode:
            mode = llm_mode  # type: ignore[assignment]
            confidence = 0.7
            rationale = f"LLM intent classification: {mode.lower()}"
            used_llm = True
        else:
            mode = "GLOBAL"
            rationale = "No strong intent signal; defaulting to global synthesis"

    return RouteDecision(
        mode=mode,  # type: ignore[arg-type]
        seed_ids=seed_ids,
        seed_names=seed_names,
        rationale=rationale,
        confidence=confidence,
        used_llm=used_llm,
    )
