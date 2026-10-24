# API REFERENCE — fincitee

Base URL: `http://localhost:8000` (dev) · Prefix: **`/api`** (`settings.API_PREFIX`) ·
Interactive docs: `/api/docs` (Swagger), `/api/redoc`, spec at `/api/openapi.json`.

All handlers are `async def` and take `db: AsyncSession = Depends(get_db)` unless noted.
Response models come from `app/schema.py`. There is **no authentication** on any route.

Route table verified by enumerating the live `app` object:

```
GET    /api/openapi.json              GET /api/docs            GET /api/redoc
POST   /api/conversation/             GET /api/conversation/{conversation_id}
DELETE /api/conversation/{conversation_id}
GET    /api/conversation/{conversation_id}/message
GET    /api/conversation/{conversation_id}/test_message
POST   /api/document/upload           GET /api/document/       GET /api/document/{document_id}
GET    /api/health/
```

Note the **trailing slashes** on collection routes (`/api/conversation/`, `/api/document/`,
`/api/health/`); FastAPI's default `redirect_slashes` will 307 the slashless variant.

---

## 1. Health

### `GET /api/health/`
`app/api/endpoints/health.py:11` · no auth · no schema

Executes `SELECT 1` through the request session, then:

```json
{"status": "alive"}
```

| Status | When |
|---|---|
| 200 | DB reachable |
| 500 | DB unreachable (the SQLAlchemy exception escapes — no handler) |

The frontend polls this every 25 s (`App.tsx:29`) and renders the dot in `Sidebar`; a failure is
treated as `{"status":"down"}` client-side. The UI expects a `healthy` value, which this endpoint
never returns — see `AGENTS.md §14.K`.

---

## 2. Documents

### `POST /api/document/upload` → **201**

`app/api/endpoints/documents.py:50`

**Request** — `multipart/form-data` (`python-multipart`):

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | **yes** | PDF; validated by content-type (`application/pdf` or absent) **and** `%PDF` magic bytes |
| `company_name` | str | no | defaults to a title-cased version of the filename |
| `company_symbol` | str | no | NSE ticker, e.g. `RELIANCE` |
| `financial_year` | str | no | e.g. `2025` |
| `document_type` | enum | no | `annual_report` (default) \| `financial_results` \| `corporate_filing` \| `investor_presentation` \| `other` |
| `exchange` | str | no | default `NSE` |

**Response 201** (`schema.DocumentUploadResponse`):

```json
{
  "id": "0f0b6f9e-6f0e-4a3a-9f5e-6d0f3f9a1b2c",
  "url": "https://<project>.supabase.co/storage/v1/object/public/annual-reports/documents/0f0b…/original.pdf",
  "metadata_map": {
    "nse_document": {
      "company_name": "Reliance Industries Limited",
      "company_symbol": "RELIANCE",
      "document_type": "annual_report",
      "financial_year": "2025",
      "report_date": null,
      "exchange": "NSE",
      "original_filename": "reliance-ar-2025.pdf"
    },
    "content_hash": "9f2c…",
    "original_filename": "reliance-ar-2025.pdf"
  },
  "status": "indexed",
  "created_at": "2026-10-24T12:00:00",
  "updated_at": "2026-10-24T12:00:00"
}
```

**Behaviour**

1. Empty body → `400 {"detail": "The uploaded file is empty."}`
2. Non-PDF content-type → `400 {"detail": "Only PDF files are accepted. Received content-type: …"}`
3. No `%PDF` prefix → `400 {"detail": "The uploaded file does not appear to be a valid PDF."}`
4. **Duplicate (same SHA-256)** → returns the **existing** document with `status: "indexed"`,
   HTTP **201** (idempotent; no second storage object).
5. Storage upload failure → `500 {"detail": "Failed to upload file to storage: …"}`
6. DB insert failure → storage object deleted, `500 {"detail": "Failed to create document record in database."}`
7. Indexing failure → DB row + storage object deleted, `422 {"detail": "PDF indexing failed. The file may be corrupted or unreadable: …"}`

**Timing** — indexing (parse → chunk → Gemini embeddings → pgvector) happens **inside** this
request. Multi-hundred-page PDFs can take minutes; there is no progress channel.

