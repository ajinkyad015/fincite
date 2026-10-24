# AGENTS.md — fincitee

> **Read this first, every session.** It is the map of this repository: what it is, how the
> pieces connect, what is verified working, and what is broken. Everything below was checked
> against the code at commit `3b43329` (branch `arena/81e80233-fincitee`) on 2026-10-24.
> Where documentation (root `README.md`) disagrees with the code, **the code wins** — see §14.

**Repo:** `shinosuke0103/fincitee` · **License:** MIT · **Size:** 83 tracked files, ~7,350 lines of
application source (45 Python · 14 TSX · 6 TS · 1 CSS) plus committed lockfiles and a 493-line README.

---

## Extended Documentation

For deep dives, read the relevant file in `docs/agents/` before working on that module.
Do NOT read all of them — only what's relevant.

| File | Read it when you are… |
|---|---|
| `docs/agents/ARCHITECTURE.md` | changing the RAG harness, process model, or cross-cutting wiring |
| `docs/agents/DATA_MODELS.md` | touching SQLAlchemy models, Pydantic schemas, Alembic, or frontend types |
| `docs/agents/API_REFERENCE.md` | adding/altering endpoints or the SSE contract |
| `docs/agents/WORKFLOWS.md` | tracing upload, chat, streaming, or bootstrap end to end |
| `docs/agents/DEVELOPMENT.md` | setting up, running, building, testing, or debugging locally |
| `docs/agents/modules/backend-api.md` | endpoints, CRUD, DB session, settings |
| `docs/agents/modules/rag-engine.md` | `app/chat/**` — agent, prompts, vector store |
| `docs/agents/modules/ingestion-storage.md` | `app/ingestion/**`, `app/storage/**`, bootstrap/DDL |
| `docs/agents/modules/streaming.md` | `messaging.py`, the SSE endpoint, frontend transport |
| `docs/agents/modules/frontend.md` | `frontend/src/**` — store, components, design system, mock transport |

---

## 1. PROJECT OVERVIEW

**fincite / "Fin-Cite"** — an AI research terminal for **Indian / NSE company filings**
(annual reports, financial results, investor presentations, concall transcripts).

Two deliverables in one repo, deployable independently:

1. **`backend/`** — FastAPI + LlamaIndex RAG service. Upload a PDF → it is stored in Supabase
   Storage, parsed page-by-page, chunked, embedded with Google Gemini, and written into
   PostgreSQL/pgvector. Users then open a *conversation* scoped to 1..n documents and ask
   questions; answers stream over **SSE** as complete `Message` snapshots, with page-level
   citations and a persisted reasoning trace ("research trail").
2. **`frontend/`** — React 19 SPA ("research terminal"): thread rail, chat view, filing
   library with drag-and-drop upload, a live research-trail panel, clickable `[n]` citation
   chips and a source drawer. **It currently runs against an in-memory mock transport, not the
   backend** — see §14.B.

**Lineage.** The backend is a fork of a LlamaIndex + FastAPI "chat with documents" template
(originally SEC-focused) re-skinned for NSE filings. Fossils of the original: the default DB
name `llama_app_db` in `backend/alembic.ini:75`, "Upserts a single SEC document" in
`backend/scripts/upsert_document.py:9`, and the `CONSTRUCTED_QUERY_ENGINE` / `SUB_QUESTIONS`
sub-process enum values.

**Product invariants the prompts enforce** (`backend/app/chat/constants.py:3` `SYSTEM_MESSAGE`,
`backend/app/chat/qa_response_synth.py`): always call tools before answering; preserve units
exactly (₹ Crore / ₹ Lakh / USD Million); always name the financial year; cite page numbers;
never fabricate figures.

**What this project is NOT (yet):** no authentication, no multi-tenancy, no document
deletion, no background job queue, no CI, no frontend tests.

---

## 2. TECH STACK (exact versions)

### Backend — `backend/pyproject.toml` (resolved in `backend/uv.lock`, `requires-python = "==3.11.*"`)

| Package | Version | Role |
|---|---|---|
| `fastapi` | 0.115.11 | HTTP + OpenAPI |
| `pydantic` | 2.9.2 | API schemas (v2 API throughout) |
| `pydantic-settings` | 2.8.1 | `Settings` from env / `.env` |
| `uvicorn` | 0.22.0 | ASGI server (`workers=`, `reload=`) |
| `sse-starlette` | 1.6.5 | `EventSourceResponse` |
| `anyio` | 3.7.1 | in-memory object streams (`create_memory_object_stream`) |
| `sqlalchemy[asyncio]` | 2.0.19 | ORM, async engine/session |
| `asyncpg` | 0.29.0 | async PG driver |
| `psycopg2-binary` | 2.9.10 | sync engine for the Alembic head check |
| `psycopg[binary]` | 3.3.4 | (transitive / alternate PG driver) |
| `alembic` | 1.11.2 | migrations |
| `pgvector` | 0.3.6 | vector column type |
| `llama-index-core` | 0.12.23 | agent, query engines, callbacks |
| `llama-index-vector-stores-postgres` | 0.4.2 | `PGVectorStore` |
| `llama-index-readers-file` | 0.4.6 | `PDFReader` |
| `llama-index-llms-gemini` | 0.5.0 | `Gemini` LLM |
| `llama-index-embeddings-gemini` | 0.3.2 | `GeminiEmbedding` |
| `supabase` | 2.16.0 | Storage client |
| `nltk` | 3.9.1 | sentence tokenizer data |
| `nest-asyncio` | 1.6.0 | re-entrant loop patch (imported in `chat/engine.py:64`) |
| `python-multipart` | 0.0.9 | multipart upload parsing |
| `requests` | 2.32.3 | HTTP fallback download |
| `sentry-sdk[fastapi]` | 1.29.2 | optional error tracking |
| `pypdf` | 5.3.1 | PDF backend |
| `greenlet` | 2.0.2 | SQLAlchemy async requirement |
| `mako` | ≥1.4.1 | Alembic templates |

**Dev group:** `pytest` 7.4.0, `pytest-asyncio` 0.23.8, `httpx` 0.27.2, `sseclient-py` 1.7.2,
`pylint` 2.17.5. Build backend: `hatchling`; env manager: **uv** (lockfile committed).

### Frontend — `frontend/package.json` (versions in parentheses = installed/resolved)

| Package | Spec | Installed |
|---|---|---|
| `react`, `react-dom` | 19.2.6 | 19.2.6 |
| `typescript` | 5.9.3 | 5.9.3 |
| `vite` | 7.3.2 | 7.3.2 |
| `@vitejs/plugin-react` | 5.1.1 | 5.1.1 |
| `@tailwindcss/vite` + `tailwindcss` | 4.1.17 | 4.1.17 |
| `vite-plugin-singlefile` | 2.3.0 | single-file `dist/index.html` build |
| `framer-motion` | ^13.4.0 | 13.4.0 |
| `lucide-react` | ^1.47.0 | 1.47.0 |
| `react-markdown` | ^10.1.0 | 10.1.0 |
| `remark-gfm` | ^4.0.1 | 4.0.1 |
| `clsx` / `tailwind-merge` | 2.1.1 / 3.4.0 | `cn()` helper (**unused**, see §14) |
| `@vercel/analytics` | ^2.0.1 | `<Analytics />` in `App.tsx` |
| `@types/node` / `@types/react` / `@types/react-dom` | 22.19.17 / 19.2.7 / 19.2.3 | types |

