"""Model construction for OpenAI-compatible providers.

Single construction site for the two clients used everywhere (global
``Settings`` at startup, and the per-conversation agent in ``app.chat.engine``)
so model ids / key / endpoint / capabilities can never drift between them.

Nothing in this module knows a specific model. Ids, endpoint and the model's
*declared capabilities* all come from ``app.core.config.Settings`` (env /
``.env``); changing models is a config change, never a code change.

Chat — ``llama_index.llms.openai_like.OpenAILike``
    A plain OpenAI-compatible chat client. We deliberately do **not** use
    ``llama_index.llms.nvidia.NVIDIA``: that client derives
    ``is_chat_model`` / ``is_function_calling_model`` from a frozen, hardcoded
    model table and sets both to ``None`` for newer ids (e.g.
    ``nvidia/nemotron-3.5-bolt-e4b``). ``LLMMetadata`` requires booleans, so
    ``get_response_synthesizer()`` — called by ``index.as_query_engine()`` —
    died with a pydantic ValidationError while the chat engine was being
    built. That client also ran a blocking ``GET /v1/models`` lookup for ids
    outside its table. OpenAILike takes the same metadata as explicit config,
    does no catalog I/O, and works with any /v1-compatible endpoint (hosted
    NVIDIA NIM, self-hosted NIM, vLLM, gateways, ...).

Embeddings — ``_NVIDIAEmbedding``
    A thin, config-driven wrapper around
    ``llama_index.embeddings.nvidia.NVIDIAEmbedding``. All request builders
    are overridden so that:
      * ``input_type`` (passage while indexing, query while searching) and
        ``truncate`` are sent only for NIM-style endpoints
        (``NVIDIA_EMBEDDING_REQUEST_STYLE=nim``); plain OpenAI-style endpoints
        get a clean request (``openai``),
      * an optional ``dimensions`` override reaches every sync/async path,
      * the pinned client's known-model validation (warning + endpoint
        rewrite for unknown ids) is skipped — arbitrary model ids just work,
      * the 0.3.4 sync-query bug (questions embedded as ``passage``) cannot
        recur, because there is a single query/passage switch for all paths.
"""
import logging
from typing import Any, Dict, List

from llama_index.core import Settings
from llama_index.core.settings import _Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.nvidia import NVIDIAEmbedding

from app.core.config import settings
from app.chat.constants import (
    NODE_PARSER_CHUNK_OVERLAP,
    NODE_PARSER_CHUNK_SIZE,
)

logger = logging.getLogger(__name__)

_PASSAGE = "passage"
_QUERY = "query"


def _base_url() -> str:
    """Canonical endpoint for both clients (OpenAI SDK appends the path)."""
    return settings.NVIDIA_BASE_URL.rstrip("/")


def get_chat_llm() -> OpenAILike:
    """Build the chat LLM (ReAct brain, question-gen, synthesis).

    Network-free: no model catalog lookup, so this is safe to call on the
    event loop as well as from the startup thread.
    """
    return OpenAILike(
        model=settings.NVIDIA_CHAT_LLM_NAME,
        api_key=settings.NVIDIA_API_KEY,
        api_base=_base_url(),
        # Explicit booleans: LLMMetadata rejects None. Do not let a client
        # "infer" these from a model-name table — see module docstring.
        is_chat_model=settings.NVIDIA_CHAT_IS_CHAT_MODEL,
        is_function_calling_model=settings.NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL,
        # OpenAILike's defaults (3900-token window, non-chat, 1024-token
        # reply cap) would starve synthesis and truncate answers. Every one of
        # these is env-driven, so any model can be dropped in.
        context_window=settings.NVIDIA_CHAT_CONTEXT_WINDOW,
        max_tokens=settings.NVIDIA_CHAT_MAX_TOKENS,
        timeout=settings.NVIDIA_CHAT_TIMEOUT,
    )


