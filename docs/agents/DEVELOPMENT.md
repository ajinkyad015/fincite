# DEVELOPMENT — fincitee

Setup, run, build, test, and troubleshoot. Verified commands are marked ✅ with the observed
output; ❌ marks commands that currently fail (see `AGENTS.md §14`).

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.11.x** (`>=3.11,<3.12`; lock is `==3.11.*`) | 3.12 will not resolve `uv.lock` |
| uv | any recent | installs from `backend/uv.lock` |
| Node + npm | Node 20+ | frontend only |
| PostgreSQL + pgvector | 14+ | Supabase project **or** `ankane/pgvector` via compose |
| Supabase project | — | Storage bucket (default `annual-reports`) + service-role key |
| Model API key | — | default provider: https://build.nvidia.com — sign in, open any model, "Get API Key" (`nvapi-…`). Any OpenAI-compatible endpoint works (set `NVIDIA_BASE_URL`); no API key is needed for an unauthenticated local server — use any non-empty string. |

There is no `Makefile`, `justfile`, or task runner. `.github/workflows/ci.yml` runs backend pytest,
frontend typecheck and both frontend builds on pushes/PRs.

---

## 2. Backend setup

```bash
cd backend
cp .env.example .env          # then edit
uv sync                       # ✅ installs runtime + dev group from uv.lock
uv run alembic upgrade head    # ✅ single head: 663b3fea3024
uv run start                  # bootstrap + uvicorn on 0.0.0.0:8000
```

Minimum `.env` to boot:

```dotenv
DATABASE_URL=postgresql://postgres:<pw>@<host>:5432/postgres
NVIDIA_API_KEY=nvapi-<key>
# required for anything that touches Storage (i.e. all uploads):
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_STORAGE_BUCKET=annual-reports
```

`DATABASE_URL` may be written as `postgres://…`, `postgresql://…` or
`postgresql+asyncpg://…`; `core/config.py` normalises it to asyncpg form. The sync head-check
engine rewrites it back to `psycopg2`.

**Changing models:** copy the whole *chat model profile* / *embedding model profile* block from
`.env.example`, then edit ids and declared capabilities together. For example, to use
`nvidia/nemotron-3.5-bolt-e4b`:

```dotenv
NVIDIA_CHAT_LLM_NAME=nvidia/nemotron-3.5-bolt-e4b
NVIDIA_CHAT_IS_CHAT_MODEL=true
NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL=false
NVIDIA_CHAT_CONTEXT_WINDOW=<that model's context length>
NVIDIA_CHAT_MAX_TOKENS=<that model's max output tokens>
NVIDIA_CHAT_TIMEOUT=120
```

No code change, no catalog lookup, no restart-time `GET /v1/models`. Startup logs
`Models configured — chat=… embeddings=… endpoint=…`. Booleans are mandatory:
`LLMMetadata` rejects `None` (that was the first-message crash). For a plain
`/v1/embeddings` provider set `NVIDIA_EMBEDDING_REQUEST_STYLE=openai`; if the embedding
dimension changes, drop and recreate `data_pg_vector_store`, then re-index every document.

**Supabase storage layout:** bucket `SUPABASE_STORAGE_BUCKET`, object key
`documents/{document_id}/original.pdf`. Create the bucket before the first upload.

**Local DB instead of Supabase:**

```bash
cd backend && docker compose up -d db       # ankane/pgvector on the compose network
# ⚠ compose maps 127.0.0.1:5433:5433 but Postgres listens on 5432 — see AGENTS.md §14.F
docker compose exec db psql -U user -d fincite_db -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

The backend container gets `DATABASE_URL=postgresql://user:password@db:5432/fincite_db`. Storage
still requires real Supabase credentials even in local mode.

---

## 3. Frontend setup

```bash
cd frontend
npm ci               # ✅ pinned dependencies
npm run dev          # live API via the same-origin /api proxy (default)
npm run dev:mock     # explicit seeded demo, no backend
npm run typecheck    # ✅ 0 errors
npm run build        # ✅ single-file dist/index.html (real mode)
npm run build:demo   # ✅ single-file build with VITE_USE_MOCK=1
npm run preview      # serve the built file
```

