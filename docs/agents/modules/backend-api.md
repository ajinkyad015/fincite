# MODULE — backend HTTP & data layer

`backend/app/api/**`, `backend/app/db/**`, `backend/app/core/config.py`, `backend/app/schema.py`.

---

## 1. Files

| File | Responsibility | Key symbols |
|---|---|---|
| `api/api.py` | router registry | `api_router`; mounts `conversation` (`/conversation`), `documents` (`/document`), `health` (`/health`) |
| `api/deps.py` | request-scoped session | `get_db()` — `async with SessionLocal() as db: yield db` |
| `api/crud.py` | all SQL | 9 functions, see §3 |
| `api/endpoints/health.py` | liveness | `health()` |
| `api/endpoints/documents.py` | upload/list/get | `upload_document_endpoint`, `get_documents`, `get_document`, `_validate_pdf` |
| `api/endpoints/conversation.py` | CRUD + SSE | `create_conversation`, `get_conversation`, `delete_conversation`, `message_conversation`, `test_message_conversation` |
| `db/session.py` | engine + sessionmaker | `engine`, `SessionLocal` |
| `db/base.py` | Alembic metadata | re-exports `Base` + all models |
| `db/wait_for_db.py` | startup retry | `check_database_connection(max_attempts=30, sleep_interval=1)` |
| `core/config.py` | settings | `Settings`, `settings` (module singleton) |
| `schema.py` | API contracts | see `../DATA_MODELS.md §6` |

---

## 2. Layering rules

```
endpoint (validate, HTTP codes, response_model)
   └── crud (select/insert/update/delete + commit)
          └── models (tables)
```

- Endpoints never import `sqlalchemy` query builders (only `text("SELECT 1")` in `health`).
- `crud` returns **Pydantic schemas**, not ORM objects (`schema.X.model_validate(obj, from_attributes=True)`).
- Commits live in `crud` (`create_*`, `delete_*`, SSE persistence) — read helpers never commit.
- Every endpoint is `async def` and receives `db: AsyncSession = Depends(get_db)`.

---

## 3. `crud.py` function index

| Function | Line | Query shape | Notes |
|---|---|---|---|
| `fetch_conversation_with_messages(db, id)` | 11 | `joinedload(messages).subqueryload(sub_processes)` + `joinedload(conversation_documents).subqueryload(document)` | builds `{"documents": [...]}` into `schema.Conversation(**d)`; returns `None` if missing |
| `create_conversation(db, payload)` | 42 | ORM add of `Conversation` + N `ConversationDocument` | commits, refreshes, re-reads via `fetch_conversation_with_messages` |
| `delete_conversation(db, id)` | 57 | `delete(Conversation)` | ⚠ no child cleanup — FK violation if messages exist |
| `fetch_message_with_sub_processes(db, id)` | 64 | `joinedload(sub_processes)` | used for the final SSE frame |
| `fetch_documents(db, id=None, ids=None, url=None, limit=None)` | 83 | `select(Document)` with optional filters | `id` forces `limit=1`; used by both document endpoints and conversation validation |
| `create_document(db, document)` | 108 | ORM add | expects `document.id` already set (UUID from the endpoint) |
| `delete_document_by_id(db, id)` | 125 | `delete(Document)` | rollback path for failed indexing |
| `upsert_document_by_url(db, document)` | 135 | `insert(...).on_conflict_do_update(index_elements=[Document.url])` | used only by `scripts/upsert_document.py` |
| `fetch_document_by_content_hash(db, hash)` | 155 | `Document.metadata_map["content_hash"].astext == hash` | duplicate detection |

Gotchas: `crud.py` imports `uuid as uuid_module` without using it; `upsert_document_by_url`
commits **after** validation of the returned row; the JSONB `astext` filter is unindexed (fine at
small scale, add a GIN/expression index if the library grows).

---

## 4. Settings (`core/config.py`)

```python
class Settings(BaseSettings):
    PROJECT_NAME: str = "fincite"
    API_PREFIX: str = "/api"
    DATABASE_URL: str            # required
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "annual-reports"
    NVIDIA_API_KEY: str          # required (any /v1 endpoint)
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    # Chat model profile — ids + DECLARED capabilities (no model table)
    NVIDIA_CHAT_LLM_NAME: str = "meta/llama-3.3-70b-instruct"
    NVIDIA_CHAT_IS_CHAT_MODEL: bool = True
    NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL: bool = False
    NVIDIA_CHAT_CONTEXT_WINDOW: int = 131072
    NVIDIA_CHAT_MAX_TOKENS: int = 4096
    NVIDIA_CHAT_TIMEOUT: float = 120.0
    # Embedding model profile
    NVIDIA_EMBEDDING_MODEL_NAME: str = "nvidia/nemotron-3-embed-1b"
    NVIDIA_EMBEDDING_REQUEST_STYLE: Literal["nim", "openai"] = "nim"
    NVIDIA_EMBEDDING_TRUNCATE: Literal["NONE", "START", "END"] = "END"
    NVIDIA_EMBEDDING_DIMENSIONS: Optional[int] = None
    VECTOR_STORE_TABLE_NAME: str = "pg_vector_store"
    VECTOR_STORE_EMBED_DIM: int = 2048
    LOG_LEVEL: str = "INFO"
    BACKEND_WORKERS: int = 4
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl | Literal["*"]] = []
    SENTRY_DSN: Optional[str] = None
```

