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

### 3.1 `conversation` (`models/db.py:52`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK, default `uuid_generate_v4()`, indexed (`ix_conversation_id`) |
| created_at | timestamp | no | `now()` |
| updated_at | timestamp | no | `now()` + ORM onupdate |

Relationships: `messages` → `Message.conversation`; `conversation_documents` →
`ConversationDocument.conversation`. No cascade configured.

### 3.2 `document` (`models/db.py:41`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| url | varchar | **no** | **UNIQUE** — Supabase public URL of the PDF |
| metadata_map | JSONB | yes | NSE metadata + content hash (below) |
| created_at / updated_at | timestamp | no | |

Created in migration `90a1d6a26343`. `crud.upsert_document_by_url` uses
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

Lookup helper: `crud.fetch_document_by_content_hash` uses
`Document.metadata_map["content_hash"].astext == content_hash` (`crud.py:162`).

### 3.3 `conversationdocument` (`models/db.py:63`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| conversation_id | UUID | yes | FK → `conversation.id`, indexed |
| document_id | UUID | yes | FK → `document.id`, indexed |
| created_at / updated_at | timestamp | no | |

Created in `90a1d6a26343`; indexes added in `873c0c4616ea`. No unique constraint on
`(conversation_id, document_id)` — the same document can be linked twice if the API is called
with duplicates.

### 3.4 `message` (`models/db.py:76`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| conversation_id | UUID | yes | FK → `conversation.id`, indexed |
| content | varchar | yes (DB) | **but `schema.Message.content: str` is required** |
| role | `MessageRoleEnum` | yes | `user` / `assistant` |
| status | `MessageStatusEnum` | yes | default in ORM: `PENDING` |

### 3.5 `messagesubprocess` (`models/db.py:91`)

| Column | Type | Null | Notes |
|---|---|---|---|
| id | UUID | no | PK |
| message_id | UUID | yes | FK → `message.id`, indexed |
| source | `MessageSubProcessSourceEnum` | yes | LlamaIndex event name |
| status | `MessageSubProcessStatusEnum` | **no** | default `FINISHED` |
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
    embed_dim=settings.VECTOR_STORE_EMBED_DIM, # 3072
)
```

| Property | Value |
|---|---|
| Data table | `data_pg_vector_store` (`data_` + table name) |
| Metadata table | `data_pg_vector_store_metadata_col` |
| Vector type | `vector(3072)` (pgvector), cosine distance |
| Columns | `id`, `node_id`, `text`, `metadata_` (JSONB), `embedding` |
| Per-doc key | `metadata_->>'db_document_id'` = `document.id` (constant `DB_DOC_ID_KEY`) |
| Page key | `metadata_->>'page_label'` (string; `Citation.from_node` casts to `int`) |
| Index id | `index.set_index_id(document_id)` (ingestion) — informational |
| Created by | `CustomPGVectorStore.run_setup()` (extension + `create_all`), once per deploy |

Chunking settings that determine table content: `SentenceSplitter(chunk_size=512,
chunk_overlap=10)` (`chat/constants.py:25`, applied in `llama_index_settings.py:22`).

> Changing `VECTOR_STORE_EMBED_DIM` or the embedding model requires dropping/recreating
> `data_pg_vector_store*` and re-indexing every document.

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

⚠ Lines 1-4 open a `/**` comment that is only closed on line 22, so the first four exported
types are commented out and do not exist at runtime/typecheck
(see `AGENTS.md §14.A`).

| Type | Shape |
|---|---|
| `NSEDocumentType` | `annual_report \| quarterly_results \| concall_transcript \| investor_presentation \| shareholding_pattern \| corporate_announcement` |
| `DocumentStatus` | `uploading \| parsing \| chunking \| embedding \| indexing \| ready \| failed` |
| `DocumentMetadata` | `company_name, nse_symbol, document_type, fiscal_year, period, pages, file_size, language` |
| `FinDocument` | `id, filename, status, progress, metadata, uploaded_at` |
| `SubProcessSource` | `llm \| retrieval \| rerank \| parser` |
| `SubProcessStatus` | `pending \| running \| completed \| failed` |
| `MessageSubProcess` | `id, name, source, status, detail?, duration_ms?` |
| `MessageRole` / `MessageStatus` | `user\|assistant` / `pending\|processing\|streaming\|completed\|failed` |
| `Source` | `index, document_id, page, excerpt, score` |
| `ChatMessage` | `id, conversation_id, role, content, status, sub_processes, sources, created_at` |
| `Conversation` | `id, title, document_scope[], messages[], created_at, updated_at` |
| `ConversationCreate` | `title, document_scope?` |
| `DocumentUploadResponse` | `{ document: FinDocument }` |
| `HealthResponse` | `status: healthy \| degraded \| down` |
| `View` | `chat \| library` |

### 7.1 Backend ⇄ frontend mismatch matrix (must be bridged before real mode)

| Concept | Backend | Frontend |
|---|---|---|
| Document id field | `Document.id` (UUID) | `FinDocument.id` (string, often `doc_*` mock ids) |
| Filename | `metadata_map.original_filename` | `FinDocument.filename` |
| Company ticker | `nse_document.company_symbol` | `metadata.nse_symbol` |
| Financial year | `nse_document.financial_year` | `metadata.fiscal_year` (e.g. `"FY2023-24"`) |
| Document type values | `financial_results`, `corporate_filing`, `investor_presentation`, `other` | `quarterly_results`, `concall_transcript`, `shareholding_pattern`, `corporate_announcement` |
| Page count / file size / period | not stored | `metadata.pages`, `metadata.file_size`, `metadata.period` |
| Indexing status | implicit (`status:"indexed"` on upload; no polling endpoint) | 7-state `DocumentStatus` driven by the mock pipeline |
| Message status | `PENDING \| SUCCESS \| ERROR` | `pending \| processing \| streaming \| completed \| failed` |
| Sub-process shape | `{message_id, source: CBEventType, status: PENDING\|FINISHED, metadata_map}` | `{id, name, source: llm\|retrieval\|rerank\|parser, status: pending\|running\|completed\|failed, detail?, duration_ms?}` |
| Citations | `metadata.sub_question.citations[{document_id,text,page_number,score}]` | top-level `ChatMessage.sources[{index,document_id,page,excerpt,score}]` |
| Conversation create | `{document_ids: [uuid]}` | `{title, document_scope: [id]}` |
| Conversation title | not persisted | client-side only |
| SSE frames | unnamed events, full `Message` JSON | expects `sub_process` / `delta` / `done` events |

A mapper module is required (the README's `lib/backend.ts` does not exist).

---

## 8. Schema change playbook

1. Edit `app/models/db.py` (and/or enums). If you add an enum **value**, you also need the
   rename/recreate dance (see §4) — Alembic autogenerate will not do it.
2. `cd backend && uv run alembic revision --autogenerate -m "…"` — review the generated file:
   enum changes and `server_default` edits are frequently missed.
3. `uv run alembic upgrade head`; `uv run alembic heads` must show exactly one head.
4. Update `app/schema.py` if the API shape changes; update `frontend/src/lib/types.ts` to match.
5. Update `docs/agents/DATA_MODELS.md` (this file) in the same commit.
6. If the change affects vector metadata (`db_document_id`, `page_label`), plan a re-index.
7. Remember `_bootstrap()` refuses to start when the DB is not at head — deploy migrations
   before the new image.
