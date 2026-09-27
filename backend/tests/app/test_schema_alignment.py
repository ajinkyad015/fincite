"""
Tests for the frontend-backend model alignment changes.

Covers:
  1. FinDocumentSchema.from_db_document — promoted columns path
  2. FinDocumentSchema.from_db_document — metadata_map fallback (legacy rows)
  3. MessageSubProcess.name auto-derivation from source
  4. ConversationCreate — title + document_scope alias
  5. MessageSource round-trip
  6. DocumentUploadResponse wraps FinDocumentSchema
  7. FinDocumentSchema.from_db_document — filename fallback from url
"""
import pytest
from datetime import datetime
from uuid import uuid4, UUID

from app import schema
from app.schema import (
    FinDocumentSchema,
    FinDocumentMetadata,
    DocumentUploadResponse,
    MessageSource,
    MessageSubProcess,
    ConversationCreate,
    DocumentMetadataKeysEnum,
)
from app.models.db import (
    MessageSubProcessStatusEnum,
    MessageSubProcessSourceEnum,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_legacy_document(**kwargs):
    """Return a schema.Document built like a legacy row (no promoted columns)."""
    defaults = dict(
        id=uuid4(),
        url="https://storage.example.com/documents/abc/original.pdf",
        created_at=datetime(2024, 3, 1),
        updated_at=datetime(2024, 3, 1),
    )
    return schema.Document(**{**defaults, **kwargs})


def _make_promoted_document(**kwargs):
    """Return a schema.Document with promoted columns fully populated."""
    defaults = dict(
        id=uuid4(),
        url="https://storage.example.com/documents/abc/original.pdf",
        filename="reliance-ar-fy24.pdf",
        status="ready",
        progress=100,
        company_name="Reliance Industries Ltd",
        company_symbol="RELIANCE",
        exchange="NSE",
        document_type="annual_report",
        financial_year="2024",
        language="en",
        pages=386,
        file_size=24_000_000,
        created_at=datetime(2024, 4, 1),
        updated_at=datetime(2024, 4, 1),
    )
    return schema.Document(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# 1. FinDocumentSchema.from_db_document — promoted columns path
# ---------------------------------------------------------------------------

def test_fin_document_from_promoted_columns():
    doc = _make_promoted_document()
    fin = FinDocumentSchema.from_db_document(doc)

    assert str(fin.id) == str(doc.id)
    assert fin.filename == "reliance-ar-fy24.pdf"
    assert fin.status == "ready"
    assert fin.progress == 100
    assert fin.metadata.company_name == "Reliance Industries Ltd"
    assert fin.metadata.nse_symbol == "RELIANCE"
    assert fin.metadata.document_type == "annual_report"
    assert fin.metadata.fiscal_year == "2024"
    assert fin.metadata.pages == 386
    assert fin.metadata.file_size == 24_000_000
    assert fin.metadata.language == "en"
    assert fin.uploaded_at == datetime(2024, 4, 1)
    assert fin.url == doc.url


# ---------------------------------------------------------------------------
# 2. FinDocumentSchema.from_db_document — metadata_map fallback (legacy rows)
# ---------------------------------------------------------------------------

def test_fin_document_from_metadata_map_fallback():
    """Legacy rows have no promoted columns — should fall back to metadata_map."""
    doc = _make_legacy_document(
        metadata_map={
            DocumentMetadataKeysEnum.NSE_DOCUMENT: {
                "company_name": "TCS",
                "company_symbol": "TCS",
                "document_type": "annual_report",
                "financial_year": "2023",
                "exchange": "NSE",
                "original_filename": "tcs-annual-report-fy23.pdf",
            }
        }
    )
    fin = FinDocumentSchema.from_db_document(doc)

    assert fin.filename == "tcs-annual-report-fy23.pdf"
    assert fin.status == "ready"   # default
    assert fin.progress == 100     # default
    assert fin.metadata.company_name == "TCS"
    assert fin.metadata.nse_symbol == "TCS"
    assert fin.metadata.document_type == "annual_report"
    assert fin.metadata.fiscal_year == "2023"


def test_fin_document_fallback_no_metadata():
    """Rows with no metadata_map and no promoted columns get safe defaults."""
    doc = _make_legacy_document(metadata_map=None)
    fin = FinDocumentSchema.from_db_document(doc)

    # filename derived from url
    assert fin.filename == "original.pdf"
    assert fin.status == "ready"
    assert fin.metadata.company_name == ""


# ---------------------------------------------------------------------------
# 3. Filename fallback from url
# ---------------------------------------------------------------------------

def test_fin_document_filename_from_url():
    doc = _make_legacy_document(
        url="https://storage.example.com/documents/xyz/my-report.pdf",
        metadata_map={},
    )
    fin = FinDocumentSchema.from_db_document(doc)
    assert fin.filename == "my-report.pdf"


# ---------------------------------------------------------------------------
# 4. MessageSubProcess.name auto-derivation from source
# ---------------------------------------------------------------------------

def test_message_subprocess_name_auto_derived():
    """name should be auto-populated from source if not explicitly set."""
    sp = MessageSubProcess(
        id=uuid4(),
        message_id=uuid4(),
        source=MessageSubProcessSourceEnum["LLM"],
        status=MessageSubProcessStatusEnum.FINISHED,
    )
    assert sp.name == "LLM reasoning"


def test_message_subprocess_name_retrieve():
    sp = MessageSubProcess(
        id=uuid4(),
        message_id=uuid4(),
        source=MessageSubProcessSourceEnum["RETRIEVE"],
        status=MessageSubProcessStatusEnum.PENDING,
    )
    assert sp.name == "Retrieval"


def test_message_subprocess_name_synthesize():
    sp = MessageSubProcess(
        id=uuid4(),
        message_id=uuid4(),
        source=MessageSubProcessSourceEnum["SYNTHESIZE"],
        status=MessageSubProcessStatusEnum.FINISHED,
    )
    assert sp.name == "Answer synthesis"


# ---------------------------------------------------------------------------
# 5. ConversationCreate — title + document_scope alias
# ---------------------------------------------------------------------------

def test_conversation_create_document_scope():
    doc_id = uuid4()
    payload = ConversationCreate(title="My Chat", document_scope=[doc_id])
    assert payload.title == "My Chat"
    assert payload.document_scope == [doc_id]


def test_conversation_create_document_ids_alias():
    """Legacy document_ids should be unified into document_scope."""
    doc_id = uuid4()
    payload = ConversationCreate(document_ids=[doc_id])
    assert payload.document_scope == [doc_id]


def test_conversation_create_no_title_no_docs():
    payload = ConversationCreate()
    assert payload.title is None
    assert payload.document_scope == []


def test_conversation_create_document_scope_takes_precedence():
    """When both document_scope and document_ids are given, document_scope wins."""
    id1, id2 = uuid4(), uuid4()
    payload = ConversationCreate(document_scope=[id1], document_ids=[id2])
    assert id1 in payload.document_scope


# ---------------------------------------------------------------------------
# 6. MessageSource round-trip
# ---------------------------------------------------------------------------

def test_message_source_schema():
    msg_id = uuid4()
    doc_id = uuid4()
    src = MessageSource(
        id=uuid4(),
        message_id=str(msg_id),
        document_id=str(doc_id),
        index=1,
        page=42,
        excerpt="Revenue grew by 12% year-on-year.",
        score=0.92,
        created_at=datetime(2024, 5, 1),
    )
    assert src.index == 1
    assert src.page == 42
    assert src.score == 0.92
    assert "Revenue" in src.excerpt


# ---------------------------------------------------------------------------
# 7. DocumentUploadResponse wraps FinDocumentSchema
# ---------------------------------------------------------------------------

def test_document_upload_response_wraps_fin_document():
    fin_doc = FinDocumentSchema(
        id=uuid4(),
        filename="test.pdf",
        status="ready",
        progress=100,
        metadata=FinDocumentMetadata(company_name="Test Co"),
        uploaded_at=datetime(2024, 1, 1),
    )
    resp = DocumentUploadResponse(document=fin_doc)
    assert resp.document.filename == "test.pdf"
    assert resp.document.metadata.company_name == "Test Co"
    # Ensure it serializes to JSON with 'document' key
    data = resp.model_dump()
    assert "document" in data
    assert data["document"]["filename"] == "test.pdf"
