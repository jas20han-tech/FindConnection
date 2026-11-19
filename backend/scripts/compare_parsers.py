"""Compare Docling and PyMuPDF parsing on the Will of Fire PDF."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.ingestion.parser import parse_document

PDF = Path(
    "uploads/5fdc6d51282f49b6bbed7956b11b718a_The Will of Fire_ Chronicles of the Hidden Leaf.pdf"
).resolve()


async def main() -> None:
    document = await parse_document(PDF, PDF.name)
    print(json.dumps(
        {
            "parser": document.parser,
            "pages": document.page_count,
            "chars": len(document.text),
            "elements": len(document.elements),
            "first_elements": document.elements[:12],
            "page1_head": document.pages[0][:600],
            "page2_head": document.pages[1][:600] if len(document.pages) > 1 else "",
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    asyncio.run(main())
