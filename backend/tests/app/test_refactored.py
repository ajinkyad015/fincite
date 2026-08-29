import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from uuid import uuid4, UUID
from fastapi.exceptions import HTTPException
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app import schema
from app.api import crud
from app.storage import supabase
from app.ingestion import pdf
from app.api.endpoints.documents import upload_document_endpoint


# ---------------------------------------------------------------------------
# 1. Metadata tests
# ---------------------------------------------------------------------------
def test_nse_metadata_parsing():
    # Happy path: all fields provided
    data = {
        "company_name": "Reliance Industries Limited",
        "company_symbol": "RELIANCE",
        "document_type": "annual_report",
        "financial_year": "2025",
        "report_date": "2025-08-28T12:00:00",
        "exchange": "NSE",
        "original_filename": "reliance_report.pdf",
    }
    meta = schema.NSEDocumentMetadata.model_validate(data)
    assert meta.company_name == "Reliance Industries Limited"
    assert meta.company_symbol == "RELIANCE"
    assert meta.document_type == schema.NSEDocumentTypeEnum.ANNUAL_REPORT
    assert meta.financial_year == "2025"
    assert meta.report_date == datetime(2025, 8, 28, 12, 0)
    assert meta.exchange == "NSE"
    assert meta.original_filename == "reliance_report.pdf"


def test_nse_metadata_defaults_and_missing_optional():
    # Only company_name is required
    data = {
        "company_name": "TCS",
    }
    meta = schema.NSEDocumentMetadata.model_validate(data)
    assert meta.company_name == "TCS"
    assert meta.company_symbol is None
    assert meta.document_type == schema.NSEDocumentTypeEnum.ANNUAL_REPORT
    assert meta.financial_year is None
    assert meta.report_date is None
    assert meta.exchange == "NSE"
    assert meta.original_filename is None