**curl**

```bash
curl -X POST localhost:8000/api/document/upload \
  -F "file=@reliance-ar-2025.pdf;type=application/pdf" \
  -F "company_name=Reliance Industries Limited" \
  -F "company_symbol=RELIANCE" -F "financial_year=2025" -F "document_type=annual_report"
```

### `GET /api/document/` → `List[Document]`

`documents.py:186` · optional repeatable query `document_ids=<uuid>`

```json
[{"id":"…","url":"…","metadata_map":{…},"created_at":"…","updated_at":"…"}]
```

- **404 `{"detail":"Document(s) not found"}` when the result set is empty** (including an empty
  library). Quirk, see `AGENTS.md §14.L`.
- No pagination, no filtering by company/symbol/type.

### `GET /api/document/{document_id}` → `Document`

`documents.py:205` · path param is a `UUID` (FastAPI returns 422 for a malformed UUID).
Returns `docs[0]` from `crud.fetch_documents(id=…)`; `404 {"detail":"Document not found"}` if absent.

---

## 3. Conversations

### `POST /api/conversation/` → `Conversation`

`conversation.py:31`

**Request**

```json
{"document_ids": ["0f0b6f9e-6f0e-4a3a-9f5e-6d0f3f9a1b2c"]}
```

**Response** (`schema.Conversation`; `messages` empty on creation)

```json
{
  "id": "6d8f…",
  "created_at": "2026-10-24T12:03:11",
  "updated_at": "2026-10-24T12:03:11",
  "messages": [],
  "documents": [{"id": "0f0b…", "url": "…", "metadata_map": {…}, "created_at": "…", "updated_at": "…"}]
}
```

Errors: `404 {"detail":"Documents not found: <id>, <id>"}` when any supplied id is unknown.
An empty `document_ids` list is allowed and produces a conversation with no scope (the agent then
has zero document tools — answers will be empty).

`crud.create_conversation` (`crud.py:42`) inserts the conversation plus one
`conversationdocument` row per id, then re-reads with eager loading.

### `GET /api/conversation/{conversation_id}` → `Conversation`

`conversation.py:53` · includes every message (ordered as the DB returns them) with its full
`sub_processes` array, plus the linked documents. `404 {"detail":"Conversation not found"}`.

### `DELETE /api/conversation/{conversation_id}` → **204**, empty body

`conversation.py:66` · `404 {"detail":"Conversation not found"}` if the row is absent.

⚠ Does **not** delete child `message` / `messagesubprocess` / `conversationdocument` rows, and the
FKs have no `ON DELETE CASCADE` ⇒ a conversation with messages raises a FK violation (500). See
`AGENTS.md §14.E`.

---

## 4. Chat / SSE

### `GET /api/conversation/{conversation_id}/message?user_message=<text>` → `text/event-stream`

`conversation.py:81` · returns `EventSourceResponse(event_publisher())`.

⚠ The message is a **query parameter** (`user_message`), not a body — GET with side effects.
The user message is persisted only at the end of the stream.

**Protocol**

- Event type: **none** (default `message` event); each frame's `data` is one JSON object.
- Payload: a complete `schema.Message` snapshot (not a delta). `content` and `sub_processes`
  grow monotonically across frames.
- `status` is `PENDING` while generating; the last frame carries `SUCCESS` or `ERROR`.
- The final frame is re-read from the DB, so it contains the persisted ids/timestamps.

Frame shape:

```jsonc
{
  "id": "b1e0…",                       // assistant message id (uuid4 generated up-front)
  "conversation_id": "6d8f…",
  "content": "Reliance's FY2025 consolidated revenue was …",   // cumulative
  "role": "assistant",
  "status": "PENDING",
  "sub_processes": [
    {
      "id": null,
      "message_id": "b1e0…",
      "source": "SUB_QUESTION",
      "status": "FINISHED",
      "metadata_map": {
        "sub_question": {
          "question": "What was Reliance's FY2025 consolidated revenue?",
          "answer": "₹ 10,71,774 crore",
          "citations": [
            {"document_id": "0f0b…", "text": "…consolidated revenue…", "page_number": 112, "score": 0.83}
          ]
        }
      }
    }
  ],
  "created_at": "2026-10-24T12:05:01",
  "updated_at": null
}
```