Validators (`mode="before"`):

| Field | Behaviour |
|---|---|
| `BACKEND_CORS_ORIGINS` | accepts JSON list string or comma-separated string |
| `DATABASE_URL` | must start with `postgres`; `postgres://`→`postgresql://`→`postgresql+asyncpg://` (idempotent) |
| `LOG_LEVEL` | upper-cased; rejects anything outside DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `NVIDIA_BASE_URL` | strips whitespace + trailing slash (one canonical form for both clients) |
| `NVIDIA_CHAT_LLM_NAME`, `NVIDIA_EMBEDDING_MODEL_NAME` | trimmed; blank ids rejected — model ids are free-form, never checked against a list |
| `NVIDIA_CHAT_CONTEXT_WINDOW` / `MAX_TOKENS` / `VECTOR_STORE_EMBED_DIM` | must be positive; `NVIDIA_CHAT_TIMEOUT` too |
| `model_validator` (`mode="after"`) | `NVIDIA_EMBEDDING_DIMENSIONS` (if set) must equal `VECTOR_STORE_EMBED_DIM` |

`settings` is instantiated at import, so **importing anything under `app` requires
`DATABASE_URL` and `NVIDIA_API_KEY`** (tests set them in `conftest.py`). Key and endpoint are
passed explicitly to both model clients in `llama_index_settings.py`; the old
`os.environ["NVIDIA_API_KEY"]` / `NVIDIA_BASE_URL` side effects were removed.
`NVIDIA_*` names are historical — they configure a generic OpenAI-compatible endpoint.

Env file: `.env` in the CWD (`env_file=".env"`, no prefix). See `backend/.env.example`.

---

## 5. Session & pool (`db/session.py`)

```python
engine = create_async_engine(settings.DATABASE_URL,
    pool_pre_ping=True, pool_size=4, max_overflow=4, pool_recycle=3600, pool_timeout=120)
SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine,
                                  expire_on_commit=False)
```

`expire_on_commit=False` is mandatory for async sessions here: with the default (`True`), a
commit expires ORM instances and the next `message.id` / `assistant.created_at` read performs
an implicit **sync** lazy load → `sqlalchemy.exc.MissingGreenlet`. The SSE path additionally
copies those scalars before later commits, and `crud.finalise_message` uses the `message_id`
argument rather than `message.id` after `commit()`. Code that needs fresh values calls
`await db.refresh(...)` or re-queries (see `create_message`, `fetch_message_with_sub_processes`).

`pool_size=4 + max_overflow=4` per process ⇒ with `BACKEND_WORKERS=4` the app can open **32**
connections. Supabase free/pooler tiers have low limits — lower `BACKEND_WORKERS` if you see
`TimeoutError: connection pool exhausted` (pool_timeout=120 s).

The same engine is reused by the vector store (`chat/pg_vector.py:24`), so one pool serves both.

---

## 6. Endpoint conventions

- Paths end in `/` for collections; path params typed as `uuid.UUID`.
- Optional filters via `fastapi.Query`; uploads via `File`/`Form` (`python-multipart`).
- `response_model=` used only on `/document/upload`; other routes use return annotations.
- `status_code=201` for upload, `204` + `response_model=None` for delete.
- Errors are raised as `HTTPException`; nothing is wrapped in a custom exception handler.
- Long-running work (indexing) is inline — see `AGENTS.md §14.I`.

## 7. Adding an endpoint (checklist)

1. Add/extend a schema in `app/schema.py`.
2. Add a `crud` function if it touches SQL (keep queries there).
3. Write `@router.<verb>("…")` in the right `endpoints/*.py`; annotate the return type.
4. Register a new router (if any) in `api/api.py` with a prefix + tag.
5. Add a test under `backend/tests/app/…` using `AsyncMock(spec=AsyncSession)`.
6. Update `docs/agents/API_REFERENCE.md` and, if the shape reaches the UI, `frontend/src/lib/types.ts`.
