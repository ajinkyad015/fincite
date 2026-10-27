"""
Contract tests for the frontend↔backend integration work (M1).

These cover the promises the UI now builds on:

* a thread can be created without documents and scoped later;
* an empty library returns `[]`, not a 404;
* uploads are asynchronous — 202 + a scheduled job;
* deleting a filing clears vectors before anything else;
* the SSE stream yields monotonic `Message` snapshots, persists partial text,
  exposes citations on the message, and always ends in SUCCESS or ERROR;
* `handle_chat_message` never closes the channel it was handed.

No database, no NVIDIA API, no network: everything external is mocked.
"""
import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import anyio
import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

from app import schema
from app.api.endpoints import conversation as conversation_module
from app.api.endpoints import documents as documents_module
from app.chat import messaging
from app.models.db import (
    DocumentStatusEnum,
    MessageRoleEnum,
    MessageStatusEnum,
    MessageSubProcessSourceEnum,
    MessageSubProcessStatusEnum,
)


# ---------------------------------------------------------------------------
# Schema-level promises
# ---------------------------------------------------------------------------


def test_conversation_can_be_created_without_documents():
    """The UI's "New chat" flow creates an empty thread, then scopes it."""
    payload = schema.ConversationCreate()
    assert payload.document_ids == []
    assert payload.title is None


def test_conversation_title_and_documents_are_accepted():
    doc_id = uuid4()
    payload = schema.ConversationCreate(document_ids=[doc_id], title="Margin check")
    assert payload.document_ids == [doc_id]
    assert payload.title == "Margin check"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-25", "FY2024-25"),
        ("FY2024-2025", "FY2024-25"),
        ("fy 24-25", "FY2024-25"),
        ("2025", "FY2024-25"),
        ("", None),
        (None, None),
        ("Mar-2023", "Mar-2023"),
    ],
)
def test_fiscal_year_normalisation(raw, expected):
    assert schema.normalise_fiscal_year(raw) == expected


def test_document_upload_defaults_to_uploaded_not_ready():
    """A row that exists but has not been indexed must not claim to be ready."""
    doc = schema.Document(url="https://example.test/doc.pdf")
    assert doc.status == DocumentStatusEnum.uploaded
    assert doc.progress == 0


def test_document_exposes_nse_metadata_conveniences():
    doc = schema.Document(
        url="https://example.test/doc.pdf",
        metadata_map={
            "nse_document": {
                "company_name": "Reliance Industries",
                "company_symbol": "RELIANCE",
                "document_type": "annual_report",
                "financial_year": "2024-25",
                "exchange": "NSE",
            },
            "original_filename": "reliance.pdf",
        },
    )
    assert doc.company_name == "Reliance Industries"
    assert doc.company_symbol == "RELIANCE"
    assert doc.fiscal_year == "FY2024-25"
    assert doc.original_filename == "reliance.pdf"


# ---------------------------------------------------------------------------
# Citations → sources
# ---------------------------------------------------------------------------


def _citation(doc_id: UUID, page: int, text: str, score: float = 0.9) -> schema.Citation:
    return schema.Citation(document_id=doc_id, text=text, page_number=page, score=score)


def test_citations_to_sources_is_ordered_and_deduplicated():
    doc_id = uuid4()
    sources = schema.citations_to_sources(
        [
            _citation(doc_id, 41, "Revenue from operations"),
            _citation(doc_id, 41, "Revenue from operations"),  # duplicate
            _citation(doc_id, 88, "Segment information"),
        ]
    )
    assert [s.index for s in sources] == [1, 2]
    assert [s.page for s in sources] == [41, 88]
    assert sources[0].excerpt == "Revenue from operations"


