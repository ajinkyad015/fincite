"""
PDF ingestion pipeline.

Flow:
    Supabase Storage PDF
          ↓
    temporary local file
          ↓
    PDFReader (LlamaIndex)
          ↓
    LlamaIndex Document nodes
    (each node carries DB_DOC_ID_KEY + page metadata)
          ↓
    VectorStoreIndex.from_documents()
          ↓
    Supabase PostgreSQL + pgvector
"""
import asyncio
import logging
import tempfile
import os
from pathlib import Path
from typing import List

from llama_index.readers.file.docs.base import PDFReader
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.schema import Document as LlamaIndexDocument
from llama_index.core.vector_stores.types import VectorStore
from llama_index.core.callbacks.base import CallbackManager

from app.chat.constants import DB_DOC_ID_KEY
from app import schema
from app.storage.supabase import download_document

logger = logging.getLogger(__name__)


def load_pdf_from_bytes(
    pdf_bytes: bytes,
    document_id: str,
) -> List[LlamaIndexDocument]:
    """
    Write pdf_bytes to a temporary file, parse with PDFReader, then return
    LlamaIndex Documents with DB_DOC_ID_KEY injected into each document's
    extra_info so page-level citations work downstream.

    The temporary file is deleted after parsing.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"{document_id}.pdf"
        tmp_path.write_bytes(pdf_bytes)
        logger.info(
            "Parsing PDF for document %s (%d bytes) from %s",
            document_id,
            len(pdf_bytes),
            tmp_path,
        )
        reader = PDFReader()
        docs = reader.load_data(
            tmp_path,
            extra_info={DB_DOC_ID_KEY: document_id},
        )
        logger.info(
            "PDF parsing complete for document %s — %d LlamaIndex documents produced",
            document_id,
            len(docs),
        )
        return docs


async def ingest_document(
    document: schema.Document,
    vector_store: VectorStore,
    callback_manager: CallbackManager | None = None,
) -> VectorStoreIndex:
    """
    Download a PDF from Supabase Storage, parse it, and index it into
    the pgvector vector store.

    Each indexed node carries DB_DOC_ID_KEY so retrieval can be filtered
    to a specific document.

    Returns the created VectorStoreIndex (mainly useful for testing).
    Raises RuntimeError if download or indexing fails.
    """
    document_id = str(document.id)
    logger.info("Starting ingestion for document %s", document_id)

    # 1. Download PDF bytes from Supabase Storage (sync SDK — offload to thread)
    pdf_bytes = await asyncio.to_thread(download_document, document_id)

    # 2. Parse PDF into LlamaIndex documents (sync file I/O — offload to thread)
    logger.info("PDF parsing started for document %s", document_id)
    llama_docs = await asyncio.to_thread(load_pdf_from_bytes, pdf_bytes, document_id)

    if not llama_docs:
        raise ValueError(
            f"PDFReader produced no documents for document_id={document_id}. "
            "The file may be empty or unreadable."
        )

    # 3. Build storage context backed by pgvector
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # 4. Index — this calls Gemini embeddings and writes to pgvector.
    #    VectorStoreIndex.from_documents has a synchronous code path; run in a
    #    thread so embedding API calls don’t block the event loop.
    logger.info("Document indexing started for document %s", document_id)
    km = {"callback_manager": callback_manager} if callback_manager else {}

    def _build_index() -> VectorStoreIndex:
        return VectorStoreIndex.from_documents(
            llama_docs,
            storage_context=storage_context,
            show_progress=True,
            **km,
        )

    index = await asyncio.to_thread(_build_index)
    index.set_index_id(document_id)
    logger.info("Document indexing completed for document %s", document_id)

    return index
