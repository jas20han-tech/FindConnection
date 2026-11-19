from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.types import EntityType


class ExtractedEntity(BaseModel):
    name: str = Field(description="Canonical capitalized name, e.g. 'Google' instead of 'Google LLC'")
    type: EntityType
    description: str = Field(description="Concise summary of this entity in context")


class ExtractedRelationship(BaseModel):
    source: str = Field(description="Exact canonical name of the source entity")
    target: str = Field(description="Exact canonical name of the target entity")
    type: str = Field(
        description="Descriptive UPPER_SNAKE_CASE verb, e.g. CEO_OF, INVESTED_IN, REGULATES, DEVELOPED, ALLY_OF, RIVAL_TO, MISUNDERSTANDS"
    )
    description: str = Field(
        description="Detailed narrative story explaining the background, context, history, and dynamics of the relationship"
    )
    strength: int = Field(ge=1, le=10, description="Significance from 1 (minor) to 10 (critical)")
    sentiment: str = Field(
        default="NEUTRAL",
        description="Dynamic/emotional tone: POSITIVE, NEGATIVE, TENSE, ROMANTIC, RIVALRY, ALLIANCE, NEUTRAL",
    )
    date: str | None = Field(default=None, description="YYYY-MM-DD if stated or inferred, else null")
    date_confidence: Literal["explicit", "inferred", "unknown"] = "unknown"


class ChunkGraphExtraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
