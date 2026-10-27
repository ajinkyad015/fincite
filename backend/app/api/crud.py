from typing import List, Optional
import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, delete, update
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.models.db import (
    Conversation,
    ConversationDocument,
    Document,
    DocumentStatusEnum,
    Message,
    MessageRoleEnum,
    MessageStatusEnum,
    MessageSubProcess,
)
from app import schema


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


async def fetch_conversation_with_messages(
    db: AsyncSession, conversation_id: str
) -> Optional[schema.Conversation]:
    """
    Fetch a conversation with its messages + messagesubprocesses.
    Returns None if the conversation does not exist.
    """
    stmt = (
        select(Conversation)
        .options(joinedload(Conversation.messages).subqueryload(Message.sub_processes))
        .options(
            joinedload(Conversation.conversation_documents).subqueryload(
                ConversationDocument.document
            )
        )
        .where(Conversation.id == conversation_id)
    )

    result = await db.execute(stmt)
    conversation = result.scalars().first()
    if conversation is not None:
        convo_dict = {
            **conversation.__dict__,
            "messages": sorted(
                conversation.messages, key=lambda m: m.created_at or datetime.datetime.min
            ),
            "documents": [
                convo_doc.document for convo_doc in conversation.conversation_documents
            ],
        }
        return schema.Conversation(**convo_dict)
    return None


async def create_conversation(
    db: AsyncSession, convo_payload: schema.ConversationCreate
) -> schema.Conversation:
    conversation = Conversation(title=convo_payload.title)
    db.add(conversation)
    await db.flush()
    convo_doc_db_objects = [
        ConversationDocument(document_id=doc_id, conversation_id=conversation.id)
        for doc_id in convo_payload.document_ids
    ]
    if convo_doc_db_objects:
        db.add_all(convo_doc_db_objects)
    await db.commit()
    await db.refresh(conversation)
    return await fetch_conversation_with_messages(db, conversation.id)


async def update_conversation(
    db: AsyncSession,
    conversation_id: str,
    payload: schema.ConversationUpdate,
) -> Optional[schema.Conversation]:
    """
    Rename a thread and/or replace its document scope.

    Returns None when the conversation does not exist.
    """
    existing = await db.get(Conversation, conversation_id)
    if existing is None:
        return None

    if payload.title is not None:
        existing.title = payload.title.strip() or None

    if payload.document_ids is not None:
        await db.execute(
            delete(ConversationDocument).where(
                ConversationDocument.conversation_id == conversation_id
            )
        )
        db.add_all(
            [
                ConversationDocument(
                    conversation_id=conversation_id, document_id=doc_id
                )
                for doc_id in payload.document_ids
            ]
        )

    await db.commit()
    return await fetch_conversation_with_messages(db, conversation_id)


async def list_conversations(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    query: Optional[str] = None,
) -> List[schema.ConversationSummary]:
    """
    Thread index for the sidebar: newest activity first, with a message count
    and a preview of the first user message. Never returns full message bodies.
    """
    counts = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    stmt = (
        select(
            Conversation,
            func.coalesce(counts.c.message_count, 0).label("message_count"),
        )
        .outerjoin(counts, counts.c.conversation_id == Conversation.id)
        .order_by(
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc()
        )
        .limit(limit)
        .offset(offset)
    )
    if query:
        stmt = stmt.where(Conversation.title.ilike(f"%{query}%"))

    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return []

    conversation_ids = [row[0].id for row in rows]

    # First user message per conversation → the subtitle in the thread list.
    preview_stmt = (
        select(Message.conversation_id, Message.content)
        .where(
            Message.conversation_id.in_(conversation_ids),
            Message.role == MessageRoleEnum.user,
        )
        .order_by(Message.conversation_id, Message.created_at)
    )
    preview_result = await db.execute(preview_stmt)
    previews: dict = {}
    for conversation_id, content in preview_result.all():
        if conversation_id in previews or not content:
            continue
        text = content.strip().replace("\n", " ")
        previews[conversation_id] = text[:140] + ("…" if len(text) > 140 else "")

    # Document scope per conversation.
    scope_stmt = select(
        ConversationDocument.conversation_id, ConversationDocument.document_id
    ).where(ConversationDocument.conversation_id.in_(conversation_ids))
    scope_result = await db.execute(scope_stmt)
    scopes: dict = {}
    for conversation_id, document_id in scope_result.all():
        scopes.setdefault(conversation_id, []).append(document_id)

    return [
        schema.ConversationSummary(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            last_message_at=conversation.last_message_at,
            message_count=int(message_count),
            document_ids=scopes.get(conversation.id, []),
            preview=previews.get(conversation.id),
        )
        for conversation, message_count in rows
    ]


