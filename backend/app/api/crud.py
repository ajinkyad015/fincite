from typing import Optional, Sequence, List
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db import Conversation, Message, Document, ConversationDocument
from app import schema
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert
import uuid as uuid_module


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
            "documents": [
                convo_doc.document for convo_doc in conversation.conversation_documents
            ],
        }
        return schema.Conversation(**convo_dict)
    return None


async def create_conversation(
    db: AsyncSession, convo_payload: schema.ConversationCreate
) -> schema.Conversation:
    conversation = Conversation()
    convo_doc_db_objects = [
        ConversationDocument(document_id=doc_id, conversation=conversation)
        for doc_id in convo_payload.document_ids
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


async def fetch_documents(
    db: AsyncSession,
    id: Optional[str] = None,
    ids: Optional[List[str]] = None,
    url: Optional[str] = None,
    limit: Optional[int] = None,
) -> Optional[Sequence[schema.Document]]:
    """
    Fetch documents by id, ids list, or url.
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
    return [schema.Document.model_validate(doc, from_attributes=True) for doc in documents]


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
    stmt = insert(Document).values(**document.dict(exclude_none=True))
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
