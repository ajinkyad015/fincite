# MODULE — RAG engine (`backend/app/chat/**`, `llama_index_settings.py`)

Everything that turns a question plus a set of documents into a streamed, cited answer.

---

## 1. Files

| File | Responsibility | Key symbols |
|---|---|---|
| `chat/engine.py` | build the agent | `get_chat_engine`, `build_doc_id_to_index_map`, `index_to_query_engine`, `fetch_and_read_document`, `get_chat_history` |
| `chat/messaging.py` | bridge LlamaIndex callbacks → anyio stream | `ChatCallbackHandler`, `handle_chat_message`, `StreamedMessage`, `StreamedMessageSubProcess` |
| `chat/pg_vector.py` | pool-sharing vector store | `CustomPGVectorStore`, `get_vector_store_singleton` |
| `chat/qa_response_synth.py` | custom QA/Refine prompts | `get_custom_response_synth` |
| `chat/constants.py` | prompt + chunking constants | `DB_DOC_ID_KEY`, `SYSTEM_MESSAGE`, `NODE_PARSER_CHUNK_SIZE=512`, `NODE_PARSER_CHUNK_OVERLAP=10` |
| `chat/utils.py` | human labels for tools/prompts | `build_title_for_document`, `build_description_for_document`, `_fallback_title`, `_fallback_description` |
| `llama_index_settings.py` | NVIDIA client factories + global defaults | `get_chat_llm()` / `get_embed_model()` build the NIM clients; `_setup_llama_index_settings()` registers them as `Settings.llm` / `.embed_model` (+ `.node_parser`) |

Import-time side effects: `chat/engine.py:65` `nest_asyncio.apply()`.

---

## 2. Object graph per conversation

```
ReActAgent(max_iterations=6, context=SYSTEM_MESSAGE, chat_history)
└── QueryEngineTool "document_question_engine"
    └── SubQuestionQueryEngine(use_async=True,
                               question_gen=LLMQuestionGenerator(NVIDIA chat LLM),
                               response_synthesizer=custom QA/Refine)
        ├── QueryEngineTool name=<doc A uuid>  desc="Annual report for …"
        │     └── VectorStoreIndex.as_query_engine(similarity_top_k=3,
        │              filters=MetadataFilters([ExactMatchFilter(db_document_id=uuid)]))
        ├── QueryEngineTool name=<doc B uuid> …
        └── …
```

All tiers use `settings.NVIDIA_CHAT_LLM_NAME`; embeddings are configured globally in
`llama_index_settings.py` and used by `VectorStoreIndex`.

---

## 3. `get_chat_engine(callback_handler, conversation)` step by step

`chat/engine.py:181`

1. `CallbackManager([callback_handler])` — the manager is threaded into every index/engine so all
   events reach the SSE handler.
2. `build_doc_id_to_index_map(...)` (`:112`):
   - `vector_store = await get_vector_store_singleton()`
   - `StorageContext.from_defaults(vector_store=vector_store)`
   - per document: `VectorStoreIndex.from_vector_store(...)`; on exception
     `fetch_and_read_document(doc)` → `from_documents(...)` → `set_index_id(doc_id)`.
   - ⚠ does **not** check that vectors exist for the doc (see `AGENTS.md §14.H`).
3. `id_to_doc = {str(doc.id): doc}`.
4. one `QueryEngineTool` per doc: `name = doc_id` (the LLM selects tools by name **and**
   description), `description = build_description_for_document(doc)`.
5. `response_synth = get_custom_response_synth(callback_manager, conversation.documents)`.
6. `chat_llm = get_chat_llm()` — the `llama_index_settings` factory, shared with `Settings.llm` so agent/question-gen/synthesis cannot drift.
7. `question_gen = LLMQuestionGenerator.from_defaults(llm=chat_llm)`.
8. `SubQuestionQueryEngine.from_defaults(query_engine_tools, question_gen, response_synthesizer,
   verbose=LOG_LEVEL=="DEBUG", use_async=True)`.
9. single top-level tool `document_question_engine` with a deliberately broad description.
10. `chat_history = get_chat_history(conversation.messages)`.
11. `SYSTEM_MESSAGE.format(doc_titles=…, curr_date=utcnow %Y-%m-%d)`.
12. `ReActAgent.from_tools(tools, llm, chat_history, verbose, context, callback_manager,
    max_iterations=6)`.

**Cost per question** (rule of thumb): 1 ReAct planning call + 1 question-generation call + N
sub-answer calls + 1 synthesis (refine may loop) + N×retrieval embedding calls. A 3-document
question is easily 6-8 LLM calls.

---

## 4. Prompts

