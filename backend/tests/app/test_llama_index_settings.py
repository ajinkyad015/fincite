"""Provider wiring (app/llama_index_settings.py).

Regression coverage for the chat failure with newer model ids: the old
NVIDIA client inferred LLMMetadata booleans from a frozen model table and
produced ``None`` for ids it did not know, so ``get_response_synthesizer()``
raised a pydantic ValidationError while the query engine was being built.
Construction here is offline: no catalog lookups, no API keys in tests.
"""
import asyncio
import warnings
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from llama_index.core.callbacks import CallbackManager
from llama_index.core.response_synthesizers.factory import get_response_synthesizer
from llama_index.embeddings.nvidia import NVIDIAEmbedding
from llama_index.llms.openai.base import OpenAI
from llama_index.llms.openai_like import OpenAILike
from pydantic import ValidationError

from app.chat.qa_response_synth import get_custom_response_synth
from app.core.config import Settings, settings
from app.llama_index_settings import (
    _NVIDIAEmbedding,
    _setup_llama_index_settings,
    get_chat_llm,
    get_embed_model,
)


def test_chat_llm_is_openai_compatible_with_configured_model_and_limits():
    llm = get_chat_llm()

    assert isinstance(llm, OpenAILike)
    assert llm.model == settings.NVIDIA_CHAT_LLM_NAME
    assert llm.api_base.rstrip("/") == settings.NVIDIA_BASE_URL.rstrip("/")
    # OpenAILike's defaults (3900 / 1024 / non-chat) must not leak through:
    # the synthesizer sizes its context from this metadata.
    assert llm.metadata.context_window == settings.NVIDIA_CHAT_CONTEXT_WINDOW
    assert llm.metadata.num_output == settings.NVIDIA_CHAT_MAX_TOKENS
    assert llm.metadata.is_chat_model is settings.NVIDIA_CHAT_IS_CHAT_MODEL
    assert (
        llm.metadata.is_function_calling_model
        is settings.NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL
    )


def test_any_model_id_works_and_metadata_comes_from_env(monkeypatch):
    """The whole point: swap models in .env, no code/known-model table."""
    monkeypatch.setattr(settings, "NVIDIA_CHAT_LLM_NAME", "nvidia/nemotron-3.5-bolt-e4b")
    monkeypatch.setattr(settings, "NVIDIA_CHAT_IS_CHAT_MODEL", True)
    monkeypatch.setattr(settings, "NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL", True)
    monkeypatch.setattr(settings, "NVIDIA_CHAT_CONTEXT_WINDOW", 32768)
    monkeypatch.setattr(settings, "NVIDIA_CHAT_MAX_TOKENS", 2048)

    # A client request here would mean a catalog lookup / network on
    # construction — that was the old NVIDIA client's behaviour.
    with patch.object(
        OpenAI, "_get_client", side_effect=AssertionError("network at construction")
    ):
        llm = get_chat_llm()

    assert llm.model == "nvidia/nemotron-3.5-bolt-e4b"
    assert llm.metadata.is_chat_model is True
    assert llm.metadata.is_function_calling_model is True
    assert llm.metadata.context_window == 32768
    assert llm.metadata.num_output == 2048
    assert llm.metadata.model_name == "nvidia/nemotron-3.5-bolt-e4b"


def test_response_synthesizer_and_custom_synth_accept_the_configured_llm():
    """Reproduces the reported LLMMetadata ValidationError call chain."""
    llm = get_chat_llm()

    assert get_response_synthesizer(llm=llm, structured_answer_filtering=False)
    assert get_custom_response_synth(CallbackManager([]), [], llm=llm)


def test_embed_model_is_nvidia_with_configured_model():
    embed_model = get_embed_model()

    assert isinstance(embed_model, NVIDIAEmbedding)
    assert isinstance(embed_model, _NVIDIAEmbedding)
    assert embed_model.model == settings.NVIDIA_EMBEDDING_MODEL_NAME
    assert embed_model.base_url.rstrip("/") == settings.NVIDIA_BASE_URL.rstrip("/")
    assert embed_model.truncate == settings.NVIDIA_EMBEDDING_TRUNCATE
    # Native dimension only by default: VECTOR_STORE_EMBED_DIM must match it.
    assert not embed_model.dimensions
    assert settings.VECTOR_STORE_EMBED_DIM == 2048