async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
    """
    Delete a conversation and everything hanging off it.

    Children are deleted explicitly *and* the FKs cascade (see migration
    ``cascade_deletes``), so this is safe on databases where the constraint was
    created before the cascade existed.
    """
    message_ids = (
        select(Message.id).where(Message.conversation_id == conversation_id).scalar_subquery()
    )
    await db.execute(
        delete(MessageSubProcess).where(MessageSubProcess.message_id.in_(message_ids))
    )
    await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await db.execute(
        delete(ConversationDocument).where(
            ConversationDocument.conversation_id == conversation_id
        )
    )
    result = await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await db.commit()
    return result.rowcount > 0


async def touch_conversation(
    db: AsyncSession,
    conversation_id: str,
    when: Optional[datetime.datetime] = None,
    title_if_empty: Optional[str] = None,
) -> None:
    """
    Bump the thread's activity timestamp (and optionally seed a title from the
    first question, which is how threads get their name in every chat product).
    """
    values: dict = {"last_message_at": when or datetime.datetime.utcnow()}
    if title_if_empty:
        values["title"] = func.coalesce(
            func.nullif(Conversation.title, ""), title_if_empty
        )
    await db.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(**values)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


async def create_message(
    db: AsyncSession,
    conversation_id: str,
    role: MessageRoleEnum,
    content: str = "",
    status: MessageStatusEnum = MessageStatusEnum.PENDING,
    message_id: Optional[str] = None,
) -> Message:
    """Insert a message row immediately (so a dropped stream never loses data)."""
    message = Message(
        conversation_id=conversation_id,
        content=content,
        role=role,
        status=status,
        sub_processes=[],
        sources=[],
    )
    if message_id:
        message.id = message_id
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def update_message_content(db: AsyncSession, message_id: str, content: str) -> None:
    """Flush streamed content so a reload/reconnect sees what was generated."""
    await db.execute(
        update(Message).where(Message.id == message_id).values(content=content)
    )
    await db.commit()


async def finalise_message(
    db: AsyncSession,
    message_id: str,
    content: str,
    status: MessageStatusEnum,
    sources: Optional[List[dict]] = None,
    sub_processes: Optional[List[MessageSubProcess]] = None,
) -> Optional[schema.Message]:
    """
    Persist the terminal state of an assistant message: content, status,
    citations, and the research trail.
    """
    message = await db.get(Message, message_id)
    if message is None:
        return None

    message.content = content
    message.status = status
    message.sources = sources or []

    if sub_processes:
        # Replace the trail wholesale: this call owns the final state. Bind a
        # real UUID object (as `message.id` used to) instead of relying on the
        # driver coercing our str id for an INSERT.
        message_uuid = (
            message_id if isinstance(message_id, UUID) else UUID(str(message_id))
        )
        await db.execute(
            delete(MessageSubProcess).where(
                MessageSubProcess.message_id == message_uuid
            )
        )
        for sub_process in sub_processes:
            db.add(
                MessageSubProcess(
                    message_id=message_uuid,
                    source=sub_process.source,
                    status=sub_process.status,
                    name=sub_process.name,
                    duration_ms=sub_process.duration_ms,
                    metadata_map=sub_process.metadata_map,
                    created_at=sub_process.created_at or datetime.datetime.utcnow(),
                )
            )
    await db.commit()
    # Never read `message.<attr>` after commit: on an async session a commit
    # expires ORM instances, and touching one triggers a sync lazy load —
    # `MissingGreenlet: greenlet_spawn has not been called` — which used to
    # abort finalisation right here. Use the id we were handed instead.
    return await fetch_message_with_sub_processes(db, message_id)


async def fetch_message_with_sub_processes(
    db: AsyncSession, message_id: str
) -> Optional[schema.Message]:
    """
    Fetch a message with its sub processes.
    Returns None if the message does not exist.
    """
    stmt = (
        select(Message)
        .options(joinedload(Message.sub_processes))
        .where(Message.id == message_id)
    )
    result = await db.execute(stmt)
    message = result.scalars().first()
    if message is not None:
        return schema.Message.model_validate(message, from_attributes=True)
    return None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def fetch_documents(
    db: AsyncSession,
    id: Optional[str] = None,
    ids: Optional[List[str]] = None,
    url: Optional[str] = None,
    status: Optional[DocumentStatusEnum] = None,
    query: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[schema.Document]:
    """
    Fetch documents by id, ids list, url, lifecycle status or free-text query.

    Always returns a list (empty when nothing matches) — callers decide whether
    an empty result is a 404.
    """
    stmt = select(Document).order_by(Document.created_at.desc())
    if id is not None:
        stmt = stmt.where(Document.id == id)
        limit = 1
    elif ids is not None:
        stmt = stmt.where(Document.id.in_(ids))
    if url is not None:
        stmt = stmt.where(Document.url == url)
    if status is not None:
        stmt = stmt.where(Document.status == status)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            or_(
                Document.url.ilike(like),
                Document.metadata_map["original_filename"].astext.ilike(like),
                Document.metadata_map["nse_document"]["company_name"].astext.ilike(like),
                Document.metadata_map["nse_document"]["company_symbol"].astext.ilike(like),
                Document.metadata_map["nse_document"]["financial_year"].astext.ilike(like),
            )
        )
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset is not None:
        stmt = stmt.offset(offset)
    result = await db.execute(stmt)
    documents = result.scalars().all()
    return [schema.Document.model_validate(doc, from_attributes=True) for doc in documents]


