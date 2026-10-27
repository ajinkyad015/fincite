# API REFERENCE — fincitee

Everything the frontend is allowed to rely on. Base path: `settings.API_PREFIX` (`/api`).
Shapes are defined in [`backend/app/schema.py`](../../backend/app/schema.py); OpenAPI is served at
`/api/openapi.json`, Swagger at `/api/docs`, ReDoc at `/api/redoc`.

> **Status:** updated for the M1 contract (async ingestion, thread index, message-level citations,
> `POST` streaming). See `docs/plans/connect-and-deploy.md`.

---

## 0. Conventions

| Topic | Rule |
|---|---|
| IDs | UUID strings |
| Timestamps | ISO-8601 UTC (`created_at`, `updated_at`) |
| Enum casing | lowercase values (`document.status = "ready"`, `document_type = "annual_report"`); message/sub-process statuses stay upper-case (`PENDING`, `SUCCESS`, `ERROR`, `FINISHED`) for backwards compatibility |
| Empty result | `200` + `[]` — never 404 for "nothing yet" |
| Errors | `{"detail": "…"}`; 400 bad input, 404 missing, 409 conflict (e.g. nothing indexed / job already running), 413 too large, 422 validation, 502 upstream (storage), 503 dependency unavailable |
| Secrets | the service-role key and API keys never appear in any response |

---

## 1. Health & config

### `GET /api/health/` → `HealthResponse`

Always **200**; the payload distinguishes "API down" from "API up, database down".

```jsonc
{"status": "healthy", "db": true, "vector_store": null, "version": "0.2.0", "uptime_s": 1284.3}
```

`status` is `"healthy" | "degraded"` (`degraded` ⇒ `db: false`). The UI polls this for the sidebar
indicator and treats a network error as "down".

### `GET /api/config/` → `ConfigResponse`

Public, non-secret runtime configuration.

```jsonc
{"version": "0.2.0", "max_upload_mb": 50, "supported_content_types": ["application/pdf"],
 "auth_enabled": false, "demo_mode": false}
```

---

## 2. Documents

### `POST /api/document/upload` → **202** `DocumentUploadResponse`

Multipart. **Indexing is asynchronous**: the response means "accepted", not "indexed".

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | **yes** | PDF; validated by content-type and `%PDF` magic bytes, and by `MAX_UPLOAD_MB` (413 if bigger) |
| `company_name` | str | no | defaults to a title-cased filename |
| `company_symbol` | str | no | NSE ticker, upper-cased server-side |
| `financial_year` | str | no | `2024-25`, `FY2024-25`, `2025` — normalised to `FY2024-25` on read |
| `document_type` | enum | no | `annual_report` (default) \| `quarterly_results` \| `concall_transcript` \| `investor_presentation` \| `shareholding_pattern` \| `corporate_announcement` \| `financial_results` \| `corporate_filing` \| `other` |
| `exchange` | str | no | default `NSE` |

```jsonc
{
  "id": "…", "url": "https://…/documents/{id}/original.pdf",
  "status": "uploaded", "progress": 0, "error": null,
  "page_count": null, "file_size": 24800000, "content_hash": "<sha256>",
  "metadata_map": {"nse_document": {…}, "content_hash": "…", "original_filename": "reliance.pdf"},
  "created_at": "…", "updated_at": "…"
}
```

* **Duplicate content** (same SHA-256) → **200** with the existing document; nothing is re-indexed.
* Failure points: 400 not a PDF / empty, 413 too large, 500 storage or DB error (the stored object is
  removed on DB failure).

**Lifecycle** (`document.status`, polled by the library):

```
uploaded → parsing → chunking → embedding → indexing → ready
                                                    ↘ failed (document.error has the reason)
```

### `GET /api/document/` → `List[Document>`

Query: `document_ids` (repeatable), `status`, `q` (company / symbol / fiscal year / filename),
`limit` (`1..200`), `offset`. **`200 []` for an empty library.**

### `GET /api/document/{document_id}` → `Document`

404 when missing. Includes `status` / `progress` / `error` / `page_count` / `file_size`.

### `GET /api/document/{document_id}/file` → `application/pdf`

Streams the original PDF **through the API** (the bucket can stay private; the service-role key never
leaves the server). `?download=true` forces `Content-Disposition: attachment`. The citation viewer uses
`#page=N` on this URL. 502 if storage is unreachable.

### `POST /api/document/{document_id}/reindex` → **202** `DocumentUploadResponse`

Re-runs ingestion from the stored PDF. Clears existing vectors first so chunks cannot double-count.
409 while a job is already running. This is the library's "Retry indexing" action.

### `DELETE /api/document/{document_id}` → **204**

Deletes vectors → stored object → conversation links → row. If the vectors cannot be cleared the
request fails with **503** and nothing is deleted (a filing that is invisible but still retrievable is
worse than a failed delete).

---

## 3. Conversations

### `POST /api/conversation/` → **201** `Conversation`

```jsonc
{"document_ids": ["<uuid>", …], "title": "Optional name"}   // both optional
```

