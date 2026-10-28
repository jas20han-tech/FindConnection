"""Streaming hybrid query endpoint (SSE) and a non-streaming convenience endpoint."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.dependencies import repository_dependency
from app.graph.repository import GraphRepository
from app.reasoning import ppr_retriever
from app.reasoning.community import community_overview
from app.reasoning.path_finder import PathResult, describe_path, shortest_path
from app.reasoning.router import RouteDecision, classify
from app.reasoning.simulator import simulate_impact
from app.reasoning.synthesizer import (
    SynthesisContext,
    confidence_for,
    fallback_narrative,
    stream_narrative,
)
from app.schemas.graph import GraphEdge, GraphNode
from app.schemas.impact import ImpactResult
from app.schemas.query import (
    Citation,
    CompleteEvent,
    GraphContextEvent,
    QueryRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


@dataclass(slots=True)
class QueryOutcome:
    context: SynthesisContext
    decision: RouteDecision
    path: PathResult | None
    impact: ImpactResult | None
    elapsed_ms: float
    explanation: str = ""
    node_map: dict[str, GraphNode] = field(default_factory=dict)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _edges_between(edges: list[GraphEdge], node_ids: set[str], limit: int = 120) -> list[GraphEdge]:
    selected = [
        edge
        for edge in edges
        if edge.source in node_ids and edge.target in node_ids and edge.status != "DISSOLVED"
    ]
    selected.sort(key=lambda edge: edge.strength, reverse=True)
    return selected[:limit]


async def build_outcome(payload: QueryRequest, repository: GraphRepository) -> QueryOutcome:
    started = time.perf_counter()
    nodes, edges = await repository.get_all()
    node_map = {node.id: node for node in nodes}
    viewport = await repository.get_viewport()

    decision = await classify(payload.query, repository)
    mode = payload.mode or decision.mode
    year = payload.time_range[1] if payload.time_range else None

    active_edges = [
        edge
        for edge in edges
        if (year is None or edge.year is None or edge.year <= year)
        and edge.status != "DISSOLVED"
    ]

    highlighted_nodes: set[str] = set()
    highlighted_edges: set[str] = set()
    path: PathResult | None = None
    impact: ImpactResult | None = None
    scores: dict[str, float] = {}
    explanation = decision.rationale

    if mode == "CONNECTION":
        seeds = decision.seed_ids[:2]
        ppr = ppr_retriever.personalized_pagerank(
            nodes,
            edges,
            decision.seed_ids,
            max_year=year,
            top_k=payload.max_nodes,
        )
        scores = ppr.scores
        if len(seeds) >= 2:
            path = shortest_path(
                active_edges,
                seeds[0],
                seeds[1],
                max_hops=payload.max_hops,
                max_year=year,
            )
            if path.found:
                highlighted_nodes.update(path.node_ids)
                highlighted_edges.update(path.edge_ids)
                source = node_map.get(seeds[0])
                target = node_map.get(seeds[1])
                explanation = (
                    f"{explanation}. Found a {path.hops}-hop route between "
                    f"{source.name if source else seeds[0]} and {target.name if target else seeds[1]}."
                )
            else:
                explanation = f"{explanation}. {path.explanation}."
        if not highlighted_nodes:
            highlighted_nodes.update(ppr.node_ids[: payload.max_nodes])
            if not decision.seed_ids:
                ranked = sorted(nodes, key=lambda node: node.pagerank, reverse=True)
                highlighted_nodes.update(node.id for node in ranked[:12])
        highlighted_nodes.update(ppr.node_ids[: max(8, payload.max_nodes // 2)])
        highlighted_edges.update(
            edge.id
            for edge in _edges_between(edges, highlighted_nodes)
        )

    elif mode == "IMPACT":
        if not decision.seed_ids:
            raise HTTPException(
                status_code=422,
                detail="Impact simulation needs a recognised entity in the query",
            )
        target = decision.seed_ids[0]
        impact = simulate_impact(nodes, active_edges, target)
        highlighted_nodes.add(target)
        neighbour_ids = {item["id"] for item in impact.directly_disrupted}
        highlighted_nodes.update(neighbour_ids)
        highlighted_edges.update(
            edge.id
            for edge in edges
            if edge.status != "DISSOLVED" and target in (edge.source, edge.target)
        )
        ppr = ppr_retriever.personalized_pagerank(
            nodes, edges, [target], max_year=year, top_k=12
        )
        highlighted_nodes.update(ppr.node_ids[:8])
        scores = ppr.scores
        explanation = (
            f"{explanation}. Simulated severance of {impact.removed_node['name']} in "
            f"{impact.duration_ms:.1f} ms ({impact.severity.lower()} risk)."
        )

    elif mode == "TEMPORAL":
        selected_year = payload.time_range[1] if payload.time_range else max(
            (edge.year for edge in edges if edge.year), default=2026
        )
        visible = [
            edge
            for edge in edges
            if edge.year is None or edge.year <= selected_year
        ]
        changed = sorted(
            [edge for edge in visible if edge.year == selected_year],
            key=lambda edge: edge.strength,
            reverse=True,
        )[:30]
        if not changed:
            changed = sorted(visible, key=lambda edge: edge.year or 0, reverse=True)[:30]
        highlighted_edges.update(edge.id for edge in changed)
        for edge in changed:
            highlighted_nodes.update((edge.source, edge.target))
        ppr = ppr_retriever.personalized_pagerank(
            nodes, visible, decision.seed_ids, max_year=selected_year, top_k=15
        )
        if not decision.seed_ids:
            top = sorted(nodes, key=lambda node: node.pagerank, reverse=True)[:12]
            highlighted_nodes.update(node.id for node in top)
        highlighted_nodes.update(ppr.node_ids[:10])
        scores = ppr.scores
        explanation = (
            f"{explanation}. Time slice {selected_year}: "
            f"{len(changed)} relationship(s) introduced or highlighted."
        )

    else:  # GLOBAL / ENTITY
        if decision.seed_ids:
            ppr = ppr_retriever.personalized_pagerank(
                nodes,
                edges,
                decision.seed_ids,
                max_year=year,
                top_k=payload.max_nodes,
            )
            highlighted_nodes.update(ppr.node_ids[: payload.max_nodes])
            scores = ppr.scores
            highlighted_edges.update(
                edge.id for edge in _edges_between(edges, highlighted_nodes)
            )
        else:
            ranked = sorted(
                nodes,
                key=lambda node: (node.pagerank, node.degree),
                reverse=True,
            )[: min(payload.max_nodes, 30)]
            highlighted_nodes.update(node.id for node in ranked)
            highlighted_edges.update(
                edge.id for edge in _edges_between(edges, highlighted_nodes, limit=200)
            )
        explanation = (
            f"{explanation}. Synthesised the {len(highlighted_nodes)} most structurally "
            f"important entities and their strongest links."
        )

    if not highlighted_nodes:
        raise HTTPException(
            status_code=422,
            detail="No matching entities were found. Try an @Entity mention or a broader query.",
        )

    context = SynthesisContext(
        query=payload.query,
        mode=mode,  # type: ignore[arg-type]
        nodes=nodes,
        edges=edges,
        communities=viewport.communities,
        highlighted_node_ids=sorted(highlighted_nodes),
        highlighted_edge_ids=sorted(highlighted_edges),
        path=path,
        scores=scores,
        impact=impact,
        year=year or (payload.time_range[1] if payload.time_range else None),
    )
    citations = context.citations()
    confidence = confidence_for(
        seeds=decision.seed_ids,
        path=path if path is not None else PathResult(found=bool(highlighted_edges)),
        citations=len(citations),
        mode=mode,  # type: ignore[arg-type]
    )
    context.confidence = confidence

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return QueryOutcome(
        context=context,
        decision=decision,
        path=path,
        impact=impact,
        elapsed_ms=elapsed_ms,
        explanation=explanation,
        node_map=node_map,
    )


def _context_event(outcome: QueryOutcome, payload: QueryRequest) -> GraphContextEvent:
    context = outcome.context
    return GraphContextEvent(
        query=payload.query,
        mode=context.mode,
        seed_node_ids=outcome.decision.seed_ids,
        highlighted_node_ids=context.highlighted_node_ids,
        highlighted_edge_ids=context.highlighted_edge_ids,
        path_node_ids=outcome.path.node_ids if outcome.path else [],
        path_edge_ids=outcome.path.edge_ids if outcome.path else [],
        scores={
            node_id: round(score, 6)
            for node_id, score in sorted(
                context.scores.items(), key=lambda item: item[1], reverse=True
            )[:25]
        },
        explanation=outcome.explanation,
        elapsed_ms=outcome.elapsed_ms,
        confidence=context.confidence,
    )


@router.post("/query/stream")
async def query_stream(
    payload: QueryRequest,
    repository: GraphRepository = Depends(repository_dependency),
) -> StreamingResponse:
    async def generator():
        started = time.perf_counter()
        try:
            outcome = await build_outcome(payload, repository)
            yield _sse("graph_context", _context_event(outcome, payload).model_dump())

            async for token in stream_narrative(outcome.context):
                yield _sse("token", {"type": "token", "text": token})

            citations: list[Citation] = outcome.context.citations()
            complete = CompleteEvent(
                citations=citations,
                confidence=outcome.context.confidence,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                mode=outcome.context.mode,
            )
            yield _sse("complete", complete.model_dump())
        except HTTPException as exc:
            yield _sse("error", {"type": "error", "message": exc.detail})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Query stream failed")
            yield _sse("error", {"type": "error", "message": str(exc)})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/query")
async def query_once(
    payload: QueryRequest,
    repository: GraphRepository = Depends(repository_dependency),
) -> dict:
    outcome = await build_outcome(payload, repository)
    text = fallback_narrative(outcome.context)
    citations = outcome.context.citations()
    return {
        "query": payload.query,
        "mode": outcome.context.mode,
        "answer": text,
        "citations": [citation.model_dump() for citation in citations],
        "confidence": outcome.context.confidence,
        "context": _context_event(outcome, payload).model_dump(),
        "elapsed_ms": outcome.elapsed_ms,
    }
