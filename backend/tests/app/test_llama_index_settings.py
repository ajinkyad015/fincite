"""
NVIDIA provider wiring (app/llama_index_settings.py).

No network: constructing the catalog-known default chat model performs no
I/O in llama-index-llms-nvidia, and the embedding client's transport is
replaced with a fake that records the request payloads. If construction
ever starts calling the live API, these tests fail loudly offline.
"""
import asyncio
from types import SimpleNamespace

from llama_index.llms.nvidia import NVIDIA
from llama_index.embeddings.nvidia import NVIDIAEmbedding

from app.core.config import settings
from app.llama_index_settings import (
    _NVIDIAEmbedding,
    _setup_llama_index_settings,
    get_chat_llm,
    get_embed_model,
)


def test_chat_llm_is_nvidia_with_configured_model_and_limits():
    llm = get_chat_llm()

    assert isinstance(llm, NVIDIA)
    assert llm.model == settings.NVIDIA_CHAT_LLM_NAME
    assert llm.api_base.rstrip("/") == settings.NVIDIA_BASE_URL.rstrip("/")
    # The OpenAILike defaults (3900 / 1024) must not leak through: the
    # synthesizer sizes its context from this metadata and answers would be
    # truncated at the upstream reply cap.
    assert llm.metadata.context_window == settings.NVIDIA_CHAT_CONTEXT_WINDOW
    assert llm.metadata.num_output == settings.NVIDIA_CHAT_MAX_TOKENS
    assert llm.metadata.is_chat_model is True


def test_embed_model_is_nvidia_with_configured_model():
    embed_model = get_embed_model()

    assert isinstance(embed_model, NVIDIAEmbedding)
    assert embed_model.model == settings.NVIDIA_EMBEDDING_MODEL_NAME
    assert embed_model.base_url.rstrip("/") == settings.NVIDIA_BASE_URL.rstrip("/")
    assert embed_model.truncate == "END"
    # Native dimension only: sending `dimensions` would 400 on this model,
    # and VECTOR_STORE_EMBED_DIM must be its native output size.
    assert not embed_model.dimensions
    assert settings.VECTOR_STORE_EMBED_DIM == 2048


def _fake_embeddings_client(calls: list):
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in kwargs["input"]]
        )

    return SimpleNamespace(embeddings=SimpleNamespace(create=create))


def test_sync_embeddings_use_passage_for_texts_and_query_for_queries():
    """Regression test for the llama-index-embeddings-nvidia 0.3.4 bug where
    the sync query path also sent input_type="passage" (see _NVIDIAEmbedding).
    """
    embed_model = get_embed_model()
    assert isinstance(embed_model, _NVIDIAEmbedding)

    calls: list = []
    embed_model._client = _fake_embeddings_client(calls)

    assert embed_model._get_text_embedding("a chunk of an annual report") == [0.1, 0.2]
    assert embed_model._get_query_embedding("what was FY2025 revenue?") == [0.1, 0.2]

    assert calls[0]["extra_body"]["input_type"] == "passage"
    assert calls[1]["extra_body"]["input_type"] == "query"
    assert all(c["extra_body"]["truncate"] == "END" for c in calls)
    assert all(c["model"] == settings.NVIDIA_EMBEDDING_MODEL_NAME for c in calls)


def test_async_query_embedding_uses_query_input_type():
    embed_model = get_embed_model()
    calls: list = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.3, 0.4])])

    embed_model._aclient = SimpleNamespace(
        embeddings=SimpleNamespace(create=create)
    )

    assert asyncio.run(embed_model._aget_query_embedding("revenue?")) == [0.3, 0.4]
    assert calls[0]["extra_body"]["input_type"] == "query"


def test_setup_llama_index_settings_registers_nvidia_clients():
    configured = _setup_llama_index_settings()

    assert isinstance(configured.llm, NVIDIA)
    assert isinstance(configured.embed_model, NVIDIAEmbedding)
