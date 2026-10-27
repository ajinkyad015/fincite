"""Application settings.

Everything that describes a *model* lives here (env / ``.env``), never in the
LlamaIndex factories: ids, endpoint, key and the capabilities LlamaIndex needs
to know about (chat vs completion, function calling, context window, output
cap, embedding request shape). Swapping a model is a config change, not a code
change — see ``backend/.env.example`` and ``AGENTS.md`` §10.
"""
from typing import List, Union, Literal, Optional

from pydantic import AnyHttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ─────────────────────────────────────────────────────────────────────
    # Model providers (any OpenAI-compatible endpoint).
    #
    # The ``NVIDIA_*`` names are historical: build.nvidia.com is the default,
    # but nothing below is NVIDIA-specific. Point NVIDIA_BASE_URL at a
    # self-hosted NIM, vLLM, or another /v1-compatible gateway and set the
    # model ids to whatever that endpoint serves.
    # ─────────────────────────────────────────────────────────────────────
    # One key for chat + embeddings. Any non-empty string works for an
    # unauthenticated local endpoint.
    NVIDIA_API_KEY: str
    # OpenAI-compatible base URL, with or without a trailing slash.
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # --- Chat model -----------------------------------------------------
    # ReAct brain + sub-question generation + response synthesis. Use the
    # exact id the endpoint expects (NIM ids look like ``org/model``).
    NVIDIA_CHAT_LLM_NAME: str = "meta/llama-3.3-70b-instruct"
    # Declared capabilities. LlamaIndex's LLMMetadata requires real booleans;
    # the old NVIDIA client tried to infer them from a frozen model table and
    # produced ``None`` for newer ids (pydantic ValidationError in
    # get_response_synthesizer). Declare them explicitly for *every* model.
    # ReAct here is prompt-based, so function calling is off by default; turn
    # it on only if the endpoint supports OpenAI-style tool calls.
    NVIDIA_CHAT_IS_CHAT_MODEL: bool = True
    NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL: bool = False
    # Used to size synthesizer prompts and cap replies. Defaults are the
    # shipped chat model's limits — re-check them when changing the model id.
    NVIDIA_CHAT_CONTEXT_WINDOW: int = 131072
    NVIDIA_CHAT_MAX_TOKENS: int = 4096
    # Per-request timeout (seconds) for chat completions, including streams.
    NVIDIA_CHAT_TIMEOUT: float = 120.0

    # --- Embedding model ------------------------------------------------
    # Must output exactly VECTOR_STORE_EMBED_DIM dimensions. Changing the id
    # (or its output size) invalidates every stored vector: drop and recreate
    # the vector table, then re-index every document.
    NVIDIA_EMBEDDING_MODEL_NAME: str = "nvidia/nemotron-3-embed-1b"
    # ``nim``     — send asymmetric ``input_type`` (passage/query) plus
    #               ``truncate`` in extra_body, as NVIDIA NIMs expect.
    # ``openai``  — plain /v1/embeddings request (no NIM-only fields).
    NVIDIA_EMBEDDING_REQUEST_STYLE: Literal["nim", "openai"] = "nim"
    NVIDIA_EMBEDDING_TRUNCATE: Literal["NONE", "START", "END"] = "END"
    # Optional reduced output size for models that support it. Must equal
    # VECTOR_STORE_EMBED_DIM (validated below) or retrieval breaks.
    NVIDIA_EMBEDDING_DIMENSIONS: Optional[int] = None

    # Vector store
    VECTOR_STORE_TABLE_NAME: str = "pg_vector_store"
    # Must equal the embedding model's output dimension. Changing it (or the
    # embedding model) makes every stored vector unusable: drop and recreate
    # the vector table, then re-index every document. Startup refuses to run
    # against a table built for a different dimension.
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

    @field_validator("NVIDIA_BASE_URL", mode="before")
    @classmethod
    def normalise_base_url(cls, v: str) -> str:
        """One canonical form for both clients (OpenAI SDK appends /chat/...)."""
        if not isinstance(v, str):
            return v
        url = v.strip().rstrip("/")
        if not url:
            raise ValueError("NVIDIA_BASE_URL must not be empty")
        return url

    @field_validator("NVIDIA_CHAT_LLM_NAME", "NVIDIA_EMBEDDING_MODEL_NAME")
    @classmethod
    def non_empty_model_id(cls, v: str) -> str:
        """Model ids are free-form strings — never hardcode or validate a list."""
        value = v.strip()
        if not value:
            raise ValueError("model id must not be empty; set it in .env")
        return value

    @field_validator(
        "NVIDIA_CHAT_CONTEXT_WINDOW",
        "NVIDIA_CHAT_MAX_TOKENS",
        "VECTOR_STORE_EMBED_DIM",
    )
    @classmethod
    def positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v

    @field_validator("NVIDIA_CHAT_TIMEOUT")
    @classmethod
    def positive_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("NVIDIA_CHAT_TIMEOUT must be positive")
        return v

    @model_validator(mode="after")
    def embedding_dimensions_match_vector_store(self) -> "Settings":
        """A configured output size must match the pgvector column exactly."""
        requested = self.NVIDIA_EMBEDDING_DIMENSIONS
        if requested is not None and requested != self.VECTOR_STORE_EMBED_DIM:
            raise ValueError(
                "NVIDIA_EMBEDDING_DIMENSIONS must equal VECTOR_STORE_EMBED_DIM "
                f"({self.VECTOR_STORE_EMBED_DIM}); pgvector cannot store a mix "
                "of dimensions. Change both settings, recreate the vector "
                "table and re-index every document."
            )
        return self

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