class _NVIDIAEmbedding(NVIDIAEmbedding):
    """NVIDIA/openai-compatible embeddings with config-driven request shape."""

    def _validate_model(self, model_name: str) -> None:
        """Skip the pinned client's frozen model table.

        It warns for every id it does not know and can silently rewrite the
        endpoint from its table. Our ids come from env and the endpoint is
        ours to choose, so validation must not touch either.
        """
        return None

    def _extra_body(self, input_type: str) -> Dict[str, Any]:
        """Extra request fields for the configured provider flavour."""
        body: Dict[str, Any] = {}
        if settings.NVIDIA_EMBEDDING_REQUEST_STYLE == "nim":
            body["input_type"] = input_type
            body["truncate"] = self.truncate
        if self.dimensions:
            body["dimensions"] = self.dimensions
        return body

    def _create(self, client: Any, texts: List[str], input_type: str) -> List[List[float]]:
        response = client.embeddings.create(
            input=texts,
            model=self.model,
            extra_body=self._extra_body(input_type),
        )
        return [item.embedding for item in response.data]

    async def _acreate(
        self, client: Any, texts: List[str], input_type: str
    ) -> List[List[float]]:
        response = await client.embeddings.create(
            input=texts,
            model=self.model,
            extra_body=self._extra_body(input_type),
        )
        return [item.embedding for item in response.data]

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._create(self._client, [query], _QUERY)[0]

    def _get_text_embedding(self, text: str) -> List[float]:
        return self._create(self._client, [text], _PASSAGE)[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        assert len(texts) <= 259, "The batch size should not be larger than 259."
        return self._create(self._client, texts, _PASSAGE)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return (await self._acreate(self._aclient, [query], _QUERY))[0]

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return (await self._acreate(self._aclient, [text], _PASSAGE))[0]

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        assert len(texts) <= 259, "The batch size should not be larger than 259."
        return await self._acreate(self._aclient, texts, _PASSAGE)


def get_embed_model() -> NVIDIAEmbedding:
    """Build the embedding model used for both indexing and retrieval."""
    return _NVIDIAEmbedding(
        model=settings.NVIDIA_EMBEDDING_MODEL_NAME,
        api_key=settings.NVIDIA_API_KEY,
        base_url=_base_url(),
        # Chunks are ~512 tokens against a multi-thousand-token model limit,
        # so this should never bite; "END" turns a pathological chunk into a
        # truncated embedding instead of a failed ingestion. Ignored entirely
        # when NVIDIA_EMBEDDING_REQUEST_STYLE=openai.
        truncate=settings.NVIDIA_EMBEDDING_TRUNCATE,
        # None = the model's native output size, which must equal
        # VECTOR_STORE_EMBED_DIM. Setting a reduced size is validated against
        # the vector store dimension in core/config.py.
        dimensions=settings.NVIDIA_EMBEDDING_DIMENSIONS,
    )


def _setup_llama_index_settings() -> _Settings:
    """Register the configured clients as LlamaIndex global defaults."""
    Settings.llm = get_chat_llm()
    Settings.embed_model = get_embed_model()
    Settings.node_parser = SentenceSplitter(
        chunk_size=NODE_PARSER_CHUNK_SIZE,
        chunk_overlap=NODE_PARSER_CHUNK_OVERLAP,
    )
    logger.info(
        "Models configured — chat=%s (chat=%s, tools=%s, ctx=%s, max_out=%s, "
        "timeout=%ss), embeddings=%s (style=%s, truncate=%s, dim=%s), endpoint=%s",
        settings.NVIDIA_CHAT_LLM_NAME,
        settings.NVIDIA_CHAT_IS_CHAT_MODEL,
        settings.NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL,
        settings.NVIDIA_CHAT_CONTEXT_WINDOW,
        settings.NVIDIA_CHAT_MAX_TOKENS,
        settings.NVIDIA_CHAT_TIMEOUT,
        settings.NVIDIA_EMBEDDING_MODEL_NAME,
        settings.NVIDIA_EMBEDDING_REQUEST_STYLE,
        settings.NVIDIA_EMBEDDING_TRUNCATE,
        settings.NVIDIA_EMBEDDING_DIMENSIONS or settings.VECTOR_STORE_EMBED_DIM,
        _base_url(),
    )
    return Settings
