"""
Pydantic Schemas for the API

New additions (frontend alignment):
  - DocumentStatusEnum          — status values matching frontend DocumentStatus
  - FinDocumentMetadata         — flattened metadata sub-object matching frontend DocumentMetadata
  - FinDocumentSchema           — product-facing Document schema matching frontend FinDocument
  - MessageSourceSchema         — citation / Source matching frontend Source type
  - Enriched MessageSubProcess  — adds name, detail, duration_ms
  - Updated Message             — adds sources: List[MessageSourceSchema]
  - Updated Conversation        — adds title, document_scope
  - Updated ConversationCreate  — accepts title + document_scope (alias for document_ids)
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from typing import List, Optional, Dict, Union, Any
from uuid import UUID
from datetime import datetime
from llama_index.core.schema import BaseNode, NodeWithScore
from llama_index.core.callbacks.schema import EventPayload
from llama_index.core.query_engine.sub_question_query_engine import SubQuestionAnswerPair
from app.models.db import (
    MessageRoleEnum,
    MessageStatusEnum,
    MessageSubProcessSourceEnum,
    MessageSubProcessStatusEnum,
    DocumentStatusEnum,
)
from app.chat.constants import DB_DOC_ID_KEY


class Base(BaseModel):
    id: Optional[UUID] = Field(None, description="Unique identifier")
    created_at: Optional[datetime] = Field(None, description="Creation datetime")
    updated_at: Optional[datetime] = Field(None, description="Update datetime")

    model_config = {"from_attributes": True}


class BaseMetadataObject(BaseModel):
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Citation / Source
# ---------------------------------------------------------------------------


class Citation(BaseMetadataObject):
    document_id: UUID
    text: str
    page_number: int
    score: Optional[float] = None

    @field_validator("document_id", mode="before")
    @classmethod
    def validate_document_id(cls, value):
        if value:
            return str(value)
        return value

    @classmethod
    def from_node(cls, node_w_score: NodeWithScore) -> "Citation":
        node: BaseNode = node_w_score.node
        page_number = int(node.source_node.metadata["page_label"])
        document_id = node.source_node.metadata[DB_DOC_ID_KEY]
        return cls(
            document_id=document_id,
            text=node.get_content(),
            page_number=page_number,
            score=node_w_score.score,
        )


class QuestionAnswerPair(BaseMetadataObject):
    """
    A question-answer pair that is used to store the sub-questions and answers
    """

    question: str
    answer: Optional[str] = None
    citations: Optional[List[Citation]] = None

    @classmethod
    def from_sub_question_answer_pair(
        cls, sub_question_answer_pair: SubQuestionAnswerPair
    ):
        if sub_question_answer_pair.sources is None:
            citations = None
        else:
            citations = [
                Citation.from_node(node_w_score)
                for node_w_score in sub_question_answer_pair.sources
                if node_w_score.node.source_node is not None
                and DB_DOC_ID_KEY in node_w_score.node.source_node.metadata
            ]
        citations = citations or None
        return cls(
            question=sub_question_answer_pair.sub_q.sub_question,
            answer=sub_question_answer_pair.answer,
            citations=citations,
        )


class SubProcessMetadataKeysEnum(str, Enum):
    SUB_QUESTION = EventPayload.SUB_QUESTION.value


SubProcessMetadataMap = Dict[Union[SubProcessMetadataKeysEnum, str], Any]

# ---------------------------------------------------------------------------
# Human-readable labels for MessageSubProcess source values
# ---------------------------------------------------------------------------

_SOURCE_LABELS: Dict[str, str] = {
    "LLM": "LLM reasoning",
    "QUERY": "Query planning",
    "RETRIEVE": "Retrieval",
    "RERANKING": "Reranking",
    "SYNTHESIZE": "Answer synthesis",
    "EMBEDDING": "Embedding",
    "CHUNKING": "Chunking",
    "NODE_PARSING": "Node parsing",
    "SUB_QUESTION": "Sub-question",
    "TEMPLATING": "Templating",
    "FUNCTION_CALL": "Function call",
    "EXCEPTION": "Exception",
    "AGENT_STEP": "Agent step",
    "CONSTRUCTED_QUERY_ENGINE": "Query engine ready",
    "SUB_QUESTIONS": "Sub-questions",
}


def _source_label(source) -> str:
    """Return a human-readable label for a MessageSubProcessSource value."""
    name = source.name if hasattr(source, "name") else str(source)
    return _SOURCE_LABELS.get(name, name.replace("_", " ").title())


class MessageSubProcess(Base):
    message_id: UUID
    source: MessageSubProcessSourceEnum
    status: MessageSubProcessStatusEnum
    metadata_map: Optional[SubProcessMetadataMap] = None
    # Enriched fields for frontend
    name: Optional[str] = None
    detail: Optional[str] = None
    duration_ms: Optional[int] = None

    @model_validator(mode="after")
    def _derive_name(self) -> "MessageSubProcess":
        """Auto-populate name from source if not explicitly set."""
        if self.name is None and self.source is not None:
            self.name = _source_label(self.source)
        return self


# ---------------------------------------------------------------------------
# MessageSource (citation)
# ---------------------------------------------------------------------------


class MessageSource(Base):
    """
    A grounded citation attached to an assistant message.
    Matches the frontend Source type.
    """

    message_id: UUID
    document_id: UUID
    index: int
    page: Optional[int] = None
    excerpt: Optional[str] = None
    score: Optional[float] = None

    @field_validator("document_id", "message_id", mode="before")
    @classmethod
    def _stringify_uuid(cls, v):
        if v is not None:
            return str(v)
        return v


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

# Map backend status enum values → frontend-friendly lowercase strings
_MESSAGE_STATUS_MAP: Dict[str, str] = {
    MessageStatusEnum.PENDING: "pending",
    MessageStatusEnum.SUCCESS: "completed",
    MessageStatusEnum.ERROR: "failed",
}


class Message(Base):
    conversation_id: UUID
    content: str
    role: MessageRoleEnum
    status: MessageStatusEnum
    sub_processes: List[MessageSubProcess]
    sources: List[MessageSource] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def _normalise_status(cls, v):
        """Accept both the raw DB enum and plain string values."""
        return v


# ---------------------------------------------------------------------------
# NSE / Indian Financial Document Metadata
# ---------------------------------------------------------------------------


class DocumentMetadataKeysEnum(str, Enum):
    """
    Enum for the top-level keys of the metadata_map JSONB column for a document.
    """

    NSE_DOCUMENT = "nse_document"


class NSEDocumentTypeEnum(str, Enum):
    """
    Type of Indian / NSE financial document.
    """

    ANNUAL_REPORT = "annual_report"
    FINANCIAL_RESULTS = "financial_results"
    CORPORATE_FILING = "corporate_filing"
    INVESTOR_PRESENTATION = "investor_presentation"
    OTHER = "other"


class NSEDocumentMetadata(BaseModel):
    """
    Metadata for an Indian / NSE financial document.

    All fields except company_name are optional so that users can upload PDFs
    with minimal information.
    """

    company_name: str
    company_symbol: Optional[str] = None
    document_type: NSEDocumentTypeEnum = NSEDocumentTypeEnum.ANNUAL_REPORT
    financial_year: Optional[str] = None
    report_date: Optional[datetime] = None
    exchange: str = "NSE"
    original_filename: Optional[str] = None


DocumentMetadataMap = Dict[Union[DocumentMetadataKeysEnum, str], Any]


# ---------------------------------------------------------------------------
# Legacy Document schema (kept for internal use / backward compat)
# ---------------------------------------------------------------------------


class Document(Base):
    url: str
    metadata_map: Optional[DocumentMetadataMap] = None
    # Promoted columns (may be None for pre-migration rows)
    filename: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    company_name: Optional[str] = None
    company_symbol: Optional[str] = None
    exchange: Optional[str] = None
    document_type: Optional[str] = None
    financial_year: Optional[str] = None
    report_date: Optional[str] = None
    pages: Optional[int] = None
    file_size: Optional[int] = None
    language: Optional[str] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# FinDocumentMetadata — flattened metadata matching frontend DocumentMetadata
# ---------------------------------------------------------------------------


class FinDocumentMetadata(BaseModel):
    company_name: str = ""
    nse_symbol: Optional[str] = None
    document_type: Optional[str] = None
    fiscal_year: Optional[str] = None
    period: Optional[str] = None
    pages: Optional[int] = None
    file_size: Optional[int] = None
    language: Optional[str] = None


# ---------------------------------------------------------------------------
# FinDocumentSchema — product-facing Document schema matching frontend FinDocument
# ---------------------------------------------------------------------------


class FinDocumentSchema(BaseModel):
    """
    Product-facing document schema. Matches the frontend FinDocument type exactly.

    Promoted columns are read directly from the DB row. For legacy rows that
    only have metadata_map, the fallback logic in from_db_document() extracts
    the same information from metadata_map["nse_document"].
    """

    id: Optional[UUID] = None
    filename: str = ""
    status: str = DocumentStatusEnum.ready.value
    progress: int = 100
    metadata: FinDocumentMetadata = Field(default_factory=FinDocumentMetadata)
    uploaded_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Keep storage URL accessible for internal use
    url: Optional[str] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_db_document(cls, doc: "Document") -> "FinDocumentSchema":
        """
        Build a FinDocumentSchema from a Document (legacy or promoted-column row).

        Priority:
          1. Promoted columns (new rows)
          2. metadata_map["nse_document"] (legacy rows)
          3. Defaults
        """
        # --- Resolve basic fields ---
        filename = doc.filename
        status = doc.status or DocumentStatusEnum.ready.value
        progress = doc.progress if doc.progress is not None else 100

        # --- Resolve financial metadata ---
        company_name = doc.company_name
        company_symbol = doc.company_symbol
        document_type = doc.document_type
        financial_year = doc.financial_year
        pages = doc.pages
        file_size = doc.file_size
        language = doc.language

        # Fallback to metadata_map["nse_document"] for legacy rows
        nse_meta: Dict[str, Any] = {}
        if doc.metadata_map and DocumentMetadataKeysEnum.NSE_DOCUMENT in doc.metadata_map:
            nse_meta = doc.metadata_map[DocumentMetadataKeysEnum.NSE_DOCUMENT] or {}

        if not filename:
            filename = (
                nse_meta.get("original_filename")
                or (doc.url.split("/")[-1] if doc.url else "document.pdf")
            )
        if not company_name:
            company_name = nse_meta.get("company_name", "")
        if not company_symbol:
            company_symbol = nse_meta.get("company_symbol")
        if not document_type:
            document_type = nse_meta.get("document_type")
        if not financial_year:
            financial_year = nse_meta.get("financial_year")

        metadata = FinDocumentMetadata(
            company_name=company_name or "",
            nse_symbol=company_symbol,
            document_type=document_type,
            fiscal_year=financial_year,
            pages=pages,
            file_size=file_size,
            language=language or "en",
        )

        return cls(
            id=doc.id,
            filename=filename,
            status=status,
            progress=progress,
            metadata=metadata,
            uploaded_at=doc.created_at,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            url=doc.url,
        )


# ---------------------------------------------------------------------------
# DocumentUploadResponse — now wraps FinDocumentSchema
# ---------------------------------------------------------------------------


class DocumentUploadResponse(BaseModel):
    """
    Response returned after a successful document upload and indexing.
    Matches the frontend DocumentUploadResponse type: { document: FinDocument }
    """

    document: FinDocumentSchema


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class Conversation(Base):
    title: Optional[str] = None
    messages: List[Message]
    documents: List[Document]
    # document_scope: list of document IDs for this conversation
    document_scope: List[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_document_scope(self) -> "Conversation":
        if not self.document_scope and self.documents:
            self.document_scope = [doc.id for doc in self.documents if doc.id]
        return self


class ConversationCreate(BaseModel):
    """
    Create a new conversation.

    Accepts both old `document_ids` (internal) and new `document_scope`
    (frontend-facing). If both are supplied, document_scope takes precedence.
    Accepts an optional `title`; if omitted, one is auto-generated.
    """

    title: Optional[str] = None
    document_ids: Optional[List[UUID]] = Field(default=None, exclude=True)
    document_scope: Optional[List[UUID]] = None

    @model_validator(mode="after")
    def _resolve_document_ids(self) -> "ConversationCreate":
        """Unify document_scope and document_ids into document_scope."""
        if self.document_scope is None:
            self.document_scope = self.document_ids or []
        return self


class UserMessageCreate(BaseModel):
    content: str
