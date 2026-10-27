# WORKFLOWS — fincitee

End-to-end traces for the five flows that matter. Line references are to the current tree; read
`../ARCHITECTURE.md` first if you need the layering context.

| # | Flow | Entry point | Exit |
|---|---|---|---|
| W1 | Upload & index a filing | `POST /api/document/upload` | 201 `DocumentUploadResponse` |
| W2 | Create a scoped conversation | `POST /api/conversation/` | `Conversation` with linked documents |
| W3 | Ask a question (streamed RAG) | `GET /api/conversation/{id}/message` | SSE frames → persisted messages |
| W4 | Frontend question (mock transport) | `Composer.submit` | rendered answer + research trail + sources |
| W5 | Deploy bootstrap | `uv run start` | uvicorn serving N workers |

---

## W1 — Upload & index a filing

**Call path:** `api/endpoints/documents.py:50 upload_document_endpoint`
→ `crud` / `storage.supabase` / `ingestion.pdf` → `pgvector`

```
1  client            multipart POST /api/document/upload
2  handler           read file → `content = await file.read()`                documents.py:81
3  handler           empty? → 400                                              :82
4  handler           _validate_pdf(file, content)                              :86 → :32
                       content_type.split(";")[0] in {"application/pdf"} (or "")
                       content.startswith(b"%PDF")
5  handler           content_hash = sha256(content).hexdigest()                :89
6  crud              fetch_document_by_content_hash(db, hash)                  :90
                       → SELECT … WHERE metadata_map->>'content_hash' = hash
                       HIT ⇒ return existing doc, status "indexed", 201        :97-104
7  handler           resolved_company_name = company_name or title(filename)   :108
8  handler           NSEDocumentMetadata(...)                                  :115
9  handler           document_id = uuid4()                                     :124
10 storage           upload_document(content, document_id)                     :129
                       → storage.from_(bucket).upload("documents/{id}/original.pdf",
                            file_options={"content-type":"application/pdf","upsert":"false"})
                       raises RuntimeError ⇒ 500                               :130-134
11 storage           get_document_url(document_id) → public URL                :137
12 handler           schema.Document(id, url, metadata_map={nse_document,      :140-148
                       content_hash, original_filename})
13 crud              create_document(db, doc_schema) → INSERT + commit         :150
                       exception ⇒ delete_document(id) → 500                   :152-159
14 handler           vector_store = await get_vector_store_singleton()         :163
15 ingestion         ingest_document(db_doc, vector_store)                     :164 → pdf.py:70
       15a           download_document(document_id) → bytes                   pdf.py:89
       15b           load_pdf_from_bytes(bytes, id)                           pdf.py:37
                       TemporaryDirectory → write {id}.pdf
                       PDFReader().load_data(path, extra_info={db_document_id: id})
                       → one LlamaIndex Document per page, metadata.page_label
                       empty result ⇒ ValueError "PDFReader produced no documents"
       15c           StorageContext.from_defaults(vector_store=…)             pdf.py:102
       15d           VectorStoreIndex.from_documents(llama_docs, show_progress=True)
                       SentenceSplitter(512/10) → NVIDIAEmbedding(2048) → INSERT
       15e           index.set_index_id(document_id)                          pdf.py:113
16 handler           failure ⇒ crud.delete_document_by_id + delete_document    :166-174
                       → 422 "PDF indexing failed…"
17 handler           return DocumentUploadResponse(status="indexed")           :176
```

**Why the order matters.** Storage first, then DB, then vectors: each later step can be undone
using the earlier artifacts (the rollback needs `document_id` to locate the object). The reverse
order would leave orphan vectors with no `Document` row to filter against.

**Observability.** `logger.info` at upload start, DB record created, indexing start/complete;
`logger.error(..., exc_info=True)` before every 5xx.

**Failure matrix**

