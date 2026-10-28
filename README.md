<div align="center">

# Fincite

### Ask the filings. Every claim, pinned to a page.

**An AI research terminal for Indian / NSE company annual reports and corporate filings.**<br/>
Upload PDFs, ask questions in plain English, and get answers that cite the exact page they came from.

<br/>

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](backend/app/main.py)
[![LlamaIndex](https://img.shields.io/badge/LlamaIndex-0.12-6B4FBB)](backend/app/chat/engine.py)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-LLM%20%2B%20Embeddings-76B900?logo=nvidia&logoColor=white)](backend/app/llama_index_settings.py)
[![Supabase](https://img.shields.io/badge/Supabase-Postgres%20%2B%20pgvector%20%2B%20Storage-3FCF8E?logo=supabase&logoColor=white)](backend/app/storage/supabase.py)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](frontend/package.json)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)](frontend/tsconfig.json)
[![Tailwind](https://img.shields.io/badge/Tailwind%20CSS-v4-06B6D4?logo=tailwindcss&logoColor=white)](frontend/src/index.css)
[![Tests](https://img.shields.io/badge/backend%20tests-15%20passing-1F7A4D)](backend/tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<br/>

[**Product**](#1-product) · [**How it works**](#2-how-it-works) · [**Engineering**](#3-engineering) · [**Repository structure**](#4-repository-structure) · [**Capabilities**](#5-capabilities) · [**Quick start**](#6-quick-start) · [**API**](#7-api-surface) · [**Roadmap**](#9-roadmap)

</div>

---

## 1. Product

### 1.1 The problem

An Indian listed company's annual report is routinely **250–400 pages** of PDF: audited financials, MD&A, board reports, ESG disclosures, risk factors, notes to accounts. Analysts, students, retail investors and journalists all ask the same kinds of questions —

> *"What was consolidated revenue in FY2025 versus FY2024?"*
> *"What did management say about input-cost inflation?"*
> *"Compare the capex guidance of these two companies."*

— and answer them the slow way: Ctrl-F across multiple PDFs, copy numbers into a spreadsheet, and hope nothing was mis-read. General-purpose chatbots are worse: they hallucinate figures, silently convert **₹ Crore** to millions, and blur one financial year into another.

### 1.2 The product

**Fincite** is a focused, retrieval-augmented research assistant for exactly this corpus. You build a private library of filings, open a research thread scoped to one or many of them, and interrogate the documents conversationally. Every answer is:

| Principle | What it means in practice |
|---|---|
| **Grounded** | The model is instructed to *always* consult the documents through its tools before answering, and to say so explicitly when a figure is not in the retrieved context. |
| **Pinned to a page** | Retrieval carries page labels through the whole pipeline; citations include document, page number, the quoted passage and a relevance score. |
| **Unit-faithful** | Figures are reported in the units the filing uses (₹ Crore, ₹ Lakh, USD Million) — never silently converted. |
| **Year-aware** | FY2025 vs FY2024 is disambiguated in every answer; cross-document comparisons attribute each data point to the right company and year. |
| **Transparent** | A live *research trail* shows the work: engine construction, sub-questions generated per document, retrieval, synthesis — streamed as it happens. |
| **On-topic** | Off-topic requests are politely declined; the assistant is a financial-research specialist, not a general chatbot. |

### 1.3 Who it is for

- **Equity analysts & finance students** who need numbers with provenance.
- **Retail investors** who want to read filings without reading *all* of the filing.
- **Engineers** evaluating a production-shaped RAG reference: agentic multi-document reasoning, per-document retrieval isolation, streamed observability, and clean service boundaries.

---

## 2. How it works

A single research session, end to end:

```
   ┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌────────────────────┐
   │ 1. UPLOAD    │ ──▶ │ 2. INDEX         │ ──▶ │ 3. ASK           │ ──▶ │ 4. READ & VERIFY   │
   │ Drop a PDF   │     │ Parse → chunk →  │     │ Open a thread    │     │ Streamed answer +  │
   │ annual report│     │ embed → pgvector │     │ scoped to 1..n   │     │ research trail +   │
   │ + metadata   │     │ (page-labelled)  │     │ filings, ask     │     │ page-level sources │
   └──────────────┘     └──────────────────┘     └──────────────────┘     └────────────────────┘
```

1. **Upload** — `POST /api/document/upload` with the PDF and optional NSE metadata (company, ticker, financial year, document type). Duplicates are detected by SHA-256 and returned idempotently.
2. **Index** — the PDF is stored in Supabase Storage, parsed page-by-page, split into sentence-aware chunks, embedded with NVIDIA Nemotron, and written to pgvector with the document ID stamped on every node.
3. **Ask** — create a conversation over any set of indexed documents, then send a question. The agent decides which documents to consult, breaks the question into per-document sub-questions, retrieves and synthesises.
4. **Read & verify** — the answer streams token-by-token over Server-Sent Events alongside structured sub-process events, so the UI can render a research trail and clickable `[n]` citations that open the exact passage.

---

## 3. Engineering

### 3.1 System architecture

```mermaid
flowchart LR
    subgraph Client["Browser"]
        UI["Fincite UI<br/>React 19 · Vite 7 · Tailwind v4"]
    end

    subgraph API["Backend · FastAPI · Python 3.11"]
        R["REST + SSE layer<br/>/api/document · /api/conversation · /api/health"]
        ING["Ingestion pipeline<br/>PDFReader → SentenceSplitter → embed → upsert"]
        ENG["Chat engine<br/>ReAct agent → SubQuestion engine → per-document tools"]
    end

    subgraph Supabase["Supabase"]
        PG[("PostgreSQL<br/>conversations · messages · documents")]
        VEC[("pgvector<br/>data_pg_vector_store · 2048-d")]
        ST[["Storage bucket<br/>documents/ID/original.pdf"]]
    end

    subgraph Nvidia["OpenAI-compatible models (default: NVIDIA NIMs)"]
        LLM["env-selected chat model<br/>reasoning · sub-questions · synthesis"]
        EMB["env-selected embedding model<br/>2048-d embeddings"]
    end

    UI -- "multipart upload" --> R
    UI -- "EventSource / SSE" --> R
    R --> ING
    R --> ENG
    ING --> ST
    ING --> EMB
    ING --> VEC
    ING --> PG
    ENG --> VEC
    ENG --> LLM
    ENG --> EMB
    ENG --> PG
```

| Layer | Technology | Why |
|---|---|---|
| **API** | FastAPI · Pydantic v2 · `sse-starlette` | Async-native, typed request/response models, first-class OpenAPI docs, SSE without WebSockets. |
| **Orchestration** | LlamaIndex 0.12 (`ReActAgent`, `SubQuestionQueryEngine`, `VectorStoreIndex`) | Battle-tested primitives for agentic RAG; callback system doubles as the observability bus. |
| **Models** | Any OpenAI-compatible endpoint (default NVIDIA NIMs) — chat `meta/llama-3.3-70b-instruct`, embeddings `nvidia/nemotron-3-embed-1b` (2048-d) **by default only** | Model ids, endpoint, key **and declared capabilities** come from `.env`; the generic `OpenAILike` chat client has no hardcoded model table, so newer ids (e.g. `nvidia/nemotron-3.5-bolt-e4b`) work without a code change. |
| **Data** | PostgreSQL + pgvector (Supabase) · SQLAlchemy 2 async · Alembic | One database for relational state *and* vectors — no separate vector DB to operate; migrations are versioned. |
| **Object storage** | Supabase Storage | Original PDFs are kept for re-indexing and future viewer features; service-role key stays server-side. |
| **Frontend** | React 19 · TypeScript (strict) · Vite 7 · Tailwind CSS v4 · Framer Motion | Lightweight, no heavy state library; design-token driven editorial UI. |
| **Packaging** | `uv` + `hatchling` · multi-stage Docker · `docker compose` | Reproducible, lock-file-driven Python installs; cached dependency layers. |
| **Quality** | `pytest` + `pytest-asyncio` (backend) · `tsc --strict` (frontend) · Sentry hook | Unit tests run with zero external services. |

### 3.2 The retrieval & reasoning harness

The core of Fincite is a **three-tier query harness** built in [`backend/app/chat/engine.py`](backend/app/chat/engine.py). Each tier has one job:

```
            ┌──────────────────────────────────────────────────────────────────────┐
  Tier 1    │ ReActAgent  (env-selected chat LLM · 6 iterations · system prompt)   │
            │  "Should I use a tool? Which? Is the answer complete?"               │
            └───────────────────────────────┬──────────────────────────────────────┘
                                            │ single tool: document_question_engine
            ┌───────────────────────────────▼──────────────────────────────────────┐
  Tier 2    │  SubQuestionQueryEngine  (LLMQuestionGenerator · async fan-out)      │
            │  "Split the question into one sub-question per relevant document."   │
            │  Custom QA + Refine prompts enforce units & financial-year hygiene.  │
            └───────┬──────────────────────────┬───────────────────────┬───────────┘
                    │                          │                       │
            ┌───────▼────────┐        ┌────────▼───────┐       ┌───────▼────────┐
  Tier 3    │ QueryEngineTool│        │ QueryEngineTool│  ...  │ QueryEngineTool│
            │ doc A · top-3  │        │ doc B · top-3  │       │ doc N · top-3  │
            │ filter:        │        │ filter:        │       │ filter:        │
            │ db_document_id │        │ db_document_id │       │ db_document_id │
            └───────┬────────┘        └────────┬───────┘       └───────┬────────┘
                    └──────────────────────────┴───────────────────────┘
                                               │
                                   ┌───────────▼───────────┐
                                   │  pgvector (one table) │
                                   │  cosine · 2048-d      │
                                   └───────────────────────┘
```

**Design decisions worth knowing:**

- **One tool per document, isolated by metadata filter.** All documents share a single pgvector table, but each `QueryEngineTool` applies an `ExactMatchFilter(db_document_id = …)`. Cross-contamination between filings is impossible by construction, and the tool *description* (built from NSE metadata — *"Annual report for Reliance Industries (RELIANCE), financial year 2025 (exchange: NSE)."*) is what lets the LLM route sub-questions correctly.
- **Sub-question decomposition before retrieval.** "Compare X across A and B" becomes two targeted sub-questions executed concurrently (`use_async=True`), each answered from its own document, then synthesised. This is what makes multi-document comparison reliable rather than lucky.
- **Domain-specific prompts at every tier.** The system prompt, the QA prompt and the Refine prompt all restate the same contract: use tools first, preserve units, name the financial year, cite pages, never fabricate. Redundancy here is deliberate — it is cheap and measurably reduces drift.
- **The callback bus *is* the observability layer.** A custom `ChatCallbackHandler` turns LlamaIndex `CBEventType` events (`SUB_QUESTION`, `RETRIEVE`, `LLM`, `SYNTHESIZE`, …) into typed `MessageSubProcess` records, pushes them through an `anyio` memory channel, and the SSE endpoint fans them out to the client — *and* persists them, so a conversation's full reasoning trace survives reloads.
- **Index-once, query-many.** The vector index is persistent in pgvector; building a chat engine never re-embeds. If an index cannot be loaded, the engine falls back to re-ingesting the PDF from Storage.

### 3.3 Streaming request lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser
    participant API as FastAPI · /api/conversation/:id/message
    participant H as handle_chat_message
    participant A as ReActAgent · Llama 3.3 70B
    participant S as SubQuestionQueryEngine
    participant V as pgvector
    participant DB as PostgreSQL

    U->>API: GET ?user_message=… (Accept: text/event-stream)
    API->>DB: load conversation, history, documents
    API->>H: spawn task + anyio channel
    H->>A: build engine (per-document tools, custom prompts)
    H-->>U: SSE · sub_process CONSTRUCTED_QUERY_ENGINE
    A->>S: tool call · document_question_engine
    S->>S: generate one sub-question per relevant document
    par for each sub-question (async)
        S->>V: filtered similarity search · top-3 · db_document_id = doc
        V-->>S: chunks + page labels + scores
        S-->>U: SSE · sub_process SUB_QUESTION (question · answer · citations)
    end
    S-->>A: synthesised answer (QA + Refine prompts)
    loop token stream
        A-->>H: delta
        H-->>U: SSE · Message snapshot (content grows · status PENDING)
    end
    API->>DB: persist user + assistant messages + sub-processes
    API-->>U: SSE · final Message (status SUCCESS or ERROR)
```

Every SSE event is a complete JSON `Message` snapshot — content and `sub_processes` grow monotonically — so clients are trivially resumable and never have to reassemble partial deltas.

### 3.4 Ingestion pipeline

```
PDF bytes ─▶ validate (MIME + %PDF magic) ─▶ SHA-256 dedupe ─▶ UUID
        ─▶ Supabase Storage  documents/{id}/original.pdf
        ─▶ Postgres  document row  { url, metadata_map: { nse_document, content_hash, original_filename } }
        ─▶ PDFReader (page-labelled LlamaIndex Documents, db_document_id stamped)
        ─▶ SentenceSplitter  chunk 512 · overlap 10
        ─▶ NVIDIAEmbedding  2048-d
        ─▶ pgvector  data_pg_vector_store
        ─▶ 201 { status: "indexed" }
```

Failure at any step after storage **rolls back** both the Storage object and the DB row, so the library never contains a document that can't be queried.

### 3.5 Data model

```mermaid
erDiagram
    CONVERSATION ||--o{ MESSAGE : has
    CONVERSATION ||--o{ CONVERSATIONDOCUMENT : scopes
    DOCUMENT ||--o{ CONVERSATIONDOCUMENT : "linked to"
    MESSAGE ||--o{ MESSAGESUBPROCESS : "traced by"

    CONVERSATION {
        uuid id PK
        timestamp created_at
        timestamp updated_at
    }
    DOCUMENT {
        uuid id PK
        string url UK
        jsonb metadata_map
    }
    CONVERSATIONDOCUMENT {
        uuid id PK
        uuid conversation_id FK
        uuid document_id FK
    }
    MESSAGE {
        uuid id PK
        uuid conversation_id FK
        string content
        enum role
        enum status
    }
    MESSAGESUBPROCESS {
        uuid id PK
        uuid message_id FK
        enum source
        enum status
        jsonb metadata_map
    }
```

Vectors live alongside in `data_pg_vector_store` (managed by LlamaIndex), linked to `DOCUMENT` through `metadata_.db_document_id`. Schema evolution is handled by six Alembic migrations in [`backend/alembic/versions`](backend/alembic/versions).

### 3.6 Process model

`uv run start` performs deploy-time bootstrap **once** in the parent process — wait for DB, verify Alembic is at head, `CREATE EXTENSION vector`, create vector tables, pre-fetch NLTK tokenizer data — then launches `uvicorn` with `BACKEND_WORKERS` (default 4) worker processes. Each worker's lifespan only does per-process work: configure NVIDIA model clients off the event loop, open its own connection pools, and close them on shutdown. The vector store deliberately **shares the app's async engine**, so a worker holds one pool, not two.

---

## 4. Repository structure

```
fincitee/
├── backend/                         # FastAPI + LlamaIndex service
│   ├── app/
│   │   ├── main.py                  #   bootstrap, lifespan, uvicorn entrypoint
│   │   ├── core/config.py           #   pydantic-settings; env validation & URL normalisation
│   │   ├── llama_index_settings.py  #   env-driven chat + embedding factories + SentenceSplitter
│   │   ├── api/
│   │   │   ├── api.py               #   router registry (/conversation, /document, /health)
│   │   │   ├── crud.py              #   async SQLAlchemy data access
│   │   │   ├── deps.py              #   DB session dependency
│   │   │   └── endpoints/           #   conversation.py (SSE) · documents.py (upload) · health.py
│   │   ├── chat/
│   │   │   ├── engine.py            #   ReAct → SubQuestion → per-document tools
│   │   │   ├── messaging.py         #   callback handler → anyio channel → stream
│   │   │   ├── qa_response_synth.py #   custom QA / Refine prompts
│   │   │   ├── pg_vector.py         #   pool-sharing PGVectorStore singleton
│   │   │   ├── constants.py         #   system prompt, chunking constants
│   │   │   └── utils.py             #   document title / tool-description builders
│   │   ├── ingestion/pdf.py         #   PDF → nodes → embeddings → pgvector
│   │   ├── storage/supabase.py      #   upload / download / delete / public URL
│   │   ├── models/                  #   SQLAlchemy declarative models + PG enums
│   │   ├── db/                      #   async engine, session, wait-for-db
│   │   └── schema.py                #   Pydantic API schemas incl. NSE metadata + citations
│   ├── alembic/                     #   6 versioned migrations
│   ├── scripts/                     #   SSE chat CLI, vector-table builder, dedupe tool
│   ├── tests/                       #   70 unit tests, fully mocked (no DB / API key)
│   ├── Dockerfile · docker-compose.yml · pyproject.toml · uv.lock · .env.example
│
├── frontend/                        # React research terminal
│   ├── src/
│   │   ├── App.tsx                  #   shell: ticker · sidebar · views · drawers · splash
│   │   ├── store.tsx                #   React-context store: docs, threads, streaming, health
│   │   ├── lib/
│   │   │   ├── api.ts               #   thin facade: demo transport vs real transport
│   │   │   ├── transport.ts         #   fetch + POST/ReadableStream SSE client
│   │   │   ├── wire.ts              #   backend DTO → UI domain mappers
│   │   │   ├── types.ts             #   domain types
│   │   │   ├── format.ts            #   labels, formatters
│   │   │   └── mockData.ts          #   seeded demo corpus + canned answers
│   │   └── components/              #   ChatView · LibraryView · MessageItem · ResearchTrail
│   │                                #   CiteMarkdown · SourceDrawer · Sidebar · Composer …
│   ├── index.html · vite.config.ts · tsconfig.json · package.json
│
├── LICENSE                          # MIT
└── README.md                        # you are here
```

---

## 5. Capabilities

By subsystem:

| Area | Capability | Status |
|---|---|---|
| **Ingestion** | Upload PDF with NSE metadata (company, ticker, FY, type, exchange) | ✅ |
| | MIME + magic-byte validation; empty-file rejection | ✅ |
| | SHA-256 duplicate detection (idempotent re-upload) | ✅ |
| | Page-labelled parsing → sentence-aware chunking → NVIDIA embeddings → pgvector | ✅ |
| | Atomic rollback of Storage + DB on indexing failure | ✅ |
| | **Background indexing** (202 + `status`/`progress`/`error`, polled by the UI) | ✅ |
| | **Delete a filing** — vectors, stored PDF, links and rows | ✅ |
| | **Re-index / retry** from the stored PDF | ✅ |
| | **PDF streaming** through the API (`/file`, `#page=N` ready) | ✅ |
| **Conversations** | Create / fetch / patch / delete conversations scoped to 0..n documents | ✅ |
| | **Thread index** — title, message count, preview, last activity | ✅ |
| | Chat history replay (failed / empty messages filtered out) | ✅ |
| **Reasoning** | ReAct agent with domain system prompt (units, FY, citations, refusal) | ✅ |
| | Per-document isolated retrieval (metadata-filtered, top-3) | ✅ |
| | Multi-document sub-question decomposition with async fan-out | ✅ |
| | Custom QA / Refine synthesis prompts | ✅ |
| **Streaming** | SSE token stream with structured sub-process events | ✅ |
| | **`POST /message`** with the question in the body (GET kept, deprecated) | ✅ |
| | Page-level citations with passage text + relevance score, **flattened onto the message** | ✅ |
| | Full reasoning trace persisted per message, with step labels + durations | ✅ |
| | **Durable partials** — user message + placeholder written first, content flushed mid-stream | ✅ |
| **Ops** | One-shot deploy bootstrap, multi-worker uvicorn, pooled connections | ✅ |
| | Alembic migrations with head verification at boot | ✅ |
| | Docker image + compose with local pgvector | ✅ |
| | Optional Sentry, configurable CORS, structured logging | ✅ |
| | OpenAPI / Swagger / ReDoc at `/api/docs`, `/api/redoc` | ✅ |
| **Frontend** | Research threads, streaming answers, live research trail, citation chips, source drawer | ✅ (live API) |
| | Filing library: real PDF uploads, polling, search, detail drawer, scoped threads | ✅ |
| | Server-backed thread list, reload-safe messages, PATCH scope, real delete errors | ✅ |
| | Explicit demo transport: seeded corpus + canned cited answers, no backend required | ✅ |
| | Single-file production build (`dist/index.html`) | ✅ |

### Try it in the sandbox

Four ways to exercise the system:

```bash
# 0a. The research terminal against the live API (backend + /api proxy required)
cd frontend && npm ci && npm run dev          # http://localhost:5173

# 0b. The same terminal in explicit demo mode (no backend required)
cd frontend && npm ci && npm run dev:mock     # http://localhost:5173

# 1. Swagger UI — interactive, every endpoint (use /test_message for a non-streamed answer)
open http://localhost:8000/api/docs

# 2. Raw SSE with curl — watch the research trail arrive event by event
curl -N "http://localhost:8000/api/conversation/<CONVERSATION_ID>/message?user_message=What%20was%20FY2025%20revenue%3F"

# 3. Interactive terminal client (fetch → select → create → message)
cd backend && uv run python scripts/chat_llama.py --base_url http://localhost:8000
```

---

## 6. Quick start

### 6.1 Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11.x** and [`uv`](https://docs.astral.sh/uv/) | `requires-python = ">=3.11,<3.12"` |
| **Node 20+** and npm | for the frontend |
| **PostgreSQL with pgvector** | a Supabase project (recommended) **or** the bundled `docker compose` database |
| **Supabase project** | Storage bucket (default name `annual-reports`) + service-role key |
| **NVIDIA API key** (`nvapi-…`) | https://build.nvidia.com — sign in, open any model, “Get API Key” |

### 6.2 Backend

```bash
cd backend
cp .env.example .env          # fill in DATABASE_URL, SUPABASE_*, NVIDIA_API_KEY
uv sync                        # installs from uv.lock (dev group included)
uv run alembic upgrade head    # create tables
uv run start                   # bootstrap + uvicorn on http://0.0.0.0:8000
```

Or with Docker (local pgvector included — you still need Supabase Storage + an NVIDIA API key in `.env`):

```bash
cd backend && docker compose up --build
```

### 6.3 Frontend

```bash
cd frontend
npm ci
npm run dev                    # http://localhost:5173 — live API via the Vite /api proxy
npm run dev:mock               # explicit demo mode (seeded data, no backend)
npm run dev:real               # explicitly force live API (same as the default)
npm run build                  # → dist/index.html, a single static file
npm run typecheck              # tsc --noEmit (0 errors)
```

Transport selection is environment-driven — no source edits:

| `VITE_USE_MOCK` | Behaviour |
|---|---|
| unset / `0` | real API (`npm run dev` / `npm run dev:real` / `npm run build`) |
| `1` | always mock (demo mode, `npm run dev:mock` / `npm run build:demo`) |

`VITE_API_URL` defaults to `""` (same origin), which is what the Vite dev proxy
(`server.proxy`, target `VITE_PROXY_TARGET`) and the production reverse proxy expect — so CORS is not
part of local development. See `frontend/.env.example`.

> **M2 status:** the real transport uses `POST /message` over fetch/`ReadableStream`, maps unnamed
> `Message` snapshots in [`frontend/src/lib/wire.ts`](frontend/src/lib/wire.ts), rehydrates the thread
> list and messages from the server, PATCHes scope, polls real ingestion status, and opens the original
> PDF at the cited page. Demo mode remains only behind `VITE_USE_MOCK=1`. See
> [`docs/plans/connect-and-deploy.md`](docs/plans/connect-and-deploy.md).

### 6.4 Run the tests

```bash
cd backend && uv run pytest -q      # 70 passed — no database or API key required
cd frontend && npm run typecheck     # 0 errors
cd frontend && npm run build         # single dist/index.html
cd frontend && npm run build:demo    # still typechecks/builds demo mode
```

With a running backend and a real PDF, `./scripts/smoke.sh http://localhost:8000 path/to/filing.pdf`
checks upload → indexing → streaming answer → citation → reload → cleanup.

CI (`.github/workflows/ci.yml`) runs the backend suite, the typecheck, and both the real and demo builds
on every push, so mock mode cannot rot.

---

## 7. API surface

All routes are prefixed with `/api`. Full request/response documentation lives in
[`docs/agents/API_REFERENCE.md`](docs/agents/API_REFERENCE.md) and in the generated OpenAPI spec.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/` | Liveness + readiness → `{status, db, version, uptime_s}` (never 5xx) |
| `GET` | `/config/` | Public runtime config: upload limit, accepted types, `auth_enabled`, `demo_mode` |
| `POST` | `/document/upload` | Multipart PDF upload → **202** `{status:"uploaded"}`; indexing runs in the background |
| `GET` | `/document/` | List documents (`?status=&q=&limit=&offset=`) → `[]` when empty |
| `GET` | `/document/{id}` | One document incl. `status` / `progress` / `error` |
| `GET` | `/document/{id}/file` | Streams the original PDF (citation viewer, `#page=N`) |
| `POST` | `/document/{id}/reindex` | Re-run ingestion from the stored PDF (retry) |
| `DELETE` | `/document/{id}` | Delete vectors + stored PDF + rows → `204` |
| `POST` | `/conversation/` | Create a thread over `document_ids[]` (optional) + `title` |
| `GET` | `/conversation/` | Thread index: title, message count, preview, last activity |
| `GET` | `/conversation/{id}` | Thread + messages + research trail + citations |
| `PATCH` | `/conversation/{id}` | Rename and/or replace the document scope |
| `DELETE` | `/conversation/{id}` | Delete a thread → `204` |
| `POST` | `/conversation/{id}/message` | **SSE** — `{"content": "…"}` → streamed answer with trail + citations |
| `GET` | `/conversation/{id}/message?user_message=` | Same stream (deprecated, kept for `curl`) |
| `GET` | `/conversation/{id}/test_message?user_message=` | Same, non-streamed (handy in Swagger) |

Full request/response documentation: [`docs/agents/API_REFERENCE.md`](docs/agents/API_REFERENCE.md) and
the generated OpenAPI spec at `/api/docs`.

---

## 8. Configuration

Copy [`backend/.env.example`](backend/.env.example). The important knobs:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | Postgres URL; normalised to `postgresql+asyncpg://` automatically |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | — | Storage access (server-side only) |
| `SUPABASE_STORAGE_BUCKET` | `annual-reports` | Bucket holding original PDFs |
| `NVIDIA_API_KEY` | — | Key for chat + embeddings (`nvapi-…` from build.nvidia.com by default) |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Any OpenAI-compatible `/v1` endpoint |
| `NVIDIA_CHAT_LLM_NAME` | `meta/llama-3.3-70b-instruct` | Reasoning / synthesis model id (any id the endpoint serves) |
| `NVIDIA_CHAT_IS_CHAT_MODEL` / `NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL` | `true` / `false` | Declared `LLMMetadata` booleans — required, never inferred |
| `NVIDIA_CHAT_CONTEXT_WINDOW` / `NVIDIA_CHAT_MAX_TOKENS` | `131072` / `4096` | Must match the chat model's limits |
| `NVIDIA_CHAT_TIMEOUT` | `120` | Per-request chat timeout in seconds |
| `NVIDIA_EMBEDDING_MODEL_NAME` | `nvidia/nemotron-3-embed-1b` | Embedding model id |
| `NVIDIA_EMBEDDING_REQUEST_STYLE` / `NVIDIA_EMBEDDING_TRUNCATE` | `nim` / `END` | `nim` sends `input_type` + `truncate`; `openai` sends a plain request |
| `NVIDIA_EMBEDDING_DIMENSIONS` | — | Optional reduced size; must equal `VECTOR_STORE_EMBED_DIM` |
| `VECTOR_STORE_TABLE_NAME` / `VECTOR_STORE_EMBED_DIM` | `pg_vector_store` / `2048` | pgvector table & dimension (must match the embedding model) |
| `MAX_UPLOAD_MB` | `50` | Upload size ceiling (413 above it) |
| `INGESTION_ENABLED` | `true` | `false` accepts uploads without indexing them |
| `AUTH_ENABLED` | `false` | Reserved for M4 (Supabase JWT); endpoints are public while false |
| `DEMO_MODE` | `false` | Labels a seeded/demo deployment |
| `BACKEND_WORKERS` | `4` | uvicorn worker processes |
| `BACKEND_CORS_ORIGINS` | `[]` | JSON list or comma-separated origins |
| `LOG_LEVEL` | `INFO` | `DEBUG` also enables uvicorn reload + verbose agent traces |
| `SENTRY_DSN` | — | Optional error tracking |

### 8.1 Changing models (no code changes)

The `NVIDIA_*` names are historical — they configure a **generic OpenAI-compatible** client,
so you can point the app at NVIDIA hosted NIMs, a self-hosted NIM, vLLM, or a gateway. There
is no hardcoded model id or provider-specific model table in the backend.

1. Set `NVIDIA_CHAT_LLM_NAME` to the exact id your endpoint serves (for example
   `nvidia/nemotron-3.5-bolt-e4b`), plus `NVIDIA_BASE_URL` / `NVIDIA_API_KEY` if the provider
   changes.
2. Update the **whole chat profile** for that model: `NVIDIA_CHAT_IS_CHAT_MODEL`,
   `NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL`, `NVIDIA_CHAT_CONTEXT_WINDOW`,
   `NVIDIA_CHAT_MAX_TOKENS`, `NVIDIA_CHAT_TIMEOUT`. These are declarations used to build
   LlamaIndex `LLMMetadata`; a stale context window silently truncates synthesis.
3. Restart. Startup logs `Models configured — chat=… embeddings=… endpoint=…` (never the key).
4. Changing the **embedding** model also means checking its output dimension against
   `VECTOR_STORE_EMBED_DIM`; if it differs, drop `data_pg_vector_store` and re-index every
   document. Set `NVIDIA_EMBEDDING_REQUEST_STYLE=openai` for plain `/v1/embeddings`
   providers that reject NIM's `input_type` / `truncate` fields.

See [`backend/.env.example`](backend/.env.example) for the fully commented profile and
[`AGENTS.md` §10.2](AGENTS.md) for the agent-facing checklist.

> **Fixed (Oct 2026):** with newer model ids, `llama-index-llms-nvidia` used to set
> `is_chat_model` / `is_function_calling_model` to `None`, so the first `POST /message`
> failed with `LLMMetadata: 2 validation errors` while building the query engine; the
> follow-on `MissingGreenlet` prevented the ERROR answer from being persisted. Both are
> resolved by the explicit config above plus `expire_on_commit=False` on async sessions.

---

## 9. Roadmap

- [x] **Frontend connected (M2)** — real POST SSE, server-backed threads, live uploads and citations;
      demo mode is explicit.
- [x] **Background indexing** — uploads return 202 and a job reports `status`/`progress`/`error`
      (process-local scheduler; a durable queue is the follow-up).
- [ ] **Authentication & tenancy** — per-user libraries and threads.
- [ ] **Hybrid retrieval + reranking** — BM25 fusion and a cross-encoder stage ahead of synthesis.
- [ ] **In-app PDF viewer** — backend half is done (`GET /api/document/{id}/file` streams the PDF);
      the UI viewer is M3.
- [ ] **Richer NSE metadata** — quarterly results, concall transcripts, shareholding patterns as first-class document types (the UI already labels them).
- [x] **Conversation listing** — `GET /api/conversation/` returns the sidebar index (title, preview,
      message count, last activity).
- [ ] **Evaluation harness** — golden Q&A set over public filings for regression-testing answer faithfulness.
- [x] **Model abstraction** — providers/models swap via `app/llama_index_settings.py` factories + env (Google Gemini → NVIDIA NIM, Oct 2026); since Oct 27 the chat client is a generic `OpenAILike` with env-declared capabilities, so any model id works without a code change.

---

## 10. Documentation map

| Document | Audience | Contents |
|---|---|---|
| **This file** | Everyone | Product, architecture, capabilities, quick start |
| [`AGENTS.md`](AGENTS.md) | AI agents / contributors | Repo map, verified commands, known issues, coding conventions, agent rules |
| [`backend/README.md`](backend/README.md) | Backend / ML engineers | Harness internals, SSE protocol, data model, configuration, API reference, ops |

> **Note:** `frontend/README.md` and `backend/CONTEXT.md` do not exist. `docs/agents/` holds the
> module-level deep dives, and [`docs/plans/connect-and-deploy.md`](docs/plans/connect-and-deploy.md)
> is the roadmap for connecting the frontend to the backend and deploying them.

---

## License

MIT © 2026 Ajinkya Datir — see [`LICENSE`](LICENSE).

<div align="center">
<sub>Built with FastAPI · LlamaIndex · NVIDIA NIM · Supabase · React</sub>
</div>
