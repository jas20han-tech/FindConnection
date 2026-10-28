"""Page-aware document parsing (PyMuPDF for PDFs, plain text fallback)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedDocument:
    doc_hash: str
    filename: str
    title: str
    pages: list[str]
    page_count: int
    text: str
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def document_id(self) -> str:
        return f"doc_{self.doc_hash[:16]}"


def _parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to parse PDFs. Install the 'pdf' extra "
            "(uv pip install '.[pdf]') or upload a .txt/.md file."
        ) from exc

    doc_hash = hashlib.sha256(data).hexdigest()
    with fitz.open(stream=data, filetype="pdf") as document:
        pages = [page.get_text("text").strip() for page in document]
        metadata = {str(k): str(v) for k, v in (document.metadata or {}).items() if v}
        title = metadata.get("title") or Path(filename).stem.replace("_", " ").title()
        page_count = document.page_count

    text = "\n\n".join(page for page in pages if page)
    return ParsedDocument(
        doc_hash=doc_hash,
        filename=filename,
        title=title,
        pages=pages,
        page_count=page_count,
        text=text,
        metadata=metadata,
    )


def _parse_text(data: bytes, filename: str) -> ParsedDocument:
    doc_hash = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8", errors="replace")
    # Split on form feeds when available, otherwise treat as a single page.
    pages = [page.strip() for page in text.split("\f")]
    if len(pages) == 1:
        pages = [chunk.strip() for chunk in text.split("\n\n\n") if chunk.strip()] or [text]
    return ParsedDocument(
        doc_hash=doc_hash,
        filename=filename,
        title=Path(filename).stem.replace("_", " ").title(),
        pages=pages,
        page_count=len(pages),
        text=text,
        metadata={"source": "text"},
    )


async def parse_document(path: Path, filename: str | None = None) -> ParsedDocument:
    """Parse a document off the event loop."""
    filename = filename or path.name
    data = await asyncio.to_thread(path.read_bytes)
    if not data:
        raise ValueError("Uploaded file is empty")

    suffix = path.suffix.lower()
    if suffix == ".pdf" or data[:4] == b"%PDF":
        parsed = await asyncio.to_thread(_parse_pdf, data, filename)
    elif suffix in {".txt", ".md", ".markdown", ".csv"}:
        parsed = await asyncio.to_thread(_parse_text, data, filename)
    else:
        # Best-effort: try PDF signature first, else decode as text.
        try:
            parsed = await asyncio.to_thread(_parse_pdf, data, filename)
        except Exception as exc:
            logger.info("Non-PDF upload (%s): %s — decoding as text", suffix, exc)
            parsed = await asyncio.to_thread(_parse_text, data, filename)

    if not parsed.text.strip():
        raise ValueError("Document contains no extractable text (scanned PDFs need OCR)")
    logger.info(
        "Parsed %s: %d pages, %d characters", filename, parsed.page_count, len(parsed.text)
    )
    return parsed
