"""High-throughput extraction: GPT-4o-mini Structured Outputs with a deterministic
heuristic fallback.

The LLM path runs with ``asyncio.Semaphore(settings.extraction_concurrency)`` so a
50-page document can be processed in seconds. The heuristic path is fully offline and
keeps demo mode (and tests) self-contained.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.config import settings
from app.core import llm
from app.ingestion.chunker import Chunk
from app.schemas.extraction import ChunkGraphExtraction, ExtractedEntity, ExtractedRelationship
from app.schemas.types import EntityType

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int, int], Awaitable[None]]

SYSTEM_PROMPT = """You are a precise knowledge-graph extraction engine.
Extract only entities and relationships explicitly supported by the text.
Rules:
- Use canonical, capitalized entity names (prefer 'Google' over 'Google LLC' when the text says Google).
- Allowed entity types: PERSON, COMPANY, PRODUCT, TECHNOLOGY, LOCATION, REGULATION, EVENT, ORGANIZATION.
- Relationship types are UPPER_SNAKE_CASE verbs: CEO_OF, DEVELOPED, INVESTED_IN, ACQUIRED, SUPPLIES, REGULATES, REGULATED_BY, PARTNERED_WITH, COMPETES_WITH, FOUNDED, PUBLISHED, OWNS, HOSTS, USES, BUILT_ON.
- Every relationship must connect two entities that appear in the entities list.
- Include a date (YYYY-MM-DD) only when the text supports it; otherwise null and date_confidence 'unknown'.
- Never infer facts that are not in the text. Descriptions must be one sentence.
- If the text contains no meaningful entities, return empty lists."""


@dataclass(slots=True)
class ChunkExtraction:
    chunk: Chunk
    extraction: ChunkGraphExtraction


@dataclass(slots=True)
class ExtractionReport:
    results: list[ChunkExtraction] = field(default_factory=list)
    llm_chunks: int = 0
    heuristic_chunks: int = 0
    failed_chunks: int = 0


# --------------------------------------------------------------------------- heuristic
KNOWN_TYPES: dict[str, EntityType] = {
    "google": "COMPANY",
    "alphabet": "COMPANY",
    "deepmind": "COMPANY",
    "google deepmind": "COMPANY",
    "openai": "COMPANY",
    "microsoft": "COMPANY",
    "nvidia": "COMPANY",
    "tsmc": "COMPANY",
    "asml": "COMPANY",
    "samsung": "COMPANY",
    "samsung electronics": "COMPANY",
    "smic": "COMPANY",
    "anthropic": "COMPANY",
    "amazon": "COMPANY",
    "meta": "COMPANY",
    "meta platforms": "COMPANY",
    "mistral": "COMPANY",
    "mistral ai": "COMPANY",
    "apple": "COMPANY",
    "tesla": "COMPANY",
    "waymo": "COMPANY",
    "sundar pichai": "PERSON",
    "sam altman": "PERSON",
    "elon musk": "PERSON",
    "satya nadella": "PERSON",
    "jensen huang": "PERSON",
    "gemini": "TECHNOLOGY",
    "gemini ai": "TECHNOLOGY",
    "gpt-4": "TECHNOLOGY",
    "gpt-4o": "TECHNOLOGY",
    "chatgpt": "PRODUCT",
    "claude": "TECHNOLOGY",
    "llama": "TECHNOLOGY",
    "llama 3": "TECHNOLOGY",
    "mistral large": "TECHNOLOGY",
    "copilot": "PRODUCT",
    "microsoft copilot": "PRODUCT",
    "h100": "PRODUCT",
    "nvidia h100": "PRODUCT",
    "azure": "PRODUCT",
    "aws": "PRODUCT",
    "aws bedrock": "PRODUCT",
    "youtube": "PRODUCT",
    "eu ai act": "REGULATION",
    "ai act": "REGULATION",
    "gdpr": "REGULATION",
    "us chips act": "REGULATION",
    "chips act": "REGULATION",
    "nist ai rmf": "REGULATION",
    "ai rmf": "REGULATION",
    "european commission": "ORGANIZATION",
    "european union": "ORGANIZATION",
    "european parliament": "ORGANIZATION",
    "uk ai safety institute": "ORGANIZATION",
    "nist": "ORGANIZATION",
    "ftc": "ORGANIZATION",
    "federal trade commission": "ORGANIZATION",
    "bletchley park ai safety summit": "EVENT",
    "ai safety summit": "EVENT",
}

REGULATION_WORDS = {
    "act",
    "regulation",
    "directive",
    "framework",
    "rule",
    "policy",
    "controls",
    "treaty",
    "law",
    "bill",
    "standard",
}
ORGANIZATION_WORDS = {
    "commission",
    "institute",
    "agency",
    "ministry",
    "committee",
    "council",
    "bureau",
    "authority",
    "court",
    "parliament",
    "department",
    "university",
    "foundation",
    "association",
    "lab",
    "laboratory",
}
EVENT_WORDS = {"summit", "conference", "forum", "expo", "hearing", "election", "merger", "acquisition"}
PRODUCT_WORDS = {"pro", "suite", "platform", "service", "app", "assistant", "cloud", "api", "model"}
TECH_WORDS = {"ai", "gpt", "llm", "transformer", "model", "chip", "gpu", "tpu", "cuda"}
COMPANY_SUFFIXES = {"inc", "corp", "ltd", "llc", "plc", "co", "group", "holdings", "technologies"}

STOPWORD_NAMES = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "However",
    "In",
    "On",
    "At",
    "By",
    "For",
    "With",
    "And",
    "But",
    "It",
    "Its",
    "They",
    "Their",
    "We",
    "Our",
    "You",
    "Your",
    "He",
    "She",
    "His",
    "Her",
    "As",
    "If",
    "When",
    "While",
    "According",
    "Under",
    "Over",
    "After",
    "Before",
    "Since",
    "During",
    "Between",
    "Among",
    "New",
    "Last",
    "First",
    "Second",
    "Third",
    "Today",
    "Yesterday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
}

RELATION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(acqui(?:red|res|sition)|bought|purchased)\b", re.I), "ACQUIRED"),
    (re.compile(r"\b(invest(?:ed|s|ment)|funding round|raised \$?\d)\b", re.I), "INVESTED_IN"),
    (re.compile(r"\b(partner(?:ed|ship)?|collaborat(?:ed|ion)|teamed up)\b", re.I), "PARTNERED_WITH"),
    (re.compile(r"\b(regulat(?:es|ed|ion|ory)|governs|oversees)\b", re.I), "REGULATES"),
    (re.compile(r"\b(regulated by|subject to|comply|compliance)\b", re.I), "REGULATED_BY"),
    (re.compile(r"\b(suppl(?:ies|ied|ier)|provides chips|ships)\b", re.I), "SUPPLIES"),
    (re.compile(r"\b(develop(?:ed|s|ment)?|built|created|launched|released)\b", re.I), "DEVELOPED"),
    (re.compile(r"\b(ceo|chief executive|appointed)\b", re.I), "CEO_OF"),
    (re.compile(r"\b(founded|co-founded)\b", re.I), "FOUNDED"),
    (re.compile(r"\b(published|issued)\b", re.I), "PUBLISHED"),
    (re.compile(r"\b(owns|owned by|subsidiary)\b", re.I), "OWNS"),
    (re.compile(r"\b(hosts|hosted|runs on|available on)\b", re.I), "HOSTS"),
    (re.compile(r"\b(investigat(?:es|ed|ion)|probe)\b", re.I), "INVESTIGATES"),
    (re.compile(r"\b(compet(?:es|itor|ition)|rival)\b", re.I), "COMPETES_WITH"),
    (re.compile(r"\b(restrict(?:s|ed|ion)|bans|blocked|export controls?)\b", re.I), "RESTRICTS"),
    (re.compile(r"\b(evaluat(?:es|ed|ion)|tested)\b", re.I), "EVALUATES"),
    (re.compile(r"\b(references?|aligns? with)\b", re.I), "REFERENCES"),
    (re.compile(r"\b(uses?|used by|based on|powered by)\b", re.I), "USES"),
]

CANDIDATE_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&.\-']+)(?:\s+(?:(?:of|for|and|the|de|van|von|al)\s+)?"
    r"[A-Z][A-Za-z0-9&.\-']+){0,3})"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

# Sentence-initial conjunctions/prepositions get swept into a candidate because they
# are capitalised. Strip them so "Since Kaelen Vance" becomes "Kaelen Vance".
LEADING_NOISE = {
    "a", "an", "and", "as", "at", "before", "between", "but", "by", "during", "for",
    "from", "however", "if", "in", "into", "its", "meanwhile", "nor", "of", "on", "or",
    "over", "since", "so", "than", "that", "the", "then", "these", "this", "those",
    "though", "through", "to", "under", "until", "when", "where", "while", "with",
    "within", "without", "yet",
    # Sentence-initial discourse markers / gerunds.
    "after", "afterwards", "analyzing", "eventually", "following", "initially",
    "later", "notably", "subsequently", "today", "ultimately",
}
TRAILING_NOISE = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or",
    "the", "to", "with", "partners", "supplies", "regulates",
}
# A job title in front of a name ("CEO of Crimson Lotus") is not part of the entity.
LEADING_ROLE_RE = re.compile(
    r"^(?:ceo|cto|cfo|coo|vp|chief executive officer|chief technology officer|"
    r"chief financial officer|chief operating officer)(?:\s+of\s+|\s+|$)",
    re.I,
)
# Relationship verbs and section labels get swept up as "entities" by the regex
# because they are capitalised (often in ALL CAPS). They are never real nodes.
JUNK_NAMES = {
    "id", "ceo", "cto", "cfo", "coo", "vp", "mr", "ms", "dr", "page", "figure",
    "acquired", "acquires", "announces", "announced", "appoints", "develops",
    "developed", "dissolved", "evaluates", "founded", "hosts", "invested",
    "invests", "launches", "operates", "owns", "partners", "produces", "provides",
    "publishes", "references", "regulates", "restricts", "reveals", "supplies",
    "chapter", "chapters", "section", "sections", "overview", "summary",
    "published date", "archive id",
}


def _clean_candidate(value: str) -> str:
    name = value.strip(" .,;:()[]\"'")
    name = re.sub(r"'s$", "", name)
    name = re.sub(r"\s+", " ", name)
    name = LEADING_ROLE_RE.sub("", name)

    words = name.split()
    while len(words) > 1 and words[0].lower() in LEADING_NOISE:
        words.pop(0)
    while len(words) > 1 and words[-1].lower() in TRAILING_NOISE:
        words.pop()
    return " ".join(words).strip()


def _is_valid_name(name: str) -> bool:
    if len(name) < 2 or len(name) > 64:
        return False
    if name in STOPWORD_NAMES or name.lower() in JUNK_NAMES:
        return False
    words = name.split()
    if all(word in STOPWORD_NAMES for word in words):
        return False
    if name.isdigit() or YEAR_RE.fullmatch(name):
        return False
    if name.lower() in {"ai", "ceo", "cto", "us", "eu", "uk", "am", "pm"}:
        return True
    if len(words) == 1:
        # Single words need to look like an acronym or a known entity.
        return name.isupper() or name.lower() in KNOWN_TYPES
    return True


def infer_entity_type(name: str) -> EntityType:
    lowered = name.lower()
    if lowered in KNOWN_TYPES:
        return KNOWN_TYPES[lowered]
    words = set(re.findall(r"[a-z]+", lowered))
    if words & COMPANY_SUFFIXES:
        return "COMPANY"
    if words & REGULATION_WORDS:
        return "REGULATION"
    if words & EVENT_WORDS:
        return "EVENT"
    if words & ORGANIZATION_WORDS:
        return "ORGANIZATION"
    if words & PRODUCT_WORDS:
        return "PRODUCT"
    if words & TECH_WORDS:
        return "TECHNOLOGY"
    if name.isupper() and len(name) <= 6:
        return "ORGANIZATION"
    return "ORGANIZATION"


def heuristic_extract_chunk(chunk: Chunk) -> ChunkGraphExtraction:
    """Deterministic, dependency-free extraction used when no API key is configured."""
    entities: dict[str, ExtractedEntity] = {}
    relationships: list[ExtractedRelationship] = []
    seen_relationships: set[tuple[str, str, str]] = set()

    for sentence in SENTENCE_SPLIT_RE.split(chunk.text):
        sentence = sentence.strip()
        if len(sentence) < 20:
            continue

        mentions: list[tuple[int, str]] = []
        for match in CANDIDATE_RE.finditer(sentence):
            name = _clean_candidate(match.group(1))
            if not _is_valid_name(name):
                continue
            key = name.lower()
            if key not in {existing.lower() for existing in entities}:
                entities[name] = ExtractedEntity(
                    name=name,
                    type=infer_entity_type(name),
                    description=_truncate(sentence, 220),
                )
            mentions.append((match.start(), name))

        # Collapse duplicates that share a start offset (regex greediness).
        unique: list[tuple[int, str]] = []
        for position, name in mentions:
            if unique and unique[-1][1].lower() == name.lower():
                continue
            unique.append((position, name))

        if len(unique) < 2:
            continue

        year_match = YEAR_RE.search(sentence)
        date = f"{year_match.group(1)}-01-01" if year_match else None

        for index in range(min(len(unique) - 1, 4)):
            source_pos, source_name = unique[index]
            target_pos, target_name = unique[index + 1]
            if source_name.lower() == target_name.lower():
                continue
            between = sentence[source_pos + len(source_name) : target_pos]
            rel_type = "RELATED_TO"
            strength = 4
            for pattern, candidate_type in RELATION_PATTERNS:
                if pattern.search(between):
                    rel_type = candidate_type
                    strength = 8 if candidate_type != "RELATED_TO" else 5
                    break
            key = (source_name.lower(), rel_type, target_name.lower())
            if key in seen_relationships:
                continue
            seen_relationships.add(key)
            relationships.append(
                ExtractedRelationship(
                    source=source_name,
                    target=target_name,
                    type=rel_type,
                    description=_truncate(sentence, 240),
                    strength=strength,
                    date=date,
                    date_confidence="inferred" if date else "unknown",
                )
            )

    return ChunkGraphExtraction(entities=list(entities.values())[:16], relationships=relationships[:24])


def _truncate(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


class ExtractionEngine:
    def __init__(self, concurrency: int | None = None) -> None:
        self.concurrency = concurrency or settings.extraction_concurrency
        self._semaphore = asyncio.Semaphore(self.concurrency)

    async def extract(
        self,
        chunks: list[Chunk],
        on_progress: ProgressCallback | None = None,
    ) -> ExtractionReport:
        report = ExtractionReport()
        if not chunks:
            return report

        total = len(chunks)
        completed = 0
        lock = asyncio.Lock()

        async def process(chunk: Chunk) -> ChunkExtraction:
            nonlocal completed
            async with self._semaphore:
                extraction: ChunkGraphExtraction
                if llm.is_enabled():
                    try:
                        extraction = await llm.extract_structured(
                            system_prompt=SYSTEM_PROMPT,
                            user_prompt=self._prompt(chunk),
                            response_model=ChunkGraphExtraction,
                        )
                        report.llm_chunks += 1
                    except Exception as exc:
                        logger.warning(
                            "LLM extraction failed for chunk %s (%s) — using heuristic",
                            chunk.id,
                            exc,
                        )
                        report.failed_chunks += 1
                        extraction = heuristic_extract_chunk(chunk)
                        report.heuristic_chunks += 1
                else:
                    extraction = heuristic_extract_chunk(chunk)
                    report.heuristic_chunks += 1

            async with lock:
                completed += 1
                if on_progress:
                    entity_count = sum(len(item.extraction.entities) for item in report.results) + len(
                        extraction.entities
                    )
                    rel_count = sum(
                        len(item.extraction.relationships) for item in report.results
                    ) + len(extraction.relationships)
                    await on_progress(completed, total, entity_count, rel_count)
            return ChunkExtraction(chunk=chunk, extraction=extraction)

        results = await asyncio.gather(*(process(chunk) for chunk in chunks))
        report.results = results
        return report

    @staticmethod
    def _prompt(chunk: Chunk) -> str:
        return (
            f"Document: {chunk.doc_title} (page {chunk.page_number}, chunk {chunk.index})\n"
            f"Extract the knowledge graph from this text:\n\n{chunk.text}"
        )
