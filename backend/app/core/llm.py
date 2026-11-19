"""LLM + embedding access with provider fallback.

Every supported provider speaks the OpenAI-compatible API, so a single adapter
covers Gemini, Ollama, OpenRouter and OpenAI. Providers are tried in
``LLM_PROVIDER_ORDER`` (Gemini → Ollama → OpenRouter → OpenAI by default). A
provider that is unreachable, unauthorised or rate-limited is skipped for a
short cooldown instead of being retried for every chunk.

When no provider is configured, or every provider fails, callers fall back to
the deterministic heuristic extractor and the local narrative synthesizer.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

# Skip a broken provider for this long before trying it again.
_COOLDOWN_SECONDS = 60.0

_providers: list["_Provider"] | None = None
_cooldown: dict[str, float] = {}
_preferred: str | None = None


class LLMUnavailable(RuntimeError):
    """Raised when no provider can satisfy a request."""


class LLMOutputError(LLMUnavailable):
    """The provider answered, but its payload did not match the schema.

    This is a model/prompt problem, not a broken endpoint, so the provider is not
    put on cooldown; the caller still falls through to the next provider.
    """


@dataclass(slots=True)
class _Provider:
    name: str
    model: str
    embedding_model: str
    client: Any


# --------------------------------------------------------------------------- setup
def _embedding_model_for(name: str) -> str:
    if name == "gemini":
        return settings.gemini_embedding_model
    if name == "ollama":
        return settings.ollama_embedding_model
    return settings.embedding_model


def _build_providers() -> list[_Provider]:
    global _providers
    if _providers is not None:
        return _providers

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise LLMUnavailable(
            "The openai package is required for LLM providers. "
            "Install the 'llm' extra or keep using the heuristic extractor."
        ) from exc

    built: list[_Provider] = []
    for name in settings.llm_providers:
        if not settings.provider_enabled(name):
            continue
        api_key, base_url, model = settings.provider_credentials(name)
        if not api_key:
            continue
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        built.append(
            _Provider(
                name=name,
                model=model or "",
                embedding_model=_embedding_model_for(name),
                client=client,
            )
        )

    if not built:
        raise LLMUnavailable(
            "No LLM provider is configured. Set GEMINI_API_KEY, OPENROUTER_API_KEY, "
            "OLLAMA_ENABLED=true or OPENAI_API_KEY."
        )

    _providers = built
    logger.info("LLM providers available: %s", ", ".join(p.name for p in built))
    return built


def reset_providers() -> None:
    """Drop cached clients (used by tests and after a settings change)."""
    global _providers, _preferred
    _providers = None
    _preferred = None
    _cooldown.clear()


def _ordered_providers() -> list[_Provider]:
    providers = _build_providers()
    now = time.monotonic()
    alive = [p for p in providers if _cooldown.get(p.name, 0.0) <= now]
    if not alive:
        # Everything is cooling down: give them all another chance rather than
        # refusing to work.
        _cooldown.clear()
        alive = list(providers)
    if _preferred:
        alive.sort(key=lambda p: 0 if p.name == _preferred else 1)
    return alive


def _cool_down(provider: _Provider, exc: Exception) -> None:
    # A schema validation failure is the model's answer, not a broken provider.
    if isinstance(exc, (ValidationError, LLMOutputError)):
        return
    _cooldown[provider.name] = time.monotonic() + _COOLDOWN_SECONDS


def is_enabled() -> bool:
    return settings.llm_enabled


def get_client() -> Any:
    """Return the first configured client (backwards-compatible helper)."""
    return _ordered_providers()[0].client


# --------------------------------------------------------------------------- helpers
def _loads_json(text: str) -> Any:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _schema_format(response_model: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_model.__name__,
            "schema": response_model.model_json_schema(),
            "strict": False,
        },
    }


async def _extract_with(
    provider: _Provider,
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: type[TModel],
) -> TModel:
    schema_text = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": (
                f"{system_prompt}\n\n"
                "Return ONLY a JSON object that satisfies this JSON Schema. "
                "Do not wrap it in prose or markdown.\n"
                f"{schema_text}"
            ),
        },
        {"role": "user", "content": user_prompt},
    ]

    # 1. Native structured output (OpenAI SDK, best fidelity).
    try:
        completion = await provider.client.beta.chat.completions.parse(
            model=provider.model,
            messages=messages,
            response_format=response_model,
            temperature=0,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is not None:
            return parsed
    except Exception as exc:  # noqa: BLE001 - provider-specific unsupported feature
        logger.debug("%s native parse unavailable: %s", provider.name, exc)

    # 2. JSON Schema / JSON mode. This is the path most free providers support.
    last_error: Exception | None = None
    last_was_output = False
    for response_format in (_schema_format(response_model), {"type": "json_object"}):
        try:
            completion = await provider.client.chat.completions.create(
                model=provider.model,
                messages=messages,
                response_format=response_format,
                temperature=0,
                max_tokens=4096,
            )
            content = completion.choices[0].message.content or ""
            try:
                return response_model.model_validate(_loads_json(content))
            except (ValidationError, json.JSONDecodeError) as exc:
                # The provider answered; the answer was not usable. Try the next
                # format, but do not treat the endpoint as broken.
                last_error, last_was_output = exc, True
        except Exception as exc:  # noqa: BLE001 - transport/API error, try next format
            last_error, last_was_output = exc, False

    if last_was_output:
        raise LLMOutputError(
            f"{provider.name} did not return valid structured output: {last_error}"
        ) from last_error
    raise LLMUnavailable(
        f"{provider.name} request failed: {last_error}"
    ) from last_error


# --------------------------------------------------------------------------- public API
async def extract_structured(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: type[TModel],
) -> TModel:
    """Guaranteed-schema extraction, trying each provider in order."""
    global _preferred

    errors: list[str] = []
    providers = _ordered_providers()
    for index, provider in enumerate(providers):
        try:
            result = await _extract_with(
                provider,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )
            _preferred = provider.name
            if index > 0:
                logger.info("LLM extraction served by fallback provider %s", provider.name)
            return result
        except Exception as exc:  # noqa: BLE001 - fall through to the next provider
            errors.append(f"{provider.name}: {exc}")
            _cool_down(provider, exc)
            logger.warning("LLM provider %s failed: %s", provider.name, exc)

    raise LLMUnavailable("All LLM providers failed: " + "; ".join(errors))


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    global _preferred
    errors: list[str] = []
    for provider in _ordered_providers():
        if provider.name == "openrouter":
            # OpenRouter routes chat completions only; it has no embeddings endpoint.
            continue
        try:
            vectors: list[list[float]] = []
            batch_size = 64
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                response = await provider.client.embeddings.create(
                    model=provider.embedding_model,
                    input=batch,
                )
                vectors.extend([item.embedding for item in response.data])
            if len(vectors) == len(texts):
                _preferred = provider.name
                return vectors
            errors.append(f"{provider.name}: returned {len(vectors)} vectors")
        except Exception as exc:  # noqa: BLE001 - fall through
            errors.append(f"{provider.name}: {exc}")
            _cool_down(provider, exc)

    logger.warning("Embeddings unavailable (%s); continuing without vectors", "; ".join(errors))
    return []


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
    """Yield narrative tokens from the first provider that starts streaming."""
    global _preferred

    errors: list[str] = []
    for provider in _ordered_providers():
        try:
            stream = await provider.client.chat.completions.create(
                model=provider.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            _preferred = provider.name
        except Exception as exc:  # noqa: BLE001 - fall through
            errors.append(f"{provider.name}: {exc}")
            _cool_down(provider, exc)
            continue

        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
        return

    raise LLMUnavailable("All LLM providers failed: " + "; ".join(errors))


async def classify_intent(query: str, labels: list[str]) -> str | None:
    """Optional LLM fallback for the intent router (heuristics run first)."""
    if not settings.llm_enabled:
        return None

    for provider in _ordered_providers():
        try:
            completion = await provider.client.chat.completions.create(
                model=provider.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify the user's graph query intent. Reply with exactly one "
                            f"label from this list: {', '.join(labels)}."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                temperature=0,
                max_tokens=8,
            )
            label = (completion.choices[0].message.content or "").strip().upper()
            return label if label in labels else None
        except Exception as exc:  # noqa: BLE001 - network dependent
            logger.debug("Intent classification via %s failed: %s", provider.name, exc)
            _cool_down(provider, exc)
    return None


async def close_llm() -> None:
    global _providers
    if _providers is None:
        return
    for provider in _providers:
        try:
            await provider.client.close()
        except Exception:  # pragma: no cover - best effort
            pass
    _providers = None