### Infrastructure

- **PostgreSQL + pgvector** — Supabase in prod; `ankane/pgvector:v0.5.0` locally.
- **Supabase Storage** — bucket from `SUPABASE_STORAGE_BUCKET` (default `annual-reports`),
  object path `documents/{document_id}/original.pdf`.
- **Google AI (Gemini)** — chat `models/gemini-1.5-flash`, embeddings
  `models/gemini-embedding-001` (3072 dims).
- **Docker** — `backend/Dockerfile` (`python:3.11.3-slim-bullseye` + `uv sync --frozen`),
  `backend/docker-compose.yml` (backend + local pgvector).

---

## 3. ANNOTATED DIRECTORY STRUCTURE

```
fincitee/
├── AGENTS.md                      # ← you are here (agent entry point)
├── README.md                      # 493-line product/architecture doc (partly aspirational, §14)
├── LICENSE                        # MIT © 2026 Ajinkya Datir
├── .gitignore                     # ignores .env*, .venv, node_modules, dist, skills-lock.json
│
├── backend/
│   ├── pyproject.toml             # deps, dev group, `start` console script
│   ├── uv.lock                    # pinned lockfile (Python 3.11.*)
│   ├── Dockerfile                 # uv-based image; pre-downloads NLTK punkt; CMD .venv/bin/start
│   ├── docker-compose.yml         # backend + ankane/pgvector (see §14 for the broken port map)
│   ├── .dockerignore              # excludes tests/, .env, CONTEXT.md
│   ├── .env.example               # every env var, documented in sections
│   ├── alembic.ini                # script_location=alembic; stale default url (overridden by env.py)
│   ├── README.md                  # 3-line stub pointing at a non-existent CONTEXT.md
│   │
│   ├── app/
│   │   ├── main.py                # FastAPI app, lifespan, _bootstrap(), `start()` entrypoint
│   │   ├── schema.py              # ALL Pydantic API schemas (incl. NSE metadata, Citation)
│   │   ├── llama_index_settings.py# global LlamaIndex Settings: Gemini LLM, embeddings, splitter
│   │   ├── core/config.py         # pydantic-settings `Settings` + URL/CORS/LOG_LEVEL validators
│   │   ├── db/
│   │   │   ├── session.py         # async engine + async_sessionmaker (pool 4 / overflow 4)
│   │   │   ├── base.py            # imports models for Alembic autogenerate
│   │   │   └── wait_for_db.py     # 30× SELECT 1 retry loop
│   │   ├── models/
│   │   │   ├── base.py            # DeclarativeBase: uuid id + created_at/updated_at + auto __tablename__
│   │   │   └── db.py              # Conversation, Message, MessageSubProcess, Document, ConversationDocument + PG enums
│   │   ├── api/
│   │   │   ├── api.py             # router registry (also mounts /docs, /redoc, /openapi.json under /api)
│   │   │   ├── deps.py            # get_db() dependency
│   │   │   ├── crud.py            # all data access (9 async functions)
│   │   │   └── endpoints/
│   │   │       ├── conversation.py# create/get/delete + SSE /message + /test_message
│   │   │       ├── documents.py   # POST /upload (validate→dedupe→store→index), GET list/one
│   │   │       └── health.py      # GET / → {"status": "alive"}
│   │   ├── chat/
│   │   │   ├── engine.py          # 3-tier harness: ReActAgent → SubQuestionEngine → per-doc tools
│   │   │   ├── messaging.py       # ChatCallbackHandler → anyio channel; handle_chat_message()
│   │   │   ├── pg_vector.py       # CustomPGVectorStore singleton sharing the app's async pool
│   │   │   ├── qa_response_synth.py# custom QA + Refine prompts (units, FY, no fabrication)
│   │   │   ├── constants.py       # DB_DOC_ID_KEY, SYSTEM_MESSAGE, chunk 512 / overlap 10
│   │   │   └── utils.py           # build_title_for_document / build_description_for_document
│   │   ├── ingestion/pdf.py       # PDF bytes → PDFReader → VectorStoreIndex → pgvector
│   │   └── storage/supabase.py    # upload/download/delete/get_public_url + client singleton
│   │
│   ├── alembic/
│   │   ├── env.py                 # async migrations; overrides url from settings.DATABASE_URL
│   │   └── versions/              # 6 migrations, single head `663b3fea3024`
│   │       ├── 477cee72edc4_init_tables.py
│   │       ├── c008bb4f3f48_update_sub_process_columns.py
│   │       ├── 90a1d6a26343_create_doc_tables.py
│   │       ├── 1b0b616e08c6_replace_value_within_.py
│   │       ├── 873c0c4616ea_add_foreign_key_indices.py
│   │       └── 663b3fea3024_update_sub_process_columns.py   # HEAD
│   │
│   ├── scripts/                   # ⚠ all four import `fire`, which is NOT a dependency (§14)
│   │   ├── chat_llama.py          # interactive CLI over the SSE API (uses sseclient-py)
│   │   ├── build_vector_tables.py # run_setup() DDL by hand
│   │   ├── dedupe_vector_store.py # SQL dedupe of data_pg_vector_store
│   │   └── upsert_document.py     # insert a Document row by URL
│   │
│   └── tests/
│       ├── conftest.py            # sets dummy DATABASE_URL / GOOGLE_API_KEY / SUPABASE_* before import
│       ├── app/chat/test_engine.py# 8 tests: singleton embed_dim + get_chat_history matrix
│       └── app/test_refactored.py # 7 tests: NSE metadata, storage, ingestion, upload, health
│
└── frontend/
    ├── index.html                 # Google Fonts (Fraunces / Space Grotesk / IBM Plex Mono) + #root
    ├── package.json               # scripts: dev, build, preview ONLY
    ├── vite.config.ts             # react + tailwind + singlefile; alias `@` → src; NO dev proxy
    ├── tsconfig.json              # strict, noUnusedLocals/Parameters, noEmit, jsx react-jsx
    └── src/
        ├── main.tsx               # createRoot + StrictMode
        ├── App.tsx                # Shell: Ticker / Sidebar / view switch / drawers / splash / Analytics
        ├── store.tsx              # the single React-context store (documents, threads, streaming, health, toasts)
        ├── index.css              # Tailwind v4 @theme design tokens + grain, scrollbars, markdown tables
        ├── lib/
        │   ├── api.ts             # api facade + MockTransport (active) + RealTransport (incomplete)
        │   ├── types.ts           # domain types (⚠ first 22 lines swallowed by an unterminated comment)
        │   ├── mockData.ts        # 5 seeded filings, 4 canned Q&A banks, ticker data, suggestions
        │   └── format.ts          # labels, dates, byte formatting, uid/nowIso helpers
        ├── utils/cn.ts            # clsx + twMerge (dead code)
        └── components/
            ├── ChatView.tsx       # header, hero empty state, message list, scope picker, composer slot
            ├── LibraryView.tsx    # table, search, drag-drop, UploadDrawer, DocDetailDrawer
            ├── MessageItem.tsx    # user/assistant bubbles, research trail, sources grid, copy
            ├── ResearchTrail.tsx  # collapsible sub-process timeline
            ├── CiteMarkdown.tsx   # `[n]` → clickable citation chip + prose styles
            ├── SourceDrawer.tsx   # right-hand passage viewer ("open in library")
            ├── Composer.tsx       # auto-grow textarea, ⌘K focus, Enter/⇧↵, stop button
            ├── Sidebar.tsx        # brand, nav, thread list with inline delete confirm, health dot
            ├── Toasts.tsx         # bottom-right toast stack
            ├── Ticker.tsx         # marquee market strip
            └── Monogram.tsx       # coloured 2-letter company tile
```

