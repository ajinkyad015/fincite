"""Public, non-secret runtime configuration for the client."""
from fastapi import APIRouter

from app import schema
from app.core.config import settings

router = APIRouter()


@router.get("/", response_model=schema.ConfigResponse)
async def get_config() -> schema.ConfigResponse:
    """
    What the UI needs to render itself correctly: upload limits, accepted types,
    whether auth is on, and whether this deployment is a demo.

    Nothing here is sensitive — credentials never leave the server.
    """
    return schema.ConfigResponse(
        version=settings.APP_VERSION,
        max_upload_mb=settings.MAX_UPLOAD_MB,
        supported_content_types=["application/pdf"],
        auth_enabled=settings.AUTH_ENABLED,
        demo_mode=settings.DEMO_MODE,
    )
