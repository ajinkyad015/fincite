import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from app import schema
from app.api import deps
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

#: Set on first import; used for the `uptime_s` field.
_STARTED_AT = time.time()


@router.get("", response_model=schema.HealthResponse)
@router.get("/", response_model=schema.HealthResponse, include_in_schema=False)
async def health(db: AsyncSession = Depends(deps.get_db)) -> schema.HealthResponse:
    """
    Liveness + readiness probe.

    `status` is ``healthy`` when the database answers, ``degraded`` when it does
    not — the endpoint itself always returns 200 so a client can distinguish
    "API unreachable" from "API up, database down". The frontend polls this for
    the sidebar indicator.
    """
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        logger.warning("Health check: database unreachable", exc_info=True)
        db_ok = False

    return schema.HealthResponse(
        status="healthy" if db_ok else "degraded",
        db=db_ok,
        vector_store=None,
        version=settings.APP_VERSION,
        uptime_s=round(time.time() - _STARTED_AT, 1),
    )
