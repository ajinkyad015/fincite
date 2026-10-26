"""
Document endpoints.

Provides:
    POST   /upload            — Upload a PDF; indexing runs in the background
    GET    /                  — List / filter documents (200 + [] when empty)
    GET    /{document_id}     — Get a single document (includes ingestion status)
    GET    /{document_id}/file— Stream the original PDF (citation viewer)
    POST   /{document_id}/reindex — Re-run ingestion from storage
    DELETE /{document_id}     — Delete the PDF, its vectors and its rows
"""
import asyncio
import hashlib
import logging
import uuid as uuid_module
from typing import List, Optional

from fastapi import (
    Depends,
    APIRouter,
    HTTPException,
    Query,
    Response,
    UploadFile,
    File,
    Form,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.api.deps import get_db
from app.api import crud
from app import schema
from app.core.config import settings
from app.ingestion import jobs
from app.models.db import DocumentStatusEnum
from app.storage.supabase import (
    upload_document,
    delete_document,
    download_document,
    get_document_url,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_ALLOWED_CONTENT_TYPES = {"application/pdf"}
_PDF_MAGIC_BYTES = b"%PDF"


def _validate_pdf(file: UploadFile, content: bytes) -> None:
    """
    Basic PDF validation: check content-type header and magic bytes.
    Raises HTTPException 400 on failure.
    """
    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are accepted. Received content-type: {content_type}",
        )
    if not content.startswith(_PDF_MAGIC_BYTES):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file does not appear to be a valid PDF.",
        )


def _upload_response(document: schema.Document) -> schema.DocumentUploadResponse:
    """Build the upload/patch response from a stored document."""
    return schema.DocumentUploadResponse(
        id=document.id,
        created_at=document.created_at,
        updated_at=document.updated_at,
        url=document.url,
        metadata_map=document.metadata_map,
        status=document.status,
        progress=document.progress,
        error=document.error,
        page_count=document.page_count,
        file_size=document.file_size,
        content_hash=document.content_hash,
    )


@router.post("/upload", response_model=schema.DocumentUploadResponse, status_code=202)
async def upload_document_endpoint(
    response: Response,
    file: UploadFile = File(..., description="PDF file to upload and index"),
    company_name: Optional[str] = Form(None, description="Company name (e.g. Reliance Industries)"),
    company_symbol: Optional[str] = Form(None, description="NSE ticker symbol (e.g. RELIANCE)"),
    financial_year: Optional[str] = Form(None, description="Financial year (e.g. 2024-25)"),
    document_type: Optional[schema.NSEDocumentTypeEnum] = Form(
        schema.NSEDocumentTypeEnum.ANNUAL_REPORT,
        description="Type of document",
    ),
    exchange: Optional[str] = Form("NSE", description="Exchange (default: NSE)"),
    db: AsyncSession = Depends(get_db),
) -> schema.DocumentUploadResponse:
    """
    Accept a PDF and schedule indexing.

    Workflow:
    1. Validate the uploaded file is a PDF and within the size limit.
    2. Check for duplicate (by SHA-256 content hash) → return the existing document.
    3. Generate a UUID, upload the PDF to Supabase Storage, create the row
       with ``status="uploaded"``.
    4. Schedule background ingestion and return **202**.

    The client polls ``GET /api/document/{id}`` until ``status`` is ``ready`` or
    ``failed`` — indexing a 300-page filing takes minutes, far longer than an
    HTTP request should live.

    Only `file` is required. All metadata fields are optional.
    """
    # Explicit: the duplicate branch below downgrades this to 200.
    response.status_code = status.HTTP_202_ACCEPTED

    if file is None:
        raise HTTPException(status_code=400, detail="No file was provided.")

    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF is larger than the {settings.MAX_UPLOAD_MB} MB limit.",
        )

    # Basic PDF validation
    _validate_pdf(file, content)

    # Duplicate detection via SHA-256 content hash
    content_hash = hashlib.sha256(content).hexdigest()
    existing = await crud.fetch_document_by_content_hash(db, content_hash)
    if existing:
        logger.info(
            "Duplicate upload detected (hash=%s). Returning existing document %s.",
            content_hash,
            existing.id,
        )
        # 200 (not 202): nothing was scheduled, the document already exists.
        response.status_code = status.HTTP_200_OK
        return _upload_response(existing)

    # Derive company_name from filename if not supplied
    original_filename = file.filename or "document.pdf"
    resolved_company_name = (
        company_name
        or original_filename.replace(".pdf", "").replace("-", " ").replace("_", " ").title()
        or "Unknown Company"
    )

    # Build NSE metadata
    nse_metadata = schema.NSEDocumentMetadata(
        company_name=resolved_company_name,
        company_symbol=company_symbol.upper() if company_symbol else None,
        document_type=document_type or schema.NSEDocumentTypeEnum.ANNUAL_REPORT,
        financial_year=financial_year,
        exchange=exchange or "NSE",
        original_filename=original_filename,
    )

    document_id = str(uuid_module.uuid4())
    logger.info("Document upload started: id=%s file=%s", document_id, original_filename)

    # Upload to Supabase Storage
    try:
        upload_document(content, document_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload file to storage: {exc}",
        )

    # Build the public storage URL (server-side reference; clients never get
    # direct storage credentials — see GET /{id}/file).
    storage_url = get_document_url(document_id)

    # Create database record in the "uploaded" state
    doc_schema = schema.Document(
        id=uuid_module.UUID(document_id),
        url=storage_url,
        metadata_map={
            schema.DocumentMetadataKeysEnum.NSE_DOCUMENT: nse_metadata.model_dump(mode="json"),
            "content_hash": content_hash,
            "original_filename": original_filename,
        },
        status=DocumentStatusEnum.uploaded,
        progress=0,
        content_hash=content_hash,
        file_size=len(content),
    )
    try:
        db_doc = await crud.create_document(db, doc_schema)
        logger.info("Database record created for document %s", document_id)
    except Exception as exc:
        logger.error("Failed to create database record for %s: %s", document_id, exc, exc_info=True)
        # Clean up storage
        delete_document(document_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to create document record in database.",
        )

    # Index in the background — the request returns immediately.
    if settings.INGESTION_ENABLED:
        jobs.schedule_ingestion(document_id)
    else:
        logger.warning("INGESTION_ENABLED is false — document %s will not be indexed", document_id)

    return _upload_response(db_doc)


