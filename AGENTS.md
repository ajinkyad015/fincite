# AGENTS.md — fincitee

> **Read this first, every session.** It is the map of this repository: what it is, how the
> pieces connect, what is verified working, and what is broken. Originally audited at commit
> `3b43329` (2026-10-24); M0/M1/M2 updates below were checked against the current branch on
> 2026-10-27. Where documentation (root `README.md`) disagrees with the code, **the code wins** — see §14.

**Repo:** `shinosuke0103/fincite_temp` · **License:** MIT · **Size:** ~90 tracked files (45 Python ·
14 TSX · 8 TS · 1 CSS) plus committed lockfiles and a README.

> **Update 2026-10-27 (chat creation failures + model swapping).** The chat LLM is now a
> **generic OpenAI-compatible client** (`llama_index.llms.openai_like.OpenAILike`), not
> `llama_index.llms.nvidia.NVIDIA`. The old client inferred `is_chat_model` /
> `is_function_calling_model` from a frozen model table and set both to `None` for newer ids
> (e.g. `nvidia/nemotron-3.5-bolt-e4b`), which made `get_response_synthesizer()` /
> `index.as_query_engine()` raise a pydantic `LLMMetadata` ValidationError on the first
> message. All model ids **and their capabilities** now come from `.env` — see §10.2 for the
> model-swap checklist. The follow-on `MissingGreenlet` in `crud.finalise_message()` (reading
> `message.id` after commit) is also fixed: async sessions use `expire_on_commit=False` and
> persistence never touches an expired ORM attribute. Verify with `cd backend && uv run pytest -q`
> (**70 passed**). Details: `app/llama_index_settings.py`, `app/core/config.py`,
> `app/chat/engine.py`, `app/api/crud.py`, `app/db/session.py`.

---

> **M2 update (2026-10-27 — frontend connected).** Real API mode is now the default
> (`VITE_USE_MOCK=1` is the only demo switch). `frontend/src/lib/wire.ts` owns DTO→domain
> translation, `frontend/src/lib/transport.ts` owns fetch/POST-SSE, and `store.tsx` rehydrates
> server-backed threads on boot/selection/terminal stream events. Uploads send real `File` bytes,
> document polling uses server status/backoff, scope changes PATCH the thread, delete errors are
> surfaced, and citations open `/api/document/{id}/file#page=N`. `scripts/smoke.sh` checks the live
> flow with a caller-supplied PDF. No new frontend test framework was added. Verified: backend
> **70 passed**, `npm run typecheck` **0 errors**, both `npm run build` and `npm run build:demo`
> succeed, and a temporary Node harness exercised the mapper/SSE adapter.

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
   Storage, parsed page-by-page, chunked, embedded with the configured embedding model (default
   NVIDIA Nemotron-3-Embed), and written into
   PostgreSQL/pgvector. Users then open a *conversation* scoped to 1..n documents and ask
   questions; answers stream over **SSE** as complete `Message` snapshots, with page-level
   citations and a persisted reasoning trace ("research trail").
2. **`frontend/`** — React 19 SPA ("research terminal"): thread rail, chat view, filing
   library with drag-and-drop upload, a live research-trail panel, clickable `[n]` citation
   chips and a source drawer. **M2 made the real API the default**, with server-backed threads,
   real PDF uploads, POST SSE, and page-linked citations; the mock transport remains an explicit
   demo mode behind `VITE_USE_MOCK=1`.

**Lineage.** The backend is a fork of a LlamaIndex + FastAPI "chat with documents" template
(originally SEC-focused) re-skinned for NSE filings. Fossils of the original: the default DB
name `llama_app_db` in `backend/alembic.ini:75`, "Upserts a single SEC document" in
`backend/scripts/upsert_document.py:9`, and the `CONSTRUCTED_QUERY_ENGINE` / `SUB_QUESTIONS`
sub-process enum values.

**Product invariants the prompts enforce** (`backend/app/chat/constants.py:3` `SYSTEM_MESSAGE`,
`backend/app/chat/qa_response_synth.py`): always call tools before answering; preserve units
exactly (₹ Crore / ₹ Lakh / USD Million); always name the financial year; cite page numbers;
never fabricate figures.

