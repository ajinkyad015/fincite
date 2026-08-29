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

    # Database
    DATABASE_URL: str

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "annual-reports"

    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_CHAT_LLM_NAME: str = "gpt-4o-mini"

    # Vector store
    VECTOR_STORE_TABLE_NAME: str = "pg_vector_store"

    # Logging
    LOG_LEVEL: str = "INFO"

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

    model_config = SettingsConfigDict(env_prefix="")


settings = Settings()
os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
