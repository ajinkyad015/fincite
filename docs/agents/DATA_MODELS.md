# DATA MODELS — fincitee

Everything persisted or transmitted, with the exact Python/TypeScript shapes and the places that
produce them. Migration chain: `477cee72edc4` → `c008bb4f3f48` → `90a1d6a26343` →
`1b0b616e08c6` → `873c0c4616ea` → `663b3fea3024` (**head**, single head).

---

## 1. Conventions

`app/models/base.py:6`

```python
class Base(DeclarativeBase):
    id = Column(UUID, primary_key=True, index=True, default=func.uuid_generate_v4())
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()
```

- `id` is a **DB-side** default (`uuid_generate_v4()`), so a flushed row has an id but a
  transient one does not. Requires the `uuid-ossp` extension (created in migration #1).
- Table names are the lowercased class name: `messagesubprocess`, `conversationdocument`.
- Timestamps are naive UTC (`DateTime`), set by the server; `updated_at` is maintained by
  SQLAlchemy `onupdate` (not a DB trigger).
- Two different `UUID` types are in play: generic `sqlalchemy.UUID` in `models/base.py`,
  dialect `postgresql.UUID(as_uuid=True)` for FKs in `models/db.py`.

---

## 2. ER diagram

```
CONVERSATION 1───* MESSAGE 1───* MESSAGESUBPROCESS
      │
      └──1──* CONVERSATIONDOCUMENT *──1── DOCUMENT
                                             │
                                             └──(metadata_.db_document_id)── data_pg_vector_store
```

There is **no FK** between `DOCUMENT` and the vector table — the link is the JSONB key
`db_document_id` inside each vector row's `metadata_`.

---

## 3. Tables

### 3.1 `conversation` (`models/db.py`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK, default `uuid_generate_v4()`, indexed (`ix_conversation_id`) |
| title | varchar(200) | yes | set on create, or derived from the first question (`crud.touch_conversation`) |
| last_message_at | timestamp | yes | ordering key for the thread index, indexed (`b2e4d6f8a0c1`) |
| created_at | timestamp | no | `now()` |
| updated_at | timestamp | no | `now()` + ORM onupdate |

Relationships: `messages` → `Message.conversation`; `conversation_documents` →
`ConversationDocument.conversation`. Child FKs cascade (`d4b6f8c0e2a3`).

### 3.2 `document` (`models/db.py`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| url | varchar | **no** | **UNIQUE** — Supabase public URL of the PDF |
| metadata_map | JSONB | yes | NSE metadata + content hash (below) |
| status | `DocumentStatusEnum` | no | ingestion lifecycle, default `uploaded` (`a1f0c3d5b7e9`) |
| progress | integer | no | 0–100, written by the ingestion job |
| error | text | yes | set when `status = failed` |
| page_count | integer | yes | number of parsed pages |
| file_size | bigint | yes | bytes, from the upload body |
| content_hash | varchar(64) | yes | **UNIQUE index** — duplicate detection (promoted out of `metadata_map`) |
| created_at / updated_at | timestamp | no | `updated_at` drives the stale-ingestion sweep (15 min) |

Created in migration `90a1d6a26343`; lifecycle columns added in `a1f0c3d5b7e9`. `crud.upsert_document_by_url` uses
`INSERT … ON CONFLICT (url) DO UPDATE SET metadata_map = …` (Postgres dialect insert).

`metadata_map` (written at `api/endpoints/documents.py:143`):

```jsonc
{
  "nse_document": {
    "company_name": "Reliance Industries Limited",   // required
    "company_symbol": "RELIANCE",                    // optional
    "document_type": "annual_report",                 // enum, default annual_report
    "financial_year": "2025",                         // string, not int
    "report_date": "2025-08-28T12:00:00",             // ISO datetime or null
    "exchange": "NSE",                                // default "NSE"
    "original_filename": "reliance-ar.pdf"
  },
  "content_hash": "<sha256 hex>",                     // duplicate detection key
  "original_filename": "reliance-ar.pdf"              // duplicated at top level
}
```

Lookup helper: `crud.fetch_document_by_content_hash` matches the `content_hash` **column** (falling back
to `metadata_map["content_hash"]` for pre-backfill rows).

### 3.3 `conversationdocument` (`models/db.py:63`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| conversation_id | UUID | yes | FK → `conversation.id`, indexed |
| document_id | UUID | yes | FK → `document.id`, indexed |
| created_at / updated_at | timestamp | no | |

Created in `90a1d6a26343`; indexes added in `873c0c4616ea`; both FKs cascade on delete
(`d4b6f8c0e2a3`). No unique constraint on `(conversation_id, document_id)` — `crud.update_conversation`
replaces the whole set (delete-then-insert), which keeps duplicates out of that path.

### 3.4 `message` (`models/db.py:76`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| conversation_id | UUID | yes | FK → `conversation.id`, indexed |
| content | varchar | yes (DB) | **but `schema.Message.content: str` is required** |
| role | `MessageRoleEnum` | yes | `user` / `assistant` |
| status | `MessageStatusEnum` | yes | default in ORM: `PENDING` |
| sources | JSONB | yes | citations flattened onto the message (`c3a5e7b9d1f2`) |

`sources` mirrors the UI's `Source[]`: `[{index, document_id, page, excerpt, score}]`, derived from the
trail's SUB_QUESTION citations via `schema.citations_to_sources()`. Old rows may be `null` — readers
fall back to the sub-process metadata.

### 3.5 `messagesubprocess` (`models/db.py:91`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| message_id | UUID | yes | FK → `message.id`, indexed |
| source | `MessageSubProcessSourceEnum` | yes | LlamaIndex event name |
| status | `MessageSubProcessStatusEnum` | **no** | default `FINISHED` |
| name | varchar(300) | yes | research-trail label (`messaging.describe_sub_process`) |
| duration_ms | integer | yes | wall-clock time of the step |
| metadata_map | JSONB | yes | e.g. `{"sub_question": {...}}` |

`schema.MessageSubProcess.metadata_map` is keyed by `SubProcessMetadataKeysEnum.SUB_QUESTION`
(= LlamaIndex `EventPayload.SUB_QUESTION.value`, i.e. `"sub_question"`).

```jsonc
{"sub_question": {
   "question": "What was Reliance's FY2025 consolidated revenue?",
   "answer": "₹ 10,71,774 crore …",
   "citations": [{"document_id":"<uuid>","text":"…","page_number":112,"score":0.83}]
}}
```

Migration history for this table: created with a `content` varchar (`477cee72edc4`), then
`content` dropped and `status` + `metadata_map` added (`c008bb4f3f48`).

---

## 4. PostgreSQL enums

| Enum (PG type name) | Values | Created / extended by |
|---|---|---|
| `MessageRoleEnum` | `user`, `assistant` | `477cee72edc4` |
| `MessageStatusEnum` | `PENDING`, `SUCCESS`, `ERROR` | `477cee72edc4` |
| `MessageSubProcessStatusEnum` | `PENDING`, `FINISHED` | `c008bb4f3f48` |
| `MessageSubProcessSourceEnum` | every `CBEventType` name + `CONSTRUCTED_QUERY_ENGINE`, `SUB_QUESTIONS` | `477cee72edc4` → +`SUB_QUESTIONS` (`c008bb4f3f48`) → +`SUB_QUESTION` (`1b0b616e08c6`) → +`AGENT_STEP`, `TEMPLATING`, `FUNCTION_CALL`, `RERANKING`, `EXCEPTION` (`663b3fea3024`) |

The source enum is **generated at import time** from LlamaIndex:

```python
MessageSubProcessSourceEnum = Enum(
    "MessageSubProcessSourceEnum",
    [(e.name, e.value) for e in CBEventType] + [("CONSTRUCTED_QUERY_ENGINE", …), ("SUB_QUESTIONS", …)],
)
```

Adding values requires the rename→create→alter→drop dance used by every "update sub process
columns" migration (`replace_enum_values`), because Postgres cannot drop enum values in place.

---

## 5. Vector store

Managed entirely by `llama_index.vector_stores.postgres.PGVectorStore`
(`app/chat/pg_vector.py:71`):

```python
CustomPGVectorStore.from_params(
    url.host, url.port or 5432, url.database, url.username, url.password,
    settings.VECTOR_STORE_TABLE_NAME,          # "pg_vector_store"
    embed_dim=settings.VECTOR_STORE_EMBED_DIM, # 2048
)
```

| Property | Value |
|---|---|
| Data table | `data_pg_vector_store` (`data_` + table name) |
| Metadata table | `data_pg_vector_store_metadata_col` |
| Vector type | `vector(2048)` (pgvector), cosine distance |
| Columns | `id`, `node_id`, `text`, `metadata_` (JSONB), `embedding` |
| Per-doc key | `metadata_->>'db_document_id'` = `document.id` (constant `DB_DOC_ID_KEY`) |
| Page key | `metadata_->>'page_label'` (string; `Citation.from_node` casts to `int`) |
| Index id | `index.set_index_id(document_id)` (ingestion) — informational |
| Created by | `CustomPGVectorStore.run_setup()` (extension + `create_all`), once per deploy |

Chunking settings that determine table content: `SentenceSplitter(chunk_size=512,
chunk_overlap=10)` (`chat/constants.py:25`, applied in `llama_index_settings.py:22`).

> Changing `VECTOR_STORE_EMBED_DIM` or the embedding model requires dropping/recreating
> `data_pg_vector_store*` and re-indexing every document. If
> `NVIDIA_EMBEDDING_DIMENSIONS` is set, `Settings` rejects a value that differs from
> `VECTOR_STORE_EMBED_DIM` at boot — mixed dimensions break similarity search.

---

## 6. Pydantic API schemas (`app/schema.py`)

| Model | Fields | Notes |
|---|---|---|
| `Base` | `id: UUID?`, `created_at: datetime?`, `updated_at: datetime?` | `from_attributes=True` |
| `BaseMetadataObject` | — | `from_attributes=True` |
| `Citation` | `document_id: UUID`, `text: str`, `page_number: int`, `score: float?` | `from_node()` builds it from a `NodeWithScore`; validator returns `str` for `document_id` |
| `QuestionAnswerPair` | `question: str`, `answer: str?`, `citations: List[Citation]?` | `from_sub_question_answer_pair()` |
| `SubProcessMetadataKeysEnum` | `SUB_QUESTION = "sub_question"` | |
| `MessageSubProcess` | `message_id: UUID`, `source`, `status`, `metadata_map: dict?` | |
| `Message` | `conversation_id: UUID`, `content: str`, `role`, `status`, `sub_processes: List[MessageSubProcess]` | `sub_processes` is **required** |
| `UserMessageCreate` | `content: str` | declared but unused by endpoints (they take a query param) |
| `DocumentMetadataKeysEnum` | `NSE_DOCUMENT = "nse_document"` | |
| `NSEDocumentTypeEnum` | `annual_report`, `financial_results`, `corporate_filing`, `investor_presentation`, `other` | |
| `NSEDocumentMetadata` | `company_name` (required), `company_symbol?`, `document_type=annual_report`, `financial_year?`, `report_date?`, `exchange="NSE"`, `original_filename?` | |
| `Document` | `url: str`, `metadata_map: dict?` | |
| `DocumentUploadResponse` | + `url`, `metadata_map`, `status="indexed"` | 201 body |
| `Conversation` | `messages: List[Message]`, `documents: List[Document]` | |
| `ConversationCreate` | `document_ids: List[UUID]` | 404 if any id is unknown |

`schema.py` imports `DB_DOC_ID_KEY` from `chat/constants.py` and the four enums from
`models/db.py` — it is the junction between the ORM and the HTTP contract.

---

## 7. Frontend domain types (`frontend/src/lib/types.ts`)

M2 keeps these UI shapes intentionally stable; `npm run typecheck` is green. `frontend/src/lib/wire.ts`
maps every backend DTO into them.

| Type | Shape |
|---|---|
| `NSEDocumentType` | `annual_report \| quarterly_results \| concall_transcript \| investor_presentation \| shareholding_pattern \| corporate_announcement` |
| `DocumentStatus` | `uploading \| parsing \| chunking \| embedding \| indexing \| ready \| failed` |
| `DocumentMetadata` | `company_name, nse_symbol, document_type, fiscal_year, period, pages, file_size, language` |
| `FinDocument` | `id, filename, status, progress, metadata, uploaded_at, url?, error?` |
| `SubProcessSource` | `llm \| retrieval \| rerank \| parser` |
| `SubProcessStatus` | `pending \| running \| completed \| failed` |
| `MessageSubProcess` | `id, name, source, status, detail?, duration_ms?` |
| `MessageRole` / `MessageStatus` | `user\|assistant` / `pending\|processing\|streaming\|completed\|failed` |
| `Source` | `index, document_id, page, excerpt, score` |
| `ChatMessage` | `id, conversation_id, role, content, status, sub_processes, sources, created_at` |
| `Conversation` | `id, title, document_scope[], messages[], created_at, updated_at, message_count?, preview?` |
| `ConversationCreate` / `ConversationUpdate` | `title, document_scope?` |
| `DocumentUploadResponse` | `{ document: FinDocument }` |
| `HealthResponse` | `status: healthy \| degraded \| down` plus optional M1 fields |
| `View` | `chat \| library` |

### 7.1 Backend ⇄ frontend mapping (M2 `wire.ts`)

| Concept | Backend DTO | Domain rule |
|---|---|---|
| Filename | `metadata_map.original_filename` / nse metadata / URL | `FinDocument.filename` |
| Company ticker | `nse_document.company_symbol` | `metadata.nse_symbol ?? "—"` |
| Financial year | `nse_document.financial_year` | `normaliseFiscalYear()` → `FY2024-25` |
| Document type | M1 enum incl. legacy values | `financial_results→quarterly_results`, `corporate_filing/other→corporate_announcement` |
| Page count / size / period | `page_count`, `file_size`, `report_date` | `metadata.pages/file_size/period`, `0`/"—" when unknown |
| Indexing status | `uploaded…ready/failed` | `uploaded→uploading`, others direct, unknown→uploading |
| Message status | `PENDING \| SUCCESS \| ERROR` | `streaming`/`processing`, `completed`, `failed` |
| Trail source | LlamaIndex `CBEventType` | `RETRIEVE/SUB_QUESTION→retrieval`, `LLM/SYNTHESIZE→llm`, `RERANK→rerank`, unknown→parser |
| Citations | `message.sources` or `metadata.sub_question.citations` | deduplicated 1-based `Source[]`; `score` defaults to 0 |
| Conversation create/update | `{document_ids, title}` | `{title, document_scope}` |
| SSE frames | unnamed events, full `Message` JSON | `toChatMessage()` snapshot replacing state |

---

## 8. Schema change playbook

1. Edit `app/models/db.py` (and/or enums). If you add an enum **value**, you also need the
   rename/recreate dance (see §4) — Alembic autogenerate will not do it.
2. `cd backend && uv run alembic revision --autogenerate -m "…"` — review the generated file:
   enum changes and `server_default` edits are frequently missed.
3. `uv run alembic upgrade head`; `uv run alembic heads` must show exactly one head.
4. Update `app/schema.py` if the API shape changes; update `frontend/src/lib/wire.ts` (and `types.ts`
   only when the UI domain itself changes). Keep DTO names out of components.
5. Update `docs/agents/DATA_MODELS.md` (this file) in the same commit.
6. If the change affects vector metadata (`db_document_id`, `page_label`), plan a re-index.
7. Remember `_bootstrap()` refuses to start when the DB is not at head — deploy migrations
   before the new image.