**What this project is NOT (yet):** no authentication, no multi-tenancy, no durable job queue,
no automated frontend test runner, and no end-to-end browser suite. Document deletion and CI now
exist; `scripts/smoke.sh` is a live-contract check requiring real services and a supplied PDF.

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
| `llama-index-llms-openai-like` | 0.3.4 | **chat LLM** — provider-agnostic `OpenAILike`; replaces `llama-index-llms-nvidia` (removed: its frozen model table produced `None` LLMMetadata booleans for newer ids). Pin threaded through core 0.12.23, see `pyproject.toml` |
| `llama-index-embeddings-nvidia` | 0.3.4 | `NVIDIAEmbedding` base class, subclassed as `_NVIDIAEmbedding` for config-driven request shape |
| `openai` | 1.81.0 | SDK under both clients (capped `<1.82` in `pyproject.toml`) |
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
- **OpenAI-compatible model providers (default: NVIDIA hosted NIMs)** — API at
  `https://integrate.api.nvidia.com/v1`, one `nvapi-…` key, chat id
  `meta/llama-3.3-70b-instruct` and embedding id `nvidia/nemotron-3-embed-1b`
  (2048 dims, native only) **by default only**. No model id is hardcoded in
  executable code: ids, endpoint, key and declared capabilities are env-driven
  (`core/config.py`). Both clients are built in `app/llama_index_settings.py`
  (`get_chat_llm()` = `OpenAILike`, `get_embed_model()` = config-driven
  `NVIDIAEmbedding` subclass); NIM embeddings are asymmetric (`input_type`
  passage vs query) unless `NVIDIA_EMBEDDING_REQUEST_STYLE=openai`.
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
├── scripts/smoke.sh               # M2 live API smoke test (health → upload → SSE → reload → delete)
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
│   │   ├── llama_index_settings.py# env-driven chat/embedding factories + global Settings + splitter
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
│       ├── conftest.py            # sets dummy DATABASE_URL / NVIDIA_API_KEY / SUPABASE_* before import
│       ├── app/chat/test_engine.py# 8 tests: singleton embed_dim + get_chat_history matrix
│       └── app/test_refactored.py # 7 tests: NSE metadata, storage, ingestion, upload, health
│
└── frontend/
    ├── index.html                 # Google Fonts (Fraunces / Space Grotesk / IBM Plex Mono) + #root
    ├── package.json               # dev / dev:mock / dev:real / build / build:demo / typecheck
    ├── vite.config.ts             # react + tailwind + singlefile; same-origin /api dev proxy
    ├── tsconfig.json              # strict, noUnusedLocals/Parameters, noEmit, jsx react-jsx
    └── src/
        ├── main.tsx               # createRoot + StrictMode
        ├── App.tsx                # Shell: Ticker / Sidebar / view switch / drawers / splash / Analytics
        ├── store.tsx              # the single React-context store (documents, threads, streaming, health, toasts)
        ├── index.css              # Tailwind v4 @theme design tokens + grain, scrollbars, markdown tables
        ├── lib/
        │   ├── api.ts             # facade + explicit-demo MockTransport; real mode is default
        │   ├── transport.ts       # fetch/ReadableStream POST SSE, AbortController, ApiError
        │   ├── wire.ts            # DTO → domain mappers + citation/trail derivation
        │   ├── types.ts           # strict UI domain types
        │   ├── mockData.ts        # demo-only seeded filings / canned Q&A / ticker / suggestions
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
   │        │                  ──►  pgvector    (table data_pg_vector_store, 2048-d)
   │        └──► Supabase Storage (documents/{id}/original.pdf)
   └──► configured OpenAI-compatible endpoint (chat + embeddings)
```

**One database for both relational state and vectors.** There is no separate vector DB, no
cache, no queue. A single uvicorn process pool serves everything; heavyweight indexing happens
**inside the upload request** (synchronously).

### 4.2 The three-tier RAG harness (`backend/app/chat/engine.py:181` `get_chat_engine`)

```
Tier 1  ReActAgent (env-selected chat model, max_iterations=6, SYSTEM_MESSAGE context)
        │  exactly ONE tool: `document_question_engine`
Tier 2  SubQuestionQueryEngine (LLMQuestionGenerator, use_async=True, custom response synth)
        │  one QueryEngineTool per document, each ExactMatchFilter(db_document_id=…)
Tier 3  VectorStoreIndex.as_query_engine(similarity_top_k=3, filters=…, llm=chat_llm)
        │
        └── pgvector (single shared table, cosine)

One `chat_llm` instance from `get_chat_llm()` is passed explicitly to the agent, the question
generator, the response synthesizer **and** both `from_defaults`/`as_query_engine` calls.
LlamaIndex resolves `Settings.llm` internally even when those components are supplied, so
passing it is what guarantees every tier uses the configured model (and that a missing global
cannot blow up with "No API key found for OpenAI").
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
| **Transport facade / strategy** | `frontend/src/lib/api.ts` switches between `MockTransport` and `RealTransport`; `wire.ts` maps DTOs and `transport.ts` handles fetch/SSE |
| **Context store (no Redux/router)** | `frontend/src/store.tsx` — one `createContext`, ~30 fields, all mutations via `patchConversation` |
| **Schema-first API** | Pydantic v2 models in `app/schema.py` used as `response_model` / annotations |
| **Derived-state components** | `ResearchTrail` auto-collapses when all steps finish; ChatView sticks to bottom unless user scrolls up |

### 4.4 Invariants — break these and the product silently degrades

1. **Every vector node carries `db_document_id`** (`DB_DOC_ID_KEY`, `chat/constants.py:1`).
   Without it, per-document filtering and citations both fail.
2. **Node metadata must include `page_label`** — `Citation.from_node` does
   `int(node.source_node.metadata["page_label"])` (`schema.py:49`). Missing key ⇒ KeyError.
3. **`VECTOR_STORE_EMBED_DIM` must equal the embedding model's dimension (2048).** Vectors of a
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
  ├─ llama_index_settings.py   get_chat_llm()/get_embed_model() ← env-driven model factories
  │                            _setup_llama_index_settings()    ← lifespan (in asyncio.to_thread)
  ├─ db/session.py             SessionLocal (expire_on_commit=False) ← all async DB work
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
  │         └─ llama_index ReActAgent / SubQuestionQueryEngine / configured chat LLM
  └─ chat/messaging.py:ChatCallbackHandler → anyio send_chan → event_publisher → EventSourceResponse
