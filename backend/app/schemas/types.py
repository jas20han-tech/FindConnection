from __future__ import annotations

from typing import Literal

EntityType = Literal[
    "PERSON",
    "COMPANY",
    "PRODUCT",
    "TECHNOLOGY",
    "LOCATION",
    "REGULATION",
    "EVENT",
    "ORGANIZATION",
    "CHARACTER",
    "FACTION",
    "CONCEPT",
    "ARTIFACT",
]

EdgeStatus = Literal["ACTIVE", "NEW", "DISSOLVED"]

QueryMode = Literal["CONNECTION", "IMPACT", "TEMPORAL", "GLOBAL", "ENTITY"]

IngestionStage = Literal[
    "QUEUED",
    "PARSING",
    "CHUNKING",
    "EXTRACTING",
    "RESOLVING",
    "INDEXING",
    "CLUSTERING",
    "COMPLETED",
    "FAILED",
]