An **empty scope is allowed** — create the thread, then `PATCH` the scope (this is how "New chat" works).
404 if any `document_id` does not exist.

### `GET /api/conversation/` → `List[ConversationSummary>`

The thread index for the sidebar. Query: `limit` (`1..200`), `offset`, `q` (title search).

```jsonc
{"id": "…", "title": "Compare FY24 revenue", "created_at": "…", "updated_at": "…",
 "last_message_at": "…", "message_count": 6, "document_ids": ["…"],
 "preview": "Compare FY24 revenue across Reliance and TCS…"}
```

Ordered by `last_message_at` then `created_at`, newest first. Never includes message bodies.

### `GET /api/conversation/{conversation_id}` → `Conversation`

Messages (oldest first) each with `sub_processes[]` **and** a flat `sources[]`:

```jsonc
{"id": "…", "title": "…", "last_message_at": "…",
 "documents": [{"id": "…", "metadata_map": {…}, "status": "ready", …}],
 "messages": [
   {"id": "…", "role": "user", "content": "What was FY24 revenue?", "status": "SUCCESS",
    "sub_processes": [], "sources": []},
   {"id": "…", "role": "assistant", "content": "₹9.0 lakh crore [1]", "status": "SUCCESS",
    "sub_processes": [
      {"id": "…", "source": "SUB_QUESTION", "status": "FINISHED",
       "name": "What was FY24 revenue?", "duration_ms": 812,
       "metadata_map": {"sub_question": {"question": "…", "answer": "…", "citations": [{…}]}}}
    ],
    "sources": [
      {"index": 1, "document_id": "…", "page": 41, "excerpt": "Revenue from operations …", "score": 0.91}
    ]}
 ]}
```

`sources[].index` matches the `[n]` markers in the answer text. `sources` is also persisted, so it
survives a reload.

### `PATCH /api/conversation/{conversation_id}` → `Conversation`

```jsonc
{"title": "Renamed thread"}            // or
{"document_ids": ["<uuid>", …]}        // replaces the scope entirely ([] = all filings)
```

404 for a missing thread or unknown document ids.

### `DELETE /api/conversation/{conversation_id}` → **204**

Deletes messages, sub-processes and scope links (explicitly *and* via `ON DELETE CASCADE`).

---

## 4. Chat / SSE

### `POST /api/conversation/{conversation_id}/message` → `text/event-stream` **(preferred)**

```jsonc
{"content": "Compare FY24 revenue across both filings"}
```

### `GET /api/conversation/{conversation_id}/message?user_message=<text>` → `text/event-stream` (deprecated)

Identical contract, question in the query string. Kept for `curl -N` and the terminal client.

### `GET /api/conversation/{conversation_id}/test_message?user_message=<text>` → `Message`

Runs the exact same pipeline (persistence, trail, citations) without streaming — handy in Swagger.

**Stream contract**

* **unnamed** events: `data: {…}` with no `event:` line;
* every frame is a **complete** `Message` snapshot — `content` and `sub_processes` grow monotonically,
  so a client replaces state instead of reassembling deltas;
* `status` is `PENDING` while generating, then exactly one terminal `SUCCESS` or `ERROR`;
* `: ping` comments every 15 s (keep-alive);
* pre-stream failures are real HTTP errors, not error frames: 404 unknown thread, 409 nothing indexed,
  422 empty question.

**Durability** — a dropped connection loses at most the last ~1.5 s / 200 characters:

1. the user message and an assistant placeholder row are committed **before** generation starts;
2. assistant content is flushed during the stream (every 1.5 s or 200 chars);
3. the terminal state (status, content, `sources`, `sub_processes`) is written even on disconnect or
   engine failure. Reconnecting = `GET /api/conversation/{id}`.

**Scope resolution** — a thread with no documents answers across *all* `ready` documents; if none are
indexed the request is rejected with **409**.

---

## 5. WebSocket / other

None. Streaming is SSE only; there is no websocket endpoint.

---

## 6. Frontend contract map (M2 — implemented)

M2 is landed: `frontend/src/lib/wire.ts` implements the wire→domain translation from §M2.1, and
`frontend/src/lib/transport.ts` consumes the POST SSE snapshots over `fetch` + `ReadableStream`.
`api.ts` is now only a facade over the real and explicit-demo transports.

| Concern | Wire shape | UI domain shape |
|---|---|---|
| document | `metadata_map.nse_document.{company_name,company_symbol,financial_year}` + `page_count` | `FinDocument.metadata.{company_name,nse_symbol,fiscal_year,pages}` |
| status | `uploaded…ready/failed` | same names |
| message sources | `message.sources[]` | `ChatMessage.sources[]` (identical fields) |
| trail step | `source` (CBEventType) + `name` + `duration_ms` | `MessageSubProcess.{source,name,detail,duration_ms}` |
| conversation | `documents[]`, `title`, `last_message_at` | `document_scope[]`, `title`, `updated_at` |

---

## 7. OpenAPI

`/api/openapi.json` (spec) · `/api/docs` (Swagger) · `/api/redoc` (ReDoc).