| Stage | Side effects | Recovery |
|---|---|---|
| validation | none | client error 400 |
| dedupe hit | none | returns existing doc (no re-index!) |
| storage upload | none (Supabase rejects) | 500 |
| DB insert | storage object | object deleted, 500 |
| PDF parse | storage + DB row | both deleted, 422 |
| embeddings (mid-batch) | storage + DB row + **partial vectors** | row + object deleted; partial vectors are orphaned (harmless, never queried) |

**Debugging**

```sql
SELECT id, metadata_map->>'content_hash' FROM document ORDER BY created_at DESC LIMIT 5;
SELECT count(*) FROM data_pg_vector_store
 WHERE metadata_->>'db_document_id' = '<document_id>';
```

If vectors exist but queries return nothing, check that `db_document_id` is present (it is a
string, not a number) and that the dimension matches `VECTOR_STORE_EMBED_DIM`.

---

## W2 — Create a conversation

```
1  handler     ConversationCreate{document_ids}                          conversation.py:31
2  handler     if payload.document_ids:
                 found = crud.fetch_documents(db, ids=[str(x) …])      :41
                 missing = supplied - found ⇒ 404 "Documents not found: …"   :44-48
3  crud        conversation = Conversation()                            crud.py:45
               ConversationDocument(document_id=…, conversation=…)     per id
               db.add / add_all → commit → refresh                     :50-53
4  crud        fetch_conversation_with_messages(db, conversation.id)    :54 → :11
                 select(Conversation)
                   .options(joinedload(messages).subqueryload(sub_processes))
                   .options(joinedload(conversation_documents)
                            .subqueryload(document))
               → builds {"documents": [cd.document …]} then
                 schema.Conversation(**convo_dict)
5  returns     Conversation{messages: [], documents: [...]}
```

**Notes**

- Document order is DB order, not request order.
- Duplicate ids create duplicate join rows (no unique constraint).
- The conversation "title" the UI shows is **client-side only** — no `title` column exists.
- `schema.Conversation(**convo_dict)` relies on `conversation.__dict__` plus the synthesized
  `documents` key; adding a field to the Pydantic model that is not an ORM attribute requires
  updating this function.

---

## W3 — Ask a question (streamed RAG)

This is the core flow. Two coroutines share one `anyio` channel.

```
client ──GET /message?user_message=…──►  message_conversation
                                             │
                              conversation = crud.fetch_conversation_with_messages   (:97)
                              (loaded BEFORE the new user message is persisted)
                              user_msg_obj = Message(role=user, status=SUCCESS)       (:101)
                              send_chan, recv_chan = anyio.create_memory_object_stream(100)  (:110)
                                             │
                              return EventSourceResponse(event_publisher())           (:178)

event_publisher (consumer)                                    handle_chat_message (producer)
──────────────────────────                                    ────────────────────────────
task = create_task(handle_chat_message(convo, user_msg, send_chan))
message = Message(id=uuid4(), role=assistant, status=PENDING, sub_processes=[])
event_id_to_sub_process = OrderedDict()
async for msg in recv_chan:
  StreamedMessage           → message.content = msg.content
  StreamedMessageSubProcess → upsert row keyed by event_id
                               (PENDING / FINISHED, keep original created_at)
  yield schema.Message.model_validate(message).model_dump_json()
|
await task; if task.exception(): raise
final_status = SUCCESS
|
db.add(user_msg_obj); db.add(message); await db.commit()
final = crud.fetch_message_with_sub_processes(db, message_id)
yield final.model_dump_json()

                                                             async with send_chan:
                                                               engine = await get_chat_engine(
                                                                   ChatCallbackHandler(send_chan), convo)
                                                               send CONSTRUCTED_QUERY_ENGINE (has_ended=True)
                                                               resp = await engine.astream_chat(
                                                                   "Remember - if I have asked a relevant
                                                                    financial question, use your tools.\n\n" + q)
                                                               async for text in resp.async_response_gen():
                                                                   response_str += text
                                                                   send StreamedMessage(content=response_str)
                                                               if empty: send apology
```