def test_embed_model_accepts_an_unknown_model_id_without_warnings(monkeypatch):
    """No frozen catalog validation, so arbitrary ids work silently."""
    monkeypatch.setattr(settings, "NVIDIA_EMBEDDING_MODEL_NAME", "my-org/my-embed-2k")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        embed_model = get_embed_model()

    assert embed_model.model == "my-org/my-embed-2k"
    assert not [w for w in caught if "determine validity" in str(w.message)]


def _fake_embeddings_client(calls: list):
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in kwargs["input"]]
        )

    return SimpleNamespace(embeddings=SimpleNamespace(create=create))


def test_sync_embeddings_use_passage_for_texts_and_query_for_queries():
    """All request paths go through one query/passage switch (0.3.4 bug)."""
    embed_model = get_embed_model()
    calls: list = []
    embed_model._client = _fake_embeddings_client(calls)

    assert embed_model._get_text_embedding("a chunk of an annual report") == [0.1, 0.2]
    assert embed_model._get_text_embeddings(["chunk A", "chunk B"]) == [
        [0.1, 0.2],
        [0.1, 0.2],
    ]
    assert embed_model._get_query_embedding("what was FY2025 revenue?") == [0.1, 0.2]

    assert [c["extra_body"]["input_type"] for c in calls] == [
        "passage",
        "passage",
        "query",
    ]
    assert all(c["extra_body"]["truncate"] == settings.NVIDIA_EMBEDDING_TRUNCATE for c in calls)
    assert all(c["model"] == settings.NVIDIA_EMBEDDING_MODEL_NAME for c in calls)


def test_async_embeddings_keep_query_vs_passage_input_types():
    embed_model = get_embed_model()
    calls: list = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.3, 0.4]) for _ in kwargs["input"]]
        )

    embed_model._aclient = SimpleNamespace(embeddings=SimpleNamespace(create=create))

    assert asyncio.run(embed_model._aget_query_embedding("revenue?")) == [0.3, 0.4]
    assert asyncio.run(embed_model._aget_text_embedding("a passage")) == [0.3, 0.4]
    assert asyncio.run(embed_model._aget_text_embeddings(["a", "b"])) == [
        [0.3, 0.4],
        [0.3, 0.4],
    ]

    assert [c["extra_body"]["input_type"] for c in calls] == [
        "query",
        "passage",
        "passage",
    ]


def test_openai_style_requests_omit_nim_only_fields_and_can_set_dimensions(monkeypatch):
    """A different embedding provider is a config change, not a code change."""
    monkeypatch.setattr(settings, "NVIDIA_EMBEDDING_REQUEST_STYLE", "openai")
    monkeypatch.setattr(settings, "NVIDIA_EMBEDDING_DIMENSIONS", 2048)

    embed_model = get_embed_model()
    calls: list = []
    embed_model._client = _fake_embeddings_client(calls)

    embed_model._get_query_embedding("revenue?")
    assert calls[0]["extra_body"] == {"dimensions": 2048}

    # No dimensions requested → the model's native size is used.
    monkeypatch.setattr(settings, "NVIDIA_EMBEDDING_DIMENSIONS", None)
    embed_model = get_embed_model()
    embed_model._client = _fake_embeddings_client(calls)
    embed_model._get_query_embedding("revenue?")
    assert calls[-1]["extra_body"] == {}


def test_setup_llama_index_settings_registers_configured_clients():
    configured = _setup_llama_index_settings()

    assert isinstance(configured.llm, OpenAILike)
    assert isinstance(configured.embed_model, NVIDIAEmbedding)


# ---------------------------------------------------------------------------
# Config validation — a bad "model profile" should fail at boot, not mid-chat.
# ---------------------------------------------------------------------------


def test_settings_reject_mismatched_embedding_dimensions():
    with pytest.raises(ValidationError, match="NVIDIA_EMBEDDING_DIMENSIONS"):
        Settings(NVIDIA_EMBEDDING_DIMENSIONS=1024)


def test_settings_reject_blank_model_ids():
    with pytest.raises(ValidationError):
        Settings(NVIDIA_CHAT_LLM_NAME="   ")


def test_settings_normalise_base_url_trailing_slash():
    assert (
        Settings(NVIDIA_BASE_URL="https://example.test/v1/").NVIDIA_BASE_URL
        == "https://example.test/v1"
    )
