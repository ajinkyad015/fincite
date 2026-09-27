from sqlalchemy import Column, String, Integer, Float, Text, Enum as SAEnum, ForeignKey
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
    """Status of a document in the ingestion pipeline."""
    uploading = "uploading"
    processing = "processing"
    ready = "ready"
    error = "error"


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
    A document along with its metadata.

    Promoted columns (added for frontend alignment):
        filename, status, progress, company_name, company_symbol, exchange,
        document_type, financial_year, report_date, pages, file_size, language,
        error_message

    Legacy columns (kept for backward compatibility):
        url          — Supabase Storage URL for the PDF
        metadata_map — arbitrary JSONB (includes nse_document sub-object)
    """

    # ------------------------------------------------------------------
    # Legacy / core fields
    # ------------------------------------------------------------------
    # URL to the actual document (e.g. a PDF in Supabase Storage)
    url = Column(String, nullable=False, unique=True)
    metadata_map = Column(JSONB, nullable=True)

    # ------------------------------------------------------------------
    # Promoted product-facing fields
    # ------------------------------------------------------------------
    filename = Column(String, nullable=True)
    status = Column(
        String,
        nullable=False,
        default=DocumentStatusEnum.ready.value,
        server_default=DocumentStatusEnum.ready.value,
    )
    progress = Column(Integer, nullable=False, default=100, server_default="100")

    # Financial / NSE metadata (promoted for fast querying & clean API)
    company_name = Column(String, nullable=True)
    company_symbol = Column(String, nullable=True)
    exchange = Column(String, nullable=True)
    document_type = Column(String, nullable=True)
    financial_year = Column(String, nullable=True)
    report_date = Column(String, nullable=True)   # stored as ISO string
    pages = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=True)    # bytes
    language = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    conversations = relationship("ConversationDocument", back_populates="document")


class Conversation(Base):
    """
    A conversation with messages and linked documents.
    """

    title = Column(String, nullable=True)

    messages = relationship("Message", back_populates="conversation")
    conversation_documents = relationship(
        "ConversationDocument", back_populates="conversation"
    )


class ConversationDocument(Base):
    """
    A many-to-many relationship between a conversation and a document
    """

    conversation_id = Column(
        UUID(as_uuid=True), ForeignKey("conversation.id"), index=True
    )
    document_id = Column(UUID(as_uuid=True), ForeignKey("document.id"), index=True)
    conversation = relationship("Conversation", back_populates="conversation_documents")
    document = relationship("Document", back_populates="conversations")


class Message(Base):
    """
    A message in a conversation
    """

    conversation_id = Column(
        UUID(as_uuid=True), ForeignKey("conversation.id"), index=True
    )
    content = Column(String)
    role = Column(to_pg_enum(MessageRoleEnum))
    status = Column(to_pg_enum(MessageStatusEnum), default=MessageStatusEnum.PENDING)
    conversation = relationship("Conversation", back_populates="messages")
    sub_processes = relationship("MessageSubProcess", back_populates="message")
    sources = relationship("MessageSource", back_populates="message")


class MessageSubProcess(Base):
    """
    A record of a sub-process that occurred as part of the generation of a message from an AI assistant
    """

    message_id = Column(UUID(as_uuid=True), ForeignKey("message.id"), index=True)
    source = Column(to_pg_enum(MessageSubProcessSourceEnum))
    message = relationship("Message", back_populates="sub_processes")
    status = Column(
        to_pg_enum(MessageSubProcessStatusEnum),
        default=MessageSubProcessStatusEnum.FINISHED,
        nullable=False,
    )
    metadata_map = Column(JSONB, nullable=True)


class MessageSource(Base):
    """
    A grounded citation / source attached to an assistant message.

    Corresponds to the frontend Source type:
        { index, document_id, page, excerpt, score }
    """

    message_id = Column(UUID(as_uuid=True), ForeignKey("message.id"), index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("document.id"), index=True)
    index = Column(Integer, nullable=False)        # 1-based citation index
    page = Column(Integer, nullable=True)
    excerpt = Column(Text, nullable=True)
    score = Column(Float, nullable=True)

    message = relationship("Message", back_populates="sources")
    document = relationship("Document")
