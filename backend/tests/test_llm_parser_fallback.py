"""Tests for provider failover and parser fallback (free-LLM stack)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.config import settings
from app.core import llm
from app.ingestion import parser
from app.ingestion.parser import ParsedDocument


class _Entity(BaseModel):
    name: str
    type: str = "ORGANIZATION"


def _fake_client(*, parsed: BaseModel | None = None, fail: bool = False) -> SimpleNamespace:
    async def parse(**_: object) -> SimpleNamespace:
        if fail:
            raise RuntimeError("provider unavailable")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
        )

    async def create(**_: object) -> SimpleNamespace:
        if fail:
            raise RuntimeError("provider unavailable")
        content = json.dumps(parsed.model_dump() if parsed else {})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    completions = SimpleNamespace(parse=parse, create=create)
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        chat=SimpleNamespace(completions=completions),
        close=lambda: None,
    )


def _provider(name: str, client: SimpleNamespace) -> llm._Provider:
    return llm._Provider(
        name=name,
        model=f"{name}-model",
        embedding_model=f"{name}-embed",
        client=client,
    )


# --------------------------------------------------------------------------- LLM
def test_provider_order_follows_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key")
    monkeypatch.setattr(settings, "openrouter_api_key", "openrouter-key")
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "ollama_enabled", False)
    monkeypatch.setattr(settings, "llm_provider_order", "gemini,ollama,openrouter,openai")

    llm.reset_providers()
    try:
        providers = llm._build_providers()
        assert [provider.name for provider in providers] == ["gemini", "openrouter"]
    finally:
        llm.reset_providers()


def test_extract_falls_back_to_next_provider(monkeypatch: pytest.MonkeyPatch):
    expected = _Entity(name="Konoha", type="ORGANIZATION")
    broken = _provider("gemini", _fake_client(fail=True))
    working = _provider("openrouter", _fake_client(parsed=expected))

    monkeypatch.setattr(llm, "_ordered_providers", lambda: [broken, working])
    monkeypatch.setattr(llm, "_cooldown", {})
    llm._preferred = None

    result = asyncio.run(
        llm.extract_structured(
            system_prompt="Extract entities.",
            user_prompt="Konoha is a village.",
            response_model=_Entity,
        )
    )

    assert result == expected
    assert llm._preferred == "openrouter"
    assert "gemini" in llm._cooldown
    llm.reset_providers()


def test_extract_raises_when_every_provider_fails(monkeypatch: pytest.MonkeyPatch):
    first = _provider("gemini", _fake_client(fail=True))
    second = _provider("ollama", _fake_client(fail=True))

    monkeypatch.setattr(llm, "_ordered_providers", lambda: [first, second])
    monkeypatch.setattr(llm, "_cooldown", {})
    llm._preferred = None

    with pytest.raises(llm.LLMUnavailable):
        asyncio.run(
            llm.extract_structured(
                system_prompt="Extract entities.",
                user_prompt="Nothing here.",
                response_model=_Entity,
            )
        )
    llm.reset_providers()


# --------------------------------------------------------------------------- parser
def _parsed(source: str) -> ParsedDocument:
    return ParsedDocument(
        doc_hash="b" * 64,
        filename="sample.pdf",
        title="Sample",
        pages=["page one"],
        page_count=1,
        text="page one",
        metadata={},
        parser=source,
    )


def test_docling_failure_falls_back_to_pymupdf(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    def boom(*_: object, **__: object) -> ParsedDocument:
        raise RuntimeError("docling model missing")

    monkeypatch.setattr(parser, "_parse_pdf_docling", boom)
    monkeypatch.setattr(parser, "_parse_pdf_pymupdf", lambda *a, **k: _parsed("pymupdf"))
    monkeypatch.setattr(settings, "pdf_parser", "auto")

    result = asyncio.run(
        parser._parse_pdf(tmp_path / "sample.pdf", b"%PDF-1.7", "sample.pdf")
    )
    assert result.parser == "pymupdf"


def test_forced_pymupdf_never_calls_docling(tmp_path, monkeypatch: pytest.MonkeyPatch):
    def unexpected(*_: object, **__: object) -> ParsedDocument:
        raise AssertionError("Docling should not be called when PDF_PARSER=pymupdf")

    monkeypatch.setattr(parser, "_parse_pdf_docling", unexpected)
    monkeypatch.setattr(parser, "_parse_pdf_pymupdf", lambda *a, **k: _parsed("pymupdf"))
    monkeypatch.setattr(settings, "pdf_parser", "pymupdf")

    result = asyncio.run(
        parser._parse_pdf(tmp_path / "sample.pdf", b"%PDF-1.7", "sample.pdf")
    )
    assert result.parser == "pymupdf"


def test_document_title_strips_upload_hash_and_keeps_case():
    from app.ingestion.parser import _document_title

    title = _document_title(
        "5fdc6d51282f49b6bbed7956b11b718a_The Will of Fire_ Chronicles of the Hidden Leaf.pdf"
    )
    assert title == "The Will of Fire Chronicles of the Hidden Leaf"
    assert _document_title("onyx.txt") == "Onyx"
    assert _document_title("upload.pdf", {"title": "Report 2026"}) == "Report 2026"
