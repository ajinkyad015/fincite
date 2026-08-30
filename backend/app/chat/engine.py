"""
Chat engine construction.

Builds a ReActAgent with per-document RAG query engines powered by Google Gemini.
Documents are retrieved from Supabase Storage and indexed into pgvector.

Flow:
    conversation documents
          ↓
    build_doc_id_to_index_map()
       ↓ (per document)
    fetch PDF from Supabase Storage
       ↓
    PDFReader → LlamaIndex nodes (with DB_DOC_ID_KEY)
       ↓
    VectorStoreIndex (backed by pgvector)
          ↓
    QueryEngineTool (one per document, with MetadataFilter by doc ID)
          ↓
    SubQuestionQueryEngine
          ↓
    ReActAgent (streaming, powered by Gemini)
"""
from typing import Dict, List
import logging
from datetime import datetime
from tempfile import TemporaryDirectory
from pathlib import Path

import nest_asyncio
import requests

from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.vector_stores.types import VectorStore
from llama_index.core.vector_stores.types import MetadataFilters, ExactMatchFilter
from llama_index.core.indices.query.base import BaseQueryEngine
from llama_index.core.schema import Document as LlamaIndexDocument
from llama_index.core.chat_engine.types import ChatMessage
from llama_index.core.callbacks.base import BaseCallbackHandler, CallbackManager
from llama_index.core.tools import QueryEngineTool, ToolMetadata
from llama_index.core.query_engine import SubQuestionQueryEngine
from llama_index.core.agent import ReActAgent
from llama_index.llms.gemini import Gemini
from llama_index.core.base.llms.types import MessageRole

from llama_index.readers.file.docs.base import PDFReader

from app.core.config import settings
from app.schema import (
    Message as MessageSchema,
    Document as DocumentSchema,
    Conversation as ConversationSchema,
)
from app.models.db import MessageRoleEnum, MessageStatusEnum
from app.chat.constants import DB_DOC_ID_KEY, SYSTEM_MESSAGE
from app.chat.utils import build_title_for_document, build_description_for_document
from app.chat.pg_vector import get_vector_store_singleton
from app.chat.qa_response_synth import get_custom_response_synth
from app.storage.supabase import download_document

logger = logging.getLogger(__name__)

logger.info("Applying nested asyncio patch")
nest_asyncio.apply()


