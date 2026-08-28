"""
Document endpoints.

Provides:
    POST /upload       — Upload a PDF and index it (new)
    GET  /             — List / filter documents
    GET  /{document_id} — Get a single document
"""
import hashlib
import logging
import uuid as uuid_module
from typing import List, Optional

from fastapi import Depends, APIRouter, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.api.deps import get_db
from app.api import crud
from app import schema
from app.chat.pg_vector import get_vector_store_singleton
from app.ingestion.pdf import ingest_document
from app.storage.supabase import upload_document, delete_document

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


@router.post("/upload", response_model=schema.DocumentUploadResponse, status_code=201)
async def upload_document_endpoint(
    file: UploadFile = File(..., description="PDF file to upload and index"),
    company_name: Optional[str] = Form(None, description="Company name (e.g. Reliance Industries)"),
    company_symbol: Optional[str] = Form(None, description="NSE ticker symbol (e.g. RELIANCE)"),
    financial_year: Optional[str] = Form(None, description="Financial year (e.g. 2025)"),
    document_type: Optional[schema.NSEDocumentTypeEnum] = Form(
        schema.NSEDocumentTypeEnum.ANNUAL_REPORT,
        description="Type of document",
    ),
    exchange: Optional[str] = Form("NSE", description="Exchange (default: NSE)"),
    db: AsyncSession = Depends(get_db),
) -> schema.DocumentUploadResponse:
    """
    Upload a PDF and make it immediately available for conversational analysis.

    Workflow:
    1. Validate the uploaded file is a PDF.
    2. Check for duplicate (by SHA-256 content hash).
    3. Generate a UUID for the document.
    4. Upload the PDF to Supabase Storage.
    5. Create the database record.
    6. Index the PDF through LlamaIndex into pgvector.
    7. Return the document information.

    Only `file` is required. All metadata fields are optional.
    """
    if file is None:
        raise HTTPException(status_code=400, detail="No file was provided.")

    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

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
        return schema.DocumentUploadResponse(
            id=existing.id,
            url=existing.url,
            metadata_map=existing.metadata_map,
            status="indexed",
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )

    # Derive company_name from filename if not supplied
    original_filename = file.filename or "document.pdf"
    resolved_company_name = company_name or original_filename.replace(".pdf", "").replace("-", " ").replace("_", " ").title() or "Unknown Company"

    # Build NSE metadata
    nse_metadata = schema.NSEDocumentMetadata(
        company_name=resolved_company_name,
        company_symbol=company_symbol,
        document_type=document_type or schema.NSEDocumentTypeEnum.ANNUAL_REPORT,
        financial_year=financial_year,
        exchange=exchange or "NSE",
        original_filename=original_filename,
    )

    document_id = str(uuid_module.uuid4())
    logger.info("Document upload started: id=%s file=%s", document_id, original_filename)

    # Upload to Supabase Storage
    try:
        storage_path = upload_document(content, document_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload file to storage: {exc}",
        )

    # Build the public storage URL
    from app.storage.supabase import get_document_url
    storage_url = get_document_url(document_id)

    # Create database record
    doc_schema = schema.Document(
        id=uuid_module.UUID(document_id),
        url=storage_url,
        metadata_map={
            schema.DocumentMetadataKeysEnum.NSE_DOCUMENT: nse_metadata.model_dump(mode="json"),
            "content_hash": content_hash,
            "original_filename": original_filename,
        },
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

    # Index through LlamaIndex into pgvector
    try:
        vector_store = await get_vector_store_singleton()
        await ingest_document(db_doc, vector_store)
        logger.info("Indexing completed for document %s", document_id)
    except Exception as exc:
        logger.error("Indexing failed for document %s: %s", document_id, exc, exc_info=True)
        # Rollback: remove DB record and storage object
        await crud.delete_document_by_id(db, document_id)
        delete_document(document_id)
        raise HTTPException(
            status_code=422,
            detail=f"PDF indexing failed. The file may be corrupted or unreadable: {exc}",
        )

    return schema.DocumentUploadResponse(
        id=db_doc.id,
        url=db_doc.url,
        metadata_map=db_doc.metadata_map,
        status="indexed",
        created_at=db_doc.created_at,
        updated_at=db_doc.updated_at,
    )


@router.get("/")
async def get_documents(
    document_ids: Optional[List[UUID]] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> List[schema.Document]:
    """
    Get all documents or documents filtered by their IDs.
    """
    if document_ids is None:
        docs = await crud.fetch_documents(db)
    else:
        docs = await crud.fetch_documents(db, ids=[str(d) for d in document_ids])

    if not docs:
        raise HTTPException(status_code=404, detail="Document(s) not found")

    return docs


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> schema.Document:
    """
    Get a single document by its ID.
    """
    docs = await crud.fetch_documents(db, id=str(document_id))
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found")

    return docs[0]
