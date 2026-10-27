"""
LlamaIndex model construction (NVIDIA / build.nvidia.com).

Single construction site for the two hosted-NIM clients used everywhere:

* chat — ``llama_index.llms.nvidia.NVIDIA`` (an OpenAI-compatible client
  pointed at https://integrate.api.nvidia.com/v1, the API build.nvidia.com
  documents for every catalog model). Powers the ReAct agent, sub-question
  generation, and response synthesis (via ``Settings.llm``).
* embeddings — ``llama_index.embeddings.nvidia.NVIDIAEmbedding``, which adds
  the two NIM-specific request fields the OpenAI schema does not know:
  ``input_type`` (``passage`` while indexing, ``query`` while searching —
  asymmetric models lose significant retrieval accuracy if this is wrong)
  and ``truncate`` (server-side handling of over-long inputs).

Both ``_setup_llama_index_settings()`` (global ``Settings``, at startup) and
the per-conversation agent in ``app.chat.engine`` build their clients here,
so the model / key / endpoint can never drift between them.
"""
from typing import List

from llama_index.core import Settings
from llama_index.core.settings import _Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.llms.nvidia import NVIDIA
from llama_index.embeddings.nvidia import NVIDIAEmbedding

from app.core.config import settings
from app.chat.constants import (
    NODE_PARSER_CHUNK_OVERLAP,
    NODE_PARSER_CHUNK_SIZE,
)


class _NVIDIAEmbedding(NVIDIAEmbedding):
    """NVIDIAEmbedding with 0.3.4's synchronous query-side bug fixed.

    In llama-index-embeddings-nvidia 0.3.4 (the last release compatible with
    our llama-index-core pin), ``_get_query_embedding`` sends
    ``input_type="passage"`` — the async variant correctly sends ``"query"``.
    Indexing (passages) runs synchronously in a worker thread while chat
    retrieval is async, so today only sync callers (scripts, any future sync
    query path) would embed questions as passages and silently degrade
    retrieval. Re-check on upgrade and drop this subclass once upstream
    agrees with itself.
    """

    def _get_query_embedding(self, query: str) -> List[float]:
        extra_body = {"input_type": "query", "truncate": self.truncate}
        if self.dimensions:
            extra_body["dimensions"] = self.dimensions
        return (
            self._client.embeddings.create(
                input=[query],
                model=self.model,
                extra_body=extra_body,
            )
            .data[0]
            .embedding
        )


def get_chat_llm() -> NVIDIA:
    """Build the chat LLM (ReAct brain, question-gen, synthesis)."""
    return NVIDIA(
        model=settings.NVIDIA_CHAT_LLM_NAME,
        api_key=settings.NVIDIA_API_KEY,
        # The trailing slash is load-bearing: this client decides "hosted
        # catalog vs self-hosted NIM" by exact string match against its own
        # BASE_URL ("…/v1/"), and the self-hosted branch validates the model
        # with a live GET /v1/models. Normalising here keeps construction
        # network-free for catalog models however the env var was written.
        # (The embeddings client below defines its BASE_URL *without* the
        # slash, hence the opposite normalisation there.)
        base_url=settings.NVIDIA_BASE_URL.rstrip("/") + "/",
        max_tokens=settings.NVIDIA_CHAT_MAX_TOKENS,
        # OpenAILike defaults (3900-token window, non-chat) would cripple
        # synthesis over retrieved chunks; declare the real model shape.
        # (Function-calling support is taken from the client's known-model
        # table — ReAct here is prompt-based, so nothing depends on it.)
        context_window=settings.NVIDIA_CHAT_CONTEXT_WINDOW,
        is_chat_model=True,
    )


def get_embed_model() -> NVIDIAEmbedding:
    """Build the embedding model used for both indexing and retrieval."""
    return _NVIDIAEmbedding(
        model=settings.NVIDIA_EMBEDDING_MODEL_NAME,
        api_key=settings.NVIDIA_API_KEY,
        # No trailing slash — see get_chat_llm(); this client's hosted
        # BASE_URL is "…/v1". It will warn "Unable to determine validity of
        # nvidia/nemotron-3-embed-1b" once per process: the model postdates
        # this (core-0.12-era) client's known-model table, which is a
        # warning there, not an error.
        base_url=settings.NVIDIA_BASE_URL.rstrip("/"),
        # Chunks are ~512 tokens against a 4096-token model limit, so this
        # should never bite; "END" turns a pathological chunk into a
        # truncated embedding instead of a failed ingestion.
        truncate="END",
        # No `dimensions`: the default model only serves its native 2048
        # (== VECTOR_STORE_EMBED_DIM) and rejects reduced sizes.
    )


def _setup_llama_index_settings() -> _Settings:
    Settings.llm = get_chat_llm()
    Settings.embed_model = get_embed_model()
    Settings.node_parser = SentenceSplitter(
        chunk_size=NODE_PARSER_CHUNK_SIZE,
        chunk_overlap=NODE_PARSER_CHUNK_OVERLAP,
    )
    return Settings
