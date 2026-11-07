from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings


def create_app_engine():
    """Build the app's async engine from the current settings.

    Factored out of module scope so the settings -> engine wiring is
    testable; the module-level engine below is what the app actually uses.

    Every pool value is PER WORKER PROCESS: the total Postgres connection
    footprint is workers x (pool_size + max_overflow), plus the vector
    store's sync engine in each worker. Keep these small on hosted free
    tiers (Supabase's direct/pooler limits) or the database starts refusing
    connections under load.
    """
    return create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        # Recycle before the provider's idle timeout silently drops
        # connections.
        pool_recycle=settings.DB_POOL_RECYCLE_S,
        pool_timeout=settings.DB_POOL_TIMEOUT_S,
    )


engine = create_app_engine()
SessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    # Async sessions must never lazy-load an expired attribute implicitly:
    # that does sync IO in an async context and raises MissingGreenlet. Code
    # that needs fresh values refreshes/re-queries explicitly (see
    # crud.create_message / crud.finalise_message).
    expire_on_commit=False,
)
