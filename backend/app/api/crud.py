from typing import Optional, Sequence, List
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db import Conversation, Message, Document, ConversationDocument, MessageSource
from app import schema
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert
import uuid as uuid_module


async def fetch_conversation_with_messages(
    db: AsyncSession, conversation_id: str
) -> Optional[schema.Conversation]:
    """
    Fetch a conversation with its messages + messagesubprocesses + sources.
    Returns None if the conversation does not exist.
    """
    stmt = (
        select(Conversation)
        .options(
            joinedload(Conversation.messages)
            .subqueryload(Message.sub_processes)
        )
        .options(
            joinedload(Conversation.messages)
            .subqueryload(Message.sources)
        )
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
        raw_docs = [
            convo_doc.document for convo_doc in conversation.conversation_documents
        ]
        convo_dict = {
            **conversation.__dict__,
            "documents": raw_docs,
            "document_scope": [doc.id for doc in raw_docs if doc.id],
        }
        return schema.Conversation(**convo_dict)
    return None


async def create_conversation(
    db: AsyncSession, convo_payload: schema.ConversationCreate
) -> schema.Conversation:
    doc_ids = convo_payload.document_scope or []
    conversation = Conversation(title=convo_payload.title)
    convo_doc_db_objects = [
        ConversationDocument(document_id=doc_id, conversation=conversation)
        for doc_id in doc_ids
    ]
    db.add(conversation)
    db.add_all(convo_doc_db_objects)
    await db.commit()
    await db.refresh(conversation)
    return await fetch_conversation_with_messages(db, conversation.id)


async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
    stmt = delete(Conversation).where(Conversation.id == conversation_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def fetch_message_with_sub_processes(
    db: AsyncSession, message_id: str
) -> Optional[schema.Message]:
    """
    Fetch a message with its sub processes and sources.
    Returns None if the message does not exist.
    """
    stmt = (
        select(Message)
        .options(joinedload(Message.sub_processes))
        .options(joinedload(Message.sources))
        .where(Message.id == message_id)
    )
    result = await db.execute(stmt)
    message = result.scalars().first()
    if message is not None:
        return schema.Message.model_validate(message, from_attributes=True)
    return None


async def fetch_documents(
    db: AsyncSession,
    id: Optional[str] = None,
    ids: Optional[List[str]] = None,
    url: Optional[str] = None,
    limit: Optional[int] = None,
) -> Optional[Sequence[schema.FinDocumentSchema]]:
    """
    Fetch documents by id, ids list, or url. Returns FinDocumentSchema objects.
    """
    stmt = select(Document)
    if id is not None:
        stmt = stmt.where(Document.id == id)
        limit = 1
    elif ids is not None:
        stmt = stmt.where(Document.id.in_(ids))
    if url is not None:
        stmt = stmt.where(Document.url == url)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    documents = result.scalars().all()
    # Convert to legacy Document schema first (for attribute mapping), then to FinDocumentSchema
    legacy_docs = [schema.Document.model_validate(doc, from_attributes=True) for doc in documents]
    return [schema.FinDocumentSchema.from_db_document(d) for d in legacy_docs]


async def fetch_documents_legacy(
    db: AsyncSession,
    id: Optional[str] = None,
    ids: Optional[List[str]] = None,
) -> Optional[Sequence[schema.Document]]:
    """
    Fetch documents as legacy Document schema. Used internally (e.g. by conversation engine).
    """
    stmt = select(Document)
    if id is not None:
        stmt = stmt.where(Document.id == id)
    elif ids is not None:
        stmt = stmt.where(Document.id.in_(ids))
    result = await db.execute(stmt)
    documents = result.scalars().all()
    return [schema.Document.model_validate(doc, from_attributes=True) for doc in documents]


async def create_document(
    db: AsyncSession, document: schema.Document
) -> schema.Document:
    """
    Insert a new document row. The document.id should already be set.
    Writes promoted columns if present on the schema object.
    """
    db_doc = Document(
        id=document.id,
        url=document.url,
        metadata_map=document.metadata_map,
        filename=document.filename,
        status=document.status or "ready",
        progress=document.progress if document.progress is not None else 100,
        company_name=document.company_name,
        company_symbol=document.company_symbol,
        exchange=document.exchange,
        document_type=document.document_type,
        financial_year=document.financial_year,
        report_date=document.report_date,
        pages=document.pages,
        file_size=document.file_size,
        language=document.language,
        error_message=document.error_message,
    )
    db.add(db_doc)
    await db.commit()
    await db.refresh(db_doc)
    return schema.Document.model_validate(db_doc, from_attributes=True)


async def delete_document_by_id(db: AsyncSession, document_id: str) -> bool:
    """
    Delete a document record by ID. Used for rollback when indexing fails.
    """
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
    Look up a document by its SHA-256 content hash stored in metadata_map.
    Used for duplicate detection on upload.
    """
    stmt = select(Document).where(
        Document.metadata_map["content_hash"].astext == content_hash
    )
    result = await db.execute(stmt)
    doc = result.scalars().first()
    if doc is not None:
        return schema.Document.model_validate(doc, from_attributes=True)
    return None


async def create_message_source(
    db: AsyncSession, source: schema.MessageSource
) -> schema.MessageSource:
    """
    Insert a MessageSource (citation) row.
    """
    db_source = MessageSource(
        message_id=source.message_id,
        document_id=source.document_id,
        index=source.index,
        page=source.page,
        excerpt=source.excerpt,
        score=source.score,
    )
    db.add(db_source)
    await db.commit()
    await db.refresh(db_source)
    return schema.MessageSource.model_validate(db_source, from_attributes=True)


async def bulk_create_message_sources(
    db: AsyncSession, sources: List[schema.MessageSource]
) -> List[schema.MessageSource]:
    """
    Insert multiple MessageSource rows in one commit.
    """
    if not sources:
        return []
    db_sources = [
        MessageSource(
            message_id=s.message_id,
            document_id=s.document_id,
            index=s.index,
            page=s.page,
            excerpt=s.excerpt,
            score=s.score,
        )
        for s in sources
    ]
    db.add_all(db_sources)
    await db.commit()
    for db_s in db_sources:
        await db.refresh(db_s)
    return [schema.MessageSource.model_validate(s, from_attributes=True) for s in db_sources]