### `get_chat_engine` internals (`chat/engine.py:181`)

```
callback_manager = CallbackManager([handler])
doc_id_to_index = build_doc_id_to_index_map(callback_manager, conversation.documents)
    per doc: VectorStoreIndex.from_vector_store(vector_store, callback_manager)
             (fallback on exception: fetch_and_read_document → from_documents → set_index_id)
id_to_doc = {str(doc.id): doc}
tools = [QueryEngineTool(index_to_query_engine(doc_id, index),
                         ToolMetadata(name=doc_id,
                                      description=build_description_for_document(doc)))
         for doc_id, index in doc_id_to_index.items()]
response_synth = get_custom_response_synth(callback_manager, conversation.documents)
chat_llm = get_chat_llm()  # NVIDIA NIM, via llama_index_settings
question_gen = LLMQuestionGenerator.from_defaults(llm=chat_llm)
sub_q_engine = SubQuestionQueryEngine.from_defaults(tools, question_gen, response_synth,
                                                    use_async=True, verbose=DEBUG)
chat_history = get_chat_history(conversation.messages)
context = SYSTEM_MESSAGE.format(doc_titles=…, curr_date=utcnow %Y-%m-%d)
return ReActAgent.from_tools([document_question_engine], llm=chat_llm,
                             chat_history=…, context=…, max_iterations=6)
```

### What the user sees per phase

| Phase | SSE evidence | UI |
|---|---|---|
| engine built | `CONSTRUCTED_QUERY_ENGINE` (synthetic) | trail appears |
| agent thinking | `LLM` / `AGENT_STEP` events | trail rows appear/complete |
| sub-questions | one `SUB_QUESTION` per doc with Q/A/citations | trail shows questions, citations captured |
| retrieval | `RETRIEVE` (top-3 per doc) | trail |
| synthesis | `SYNTHESIZE` | trail |
| tokens | `content` grows in each snapshot | streaming text with caret |
| done | final frame `status: SUCCESS` + `sub_processes[].metadata_map` | citations grid, copy button |

### Concurrency hazards (present today)

1. `handle_chat_message` and `event_publisher` both enter `async with send_chan` — the stream is
   closed twice.
2. `on_event_start/end` schedule `asyncio.create_task(...)` and return immediately, so events may
   be delivered after the producer finished and closed the channel; the handler checks
   `send_chan._closed` then swallows `ClosedResourceError`.
3. If the callback task raises (e.g. `KeyError` on an enum value not in
   `MessageSubProcessSourceEnum`), nothing surfaces it: `event_publisher` just waits for the
   channel to close. The request appears to hang.
4. Client disconnect sets `_closed`; the producer stops sending tokens and returns without
   persisting anything (`response_str` partial → messages are still committed by the consumer if
   it is still running, but its `await task` may be cancelled).

**Debugging a stuck stream**

```bash
# watch raw frames
curl -N "localhost:8000/api/conversation/<ID>/message?user_message=hello"
# then inspect persisted state
curl localhost:8000/api/conversation/<ID> | jq '.messages[] | {role,status,sub:(.sub_processes|length)}'
```

Set `LOG_LEVEL=DEBUG` to get `verbose=True` on the agent/sub-question engine (very chatty) and
uvicorn reload.

---

## W4 — Frontend question flow (mock transport)

```
Composer.submit                                              Composer.tsx:36
  └─ store.send(q)                                           store.tsx:175
       ├─ guard: q non-empty && !streaming
       ├─ setStreaming(true); setView("chat"); setSelectedSource(null)
       ├─ if no activeId: api.createConversation({title: first 46 chars})
       │     → prepend to conversations, setActiveId
       └─ api.streamMessage(cid, q, handlers)                lib/api.ts:195
            MockTransport.streamMessage:
              pickAnswer(q, scopedDocs)   ← ANSWER_BANK regex match or generic fallback
              after(0)    onUserMessage
              after(240)  onAssistantCreated (4-step plan, all "pending")
              per step:   onSubProcess running → onSubProcess completed(+detail,duration)
              then tokens (~12-26 ms, 1-2 chars each) → onToken
              final:      onSubProcess last step completed → onDone({content, sources})
```