# ---------------------------------------------------------------------------
# 2. Storage tests (Mocked)
# ---------------------------------------------------------------------------
@patch("app.storage.supabase.create_client")
def test_supabase_storage_helpers(mock_create_client):
    mock_client = MagicMock()
    mock_create_client.return_value = mock_client
    
    # Reset singleton just in case
    supabase._supabase_client = None
    
    with patch("app.storage.supabase.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://example.supabase.co"
        mock_settings.SUPABASE_SERVICE_ROLE_KEY = "dummy_key"
        mock_settings.SUPABASE_STORAGE_BUCKET = "annual-reports"
        
        # Test client creation
        client = supabase.get_supabase_client()
        assert client == mock_client
        mock_create_client.assert_called_once_with("https://example.supabase.co", "dummy_key")
        
        # Test upload
        mock_bucket = MagicMock()
        mock_client.storage.from_.return_value = mock_bucket
        
        doc_id = str(uuid4())
        supabase.upload_document(b"pdf data", doc_id)
        mock_client.storage.from_.assert_called_with("annual-reports")
        mock_bucket.upload.assert_called_once()
        
        # Test download
        mock_bucket.download.return_value = b"downloaded data"
        res = supabase.download_document(doc_id)
        assert res == b"downloaded data"
        mock_bucket.download.assert_called_with(f"documents/{doc_id}/original.pdf")
        
        # Test delete
        supabase.delete_document(doc_id)
        mock_bucket.remove.assert_called_with([f"documents/{doc_id}/original.pdf"])


# ---------------------------------------------------------------------------
# 3. PDF Ingestion tests (Mocked)
# ---------------------------------------------------------------------------
@patch("app.ingestion.pdf.download_document")
@patch("app.ingestion.pdf.PDFReader")
@patch("app.ingestion.pdf.VectorStoreIndex")
@patch("app.ingestion.pdf.StorageContext")
@pytest.mark.asyncio
async def test_pdf_ingestion_flow(mock_storage_context, mock_vector_index, mock_pdf_reader, mock_download):
    mock_download.return_value = b"pdf_data"
    
    mock_reader_instance = MagicMock()
    mock_pdf_reader.return_value = mock_reader_instance
    mock_reader_instance.load_data.return_value = [
        MagicMock(text="page 1 text", metadata={"page_label": "1"})
    ]
    
    mock_index_instance = MagicMock()
    mock_vector_index.from_documents.return_value = mock_index_instance
    
    doc_schema = schema.Document(
        id=uuid4(),
        url="http://supabase/pdf",
        metadata_map={}
    )
    
    vector_store = MagicMock()
    
    # Run ingestion
    index = await pdf.ingest_document(doc_schema, vector_store)
    
    assert index == mock_index_instance
    mock_download.assert_called_once_with(str(doc_schema.id))
    mock_reader_instance.load_data.assert_called_once()
    mock_vector_index.from_documents.assert_called_once()
    mock_index_instance.set_index_id.assert_called_once_with(str(doc_schema.id))


# ---------------------------------------------------------------------------
# 4. Upload Endpoint tests (Mocked)
# ---------------------------------------------------------------------------
@patch("app.api.endpoints.documents.upload_document")
@patch("app.api.endpoints.documents.get_document_url")
@patch("app.api.endpoints.documents.crud")
@patch("app.api.endpoints.documents.get_vector_store_singleton")
@patch("app.api.endpoints.documents.ingest_document")
@pytest.mark.asyncio
async def test_upload_document_endpoint_success(
    mock_ingest, mock_get_vector_store, mock_crud, mock_get_url, mock_upload
):
    mock_upload.return_value = "documents/some_uuid/original.pdf"
    mock_get_url.return_value = "https://example.supabase.co/bucket/documents/some_uuid/original.pdf"
    
    doc_id = uuid4()
    mock_db_doc = schema.Document(
        id=doc_id,
        url="https://example.supabase.co/bucket/documents/some_uuid/original.pdf",
        metadata_map={
            "nse_document": {
                "company_name": "TCS",
                "company_symbol": "TCS",
                "document_type": "annual_report",
                "financial_year": "2024",
                "exchange": "NSE",
            }
        }
    )
    mock_crud.fetch_document_by_content_hash = AsyncMock(return_value=None)
    mock_crud.create_document = AsyncMock(return_value=mock_db_doc)
    
    # Create mock UploadFile
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "tcs_report.pdf"
    mock_file.content_type = "application/pdf"
    # %PDF magic bytes
    mock_file.read.return_value = b"%PDF-1.4 mock pdf data"
    
    db_session = AsyncMock(spec=AsyncSession)
    
    response = await upload_document_endpoint(
        file=mock_file,
        company_name="TCS",
        company_symbol="TCS",
        financial_year="2024",
        document_type=schema.NSEDocumentTypeEnum.ANNUAL_REPORT,
        exchange="NSE",
        db=db_session
    )
    
    assert response.id == doc_id
    assert response.status == "indexed"
    assert response.url == mock_db_doc.url
    
    mock_upload.assert_called_once()
    mock_crud.create_document.assert_called_once()
    mock_ingest.assert_called_once_with(mock_db_doc, mock_get_vector_store.return_value)


@patch("app.api.endpoints.documents.crud")
@pytest.mark.asyncio
async def test_upload_document_endpoint_invalid_file(mock_crud):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "tcs_report.txt"
    mock_file.content_type = "text/plain"
    mock_file.read.return_value = b"not a pdf"
    
    db_session = AsyncMock(spec=AsyncSession)
    
    with pytest.raises(HTTPException) as excinfo:
        await upload_document_endpoint(
            file=mock_file,
            company_name="TCS",
            db=db_session
        )
    assert excinfo.value.status_code == 400
    assert "Only PDF files are accepted" in excinfo.value.detail


# ---------------------------------------------------------------------------
# 5. Health endpoint tests (Mocked)
# ---------------------------------------------------------------------------
from app.api.endpoints.health import health

@pytest.mark.asyncio
async def test_health_endpoint():
    db_session = AsyncMock(spec=AsyncSession)
    res = await health(db=db_session)
    assert res == {"status": "alive"}
    db_session.execute.assert_called_once()