---

## 4. ARCHITECTURE & DESIGN PATTERNS

### 4.1 Shape

```
Browser (React 19 SPA, mock transport today)
   │  fetch / EventSource        (target: /api/**)
   ▼
FastAPI (uvicorn, N workers)  ──►  PostgreSQL  (relational: conversation/message/document)
   │        │                  ──►  pgvector    (table data_pg_vector_store, 3072-d)
   │        └──► Supabase Storage (documents/{id}/original.pdf)
   └──► Google Gemini (chat + embeddings)
```

**One database for both relational state and vectors.** There is no separate vector DB, no
cache, no queue. A single uvicorn process pool serves everything; heavyweight indexing happens
**inside the upload request** (synchronously).

### 4.2 The three-tier RAG harness (`backend/app/chat/engine.py:181` `get_chat_engine`)

```
Tier 1  ReActAgent (Gemini, max_iterations=6, SYSTEM_MESSAGE context)
        │  exactly ONE tool: `document_question_engine`
Tier 2  SubQuestionQueryEngine (LLMQuestionGenerator, use_async=True, custom response synth)
        │  one QueryEngineTool per document, each ExactMatchFilter(db_document_id=…)
Tier 3  VectorStoreIndex.as_query_engine(similarity_top_k=3, filters=…)
        │
        └── pgvector (single shared table, cosine)
```

### 4.3 Patterns inventory (and where they live)

| Pattern | Implementation |
|---|---|
| **Repository / data-access module** | `app/api/crud.py` — the only place mixing SQLAlchemy; endpoints stay thin |
| **Dependency injection** | `Depends(get_db)` (`app/api/deps.py:6`) yields one `AsyncSession` per request |
| **Module-level singletons** | `pg_vector.singleton_instance` (`pg_vector.py:10,66`), `storage.supabase._supabase_client` (`supabase.py:20`) |
| **Lazy initialisation** | Supabase client created on first use; vector store created on first `get_vector_store_singleton()` |
| **Idempotent bootstrap + env handoff** | `app/main.py:47` `FINCITE_BOOTSTRAP_DONE`; parent runs `_bootstrap()` once, workers inherit the flag |
| **Observer / callback bus** | LlamaIndex `BaseCallbackHandler` → `ChatCallbackHandler` (`chat/messaging.py:33`) → `anyio` memory channel |
| **Producer/consumer streaming** | task runs `handle_chat_message`, coroutine `event_publisher` drains the channel (`endpoints/conversation.py:110-178`) |
| **Full-state snapshots over deltas** | every SSE frame is a serialized `schema.Message` (content + sub_processes grow monotonically) |
| **Compensating transaction** | upload rolls back Storage object **and** DB row when indexing fails (`documents.py:149-174`) |
| **Transport facade / strategy** | `frontend/src/lib/api.ts` `USE_MOCK` switch between `MockTransport` and `RealTransport`, same method surface |
| **Context store (no Redux/router)** | `frontend/src/store.tsx` — one `createContext`, ~30 fields, all mutations via `patchConversation` |
| **Schema-first API** | Pydantic v2 models in `app/schema.py` used as `response_model` / annotations |
| **Derived-state components** | `ResearchTrail` auto-collapses when all steps finish; ChatView sticks to bottom unless user scrolls up |

### 4.4 Invariants — break these and the product silently degrades

1. **Every vector node carries `db_document_id`** (`DB_DOC_ID_KEY`, `chat/constants.py:1`).
   Without it, per-document filtering and citations both fail.
2. **Node metadata must include `page_label`** — `Citation.from_node` does
   `int(node.source_node.metadata["page_label"])` (`schema.py:49`). Missing key ⇒ KeyError.
3. **`VECTOR_STORE_EMBED_DIM` must equal the embedding model's dimension (3072).** Vectors of a
   different width cannot share the table.
4. **pgvector table name** is `data_` + `VECTOR_STORE_TABLE_NAME` (LlamaIndex convention) ⇒
   `data_pg_vector_store`.
5. **Alembic must be at head before the app boots** or `_bootstrap()` raises
   (`main.py:95-98`).
6. **`alembic.ini` is resolved relative to CWD** ⇒ commands must run from `backend/`.

---

## 5. COMPONENT INTERCONNECTIONS (who calls whom)

### 5.1 Backend call graph

```
app/main.py
  ├─ core/config.py            settings = Settings()   (import-time; validates env)
  ├─ api/api.py                api_router → endpoints/{conversation,documents,health}
  ├─ db/wait_for_db.py         check_database_connection()      ← _bootstrap()
  ├─ chat/pg_vector.py         get_vector_store_singleton()     ← _bootstrap(), lifespan, upload, engine
  ├─ llama_index_settings.py   _setup_llama_index_settings()    ← lifespan (in asyncio.to_thread)
  └─ alembic (Config("alembic.ini"), psycopg2 engine)           ← _bootstrap()

endpoints/documents.py: upload_document_endpoint
  ├─ api/crud.py                     fetch_document_by_content_hash, create_document, delete_document_by_id
  ├─ storage/supabase.py             upload_document, get_document_url, delete_document
  ├─ ingestion/pdf.py                ingest_document
  │    ├─ storage/supabase.py          download_document
  │    ├─ llama_index PDFReader        (page-level Documents + extra_info{db_document_id})
  │    └─ llama_index VectorStoreIndex.from_documents → pgvector
  └─ chat/pg_vector.py               get_vector_store_singleton

endpoints/conversation.py: message_conversation (SSE)
  ├─ api/crud.py                     fetch_conversation_with_messages, fetch_message_with_sub_processes
  ├─ chat/messaging.py               handle_chat_message, StreamedMessage, StreamedMessageSubProcess
  │    └─ chat/engine.py               get_chat_engine
  │         ├─ chat/pg_vector.py         get_vector_store_singleton
  │         ├─ chat/utils.py             build_title/description_for_document
  │         ├─ chat/qa_response_synth.py get_custom_response_synth
  │         ├─ storage/supabase.py       download_document  (only on re-index fallback)
  │         ├─ chat/constants.py         DB_DOC_ID_KEY, SYSTEM_MESSAGE
  │         └─ llama_index ReActAgent / SubQuestionQueryEngine / Gemini
  └─ chat/messaging.py:ChatCallbackHandler → anyio send_chan → event_publisher → EventSourceResponse
```

### 5.2 Frontend call graph

