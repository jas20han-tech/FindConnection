"""Print per-page heads and repeated-block counts for a parsed PDF."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from pathlib import Path

from app.ingestion.parser import parse_document

PDF = Path(
    "uploads/5fdc6d51282f49b6bbed7956b11b718a_The Will of Fire_ Chronicles of the Hidden Leaf.pdf"
).resolve()


def key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


async def main() -> None:
    document = await parse_document(PDF, PDF.name)
    print("parser:", document.parser, "pages:", document.page_count)
    for number, page in enumerate(document.pages, start=1):
        print(f"--- page {number} ---")
        print(page[:240].replace("\n", " | "))
    counts = Counter(key(element["text"]) for element in document.elements)
    print("--- repeated ---")
    for text, count in counts.most_common(10):
        if count > 1:
            print(count, text[:120])


if __name__ == "__main__":
    asyncio.run(main())
