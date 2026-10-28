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
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    extraction_concurrency: int = 25
    llm_timeout_seconds: float = 90.0

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

    # ---- Graph persistence (demo / in-memory) ----
    graph_persist: bool = True
    graph_snapshot_file: Path = Field(default=BACKEND_ROOT / "data" / "runtime_graph.json")

    # ---- Reasoning ----
    ppr_alpha: float = 0.15
    ppr_top_k: int = 40
    max_path_hops: int = 5
    cache_ttl_seconds: int = 900

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())

    def ensure_upload_dir(self) -> Path:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        return self.upload_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