```
main.tsx → App.tsx (StoreProvider)
  ├─ Shell: boot() (store) + 25 s health poll (store.checkHealth → api.health)
  ├─ Ticker            (lib/mockData TICKS)
  ├─ Sidebar           (store: view, conversations, documents, health, deleteConversation)
  ├─ ChatView          (store: active, documents, send, setView)
  │   ├─ Hero          (lib/mockData SUGGESTIONS)
  │   ├─ ScopePicker   (store.setScope)
  │   ├─ MessageItem ──► CiteMarkdown (onCite → store.openSource)
  │   │              └─ ResearchTrail (message.sub_processes)
  │   └─ Composer      (store.send / stopStreaming)
  ├─ LibraryView       (store: documents, uploadFiles, refreshDocuments, setLibraryOpenDocId)
  │   ├─ DocRow → StatusPill
  │   ├─ UploadDrawer  (store.uploadFiles)
  │   └─ DocDetailDrawer (store.startScopedChat, uploadFiles)
  ├─ SourceDrawer      (store.selectedSource → setLibraryOpenDocId + setView("library"))
  └─ Toasts            (store.toasts)
```

`store.send()` is the hub: it creates a conversation if needed, then calls
`api.streamMessage(id, q, handlers)` and patches the conversation from `onUserMessage` /
`onAssistantCreated` / `onSubProcess` / `onToken` / `onDone` / `onError`.

---

## 6. KEY ENTRY POINTS & STARTUP SEQUENCE

### 6.1 Backend — `app.main:start` (console script `start`, `pyproject.toml:45`)

`start()` at `main.py:165`:

1. `_setup_logging(settings.LOG_LEVEL)` — root logger to stdout,
   `"%(asctime)s [%(threadName)] [%(levelname)] %(message)s"`.
2. `_setup_sentry()` — only if `SENTRY_DSN` is set (`traces_sample_rate=0.1`).
3. `asyncio.run(_bootstrap(release_connections=True))` (`main.py:81`):
   - `check_database_connection()` — up to 30 attempts, 1 s apart;
   - Alembic head check: `Config("alembic.ini")`, URL rewritten
     `postgresql+asyncpg://` → `postgresql+psycopg2://`, `create_engine(...)`, compare
     `MigrationContext.get_current_heads()` with `ScriptDirectory.get_heads()`;
   - `(await get_vector_store_singleton()).run_setup()` — `CREATE EXTENSION IF NOT EXISTS vector`
     + `base.metadata.create_all` for the vector tables (guarded by module global `did_run_setup`);
   - `split_by_sentence_tokenizer()` — warms the NLTK punkt download;
   - `vector_store.close()` — parent releases connections.
4. `os.environ["FINCITE_BOOTSTRAP_DONE"] = "1"`.
5. `uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=LOG_LEVEL=="DEBUG",
   workers=BACKEND_WORKERS)` — **reload ignores workers** (uvicorn behaviour).

### 6.2 Per-worker lifespan (`main.py:119`)

1. Run `_bootstrap()` **only if** `FINCITE_BOOTSTRAP_DONE != "1"` (i.e. when launched with
   `uvicorn app.main:app` directly).
2. `await asyncio.to_thread(_setup_llama_index_settings)` — Gemini constructor performs a
   blocking model-metadata lookup, so it must not run on the event loop.
3. `(await get_vector_store_singleton()).ensure_initialized()` — creates this process's engines,
   **no DDL**.
4. `yield` → serve; on shutdown `vector_store.close()` disposes the shared engine.

### 6.3 App object

`app = FastAPI(title=settings.PROJECT_NAME, ...)` at `main.py:141`:
docs at `/api/docs`, ReDoc at `/api/redoc`, OpenAPI at `/api/openapi.json`; CORS middleware only
when `BACKEND_CORS_ORIGINS` is non-empty; `app.include_router(api_router, prefix="/api")`.

### 6.4 Other entry points

| Entry point | Command |
|---|---|
| Alternate server launch | `uvicorn app.main:app --host 0.0.0.0 --port 8000` (CWD `backend/`) |
| Migrations | `uv run alembic upgrade head` (CWD `backend/`) |
| Migrations (async env) | `alembic/env.py:92` → `asyncio.run(run_async_migrations())` |
| SSE CLI | `uv run python scripts/chat_llama.py --base_url http://localhost:8000` (needs only `requests` + `sseclient-py`; this script does **not** need `fire`) |
| Vector DDL / dedupe / upsert | `scripts/{build_vector_tables,dedupe_vector_store,upsert_document}.py` — all require `fire` (§14) |
| Frontend | `index.html` → `src/main.tsx` → `createRoot(<StrictMode><App/></StrictMode>)` |
| Frontend build | `npx vite build` → single inlined `dist/index.html` |

---

## 7. DATA MODELS & SCHEMAS

Deep reference: `docs/agents/DATA_MODELS.md`.

### 7.1 Relational tables (`backend/app/models/db.py`, base in `models/base.py`)

All tables inherit `Base` (`models/base.py:6`): `id UUID PK` (default
`uuid_generate_v4()`), `created_at` / `updated_at` (`server_default now()`, `onupdate`),
`__tablename__` auto-lowercased class name.

| Table | Columns (beyond base) | Notes |
|---|---|---|
| `conversation` | — | container for messages + document scope |
| `document` | `url String NOT NULL UNIQUE`, `metadata_map JSONB` | `url` = Supabase public URL |
| `conversationdocument` | `conversation_id FK`, `document_id FK` | M:N join, both indexed |
| `message` | `conversation_id FK`, `content String`, `role`, `status` | `status` default `PENDING` |
| `messagesubprocess` | `message_id FK`, `source`, `status`, `metadata_map JSONB` | one row per LlamaIndex callback event |

**Enums** (`models/db.py`): `MessageRoleEnum` = `user|assistant`;
`MessageStatusEnum` = `PENDING|SUCCESS|ERROR`;
`MessageSubProcessStatusEnum` = `PENDING|FINISHED`;
`MessageSubProcessSourceEnum` = every `CBEventType` name **plus**
`CONSTRUCTED_QUERY_ENGINE` and `SUB_QUESTIONS` (`models/db.py:26-34`). PG type names equal the
Python enum class names (`to_pg_enum`, `models/db.py:37`).

**`document.metadata_map` shape** (written by `documents.py:143-147`):

```jsonc
{
  "nse_document": {              // key = DocumentMetadataKeysEnum.NSE_DOCUMENT
    "company_name": "Reliance Industries",   // required
    "company_symbol": "RELIANCE",
    "document_type": "annual_report",        // annual_report|financial_results|corporate_filing|investor_presentation|other
    "financial_year": "2025",
    "report_date": "2025-08-28T12:00:00",
    "exchange": "NSE",
    "original_filename": "reliance-ar.pdf"
  },
  "content_hash": "<sha256 hex>",           // used for duplicate detection
  "original_filename": "reliance-ar.pdf"
}
```

### 7.2 API schemas (`backend/app/schema.py`)

`Base` (id/created_at/updated_at, `from_attributes=True`) → `Conversation`, `Message`,
`MessageSubProcess`, `Document`, `DocumentUploadResponse`; plus `ConversationCreate
{document_ids: List[UUID]}`, `UserMessageCreate {content}`, `NSEDocumentMetadata`,
`NSEDocumentTypeEnum`, `DocumentMetadataKeysEnum`, `Citation`, `QuestionAnswerPair`,
`SubProcessMetadataKeysEnum` (= `EventPayload.SUB_QUESTION.value`).

`Citation.from_node` (`schema.py:47`) converts a `NodeWithScore` into
`{document_id, text, page_number, score}` — this is the only citation source of truth.

