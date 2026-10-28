from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_label: Mapped[str] = mapped_column(String(100), nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)
    community_count: Mapped[int] = mapped_column(Integer, nullable=False)
    community_summaries: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    centrality_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