@router.get("/", response_model=List[schema.Document])
async def get_documents(
    document_ids: Optional[List[UUID]] = Query(None, description="Filter by document ids"),
    status: Optional[DocumentStatusEnum] = Query(None, description="Filter by ingestion status"),
    q: Optional[str] = Query(
        None, description="Free-text search over company, symbol, fiscal year and filename"
    ),
    limit: Optional[int] = Query(None, ge=1, le=200),
    offset: Optional[int] = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
) -> List[schema.Document]:
    """
    Get all documents or documents filtered by ids / status / free text.

    Returns ``200 []`` for an empty library: clients poll this endpoint and a 404
    is not an error state.
    """
    return await crud.fetch_documents(
        db,
        ids=[str(d) for d in document_ids] if document_ids else None,
        status=status,
        query=q,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=schema.Document)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> schema.Document:
    """
    Get a single document by its ID — includes the ingestion status the library
    UI polls (`status`, `progress`, `error`).
    """
    document = await crud.fetch_document(db, str(document_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: UUID,
    download: bool = Query(False, description="Force a download instead of inline display"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Stream the original PDF for the citation viewer.

    The bytes are proxied from Supabase Storage so the bucket can stay private
    and the service-role key never leaves the server. Browsers can jump straight
    to a page with ``#page=N`` on the returned URL.
    """
    document = await crud.fetch_document(db, str(document_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        pdf_bytes = await asyncio.to_thread(download_document, str(document_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch the stored PDF: {exc}")

    filename = document.original_filename or f"{document_id}.pdf"
    disposition = "attachment" if download else "inline"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post("/{document_id}/reindex", response_model=schema.DocumentUploadResponse, status_code=202)
async def reindex_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> schema.DocumentUploadResponse:
    """
    Re-run ingestion for an existing document from its stored PDF.

    Used by the library's "Retry indexing" action for documents stuck in
    ``failed`` — the most common cause is a transient embedding error.
    """
    document = await crud.fetch_document(db, str(document_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if jobs.is_running(str(document_id)):
        raise HTTPException(status_code=409, detail="Indexing is already running for this document")

    # Clear the previous vector rows so a re-index cannot double-count chunks.
    try:
        await jobs.delete_document_vectors(str(document_id))
    except Exception:  # noqa: BLE001 — a failed cleanup must not block the retry
        logger.warning("Could not clear vectors for %s before re-indexing", document_id, exc_info=True)

    await crud.update_document_status(
        db, str(document_id), DocumentStatusEnum.uploaded, progress=0, error=""
    )
    jobs.schedule_ingestion(str(document_id))

    refreshed = await crud.fetch_document(db, str(document_id))
    return _upload_response(refreshed or document)


@router.delete("/{document_id}", status_code=204, response_model=None)
async def delete_document_endpoint(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a filing for good: vectors, stored PDF, conversation links and the row.

    Vectors go first — if that fails we abort, because a document that is gone
    from the library but still retrievable is worse than a failed delete.
    """
    document = await crud.fetch_document(db, str(document_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        await jobs.delete_document_vectors(str(document_id))
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not delete vectors for %s: %s", document_id, exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Could not clear the document's search index; nothing was deleted. Try again.",
        )

    delete_document(str(document_id))
    await crud.delete_document_by_id(db, str(document_id))
    logger.info("Document %s deleted", document_id)
    return None
