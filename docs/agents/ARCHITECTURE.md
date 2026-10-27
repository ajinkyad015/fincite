# ARCHITECTURE — fincitee

Deep dive for anyone changing the RAG harness, the process model, or cross-cutting wiring.
Companion files: `../DATA_MODELS.md`, `../WORKFLOWS.md`, `../modules/rag-engine.md`,
`../modules/streaming.md`.

---

## 1. System context

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Browser                                                                      │
│   React 19 SPA (Vite 7, Tailwind v4, framer-motion)                          │
│   frontend/src/store.tsx  ──►  frontend/src/lib/api.ts                       │
│                                  ├── RealTransport  (DEFAULT, M1 contract)   │
│                                  │     ├─ transport.ts: fetch + POST SSE     │
│                                  │     └─ wire.ts: DTO → domain mapper       │
│                                  └── MockTransport  (VITE_USE_MOCK=1 only)   │
└───────────────────────────┬──────────────────────────────────────────────────┘
                            │ same-origin /api/** (Vite proxy / reverse proxy)
┌───────────────────────────▼──────────────────────────────────────────────────┐
│ FastAPI (uvicorn, BACKEND_WORKERS=4)                                         │
│   app/main.py  ── lifespan ──► settings, vector store pools                  │
│   app/api/endpoints/{health,documents,conversation}.py                       │
│        │                     │                                               │
│        │                     └─ SSE (sse-starlette EventSourceResponse)      │
│        ▼                                                                     │
│   app/api/crud.py  ──►  SQLAlchemy 2 async  ──►  PostgreSQL                  │
│   app/ingestion/pdf.py ─┐                                                    │
│   app/chat/engine.py  ──┼──►  LlamaIndex  ──►  pgvector (data_pg_vector_store)│
│   app/chat/pg_vector.py ┘        │                                           │
│                                  └──► configured /v1 models (chat+embeddings) │
│   app/storage/supabase.py  ──►  Supabase Storage (documents/{id}/original.pdf)│
└──────────────────────────────────────────────────────────────────────────────┘
```

Everything is **one deployable service + one static SPA**. There is no cache tier, no message
broker, no vector DB, and no auth service.

---

## 2. Process & deployment model

### 2.1 Boot phases (`app/main.py`)

| Phase | Where | Runs | Work |
|---|---|---|---|
| Deploy bootstrap | `start()` → `_bootstrap(release_connections=True)` | **once**, parent process | DB wait, Alembic head check, pgvector extension + DDL, NLTK punkt warm-up, release parent pools |
| Handoff | `os.environ["FINCITE_BOOTSTRAP_DONE"]="1"` | once | children inherit env ⇒ skip bootstrap |
| Worker lifespan (setup) | `lifespan()` before `yield` | per worker | `_setup_llama_index_settings()` in a thread (config-only, network-free; logs the effective model profile); `vector_store.ensure_initialized()` (no DDL) |
| Serving | uvicorn | per worker | stateless request handling |
| Worker lifespan (teardown) | after `yield` | per worker | `vector_store.close()` |

`uvicorn.run(..., reload=LOG_LEVEL=="DEBUG", workers=BACKEND_WORKERS)`: when reload is on,
uvicorn **ignores** `workers` and runs a single reloading process. `reload` also means the
module-level app is re-imported, so `nest_asyncio.apply()` and `Settings()` run again — harmless
but noisy.

If the app is started with `uvicorn app.main:app` instead of `start()`, the flag is absent and
**each worker** runs `_bootstrap()`; the steps are idempotent (`did_run_setup`, `drop/create`
guards, `CREATE EXTENSION IF NOT EXISTS`), but the Alembic check runs N times.

### 2.2 Connection pools

- `app/db/session.py:6` — one async engine per process: `pool_size=4`, `max_overflow=4`,
  `pool_recycle=3600`, `pool_timeout=120`, `pool_pre_ping=True`.
- `CustomPGVectorStore._connect()` (`chat/pg_vector.py:19`) **replaces** LlamaIndex's own async
  engine/session with `app.db.session.engine` / `SessionLocal`, so a worker holds **one** pool,
  not two. It still builds a small **sync** engine (psycopg2-style) for the base class's sync
  paths.
- `close()` (`pg_vector.py:27`) closes the sync session/engine and disposes the shared async
  engine. Because the engine is shared, `close()` in one place affects the whole process — only
  called at shutdown and in the parent's `_bootstrap(release_connections=True)`.

### 2.3 DDL ownership

| Object | Created by | Where |
|---|---|---|
| `uuid-ossp` extension | Alembic first migration | `alembic/versions/477cee72edc4_init_tables.py:21` |
| relational tables + PG enums | Alembic | six migrations (single head `663b3fea3024`) |
| `vector` extension | `run_setup()` | `chat/pg_vector.py:46` |
| `data_pg_vector_store` (+ `data_pg_vector_store_metadata_col`) | `run_setup()` → `self._base.metadata.create_all` | `chat/pg_vector.py:53` |
| Alembic freshness check | `check_current_head()` | `main.py:50` |

`_create_tables_if_not_exists()` and `_create_extension()` are intentionally overridden to
no-ops so LlamaIndex's lazy `_initialize()` never issues DDL from a worker.

---

## 3. Backend module layers

```
HTTP layer        app/api/endpoints/*.py      validation, HTTP codes, response models
      │
Data access       app/api/crud.py             the ONLY module with SQLAlchemy queries
      │
ORM               app/models/db.py            tables, PG enums
      │
Domain services   app/chat/*, app/ingestion/*, app/storage/*, app/llama_index_settings.py
      │
Infrastructure    app/db/*, app/core/config.py
```

Dependency rules that hold today (keep them):

- `endpoints → crud → models`; endpoints never build queries.
- `chat/*` never imports `endpoints/*`; it consumes **Pydantic schemas** (`app.schema`) so the
  engine is testable without a DB session.
- `models/*` imports nothing from `chat/*` except `CBEventType` (`models/db.py:5`) used to
  generate the sub-process enum.
- `schema.py` imports `chat/constants.py` (`DB_DOC_ID_KEY`) and model enums — a deliberate
  small cycle in the "types" direction.
- `storage/supabase.py` is a leaf (only `core/config.py`).

### Notable coupling to be aware of

| Coupling | Consequence |
|---|---|
| `chat/pg_vector.py` reaches into `db/session.py` | vector store shares the app pool; closing one affects the other |
| `core/config.py` instantiates `Settings` at import | `DATABASE_URL` + `NVIDIA_API_KEY` are required before any app import (tests set them in `conftest.py`). Key/endpoint are passed explicitly to both model clients — no `os.environ` mutation |
| `chat/engine.py:65` calls `nest_asyncio.apply()` at import | re-entrant loops; masks sync/async mistakes (e.g. `VectorStoreIndex.from_documents` inside an async handler) |
| `models/db.py` derives enum values from LlamaIndex's `CBEventType` | upgrading `llama-index-core` can add enum values the DB type doesn't have ⇒ need a migration |

---

## 4. The RAG harness (`app/chat/engine.py`)

### 4.1 Tier 1 — `ReActAgent`

```python
chat_llm = get_chat_llm()  # llama_index_settings factory (OpenAILike, env-declared metadata)
question_gen = LLMQuestionGenerator.from_defaults(llm=chat_llm)
document_question_engine = SubQuestionQueryEngine.from_defaults(..., llm=chat_llm)
top_level_tools = [QueryEngineTool(document_question_engine, "document_question_engine")]
chat_engine = ReActAgent.from_tools(tools=top_level_tools, llm=chat_llm,
                                    chat_history=chat_history, verbose=LOG_LEVEL=="DEBUG",
                                    context=SYSTEM_MESSAGE.format(...), max_iterations=6)
```

That one `chat_llm` is also passed to `index.as_query_engine(..., llm=chat_llm)` and
`get_custom_response_synth(..., llm=chat_llm)`: LlamaIndex resolves `Settings.llm` internally
even when a synthesizer/question generator is supplied, so explicit passing is what keeps every
tier on the configured model and prevents `None` metadata or an unset global from breaking the
first message.

Exactly **one** top-level tool, described as an engine that answers *all* questions about the
selected Indian financial documents. `context` carries the doc titles for the current
conversation and today's date; the agent must consult tools before answering.

### 4.2 Tier 2 — `SubQuestionQueryEngine`

- `use_async=True` ⇒ sub-questions fan out concurrently.
- `response_synthesizer=get_custom_response_synth(...)` — Refine + QA prompts that restate:
  selected documents, preserve units, name the financial year, do not fabricate
  (`qa_response_synth.py:16-66`).
- `question_gen` reuses the same configured chat model, so one conversation makes many LLM calls
  (question generation + N sub-answers + synthesis + ReAct steps).

### 4.3 Tier 3 — per-document tools

```python
MetadataFilters([ExactMatchFilter(key=DB_DOC_ID_KEY, value=doc_id)])
index.as_query_engine(similarity_top_k=3, filters=filters)   # engine.py:104-109
```

One tool per document, named by the **document UUID** and described by
`build_description_for_document` (e.g. *"Annual report for Reliance Industries (RELIANCE),
financial year 2025 (exchange: NSE)."*). The description is the routing signal — improve metadata
before you touch retrieval parameters.

### 4.4 Index acquisition

`build_doc_id_to_index_map` (`engine.py:112`) iterates `conversation.documents`:

```
VectorStoreIndex.from_vector_store(vector_store, callback_manager)   # "load" attempt
    on exception → fetch_and_read_document(doc) → VectorStoreIndex.from_documents(...)
```

⚠ The first call does not verify that vectors exist for that `doc_id` and does not raise for an
empty document — see `AGENTS.md §14.H`. `fetch_and_read_document` downloads from Supabase
Storage and falls back to `requests.get(document.url, stream=True)` inside a `TemporaryDirectory`.

### 4.5 Chat history

`get_chat_history` (`engine.py:153`) drops empty-content and non-`SUCCESS` messages, sorts by
`created_at`, maps `MessageRoleEnum` → LlamaIndex `MessageRole`, and passes the list to
`ReActAgent.from_tools(chat_history=...)`. The pending assistant message is never included
because the conversation is loaded *before* the user message is inserted.

---

## 5. Observability bus (LlamaIndex callbacks → SSE)

```
LlamaIndex internals
   │ CBEventType.{LLM, RETRIEVE, SYNTHESIZE, SUB_QUESTION, AGENT_STEP, …}
   ▼
ChatCallbackHandler (chat/messaging.py:33)
   │ on_event_start / on_event_end → asyncio.create_task(async_on_event)
   │ get_metadata_from_event: SUB_QUESTION → schema.QuestionAnswerPair (Q, A, citations)
   ▼
StreamedMessageSubProcess{source, has_ended, event_id, metadata_map}
   ▼
anyio MemoryObjectSendStream (capacity 100, endpoints/conversation.py:110)
   ▼
event_publisher: OrderedDict[event_id → MessageSubProcess]
   │ start event creates a PENDING row; end event sets FINISHED and keeps created_at
   ▼
schema.Message.model_validate(message).model_dump_json()  → one SSE frame per event
```

Design consequence: **the client never assembles deltas** — every frame is a complete snapshot,
so reconnection/resume is trivial and the same data shape is persisted at the end.

The `source` value is `MessageSubProcessSourceEnum[event_type.name]`; because the enum is built
from `CBEventType` plus `CONSTRUCTED_QUERY_ENGINE`/`SUB_QUESTIONS`, an unknown event name raises
`KeyError` (and the task dies silently — see `AGENTS.md §14.D`).

---

## 6. Ingestion architecture

```
POST multipart
   ├── _validate_pdf            content-type + %PDF magic bytes          documents.py:32
   ├── sha256 + dedupe lookup   metadata_map->>'content_hash'            crud.py:155
   ├── storage.upload_document  documents/{uuid}/original.pdf            supabase.py:44
   ├── crud.create_document     Document(url, metadata_map)              crud.py:108
   └── ingest_document          pdf.py:70
         ├── storage.download_document(id)      → bytes
         ├── load_pdf_from_bytes                → temp file → PDFReader.load_data(extra_info={db_document_id})
         │                                        one LlamaIndex Document per PDF page, metadata.page_label
         ├── StorageContext.from_defaults(vector_store=…)
         ├── VectorStoreIndex.from_documents(show_progress=True)
         │     SentenceSplitter(chunk_size=512, chunk_overlap=10)  (llama_index_settings.py:22)
         │     configured embedding model (2048-d) → INSERT into data_pg_vector_store
         └── index.set_index_id(document_id)
```

Rollback matrix:

| Failure point | Cleanup |
|---|---|
| storage upload | nothing persisted |
| DB insert | `delete_document(id)` (storage) |
| indexing | `crud.delete_document_by_id` + `delete_document(id)` → HTTP 422 |

Note the rollback does **not** delete partially written vector rows. If `from_documents` fails
mid-batch, orphan vectors can remain (they are harmless — filtered by a `db_document_id` that no
longer has a `Document` row — but they cost storage).

---

## 7. Frontend architecture

### 7.1 Layers

```
index.html
  └─ src/main.tsx (StrictMode)
       └─ App.tsx
            ├─ StoreProvider (store.tsx)             ← all app state
            └─ Shell
                 ├─ Ticker (static mock data)
                 ├─ Sidebar (conversations, docs count, health dot)
                 ├─ view switch: ChatView | LibraryView   (animated with AnimatePresence)
                 ├─ SourceDrawer / Toasts / Splash   (global overlays)
                 └─ <Analytics/> (@vercel/analytics)
```

There is **no router**: `view: "chat" | "library"` in the store drives the screen. Overlays
(`SourceDrawer`, `UploadDrawer`, `DocDetailDrawer`, mobile nav) are controlled by store fields or
local `useState`, never by URLs.

### 7.2 Store design (`store.tsx`)

One context, ~30 fields, three concerns:

| Concern | State | Notable functions |
|---|---|---|
| Documents | `documents`, `uploading`, `libraryOpenDocId` | `refreshDocuments`, `uploadFiles`, `watchDocument` (900 ms polling until `ready`/`failed`) |
| Conversations | `conversations`, `activeId`, `active`, `streaming` | `send`, `selectConversation`, `newChat`, `deleteConversation`, `setScope`, `startScopedChat`, `stopStreaming` |
| Chrome | `view`, `mobileNav`, `health`, `selectedSource`, `toasts`, `booted` | `boot`, `checkHealth`, `pushToast`, `openSource`, `closeSource` |

`patchConversation(id, fn)` is the single mutation primitive for a thread; it re-sorts threads by
`updated_at` descending. M2 batches full assistant snapshots on `requestAnimationFrame` and flushes
terminal snapshots immediately. `send()` guards with `streaming` (one in-flight answer per tab).

### 7.3 Transport facade (`lib/api.ts`)

`export const api = { … }` exposes the full M1 client surface. Each method is
`USE_MOCK ? mock.x() : real.x()`. `RealTransport` lives in `transport.ts`, maps DTOs through
`wire.ts`, POSTs questions and reads unnamed `Message` snapshots from a `ReadableStream`. Both
transports emit the same full snapshots; `MockTransport` is selected only by `VITE_USE_MOCK=1` and
uses `ANSWER_BANK` plus timed pipeline stages for offline demos.

### 7.4 Design system

`src/index.css` `@theme` defines: colours (`bone paper faint line line-dark ink soot soot-2 moss
accent accent-deep accent-soft pine pine-soft rust rust-soft gold`), fonts (`font-display` =
Fraunces, `font-sans` = Space Grotesk, `font-mono` = IBM Plex Mono), animations (`animate-marquee`,
`animate-pulse-dot`) and utilities (`.tnum` tabular numerals, `.stream-caret`, `.dark-scroll`,
`.md-table`). Body has an SVG-noise grain overlay; scrollbars are thin.

Aesthetic rules in practice: sharp corners (no border radius), hairline borders, uppercase
9-10 px mono labels with wide tracking, serif display headings, one orange accent, motion used
only for entrance and panel slides.

### 7.5 Build

`vite.config.ts`: `react()` + `tailwindcss()` + `viteSingleFile()`, alias `@ → src` (defined in
both Vite and `tsconfig.json`), host `0.0.0.0`, allowed preview hosts and a same-origin `/api` proxy.
`vite build` emits **one** `dist/index.html` (~644 kB, ~195 kB gzip) — no code splitting, everything
inlined, fonts still fetched from Google Fonts CDN.

---

## 8. Extension points (where to add things)

| Goal | Touch these files |
|---|---|
| New endpoint | `api/endpoints/<area>.py` → register in `api/api.py`; add schema in `schema.py`; SQL in `crud.py`; test in `tests/app/…` |
| New document metadata field | `schema.NSEDocumentMetadata` → `documents.py` form param → `chat/utils.py` (title/description) → frontend `types.ts` + drawers |
| Change chunking/embeddings | `.env` embedding profile (model id, request style, dimensions) + `chat/constants.py` (chunk); **plus a migration/reindex** if `VECTOR_STORE_EMBED_DIM` changes |
| New agent tool | `chat/engine.py` (`top_level_tools`) + tool description in `chat/utils.py`/constants |
| New streamed UI metric | `chat/messaging.py` (`get_metadata_from_event`) + `schema.SubProcessMetadataKeysEnum` + `ResearchTrail`/`types.ts` |
| Swap chat model | **`.env` only** — set `NVIDIA_CHAT_LLM_NAME` + the declared `NVIDIA_CHAT_*` capability/limit profile and restart (§10.2 in AGENTS.md). No code change: `get_chat_llm()` is a generic `OpenAILike` |
| Swap embedding provider | `.env` embedding profile (`NVIDIA_EMBEDDING_*`, `NVIDIA_BASE_URL`) + `llama_index_settings.py` only if the request shape differs; `pyproject.toml` only for a new SDK. A new dimension means recreating `data_pg_vector_store` + re-indexing |
| Change wire↔domain mapping | `lib/wire.ts` first; keep components on `types.ts` |
| Change API transport / SSE | `lib/transport.ts`; keep full-snapshot handlers and rehydrate after terminal frames |
| Durable background indexing | replace `app/ingestion/jobs.py` process-local scheduler with a queue; endpoints/store already use 202 + polling |

---

## 9. Failure modes & resilience

| Symptom | Likely cause | Where |
|---|---|---|
| App exits at boot: "Database is not up to date" | migrations behind head | `main.py:95` |
| 500 on first upload | Supabase env missing (`RuntimeError`) | `storage/supabase.py:28` |
| Empty answers, no citations | documents have no vectors (reuse "worked") | `engine.py:126` |
| SSE hangs forever | callback task raised (e.g. `KeyError` on unknown `CBEventType`) and the channel never closed | `messaging.py:101` |
| 500 deleting a thread | regression in cascade delete (M1 fixed it) | `crud.py`, migration `d4b6f8c0e2a3` |
| Frontend shows stale data | `/api` proxy/backend down, or poller stopped | `transport.ts`, `store.tsx` |
| `ModuleNotFoundError: fire` | running a legacy `scripts/*.py` helper | `pyproject.toml` |
| Upload accepted but never ready | process-local ingestion task died / provider failure | `ingestion/jobs.py`; retry via `POST /reindex` |