```

### 5.2 Frontend call graph

```
main.tsx → App.tsx (StoreProvider)
  ├─ Shell: boot() (health + documents + conversation list) + 25 s health poll
  ├─ Ticker            (lib/mockData TICKS)
  ├─ Sidebar           (store: view, conversations, documents, health, deleteConversation)
  ├─ ChatView          (store: active, documents, send, setView)
  │   ├─ Hero          (lib/mockData SUGGESTIONS)
  │   ├─ ScopePicker   (store.setScope)
  │   ├─ MessageItem ──► CiteMarkdown (onCite → store.openSource)
  │   │              └─ ResearchTrail (message.sub_processes)
  │   └─ Composer      (store.send / stopStreaming)
  ├─ LibraryView       (store: documents, uploadFiles, retryDocument, refreshDocuments)
  │   ├─ DocRow → StatusPill
  │   ├─ UploadDrawer  (store.uploadFiles)
  │   └─ DocDetailDrawer (store.startScopedChat, retryDocument; demo-only upload)
  ├─ SourceDrawer      (source passage + /api/document/{id}/file#page=N + library jump)
  └─ Toasts            (store.toasts)
```

`store.send()` is the hub: it creates `{title, document_ids}` if needed, then calls
`api.streamMessage(id, q, handlers)`. Full `onSnapshot`s are rAF-batched; terminal handlers
rehydrate `GET /api/conversation/{id}` so React state reflects the database.

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
2. `await asyncio.to_thread(_setup_llama_index_settings)` — builds the two configured clients
   and logs the effective model profile (no secrets). Construction is network-free since the
   generic `OpenAILike` chat client replaced the NVIDIA catalog-validating one, but keeping it
   off the event loop stays safe if a future provider SDK does blocking work in its constructor.
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
| `conversation` | `title String(200)`, `last_message_at DateTime` (indexed) | title derived from the first question; `last_message_at` orders the sidebar list |
| `document` | `url String NOT NULL UNIQUE`, `metadata_map JSONB`, `status`, `progress`, `error Text`, `page_count`, `file_size`, `content_hash String(64) UNIQUE` | `url` = Supabase public URL; `status` drives the ingestion UI |
| `conversationdocument` | `conversation_id FK`, `document_id FK` | M:N join, both indexed, both `ON DELETE CASCADE` |
| `message` | `conversation_id FK`, `content String`, `role`, `status`, `sources JSONB` | `status` default `PENDING`; `sources` = citations flattened onto the message |
| `messagesubprocess` | `message_id FK`, `source`, `status`, `name`, `duration_ms`, `metadata_map JSONB` | one row per LlamaIndex callback event; `name` is the research-trail label |

`document.status` lifecycle (enum `DocumentStatusEnum`, **lowercase** names == values):
`uploaded → parsing → chunking → embedding → indexing → ready`, with `failed` reachable from any
non-terminal state. Ingestion runs in `app/ingestion/jobs.py`, not in the upload request.

**Enums** (`models/db.py`): `DocumentStatusEnum` = `uploaded|parsing|chunking|embedding|indexing|ready|failed`;
`MessageRoleEnum` = `user|assistant`;
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

`Base` (id/created_at/updated_at, `from_attributes=True`) → `Conversation`, `ConversationSummary`,
`Message`, `MessageSubProcess`, `Document`, `DocumentUploadResponse`, `HealthResponse`,
`ConfigResponse`; plus `ConversationCreate {document_ids?: List[UUID], title?}`,
`ConversationUpdate {title?, document_ids?}`, `MessageCreate {content}` (`UserMessageCreate` is an
alias), `NSEDocumentMetadata`, `NSEDocumentTypeEnum`, `DocumentMetadataKeysEnum`, `Citation`, `Source`,
`QuestionAnswerPair`, `SubProcessMetadataKeysEnum` (= `EventPayload.SUB_QUESTION.value`) and the helper
`schema.citations_to_sources()` / `schema.normalise_fiscal_year()`.

`Citation.from_node` (`schema.py:47`) converts a `NodeWithScore` into
`{document_id, text, page_number, score}` — this is the only citation source of truth.

### 7.3 Vector store

`data_pg_vector_store` (LlamaIndex-managed, `VECTOR_STORE_TABLE_NAME` + `data_` prefix),
`embed_dim = VECTOR_STORE_EMBED_DIM` (2048), cosine distance, columns include
`id, text, metadata_ (JSONB), node_id, embedding`. Every row's `metadata_->>'db_document_id'`
holds the owning `document.id`; `metadata_->>'page_label'` holds the PDF page.

### 7.4 Frontend domain types (`frontend/src/lib/types.ts`)

`NSEDocumentType`, `DocumentStatus`, `DocumentMetadata`, `FinDocument`, `SubProcessSource`,
`SubProcessStatus`, `MessageSubProcess`, `MessageRole`, `MessageStatus`, `Source`,
`ChatMessage`, `Conversation`, `ConversationCreate`, `DocumentUploadResponse`, `HealthResponse`,
`View`, plus upload/update helper types. They are intentionally UI shapes; `wire.ts` is the sole
translation boundary from `schema.py` DTOs (M2).

---

## 8. API ROUTES / ENDPOINTS

All under `settings.API_PREFIX = "/api"`. Verified route table (enumerated from the live app):

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/health/` | — | `200 {status: healthy\|degraded, db, vector_store, version, uptime_s}` — never 5xx |
| GET | `/api/config/` | — | `200 {version, max_upload_mb, supported_content_types, auth_enabled, demo_mode}` |
| POST | `/api/document/upload` | multipart `file` + optional `company_name`, `company_symbol`, `financial_year`, `document_type`, `exchange` | **202** `DocumentUploadResponse {status:"uploaded"}`; **200** with the existing doc on a duplicate hash; 413 too large |
| GET | `/api/document/` | `?document_ids&status&q&limit&offset` | `List[Document]` — **`[]` when empty** |
| GET | `/api/document/{document_id}` | path UUID | `Document` (with `status`/`progress`/`error`) or 404 |
| GET | `/api/document/{document_id}/file` | `?download` | `application/pdf` proxied from storage (citation viewer) |
| POST | `/api/document/{document_id}/reindex` | path UUID | **202**, re-runs ingestion (409 if already running) |
| DELETE | `/api/document/{document_id}` | path UUID | **204**; vectors → storage → rows; **503** if vectors cannot be cleared |
| POST | `/api/conversation/` | `{document_ids?: [], title?}` | **201** `Conversation` (empty scope allowed) |
| GET | `/api/conversation/` | `?limit&offset&q` | `List[ConversationSummary]` (thread index, no messages) |
| GET | `/api/conversation/{conversation_id}` | path UUID | `Conversation` with `messages[].sub_processes[]` **and** `messages[].sources[]` |
| PATCH | `/api/conversation/{conversation_id}` | `{title?, document_ids?}` | `Conversation` (rename / re-scope) |
| DELETE | `/api/conversation/{conversation_id}` | path UUID | **204** (cascade-safe) |
| POST | `/api/conversation/{conversation_id}/message` | `{"content": "…"}` | `text/event-stream` of `Message` snapshots (**preferred**) |
| GET | `/api/conversation/{conversation_id}/message` | **query** `user_message=` | same stream (deprecated) |
| GET | `/api/conversation/{conversation_id}/test_message` | **query** `user_message=` | single final `Message` |
| GET | `/api/docs` · `/api/redoc` · `/api/openapi.json` | — | Swagger / ReDoc / spec |

**Error conventions:** 400 invalid PDF/empty file; 404 missing document/conversation; 409 nothing indexed
or a job already running; 413 over `MAX_UPLOAD_MB`; 422 validation; 502 storage unreachable;
503 vector store unavailable.

**SSE payload** — unnamed events, each frame is one complete serialized `schema.Message`:

```jsonc
{"id":"…","conversation_id":"…","role":"assistant","status":"PENDING","content":"partial text…",
 "sub_processes":[{"id":"…","message_id":"…","source":"SUB_QUESTION","status":"FINISHED",
                   "name":"What was FY24 revenue?","duration_ms":812,
                   "metadata_map":{"sub_question":{"question":"…","answer":"…","citations":[…]}}}],
 "sources":[{"index":1,"document_id":"…","page":41,"excerpt":"…","score":0.91}],
 "created_at":"…"}
```

The last frame is the final `Message` with `status: "SUCCESS"` or `"ERROR"`. The user message and the
assistant placeholder are persisted *before* generation, content is flushed during the stream, and the
terminal state (including `sources` and the trail) is written even if the client disconnects.

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

### W4 — Frontend question flow (real; demo mirrors it)

`Composer.submit` → `store.send(q)` → `POST /api/conversation/` if `activeId` is null →
`transport.ts` POSTs `{"content": q}` and reads unnamed SSE `Message` snapshots → `wire.ts`
maps cumulative content, trail steps and sources → store applies rAF-batched snapshots →
terminal `SUCCESS`/`ERROR` rehydrates `GET /api/conversation/{id}` → clicking `[n]` opens
`SourceDrawer`, whose PDF link jumps to `/api/document/{id}/file#page=N`. The demo transport
emits the same snapshots from `ANSWER_BANK`.

### W5 — Deploy bootstrap

`uv run start` → logging → Sentry → `_bootstrap` (DB wait → Alembic head check → pgvector DDL →
NLTK data → close) → flag → uvicorn with `BACKEND_WORKERS` → each worker lifespan configures
the env-selected model clients in a thread → opens its own pools → serves.

---

## 10. CONFIGURATION & ENVIRONMENT VARIABLES

`backend/app/core/config.py` (`Settings`, env prefix `""`, reads `.env`). Required: `DATABASE_URL`,
`NVIDIA_API_KEY`. Everything else has a default. Validators reject blank model ids, non-positive
limits and an embedding dimension that disagrees with the vector column — fail at boot, not
mid-chat. **No import-time `os.environ` mutation any more**: both clients receive the key /
endpoint explicitly in `llama_index_settings.py`.

### 10.1 Variable reference

| Variable | Default | Notes / where used |
|---|---|---|
| `DATABASE_URL` | **required** | validator rewrites `postgres://`→`postgresql://`→`postgresql+asyncpg://`; rejects non-postgres |
| `NVIDIA_API_KEY` | **required** | key for chat + embeddings (any non-empty string for an unauthenticated local endpoint); `NVIDIA_*` names are historical — the endpoint is any OpenAI-compatible `/v1` |
| `SUPABASE_URL` | `""` | Storage; `RuntimeError` if empty when used |
| `SUPABASE_SERVICE_ROLE_KEY` | `""` | server-side only, never returned to clients |
| `SUPABASE_STORAGE_BUCKET` | `annual-reports` | must exist in the Supabase project |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | chat + embedding endpoint; trailing slash stripped once in `Settings` |
| `NVIDIA_CHAT_LLM_NAME` | `meta/llama-3.3-70b-instruct` | chat id for agent / question-gen / synthesis. Free-form string; **no catalog lookup, no model table** |
| `NVIDIA_CHAT_IS_CHAT_MODEL` | `true` | declared `LLMMetadata.is_chat_model`; must be a real boolean (see §10.3) |
| `NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL` | `false` | declared `LLMMetadata.is_function_calling_model`; ReAct is prompt-based |
| `NVIDIA_CHAT_CONTEXT_WINDOW` / `NVIDIA_CHAT_MAX_TOKENS` | `131072` / `4096` | prompt sizing / reply cap; re-check for the model you configure |
| `NVIDIA_CHAT_TIMEOUT` | `120` | per-request chat timeout (seconds, streams included) |
| `NVIDIA_EMBEDDING_MODEL_NAME` | `nvidia/nemotron-3-embed-1b` | must output exactly `VECTOR_STORE_EMBED_DIM` (2048) |
| `NVIDIA_EMBEDDING_REQUEST_STYLE` | `nim` | `nim` sends `input_type` + `truncate`; `openai` sends a plain `/v1/embeddings` body |
| `NVIDIA_EMBEDDING_TRUNCATE` | `END` | `NONE`/`START`/`END`; only sent in `nim` style |
| `NVIDIA_EMBEDDING_DIMENSIONS` | unset | optional reduced size; boot validation requires it to equal `VECTOR_STORE_EMBED_DIM` |
| `VECTOR_STORE_TABLE_NAME` | `pg_vector_store` | real table = `data_pg_vector_store` |
| `VECTOR_STORE_EMBED_DIM` | `2048` | asserted by tests; startup refuses a table built for another dimension |
| `PROJECT_NAME` | `fincite` | FastAPI title |
| `API_PREFIX` | `/api` | all routes + docs |
| `LOG_LEVEL` | `INFO` | one of DEBUG/INFO/WARNING/ERROR/CRITICAL; `DEBUG` ⇒ uvicorn reload + verbose agent traces |
| `BACKEND_WORKERS` | `4` | uvicorn workers (ignored when reload) |
| `BACKEND_CORS_ORIGINS` | `[]` | JSON list or comma-separated; empty ⇒ **no CORS middleware** |
| `SENTRY_DSN` | unset | enables Sentry |
| `FINCITE_BOOTSTRAP_DONE` | unset | internal handoff flag (`main.py`) |

**Frontend config:** `VITE_API_URL` (default `""`, same-origin `/api`) and `VITE_USE_MOCK`
(default `false`; `1` selects demo mode). `VITE_PROXY_TARGET` controls the Vite dev proxy.
See `frontend/.env.example`.

`backend/.env.example` documents every variable (grouped into *chat model profile* and
*embedding model profile*); `docker-compose.yml` overrides `DATABASE_URL` and
`BACKEND_CORS_ORIGINS` for the local pgvector container.

### 10.2 Swapping models — the checklist

1. **Chat:** set `NVIDIA_CHAT_LLM_NAME` to the exact id the endpoint serves (e.g.
   `nvidia/nemotron-3.5-bolt-e4b`). Set `NVIDIA_BASE_URL` / `NVIDIA_API_KEY` if the
   provider changes (no client rewrites the endpoint from a model table any more — if a
   model needs a dedicated endpoint, set `NVIDIA_BASE_URL` yourself). Re-check
   `NVIDIA_CHAT_CONTEXT_WINDOW`, `NVIDIA_CHAT_MAX_TOKENS`, `NVIDIA_CHAT_IS_CHAT_MODEL`
   and `NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL` against that model's docs — they are
   declarations, not guesses. Restart; startup logs the effective profile
   (`Models configured — chat=…` in `_setup_llama_index_settings`).
2. **Embeddings:** set `NVIDIA_EMBEDDING_MODEL_NAME`, choose
   `NVIDIA_EMBEDDING_REQUEST_STYLE` (`nim` for NVIDIA NIMs, `openai` for plain
   `/v1/embeddings`), and set `NVIDIA_EMBEDDING_DIMENSIONS` only if the model supports a
   reduced size. Its output dimension must equal `VECTOR_STORE_EMBED_DIM`; otherwise
   **drop the vector table and re-index every document** (§14.R).
3. **Never** add a model id to executable code, and never reintroduce a client that infers
   metadata from a hardcoded model-name table. `config.py` + `llama_index_settings.py` are
   the only places model configuration belongs.

### 10.3 Why the metadata is explicit (the 2026-10-27 failure)

`llama-index-llms-nvidia==0.3.3` ended its constructor with
`is_chat_model = _is_chat_model()` / `is_function_calling_model = _is_function_calling_model()`,
both resolved from a frozen `CHAT_MODEL_TABLE`. For ids it did not know (the warning was
"Found … in available_models, but type is unknown") both were `None`, and
`OpenAILike.metadata` → `LLMMetadata(is_chat_model=None, …)` raises
`pydantic_core.ValidationError: 2 validation errors`. The call site was
`get_response_synthesizer()` inside `index.as_query_engine()` — hence the traceback on the
first `POST /api/conversation/{id}/message`. That client also did a blocking
`GET /v1/models` at construction. `OpenAILike` + explicit env booleans fixes both, and
removes the pydantic "protected namespace model_" warning emitted by that client's `Model`
class. The follow-on `sqlalchemy.exc.MissingGreenlet` in `finalise_message()` was caused by
reading `message.id` after `await db.commit()` (commit expires ORM attributes); use the
`message_id` argument and `expire_on_commit=False` (§15).

---

## 11. DEVELOPMENT COMMANDS

Legend: ✅ executed in this workspace with the stated result · ❌ currently fails ·
unmarked commands were **not** run here (no database or Supabase credentials) and are given from
the code/README contract — treat them as unverified.

### Backend (`cd backend`)

```bash
uv sync                                  # install from uv.lock incl. dev group  ✅
cp .env.example .env                     # then fill DATABASE_URL / SUPABASE_* / NVIDIA_API_KEY
uv run alembic upgrade head              # migrate (CWD must be backend/)
uv run start                             # bootstrap + uvicorn on 0.0.0.0:8000
# or: uv run uvicorn app.main:app --port 8000
uv run pytest -q                         # 70 passed in ~9 s (no DB / API key needed) ✅
uv run alembic current                   # applied revision
uv run alembic heads                     # single head ✅
docker compose up --build                # backend + healthy ankane/pgvector (5433:5432)
```

### Frontend (`cd frontend`)

```bash
npm ci                                   # ✅
npm run dev                              # vite dev server (:5173) — live API via /api proxy
npm run dev:mock                         # explicit seeded demo mode
npm run build                            # ✅ → dist/index.html (single file)
npm run build:demo                       # ✅ explicit demo build
npm run typecheck                        # ✅ 0 errors
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
`@pytest.mark.asyncio`). **Verified 2026-10-27: `uv run pytest -q` → 70 passed, 2 warnings
(both `supabase` deprecations), ~4 s.** The old pydantic protected-namespace and
"Unable to determine validity of …" embedding warnings are gone.

**`tests/conftest.py`** sets `DATABASE_URL`, `NVIDIA_API_KEY`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY` via `os.environ.setdefault` **before** any app import — this is why
the suite runs with no services. Add any new required setting there.

**Existing coverage (70 tests)** — highlights:

| File | Tests | What they pin |
|---|---|---|
| `tests/app/chat/test_engine.py` | 8 | `get_vector_store_singleton` passes `embed_dim=2048` (monkeypatched `from_params`); `get_chat_history` matrix: happy path, consecutive same-role messages, empty input, ERROR-status user/assistant filtering, blank content stripping, unpaired messages |
| `tests/app/test_refactored.py` | 7 | `NSEDocumentMetadata` parsing + defaults; Supabase storage helpers; `ingest_document` flow; upload endpoint success + invalid file; health endpoint |
| `tests/app/test_llama_index_settings.py` | 12 | chat client is `OpenAILike` with **env-declared** metadata; arbitrary model ids need no catalog lookup; `get_response_synthesizer` / custom synth accept it; embedding request shapes (nim/openai, query/passage, dimensions); config validators |
| `tests/app/test_engine_model_swap.py` | 1 | full `get_chat_engine()` build with `nvidia/nemotron-3.5-bolt-e4b` and **no** global `Settings.llm` — reproduces the reported traceback |
| `tests/app/test_connect_contract.py` | 29 | SSE snapshot contract, partial flushes, ERROR terminal state, plus `finalise_message` never reading an expired ORM attribute and `expire_on_commit=False` |

**Patterns to reuse**
- Patch **where the name is used**, not where it is defined:
  `@patch("app.api.endpoints.documents.upload_document")` (module attribute),
  `@patch("app.ingestion.pdf.PDFReader")`, `@patch("app.storage.supabase.create_client")`.
- `AsyncMock(spec=AsyncSession)` for the DB dependency; `AsyncMock(spec=UploadFile)` with
  `read.return_value = b"%PDF-1.4 …"`.
- Event-loop bridging in sync tests: `asyncio.run(coro)` (see
  `test_get_vector_store_singleton_uses_2048_embedding_dimension`).
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

> **Closed in M0/M1** (2026-10-26): **A**, **D**, **E**, **F**, **I**, **J**, **L**, **N**.
> **Closed in M2** (2026-10-27): **B** (real transport), **K** (wire/domain drift), the frontend half
> of **E** (delete errors), and the thread-persistence/scope parts of **C**; see
> `docs/plans/connect-and-deploy.md`. Remaining: **G**, **M**, **O**, **P**, **Q** and the still-aspirational
> M3+ UX/deploy items.

**A. ~~Frontend does not typecheck~~ — FIXED.** `frontend/src/lib/types.ts` had an unterminated `/**`
that swallowed four type declarations, plus an unused `Activity` import in `Sidebar.tsx`.
Both are repaired and `npm run typecheck` is part of CI. If it regresses, `npx tsc --noEmit` is the
fastest signal.

**B. ~~Frontend was mock-only / stale real transport~~ — FIXED in M2.** `USE_MOCK` defaults to
false, `transport.ts` uses `POST /message` with `fetch` + `ReadableStream`, `wire.ts` maps full
`Message` snapshots, and create/PATCH requests use `document_ids`. `EventSource` is gone; the
store rehydrates threads from the server. Keep demo mode explicit with `VITE_USE_MOCK=1`.

**C. Remaining documentation drift (reduced in M2).** `frontend/README.md`,
`backend/CONTEXT.md` and an NSE metadata upload form still do not exist; mock mode is now explicit,
scripts/proxy/typecheck/thread persistence are real, and README states 70 backend tests. Trust the
code and update docs in the same change when these remaining gaps are closed.

**D. Streaming concurrency — rewritten in M1, treat as load-bearing.**
`handle_chat_message` no longer enters `async with send_chan` (the endpoint owns the channel and
closes it exactly once); the callback handler tracks its scheduled sends in `_tasks` and exposes
`drain()` so the producer can flush the tail of the trail before closing; nothing reads
`send_chan._closed` any more (closed streams raise `ClosedResourceError`/`BrokenResourceError`, and a
client disconnect ends generation quietly). Tests that pin this behaviour:
`tests/app/test_connect_contract.py::test_handle_chat_message_does_not_close_the_callers_channel` and
`test_answer_stream_persists_partial_text_and_yields_monotonic_snapshots`. Any change here needs an
end-to-end check against a live SSE client.

**E. ~~`DELETE /api/conversation/{id}` fails for non-empty conversations~~ — FIXED.**
Migration `d4b6f8c0e2a3` re-creates the child FKs with `ON DELETE CASCADE`, and
`crud.delete_conversation` also deletes children explicitly (safe on databases created before the
cascade). M2 changed the frontend to await DELETE and show a real error toast instead of hiding
failures with a "local delete anyway" fallback.

**F. ~~`docker-compose.yml` database port is wrong~~ — FIXED.** Host `5433` now maps to container
`5432`, the obsolete `version:` key is gone, and `db` has a `pg_isready` healthcheck that the backend
`depends_on` with `condition: service_healthy`. Backend↔db works because the service connects to `db:5432`.

**G. Three of the four `backend/scripts/*.py` are unusable as written.**
`build_vector_tables.py`, `dedupe_vector_store.py` and `upsert_document.py` import `fire`, which is
not declared in `pyproject.toml`/`uv.lock` (`import fire` → `ModuleNotFoundError`, verified).
`chat_llama.py` is fine (it only needs `requests` + `sseclient-py`). Either add `fire` or replace
the CLI layer with `argparse`.

**H. Index reuse is not actually verified.** `build_doc_id_to_index_map`
(`engine.py:126-148`) calls `VectorStoreIndex.from_vector_store`, which does not raise for a
document with zero vectors — so the "re-index from storage" fallback is effectively dead code
and a document whose vectors are missing yields an empty tool. Do not rely on that except branch.

**I. ~~Indexing runs inside the upload request~~ — FIXED (single-process version).** `POST
/api/document/upload` stores the file + row (`status="uploaded"`) and schedules
`app/ingestion/jobs.py`, returning **202**; the job walks `parsing → chunking → embedding → indexing →
ready` writing `progress`/`error`. Constraints worth knowing: the scheduler is **process-local**
(`asyncio.create_task` + a `Semaphore(1)`), so a restart mid-ingest leaves the row stuck — the boot-time
sweep `crud.mark_stale_documents_failed` (15 min) marks those `failed` and the library's M2 "Retry
indexing" button calls `POST /reindex`. Durability across workers needs a real queue.

**J. ~~No document deletion path~~ — FIXED.** `DELETE /api/document/{id}` clears pgvector rows
(`metadata_->>'db_document_id'`), the stored PDF, conversation links and the row. It fails closed:
if the vector delete errors, the response is **503** and nothing else is touched.

**K. ~~Frontend/backend type drift~~ — FIXED in M2.** `wire.ts` translates
`company_symbol/financial_year/original_filename/page_count/file_size/message.sources`, maps legacy
document types and LlamaIndex `CBEventType` names to the UI unions, derives citations from trail
metadata, normalises fiscal years, and never throws on unknown enum values. Do not put backend field
names back into components.

**L. ~~`GET /api/document/` returns 404 for an empty library~~ — FIXED.** It returns `200 []`.

**M. Import-time side effects.** `chat/engine.py` calls `nest_asyncio.apply()` on import.
`core/config.py` instantiates `Settings` at import, so `DATABASE_URL` + `NVIDIA_API_KEY`
must be set (or the test defaults from `conftest.py`). The old
`os.environ["NVIDIA_API_KEY"]` / `NVIDIA_BASE_URL` writes were removed — both model
clients now receive the key and endpoint explicitly in `llama_index_settings.py`.

**N. ~~`_bootstrap()` depends on CWD~~ — FIXED.** `main.py` resolves `alembic.ini` from
`Path(__file__).resolve().parents[1]` and pins `script_location`, so the API boots from any working
directory. (`uv run alembic` from outside `backend/` still needs the CWD rule, §15.ALWAYS.1.)

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

**Q. No auth, tenancy, or rate limiting.** Every endpoint is public; the Supabase service-role key
must never leak to the client. CI exists (`.github/workflows/ci.yml`) and runs pytest, typecheck and
both frontend builds.

**R. Dependency age.** `sentry-sdk` 1.29.2 and `uvicorn` 0.22.0 are old. The model
integrations are pinned to the last core-0.12-compatible releases
(`llama-index-llms-openai-like==0.3.4`, `llama-index-embeddings-nvidia==0.3.4`,
plus an `openai<1.82` cap — rationale in `pyproject.toml`); moving them means the
deferred llama-index-core 0.13+ upgrade.

`llama-index-llms-nvidia` was **removed** on 2026-10-27: its frozen `CHAT_MODEL_TABLE`
returns `None` for `is_chat_model` / `is_function_calling_model` on newer catalog ids,
which crashes `LLMMetadata` (§10.3), and it performs a blocking `GET /v1/models` for
unknown ids. The replacement `OpenAILike` is model-agnostic and needs no catalog I/O.
`llama-index-embeddings-nvidia` remains only as a base class: `_NVIDIAEmbedding` in
`llama_index_settings.py` overrides `_validate_model` (no warnings / endpoint rewrites
for unknown ids) and every sync/async request builder (fixes 0.3.4's sync query sending
`input_type="passage"`, and makes the NIM-only fields config-driven). Catalog model ids
still retire (the previous embedding default's predecessor returned 410s); a 410/404
means "set the successor id in `.env` + re-check the profile in §10.2" (and for
embeddings, recreate the vector table + re-index — `pg_vector.run_setup()` refuses to
boot against a table built for a different dimension).

---

## 15. AGENT RULES

### ALWAYS

1. **Run backend commands from `backend/`** (`alembic.ini`, `.env`, `.venv` are all CWD-relative).
   Frontend commands from `frontend/`.
2. **Keep `db_document_id` on every vector node and `page_label` in metadata.** They are the
   backbone of per-document filtering and citations (§4.4).
3. **Keep `DocumentStatusEnum` names equal to their values** (lowercase). SQLAlchemy persists the enum
   *name*, so a mismatch between name and value silently writes a different string than the API
   advertises — and the migration, the DB, OpenAPI and the UI must all agree.
4. **Mirror the existing layering:** endpoint (HTTP + validation) → `crud.py` (SQL) → model.
   Never write SQL/ORM queries inside an endpoint or inside `chat/`.
5. **Keep the SSE contract as full `Message` snapshots**, unnamed events, monotonic
   `content`/`sub_processes`. The frontend's whole streaming design depends on it.
6. **Use Pydantic v2 APIs** (`model_validate`, `model_dump`, `field_validator`) in new code and
   keep `app/schema.py` as the single source of API shapes.
7. **Add or update a test** for any change to `crud.py`, `ingestion/`, `storage/`, or the upload
   endpoint, following the patch-where-used + `AsyncMock` patterns in §13.
8. **Run `uv run pytest -q` (backend) and `npm run typecheck` (frontend) before declaring work
   done.** Report the *actual* output (backend baseline after 2026-10-27: **70 passed**).
9. **Update `backend/.env.example` when you add a setting**, and `Settings` in
   `core/config.py` with a sane default so tests keep passing without new env vars.
10. **New migrations:** `uv run alembic revision --autogenerate -m "…"`, review the diff, keep a
   single head, and remember `_bootstrap()` refuses to start if the DB is not at head.
11. **Preserve the domain prompt contract** (tools first, exact units, financial year, page
    citations, no fabrication) whenever you touch `constants.py` or `qa_response_synth.py`.
12. **Match the frontend design system** — tokens in `index.css`, tiny mono labels, `aria-label`
    on icon buttons, framer-motion easings already in use.
13. **State uncertainty plainly.** If you could not run something, say which command and why.
14. **Change models only through `.env` + `core/config.py`** (§10.2). Declare every
    `LLMMetadata` capability explicitly, pass the configured `chat_llm` into *all*
    LlamaIndex factories (`as_query_engine`, `from_defaults`, `get_response_synthesizer`,
    `ReActAgent.from_tools`), and keep model ids out of executable code.
15. **Never read an ORM instance's attributes after `await db.commit()`** in async code:
    copy the scalars first (`assistant_id`, `assistant_created_at`) or use the plain
    `message_id` argument. `SessionLocal` sets `expire_on_commit=False`; code that needs
    fresh values must `await db.refresh(...)` / re-query explicitly.

### NEVER

1. **Never change `VECTOR_STORE_EMBED_DIM` (2048) or the embedding model without recreating the
   vector table** — rows of mixed dimensionality break similarity search.
2. **Never send blocking work onto the event loop.** PDF parsing, LLM client construction, and
   any `requests` call must be wrapped (`asyncio.to_thread`) or moved to a task.
3. **Never expose `SUPABASE_SERVICE_ROLE_KEY`, `NVIDIA_API_KEY`, or `DATABASE_URL`** to the
   client, in logs, or in API responses.
4. **Never edit `alembic/versions/*.py` that already ran** (or delete rows from
   `alembic_version`); add a new revision instead.
5. **Never regress the M2 transport contract.** Keep POST + unnamed full `Message` snapshots,
   `wire.ts` as the only mapper, and `VITE_USE_MOCK=1` as the only demo switch. Verify with
   `npm run typecheck`, both builds, and `scripts/smoke.sh` against a live API before claiming
   integration.
6. **Never delete the commented-out UI blocks or "unused" helpers as "cleanup"** without asking;
   they are deliberate parking spots for in-progress UI.
7. **Never trust `README.md` over the code.** If a doc claim is wrong, fix the doc in the same
   change (and note it here if it is a repeated trap).
8. **Never add a new framework** (test runner, linter, state library, router, ORM) without
   explicit user approval — this repo deliberately keeps a single store, one test framework, and
   no CSS-in-JS.
9. **Never commit `.env`, `node_modules/`, `dist/`, `.venv/`, or generated PDFs** (all ignored;
   keep new artifacts ignored too).
10. **Never assume typecheck, delete, or helper scripts are green without running them.** The M2
    typecheck and delete path are fixed; three legacy `backend/scripts/*.py` helpers still need
    `fire` (§14.G).
11. **Never reformat unrelated files.** Diffs should be scoped; this codebase mixes legacy and
    modern Python styles on purpose.

12. **After completing any task that changes architecture, adds new modules, or modifies data
    models, update the relevant sections of AGENTS.md before finishing.**
13. **Never let a provider client infer model capabilities from a hardcoded model-name table**
    (that is what broke chat creation). `OpenAILike` + explicit env booleans is the contract;
    if a client must know something about a model, it goes in `Settings`.
14. **Never call `Settings.llm` implicitly** in new RAG code — pass the configured client
    explicitly; the global is only for ingestion-time defaults.

---

### Quick "is it healthy?" checklist

```bash
cd backend  && uv run pytest -q                     # expect: 70 passed
cd backend  && uv run python -c "import app.main"   # needs DATABASE_URL + NVIDIA_API_KEY set
cd frontend && npm run typecheck                    # expect: 0 errors
cd frontend && npm run build                        # expect: single dist/index.html (~644 kB)
curl -s localhost:8000/api/health/                  # {"status":"healthy","db":true,…} — requires DB + env
curl -s localhost:8000/api/config/                  # public runtime config
curl -s localhost:8000/api/document/                 # 200 [] on an empty library
```
