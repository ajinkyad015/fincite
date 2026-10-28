"""End-to-end engine construction with an arbitrary model id.

Mirrors the reported failure: POST /message → get_chat_engine() →
index.as_query_engine() → get_response_synthesizer(llm.metadata). The old
NVIDIA client produced ``None`` for the two LLMMetadata booleans on ids it
did not know, so this whole chain raised a pydantic ValidationError.

No network, no database, no global LlamaIndex LLM: every stage must receive
the explicitly configured client.
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from llama_index.core import Settings as LlamaSettings
from llama_index.core.response_synthesizers.factory import get_response_synthesizer

from app import schema
from app.chat import engine
from app.core.config import settings
from app.models.db import DocumentStatusEnum


@pytest.mark.asyncio
async def test_chat_engine_builds_with_an_unknown_model_id(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_CHAT_LLM_NAME", "nvidia/nemotron-3.5-bolt-e4b")
    # Make any silent fallback to Settings.llm fail loudly (it would try to
    # resolve the default OpenAI LLM with no OPENAI_API_KEY in tests).
    monkeypatch.setattr(LlamaSettings, "_llm", None, raising=False)

    document = schema.Document(
        id=uuid4(),
        url="https://example.test/a.pdf",
        status=DocumentStatusEnum.ready,
    )
    synth_calls: list = []

    def as_query_engine(**kwargs):
        # The very call from the traceback. It must get a concrete LLM whose
        # metadata validates, not a global default.
        llm = kwargs.get("llm")
        assert llm is not None
        assert llm.model == "nvidia/nemotron-3.5-bolt-e4b"
        assert isinstance(llm.metadata.is_chat_model, bool)
        assert isinstance(llm.metadata.is_function_calling_model, bool)
        synth_calls.append(get_response_synthesizer(llm=llm, structured_answer_filtering=False))
        return MagicMock()

    fake_index = MagicMock()
    fake_index.as_query_engine.side_effect = as_query_engine
    monkeypatch.setattr(
        engine,
        "build_doc_id_to_index_map",
        AsyncMock(return_value={str(document.id): fake_index}),
    )

    conversation = schema.Conversation(
        id=uuid4(), title=None, messages=[], documents=[document]
    )
    chat_engine = await engine.get_chat_engine(MagicMock(), conversation)

    assert type(chat_engine).__name__ == "ReActAgent"
    assert synth_calls, "per-document query engines must have been built"