### 7.3 Vector store

`data_pg_vector_store` (LlamaIndex-managed, `VECTOR_STORE_TABLE_NAME` + `data_` prefix),
`embed_dim = VECTOR_STORE_EMBED_DIM` (3072), cosine distance, columns include
`id, text, metadata_ (JSONB), node_id, embedding`. Every row's `metadata_->>'db_document_id'`
holds the owning `document.id`; `metadata_->>'page_label'` holds the PDF page.

### 7.4 Frontend domain types (`frontend/src/lib/types.ts`)

`NSEDocumentType`, `DocumentStatus`, `DocumentMetadata`, `FinDocument`, `SubProcessSource`,
`SubProcessStatus`, `MessageSubProcess`, `MessageRole`, `MessageStatus`, `Source`,
`ChatMessage`, `Conversation`, `ConversationCreate`, `DocumentUploadResponse`, `HealthResponse`,
`View`. **These do not match the backend** (see §14.A/§14.K and `DATA_MODELS.md §6`).

---

## 8. API ROUTES / ENDPOINTS

All under `settings.API_PREFIX = "/api"`. Verified route table (enumerated from the live app):

| Method | Path | Handler | Request | Response |
|---|---|---|---|---|
| GET | `/api/health/` | `endpoints/health.py:11` | — | `{"status":"alive"}` (runs `SELECT 1`) |
| POST | `/api/document/upload` | `documents.py:50` | multipart: `file` + optional `company_name`, `company_symbol`, `financial_year`, `document_type`, `exchange` | **201** `DocumentUploadResponse {id,url,metadata_map,status:"indexed",created_at,updated_at}` |
| GET | `/api/document/` | `documents.py:186` | `?document_ids=<uuid>&document_ids=<uuid>` (repeatable) | `List[Document]`; **404 if empty** |
| GET | `/api/document/{document_id}` | `documents.py:205` | path UUID | `Document` or 404 |
| POST | `/api/conversation/` | `conversation.py:31` | `{"document_ids": ["<uuid>", …]}` | `Conversation` (with `messages`, `documents`); 404 if any id missing |
| GET | `/api/conversation/{conversation_id}` | `conversation.py:53` | path UUID | `Conversation` or 404 |
| DELETE | `/api/conversation/{conversation_id}` | `conversation.py:66` | path UUID | **204**; 404 if absent (⚠ 500 with messages, §14.E) |
| GET | `/api/conversation/{conversation_id}/message` | `conversation.py:81` | **query** `user_message=<text>` | `text/event-stream` of JSON `Message` snapshots |
| GET | `/api/conversation/{conversation_id}/test_message` | `conversation.py:181` | **query** `user_message=<text>` | single final `Message` (drains the SSE stream) |
| GET | `/api/docs` · `/api/redoc` · `/api/openapi.json` | FastAPI | — | Swagger / ReDoc / spec |

**Error conventions:** 400 invalid PDF/empty file; 404 missing conversation/document (and empty
document list); 422 indexing failed (file corrupt/unreadable) — the DB row and stored object are
deleted first; 500 storage upload or DB insert failure.

**SSE payload** — unnamed events, each frame is one complete serialized `schema.Message`:

```jsonc
{"id":"…","conversation_id":"…","role":"assistant","status":"PENDING",
 "sub_processes":[{"message_id":"…","source":"SUB_QUESTION","status":"FINISHED",
                   "metadata_map":{"sub_question":{"question":"…","answer":"…","citations":[…]}}}],
 "content":"partial answer text…","created_at":"…","updated_at":"…"}
```

Last two frames: the final `Message` with `status: "SUCCESS"` (or `ERROR`). The backend also
persists the user message and the assistant message (with all sub-processes) at the end.

Deep reference: `docs/agents/API_REFERENCE.md`.

---

## 9. CORE WORKFLOWS

Detailed traces: `docs/agents/WORKFLOWS.md`.

### W1 — Upload & index a filing (`POST /api/document/upload`)

1. `_validate_pdf` — content-type must be `application/pdf` (or absent) and bytes must start
   with `%PDF` (`documents.py:32`).
2. `hashlib.sha256(content)` → `crud.fetch_document_by_content_hash` (`documents.py:89`);
   a hit returns the **existing** document with `status: "indexed"` (idempotent, 201).
3. Derive `company_name` from the filename when not supplied; build `NSEDocumentMetadata`.
4. `uuid4()` → `storage.upload_document(content, id)` → `documents/{id}/original.pdf`.
5. `get_document_url(id)` → `crud.create_document` (DB row with `metadata_map`).
6. `ingest_document(db_doc, vector_store)`:
   `download_document` → temp file → `PDFReader.load_data(extra_info={db_document_id})` →
   `StorageContext(vector_store)` → `VectorStoreIndex.from_documents(show_progress=True)` →
   `index.set_index_id(document_id)`.
7. Failure handling: DB-insert failure deletes the storage object; indexing failure deletes both
   the DB row and the object, then raises **422**.

### W2 — Create a conversation (`POST /api/conversation/`)

1. Validate every `document_id` exists via `crud.fetch_documents(ids=…)`; missing ⇒ 404 with the
   list of missing ids (`conversation.py:39-48`).
2. `crud.create_conversation` inserts `conversation` + one `conversationdocument` row per doc,
   commits, refreshes, then re-reads with `joinedload(messages).subqueryload(sub_processes)` and
   `conversation_documents → document`.

### W3 — Ask a question (SSE) (`GET /api/conversation/{id}/message?user_message=`)

1. Load the conversation **before** the user message is persisted (so history excludes it).
2. Build an ephemeral user `Message`; create `anyio.create_memory_object_stream(100)`.
3. `event_publisher` starts `handle_chat_message` as an `asyncio` task and consumes
   `recv_chan`, maintaining an `OrderedDict[event_id → MessageSubProcess]` so start/end events
   merge into one row; yields a serialized `Message` snapshot per event.
4. `handle_chat_message` (`messaging.py:128`): build the engine (loads/creates a
   `VectorStoreIndex` per document, one tool per doc, SubQuestion engine, custom synth, ReAct
   agent with history + system prompt), emit `CONSTRUCTED_QUERY_ENGINE`, prepend the nudge
   `"Remember - if I have asked a relevant financial question, use your tools."`, then
   `astream_chat(templated_message)` and stream cumulative `content`.
5. `ChatCallbackHandler` converts every LlamaIndex `CBEventType` start/end into
   `StreamedMessageSubProcess` with `has_ended`, `event_id` and (for `SUB_QUESTION`) the
   `QuestionAnswerPair` (question, answer, citations).
6. On completion: persist user + assistant messages + sub-processes, then yield the final
   `Message`; `status` becomes `SUCCESS` or `ERROR`.
7. Empty answer ⇒ canned apology ("Sorry, I either wasn't able to understand your question…").

### W4 — Frontend question flow (mock)

`Composer.submit` → `store.send(q)` → create conversation if `activeId` is null →
`api.streamMessage` (mock walks a 4-step plan: Query understanding → Hybrid retrieval → Rerank
→ Answer synthesis, `lib/mockData.ts:188` `ANSWER_BANK`) → handlers patch the conversation →
`MessageItem` renders streaming text (`.stream-caret`) → `ResearchTrail` auto-collapses 1.4 s
after the last step → completion attaches `sources[]` → clicking `[n]` or a source card calls
`store.openSource` → `SourceDrawer` shows the passage, "open in library" jumps to `LibraryView`.

