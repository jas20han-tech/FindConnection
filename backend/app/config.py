from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All runtime configuration. Values come from `.env` or the environment."""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env", BACKEND_ROOT.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Core ----
    app_name: str = "GraphRAG Intelligence Platform"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    demo_mode: bool = True
    use_celery: bool = False
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"

    # ---- LLM ----
    # Providers are tried in this order; the first one that answers wins.
    # Names not listed here are ignored even when credentials are configured.
    llm_provider_order: str = "gemini,ollama,openrouter,openai"
    extraction_concurrency: int = 25
    llm_timeout_seconds: float = 90.0

    # OpenAI (optional, kept as the last-resort provider)
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    embedding_model: str = "text-embedding-3-small"

    # Google Gemini (OpenAI-compatible endpoint)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_embedding_model: str = "gemini-embedding-001"

    # Ollama (local, no key). Set OLLAMA_ENABLED=true once the server is running.
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_embedding_model: str = "nomic-embed-text"

    # OpenRouter (free-tier models available)
    openrouter_api_key: str | None = None
    openrouter_model: str = "nvidia/nemotron-3.5-super-vl:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ---- Neo4j ----
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "graphrag_dev_password"
    neo4j_database: str = "neo4j"
    seed_on_startup: bool = True

    # ---- PostgreSQL ----
    postgres_dsn: str = "postgresql+asyncpg://graphrag:graphrag@localhost:5432/graphrag"

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- ChromaDB ----
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_chunks: str = "document_chunks"
    chroma_collection_entities: str = "entity_descriptions"

    # ---- Ingestion ----
    upload_dir: Path = Field(default=BACKEND_ROOT / "uploads")
    chunk_size: int = 800
    chunk_overlap: int = 150
    max_upload_mb: int = 25
    # "auto" tries Docling first and falls back to PyMuPDF; "docling" and
    # "pymupdf" force a single parser.
    pdf_parser: str = "auto"

    # ---- Graph persistence (demo / in-memory) ----
    graph_persist: bool = True
    # Accumulate documents into one evolving graph. Default false: each upload
    # starts from an empty canvas so the live graph and the exported network
    # describe only the PDF that was just uploaded. Set true to merge every
    # document into one graph.
    graph_accumulate: bool = False
    graph_snapshot_file: Path = Field(default=BACKEND_ROOT / "data" / "runtime_graph.json")

    # ---- Verification network export ----
    network_dir: Path = Field(default=BACKEND_ROOT / "data" / "networks")

    # ---- Reasoning ----
    ppr_alpha: float = 0.15
    ppr_top_k: int = 40
    max_path_hops: int = 5
    cache_ttl_seconds: int = 900

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_providers(self) -> list[str]:
        """Configured provider order, normalised and de-duplicated."""
        ordered: list[str] = []
        for name in self.llm_provider_order.split(","):
            cleaned = name.strip().lower()
            if cleaned and cleaned not in ordered:
                ordered.append(cleaned)
        return ordered

    def provider_credentials(self, name: str) -> tuple[str | None, str | None, str | None]:
        """Return (api_key, base_url, model) for a provider name."""
        if name == "gemini":
            return self.gemini_api_key, self.gemini_base_url, self.gemini_model
        if name == "ollama":
            return "ollama", self.ollama_base_url, self.ollama_model
        if name == "openrouter":
            return self.openrouter_api_key, self.openrouter_base_url, self.openrouter_model
        if name == "openai":
            return self.openai_api_key, self.openai_base_url, self.openai_model
        return None, None, None

    def provider_enabled(self, name: str) -> bool:
        if name == "ollama":
            return self.ollama_enabled
        api_key, _, _ = self.provider_credentials(name)
        return bool(api_key and api_key.strip())

    @property
    def llm_enabled(self) -> bool:
        return any(self.provider_enabled(name) for name in self.llm_providers)

    def ensure_upload_dir(self) -> Path:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        return self.upload_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
