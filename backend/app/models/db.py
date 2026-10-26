from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID, ENUM, JSONB
from sqlalchemy.orm import relationship
from enum import Enum
from llama_index.core.callbacks.schema import CBEventType
from app.models.base import Base


class MessageRoleEnum(str, Enum):
    user = "user"
    assistant = "assistant"


class MessageStatusEnum(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class MessageSubProcessStatusEnum(str, Enum):
    PENDING = "PENDING"
    FINISHED = "FINISHED"


class DocumentStatusEnum(str, Enum):
    """
    Lifecycle of a document after upload.

    ``uploaded`` → ``parsing`` → ``chunking`` → ``embedding`` → ``indexing`` → ``ready``
    with ``failed`` reachable from any non-terminal state. The frontend renders
    exactly these names, so keep them in sync with `frontend/src/lib/types.ts`.
    """

    uploaded = "uploaded"
    parsing = "parsing"
    chunking = "chunking"
    embedding = "embedding"
    indexing = "indexing"
    ready = "ready"
    failed = "failed"


TERMINAL_DOCUMENT_STATUSES = (DocumentStatusEnum.ready, DocumentStatusEnum.failed)


# python doesn't allow enums to be extended, so we have to do this
additional_message_subprocess_fields = {
    "CONSTRUCTED_QUERY_ENGINE": "constructed_query_engine",
    "SUB_QUESTIONS": "sub_questions",
}
MessageSubProcessSourceEnum = Enum(
    "MessageSubProcessSourceEnum",
    [(event_type.name, event_type.value) for event_type in CBEventType]
    + list(additional_message_subprocess_fields.items()),
)


def to_pg_enum(enum_class) -> ENUM:
    return ENUM(enum_class, name=enum_class.__name__)


class Document(Base):
    """
    A document along with its metadata
    """

    # URL to the actual document (e.g. a PDF)
    url = Column(String, nullable=False, unique=True)
    metadata_map = Column(JSONB, nullable=True)

    # Ingestion lifecycle. Indexing runs in the background (app/ingestion/jobs.py),
    # so clients poll this instead of waiting on the upload request.
    status = Column(
        to_pg_enum(DocumentStatusEnum),
        default=DocumentStatusEnum.uploaded,
        nullable=False,
    )
    progress = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    # Denormalised from metadata_map / the ingestion run for cheap listing.
    page_count = Column(Integer, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    content_hash = Column(String(64), nullable=True, unique=True, index=True)

    conversations = relationship("ConversationDocument", back_populates="document")


class Conversation(Base):
    """
    A conversation with messages and linked documents
    """

    title = Column(String(200), nullable=True)
    # Denormalised ordering key for the thread list (messages may be empty).
    last_message_at = Column(DateTime, nullable=True, index=True)

    messages = relationship("Message", back_populates="conversation")
    conversation_documents = relationship(
        "ConversationDocument", back_populates="conversation"
    )


class ConversationDocument(Base):
    """
    A many-to-many relationship between a conversation and a document
    """

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), index=True
    )
    conversation = relationship("Conversation", back_populates="conversation_documents")
    document = relationship("Document", back_populates="conversations")


class Message(Base):
    """
    A message in a conversation
    """

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        index=True,
    )
    content = Column(String)
    role = Column(to_pg_enum(MessageRoleEnum))
    status = Column(to_pg_enum(MessageStatusEnum), default=MessageStatusEnum.PENDING)
    # Citations for the assistant answer: [{index, document_id, page, excerpt, score}]
    sources = Column(JSONB, nullable=True)
    conversation = relationship("Conversation", back_populates="messages")
    sub_processes = relationship("MessageSubProcess", back_populates="message")


class MessageSubProcess(Base):
    """
    A record of a sub-process that occurred as part of the generation of a message from an AI assistant
    """

    message_id = Column(
        UUID(as_uuid=True), ForeignKey("message.id", ondelete="CASCADE"), index=True
    )
    source = Column(to_pg_enum(MessageSubProcessSourceEnum))
    message = relationship("Message", back_populates="sub_processes")
    status = Column(
        to_pg_enum(MessageSubProcessStatusEnum),
        default=MessageSubProcessStatusEnum.FINISHED,
        nullable=False,
    )
    # Human-readable label rendered in the research trail, e.g.
    # "Retrieving Reliance Industries (RELIANCE) — FY2024-25"
    name = Column(String(300), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    metadata_map = Column(JSONB, nullable=True)
