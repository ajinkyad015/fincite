import os
from typing import List, Union, Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator


class Settings(BaseSettings):
    """
    Application settings for the NSE Annual Reports RAG backend.
    """

    PROJECT_NAME: str = "fincite"
    API_PREFIX: str = "/api"
    APP_VERSION: str = "0.2.0"

    # Database
    DATABASE_URL: str

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "annual-reports"

    # NVIDIA AI (build.nvidia.com hosted NIMs, OpenAI-compatible API).
    # One `nvapi-…` key serves both chat and embeddings. Get one from any
    # model page on https://build.nvidia.com ("Get API Key").
    NVIDIA_API_KEY: str
    # ReAct brain + question generation + synthesis. Any chat model id from
    # the NVIDIA API catalog works here (ids are `org/model`, no `models/`
    # prefix). The default is in llama-index-llms-nvidia's known-model table,
    # so constructing it needs no catalog lookup; an unknown id makes the
    # client verify it against GET /v1/models at startup instead.
    NVIDIA_CHAT_LLM_NAME: str = "meta/llama-3.3-70b-instruct"
    # Must stay in lock-step with VECTOR_STORE_EMBED_DIM below (this model's
    # native — and only — output size is 2048).
    NVIDIA_EMBEDDING_MODEL_NAME: str = "nvidia/nemotron-3-embed-1b"
    # Hosted API catalog endpoint. Override to point at a self-hosted NIM
    # (e.g. "http://localhost:8080/v1").
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    # llama-index-llms-nvidia (an OpenAILike) otherwise assumes a 3900-token
    # window and a 1024-token reply cap, which would starve the response
    # synthesizer and truncate answers. 131072 / 4096 are this model's NIM
    # context length and max_tokens ceiling; keep them matched to
    # NVIDIA_CHAT_LLM_NAME when swapping models.
    NVIDIA_CHAT_CONTEXT_WINDOW: int = 131072
    NVIDIA_CHAT_MAX_TOKENS: int = 4096

    # Vector store
    VECTOR_STORE_TABLE_NAME: str = "pg_vector_store"
    # Must equal NVIDIA_EMBEDDING_MODEL_NAME's output dimension. Changing it
    # (or the embedding model) makes every stored vector unusable: drop and
    # recreate the vector table, then re-index every document. Startup
    # refuses to run against a table built for a different dimension.
    VECTOR_STORE_EMBED_DIM: int = 2048

    # Uploads
    MAX_UPLOAD_MB: int = 50

    # Ingestion
    # Set to false to accept uploads without indexing them (e.g. UI work that
    # does not need embedding calls). Documents then stay in "uploaded".
    INGESTION_ENABLED: bool = True

    # Auth (M4). While false, every endpoint is public — see AGENTS.md §14.Q.
    AUTH_ENABLED: bool = False
    # Marks a seeded/demo deployment so the UI can label it.
    DEMO_MODE: bool = False

    # Logging
    LOG_LEVEL: str = "INFO"

    # Server
    # Uvicorn worker processes (ignored by uvicorn when reload is enabled)
    BACKEND_WORKERS: int = 4

    # CORS — JSON-formatted list of origins
    # e.g: '["http://localhost", "http://localhost:3000"]'
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl | Literal["*"]] = []

    # Optional observability
    SENTRY_DSN: Optional[str] = None

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    @field_validator("DATABASE_URL", mode="before")
    def assemble_db_url(cls, v: str) -> str:
        """Preprocesses the database URL to make it compatible with asyncpg."""
        if not v or not v.startswith("postgres"):
            raise ValueError("Invalid database URL: " + str(v))
        v = v.strip()
        # Already in asyncpg form — leave as-is
        if "+asyncpg" in v:
            return v
        return (
            v.replace("postgres://", "postgresql://")
            .replace("postgresql://", "postgresql+asyncpg://")
        )

    @field_validator("LOG_LEVEL", mode="before")
    def assemble_log_level(cls, v: str) -> str:
        """Validates and normalises the log level."""
        v = v.strip().upper()
        if v not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError("Invalid log level: " + str(v))
        return v

    model_config = SettingsConfigDict(
        env_prefix="", 
        env_file=".env",
        env_file_encoding="utf-8",
    )

settings = Settings()
# The NVIDIA LlamaIndex clients fall back to these env vars when a parameter
# is not passed explicitly; keep the environment in sync with the validated
# settings (we also pass both explicitly — see app/llama_index_settings.py).
os.environ["NVIDIA_API_KEY"] = settings.NVIDIA_API_KEY
os.environ["NVIDIA_BASE_URL"] = settings.NVIDIA_BASE_URL