**Current mode (M2):** `USE_MOCK` defaults to false. `VITE_API_URL` defaults to `""`, so the Vite
proxy forwards `/api/*` to `VITE_PROXY_TARGET` (default `http://127.0.0.1:8000`). `wire.ts` and
`transport.ts` implement the M1 contract; no source edits are needed to switch between real and demo
mode.

---

## 4. Tests

```bash
cd backend && uv run pytest -q
```

✅ Observed 2026-10-27: **70 passed, 2 warnings in ~4 s**. No database, no API key, no network —
`conftest.py` injects dummy env vars before import and every external boundary is patched.

Warnings you will see (all third-party, ignore): `supabase`/`gotrue`/`supafunc` deprecations.
The old pydantic protected-namespace notice (from `llama-index-llms-nvidia`'s `Model` table) and
"Unable to determine validity of …" (from the pinned embeddings client's model table) are gone —
both clients are now constructed and validated from config.

```bash
cd frontend && npm run typecheck
cd frontend && npm run build
cd frontend && npm run build:demo
```

✅ Observed 2026-10-27: **0 typecheck errors**, both builds succeed. The M2 mapper/SSE adapter was
also exercised with a temporary Node harness; there is still no committed frontend test runner, no
automated browser E2E test, and no answer-quality evaluation harness. Use
`./scripts/smoke.sh <base-url> <real.pdf>` against a configured live backend for the end-to-end
contract.

---

## 5. Linting / formatting

None configured.

- `pylint==2.17.5` is a dev dependency but there is no `.pylintrc` / `[tool.pylint]`; a bare run
  will produce mostly style noise.
- No ESLint, Prettier, or Biome config; no `format` script.
- The de-facto checks are `uv run pytest`, `npx tsc --noEmit`, and `npm run build`.

Do not add a linter to the repo without asking (see `AGENTS.md §15`).

---

## 6. Database & migrations

```bash
cd backend
uv run alembic current          # applied revision
uv run alembic heads            # 663b3fea3024 (head) — must be exactly one
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "add x"
uv run alembic downgrade -1     # review before use: enum downgrades are lossy
```

- `alembic/env.py` overrides `sqlalchemy.url` with `settings.DATABASE_URL` (printed on every run),
  so `alembic.ini`'s `llama_app_db` default is dead weight.
- Migrations run on an **async** engine (`asyncio.run(run_async_migrations())`).
- The app refuses to boot when the DB is not at head (`main.py:95`).
- Enum changes require the manual rename/create/alter/drop pattern (`replace_enum_values`) used in
  `c008bb4f3f48`, `1b0b616e08c6`, `663b3fea3024`.
- Vector tables are **not** managed by Alembic — `CustomPGVectorStore.run_setup()` creates them
  at deploy time (`chat/pg_vector.py:39`). Recreating them means re-indexing every document.

Inspect state:

```sql
SELECT version_num FROM alembic_version;
SELECT id, metadata_map->'nse_document'->>'company_name' AS company FROM document;
SELECT count(*), metadata_->>'db_document_id' FROM data_pg_vector_store GROUP BY 2;
```

---

## 7. Scripts (`backend/scripts/`)

| Script | Purpose | Status |
|---|---|---|
| `chat_llama.py` | interactive CLI over the SSE API (`fetch`, `select`, `create`, `message`); needs `requests` + `sseclient-py` | works (no `fire` import) |
| `build_vector_tables.py` | manual `run_setup()` | ❌ `import fire` — not a dependency |
| `dedupe_vector_store.py` | dedupe rows in `data_pg_vector_store` (interactive confirm) | ❌ `import fire` |
| `upsert_document.py` | insert a `Document` row by URL | ❌ `import fire` |

Run the CLI:

```bash
cd backend && uv run python scripts/chat_llama.py --base_url http://localhost:8000
(Pick📄) fetch ⏎  select 0 ⏎  finish ⏎
(Chat🦙) create ⏎  message What was FY2025 revenue? ⏎
```

---

## 8. Docker

```bash
cd backend
docker compose up --build          # backend + db
```

`Dockerfile` (python:3.11.3-slim-bullseye): copies `uv`, runs
`uv sync --frozen --no-dev --no-install-project`, pre-downloads NLTK `punkt`/`punkt_tab`, copies
source, `uv sync --frozen --no-dev`, then `CMD ["/app/.venv/bin/start"]` (avoids re-syncing the
dev group at start). Workdir `/app` = `backend/`, so `alembic.ini` resolves.

Compose caveats: `.env` is loaded via `env_file`; `DATABASE_URL` and `BACKEND_CORS_ORIGINS` are
overridden; the DB port mapping is wrong (`5433:5433`) and `version: '3'` is obsolete; the backend
port is published on `127.0.0.1:8000` only.

---

## 9. Environment recipes

**Backend only, no frontend** — Swagger at `http://localhost:8000/api/docs`; use
`/test_message` (SSE is not rendered) or `curl -N` on `/message`.

**Frontend only, no backend** — `npm run dev:mock`; everything is seeded demo data
(`VITE_USE_MOCK=1`), including uploads (simulated 4-stage pipeline) and health (`healthy`).

**Full stack with a remote DB** — set `backend/.env` to the Supabase pooled connection string, run
`uv run alembic upgrade head` once, `uv run start`, then `npm run dev` (or `npm run dev:real`). The
UI uses real documents, conversations, POST SSE, citations and PDF links. Run
`./scripts/smoke.sh http://localhost:8000 path/to/filing.pdf` for a CLI contract check.

**Preview build** — `npm run build` produces one self-contained `dist/index.html` you can serve
from any static host. Fonts are still loaded from `fonts.googleapis.com` (`index.html`), so an
offline environment falls back to Georgia/system fonts.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: fire` running a script | `fire` not declared | add dependency or use `argparse` |
| `pytest` can't import `app` | run from repo root | `cd backend` first |
| `Settings` validation error on import | `DATABASE_URL` / `NVIDIA_API_KEY` unset | export both (or rely on `conftest.py` in tests) |
| Boot: "Database is not up to date" | migrations behind | `uv run alembic upgrade head` |
| Upload 500 "must be set to use Supabase Storage" | missing `SUPABASE_*` | set them; restart |
| Upload 422 | unreadable/corrupt PDF, or embeddings failed | check logs with `LOG_LEVEL=DEBUG`, retry smaller file |
| Boot: vector-table dimension mismatch | embedding model/`VECTOR_STORE_EMBED_DIM` changed without recreating the table | `DROP TABLE data_pg_vector_store`, restart, then `POST /api/document/{id}/reindex` for every document |
| 410/404 from the model endpoint | catalog model retired (ids on build.nvidia.com are versioned) | set `NVIDIA_CHAT_LLM_NAME`/`NVIDIA_EMBEDDING_MODEL_NAME` to the successor (embedding change ⇒ table recreate + re-index; also re-check the whole chat profile: `NVIDIA_CHAT_CONTEXT_WINDOW`/`MAX_TOKENS`/`IS_CHAT_MODEL`/`IS_FUNCTION_CALLING_MODEL`) |
| `LLMMetadata: 2 validation errors … is_chat_model / is_function_calling_model … input_value=None` on first message | a client inferred capabilities from a frozen model table (pre-Oct-2026 `llama-index-llms-nvidia`) or a metadata field is `None` | use the current `OpenAILike` factory and set `NVIDIA_CHAT_IS_CHAT_MODEL` / `NVIDIA_CHAT_IS_FUNCTION_CALLING_MODEL` explicitly in `.env`; both must be `true`/`false`, never blank |
| `sqlalchemy.exc.MissingGreenlet` in `crud.finalise_message` / final answer stuck in PENDING | an ORM attribute was read after `commit()` (implicit lazy load in async code) | keep `SessionLocal(expire_on_commit=False)`; use the `message_id` argument and copied scalars (`assistant_id`, `created_at`), never `message.<attr>` after commit |
| Answers have no citations | nodes missing `db_document_id`/`page_label`, or doc not indexed | re-upload; verify with the SQL above |
| Deleting a thread 500s | regression in cascade delete | see `AGENTS.md §14.E`; M1 fixed this |
| `tsc` errors about `FinDocument` | regression in `types.ts` or a new mapper | run `npm run typecheck`; the M0 broken comment is fixed |
| Frontend shows seeded data that does not exist in the DB | explicit demo mode | expected only with `VITE_USE_MOCK=1`; otherwise check `/api` proxy/backend |
| Vite build enormous | `viteSingleFile()` inlines everything | expected by design |
