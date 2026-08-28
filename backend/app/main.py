"""
Application entry point.

Startup sequence:
    1. Configure logging
    2. Configure Sentry (optional)
    3. Set up LlamaIndex settings (OpenAI LLM + embeddings)
    4. Wait for database connection
    5. Verify migrations are up to date
    6. Initialise pgvector store
    7. Initialise NLTK sentence tokenizer
    8. Start FastAPI
"""
from typing import cast
import uvicorn
import logging
import sys
import sentry_sdk
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from alembic.config import Config
import alembic.config
from alembic import script
from alembic.runtime import migration
from sqlalchemy.engine import create_engine, Engine
from llama_index.core.node_parser.text.utils import split_by_sentence_tokenizer
from contextlib import asynccontextmanager

from app.api.api import api_router
from app.db.wait_for_db import check_database_connection
from app.core.config import settings
from app.chat.pg_vector import get_vector_store_singleton, CustomPGVectorStore
from app.llama_index_settings import _setup_llama_index_settings

logger = logging.getLogger(__name__)


def check_current_head(alembic_cfg: Config, connectable: Engine) -> bool:
    directory = script.ScriptDirectory.from_config(alembic_cfg)
    with connectable.begin() as connection:
        context = migration.MigrationContext.configure(connection)
        return set(context.get_current_heads()) == set(directory.get_heads())


def _setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper())
    log_formatter = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s"
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    root_logger.addHandler(stream_handler)
    logger.info("Logging initialised at level %s", log_level)


def _setup_sentry() -> None:
    if settings.SENTRY_DSN:
        logger.info("Initialising Sentry")
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=0.1,
        )
    else:
        logger.info("Sentry DSN not set — skipping Sentry initialisation")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Wait for the database to become available
    await check_database_connection()

    # 2. Verify Alembic migrations are current
    cfg = Config("alembic.ini")
    db_url = settings.DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    )
    cfg.set_main_option("sqlalchemy.url", db_url)
    engine = create_engine(db_url, echo=False)
    if not check_current_head(cfg, engine):
        raise Exception(
            "Database is not up to date. Please run `poetry run alembic upgrade head`"
        )
    engine.dispose()

    # 3. Initialise pgvector store
    vector_store = await get_vector_store_singleton()
    vector_store = cast(CustomPGVectorStore, vector_store)
    await vector_store.run_setup()

    # 4. Pre-download NLTK sentence tokenizer data
    try:
        split_by_sentence_tokenizer()
    except FileExistsError:
        logger.info("NLTK tokenizer files already present.")

    yield

    # Shutdown: close vector store connections
    await vector_store.close()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "AI financial research backend for Indian / NSE company annual reports "
        "and filings. Upload PDFs, then ask questions across them using RAG."
    ),
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_PREFIX)


def start() -> None:
    """Launched with `poetry run start`."""
    _setup_logging(settings.LOG_LEVEL)
    _setup_sentry()
    _setup_llama_index_settings()
    logger.info("Starting %s", settings.PROJECT_NAME)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.LOG_LEVEL == "DEBUG",
        workers=1,
    )