### W5 — Deploy bootstrap

`uv run start` → logging → Sentry → `_bootstrap` (DB wait → Alembic head check → pgvector DDL →
NLTK data → close) → flag → uvicorn with `BACKEND_WORKERS` → each worker lifespan configures
Gemini settings in a thread → opens its own pools → serves.

---

## 10. CONFIGURATION & ENVIRONMENT VARIABLES

`backend/app/core/config.py` (`Settings`, env prefix `""`, reads `.env`). Required: `DATABASE_URL`,
`GOOGLE_API_KEY`. Everything else has a default.

| Variable | Default | Notes / where used |
|---|---|---|
| `DATABASE_URL` | **required** | validator rewrites `postgres://`→`postgresql://`→`postgresql+asyncpg://`; rejects non-postgres (`config.py:54`) |
| `GOOGLE_API_KEY` | **required** | also exported to `os.environ` at import (`config.py:83`) for the Gemini SDK |
| `SUPABASE_URL` | `""` | Storage; `RuntimeError` if empty when used |
| `SUPABASE_SERVICE_ROLE_KEY` | `""` | server-side only, never returned to clients |
| `SUPABASE_STORAGE_BUCKET` | `annual-reports` | must exist in the Supabase project |
| `GEMINI_CHAT_LLM_NAME` | `models/gemini-1.5-flash` | LLM for agent, question-gen, synthesis |
| `GEMINI_EMBEDDING_MODEL_NAME` | `models/gemini-embedding-001` | must be 3072-d |
| `VECTOR_STORE_TABLE_NAME` | `pg_vector_store` | real table = `data_pg_vector_store` |
| `VECTOR_STORE_EMBED_DIM` | `3072` | asserted by a test (`test_engine.py:44`) |
| `PROJECT_NAME` | `fincite` | FastAPI title |
| `API_PREFIX` | `/api` | all routes + docs |
| `LOG_LEVEL` | `INFO` | one of DEBUG/INFO/WARNING/ERROR/CRITICAL; `DEBUG` ⇒ uvicorn reload + verbose agent traces |
| `BACKEND_WORKERS` | `4` | uvicorn workers (ignored when reload) |
| `BACKEND_CORS_ORIGINS` | `[]` | JSON list or comma-separated; empty ⇒ **no CORS middleware** |
| `SENTRY_DSN` | unset | enables Sentry |
| `FINCITE_BOOTSTRAP_DONE` | unset | internal handoff flag (`main.py:47`) |

**Frontend config:** only `VITE_API_URL` (read via `import.meta.env` at `lib/api.ts:34`,
default `http://localhost:8000`). **`USE_MOCK` is a hardcoded `true` constant** at
`lib/api.ts:32` — there is no env switch today.

`backend/.env.example` documents every variable; `docker-compose.yml` overrides `DATABASE_URL`
and `BACKEND_CORS_ORIGINS` for the local pgvector container.

---

## 11. DEVELOPMENT COMMANDS

Legend: ✅ executed in this workspace with the stated result · ❌ currently fails ·
unmarked commands were **not** run here (no database or Supabase credentials) and are given from
the code/README contract — treat them as unverified.

### Backend (`cd backend`)

```bash
uv sync                                  # install from uv.lock incl. dev group  ✅
cp .env.example .env                     # then fill DATABASE_URL / SUPABASE_* / GOOGLE_API_KEY
uv run alembic upgrade head              # migrate (CWD must be backend/)
uv run start                             # bootstrap + uvicorn on 0.0.0.0:8000
# or: uv run uvicorn app.main:app --port 8000
uv run pytest -q                         # 15 passed in ~8 s (no DB / API key needed) ✅
uv run alembic current                   # applied revision
uv run alembic heads                     # → 663b3fea3024 ✅ (single head)
docker compose up --build                # backend + ankane/pgvector (⚠ port map bug, §14.F)
```

### Frontend (`cd frontend`)

```bash
npm ci                                   # ✅
npm run dev                              # vite dev server (default :5173) — mock data only
npm run build                            # ✅ → dist/index.html (622 kB, 189 kB gzip, single file)
npm run preview                          # serve the build
npx tsc --noEmit                         # ❌ 5 errors today (§14.A) — fix before claiming "typecheck clean"
```

### Linting

There is **no configured linter**: `pylint` 2.17.5 is a dev dependency but no `.pylintrc`,
`setup.cfg`, or `[tool.pylint]` exists; the frontend has no ESLint/Prettier config or script.
Effectively, `tsc --noEmit` (or `vite build`) is the only static check. Do not add a lint step to
CI without also adding its config.

### Useful one-offs

```bash
# peek at the API contract
curl -s localhost:8000/api/openapi.json | jq '.paths | keys'

# stream an answer
curl -N "localhost:8000/api/conversation/<ID>/message?user_message=What%20was%20FY2025%20revenue%3F"

# non-streaming answer (Swagger-friendly)
curl "localhost:8000/api/conversation/<ID>/test_message?user_message=Hello"
```

---

## 12. CODING CONVENTIONS & PATTERNS

**Python**
- Absolute imports from `app.` (`from app.api import crud`), no relative imports.
- Async everywhere on the request path: `async def` endpoints, `AsyncSession`, `await
  db.execute(select(...))`, explicit `await db.commit()`; no commits inside read helpers.
- SQLAlchemy **2.0 style**: `select()/delete()`, `result.scalars().first()`,
  `model_validate(..., from_attributes=True)`; `joinedload`/`subqueryload` for eager loading.
- Errors: `HTTPException(status_code=…, detail=…)` in endpoints; `RuntimeError` in the storage
  layer (wrapped by endpoints); broad `except Exception` **only** for index-load fallback and
  storage cleanup; always `logger.warning/error(..., exc_info=True)` before a 5xx.
- Logging: module-level `logger = logging.getLogger(__name__)`; `%s` lazy formatting, never
  f-strings in log calls.
- Pydantic v2 (`model_validate`, `model_dump(mode="json")`, `field_validator`) — but note
  `messaging.py:86` still calls the deprecated `.dict()`.
- Type hints on all public functions; `Optional[...]`/`| None`; `Dict/List` from `typing` in
  older modules, builtin generics in newer ones (both present — match the file you edit).
- Docstrings: triple-quoted, often containing an ASCII flow diagram (see `engine.py`,
  `ingestion/pdf.py`, `storage/supabase.py`). Keep that style when adding modules.
- Constants live in `chat/constants.py` or module-level `_UPPER` names (e.g. `_ALLOWED_CONTENT_TYPES`).
- DB naming: singular lowercase table names derived from the class (`messagesubprocess`).

**TypeScript / React**
- Function components, default export at file end; `memo()` for `MessageItem` and `CiteMarkdown`.
- No router, no Redux: everything flows through `useStore()`.
- Local state via `useState`; derived data via `useMemo`; refs for timers/cancellation
  (`cancelStream`, `pollers`, `dragDepth`).
