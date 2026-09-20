"""
Application entry point.

start() (once per deploy, in the process that launches uvicorn):
    1. Configure logging
    2. Configure Sentry (optional)
    3. _bootstrap(): wait for database connection, verify Alembic migrations,
       initialise pgvector store (CREATE EXTENSION + tables), pre-download
       NLTK sentence tokenizer data, release the parent's DB connections
    4. Start uvicorn (BACKEND_WORKERS workers, default 4; reload when
       LOG_LEVEL=DEBUG, in which case workers are ignored by uvicorn)

lifespan (per worker process):
    1. _bootstrap() only if start() did not already run it (e.g. when the app
       is launched via `uvicorn app.main:app` directly)
    2. Configure LlamaIndex settings (Gemini LLM + embeddings) — per process;
       the blocking Gemini model-metadata lookup runs in a worker thread
    3. Initialise pgvector store engines for this process (no DDL — tables
       were already created in start())
    4. Start FastAPI
"""
from typing import cast
import asyncio
import os
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

_BOOTSTRAP_DONE_ENV_VAR = "FINCITE_BOOTSTRAP_DONE"


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


async def _bootstrap(release_connections: bool = False) -> None:
    """Deploy-time initialisation that only needs to run once per deploy,
    not once per uvicorn worker. All steps are idempotent."""
    # 1. Wait for the database to become available
    await check_database_connection()

    # 2. Verify Alembic migrations are current (sync psycopg2 engine)
    cfg = Config("alembic.ini")
    db_url = settings.DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    )
    cfg.set_main_option("sqlalchemy.url", db_url)
    engine = create_engine(db_url, echo=False)
    try:
        if not check_current_head(cfg, engine):
            raise Exception(
                "Database is not up to date. Please run `uv run alembic upgrade head`"
            )
    finally:
        engine.dispose()

    # 3. Initialise pgvector store: CREATE EXTENSION + ensure tables exist.
    #    Idempotent DDL, so once per deploy is sufficient.
    vector_store = cast(CustomPGVectorStore, await get_vector_store_singleton())
    await vector_store.run_setup()

    # 4. Pre-download NLTK sentence tokenizer data (cached on shared disk)
    try:
        split_by_sentence_tokenizer()
    except FileExistsError:
        logger.info("NLTK tokenizer files already present.")

    if release_connections:
        # The parent process does not serve requests: release its DB
        # connections (each uvicorn worker creates its own engines).
        await vector_store.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deploy-time bootstrap: skip when start() already ran it (uvicorn workers
    # inherit FINCITE_BOOTSTRAP_DONE from the parent's environment).
    if os.environ.get(_BOOTSTRAP_DONE_ENV_VAR) != "1":
        await _bootstrap()

    # 1. Configure LlamaIndex (Gemini LLM + embeddings) — per process. The
    #    Gemini constructor makes a blocking network call (model metadata
    #    lookup), so keep it off the event loop.
    await asyncio.to_thread(_setup_llama_index_settings)

    # 2. Create this process's vector store engines (no DDL).
    vector_store = cast(CustomPGVectorStore, await get_vector_store_singleton())
    await vector_store.ensure_initialized()

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
    docs_url=f"{settings.API_PREFIX}/docs",
    redoc_url=f"{settings.API_PREFIX}/redoc",
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
    """Launched with `uv run start`."""
    _setup_logging(settings.LOG_LEVEL)
    _setup_sentry()
    logger.info("Starting %s", settings.PROJECT_NAME)

    # Run the deploy-time bootstrap once here instead of in every uvicorn
    # worker (DB wait, migration check, pgvector setup, NLTK data). Workers
    # inherit FINCITE_BOOTSTRAP_DONE and skip it in their lifespan.
    asyncio.run(_bootstrap(release_connections=True))
    os.environ[_BOOTSTRAP_DONE_ENV_VAR] = "1"

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.LOG_LEVEL == "DEBUG",
        workers=settings.BACKEND_WORKERS,
    )