Sub-process semantics (produced by `ChatCallbackHandler`, `chat/messaging.py`):

| Field | Meaning |
|---|---|
| `source` | `MessageSubProcessSourceEnum[event_type.name]` — e.g. `LLM`, `RETRIEVE`, `SYNTHESIZE`, `SUB_QUESTION`, `AGENT_STEP`, plus synthetic `CONSTRUCTED_QUERY_ENGINE` (engine built) |
| `status` | `PENDING` on the start event, `FINISHED` on the end event of the same `event_id` |
| `metadata_map.sub_question` | only for `SUB_QUESTION`: question, answer, citations |

The **first** frame after the engine is built is always
`{source: "CONSTRUCTED_QUERY_ENGINE", status: "FINISHED"}`.

Persistence & edge cases:

- On success, the user message and the assistant message (with all sub-processes) are committed
  and the final snapshot is emitted.
- On exception: assistant `status="ERROR"`, both messages still committed, no 5xx (the response
  has already started).
- If the model produced no text, the stream contains the canned apology
  `"Sorry, I either wasn't able to understand your question or I don't have an answer for it."`
- Client disconnect closes the anyio send channel; the producer keeps running until it notices
  `send_chan._closed`.

**curl**

```bash
curl -N "localhost:8000/api/conversation/<ID>/message?user_message=What%20was%20FY2025%20revenue%3F"
```

### `GET /api/conversation/{conversation_id}/test_message?user_message=<text>` → `Message`

`conversation.py:181` — calls `message_conversation(...)`, drains `response.body_iterator`, and
returns the **last** frame parsed as `schema.Message`. Useful in Swagger (which cannot render SSE).
Because `sse-starlette` 1.6.5 sets `body_iterator` to the raw async generator, the yielded values
are the JSON strings themselves. On an unexpected empty stream it raises `500`.

---

## 5. Error summary

| Code | Sources |
|---|---|
| 400 | empty upload, wrong content-type, missing `%PDF` magic |
| 404 | conversation not found, document not found, **document list empty**, unknown `document_ids` on create |
| 422 | FastAPI validation (bad UUID, missing required form field), PDF indexing failure |
| 500 | storage upload failure, DB insert failure, `test_message` empty stream, unhandled FK violation on conversation delete, DB errors |

Error body is always FastAPI's default `{"detail": "<message>"}`. There is no error code
namespace and no structured error envelope.

---

## 6. Contract expected by the frontend (currently unmet)

`frontend/src/lib/api.ts` `RealTransport` is a stub that disagrees with the server:

| Client does | Server expects |
|---|---|
| `GET /api/conversation/{id}/message?q=<text>` | `?user_message=<text>` |
| Listens for named SSE events `sub_process`, `delta`, `done` | unnamed frames, each a full `Message` |
| `POST /api/conversation/ {title, document_scope}` | `{document_ids}` |
| `DocumentUploadResponse {document: FinDocument}` | `{id,url,metadata_map,status,…}` (flat) |
| `FinDocument` fields (`nse_symbol`, `fiscal_year`, `pages`) | `metadata_map.nse_document.*` |
| Plain `EventSource` (no headers) | works, but no `Accept` control; errors surface as `onerror` |

Also, `GET /api/document/` 404s on an empty library, which `listDocuments()` would surface as a
JSON parse/`Error` — the transport has no status checking at all (`res.json()` on every response).

If you implement the adapter: map wire→domain in one place, convert the snapshot stream into the
store's `onSubProcess`/`onToken`/`onDone` callbacks (diff `content` to produce tokens), and derive
`Source.index` from citation order within a message.

---

## 7. OpenAPI

- Spec: `GET /api/openapi.json`; UI: `/api/docs`; ReDoc: `/api/redoc`.
- Title `fincite` (`settings.PROJECT_NAME`), description mentions "AI financial research backend
  for Indian / NSE company annual reports and filings".
- Operations are tagged `conversation`, `document`, `health` (`api/api.py:6-10`).
- The SSE endpoint appears as a normal `GET` returning `text/event-stream`; Swagger cannot render
  it — use `curl -N` or the browser `EventSource`.
- No security schemes are declared.