def test_citations_from_sub_processes_reads_sub_question_metadata():
    doc_id = uuid4()
    trail = [
        schema.MessageSubProcess(
            message_id=uuid4(),
            source=MessageSubProcessSourceEnum.CONSTRUCTED_QUERY_ENGINE,
            status=MessageSubProcessStatusEnum.FINISHED,
            metadata_map=None,
        ),
        schema.MessageSubProcess(
            message_id=uuid4(),
            source=MessageSubProcessSourceEnum.SUB_QUESTION,
            status=MessageSubProcessStatusEnum.FINISHED,
            metadata_map={
                "sub_question": {
                    "question": "What was FY24 revenue?",
                    "answer": "₹9.0 lakh crore",
                    "citations": [
                        {
                            "document_id": str(doc_id),
                            "text": "Revenue from operations 9,00,000",
                            "page_number": 41,
                            "score": 0.87,
                        },
                        {"document_id": "not-a-uuid"},  # malformed → skipped
                    ],
                }
            },
        ),
    ]

    citations = messaging.citations_from_sub_processes(trail)

    assert len(citations) == 1
    assert citations[0].page_number == 41
    assert str(citations[0].document_id) == str(doc_id)
    # …and they flatten onto the message for the UI's source chips.
    sources = schema.citations_to_sources(citations)
    assert sources[0].index == 1
    assert sources[0].page == 41


def test_describe_sub_process_prefers_the_sub_question():
    label = messaging.describe_sub_process(
        MessageSubProcessSourceEnum.SUB_QUESTION,
        {"sub_question": {"question": "  What   drove   margin   expansion?  "}},
    )
    assert label == "What drove margin expansion?"


def test_describe_sub_process_truncates_and_falls_back():
    long_question = "x" * 400
    label = messaging.describe_sub_process(
        MessageSubProcessSourceEnum.SUB_QUESTION,
        {"sub_question": {"question": long_question}},
    )
    assert len(label) <= 140
    assert label.endswith("…")

    assert (
        messaging.describe_sub_process(MessageSubProcessSourceEnum.RETRIEVE)
        == "Retrieving passages"
    )


# ---------------------------------------------------------------------------
# Document endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_library_returns_an_empty_list():
    db = AsyncMock(spec=AsyncSession)
    with patch.object(documents_module.crud, "fetch_documents", AsyncMock(return_value=[])):
        result = await documents_module.get_documents(
            document_ids=None, status=None, q=None, limit=None, offset=None, db=db
        )
    assert result == []


