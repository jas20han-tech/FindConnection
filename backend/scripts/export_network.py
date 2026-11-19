"""Extract a verifiable network JSON from a PDF or text document.

Usage (from the backend directory):

    .venv\\Scripts\\python.exe scripts\\export_network.py ..\\report.pdf

    # choose the output file and keep the JSON self-contained
    .venv\\Scripts\\python.exe scripts\\export_network.py report.pdf -o network.json

The script runs the same parse -> chunk -> extract -> resolve pipeline as the API,
but does not touch the live graph. Every node and edge includes a page number and a
verbatim quote, with a ``quote_verified`` flag, so the network can be checked
against the source document by a human or a separate verification agent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.ingestion.chunker import chunk_document  # noqa: E402
from app.ingestion.extractor import ExtractionEngine  # noqa: E402
from app.ingestion.parser import ParsedDocument, parse_document  # noqa: E402
from app.ingestion.resolver import EntityResolver  # noqa: E402
from app.ingestion.verification import (  # noqa: E402
    attach_resolved_evidence,
    build_verification_network,
    save_verification_network,
)


async def export(
    path: Path,
    *,
    output: Path | None,
    max_pages: int | None,
    include_source_text: bool,
    no_save: bool,
) -> int:
    document: ParsedDocument = await parse_document(path, path.name)
    if max_pages is not None:
        document.pages = document.pages[:max_pages]
        document.page_count = len(document.pages)
        document.text = "\n\n".join(page for page in document.pages if page)

    chunks = chunk_document(document)
    if not chunks:
        print("error: the document has no chunkable text", file=sys.stderr)
        return 1

    print(
        f"Parsing {document.filename}: {document.page_count} pages, {len(chunks)} chunks ...",
        file=sys.stderr,
    )
    report = await ExtractionEngine().extract(chunks)
    resolved = await EntityResolver([]).resolve(report)
    attach_resolved_evidence(document, resolved, chunks)

    network = build_verification_network(
        document,
        resolved,
        chunks,
        report,
        include_source_text=include_source_text,
    )
    summary = network["summary"]

    print(
        "Extracted "
        f"{summary['node_count']} nodes and {summary['edge_count']} edges "
        f"({summary['items_with_verified_evidence']} items with verified evidence, "
        f"{summary['items_with_unverified_evidence']} unverified).",
        file=sys.stderr,
    )
    for warning in network.get("warnings", []):
        print(f"  warning: {warning}", file=sys.stderr)

    if no_save:
        print(json.dumps(network, indent=2, ensure_ascii=False))
        return 0

    saved = save_verification_network(network, document.filename, output_path=output)
    print(f"Wrote {saved}", file=sys.stderr)
    print(saved)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a page/quote-backed entity network from a PDF or text file."
    )
    parser.add_argument("document", help="Path to a PDF, Markdown, CSV or text file")
    parser.add_argument("-o", "--output", help="Output JSON path")
    parser.add_argument(
        "--max-pages", type=int, default=None, help="Only read the first N pages"
    )
    parser.add_argument(
        "--no-source-text",
        action="store_true",
        help="Omit the full source page text from the JSON",
    )
    parser.add_argument(
        "--no-save", action="store_true", help="Print the JSON to stdout instead of a file"
    )
    args = parser.parse_args()

    path = Path(args.document)
    if not path.is_file():
        print(f"error: document not found: {path}", file=sys.stderr)
        return 2

    return asyncio.run(
        export(
            path,
            output=Path(args.output) if args.output else None,
            max_pages=args.max_pages,
            include_source_text=not args.no_source_text,
            no_save=args.no_save,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
