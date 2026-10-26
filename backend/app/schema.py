"""
Pydantic Schemas for the API

This module is the single source of truth for API shapes. Anything a client can
see is defined here; endpoints and crud return these objects, never raw models.
"""
import re

from pydantic import BaseModel, Field, field_validator
from enum import Enum
from typing import List, Optional, Dict, Union, Any
from uuid import UUID
from datetime import datetime
from llama_index.core.schema import BaseNode, NodeWithScore
from llama_index.core.callbacks.schema import EventPayload
from llama_index.core.query_engine.sub_question_query_engine import SubQuestionAnswerPair
from app.models.db import (
    DocumentStatusEnum,
    MessageRoleEnum,
    MessageStatusEnum,
    MessageSubProcessSourceEnum,
    MessageSubProcessStatusEnum,
)
from app.chat.constants import DB_DOC_ID_KEY


class Base(BaseModel):
    id: Optional[UUID] = Field(None, description="Unique identifier")
    created_at: Optional[datetime] = Field(None, description="Creation datetime")
    updated_at: Optional[datetime] = Field(None, description="Update datetime")

    model_config = {"from_attributes": True}


class BaseMetadataObject(BaseModel):
    model_config = {"from_attributes": True}


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


class Source(BaseMetadataObject):
    """
    A citation as the UI consumes it (`frontend/src/lib/types.ts` → `Source`).

    Derived from `Citation`s collected out of the research trail, flattened onto
    the message so a client never has to dig through `sub_processes`.
    """

    index: int = Field(..., description="1-based citation number used by the answer text")
    document_id: UUID
    page: int
    excerpt: str
    score: Optional[float] = None

    @property
    def source_id(self) -> str:
        """Stable id for de-duplication: one citation per (document, page, excerpt head)."""
        return f"{self.document_id}:{self.page}:{self.excerpt[:64]}"


def citations_to_sources(citations: List[Citation]) -> List[Source]:
    """
    Flatten citations into de-duplicated, 1-based `Source` objects.

    Order is preserved (first occurrence wins) so citation numbers in the answer
    text line up with the chips the user clicks.
    """
    sources: List[Source] = []
    seen: set[str] = set()
    for citation in citations:
        source = Source(
            index=len(sources) + 1,
            document_id=citation.document_id,
            page=citation.page_number,
            excerpt=citation.text,
            score=citation.score,
        )
        if source.source_id in seen:
            continue
        seen.add(source.source_id)
        sources.append(source)
    return sources


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


class MessageSubProcess(Base):
    message_id: UUID
    source: MessageSubProcessSourceEnum
    status: MessageSubProcessStatusEnum
    name: Optional[str] = Field(
        None, description="Human-readable step label for the research trail"
    )
    duration_ms: Optional[int] = Field(None, description="Wall-clock duration of the step")
    metadata_map: Optional[SubProcessMetadataMap] = None


class Message(Base):
    conversation_id: UUID
    content: str
    role: MessageRoleEnum
    status: MessageStatusEnum
    sub_processes: List[MessageSubProcess] = Field(default_factory=list)
    sources: Optional[List[Source]] = Field(
        None, description="Page-level citations for the answer, citation-number ordered"
    )


