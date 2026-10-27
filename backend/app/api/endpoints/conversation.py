"""
Conversation endpoints.

Provides:
    POST   /                     — Create a thread (0..n documents, optional title)
    GET    /                     — Thread index for the sidebar
    GET    /{conversation_id}    — Thread + messages + research trail + citations
    PATCH  /{conversation_id}    — Rename and/or replace the document scope
    DELETE /{conversation_id}    — Delete a thread and everything under it
    POST   /{conversation_id}/message      — **SSE**: ask a question (preferred)
    GET    /{conversation_id}/message      — **SSE**: legacy query-param variant
    GET    /{conversation_id}/test_message — Non-streamed answer (Swagger-friendly)

Streaming contract (see docs/agents/API_REFERENCE.md):
    * one SSE event per snapshot, **unnamed** (`data: {...}`), each a complete
      JSON `Message` — content and `sub_processes` grow monotonically;
    * a terminal event with `status` SUCCESS or ERROR;
    * `sse-starlette` emits `: ping` comments every 15 s as a keep-alive.

Durability: the user message and the assistant placeholder are written *before*
generation starts and content is flushed while streaming, so a dropped
connection loses at most the last couple of seconds of text.
"""
import asyncio
import datetime
import logging
import time
from collections import OrderedDict
from typing import AsyncGenerator, Dict, List, Optional
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app import schema
from app.api import crud
from app.api.deps import get_db
from app.chat.messaging import (
    ChatCallbackHandler,
    StreamedMessage,
    StreamedMessageSubProcess,
    citations_from_sub_processes,
    describe_sub_process,
    handle_chat_message,
)
from app.db.session import SessionLocal
from app.models.db import (
    DocumentStatusEnum,
    MessageRoleEnum,
    MessageStatusEnum,
    MessageSubProcessStatusEnum,
)

router = APIRouter()
logger = logging.getLogger(__name__)

#: Durability knobs for a generating answer: flush at most this often…
_FLUSH_INTERVAL_S = 1.5
#: …or as soon as this many new characters have accumulated, whichever first.
_FLUSH_CHARS = 200

#: Line used when the engine produced nothing at all.
_EMPTY_ANSWER = (
    "Sorry, I either wasn't able to understand your question or I don't have an "
    "answer for it."
)


def _derive_title(question: str) -> str:
    """Threads get their name from the first question, like every chat product."""
    compact = " ".join(question.split())
    return compact if len(compact) <= 80 else compact[:77].rstrip() + "…"


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: schema.ConversationCreate,
    db: AsyncSession = Depends(get_db),
) -> schema.Conversation:
    """
    Create a new conversation, optionally scoped to one or more documents.

    `document_ids` may be empty: a thread can be created first and scoped later
    with `PATCH /api/conversation/{id}`.
    """
    if payload.document_ids:
        doc_ids_str = [str(doc_id) for doc_id in payload.document_ids]
        found_docs = await crud.fetch_documents(db, ids=doc_ids_str)
        found_doc_ids = {str(doc.id) for doc in found_docs}
        missing_ids = [doc_id for doc_id in doc_ids_str if doc_id not in found_doc_ids]
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Documents not found: {', '.join(missing_ids)}",
            )

    return await crud.create_conversation(db, payload)


