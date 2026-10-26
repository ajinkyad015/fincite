# Fincite Backend

FastAPI · Python 3.11 · LlamaIndex · PostgreSQL + pgvector · Supabase Storage · Gemini.

**Full documentation**

| Document | Contents |
|---|---|
| [`../README.md`](../README.md) | Product, architecture, quick start |
| [`../docs/agents/API_REFERENCE.md`](../docs/agents/API_REFERENCE.md) | Every route, request/response shapes, SSE contract |
| [`../docs/agents/ARCHITECTURE.md`](../docs/agents/ARCHITECTURE.md) | Retrieval harness, streaming lifecycle |
| [`../docs/agents/DATA_MODELS.md`](../docs/agents/DATA_MODELS.md) | Tables, enums, vector store |
| [`../docs/plans/connect-and-deploy.md`](../docs/plans/connect-and-deploy.md) | Frontend integration + deployment roadmap |
| [`../AGENTS.md`](../AGENTS.md) | Repo rules, invariants, known issues |

## Run

```bash
cp .env.example .env          # DATABASE_URL, SUPABASE_*, GOOGLE_API_KEY
uv sync
uv run alembic upgrade head   # create/patch tables (must be at head before boot)
uv run start                  # bootstrap + uvicorn on 0.0.0.0:8000
```

`uv run pytest -q` runs the suite with no database and no API key.

## Notes for this layer

* **Uploads are asynchronous.** `POST /api/document/upload` returns `202`; `app/ingestion/jobs.py`
  indexes in the background and writes `status`/`progress`/`error`. One ingestion at a time per process
  (semaphore); a boot-time sweep fails anything left mid-ingest for >15 min.
* **The SSE endpoint keeps the database honest.** The user message and the assistant placeholder are
  committed before generation; content is flushed every ~1.5 s / 200 chars; the terminal state is written
  even if the client disconnects.
* **Deleting a filing must clear vectors first.** pgvector rows are not covered by the relational FK
  cascade, so `DELETE /api/document/{id}` fails closed (503) if the vector delete fails.
* **Enum values are lowercase and equal to their names** (`DocumentStatusEnum`). SQLAlchemy stores the
  *name*; a mismatch between name and value silently diverges from what the API documents.
* Migrations must stay at a single head — `_bootstrap()` refuses to start otherwise.
