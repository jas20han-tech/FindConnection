"""Token-bounded, page-aware chunking.

Uses ``tiktoken`` (cl100k_base) when available and falls back to a character-based
estimate so ingestion works with a minimal dependency set. Chunk IDs are
deterministic: ``{doc_hash}_chunk_{index}``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings
from app.ingestion.parser import ParsedDocument

logger = logging.getLogger(__name__)

try:  # optional dependency
    import tiktoken

    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - optional dependency
    _ENCODER = None


@dataclass(slots=True)
class Chunk:
    id: str
    text: str
    index: int
    page_number: int
    token_count: int
    doc_id: str
    doc_title: str

    def as_metadata(self) -> dict[str, str | int]:
        return {
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "chunk_index": self.index,
            "page_number": self.page_number,
            "token_count": self.token_count,
        }


def count_tokens(text: str) -> int:
    if _ENCODER is not None:
        return len(_ENCODER.encode(text))
    return max(1, len(text) // 4)


def _encode(text: str) -> list[int] | None:
    return _ENCODER.encode(text) if _ENCODER is not None else None


def _decode(tokens: list[int]) -> str:
    assert _ENCODER is not None
    return _ENCODER.decode(tokens)


def chunk_document(
    document: ParsedDocument,
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Chunk each page with a sliding token window.

    Page-scoped windows keep every chunk attributable to an exact page number, which
    is required for 100% verifiable citations. Long pages are split with overlap;
    short pages are emitted intact.
    """
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap if overlap is not None else settings.chunk_overlap
    overlap = max(0, min(overlap, chunk_size // 2))
    step = max(1, chunk_size - overlap)

    chunks: list[Chunk] = []
    index = 0

    for page_number, page_text in enumerate(document.pages, start=1):
        text = (page_text or "").strip()
        if not text:
            continue

        tokens = _encode(text)
        if tokens is None:
            # Character fallback approximates 4 chars per token.
            approx_chars = chunk_size * 4
            step_chars = step * 4
            for start in range(0, len(text), step_chars):
                window = text[start : start + approx_chars].strip()
                if len(window) < 40:
                    continue
                chunks.append(
                    _build_chunk(
                        document,
                        window,
                        index,
                        page_number,
                        token_count=max(1, len(window) // 4),
                    )
                )
                index += 1
                if start + approx_chars >= len(text):
                    break
            continue

        if len(tokens) <= chunk_size:
            if len(text) >= 40:
                chunks.append(
                    _build_chunk(
                        document, text, index, page_number, token_count=len(tokens)
                    )
                )
                index += 1
            continue

        for start in range(0, len(tokens), step):
            window_tokens = tokens[start : start + chunk_size]
            if not window_tokens:
                break
            window = _decode(window_tokens).strip()
            if len(window) >= 40:
                chunks.append(
                    _build_chunk(
                        document,
                        window,
                        index,
                        page_number,
                        token_count=len(window_tokens),
                    )
                )
                index += 1
            if start + chunk_size >= len(tokens):
                break

    logger.info("Chunked %s into %d chunks", document.filename, len(chunks))
    return chunks


def _build_chunk(
    document: ParsedDocument,
    text: str,
    index: int,
    page_number: int,
    *,
    token_count: int,
) -> Chunk:
    return Chunk(
        id=f"{document.doc_hash}_chunk_{index}",
        text=text,
        index=index,
        page_number=page_number,
        token_count=token_count,
        doc_id=document.document_id,
        doc_title=document.title,
    )