### `SYSTEM_MESSAGE` (`constants.py:3`)
Indian-financial-research persona; lists the selected document titles; mandates: always use tools,
prefer document evidence, preserve units, disambiguate FY, do not fabricate, cite pages, decline
off-topic questions; injects `{curr_date}`.

### QA + Refine (`qa_response_synth.py:11`)
Both templates restate the selected document list and the unit/FY/no-fabrication rules. Refine
keeps the original answer when new context is useless. `structured_answer_filtering=False`.
If you change chunking or models, re-read these prompts — they are the main defence against
unit conversion drift.

### `chat/messaging.py` nudge
Every user question is prefixed with
`"Remember - if I have asked a relevant financial question, use your tools."` (`messaging.py:145`).
Removing it increases tool-skipping.

---

## 5. Vector store integration (`pg_vector.py`)

```python
class CustomPGVectorStore(PGVectorStore):
    def _connect(self):           # :19
        self._engine = create_engine(self.connection_string)   # sync engine (base-class paths)
        self._session = sessionmaker(self._engine)
        self._async_engine = app_engine                        # SHARED async pool
        self._async_session = AppSessionLocal
    async def close(self):        # :27
        self._session.close_all(); self._engine.dispose(); await self._async_engine.dispose()
    def _create_tables_if_not_exists(self): pass
    def _create_extension(self): pass
    async def run_setup(self):    # :39  CREATE EXTENSION vector + base.metadata.create_all
    async def ensure_initialized(self): self._initialize()     # no DDL
```

`get_vector_store_singleton()` (`:66`) builds it once from `settings.DATABASE_URL` via
`make_url(...)` and `from_params(host, port or 5432, database, user, password, table, embed_dim)`.

Because it is a **module global with no lock**, two concurrent first calls in a worker can create
two instances (last one wins) — harmless but worth knowing if you add async startup work.

---

## 6. Document titles / descriptions (`utils.py`)

`build_title_for_document` → `"Reliance Industries (RELIANCE) Annual Report FY2025"`; falls back to
`"Uploaded Document: <filename>"` or `"Uploaded Document"`.
`build_description_for_document` → `"Annual report for Reliance Industries (RELIANCE), financial
year 2025 (exchange: NSE)."`; falls back to `"Uploaded financial document: <filename>"`.

Both tolerate missing/garbage metadata (`try/except` around `NSEDocumentMetadata.model_validate`).
This text feeds the system prompt **and** the ToolMetadata ← the routing quality of the agent
depends on it.

---

## 7. Callback events → sub-process rows

| LlamaIndex event | Where it comes from | UI effect |
|---|---|---|
| `CONSTRUCTED_QUERY_ENGINE` (synthetic) | `messaging.py:137` | "engine built" step |
| `LLM` | every NVIDIA chat call | thinking / synthesis steps |
| `RETRIEVE` | vector search per doc | retrieval step |
| `SYNTHESIZE` | response synthesizer | synthesis step |
| `SUB_QUESTION` | sub-question engine, payload `EventPayload.SUB_QUESTION` = `SubQuestionAnswerPair` | Q/A + citations per document |
| `AGENT_STEP` | ReAct loop | agent step |
| `CHUNKING`, `NODE_PARSING` | ingestion | deliberately ignored (`messaging.py:39`) |

`get_metadata_from_event` (`messaging.py:71`) only enriches `SUB_QUESTION`:
`{"sub_question": QuestionAnswerPair(question, answer, citations).dict()}`.

Adding a new streamed field: extend `get_metadata_from_event` + `schema.SubProcessMetadataKeysEnum`
+ the frontend's `MessageSubProcess`/`ResearchTrail` rendering.

---

## 8. Changing the model or retrieval

| Change | Files | Caveats |
|---|---|---|
| Different chat model | `.env NVIDIA_CHAT_LLM_NAME` (+ `NVIDIA_CHAT_CONTEXT_WINDOW`/`NVIDIA_CHAT_MAX_TOKENS`) | ids outside the pinned client's known-model table are validated via `GET /v1/models` at construction |
| Different provider | `llama_index_settings.py` factories, `core/config.py`, `pyproject.toml` | single construction site; `NVIDIA_*` env exports in `config.py` must go too |
| Top-k | `index_to_query_engine` (`engine.py:109`, `similarity_top_k=3`) | higher k ⇒ more context tokens, slower |
| Chunk size | `constants.py:25-26` | requires re-index; no migration needed |
| Embedding dimension/model | `.env` + `pg_vector.py` + recreate `data_pg_vector_store` | old rows become unusable |
| New top-level tool | `engine.py:233 top_level_tools` | ReAct will route between tools; give a precise description |
| More agent iterations | `engine.py:267 max_iterations=6` | latency grows |
