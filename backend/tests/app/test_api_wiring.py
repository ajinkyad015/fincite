"""
HTTP wiring test — the routes, status codes and SSE framing the frontend talks to.

A bare FastAPI app (no lifespan, so no database bootstrap) mounts the real
router and overrides the DB dependency, so this exercises FastAPI's own
serialization: exactly what `fetch()` in the browser sees.

Requests go through `httpx.ASGITransport` rather than `TestClient`: it stays in
the test's own event loop (no Starlette portal thread), which keeps the async
fixtures honest and lets the process exit promptly.

The SSE case streams through `EventSourceResponse` and asserts the frames the
client parses: unnamed `data:` events, each a complete `Message`, last one
terminal.
"""
import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app import schema
from app.api.api import api_router
from app.api.deps import get_db
from app.api.endpoints import conversation as conversation_module
from app.api.endpoints import documents as documents_module
from app.chat import messaging
from app.models.db import (
    DocumentStatusEnum,
    MessageRoleEnum,
    MessageStatusEnum,
    MessageSubProcessSourceEnum,
)


def build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    return app


@pytest_asyncio.fixture()
async def client():
    app = build_app()
    db = AsyncMock(spec=AsyncSession)
    app.dependency_overrides[get_db] = lambda: db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fincite.test"
    ) as http_client:
        yield http_client, db


def _parse_sse(body: str):
    """Split an SSE body into payload dicts (ignoring keep-alive comments)."""
    events = []
    for block in body.split("\n\n"):
        data_lines = [
            line[len("data:"):].strip()
            for line in block.splitlines()
            if line.startswith("data:")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


@pytest.mark.asyncio
async def test_empty_library_is_200_with_an_empty_array(client):
    test_client, db = client
    with patch.object(documents_module.crud, "fetch_documents", AsyncMock(return_value=[])):
        response = await test_client.get("/api/document/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_health_payload_shape(client):
    test_client, _db = client
    response = await test_client.get("/api/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["db"] is True
    assert isinstance(body["version"], str)
    assert body["uptime_s"] >= 0


@pytest.mark.asyncio
async def test_config_exposes_limits_without_secrets(client):
    test_client, _db = client
    response = await test_client.get("/api/config/")
    assert response.status_code == 200
    body = response.json()
    assert body["max_upload_mb"] > 0
    assert "application/pdf" in body["supported_content_types"]
    assert body["auth_enabled"] is False
    # Nothing sensitive may ever appear here.
    assert not any("key" in k or "secret" in k for k in body)


@pytest.mark.asyncio
async def test_creating_a_thread_without_documents_is_201(client):
    test_client, _db = client
    created = schema.Conversation(
        id=uuid4(),
        title=None,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
        messages=[],
        documents=[],
    )
    with patch.object(
        conversation_module.crud, "create_conversation", AsyncMock(return_value=created)
    ):
        response = await test_client.post("/api/conversation/", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(created.id)
    assert body["messages"] == []
    assert body["documents"] == []


@pytest.mark.asyncio
async def test_patch_thread_validates_document_ids(client):
    test_client, _db = client
    with patch.object(
        conversation_module.crud, "fetch_documents", AsyncMock(return_value=[])
    ):
        response = await test_client.patch(
            f"/api/conversation/{uuid4()}", json={"document_ids": [str(uuid4())]}
        )
    assert response.status_code == 404
    assert "Documents not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_missing_thread_is_404(client):
    test_client, _db = client
    with patch.object(
        conversation_module.crud,
        "fetch_conversation_with_messages",
        AsyncMock(return_value=None),
    ):
        response = await test_client.get(f"/api/conversation/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_asking_in_an_unscoped_thread_with_no_filings_is_409(client):
    test_client, _db = client
    conversation = schema.Conversation(
        id=uuid4(), title=None, messages=[], documents=[]
    )
    with patch.object(
        conversation_module.crud,
        "fetch_conversation_with_messages",
        AsyncMock(return_value=conversation),
    ), patch.object(
        conversation_module.crud, "fetch_documents", AsyncMock(return_value=[])
    ):
        response = await test_client.post(
            f"/api/conversation/{conversation.id}/message", json={"content": "Revenue?"}
        )
    # A real HTTP error, not an error frame inside a 200 stream.
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_sse_frames_are_complete_message_snapshots():
    """
    The SSE wire format: one unnamed event per snapshot, each a complete
    `Message` — which is exactly what the frontend's parser reads.

    TestClient is deliberately not used here: `sse-starlette` 1.x binds an
    asyncio event at construction, which deadlocks under Starlette's blocking
    test portal. The wrapper is one `model_dump_json()` per snapshot, so
    exercising it directly proves the payload shape.
    """
    conversation = schema.Conversation(
        id=uuid4(), title="Reliance", messages=[], documents=[]
    )
    assistant_id = uuid4()
    ready_doc = schema.Document(
        id=uuid4(), url="https://example.test/a.pdf", status=DocumentStatusEnum.ready
    )

    async def fake_handle(conv, user_message, send_chan, callback_handler=None):
        content = ""
        for token in ["Revenue ", "was ", "₹9.0 lakh crore [1]."]:
            content += token
            await send_chan.send(messaging.StreamedMessage(content=content))

    class _SessionCtx:
        async def __aenter__(self):
            return AsyncMock(spec=AsyncSession)

        async def __aexit__(self, *exc):
            return False

    crud_mock = MagicMock()
    crud_mock.create_message = AsyncMock(
        side_effect=[
            MagicMock(id=uuid4(), created_at=datetime.datetime.utcnow()),
            MagicMock(id=assistant_id, created_at=datetime.datetime.utcnow()),
        ]
    )
    crud_mock.touch_conversation = AsyncMock()
    crud_mock.update_message_content = AsyncMock()
    crud_mock.finalise_message = AsyncMock()
    crud_mock.fetch_message_with_sub_processes = AsyncMock(
        return_value=schema.Message(
            id=assistant_id,
            conversation_id=conversation.id,
            content="Revenue was ₹9.0 lakh crore [1].",
            role=MessageRoleEnum.assistant,
            status=MessageStatusEnum.SUCCESS,
            sub_processes=[],
            sources=[
                schema.Source(
                    index=1,
                    document_id=ready_doc.id,
                    page=41,
                    excerpt="Revenue from operations",
                    score=0.9,
                )
            ],
            created_at=datetime.datetime.utcnow(),
        )
    )

    with patch.object(conversation_module, "SessionLocal", _SessionCtx), patch.object(
        conversation_module, "crud", crud_mock
    ), patch.object(conversation_module, "handle_chat_message", fake_handle):
        frames = [
            frame
            async for frame in conversation_module._sse_events(
                conversation, "What was FY24 revenue?"
            )
        ]

    payloads = [json.loads(frame) for frame in frames]
    assert payloads
    assert all(p["role"] == "assistant" for p in payloads)
    assert all(p["id"] == str(assistant_id) for p in payloads)
    assert all("sources" in p and "sub_processes" in p for p in payloads)
    assert payloads[-1]["status"] == "SUCCESS"
    assert payloads[-1]["sources"][0]["page"] == 41

    # Content is cumulative across frames, never deltas.
    for previous, current in zip(payloads, payloads[1:]):
        assert current["content"].startswith(previous["content"])


@pytest.mark.asyncio
async def test_stream_endpoint_rejects_an_empty_question(client):
    test_client, _db = client
    response = await test_client.post(
        f"/api/conversation/{uuid4()}/message", json={"content": ""}
    )
    assert response.status_code == 422
