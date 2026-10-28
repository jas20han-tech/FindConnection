"""Temporal time-slice diffing helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.schemas.graph import GraphEdge


@dataclass(slots=True)
class TemporalDiff:
    year: int
    active_edges: int
    new_edge_ids: list[str] = field(default_factory=list)
    dissolved_edge_ids: list[str] = field(default_factory=list)
    edges_by_year: dict[int, int] = field(default_factory=dict)
    earliest_year: int | None = None
    latest_year: int | None = None


def temporal_diff(edges: list[GraphEdge], year: int) -> TemporalDiff:
    visible = [edge for edge in edges if edge.year is None or edge.year <= year]
    by_year: Counter[int] = Counter(edge.year for edge in edges if edge.year is not None)
    years = sorted(by_year)
    return TemporalDiff(
        year=year,
        active_edges=len(visible),
        new_edge_ids=[edge.id for edge in visible if edge.year == year],
        dissolved_edge_ids=[
            edge.id
            for edge in visible
            if edge.status == "DISSOLVED" and edge.year == year
        ],
        edges_by_year=dict(sorted(by_year.items())),
        earliest_year=years[0] if years else None,
        latest_year=years[-1] if years else None,
    )


def edges_in_year(edges: list[GraphEdge], year: int) -> list[GraphEdge]:
    return [edge for edge in edges if edge.year == year]


def visible_until(edges: list[GraphEdge], year: int) -> list[GraphEdge]:
    return [edge for edge in edges if edge.year is None or edge.year <= year]
