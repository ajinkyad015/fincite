"""
Pydantic Schemas for the API
"""
from pydantic import BaseModel, Field, field_validator
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
    metadata_map: Optional[SubProcessMetadataMap] = None


class Message(Base):
    conversation_id: UUID
    content: str
    role: MessageRoleEnum
    status: MessageStatusEnum
    sub_processes: List[MessageSubProcess]


class UserMessageCreate(BaseModel):
    content: str


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


class Document(Base):
    url: str
    metadata_map: Optional[DocumentMetadataMap] = None


class DocumentUploadResponse(Base):
    """
    Response returned after a successful document upload and indexing.
    """

    url: str
    metadata_map: Optional[DocumentMetadataMap] = None
    status: str = "indexed"


class Conversation(Base):
    messages: List[Message]
    documents: List[Document]


class ConversationCreate(BaseModel):
    document_ids: List[UUID]