class MessageCreate(BaseModel):
    """Body of ``POST /api/conversation/{id}/message`` (the streaming endpoint)."""

    content: str = Field(..., min_length=1, max_length=4000, description="The user's question")


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

    The first group is what the frontend already labels; the second group is the
    older backend vocabulary, kept so existing rows and clients keep working.
    """

    ANNUAL_REPORT = "annual_report"
    QUARTERLY_RESULTS = "quarterly_results"
    CONCALL_TRANSCRIPT = "concall_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    SHAREHOLDING_PATTERN = "shareholding_pattern"
    CORPORATE_ANNOUNCEMENT = "corporate_announcement"
    # Legacy values
    FINANCIAL_RESULTS = "financial_results"
    CORPORATE_FILING = "corporate_filing"
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

    @property
    def fiscal_year(self) -> Optional[str]:
        """Normalised fiscal-year label, e.g. ``FY2024-25``.

        Accepts the shapes clients send in practice: ``2025``, ``FY25``,
        ``2024-25``, ``FY2024-2025``. Returns ``None`` when it cannot tell.
        """
        return normalise_fiscal_year(self.financial_year)


def normalise_fiscal_year(value: Optional[str]) -> Optional[str]:
    """
    Best-effort normalisation of an Indian fiscal-year label.

    ``"2024-25"``, ``"FY2024-2025"``, ``"fy 24-25"`` → ``"FY2024-25"``
    ``"2025"`` → ``"FY2024-25"`` (Indian FY ends in the stated calendar year)
    Anything unrecognised is returned stripped, unchanged.
    """
    if not value:
        return None
    raw = value.strip().upper().replace(" ", "")
    if raw.startswith("FY"):
        raw = raw[2:]
    parts = raw.replace("/", "-").split("-")
    year_re = r"^\d{2,4}$"

    if len(parts) == 2 and all(re.match(year_re, p) for p in parts):
        start, end = parts
        start = start if len(start) == 4 else f"20{start}"
        end = end if len(end) == 4 else start[:2] + end
        return f"FY{start}-{end[2:]}"
    if len(parts) == 1 and re.match(r"^\d{4}$", parts[0]):
        end = int(parts[0])
        return f"FY{end - 1}-{str(end)[2:]}"
    return value.strip()


DocumentMetadataMap = Dict[Union[DocumentMetadataKeysEnum, str], Any]


class Document(Base):
    url: str
    metadata_map: Optional[DocumentMetadataMap] = None

    # Ingestion lifecycle — polled by the library UI. A freshly created row is
    # "uploaded"; only ingestion may promote it to "ready".
    status: DocumentStatusEnum = DocumentStatusEnum.uploaded
    progress: int = Field(0, ge=0, le=100)
    error: Optional[str] = None

    # Denormalised for listing/filtering; nullable for legacy rows.
    page_count: Optional[int] = None
    file_size: Optional[int] = None
    content_hash: Optional[str] = None

    @property
    def nse_metadata(self) -> Optional[NSEDocumentMetadata]:
        """The parsed NSE block from `metadata_map`, if present."""
        if not self.metadata_map:
            return None
        raw = self.metadata_map.get(DocumentMetadataKeysEnum.NSE_DOCUMENT.value) or self.metadata_map.get(
            DocumentMetadataKeysEnum.NSE_DOCUMENT
        )
        if not raw:
            return None
        try:
            return NSEDocumentMetadata.model_validate(raw)
        except Exception:
            return None

    @property
    def company_name(self) -> Optional[str]:
        meta = self.nse_metadata
        return meta.company_name if meta else None

    @property
    def company_symbol(self) -> Optional[str]:
        meta = self.nse_metadata
        return meta.company_symbol if meta else None

    @property
    def document_type(self) -> Optional[NSEDocumentTypeEnum]:
        meta = self.nse_metadata
        return meta.document_type if meta else None

    @property
    def fiscal_year(self) -> Optional[str]:
        meta = self.nse_metadata
        return meta.fiscal_year if meta else None

    @property
    def original_filename(self) -> Optional[str]:
        if self.metadata_map:
            name = self.metadata_map.get("original_filename")
            if name:
                return str(name)
        meta = self.nse_metadata
        return meta.original_filename if meta else None


class DocumentUploadResponse(Base):
    """
    Response returned after a PDF has been accepted for indexing.

    Indexing runs in the background: `status` starts at ``uploaded`` and the
    client polls ``GET /api/document/{id}`` until it reaches ``ready``/``failed``.
    """

    url: str
    metadata_map: Optional[DocumentMetadataMap] = None
    status: DocumentStatusEnum = DocumentStatusEnum.uploaded
    progress: int = 0
    error: Optional[str] = None
    page_count: Optional[int] = None
    file_size: Optional[int] = None
    content_hash: Optional[str] = None


# Kept as an alias so existing internal call sites keep working.
UserMessageCreate = MessageCreate


class Conversation(Base):
    title: Optional[str] = None
    last_message_at: Optional[datetime] = None
    messages: List[Message] = Field(default_factory=list)
    documents: List[Document] = Field(default_factory=list)

    @property
    def document_ids(self) -> List[UUID]:
        return [doc.id for doc in self.documents if doc.id is not None]


class ConversationSummary(BaseModel):
    """A row in the thread list — deliberately without messages."""

    id: UUID
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    document_ids: List[UUID] = Field(default_factory=list)
    preview: Optional[str] = Field(
        None, description="First user message, truncated — the thread-list subtitle"
    )

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    """Create a thread.

    ``document_ids`` is optional: a thread can start empty and be scoped later
    via ``PATCH /api/conversation/{id}``, which is how the UI's "New chat" works.
    """

    document_ids: List[UUID] = Field(default_factory=list)
    title: Optional[str] = Field(None, max_length=200)


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    document_ids: Optional[List[UUID]] = None


class HealthResponse(BaseModel):
    status: str = Field(..., description="healthy | degraded")
    db: bool = Field(..., description="Database answered SELECT 1")
    vector_store: Optional[bool] = Field(
        None, description="Vector store initialised (null when not probed)"
    )
    version: str
    uptime_s: float


class ConfigResponse(BaseModel):
    """Public, non-secret runtime configuration for the client."""

    version: str
    max_upload_mb: int
    supported_content_types: List[str]
    auth_enabled: bool
    demo_mode: bool
