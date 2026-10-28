from llama_index.core.vector_stores.types import VectorStore
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy.engine import make_url
from app.db.session import SessionLocal as AppSessionLocal, engine as app_engine
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

singleton_instance = None
did_run_setup = False


class CustomPGVectorStore(PGVectorStore):
    """
    Custom PGVectorStore that uses the same connection pool as the FastAPI app.
    """

    def _connect(self) -> None:
        self._engine = create_engine(self.connection_string)
        self._session = sessionmaker(self._engine)

        # Use our existing app engine and session so we can use the same connection pool
        self._async_engine = app_engine
        self._async_session = AppSessionLocal

    async def close(self) -> None:
        self._session.close_all()
        self._engine.dispose()

        await self._async_engine.dispose()

    def _create_tables_if_not_exists(self) -> None:
        pass

    def _create_extension(self) -> None:
        pass

    async def run_setup(self) -> None:
        global did_run_setup
        if did_run_setup:
            return
        self._initialize()
        async with self._async_session() as session:
            async with session.begin():
                statement = sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector")
                await session.execute(statement)
                await session.commit()

        async with self._async_session() as session:
            async with session.begin():
                conn = await session.connection()
                await conn.run_sync(self._base.metadata.create_all)

        await self._verify_embed_dim()
        did_run_setup = True

    async def _verify_embed_dim(self) -> None:
        """Fail fast if the stored vectors were built for another dimension.

        ``create_all`` is a no-op for a pre-existing table, so after an
        embedding-model/dimension change the old ``vector(<n>)`` column would
        survive silently — every insert and similarity query would then fail
        deep inside ingestion/chat with a pgvector dimension error. Comparing
        the live column against the setting at deploy time turns that into
        one explicit, actionable boot failure.
        """
        table_name = self._table_class.__tablename__
        async with self._async_session() as session:
            result = await session.execute(
                sqlalchemy.text(
                    """
                    SELECT a.atttypmod
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = :table_name
                      AND n.nspname = :schema_name
                      AND a.attname = 'embedding'
                    """
                ),
                {"table_name": table_name, "schema_name": self.schema_name},
            )
            actual_dim = result.scalar_one_or_none()

        # atttypmod is the declared vector length, or -1 when unconstrained.
        if actual_dim is not None and actual_dim > 0 and actual_dim != settings.VECTOR_STORE_EMBED_DIM:
            raise RuntimeError(
                f"Vector table {self.schema_name}.{table_name} stores "
                f"vector({actual_dim}) embeddings, but VECTOR_STORE_EMBED_DIM is "
                f"{settings.VECTOR_STORE_EMBED_DIM} (embedding model "
                f"{settings.NVIDIA_EMBEDDING_MODEL_NAME!r}). The existing vectors "
                "were built by a different embedding model and cannot be reused: "
                f"DROP TABLE {self.schema_name}.{table_name}, restart so the "
                "table is recreated, then re-index every document "
                "(POST /api/document/{id}/reindex)."
            )

    async def ensure_initialized(self) -> None:
        """Create this process's engines without running any DDL.

        The extension/tables are ensured once per deploy via run_setup()
        (see app.main._bootstrap); each process only needs connection pools
        (the base class also calls _initialize lazily on first add/query).
        """
        self._initialize()


async def get_vector_store_singleton() -> VectorStore:
    global singleton_instance
    if singleton_instance is not None:
        return singleton_instance
    url = make_url(settings.DATABASE_URL)
    singleton_instance = CustomPGVectorStore.from_params(
        url.host,
        url.port or 5432,
        url.database,
        url.username,
        url.password,
        settings.VECTOR_STORE_TABLE_NAME,
        embed_dim=settings.VECTOR_STORE_EMBED_DIM,
    )
    return singleton_instance