- Styling: Tailwind utility classes inline; **design tokens only** (`bg-bone`, `text-ink`,
  `border-line`, `text-accent`, `bg-soot`, `text-moss`, `bg-pine`, `text-rust`, `font-display`,
  `font-mono`, `tnum`) defined in `src/index.css` `@theme`. No hex literals in components
  (except `Monogram`'s company hues from `mockData`).
- Typography scale is explicit and tiny (`text-[9.5px]`, `text-[13px]`) — copy neighbouring
  values instead of inventing.
- Motion: `framer-motion` with the shared easing `[0.22, 1, 0.36, 1]` or `[0.32, 0.72, 0, 1]`.
- Accessibility: every icon-only button carries `aria-label`.
- Comments: `/* ---- section ---- */` dividers; disabled UI blocks are left commented out in
  place — that is intentional (do not "clean up" them without asking).

---

## 13. TESTING STRATEGY

**Framework:** `pytest` 7.4.0 + `pytest-asyncio` 0.23.8, tests under `backend/tests/`, no
`pytest.ini`/`pyproject` config (strict asyncio mode ⇒ async tests need
`@pytest.mark.asyncio`). **Verified: `uv run pytest -q` → 15 passed, 4 warnings, ~8 s.**

**`tests/conftest.py`** sets `DATABASE_URL`, `GOOGLE_API_KEY`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY` via `os.environ.setdefault` **before** any app import — this is why
the suite runs with no services. Add any new required setting there.

**Existing coverage (15 tests):**

| File | Tests | What they pin |
|---|---|---|
| `tests/app/chat/test_engine.py` | 8 | `get_vector_store_singleton` passes `embed_dim=3072` (monkeypatched `from_params`); `get_chat_history` matrix: happy path, consecutive same-role messages, empty input, ERROR-status user/assistant filtering, blank content stripping, unpaired messages |
| `tests/app/test_refactored.py` | 7 | `NSEDocumentMetadata` parsing + defaults; Supabase storage helpers with `@patch("app.storage.supabase.create_client")`; `ingest_document` flow (PDFReader/VectorStoreIndex/StorageContext patched); upload endpoint success + invalid file; health endpoint |

**Patterns to reuse**
- Patch **where the name is used**, not where it is defined:
  `@patch("app.api.endpoints.documents.upload_document")` (module attribute),
  `@patch("app.ingestion.pdf.PDFReader")`, `@patch("app.storage.supabase.create_client")`.
- `AsyncMock(spec=AsyncSession)` for the DB dependency; `AsyncMock(spec=UploadFile)` with
  `read.return_value = b"%PDF-1.4 …"`.
- Event-loop bridging in sync tests: `asyncio.run(coro)` (see
  `test_get_vector_store_singleton_uses_3072_embedding_dimension`).
- Pydantic message doubles: subclass `schema.Message` with defaults
  (`class MockMessage(Message): conversation_id: UUID = uuid4(); sub_processes: list = []`).
- Reset module singletons when a test touches them (`supabase._supabase_client = None`,
  `pg_vector.singleton_instance`).

**Adding a test:** put it next to the mirrored app path (`tests/app/<pkg>/test_<module>.py`),
mark async tests, avoid real network/DB, and assert on behaviour + call arguments. There is no
integration/DB test harness and no frontend test runner — if you need one, propose it explicitly
rather than silently adding a new framework.

---

## 14. KNOWN ISSUES & TECH DEBT

Ranked by likelihood of biting an agent. Each item was checked against the code in this
session; re-verify before acting on one you intend to fix.

**A. Frontend does not typecheck (5 errors) — root cause is a broken comment.**
`frontend/src/lib/types.ts` lines 1-4 open `/**` and never close it before
`export type NSEDocumentType`. The next `*/` is on line 22, so `NSEDocumentType`,
`DocumentStatus`, `DocumentMetadata` and `FinDocument` are swallowed by the comment.
`npx tsc --noEmit` reports:
`Sidebar.tsx(3,3) TS6133 'Activity' unused`, `format.ts(1,15) TS2305 DocumentStatus`,
`format.ts(1,31) TS2305 NSEDocumentType`, `types.ts(26,18) TS2552`, `types.ts(38,11) TS2304`.
`vite build` still **succeeds** (esbuild strips types), which is why this is easy to miss.
Fix = close the comment (`*/`) and drop the unused `Activity` import.

**B. The frontend is mock-only and its "real" transport does not match the API.**
`USE_MOCK = true` is a hardcoded const (`lib/api.ts:32`); to hit the backend you must edit source.
`RealTransport` is stale: it sends `?q=` instead of `?user_message=`
(`api.ts:417`), listens for `sub_process`/`delta`/`done` events while the backend emits unnamed
`Message` snapshots (`api.ts:420-433`), and posts `{title, document_scope}` instead of
`{document_ids}` (`api.ts:399-406`). `EventSource` also cannot set an `Accept` header.
Expect to rewrite this transport, not patch it.

**C. README drift (root `README.md` describes files/scripts that do not exist).**
Missing: `frontend/src/lib/backend.ts`, `frontend/README.md`,
`backend/CONTEXT.md` (referenced by `backend/README.md`), npm scripts `dev:mock`, `typecheck`,
`check:adapter`, the Vite dev proxy / `VITE_PROXY_TARGET`, the NSE-metadata upload form
(`UploadDrawer` sends only `{name,size,type}`), thread persistence across reloads
(conversations live only in React state), and "15 passing backend tests" is correct but
"`npm run typecheck` zero errors" is false. Trust code and this file.

**D. Streaming concurrency is fragile.** `handle_chat_message` and `event_publisher` both do
`async with send_chan` on the *same* stream (`messaging.py:133`, `conversation.py:113`) — double
close; `ChatCallbackHandler.on_event_*` fires `asyncio.create_task` fire-and-forget
(`messaging.py:51,65`), so sub-process frames can arrive after the channel closes; the code
inspects the private `send_chan._closed` (`messaging.py:102`, `conversation.py:156`). Any change
here needs a real end-to-end test.

**E. `DELETE /api/conversation/{id}` fails for non-empty conversations.** `crud.delete_conversation`
issues a bare `DELETE FROM conversation`; `message.conversation_id` /
`conversationdocument.*` FKs have **no `ON DELETE CASCADE`** (migration `477cee72edc4`), so
Postgres raises a FK violation → unhandled 500. The frontend hides it ("local delete anyway",
`store.tsx:286`). Fix = cascade in the model + migration, or delete children explicitly.

**F. `docker-compose.yml` database port is wrong.** `127.0.0.1:5433:5433` maps host 5433 to
container 5433, but Postgres listens on **5432** inside the image. Use `5433:5432`. (`version:
'3'` is also obsolete.) Backend↔db works because the service connects to `db:5432`.

**G. Three of the four `backend/scripts/*.py` are unusable as written.**
`build_vector_tables.py`, `dedupe_vector_store.py` and `upsert_document.py` import `fire`, which is
not declared in `pyproject.toml`/`uv.lock` (`import fire` → `ModuleNotFoundError`, verified).
`chat_llama.py` is fine (it only needs `requests` + `sseclient-py`). Either add `fire` or replace
the CLI layer with `argparse`.

**H. Index reuse is not actually verified.** `build_doc_id_to_index_map`
(`engine.py:126-148`) calls `VectorStoreIndex.from_vector_store`, which does not raise for a
document with zero vectors — so the "re-index from storage" fallback is effectively dead code
and a document whose vectors are missing yields an empty tool. Do not rely on that except branch.

**I. Indexing runs inside the upload request.** `ingest_document` performs PDF parsing and Gemini
embedding synchronously in the request handler (blocking the worker for minutes on a 300-page
report). The roadmap calls for a job queue; until then, large uploads look like timeouts.

**J. No document deletion path.** There is no `DELETE /api/document/{id}` and no cleanup of
`data_pg_vector_store` rows, so removing a filing requires manual SQL (see
`scripts/dedupe_vector_store.py` for the table name).

**K. Frontend/backend type drift.** `FinDocument.metadata` uses `nse_symbol`, `fiscal_year`,
`period`, `pages`, `file_size`; the backend uses `company_symbol`, `financial_year`,
`original_filename` and no page/size counters. Document-type enums differ
(`quarterly_results`/`concall_transcript`/`shareholding_pattern`/`corporate_announcement` in the
UI vs `financial_results`/`corporate_filing`/`investor_presentation`/`other` in the API).
Sub-process enums differ too (UI: `llm|retrieval|rerank|parser`; API: LlamaIndex
`CBEventType` names). A mapper layer is required before real mode works.

**L. `GET /api/document/` returns 404 for an empty library** (`documents.py:199`) instead of
`[]` — hostile to clients that poll.

**M. Import-time side effects.** `chat/engine.py:64` calls `nest_asyncio.apply()` on import;
`core/config.py:83` writes `os.environ["GOOGLE_API_KEY"]`. Importing `app.main` therefore
requires `DATABASE_URL` + `GOOGLE_API_KEY` to be set (or the test defaults from `conftest.py`).

**N. `_bootstrap()` depends on CWD.** `Config("alembic.ini")` is relative; running the app from
outside `backend/` raises. Same for `uv run alembic`.

**O. Stale/incidental values.** `alembic.ini` still points at `llama_app_db`;
`scripts/upsert_document.py` says "SEC"; `dedupe_vector_store.py` hardcodes
`data_pg_vector_store` and ignores `VECTOR_STORE_TABLE_NAME`; `Citation.document_id` is typed
`UUID` but its validator returns `str` (`schema.py:39-44`); `Message.content` is non-optional in
Pydantic but nullable in the DB; `.dict()` (Pydantic v1 API) in `messaging.py:86` emits
deprecation warnings; `messagesubprocess.content` exists in the first migration but not in the
model.

**P. Dead code / unused imports.** `frontend/src/utils/cn.ts` is never imported; `Sidebar.tsx`
imports `Activity` (TS error); `crud.py` imports `uuid as uuid_module` unused; several
commented-out UI blocks remain in `Sidebar.tsx`, `ChatView.tsx`, `LibraryView.tsx`.

**Q. No auth, tenancy, rate limiting, or CI.** Every endpoint is public; the Supabase
service-role key must never leak to the client; there is no `.github/workflows`.

**R. Dependency age.** `sentry-sdk` 1.29.2 and `uvicorn` 0.22.0 are old; the Gemini SDK
(`google-generativeai`) is end-of-life and emits a `FutureWarning` on every import (visible in
the pytest output). Not urgent, but a migration to `google-genai` will eventually be required.

---

## 15. AGENT RULES

### ALWAYS

1. **Run backend commands from `backend/`** (`alembic.ini`, `.env`, `.venv` are all CWD-relative).
   Frontend commands from `frontend/`.
2. **Keep `db_document_id` on every vector node and `page_label` in metadata.** They are the
   backbone of per-document filtering and citations (§4.4).
3. **Mirror the existing layering:** endpoint (HTTP + validation) → `crud.py` (SQL) → model.
   Never write SQL/ORM queries inside an endpoint or inside `chat/`.
4. **Keep the SSE contract as full `Message` snapshots**, unnamed events, monotonic
   `content`/`sub_processes`. The frontend's whole streaming design depends on it.
5. **Use Pydantic v2 APIs** (`model_validate`, `model_dump`, `field_validator`) in new code and
   keep `app/schema.py` as the single source of API shapes.
6. **Add or update a test** for any change to `crud.py`, `ingestion/`, `storage/`, or the upload
   endpoint, following the patch-where-used + `AsyncMock` patterns in §13.
7. **Run `uv run pytest -q` (backend) and `npx tsc --noEmit` (frontend) before declaring work
   done.** Report the *actual* output; typecheck currently fails (§14.A).
8. **Update `backend/.env.example` when you add a setting**, and `Settings` in
   `core/config.py` with a sane default so tests keep passing without new env vars.
9. **New migrations:** `uv run alembic revision --autogenerate -m "…"`, review the diff, keep a
   single head, and remember `_bootstrap()` refuses to start if the DB is not at head.
10. **Preserve the domain prompt contract** (tools first, exact units, financial year, page
    citations, no fabrication) whenever you touch `constants.py` or `qa_response_synth.py`.
11. **Match the frontend design system** — tokens in `index.css`, tiny mono labels, `aria-label`
    on icon buttons, framer-motion easings already in use.
12. **State uncertainty plainly.** If you could not run something, say which command and why.

### NEVER

1. **Never change `VECTOR_STORE_EMBED_DIM` (3072) or the embedding model without recreating the
   vector table** — rows of mixed dimensionality break similarity search.
2. **Never send blocking work onto the event loop.** PDF parsing, Gemini model construction, and
   any `requests` call must be wrapped (`asyncio.to_thread`) or moved to a task.
3. **Never expose `SUPABASE_SERVICE_ROLE_KEY`, `GOOGLE_API_KEY`, or `DATABASE_URL`** to the
   client, in logs, or in API responses.
4. **Never edit `alembic/versions/*.py` that already ran** (or delete rows from
   `alembic_version`); add a new revision instead.
5. **Never switch `USE_MOCK` to `false` and call it "connected"** — `RealTransport` does not
   implement the backend contract (§14.B). Fix the transport first and verify against a live API.
6. **Never delete the commented-out UI blocks or "unused" helpers as "cleanup"** without asking;
   they are deliberate parking spots for in-progress UI.
7. **Never trust `README.md` over the code.** If a doc claim is wrong, fix the doc in the same
   change (and note it here if it is a repeated trap).
8. **Never add a new framework** (test runner, linter, state library, router, ORM) without
   explicit user approval — this repo deliberately keeps a single store, one test framework, and
   no CSS-in-JS.
9. **Never commit `.env`, `node_modules/`, `dist/`, `.venv/`, or generated PDFs** (all ignored;
   keep new artifacts ignored too).
10. **Never assume the frontend typecheck is green, the delete endpoint works, or the scripts
    run** — all three are currently broken (§14.A, §14.E, §14.G).
11. **Never reformat unrelated files.** Diffs should be scoped; this codebase mixes legacy and
    modern Python styles on purpose.

---

### Quick "is it healthy?" checklist

```bash
cd backend  && uv run pytest -q                     # expect: 15 passed
cd backend  && uv run python -c "import app.main"   # needs DATABASE_URL + GOOGLE_API_KEY set
cd frontend && npx tsc --noEmit                     # expect: FAILS (§14.A) until the comment is fixed
cd frontend && npm run build                        # expect: single dist/index.html (~622 kB)
curl -s localhost:8000/api/health/                  # {"status":"alive"} — requires DB + env
```