@pytest.mark.asyncio
async def test_missing_document_is_404():
    db = AsyncMock(spec=AsyncSession)
    with patch.object(documents_module.crud, "fetch_document", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as excinfo:
            await documents_module.get_document(document_id=uuid4(), db=db)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_clears_vectors_before_rows():
    db = AsyncMock(spec=AsyncSession)
    document = schema.Document(id=uuid4(), url="https://example.test/doc.pdf")

    with patch.object(
        documents_module.crud, "fetch_document", AsyncMock(return_value=document)
    ), patch.object(
        documents_module.jobs, "delete_document_vectors", AsyncMock()
    ) as delete_vectors, patch.object(
        documents_module, "delete_document"
    ) as delete_stored, patch.object(
        documents_module.crud, "delete_document_by_id", AsyncMock(return_value=True)
    ) as delete_row:
        await documents_module.delete_document_endpoint(document_id=document.id, db=db)

    delete_vectors.assert_awaited_once_with(str(document.id))
    delete_stored.assert_called_once_with(str(document.id))
    delete_row.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_document_aborts_when_vectors_cannot_be_cleared():
    """A document that is gone from the library but still retrievable is worse
    than a failed delete, so nothing else is touched."""
    db = AsyncMock(spec=AsyncSession)
    document = schema.Document(id=uuid4(), url="https://example.test/doc.pdf")

    with patch.object(
        documents_module.crud, "fetch_document", AsyncMock(return_value=document)
    ), patch.object(
        documents_module.jobs,
        "delete_document_vectors",
        AsyncMock(side_effect=RuntimeError("vector store down")),
    ), patch.object(documents_module, "delete_document") as delete_stored, patch.object(
        documents_module.crud, "delete_document_by_id", AsyncMock()
    ) as delete_row:
        with pytest.raises(HTTPException) as excinfo:
            await documents_module.delete_document_endpoint(document_id=document.id, db=db)

    assert excinfo.value.status_code == 503
    delete_stored.assert_not_called()
    delete_row.assert_not_called()


@pytest.mark.asyncio
async def test_reindex_conflicts_while_a_job_is_running():
    db = AsyncMock(spec=AsyncSession)
    document = schema.Document(id=uuid4(), url="https://example.test/doc.pdf")

    with patch.object(
        documents_module.crud, "fetch_document", AsyncMock(return_value=document)
    ), patch.object(documents_module.jobs, "is_running", return_value=True):
        with pytest.raises(HTTPException) as excinfo:
            await documents_module.reindex_document(document_id=document.id, db=db)

    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_upload_rejects_oversized_files(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    mock_file = AsyncMock()
    mock_file.filename = "big.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read.return_value = b"%PDF" + b"0" * (2 * 1024 * 1024)

    with pytest.raises(HTTPException) as excinfo:
        await documents_module.upload_document_endpoint(
            response=Response(),
            file=mock_file,
            company_name=None,
            company_symbol=None,
            financial_year=None,
            document_type=schema.NSEDocumentTypeEnum.ANNUAL_REPORT,
            exchange="NSE",
            db=AsyncMock(spec=AsyncSession),
        )
    assert excinfo.value.status_code == 413


@pytest.mark.asyncio
async def test_duplicate_upload_returns_existing_document_without_reindexing():
    existing = schema.Document(
        id=uuid4(),
        url="https://example.test/doc.pdf",
        status=DocumentStatusEnum.ready,
        progress=100,
    )
    mock_file = AsyncMock()
    mock_file.filename = "reliance.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read.return_value = b"%PDF-1.4 duplicate"

    http_response = Response()
    with patch.object(
        documents_module.crud, "fetch_document_by_content_hash", AsyncMock(return_value=existing)
    ), patch.object(documents_module, "upload_document") as upload, patch.object(
        documents_module.jobs, "schedule_ingestion"
    ) as schedule:
        response = await documents_module.upload_document_endpoint(
            response=http_response,
            file=mock_file,
            company_name=None,
            company_symbol=None,
            financial_year=None,
            document_type=schema.NSEDocumentTypeEnum.ANNUAL_REPORT,
            exchange="NSE",
            db=AsyncMock(spec=AsyncSession),
        )

    assert response.id == existing.id
    assert response.status == DocumentStatusEnum.ready
    assert http_response.status_code == 200  # not 202: nothing was scheduled
    upload.assert_not_called()
    schedule.assert_not_called()


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def _assistant_snapshot(conversation_id: UUID) -> schema.Message:
    return schema.Message(
        id=uuid4(),
        conversation_id=conversation_id,
        content="done",
        role=MessageRoleEnum.assistant,
        status=MessageStatusEnum.SUCCESS,
        sub_processes=[],
        sources=[],
        created_at=datetime.datetime.utcnow(),
    )


class _SessionCtx:
    """Stand-in for `async with SessionLocal() as db`."""

    def __init__(self):
        self.db = AsyncMock(spec=AsyncSession)

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_answer_stream_persists_partial_text_and_yields_monotonic_snapshots():
    conversation_id = uuid4()
    conversation = schema.Conversation(
        id=conversation_id, title=None, documents=[], messages=[]
    )
    doc_id = uuid4()

    async def fake_handle(conv, user_message, send_chan, callback_handler=None):
        """Emulates the engine: a trail event, then token-by-token content."""
        await send_chan.send(
            messaging.StreamedMessageSubProcess(
                event_id="engine",
                has_ended=True,
                source=MessageSubProcessSourceEnum.CONSTRUCTED_QUERY_ENGINE,
            )
        )
        await send_chan.send(
            messaging.StreamedMessageSubProcess(
                event_id="sq-1",
                has_ended=False,
                source=MessageSubProcessSourceEnum.SUB_QUESTION,
                metadata_map={"sub_question": {"question": "What was FY24 revenue?"}},
            )
        )
        # The wire contract is *cumulative* content, not deltas.
        content = ""
        tokens = ["Reliance ", "FY24 ", "revenue ", "was ₹9.0 lakh crore [1]. "] + [
            "Segment detail. " * 3
        ] * 5
        for token in tokens:
            content += token
            await send_chan.send(messaging.StreamedMessage(content=content))
        await send_chan.send(
            messaging.StreamedMessageSubProcess(
                event_id="sq-1",
                has_ended=True,
                source=MessageSubProcessSourceEnum.SUB_QUESTION,
                metadata_map={
                    "sub_question": {
                        "question": "What was FY24 revenue?",
                        "answer": "₹9.0 lakh crore",
                        "citations": [
                            {
                                "document_id": str(doc_id),
                                "text": "Revenue from operations 9,00,000",
                                "page_number": 41,
                                "score": 0.91,
                            }
                        ],
                    }
                },
            )
        )
        # NOTE: deliberately does not close the channel — the endpoint owns it.

    assistant_row = MagicMock()
    assistant_row.id = uuid4()
    assistant_row.created_at = datetime.datetime.utcnow()

    crud_mock = MagicMock()
    crud_mock.create_message = AsyncMock(
        side_effect=[
            MagicMock(id=uuid4(), created_at=datetime.datetime.utcnow()),
            assistant_row,
        ]
    )
    crud_mock.touch_conversation = AsyncMock()
    crud_mock.update_message_content = AsyncMock()
    crud_mock.finalise_message = AsyncMock()
    crud_mock.fetch_message_with_sub_processes = AsyncMock(
        return_value=_assistant_snapshot(conversation_id)
    )

    with patch.object(conversation_module, "SessionLocal", _SessionCtx), patch.object(
        conversation_module, "crud", crud_mock
    ), patch.object(conversation_module, "handle_chat_message", fake_handle):
        snapshots = [
            message
            async for message in conversation_module._answer_stream(
                conversation, "What was FY24 revenue?"
            )
        ]

    # The last frame is the persisted message, with a terminal status.
    assert snapshots[-1].status == MessageStatusEnum.SUCCESS
    assert snapshots[-1].content == "done"

    pending = [s for s in snapshots if s.status == MessageStatusEnum.PENDING]
    assert pending, "the client should see progress before the terminal frame"

    # Every streamed frame is a full snapshot and content only ever grows.
    pending_contents = [p.content for p in pending]
    for previous, current in zip(pending_contents, pending_contents[1:]):
        assert current.startswith(previous) and len(current) >= len(previous)
    assert all(
        p.conversation_id == conversation_id and p.role == MessageRoleEnum.assistant
        for p in pending
    )

    # Trail steps are labelled and finished once their end event arrives.
    finished = [
        step
        for snapshot in pending
        for step in snapshot.sub_processes
        if step.status == MessageSubProcessStatusEnum.FINISHED
    ]
    assert any(step.name == "What was FY24 revenue?" for step in finished)
    assert any(step.duration_ms is not None for step in finished)

    # Citations are lifted onto the message, not buried in metadata.
    with_sources = [p for p in pending if p.sources]
    assert with_sources, "citations should appear on the message itself"
    assert with_sources[-1].sources[0].page == 41

    # Partial text is flushed mid-stream, and the final state is committed.
    crud_mock.update_message_content.assert_awaited()
    finalise_args = crud_mock.finalise_message.await_args
    assert finalise_args.args[3] == MessageStatusEnum.SUCCESS
    assert finalise_args.kwargs["sources"], "final row must carry sources"
    assert str(assistant_row.id) in finalise_args.args[:2]


@pytest.mark.asyncio
async def test_answer_stream_marks_the_message_failed_when_the_engine_raises():
    conversation_id = uuid4()
    conversation = schema.Conversation(id=conversation_id, title=None, documents=[], messages=[])

    async def exploding_handle(conv, user_message, send_chan, callback_handler=None):
        raise RuntimeError("llm exploded")

    crud_mock = MagicMock()
    crud_mock.create_message = AsyncMock(
        side_effect=[
            MagicMock(id=uuid4(), created_at=datetime.datetime.utcnow()),
            MagicMock(id=uuid4(), created_at=datetime.datetime.utcnow()),
        ]
    )
    crud_mock.touch_conversation = AsyncMock()
    crud_mock.update_message_content = AsyncMock()
    crud_mock.finalise_message = AsyncMock()
    crud_mock.fetch_message_with_sub_processes = AsyncMock(return_value=None)

    with patch.object(conversation_module, "SessionLocal", _SessionCtx), patch.object(
        conversation_module, "crud", crud_mock
    ), patch.object(conversation_module, "handle_chat_message", exploding_handle):
        snapshots = [
            message
            async for message in conversation_module._answer_stream(conversation, "hello?")
        ]

    # Nothing was yielded mid-stream (the producer died before any event), but the
    # failure is still recorded instead of leaving the row stuck in PENDING.
    assert snapshots == []
    finalise_args = crud_mock.finalise_message.await_args
    assert finalise_args.args[3] == MessageStatusEnum.ERROR


@pytest.mark.asyncio
async def test_handle_chat_message_does_not_close_the_callers_channel():
    """Regression for the double-`async with send_chan` bug (AGENTS.md §14.D)."""
    send_chan, recv_chan = anyio.create_memory_object_stream(10)
    conversation = schema.Conversation(id=uuid4(), title="t", documents=[], messages=[])

    class FakeResponse:
        async def async_response_gen(self):
            for token in ["₹1 ", "crore"]:
                yield token

    class FakeEngine:
        async def astream_chat(self, message):
            return FakeResponse()

    async def fake_get_chat_engine(handler, conv):
        return FakeEngine()

    with patch.object(messaging, "get_chat_engine", fake_get_chat_engine):
        await messaging.handle_chat_message(
            conversation, schema.MessageCreate(content="q"), send_chan
        )

    # The caller can still use the channel: it must not have been closed.
    await send_chan.send(messaging.StreamedMessage(content="sentinel"))
    items = []
    async for item in recv_chan:
        items.append(item)
        if isinstance(item, messaging.StreamedMessage) and item.content == "sentinel":
            break

    assert any(
        isinstance(item, messaging.StreamedMessage) and item.content == "₹1 crore"
        for item in items
    )
    await send_chan.aclose()


@pytest.mark.asyncio
async def test_streaming_requires_a_non_empty_question():
    with pytest.raises(HTTPException) as excinfo:
        await conversation_module._stream_response(uuid4(), "   ")
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_thread_without_scope_falls_back_to_all_ready_documents():
    """Empty scope = "all filings" (what the UI implies); no indexed documents is a 409."""
    db = AsyncMock(spec=AsyncSession)
    conversation = schema.Conversation(id=uuid4(), title=None, documents=[], messages=[])
    ready = [schema.Document(id=uuid4(), url="https://example.test/a.pdf", status=DocumentStatusEnum.ready)]

    with patch.object(
        conversation_module.crud, "fetch_documents", AsyncMock(return_value=ready)
    ):
        resolved = await conversation_module._resolve_scope(db, conversation)
    assert resolved.documents == ready

    # `_resolve_scope` caches the resolved scope on the conversation object, so
    # the "nothing indexed" case needs a fresh thread.
    empty_thread = schema.Conversation(id=uuid4(), title=None, documents=[], messages=[])
    with patch.object(
        conversation_module.crud, "fetch_documents", AsyncMock(return_value=[])
    ):
        with pytest.raises(HTTPException) as excinfo:
            await conversation_module._resolve_scope(db, empty_thread)
    assert excinfo.value.status_code == 409