Store reactions:

| Handler | Effect |
|---|---|
| `onUserMessage` | append user message, bump `updated_at` |
| `onAssistantCreated` | append assistant placeholder (`status: processing`) |
| `onSubProcess` | find the message owning `stepId`, merge patch into that step |
| `onToken` | patch the **last** assistant message: `status: "streaming"`, `content += token` |
| `onDone` | set `status: "completed"`, replace content, attach `sources`, `setStreaming(false)` |
| `onError` | `status: "failed"`, toast "Answer interrupted" |

Rendering:

1. `MessageItem` (`components/MessageItem.tsx:11`) — user bubble right-aligned; assistant block
   with brand row, `ResearchTrail` (while steps exist), streaming text (`.stream-caret`) or
   `CiteMarkdown`, then the "Grounded sources" grid, then copy-answer.
2. `CiteMarkdown` rewrites `[1]` → `[1](#cite-1)` and renders `#cite-*` links as buttons calling
   `openSource`.
3. `SourceDrawer` shows the cited passage, document monogram, page and score; "open in library"
   sets `libraryOpenDocId` and switches view, where `DocDetailDrawer` opens automatically.
4. `ResearchTrail` auto-collapses 1.4 s after the last step completes (`ResearchTrail.tsx:43`).

**Stop button:** `store.stopStreaming()` calls the cancel closure returned by
`api.streamMessage`, clears `streaming`, leaves the partial message in place.

---

## W5 — Deploy bootstrap

```
uv run start  (console script `start = "app.main:start"`)
 └─ start()                                                      main.py:165
     ├─ _setup_logging(LOG_LEVEL)                                :167 → :57
     ├─ _setup_sentry()                                          :168 → :70
     ├─ asyncio.run(_bootstrap(release_connections=True))        :174 → :81
     │    ├─ check_database_connection()  30 × 1 s               wait_for_db.py:6
     │    ├─ Alembic head check                                   main.py:88-100
     │    │    Config("alembic.ini")  ← CWD-relative!
     │    │    url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
     │    │    create_engine(url); MigrationContext.get_current_heads() vs ScriptDirectory.get_heads()
     │    │    mismatch ⇒ Exception("Database is not up to date…")
     │    ├─ (await get_vector_store_singleton()).run_setup()     pg_vector.py:39
     │    │    CREATE EXTENSION IF NOT EXISTS vector
     │    │    base.metadata.create_all  (data_pg_vector_store*)
     │    │    guarded by module global did_run_setup
     │    ├─ split_by_sentence_tokenizer()   (NLTK punkt download)
     │    └─ vector_store.close()            (parent releases pools)
     ├─ os.environ["FINCITE_BOOTSTRAP_DONE"] = "1"                :175
     └─ uvicorn.run("app.main:app", 0.0.0.0:8000,
                    reload=(LOG_LEVEL=="DEBUG"), workers=BACKEND_WORKERS)   :177
          └─ per worker: lifespan()                              :119
               ├─ _bootstrap() only if flag != "1"
               ├─ await asyncio.to_thread(_setup_llama_index_settings)
               ├─ (await get_vector_store_singleton()).ensure_initialized()
               ├─ serve …
               └─ vector_store.close()
```

**Checklist when the app won't start**

| Message / symptom | Cause |
|---|---|
| `Couldn't connect to database after 30 attempts` | `DATABASE_URL` wrong / DB asleep (Supabase free tier pauses) |
| `Database is not up to date. Please run uv run alembic upgrade head` | migrations behind head |
| `FileNotFoundError: alembic.ini` | started outside `backend/` |
| `RuntimeError: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set` | only raised on first storage call, not at boot |
| Container up but 502 | workers still importing heavy libs (llama-index) — allow ~10-20 s |
