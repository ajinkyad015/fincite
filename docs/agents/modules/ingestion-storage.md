# MODULE — ingestion, storage & startup DDL

`backend/app/ingestion/**`, `backend/app/storage/**`, and the vector/DB bootstrap in
`backend/app/main.py` + `backend/app/chat/pg_vector.py`.

---

## 1. Storage abstraction — `app/storage/supabase.py`

| Function | Line | Behaviour |
|---|---|---|
| `get_supabase_client()` | 23 | lazy singleton; raises `RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set…")` if either is empty |
| `_storage_path(document_id)` | 39 | `documents/{document_id}/original.pdf` |
| `upload_document(bytes, id)` → `str` | 44 | `storage.from_(bucket).upload(path, file, file_options={"content-type":"application/pdf","upsert":"false"})`; raises `RuntimeError` on failure; returns the **path** (not a URL) |
| `download_document(id)` → `bytes` | 74 | `storage.from_(bucket).download(path)`; raises `RuntimeError` |
| `delete_document(id)` | 97 | `remove([path])`; **logs a warning instead of raising** so cleanup never cascades |
| `get_document_url(id)` → `str` | 118 | `get_public_url(path)` |

Notes

- The service-role key is used server-side only; it is never echoed in a response.
- `upsert: "false"` means a re-upload with the same id would fail — ids are always new UUIDs, so
  this only matters if you retry the same upload after a partial failure.
- `get_public_url` assumes a public (or public-read) bucket. Private buckets need
  `create_signed_url`, otherwise the persisted `Document.url` is not fetchable by clients (the
  server can still download via the authenticated client, so ingestion works either way).
- Module global `_supabase_client` is not thread-safe/locked; tests reset it manually.

---

## 2. Ingestion — `app/ingestion/pdf.py`

```
download_document(document_id)                         :89
  └─ load_pdf_from_bytes(pdf_bytes, document_id)        :37
        TemporaryDirectory()/{id}.pdf
        PDFReader().load_data(tmp_path, extra_info={DB_DOC_ID_KEY: document_id})
        → List[llama_index.core.schema.Document]  (one per page; metadata.page_label)
  └─ if not llama_docs: ValueError("PDFReader produced no documents …")
StorageContext.from_defaults(vector_store=vector_store)  :102
VectorStoreIndex.from_documents(llama_docs,
      storage_context=…, show_progress=True,
      callback_manager=… (optional))                     :107
index.set_index_id(document_id)                          :113
return index
```

- Chunking is **not** done here: `VectorStoreIndex.from_documents` applies the global
  `Settings.node_parser` configured in `llama_index_settings.py` (`SentenceSplitter(512, 10)`).
- Embeddings come from `Settings.embed_model` (Gemini, 3072-d).
- `ingest_document` is `async def` but its body is fully synchronous (parse + embed + insert). It
  blocks the event loop for the whole request — `AGENTS.md §14.I`.
- `callback_manager` is optional and only the tests pass one; production upload does not stream
  ingestion progress to the client.

### Metadata carried onto every node

| Key | Source | Consumers |
|---|---|---|
| `db_document_id` (`DB_DOC_ID_KEY`) | `extra_info` at parse time | `ExactMatchFilter` per-document tool, `Citation.from_node` |
| `page_label` | `PDFReader` | `Citation.from_node` → `page_number` |
| `file_path`, `file_name`, `file_type`, `page_label`, `total_pages` … | `PDFReader` | informational |

---

## 3. Startup DDL & bootstrap — `app/main.py`

```
start() → _bootstrap(release_connections=True)                     main.py:81
  1 check_database_connection()                                    db/wait_for_db.py:6
      30 attempts × 1 s, asyncpg SELECT 1 via SessionLocal
  2 Alembic head check                                             main.py:88-100
      Config("alembic.ini")                     ← CWD relative
      db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://","postgresql+psycopg2://")
      engine = create_engine(db_url); check_current_head(cfg, engine)
      check_current_head = set(MigrationContext.get_current_heads())
                           == set(ScriptDirectory.get_heads())
      mismatch ⇒ Exception("Database is not up to date. Please run `uv run alembic upgrade head`")
  3 vector_store = cast(CustomPGVectorStore, await get_vector_store_singleton())
      await vector_store.run_setup()                               pg_vector.py:39
        _initialize()
        CREATE EXTENSION IF NOT EXISTS vector           (own session, commit)
        conn.run_sync(base.metadata.create_all)         (data_pg_vector_store*)
        did_run_setup = True (module global)
  4 split_by_sentence_tokenizer()   — forces NLTK punkt download; FileExistsError tolerated
  5 if release_connections: vector_store.close()      (parent only)
```

Workers (`lifespan`, `main.py:119`) skip everything when `FINCITE_BOOTSTRAP_DONE == "1"`, then:

```python
await asyncio.to_thread(_setup_llama_index_settings)      # Gemini ctor does blocking I/O
(await get_vector_store_singleton()).ensure_initialized() # pools only, no DDL
```

Shutdown calls `vector_store.close()` (disposes the shared async engine for that process).

The Dockerfile also pre-downloads `punkt` and `punkt_tab` at build time so first-request latency
does not include an NLTK download.

---

## 4. Failure & cleanup semantics

| Scenario | Effect | Code |
|---|---|---|
| DB down at boot | retries 30×, then `ValueError` | `wait_for_db.py:16` |
| Migrations behind | hard failure (no auto-upgrade) | `main.py:95` |
| `vector` extension not installable | `run_setup` raises → boot fails | `pg_vector.py:46` |
| NLTK download fails (air-gapped) | `FileExistsError` only is tolerated; other errors propagate | `main.py:108-111` |
| Upload → DB insert fails | storage object deleted | `documents.py:152-159` |
| Upload → indexing fails | DB row + storage object deleted → 422 | `documents.py:166-174` |
| `delete_document` fails during rollback | warning only, original error still raised | `supabase.py:110-115` |

What is **not** cleaned up: partially written vector rows after a mid-batch embedding failure, and
vectors belonging to a deleted `Document` (nothing deletes documents today).

---

## 5. Operational queries

```sql
-- objects vs rows vs vectors
SELECT d.id, d.metadata_map->'nse_document'->>'company_name' AS company,
       (SELECT count(*) FROM data_pg_vector_store v
         WHERE v.metadata_->>'db_document_id' = d.id::text) AS vectors
FROM document d ORDER BY d.created_at DESC;

-- duplicate detection sanity
SELECT metadata_map->>'content_hash' AS h, count(*) FROM document GROUP BY 1 HAVING count(*) > 1;

-- vector table size
SELECT count(*) FROM data_pg_vector_store;
```

Cleanup of a document (manual, since there is no endpoint):

```sql
DELETE FROM data_pg_vector_store WHERE metadata_->>'db_document_id' = '<doc-uuid>';
DELETE FROM conversationdocument WHERE document_id = '<doc-uuid>';
DELETE FROM document WHERE id = '<doc-uuid>';
-- then remove documents/<doc-uuid>/original.pdf from the Supabase bucket
```

`scripts/dedupe_vector_store.py` uses the same table name (`data_pg_vector_store`) but is
currently unrunnable (`fire` missing) and hardcodes the table instead of reading
`VECTOR_STORE_TABLE_NAME`.
