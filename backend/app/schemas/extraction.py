from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal[
    "PERSON",
    "COMPANY",
    "PRODUCT",
    "TECHNOLOGY",
    "LOCATION",
    "REGULATION",
    "EVENT",
    "ORGANIZATION",
]


class ExtractedEntity(BaseModel):
    name: str = Field(description="Canonical capitalized name, e.g. 'Google' instead of 'Google LLC'")
    type: EntityType
    description: str = Field(description="Concise one-sentence summary of this entity in context")


class ExtractedRelationship(BaseModel):
    source: str = Field(description="Exact canonical name of the source entity")
    target: str = Field(description="Exact canonical name of the target entity")
    type: str = Field(
        description="UPPER_SNAKE_CASE verb, e.g. CEO_OF, INVESTED_IN, REGULATES, DEVELOPED"
    )
    description: str = Field(description="One-sentence explanation of the relationship context")
    strength: int = Field(ge=1, le=10, description="Significance from 1 (minor) to 10 (critical)")
    date: str | None = Field(default=None, description="YYYY-MM-DD if stated or inferred, else null")
    date_confidence: Literal["explicit", "inferred", "unknown"] = "unknown"


class ChunkGraphExtraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
