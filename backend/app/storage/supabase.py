"""
Supabase Storage abstraction for document (PDF) management.

All PDF files are stored under:
    documents/{document_id}/original.pdf

The Supabase service-role key is used server-side only and is never exposed
to the frontend or returned in API responses.
"""
import logging
from io import BytesIO
from typing import Optional

from supabase import create_client, Client
from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level singleton so we re-use a single client per process lifetime.
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """Return (or lazily create) the Supabase client singleton."""
    global _supabase_client
    if _supabase_client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to use "
                "Supabase Storage."
            )
        _supabase_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY,
        )
    return _supabase_client


def _storage_path(document_id: str) -> str:
    """Return the canonical storage path for a document's PDF."""
    return f"documents/{document_id}/original.pdf"


def upload_document(file_bytes: bytes, document_id: str) -> str:
    """
    Upload a PDF to Supabase Storage.

    Returns the public storage path (not a signed URL; the backend can
    generate a signed URL on demand via get_document_url).

    Raises RuntimeError on failure.
    """
    path = _storage_path(document_id)
    client = get_supabase_client()
    logger.info("Uploading document %s to Supabase Storage at %s", document_id, path)
    try:
        client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).upload(
            path=path,
            file=file_bytes,
            file_options={"content-type": "application/pdf", "upsert": "false"},
        )
        logger.info("Successfully uploaded document %s", document_id)
        return path
    except Exception as exc:
        logger.error(
            "Failed to upload document %s to Supabase Storage: %s",
            document_id,
            exc,
            exc_info=True,
        )
        raise RuntimeError(f"Supabase Storage upload failed: {exc}") from exc


def download_document(document_id: str) -> bytes:
    """
    Download a PDF from Supabase Storage and return its raw bytes.

    Raises RuntimeError on failure.
    """
    path = _storage_path(document_id)
    client = get_supabase_client()
    logger.info("Downloading document %s from Supabase Storage", document_id)
    try:
        data = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).download(path)
        logger.info("Successfully downloaded document %s (%d bytes)", document_id, len(data))
        return data
    except Exception as exc:
        logger.error(
            "Failed to download document %s from Supabase Storage: %s",
            document_id,
            exc,
            exc_info=True,
        )
        raise RuntimeError(f"Supabase Storage download failed: {exc}") from exc


def delete_document(document_id: str) -> None:
    """
    Delete a PDF from Supabase Storage.

    Logs a warning on failure but does not raise, so cleanup paths can
    proceed without cascading errors.
    """
    path = _storage_path(document_id)
    client = get_supabase_client()
    logger.info("Deleting document %s from Supabase Storage", document_id)
    try:
        client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).remove([path])
        logger.info("Deleted document %s from storage", document_id)
    except Exception as exc:
        logger.warning(
            "Could not delete document %s from Supabase Storage: %s",
            document_id,
            exc,
        )


def get_document_url(document_id: str) -> str:
    """
    Return a public or signed URL for the stored PDF.

    Uses the Supabase Storage public URL pattern. If the bucket is private,
    replace this with a signed URL call.
    """
    path = _storage_path(document_id)
    client = get_supabase_client()
    result = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).get_public_url(path)
    return result
