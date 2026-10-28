"""
Boot-time embedding-dimension guard (CustomPGVectorStore._verify_embed_dim).

The store object is constructed for real (construction does not connect),
and its async session factory is replaced with a fake that reports a chosen
stored dimension — no database needed.
"""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.chat.pg_vector import CustomPGVectorStore
from app.core.config import settings


def _store_with_stored_dim(stored_dim):
    store = CustomPGVectorStore.from_params(
        "localhost",
        5432,
        "db",
        "user",
        "password",
        settings.VECTOR_STORE_TABLE_NAME,
        embed_dim=settings.VECTOR_STORE_EMBED_DIM,
    )

    @asynccontextmanager
    async def fake_session_factory():
        result = SimpleNamespace(scalar_one_or_none=lambda: stored_dim)
        yield SimpleNamespace(execute=AsyncMock(return_value=result))

    store._async_session = fake_session_factory
    return store


def test_verify_embed_dim_accepts_matching_dimension():
    store = _store_with_stored_dim(settings.VECTOR_STORE_EMBED_DIM)
    asyncio.run(store._verify_embed_dim())  # must not raise


def test_verify_embed_dim_rejects_table_from_another_embedding_model():
    # e.g. a table created by the previous 3072-d provider.
    store = _store_with_stored_dim(3072)
    with pytest.raises(RuntimeError, match="cannot be reused"):
        asyncio.run(store._verify_embed_dim())


def test_verify_embed_dim_tolerates_missing_table_or_unconstrained_column():
    # Fresh deploy: no row in pg_attribute yet (None), or vector without a
    # declared length (-1). Neither is evidence of a mismatch.
    for stored_dim in (None, -1):
        store = _store_with_stored_dim(stored_dim)
        asyncio.run(store._verify_embed_dim())
