"""
Conversation endpoints.

Changes from original:
  - POST / now accepts ConversationCreate with `title` and `document_scope`
  - GET /{id} returns Conversation with `title` and `document_scope`
  - GET /{id}/message SSE stream now emits named events:
      event: sub_process  — subprocess started/updated/completed
      event: delta        — incremental text token
      event: done         — final payload with sources list
    This matches the frontend RealTransport event names exactly.
  - Citations extracted from LlamaIndex metadata are persisted as MessageSource rows.
"""
from fastapi import Depends, APIRouter, HTTPException, status
import anyio
from uuid import uuid4
import datetime
import asyncio
import json
import logging
from collections import OrderedDict
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from app.api.deps import get_db
from app.api import crud
from app import schema
from app.chat.messaging import (
    handle_chat_message,
    StreamedMessage,
    StreamedMessageSubProcess,
)
from app.models.db import (
    Message,
    MessageSubProcess,
    MessageRoleEnum,
    MessageStatusEnum,
    MessageSubProcessStatusEnum,
)
from app.schema import _source_label
from uuid import UUID

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/")
async def create_conversation(
    payload: schema.ConversationCreate,
    db: AsyncSession = Depends(get_db),
) -> schema.Conversation:
    """
    Create a new conversation linked to one or more previously uploaded documents.

    Accepts:
      - title (optional, auto-generated if omitted)
      - document_scope (list of document UUIDs; also accepts legacy document_ids)
    """
    doc_ids = payload.document_scope or []
    if doc_ids:
        doc_ids_str = [str(doc_id) for doc_id in doc_ids]
        found_docs = await crud.fetch_documents(db, ids=doc_ids_str)
        found_doc_ids = {str(doc.id) for doc in found_docs}
        missing_ids = [doc_id for doc_id in doc_ids_str if doc_id not in found_doc_ids]
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Documents not found: {', '.join(missing_ids)}"
            )

    # Auto-generate title if not provided
    if not payload.title and doc_ids:
        # Try to use the first document's company name
        docs = await crud.fetch_documents(db, ids=[str(doc_ids[0])])
        if docs:
            d = docs[0]
            company = d.metadata.company_name if d.metadata else None
            payload.title = f"Chat about {company}" if company else "New conversation"
        else:
            payload.title = "New conversation"
    elif not payload.title:
        payload.title = "New conversation"

    return await crud.create_conversation(db, payload)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, db: AsyncSession = Depends(get_db)
) -> schema.Conversation:
    """
    Get a conversation by ID along with its messages, sub-processes, and sources.
    """
    conversation = await crud.fetch_conversation_with_messages(db, str(conversation_id))
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
    Delete a conversation by ID.
    """
    did_delete = await crud.delete_conversation(db, str(conversation_id))
    if not did_delete:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return


@router.get("/{conversation_id}/message")
async def message_conversation(
    conversation_id: UUID,
    user_message: str,
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """
    Send a message and receive a Server-Sent Events (SSE) stream.

    Named SSE events emitted:
      event: sub_process  data: { id, name, source, status, detail?, duration_ms? }
      event: delta        data: <token string>
      event: done         data: { content, sources: [{ index, document_id, page, excerpt, score }] }

    While generating, status is PENDING; on completion it becomes SUCCESS or ERROR.

    **Note**: Swagger UI does not render SSE streams natively — use a browser EventSource
    or `curl -N` to consume this endpoint.
    """
    conversation = await crud.fetch_conversation_with_messages(db, str(conversation_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_msg_obj = Message(
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
        conversation_id=conversation_id,
        content=user_message,
        role=MessageRoleEnum.user,
        status=MessageStatusEnum.SUCCESS,
    )

    send_chan, recv_chan = anyio.create_memory_object_stream(100)

    async def event_publisher():
        async with send_chan:
            task = asyncio.create_task(
                handle_chat_message(conversation, user_msg_obj, send_chan)
            )
            message_id = str(uuid4())
            message = Message(
                id=message_id,
                conversation_id=conversation_id,
                content="",
                role=MessageRoleEnum.assistant,
                status=MessageStatusEnum.PENDING,
                sub_processes=[],
            )
            final_status = MessageStatusEnum.ERROR
            event_id_to_sub_process: OrderedDict = OrderedDict()
            # Track start times for duration_ms calculation
            event_id_to_start: dict = {}
            accumulated_content = ""
            # Collect citations (Citation objects from sub_question metadata)
            collected_citations: List[schema.Citation] = []

            try:
                async for message_obj in recv_chan:
                    if isinstance(message_obj, StreamedMessage):
                        # Extract the delta (new tokens only)
                        new_content = message_obj.content[len(accumulated_content):]
                        accumulated_content = message_obj.content
                        message.content = message_obj.content

                        if new_content:
                            # emit: event: delta, data: <token>
                            yield ServerSentEvent(event="delta", data=new_content)

                    elif isinstance(message_obj, StreamedMessageSubProcess):
                        sub_status = (
                            MessageSubProcessStatusEnum.FINISHED
                            if message_obj.has_ended
                            else MessageSubProcessStatusEnum.PENDING
                        )

                        # Track timing
                        now = datetime.datetime.utcnow()
                        if message_obj.event_id in event_id_to_sub_process:
                            created_at = event_id_to_sub_process[message_obj.event_id].created_at
                        else:
                            created_at = now
                            event_id_to_start[message_obj.event_id] = now

                        # Compute duration_ms if ended
                        duration_ms: Optional[int] = None
                        if message_obj.has_ended and message_obj.event_id in event_id_to_start:
                            delta = now - event_id_to_start[message_obj.event_id]
                            duration_ms = int(delta.total_seconds() * 1000)

                        # Extract detail from metadata_map (e.g. sub-question answer)
                        detail: Optional[str] = None
                        if message_obj.metadata_map:
                            sub_q_data = message_obj.metadata_map.get("sub_question")
                            if sub_q_data and isinstance(sub_q_data, dict):
                                detail = sub_q_data.get("question")
                                # Also collect citations from sub-question answers
                                citations = sub_q_data.get("citations") or []
                                for c in citations:
                                    try:
                                        collected_citations.append(
                                            schema.Citation(**c) if isinstance(c, dict) else c
                                        )
                                    except Exception:
                                        pass

                        sub_process = MessageSubProcess(
                            created_at=created_at,
                            message_id=message_id,
                            source=message_obj.source,
                            metadata_map=message_obj.metadata_map,
                            status=sub_status,
                        )
                        event_id_to_sub_process[message_obj.event_id] = sub_process
                        message.sub_processes = list(event_id_to_sub_process.values())

                        # Build the frontend-facing sub_process event payload
                        sp_payload = {
                            "id": message_obj.event_id,
                            "name": _source_label(message_obj.source),
                            "source": message_obj.source.value
                            if hasattr(message_obj.source, "value")
                            else str(message_obj.source),
                            "status": "completed" if message_obj.has_ended else "running",
                        }
                        if detail:
                            sp_payload["detail"] = detail
                        if duration_ms is not None:
                            sp_payload["duration_ms"] = duration_ms

                        # emit: event: sub_process
                        yield ServerSentEvent(
                            event="sub_process",
                            data=json.dumps(sp_payload),
                        )
                    else:
                        logger.error(
                            "Unknown message object type: %s", type(message_obj)
                        )
                        continue

                await task
                if task.exception():
                    raise ValueError(
                        "handle_chat_message task failed"
                    ) from task.exception()
                final_status = MessageStatusEnum.SUCCESS

            except Exception as e:
                logger.error("Error in message publisher", exc_info=True)
                final_status = MessageStatusEnum.ERROR
                
                error_msg = str(e)
                if getattr(e, "__cause__", None):
                    error_msg += f" {e.__cause__}"
                
                if "ResourceExhausted" in error_msg or "Quota exceeded" in error_msg or "429" in error_msg:
                    user_facing_error = "I'm sorry, but the AI service quota has been exceeded. Please try again in a minute."
                else:
                    user_facing_error = "An error occurred while generating the response."
                
                prefix = "\n\n" if accumulated_content else ""
                accumulated_content += f"{prefix}{user_facing_error}"
                yield ServerSentEvent(event="delta", data=f"{prefix}{user_facing_error}")

            # Persist user message and assistant message
            message.status = final_status
            db.add(user_msg_obj)
            db.add(message)
            await db.commit()

            # Persist citations as MessageSource rows
            sources_payload: List[dict] = []
            if collected_citations:
                message_sources = [
                    schema.MessageSource(
                        message_id=message_id,
                        document_id=str(c.document_id),
                        index=idx + 1,
                        page=c.page_number,
                        excerpt=c.text[:500] if c.text else None,
                        score=c.score,
                    )
                    for idx, c in enumerate(collected_citations)
                ]
                try:
                    persisted = await crud.bulk_create_message_sources(db, message_sources)
                    sources_payload = [
                        {
                            "index": s.index,
                            "document_id": str(s.document_id),
                            "page": s.page,
                            "excerpt": s.excerpt,
                            "score": s.score,
                        }
                        for s in persisted
                    ]
                except Exception as exc:
                    logger.error("Failed to persist message sources: %s", exc, exc_info=True)

            # emit: event: done
            done_payload = {
                "content": accumulated_content,
                "sources": sources_payload,
            }
            yield ServerSentEvent(event="done", data=json.dumps(done_payload))

    # ping=15: send an SSE comment (invisible keep-alive) every 15 s so that
    # reverse proxies (Cloud Run, Railway, Nginx) don't close the silent
    # connection with 504 while the RAG pipeline is thinking between tokens.
    return EventSourceResponse(event_publisher(), ping=15)


@router.get("/{conversation_id}/test_message")
async def test_message_conversation(
    conversation_id: UUID,
    user_message: str,
    db: AsyncSession = Depends(get_db),
) -> schema.Message:
    """
    Non-streaming version of `/message` — returns a single `Message` object.
    Useful for Swagger UI testing where SSE is not rendered.
    Internally consumes the full SSE stream and returns the final assembled message.
    """
    conversation = await crud.fetch_conversation_with_messages(db, str(conversation_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_msg_obj = Message(
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
        conversation_id=conversation_id,
        content=user_message,
        role=MessageRoleEnum.user,
        status=MessageStatusEnum.SUCCESS,
    )

    send_chan, recv_chan = anyio.create_memory_object_stream(100)
    task = asyncio.create_task(
        handle_chat_message(conversation, user_msg_obj, send_chan)
    )
    message_id = str(uuid4())
    message = Message(
        id=message_id,
        conversation_id=conversation_id,
        content="",
        role=MessageRoleEnum.assistant,
        status=MessageStatusEnum.PENDING,
        sub_processes=[],
    )
    final_status = MessageStatusEnum.ERROR
    event_id_to_sub_process: OrderedDict = OrderedDict()
    collected_citations: List[schema.Citation] = []

    async with send_chan:
        try:
            async for message_obj in recv_chan:
                if isinstance(message_obj, StreamedMessage):
                    message.content = message_obj.content
                elif isinstance(message_obj, StreamedMessageSubProcess):
                    sub_status = (
                        MessageSubProcessStatusEnum.FINISHED
                        if message_obj.has_ended
                        else MessageSubProcessStatusEnum.PENDING
                    )
                    if message_obj.event_id in event_id_to_sub_process:
                        created_at = event_id_to_sub_process[message_obj.event_id].created_at
                    else:
                        created_at = datetime.datetime.utcnow()
                    if message_obj.metadata_map:
                        sub_q_data = message_obj.metadata_map.get("sub_question")
                        if sub_q_data and isinstance(sub_q_data, dict):
                            for c in sub_q_data.get("citations") or []:
                                try:
                                    collected_citations.append(
                                        schema.Citation(**c) if isinstance(c, dict) else c
                                    )
                                except Exception:
                                    pass
                    sub_process = MessageSubProcess(
                        created_at=created_at,
                        message_id=message_id,
                        source=message_obj.source,
                        metadata_map=message_obj.metadata_map,
                        status=sub_status,
                    )
                    event_id_to_sub_process[message_obj.event_id] = sub_process
                    message.sub_processes = list(event_id_to_sub_process.values())
            await task
            if task.exception():
                raise ValueError("handle_chat_message task failed") from task.exception()
            final_status = MessageStatusEnum.SUCCESS
        except Exception:
            logger.error("Error in test_message", exc_info=True)
            final_status = MessageStatusEnum.ERROR

    message.status = final_status
    db.add(user_msg_obj)
    db.add(message)
    await db.commit()

    if collected_citations:
        message_sources = [
            schema.MessageSource(
                message_id=message_id,
                document_id=str(c.document_id),
                index=idx + 1,
                page=c.page_number,
                excerpt=c.text[:500] if c.text else None,
                score=c.score,
            )
            for idx, c in enumerate(collected_citations)
        ]
        try:
            await crud.bulk_create_message_sources(db, message_sources)
        except Exception as exc:
            logger.error("Failed to persist test message sources: %s", exc, exc_info=True)

    final_message = await crud.fetch_message_with_sub_processes(db, message_id)
    if final_message is None:
        raise HTTPException(status_code=500, detail="Internal server error")
    return final_message
