"""LLM + embedding access with graceful fallback.

All calls are optional: when ``OPENAI_API_KEY`` is absent the ingestion engine uses
its deterministic heuristic extractor and the reasoning engine uses its local
narrative synthesizer, so the platform stays fully usable in demo mode.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, TypeVar

from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

_client: Any = None


class LLMUnavailable(RuntimeError):
    pass


def is_enabled() -> bool:
    return settings.llm_enabled


def get_client() -> Any:
    global _client
    if not settings.llm_enabled:
        raise LLMUnavailable("OPENAI_API_KEY is not configured")
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
        )
    return _client


async def extract_structured(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: type[TModel],
) -> TModel:
    """Guaranteed-schema extraction via OpenAI Structured Outputs."""
    client = get_client()
    completion = await client.beta.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=response_model,
        temperature=0,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise LLMUnavailable("Model returned no parsed structured output")
    return parsed


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = get_client()
    vectors: list[list[float]] = []
    batch_size = 64
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
        )
        vectors.extend([item.embedding for item in response.data])
    return vectors


async def embed_text(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0] if vectors else []


async def stream_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> AsyncIterator[str]:
    """Yield narrative tokens from the model."""
    client = get_client()
    stream = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


async def classify_intent(query: str, labels: list[str]) -> str | None:
    """Optional LLM fallback for the intent router (heuristics run first)."""
    if not settings.llm_enabled:
        return None
    try:
        client = get_client()
        completion = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the user's graph query intent. Reply with exactly one label "
                        f"from this list: {', '.join(labels)}."
                    ),
                },
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=8,
        )
        label = (completion.choices[0].message.content or "").strip().upper()
        return label if label in labels else None
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("Intent classification fallback failed: %s", exc)
        return None


async def close_llm() -> None:
    global _client
    if _client is not None:
        await _client.close()
    _client = None
