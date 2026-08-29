# Fincite Backend — CONTEXT

> Token-friendly reference for AI agents and developers. Keep concise.

## What It Does
AI financial research assistant for Indian/NSE listed companies.
Users upload PDFs (annual reports, NSE filings, investor presentations), then ask questions across them via a RAG chat interface.

## Stack
| Layer | Technology |
|---|---|
| API | FastAPI 0.115, Python 3.11 |
| ORM | SQLAlchemy 2.0 async (asyncpg) |
| Migrations | Alembic |
| Vector store | pgvector via llama-index-vector-stores-postgres |
| LLM | OpenAI (gpt-4o-mini default) |
| Embeddings | OpenAI text-embedding-3-small |
| RAG | LlamaIndex Core 0.12 — SubQuestionQueryEngine + OpenAIAgent |
| PDF storage | Supabase Storage |
| Package manager | uv |

## Project Layout
```
backend/
  app/
    main.py               # FastAPI app, lifespan startup
    schema.py             # Pydantic v2 request/response schemas
    llama_index_settings.py  # LLM + embedding global config
    api/
      api.py              # Router aggregation
      crud.py             # DB query helpers (async SQLAlchemy)
      deps.py             # FastAPI dependency: get_db
      endpoints/
        health.py         # GET /api/health/
        documents.py      # POST /api/document/upload, GET /api/document/
        conversation.py   # POST/GET/DELETE /api/conversation/
    chat/
      engine.py           # Build OpenAIAgent per conversation
      messaging.py        # SSE streaming + callback handler
      pg_vector.py        # CustomPGVectorStore singleton
      qa_response_synth.py  # Custom LlamaIndex response synthesizer
      constants.py        # DB_DOC_ID_KEY, SYSTEM_MESSAGE, chunk sizes
      utils.py            # Document title/description builders
    core/
      config.py           # Pydantic Settings — reads env vars
    db/
      session.py          # Async engine + SessionLocal
      base.py             # Alembic model registry
      wait_for_db.py      # Startup DB health check
    models/
      base.py             # SQLAlchemy declarative Base (id, created_at, updated_at)
      db.py               # ORM models: Document, Conversation, Message, etc.
    ingestion/
      pdf.py              # Download PDF -> LlamaIndex nodes -> pgvector
    storage/
      supabase.py         # upload/download/delete/get_url helpers
  alembic/                # DB migrations
  tests/
    app/
      chat/test_engine.py         # Unit tests: get_chat_history
      test_refactored.py          # Unit tests: metadata, storage, upload, health
  pyproject.toml          # uv deps + scripts
  .env.development        # Local dev env vars (not committed)
  .env.example            # Template for env vars
  CONTEXT.md              # This file
```

## API Endpoints
Base prefix: `/api`
Swagger UI: `http://localhost:8000/api/docs`

| Method | Path | Description |
|---|---|---|
| GET | `/health/` | Liveness check -> `{"status": "alive"}` |
| POST | `/document/upload` | Upload PDF (multipart) + index -> DocumentUploadResponse |
| GET | `/document/` | List all documents (optionally filter by `?document_ids=`) |
| GET | `/document/{id}` | Get single document |
| POST | `/conversation/` | Create conversation linked to document IDs |
| GET | `/conversation/{id}` | Get conversation with messages |
| DELETE | `/conversation/{id}` | Delete conversation |
| GET | `/conversation/{id}/message` | SSE stream — send user message, receive streamed assistant response |
| GET | `/conversation/{id}/test_message` | Non-SSE version of /message — Swagger-friendly |

## DB Models
```
Document              id, url, metadata_map (JSONB)
Conversation          id
ConversationDocument  conversation_id, document_id  (M2M join)
Message               id, conversation_id, content, role, status
MessageSubProcess     id, message_id, source, status, metadata_map (JSONB)
```
Enums: `MessageRoleEnum` (user/assistant), `MessageStatusEnum` (PENDING/SUCCESS/ERROR)

## Key Schema Types (Pydantic v2)
- `NSEDocumentMetadata` — company_name (required), company_symbol, document_type, financial_year, exchange
- `DocumentUploadResponse` — id, url, metadata_map, status="indexed"
- `ConversationCreate` — document_ids: List[UUID]
- `Message` — conversation_id, content, role, status, sub_processes

## Required Environment Variables
```
DATABASE_URL               # PostgreSQL connection string
OPENAI_API_KEY             # OpenAI API key
SUPABASE_URL               # Supabase project URL
SUPABASE_SERVICE_ROLE_KEY  # Supabase service role key
```

Optional:
```
OPENAI_CHAT_LLM_NAME       # default: gpt-4o-mini
SUPABASE_STORAGE_BUCKET    # default: annual-reports
VECTOR_STORE_TABLE_NAME    # default: pg_vector_store
LOG_LEVEL                  # default: INFO
BACKEND_CORS_ORIGINS       # JSON array of allowed origins
SENTRY_DSN                 # Sentry DSN (optional)
```

## Developer Commands
```bash
# Install deps
uv sync

# Run dev server
uv run start

# Or directly:
uv run uvicorn app.main:app --reload --port 8000

# Run migrations
uv run alembic upgrade head

# Run tests
uv run pytest tests/ -v

# Generate a new migration
uv run alembic revision --autogenerate -m "description"
```

## Startup Sequence (lifespan)
1. `_setup_llama_index_settings()` — configure OpenAI LLM + embeddings globally
2. `check_database_connection()` — wait for Postgres
3. Alembic head check — raise if migrations are not current
4. `get_vector_store_singleton()` + `run_setup()` — ensure pgvector extension + table exist
5. NLTK sentence tokenizer pre-download

## RAG Architecture
```
Upload:  PDF bytes -> Supabase Storage -> LlamaIndex PDFReader -> VectorStoreIndex -> pgvector
Query:   User message
           -> OpenAIAgent
           -> SubQuestionQueryEngine (one sub-Q per doc)
           -> per-doc QueryEngineTool (MetadataFilter by DB_DOC_ID_KEY)
           -> pgvector similarity search
           -> custom response synthesizer (preserves INR units, cites page numbers)
           -> streaming SSE response
```

## Notes for Agents
- Always use `model_validate(..., from_attributes=True)` (Pydantic v2) — never `from_orm`.
- `DB_DOC_ID_KEY = "db_document_id"` is injected into every LlamaIndex node metadata at ingest time and used as the vector store filter key.
- `nest_asyncio.apply()` is called once in `engine.py` to allow nested event loops (LlamaIndex requirement).
- The `/conversation/{id}/test_message` endpoint is the Swagger-friendly alternative to the SSE `/message` endpoint.