@router.get("/")
async def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, description="Search thread titles"),
    db: AsyncSession = Depends(get_db),
) -> List[schema.ConversationSummary]:
    """
    Thread index: id, title, document scope, message count and a preview of the
    first question. Never includes message bodies — clients fetch a thread with
    `GET /api/conversation/{id}`.
    """
    return await crud.list_conversations(db, limit=limit, offset=offset, query=q)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, db: AsyncSession = Depends(get_db)
) -> schema.Conversation:
    """
    Get a conversation by ID along with its messages, research trail and citations.
    """
    conversation = await crud.fetch_conversation_with_messages(db, str(conversation_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.patch("/{conversation_id}")
async def patch_conversation(
    conversation_id: UUID,
    payload: schema.ConversationUpdate,
    db: AsyncSession = Depends(get_db),
) -> schema.Conversation:
    """
    Rename a thread and/or replace its document scope.

    Replacing `document_ids` is what the scope picker does: retrieval for the
    next question is narrowed (or widened) to exactly these documents.
    """
    if payload.document_ids is not None:
        doc_ids_str = [str(doc_id) for doc_id in payload.document_ids]
        found_docs = await crud.fetch_documents(db, ids=doc_ids_str)
        found_doc_ids = {str(doc.id) for doc in found_docs}
        missing_ids = [doc_id for doc_id in doc_ids_str if doc_id not in found_doc_ids]
        if missing_ids:
            raise HTTPException(
                status_code=404, detail=f"Documents not found: {', '.join(missing_ids)}"
            )

    conversation = await crud.update_conversation(db, str(conversation_id), payload)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete(
    "/{conversation_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT
)
async def delete_conversation(
    conversation_id: UUID, db: AsyncSession = Depends(get_db)
):
    """
    Delete a conversation by ID, including its messages and research trails.
    """
    did_delete = await crud.delete_conversation(db, str(conversation_id))
    if not did_delete:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


async def _resolve_scope(db: AsyncSession, conversation: schema.Conversation) -> schema.Conversation:
    """
    Return the conversation the engine should answer from.

    An empty scope means "all indexed filings" — that is what the UI implies by
    a thread with no documents selected. Fail loudly when nothing is indexed
    rather than letting the engine hallucinate over an empty index.
    """
    if conversation.documents:
        return conversation

    ready = await crud.fetch_documents(db, status=DocumentStatusEnum.ready)
    if not ready:
        raise HTTPException(
            status_code=409,
            detail=(
                "No indexed documents yet. Upload a filing and wait for it to "
                "finish indexing before asking a question."
            ),
        )
    conversation.documents = ready
    return conversation


async def _answer_stream(
    conversation: schema.Conversation, question: str
) -> AsyncGenerator[schema.Message, None]:
    """
    Generate one assistant answer, yielding `schema.Message` snapshots.

    This is the single implementation behind the SSE endpoints and the
    non-streamed `test_message` route, so both exercise identical persistence
    and trail behaviour.

    Persistence notes:
    * user message + assistant placeholder are committed before generation;
    * assistant content is flushed every ``_FLUSH_INTERVAL_S``;
    * the terminal state (status, content, `sources`, `sub_processes`) is written
      even when the client disconnects or the engine raises.
    """
    conversation_id = str(conversation.id)
    send_chan, recv_chan = anyio.create_memory_object_stream(100)
    handler = ChatCallbackHandler(send_chan)
    started_at = time.monotonic()

    async def produce() -> None:
        # Errors are *not* swallowed here: the consumer awaits this task after the
        # stream drains and turns any exception into a terminal ERROR message.
        try:
            await handle_chat_message(
                conversation,
                schema.MessageCreate(content=question),
                send_chan,
                callback_handler=handler,
            )
        finally:
            # Await the callback tasks first: their sends would otherwise race
            # the close and silently drop the tail of the research trail.
            await handler.drain()
            with anyio.move_on_after(2):
                await send_chan.aclose()

    content = ""
    sub_processes: "OrderedDict[str, dict]" = OrderedDict()
    error_message: Optional[str] = None
    final_status = MessageStatusEnum.SUCCESS

    async with SessionLocal() as db:
        await crud.create_message(
            db,
            conversation_id,
            MessageRoleEnum.user,
            question,
            status=MessageStatusEnum.SUCCESS,
        )
        assistant = await crud.create_message(
            db,
            conversation_id,
            MessageRoleEnum.assistant,
            "",
            status=MessageStatusEnum.PENDING,
        )
        # Copy the scalars we need before any further commit on this session:
        # `snapshot()` runs after `crud.touch_conversation()` and after the
        # periodic content flushes, so it must not touch the ORM instance.
        assistant_id = str(assistant.id)
        assistant_created_at = assistant.created_at
        await crud.touch_conversation(
            db, conversation_id, title_if_empty=_derive_title(question)
        )

        producer = asyncio.create_task(produce(), name=f"answer:{assistant_id}")
        last_flush = time.monotonic()
        flushed_length = 0

        def snapshot(message_status: MessageStatusEnum) -> schema.Message:
            trail = [
                schema.MessageSubProcess(
                    id=step["id"],
                    message_id=UUID(assistant_id),
                    source=step["source"],
                    status=step["status"],
                    name=step["name"],
                    duration_ms=step["duration_ms"],
                    metadata_map=step["metadata_map"],
                    created_at=step["created_at"],
                )
                for step in sub_processes.values()
            ]
            return schema.Message(
                id=UUID(assistant_id),
                conversation_id=conversation.id,
                content=content,
                role=MessageRoleEnum.assistant,
                status=message_status,
                sub_processes=trail,
                sources=schema.citations_to_sources(citations_from_sub_processes(trail)),
                created_at=assistant_created_at,
            )

        try:
            async for item in recv_chan:
                if isinstance(item, StreamedMessage):
                    content = item.content
                elif isinstance(item, StreamedMessageSubProcess):
                    event_id = item.event_id
                    existing = sub_processes.get(event_id)
                    now = datetime.datetime.utcnow()
                    if existing is None:
                        existing = {
                            "id": uuid4(),
                            "source": item.source,
                            "name": describe_sub_process(item.source, item.metadata_map),
                            "status": MessageSubProcessStatusEnum.PENDING,
                            "duration_ms": None,
                            "metadata_map": None,
                            "created_at": now,
                            "_started_at": time.monotonic(),
                        }
                        sub_processes[event_id] = existing

                    if item.metadata_map:
                        existing["metadata_map"] = item.metadata_map
                        existing["name"] = describe_sub_process(item.source, item.metadata_map)
                    if item.has_ended:
                        existing["status"] = MessageSubProcessStatusEnum.FINISHED
                        existing["duration_ms"] = int(
                            (time.monotonic() - existing["_started_at"]) * 1000
                        )

                # Every event produces one snapshot: content and/or trail grew.
                yield snapshot(MessageStatusEnum.PENDING)

                grew_enough = len(content) - flushed_length >= _FLUSH_CHARS
                if content and (grew_enough or time.monotonic() - last_flush >= _FLUSH_INTERVAL_S):
                    await crud.update_message_content(db, assistant_id, content)
                    last_flush = time.monotonic()
                    flushed_length = len(content)

            # Let the producer finish so a mid-flight error is not lost.
            await producer
        except asyncio.CancelledError:
            final_status = MessageStatusEnum.ERROR
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming failed for conversation %s", conversation_id)
            error_message = str(exc) or exc.__class__.__name__
            final_status = MessageStatusEnum.ERROR
            content = content or f"The answer stream failed: {error_message}"
        finally:
            if not producer.done():
                producer.cancel()
                with anyio.move_on_after(2):
                    await producer
            with anyio.move_on_after(2):
                await send_chan.aclose()

            if final_status != MessageStatusEnum.ERROR and not content.strip():
                content = _EMPTY_ANSWER

            trail = [
                schema.MessageSubProcess(
                    id=step["id"],
                    message_id=UUID(assistant_id),
                    source=step["source"],
                    status=step["status"],
                    name=step["name"],
                    duration_ms=step["duration_ms"],
                    metadata_map=step["metadata_map"],
                    created_at=step["created_at"],
                )
                for step in sub_processes.values()
            ]
            sources = schema.citations_to_sources(citations_from_sub_processes(trail))

            try:
                await crud.finalise_message(
                    db,
                    assistant_id,
                    content,
                    final_status,
                    sources=[source.model_dump(mode="json") for source in sources],
                    sub_processes=trail,
                )
            except Exception:  # noqa: BLE001 — never mask the original failure
                logger.exception("Could not persist the final answer for %s", assistant_id)

        logger.info(
            "Answered conversation %s in %.1fs (%d chars, %d citations)",
            conversation_id,
            time.monotonic() - started_at,
            len(content),
            len(sources),
        )

        final = await crud.fetch_message_with_sub_processes(db, assistant_id)
        if final is not None:
            yield final


async def _sse_events(conversation: schema.Conversation, question: str):
    """Wrap `_answer_stream` as SSE frames (unnamed events, JSON snapshots)."""
    try:
        async for message in _answer_stream(conversation, question):
            yield message.model_dump_json()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("SSE stream ended unexpectedly")
        yield schema.Message(
            id=uuid4(),
            conversation_id=conversation.id,
            content=f"The answer stream failed: {exc}",
            role=MessageRoleEnum.assistant,
            status=MessageStatusEnum.ERROR,
            sub_processes=[],
            sources=[],
            created_at=datetime.datetime.utcnow(),
        ).model_dump_json()


async def _stream_response(
    conversation_id: UUID, user_message: str
) -> EventSourceResponse:
    """Shared implementation for both streaming routes."""
    if not user_message or not user_message.strip():
        raise HTTPException(status_code=422, detail="The question must not be empty.")

    # Validate before the stream starts so the client gets real HTTP errors
    # (404 / 409) instead of an error frame inside a 200 stream.
    async with SessionLocal() as db:
        conversation = await crud.fetch_conversation_with_messages(db, str(conversation_id))
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation = await _resolve_scope(db, conversation)

    return EventSourceResponse(_sse_events(conversation, user_message.strip()))


@router.post("/{conversation_id}/message")
async def message_conversation_post(
    conversation_id: UUID,
    payload: schema.MessageCreate,
) -> EventSourceResponse:
    """
    Send a message and receive an SSE stream of the assistant's response.

    Preferred over the GET variant: the question travels in the body (no URL
    length limits, no questions in access logs) and the client can send headers.

    Each frame is a complete `Message` snapshot. While generating, `status` is
    `PENDING`; the final frame is `SUCCESS` or `ERROR`.
    """
    return await _stream_response(conversation_id, payload.content)


@router.get("/{conversation_id}/message", deprecated=True)
async def message_conversation(
    conversation_id: UUID,
    user_message: str = Query(..., description="The question to ask"),
) -> EventSourceResponse:
    """
    Legacy SSE variant with the question in the query string.

    Deprecated in favour of `POST /api/conversation/{id}/message`; kept because
    `curl -N` demos and the terminal client still use it. Same contract.
    """
    return await _stream_response(conversation_id, user_message)


@router.get("/{conversation_id}/test_message")
async def test_message_conversation(
    conversation_id: UUID,
    user_message: str = Query(..., description="The question to ask"),
    db: AsyncSession = Depends(get_db),
) -> schema.Message:
    """
    Non-streaming version of `/message` — returns the final `Message` object.

    Useful in Swagger UI / curl where SSE is awkward. Runs exactly the same
    pipeline (persistence, trail, citations) as the streaming route.
    """
    conversation = await crud.fetch_conversation_with_messages(db, str(conversation_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation = await _resolve_scope(db, conversation)

    final: Optional[schema.Message] = None
    async for message in _answer_stream(conversation, user_message.strip()):
        final = message
    if final is None:
        raise HTTPException(status_code=500, detail="Internal server error")
    return final
