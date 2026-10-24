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
| Google AI key | — | https://aistudio.google.com/apikey |

There is no `Makefile`, no `justfile`, no CI workflow, and no task runner.

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
GOOGLE_API_KEY=<key>
# required for anything that touches Storage (i.e. all uploads):
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_STORAGE_BUCKET=annual-reports
```

`DATABASE_URL` may be written as `postgres://…`, `postgresql://…` or
`postgresql+asyncpg://…`; `core/config.py:54` normalises it to asyncpg form. The sync head-check
engine rewrites it back to `psycopg2`.

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
npm ci          # ✅ 6-7 s
npm run dev     # vite dev server (default http://localhost:5173)
npm run build   # ✅ single-file dist/index.html (~622 kB, ~189 kB gzip)
npm run preview # serve the built file
```

Only three scripts exist (`dev`, `build`, `preview`). The README mentions `dev:mock`,
`typecheck` and `check:adapter` — **they do not exist**.

**Current mode:** `frontend/src/lib/api.ts:32` `export const USE_MOCK = true;` — the UI runs
entirely on `lib/mockData.ts` (5 seeded filings, 4 canned Q&A banks). No backend is contacted, so
`npm run dev` alone gives a fully interactive demo. Flipping the constant to `false` exposes an
incomplete `RealTransport` (§`API_REFERENCE.md §6`) — do not ship that.

**If you need a live dev proxy** (it does not exist yet), add to `vite.config.ts`:

```ts
server: { proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } } }
```

and then switch `BASE_URL` to `""`/relative so the browser calls the same origin.

---

## 4. Tests

```bash
cd backend && uv run pytest -q
```

✅ Observed: **15 passed, 4 warnings in ~8 s**. No database, no API key, no network — `conftest.py`
injects dummy env vars before import and every external boundary is patched.

Warnings you will see (all third-party, ignore): `supabase`/`gotrue`/`supafunc` deprecations,
`google.generativeai` end-of-life, `google.api_core` Python-version notice.

```bash
cd frontend && npx tsc --noEmit
```

❌ Observed: **5 errors** — `types.ts` has an unterminated leading comment (swallows four type
exports) plus one unused import in `Sidebar.tsx`. Fix those two files before trusting typecheck.

There is **no** frontend test runner, no integration test, no evaluation harness for answer
quality (the README lists the latter as roadmap).

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

**Frontend only, no backend** — `npm run dev`; everything is mock (`USE_MOCK = true`), including
uploads (simulated 4-stage pipeline) and health (`healthy`).

**Full stack with a remote DB** — set `.env` to the Supabase pooled connection string, run
`uv run alembic upgrade head` once, `uv run start`, then either fix `RealTransport` or keep using
the mock UI for screenshots.

**Preview build** — `npm run build` produces one self-contained `dist/index.html` you can serve
from any static host. Fonts are still loaded from `fonts.googleapis.com` (`index.html`), so an
offline environment falls back to Georgia/system fonts.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: fire` running a script | `fire` not declared | add dependency or use `argparse` |
| `pytest` can't import `app` | run from repo root | `cd backend` first |
| `Settings` validation error on import | `DATABASE_URL` / `GOOGLE_API_KEY` unset | export both (or rely on `conftest.py` in tests) |
| Boot: "Database is not up to date" | migrations behind | `uv run alembic upgrade head` |
| Upload 500 "must be set to use Supabase Storage" | missing `SUPABASE_*` | set them; restart |
| Upload 422 | unreadable/corrupt PDF, or embeddings failed | check logs with `LOG_LEVEL=DEBUG`, retry smaller file |
| Answers have no citations | nodes missing `db_document_id`/`page_label`, or doc not indexed | re-upload; verify with the SQL above |
| Deleting a thread 500s | FK violation (no cascade) | see `AGENTS.md §14.E` |
| `tsc` errors about `FinDocument` | broken comment in `types.ts` | close the `/**` on line 1-4 |
| Frontend shows data that does not exist in the DB | mock transport | expected (`USE_MOCK = true`) |
| Vite build enormous | `viteSingleFile()` inlines everything | expected by design |
