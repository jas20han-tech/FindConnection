"""Dependency providers (kept thin; the runtime container owns lifecycle)."""

from __future__ import annotations

from app.graph.repository import GraphRepository
from app.runtime import get_repository


def repository_dependency() -> GraphRepository:
    return get_repository()