async def fetch_document(db: AsyncSession, document_id: str) -> Optional[schema.Document]:
    documents = await fetch_documents(db, id=document_id)
    return documents[0] if documents else None


async def create_document(
    db: AsyncSession, document: schema.Document
) -> schema.Document:
    """
    Insert a new document row. The document.id should already be set.
    """
    db_doc = Document(
        id=document.id,
        url=document.url,
        metadata_map=document.metadata_map,
        status=document.status,
        progress=document.progress,
        error=document.error,
        page_count=document.page_count,
        file_size=document.file_size,
        content_hash=document.content_hash,
    )
    db.add(db_doc)
    await db.commit()
    await db.refresh(db_doc)
    return schema.Document.model_validate(db_doc, from_attributes=True)


async def update_document_status(
    db: AsyncSession,
    document_id: str,
    status: DocumentStatusEnum,
    progress: Optional[int] = None,
    error: Optional[str] = None,
    page_count: Optional[int] = None,
    file_size: Optional[int] = None,
) -> None:
    """Advance a document through its ingestion lifecycle."""
    values: dict = {"status": status}
    if progress is not None:
        values["progress"] = max(0, min(100, progress))
    if error is not None:
        values["error"] = error
    if page_count is not None:
        values["page_count"] = page_count
    if file_size is not None:
        values["file_size"] = file_size
    if status == DocumentStatusEnum.ready:
        values["progress"] = 100
        values["error"] = None
    await db.execute(update(Document).where(Document.id == document_id).values(**values))
    await db.commit()


async def mark_stale_documents_failed(
    db: AsyncSession, older_than_minutes: int = 15
) -> int:
    """
    Boot-time sweep: anything left mid-ingestion by a crashed process is marked
    failed so the UI stops waiting. Returns the number of rows touched.
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=older_than_minutes)
    non_terminal = [
        DocumentStatusEnum.uploaded,
        DocumentStatusEnum.parsing,
        DocumentStatusEnum.chunking,
        DocumentStatusEnum.embedding,
        DocumentStatusEnum.indexing,
    ]
    stmt = (
        update(Document)
        .where(Document.status.in_(non_terminal), Document.updated_at < cutoff)
        .values(
            status=DocumentStatusEnum.failed,
            error="Ingestion was interrupted. Re-index from the library to retry.",
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0


async def delete_document_by_id(db: AsyncSession, document_id: str) -> bool:
    """
    Delete a document row (and its conversation links). Used for rollback when
    indexing fails and by ``DELETE /api/document/{id}``.
    """
    await db.execute(
        delete(ConversationDocument).where(
            ConversationDocument.document_id == document_id
        )
    )
    stmt = delete(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def upsert_document_by_url(
    db: AsyncSession, document: schema.Document
) -> schema.Document:
    """
    Upsert a document by URL (for backward compatibility).
    """
    stmt = insert(Document).values(**document.model_dump(exclude_none=True))
    stmt = stmt.on_conflict_do_update(
        index_elements=[Document.url],
        set_=document.model_dump(mode="json", include={"metadata_map"}),
    )
    stmt = stmt.returning(Document)
    result = await db.execute(stmt)
    upserted_doc = schema.Document.model_validate(
        result.scalars().first(), from_attributes=True
    )
    await db.commit()
    return upserted_doc


async def fetch_document_by_content_hash(
    db: AsyncSession, content_hash: str
) -> Optional[schema.Document]:
    """
    Look up a document by its SHA-256 content hash. Used for duplicate detection
    on upload.
    """
    stmt = select(Document).where(
        or_(
            Document.content_hash == content_hash,
            Document.metadata_map["content_hash"].astext == content_hash,
        )
    )
    result = await db.execute(stmt)
    doc = result.scalars().first()
    if doc is not None:
        return schema.Document.model_validate(doc, from_attributes=True)
    return None