def fetch_and_read_document(
    document: DocumentSchema,
) -> List[LlamaIndexDocument]:
    """
    Download a PDF from Supabase Storage (or fall back to HTTP GET of
    document.url if the URL is a direct HTTP link) and parse it with
    LlamaIndex PDFReader.

    Each resulting LlamaIndex Document carries DB_DOC_ID_KEY in its
    metadata so retrieval can be filtered per document.
    """
    with TemporaryDirectory() as temp_dir:
        temp_file_path = Path(temp_dir) / f"{str(document.id)}.pdf"

        try:
            # Primary path: download from Supabase Storage
            pdf_bytes = download_document(str(document.id))
            temp_file_path.write_bytes(pdf_bytes)
        except Exception:
            logger.warning(
                "Could not download document %s from Supabase Storage. "
                "Falling back to HTTP GET of document URL.",
                document.id,
            )
            with requests.get(document.url, stream=True) as r:
                r.raise_for_status()
                with open(temp_file_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

        reader = PDFReader()
        return reader.load_data(
            temp_file_path,
            extra_info={DB_DOC_ID_KEY: str(document.id)},
        )


def index_to_query_engine(doc_id: str, index: VectorStoreIndex) -> BaseQueryEngine:
    """Create a query engine filtered to a single document."""
    filters = MetadataFilters(
        filters=[ExactMatchFilter(key=DB_DOC_ID_KEY, value=doc_id)]
    )
    return index.as_query_engine(similarity_top_k=3, filters=filters)


async def build_doc_id_to_index_map(
    callback_manager: CallbackManager,
    documents: List[DocumentSchema],
) -> Dict[str, VectorStoreIndex]:
    """
    For each document, attempt to load an existing VectorStoreIndex from
    pgvector. If the index is not found (new document), fetch + index the PDF.

    Since pgvector IS the persistent store, we do not need an S3 persist dir.
    """
    vector_store = await get_vector_store_singleton()
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    doc_id_to_index: Dict[str, VectorStoreIndex] = {}
    for doc in documents:
        doc_id = str(doc.id)
        try:
            index = VectorStoreIndex.from_vector_store(
                vector_store=vector_store,
                callback_manager=callback_manager,
            )
            doc_id_to_index[doc_id] = index
            logger.debug("Loaded index for document %s from pgvector.", doc_id)
        except Exception:
            logger.warning(
                "Could not load index for document %s. "
                "Re-indexing from storage.",
                doc_id,
            )
            llama_docs = fetch_and_read_document(doc)
            index = VectorStoreIndex.from_documents(
                llama_docs,
                storage_context=storage_context,
                callback_manager=callback_manager,
            )
            index.set_index_id(doc_id)
            doc_id_to_index[doc_id] = index

    return doc_id_to_index


def get_chat_history(
    chat_messages: List[MessageSchema],
) -> List[ChatMessage]:
    """
    Given a list of chat messages, return a list of ChatMessage instances.

    Failed chat messages are filtered out and then the remaining ones are
    sorted by created_at.
    """
    chat_messages = [
        m
        for m in chat_messages
        if m.content.strip() and m.status == MessageStatusEnum.SUCCESS
    ]
    chat_messages = sorted(chat_messages, key=lambda m: m.created_at)

    chat_history = []
    for message in chat_messages:
        role = (
            MessageRole.ASSISTANT
            if message.role == MessageRoleEnum.assistant
            else MessageRole.USER
        )
        chat_history.append(ChatMessage(content=message.content, role=role))

    return chat_history


async def get_chat_engine(
    callback_handler: BaseCallbackHandler,
    conversation: ConversationSchema,
) -> ReActAgent:
    """
    Build a ReActAgent (powered by Gemini) for a conversation.

    Architecture:
        One QueryEngineTool per selected document (filtered to that doc's vectors)
          ↓
        SubQuestionQueryEngine (decomposes multi-doc questions)
          ↓
        ReActAgent (streaming, with system prompt)
    """
    callback_manager = CallbackManager([callback_handler])
    doc_id_to_index = await build_doc_id_to_index_map(
        callback_manager, conversation.documents
    )
    id_to_doc: Dict[str, DocumentSchema] = {
        str(doc.id): doc for doc in conversation.documents
    }

    # One tool per document, each with a metadata filter for that doc's ID
    vector_query_engine_tools = [
        QueryEngineTool(
            query_engine=index_to_query_engine(doc_id, index),
            metadata=ToolMetadata(
                name=doc_id,
                description=build_description_for_document(id_to_doc[doc_id]),
            ),
        )
        for doc_id, index in doc_id_to_index.items()
    ]

    response_synth = get_custom_response_synth(callback_manager, conversation.documents)

    document_question_engine = SubQuestionQueryEngine.from_defaults(
        query_engine_tools=vector_query_engine_tools,
        response_synthesizer=response_synth,
        verbose=settings.LOG_LEVEL == "DEBUG",
        use_async=True,
    )

    top_level_tools = [
        QueryEngineTool(
            query_engine=document_question_engine,
            metadata=ToolMetadata(
                name="document_question_engine",
                description=(
                    "A query engine that answers questions about the Indian financial "
                    "documents (annual reports, NSE filings, investor presentations) "
                    "that the user has selected for this conversation. "
                    "Use this for ALL questions — financial metrics, risk factors, "
                    "management commentary, governance, ESG, and cross-document comparisons."
                ),
            ),
        ),
    ]

    chat_llm = Gemini(
        model=settings.GEMINI_CHAT_LLM_NAME,
        api_key=settings.GOOGLE_API_KEY,
    )
    chat_history = get_chat_history(conversation.messages)
    logger.debug("Chat history: %s", chat_history)

    if conversation.documents:
        doc_titles = "\n".join(
            "- " + build_title_for_document(doc) for doc in conversation.documents
        )
    else:
        doc_titles = "No documents selected."

    curr_date = datetime.utcnow().strftime("%Y-%m-%d")
    chat_engine = ReActAgent.from_tools(
        tools=top_level_tools,
        llm=chat_llm,
        chat_history=chat_history,
        verbose=settings.LOG_LEVEL == "DEBUG",
        context=SYSTEM_MESSAGE.format(doc_titles=doc_titles, curr_date=curr_date),
        callback_manager=callback_manager,
        max_iterations=6,
    )

    return chat_engine
