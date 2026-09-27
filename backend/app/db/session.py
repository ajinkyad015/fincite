from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=2,       # 2 connections per worker; ×4 workers = 8 steady-state connections
    max_overflow=2,    # Allow up to 4 connections per worker under burst; 16 total
    pool_recycle=3600, # Recycle connections after 1 hour to avoid stale sockets
    pool_timeout=30,   # Fail fast (30 s) rather than hanging for 2 min → prevents 504
)
SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)
