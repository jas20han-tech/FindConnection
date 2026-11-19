"""Page-aware document parsing.

Primary parser: Docling (layout-aware, page + bbox provenance). Fallback:
PyMuPDF for speed and for environments where Docling is not installed.
Both paths return the same :class:`ParsedDocument`, so the rest of the
pipeline is parser-agnostic.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# A line made mostly of one- and two-character tokens is a letter-spaced
# running header such as "K O N O H A  H I S T O R I C A L ...". It is layout
# noise, not content, and it poisons entity extraction.
_LETTER_SPACED_RATIO = 0.7
_LETTER_SPACED_MIN_TOKENS = 6


@dataclass(slots=True)
class ParsedDocument:
    doc_hash: str
    filename: str
    title: str
    pages: list[str]
    page_count: int
    text: str
    metadata: dict[str, str] = field(default_factory=dict)
    # Reading-order elements with provenance: {page, bbox, label, text}
    elements: list[dict[str, Any]] = field(default_factory=list)
    parser: str = "pymupdf"

    @property
    def document_id(self) -> str:
        return f"doc_{self.doc_hash[:16]}"


def _looks_letter_spaced(text: str) -> bool:
    """Detect running headers whose letters were spaced out during typesetting.

    Example: ``KONOHA H I STOR I CAL CHRON I CLES``. Normal prose almost never
    contains three or more one-letter words, so that is a reliable signal.
    """
    tokens = [token for token in (text or "").split() if token.isalpha()]
    if len(tokens) < _LETTER_SPACED_MIN_TOKENS:
        return False
    singles = sum(1 for token in tokens if len(token) == 1)
    if singles >= 3:
        return True
    short = sum(1 for token in tokens if len(token) <= 2)
    return short / len(tokens) >= _LETTER_SPACED_RATIO and len("".join(tokens)) >= 8


def _strip_letter_spaced_lines(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not _looks_letter_spaced(line)
    )


_UPLOAD_HASH_PREFIX = re.compile(r"^[0-9a-f]{16,}[_-]+", re.IGNORECASE)


def _document_title(filename: str, metadata: dict[str, str] | None = None) -> str:
    """Human title from document metadata, else the filename without upload hash.

    Uploads are stored as ``<32-hex-hash>_<original name>``; that prefix is an
    internal identifier, not part of the title. Capitalisation is preserved so
    proper nouns ("The Will of Fire") are not title-cased into "Of The".
    """
    candidate = (metadata or {}).get("title", "").strip()
    if not candidate:
        stem = Path(filename).stem
        candidate = _UPLOAD_HASH_PREFIX.sub("", stem).replace("_", " ")
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if candidate.islower():
        candidate = candidate.title()
    return candidate or Path(filename).stem


def _block_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _repeated_block_keys(texts: list[str], page_count: int) -> set[str]:
    """Text blocks repeated on most pages are running headers/footers."""
    if page_count < 3:
        return set()
    threshold = max(2, (page_count + 1) // 2)
    counts: dict[str, int] = {}
    for text in texts:
        key = _block_key(text)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {
        key
        for key, count in counts.items()
        if count >= threshold and (len(key) > 8 or key.isdigit())
    }


def _drop_repeated_page_lines(pages: list[str]) -> list[str]:
    keys = _repeated_block_keys(
        [line for page in pages for line in page.splitlines() if line.strip()],
        len(pages),
    )
    if not keys:
        return pages
    cleaned: list[str] = []
    for page in pages:
        cleaned.append(
            "\n".join(
                line
                for line in page.splitlines()
                if _block_key(line) not in keys
            ).strip()
        )
    return cleaned


def _normalize_extracted_text(text: str) -> str:
    # Unbreak hyphenated words across newlines (e.g. "established 2017-07-\n14" -> "established 2017-07-14")
    text = re.sub(r"(\w+)-\n(\w+)", r"\1-\2", text)
    # Rejoin split drop caps such as "F rom" / "W ithin" (but never "I am" / "A man").
    text = re.sub(r"(?<![\w])([B-HJ-Z]) (?=[a-z]{2,})", r"\1", text)
    # Join soft newlines within sentences while preserving headers/lists
    text = re.sub(r"(?<![.!?:\n])\n(?!\n|[A-Z0-9\-\*•#])", " ", text)
    text = _strip_letter_spaced_lines(text)
    return text.strip()


def _parse_pdf_pymupdf(data: bytes, filename: str) -> ParsedDocument:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to parse PDFs. Install the 'pdf' extra "
            "(uv pip install '.[pdf]') or upload a .txt/.md file."
        ) from exc

    doc_hash = hashlib.sha256(data).hexdigest()
    elements: list[dict[str, Any]] = []
    with fitz.open(stream=data, filetype="pdf") as document:
        pages: list[str] = []
        for page_index, page in enumerate(document, start=1):
            raw = page.get_text("text")
            pages.append(_normalize_extracted_text(raw))
            for block in page.get_text("blocks") or []:
                if not block or len(block) < 5:
                    continue
                block_text = str(block[4]).strip()
                if not block_text:
                    continue
                elements.append(
                    {
                        "page": page_index,
                        "bbox": [float(block[0]), float(block[1]), float(block[2]), float(block[3])],
                        "label": "block",
                        "text": block_text,
                    }
                )
        metadata = {str(k): str(v) for k, v in (document.metadata or {}).items() if v}
        title = _document_title(filename, metadata)
        page_count = document.page_count

    pages = _drop_repeated_page_lines(pages)
    text = "\n\n".join(page for page in pages if page)
    return ParsedDocument(
        doc_hash=doc_hash,
        filename=filename,
        title=title,
        pages=pages,
        page_count=page_count,
        text=text,
        metadata=metadata,
        elements=elements,
        parser="pymupdf",
    )


def _parse_pdf_docling(path: Path, filename: str) -> ParsedDocument:
    """Layout-aware parse with Docling, preserving page and bbox provenance."""
    from docling.document_converter import DocumentConverter  # optional dependency

    data = path.read_bytes()
    doc_hash = hashlib.sha256(data).hexdigest()

    result = DocumentConverter().convert(str(path))
    document = result.document

    pages_map: dict[int, list[str]] = {}
    elements: list[dict[str, Any]] = []
    for item, _level in document.iterate_items():
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        provenance = getattr(item, "prov", None) or []
        page_no: int | None = None
        bbox: list[float | None] | None = None
        if provenance:
            first = provenance[0]
            raw_page = getattr(first, "page_no", None)
            if raw_page is not None:
                page_no = int(raw_page)
            box = getattr(first, "bbox", None)
            if box is not None:
                bbox = [
                    getattr(box, "l", None),
                    getattr(box, "t", None),
                    getattr(box, "r", None),
                    getattr(box, "b", None),
                ]
        if page_no is None:
            continue
        pages_map.setdefault(page_no, []).append(text)
        label = getattr(item, "label", None)
        elements.append(
            {
                "page": page_no,
                "bbox": bbox,
                "label": str(label) if label is not None else type(item).__name__,
                "text": text,
            }
        )

    if not pages_map:
        raise RuntimeError("Docling returned no page provenance")

    doc_pages = getattr(document, "pages", None)
    page_count = max(pages_map)
    if doc_pages:
        try:
            page_count = max(page_count, len(doc_pages))
        except TypeError:  # pragma: no cover - defensive for mapping-like page stores
            pass

    # A running header is usually emitted as a section_header on every page.
    # Drop blocks repeated across most pages before they reach entity extraction.
    repeated = _repeated_block_keys(
        [element["text"] for element in elements],
        page_count,
    )
    if repeated:
        elements = [
            element
            for element in elements
            if _block_key(element["text"]) not in repeated
        ]
        pages_map = {}
        for element in elements:
            pages_map.setdefault(element["page"], []).append(element["text"])

    # A letter-spaced running header appears on the first page only in some
    # documents, so filter by shape as well as by repetition.
    elements = [
        element for element in elements if not _looks_letter_spaced(element["text"])
    ]
    pages_map = {}
    for element in elements:
        pages_map.setdefault(element["page"], []).append(element["text"])

    pages = [
        _normalize_extracted_text("\n".join(pages_map.get(number, [])))
        for number in range(1, page_count + 1)
    ]
    text = "\n\n".join(page for page in pages if page)
    return ParsedDocument(
        doc_hash=doc_hash,
        filename=filename,
        title=_document_title(filename),
        pages=pages,
        page_count=page_count,
        text=text,
        metadata={"source": "docling"},
        elements=elements,
        parser="docling",
    )


def _parse_text(data: bytes, filename: str) -> ParsedDocument:
    doc_hash = hashlib.sha256(data).hexdigest()
    # utf-8-sig strips a leading BOM, which Windows editors commonly add.
    text = data.decode("utf-8-sig", errors="replace")
    # Split on form feeds when available, otherwise treat as a single page.
    pages = [page.strip() for page in text.split("\f")]
    if len(pages) == 1:
        pages = [chunk.strip() for chunk in text.split("\n\n\n") if chunk.strip()] or [text]
    return ParsedDocument(
        doc_hash=doc_hash,
        filename=filename,
        title=_document_title(filename),
        pages=pages,
        page_count=len(pages),
        text=text,
        metadata={"source": "text"},
        parser="text",
    )


async def parse_document(path: Path, filename: str | None = None) -> ParsedDocument:
    """Parse a document off the event loop."""
    filename = filename or path.name
    data = await asyncio.to_thread(path.read_bytes)
    if not data:
        raise ValueError("Uploaded file is empty")

    suffix = path.suffix.lower()
    if suffix == ".pdf" or data[:4] == b"%PDF":
        parsed = await _parse_pdf(path, data, filename)
    elif suffix in {".txt", ".md", ".markdown", ".csv"}:
        parsed = await asyncio.to_thread(_parse_text, data, filename)
    else:
        # Best-effort: try PDF signature first, else decode as text.
        try:
            parsed = await _parse_pdf(path, data, filename)
        except Exception as exc:
            logger.info("Non-PDF upload (%s): %s — decoding as text", suffix, exc)
            parsed = await asyncio.to_thread(_parse_text, data, filename)

    if not parsed.text.strip():
        raise ValueError("Document contains no extractable text (scanned PDFs need OCR)")
    logger.info(
        "Parsed %s with %s: %d pages, %d characters",
        filename,
        parsed.parser,
        parsed.page_count,
        len(parsed.text),
    )
    return parsed


async def _parse_pdf(path: Path, data: bytes, filename: str) -> ParsedDocument:
    """Try Docling, then fall back to PyMuPDF, controlled by PDF_PARSER."""
    choice = (settings.pdf_parser or "auto").strip().lower()
    if choice in {"auto", "docling"}:
        try:
            return await asyncio.to_thread(_parse_pdf_docling, path, filename)
        except Exception as exc:
            logger.info(
                "Docling parsing unavailable for %s (%s) — falling back to PyMuPDF",
                filename,
                exc,
            )
    return await asyncio.to_thread(_parse_pdf_pymupdf, data, filename)
