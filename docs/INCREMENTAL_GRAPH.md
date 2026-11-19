# Incremental, evidence-backed knowledge graph

This is the Phase B behaviour: uploads no longer replace the graph. Each document is
parsed, chunked and extracted in order, then **merged** into one evolving graph.

## What happens on upload

1. **Parse** — Docling first (layout + page/bbox), PyMuPDF as fallback. `PDF_PARSER=auto`
   is the default; use `docling` / `pymupdf` to force one.
2. **Chunk** — page-scoped token windows, so every chunk has an exact page number.
3. **Extract** — Gemini → Ollama → OpenRouter → OpenAI. A broken provider is cooled
   down for 60 s instead of being retried for every chunk. With no provider
   configured, the deterministic heuristic extractor runs.
4. **Resolve** — the resolver is seeded with **existing graph nodes**, so entities
   are merged across documents (aliases, fuzzy match, embedding match).
5. **Attach evidence** — every node/edge gets `{doc, page, quote, quote_verified,
   chunk_id}` from the current document before indexing.
6. **Index** — the repository merges nodes/edges. Symmetric relations (`RELATED_TO`,
   `ALLY_OF`, `RIVAL_TO`, …) share one canonical id, so A→B and B→A are one edge.
7. **Export** — the verification JSON is written, with evidence from every document
   that asserted the node/edge.

## Environment

```dotenv
LLM_PROVIDER_ORDER=gemini,ollama,openrouter,openai
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.1-flash-lite
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen2.5:7b-instruct
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free
PDF_PARSER=auto
GRAPH_ACCUMULATE=false
```

The default `GRAPH_ACCUMULATE=false` gives every upload its own canvas: the graph
is cleared before the new PDF is indexed, so the live graph and the exported
network contain only the document you just uploaded. Set it to `true` to merge
documents into one evolving graph instead. `GET /health` reports
`llm_providers`, `pdf_parser`, `graph_accumulate` and `document_count`.

## Graph shape

`GraphNode` and `GraphEdge` now carry:

```json
{
  "documents": ["First Report", "Second Report"],
  "evidence": [
    {
      "doc": "first-report.pdf",
      "page": 3,
      "quote": "Alice founded Beta Labs in 2020.",
      "quote_verified": true,
      "chunk_id": "<doc_hash>_chunk_4"
    }
  ]
}
```

`quote_verified=true` means the quote was found verbatim in the extracted text of the
cited page. It does **not** mean the quote supports the claim — that is the job of the
verification agent / human.

When comparing against the raw PDF, normalize typography first: PDF text often uses
curly quotes (`’`) and em dashes (`—`) where the quote uses ASCII (`'`, `-`), and a
decorative drop cap can print the first letter separately (`F` + `rom the ...`). The
`source_pages` array in the JSON contains the exact extracted text used for
verification, which avoids both problems.

## Verifying a network with a separate agent

Export files live in `backend/data/networks/` and are served by
`/api/v1/networks`, `/latest`, `/{name}` and `/{name}/download`.

Suggested verification prompt for an independent agent:

> You are an evidence auditor. You receive a network JSON and the source document.
> For every node and every edge, open `evidence[].page`, search the page for
> `evidence[].quote`, and decide:
> 1. Is the quote present on that page? (compare with `quote_verified`; normalize
>    curly quotes/dashes and allow a separated drop-cap letter before failing the match)
> 2. Does the quote actually state the node name / relation label?
> 3. Does the evidence belong to the document named in `evidence[].doc`?
> Return a table of `id`, verdict (`supported` / `quote-only` / `unsupported`),
> reason, and the exact page/quote you used. Do not use the extractor's
> description as evidence.

`source_pages` in the JSON lets the agent work without the PDF; for a stricter check,
download the original file from `backend/uploads/` and read the PDF page directly.

## Current limitations

- Chunk extraction still runs concurrently; cross-chunk pronoun resolution needs the
  planned sequential/rolling-context pass (Phase C).
- Contradictions are not yet marked (`valid_from` / `valid_to` / `superseded_by`).
- Without an LLM key the heuristic extractor produces weaker types and relation
  verbs; the evidence flags remain accurate, but the claims need heavier review.
- Docling downloads its layout/table models on first run; later parses are local.
