"""
Background ingestion.

Uploading a PDF must not block an HTTP worker for minutes, so the upload
endpoint stores the file + a `document` row with ``status="uploaded"`` and
schedules this job. The job advances the document through

    uploaded → parsing → chunking → embedding → indexing → ready

writing progress to the row as it goes; the library UI polls
``GET /api/document/{id}`` for it.

Design constraints (see docs/plans/connect-and-deploy.md §M1.4):

* **One ingestion at a time.** The configured embedding endpoint is
  rate-limited and parsing is memory hungry; a semaphore keeps concurrent
  uploads from starving each other.
* **Own DB session.** The job outlives the request, so it never borrows the
  request-scoped session.
* **No new infrastructure.** This is deliberately a process-local task. When
  horizontal scaling needs real durability, swap the scheduler for a queue
  behind the same `schedule_ingestion` interface (decision record 0002).
"""
import asyncio
import logging
from typing import Dict, Optional

from app.api import crud
from app.chat.pg_vector import get_vector_store_singleton
from app.db.session import SessionLocal
from app.ingestion.pdf import index_documents, load_pdf_from_bytes
from app.models.db import DocumentStatusEnum
from app.storage.supabase import download_document

logger = logging.getLogger(__name__)

# In-flight tasks, keyed by document id (prevents duplicate work on re-upload).
_TASKS: Dict[str, "asyncio.Task[None]"] = {}

# Parsing + embedding are heavy; serialise them.
_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(1)
    return _SEMAPHORE


def is_running(document_id: str) -> bool:
    task = _TASKS.get(document_id)
    return task is not None and not task.done()


def schedule_ingestion(document_id: str) -> bool:
    """
    Queue a document for background indexing.

    Returns False when a job for this document is already running (the caller
    should treat that as "nothing to do", not as an error).
    """
    if is_running(document_id):
        logger.info("Ingestion already running for document %s — skipping", document_id)
        return False

    task = asyncio.create_task(run_ingestion(document_id), name=f"ingest:{document_id}")
    _TASKS[document_id] = task
    task.add_done_callback(lambda _t, doc_id=document_id: _TASKS.pop(doc_id, None))
    return True


async def run_ingestion(document_id: str) -> None:
    """
    Ingest one document end to end, recording status/progress as it advances.

    Never raises: failures are recorded on the row (`status="failed"`, `error`)
    because there is no HTTP caller left to receive an exception.
    """
    async with _semaphore():
        try:
            async with SessionLocal() as db:
                await _ingest(db, document_id)
        except Exception as exc:  # noqa: BLE001 — job boundary, always record
            logger.error(
                "Ingestion failed for document %s: %s", document_id, exc, exc_info=True
            )
            await _mark_failed(document_id, exc)


async def _mark_failed(document_id: str, exc: BaseException) -> None:
    message = str(exc).strip() or exc.__class__.__name__
    try:
        async with SessionLocal() as db:
            await crud.update_document_status(
                db,
                document_id,
                DocumentStatusEnum.failed,
                error=message[:2000],
            )
    except Exception:  # noqa: BLE001 — nothing left to do but log
        logger.exception("Could not record failure for document %s", document_id)


async def _set_status(
    db,
    document_id: str,
    status: DocumentStatusEnum,
    progress: int,
    **kwargs,
) -> None:
    logger.info(
        "Document %s → %s (%d%%)", document_id, status.value, progress
    )
    await crud.update_document_status(
        db, document_id, status, progress=progress, **kwargs
    )


async def _ingest(db, document_id: str) -> None:
    document = await crud.fetch_document(db, document_id)
    if document is None:
        logger.warning("Document %s no longer exists — aborting ingestion", document_id)
        return

    # 1. Fetch the original PDF from storage
    await _set_status(db, document_id, DocumentStatusEnum.parsing, 5)
    pdf_bytes = await asyncio.to_thread(download_document, document_id)
    await crud.update_document_status(
        db, document_id, DocumentStatusEnum.parsing, progress=15, file_size=len(pdf_bytes)
    )

    # 2. Parse to page-labelled LlamaIndex documents
    llama_docs = await asyncio.to_thread(
        load_pdf_from_bytes, pdf_bytes, document_id
    )
    page_count = len(llama_docs) or None

    # 3. Chunk + embed + upsert (the long, blocking part)
    await _set_status(
        db, document_id, DocumentStatusEnum.embedding, 40, page_count=page_count
    )
    vector_store = await get_vector_store_singleton()
    await _set_status(db, document_id, DocumentStatusEnum.indexing, 80)
    await asyncio.to_thread(index_documents, document_id, llama_docs, vector_store)

    # 4. Done
    await _set_status(
        db,
        document_id,
        DocumentStatusEnum.ready,
        100,
        page_count=page_count,
        file_size=len(pdf_bytes),
    )
    logger.info("Document %s indexed (%d pages)", document_id, page_count or 0)


async def delete_document_vectors(document_id: str) -> None:
    """
    Remove every vector row for a document.

    pgvector rows are not covered by the relational FK cascade, so deleting a
    filing has to clear them explicitly or retrieval keeps answering from a
    document the user can no longer see.
    """
    import re

    from sqlalchemy import text

    vector_store = await get_vector_store_singleton()
    table_name = getattr(vector_store, "table_name", None)
    schema_name = getattr(vector_store, "schema_name", None) or "public"
    for identifier in (table_name, schema_name):
        if not identifier or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
            raise RuntimeError(
                "Cannot determine a safe vector table name; refusing to delete a "
                "document without clearing its vectors."
            )

    async with SessionLocal() as db:
        await db.execute(
            text(
                f'DELETE FROM "{schema_name}"."{table_name}" '
                f"WHERE metadata_->>'db_document_id' = :doc_id"
            ),
            {"doc_id": document_id},
        )
        await db.commit()
    logger.info("Deleted vectors for document %s", document_id)


def reset() -> None:
    """Test helper: forget in-flight tasks and the semaphore."""
    global _SEMAPHORE
    _TASKS.clear()
    _SEMAPHORE = None
