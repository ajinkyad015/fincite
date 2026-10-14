# Fincite · Frontend

> **The research terminal.** An editorial, keyboard-friendly React interface for interrogating NSE filings — streaming answers, a live research trail, and citations that open the exact passage.

[![React](https://img.shields.io/badge/React-19.2-61DAFB?logo=react&logoColor=black)](package.json)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9%20strict-3178C6?logo=typescript&logoColor=white)](tsconfig.json)
[![Vite](https://img.shields.io/badge/Vite-7.3-646CFF?logo=vite&logoColor=white)](vite.config.ts)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-4.1-06B6D4?logo=tailwindcss&logoColor=white)](src/index.css)
[![Framer Motion](https://img.shields.io/badge/Framer%20Motion-13-0055FF)](src/App.tsx)
[![Status](https://img.shields.io/badge/status-UI%20prototype%20%C2%B7%20mock%20transport-E0490B)](#5-current-status)

The product story is in the [root README](../README.md); the API this UI talks to is documented in the [backend README](../backend/README.md). This document covers the interface itself.

---

## Contents

1. [What the UI does](#1-what-the-ui-does)
2. [Design language](#2-design-language)
3. [Architecture](#3-architecture)
4. [Directory structure](#4-directory-structure)
5. [Current status](#5-current-status)
6. [Connecting to the real backend](#6-connecting-to-the-real-backend)
7. [Getting started](#7-getting-started)
8. [Interaction details](#8-interaction-details)
9. [Roadmap](#9-roadmap)

---

## 1. What the UI does

Fincite is a single-page app with two primary views and three overlays, all living inside one shell.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  TICKER   RELIANCE 2,961 ▲0.42%   TCS 4,120 ▼0.18%   HDFCBANK 1,702 ▲0.07%   …   │
├────────────────┬─────────────────────────────────────────────────────────────────┤
│  SIDEBAR       │  CHAT VIEW                                    [ Scope ▾ all 6 ] │
│                │                                                                 │
│  f  Fincite    │   Interrogate the filings.                                      │
│     Ask the    │   Every claim, pinned to a page.                                │
│     filings    │   6 DOCUMENTS · 4 NSE COMPANIES · 1,842 PAGES IN THE INDEX      │
│                │                                                                 │
│  ▸ Filing      │   ┌ suggestion ─────────┐  ┌ suggestion ─────────┐              │
│    library   6 │   └──────────────────────┘  └──────────────────────┘            │
│  ▸ Research    │                                                                 │
│    chats     3 │   ── inside a thread ────────────────────────────────────────   │
│                │                                                                 │
│  THREADS  + New│                         you ▸ Compare FY25 vs FY24 net profit   │
│  · RELIANCE AR │   f  RESEARCH TRAIL  ▾                        4 steps · 3.9s    │
│  · Capex compa…│      ✓ Query understanding    llm                      590ms    │
│  · ESG risks   │      ✓ Hybrid retrieval       retrieval               1050ms    │
│                │      ✓ Rerank                 rerank                   690ms    │
│                │      ✓ Answer synthesis       llm                               │
│                │   Net profit rose to ₹ 69,621 Crore in FY2025 [1], up from      │
│                │   ₹ 68,000 Crore in FY2024 [2] …                                │
│                │   GROUNDED SOURCES · 2                                          │
│                │   [1] RELIANCE  p.212  “…”  81%    [2] RELIANCE  p.198  “…”  74%│
│                │                                                                 │
│  ● fincite API │   ┌───────────────────────────────────────────────────────┐     │
│           14ms │   │ Ask across every indexed filing…                  [↑] │     │
│                │   │ ↵ send · ⇧+↵ newline · ⌘K focus     scope · 6 filings │     │
│                │   └───────────────────────────────────────────────────────┘     │
└────────────────┴─────────────────────────────────────────────────────────────────┘
```

### Views

| View | Component | What you can do |
|---|---|---|
| **Research chat** | `ChatView` | Start a thread from a suggestion or free text; watch the answer stream with a blinking caret; expand the **research trail** (per-step source, status, duration, detail); click inline `[n]` chips or source cards to open the passage; copy the answer; narrow the thread's **scope** to specific filings. |
| **Filing library** | `LibraryView` | Drag-and-drop PDFs anywhere on the screen or use the upload drawer; filter by company / symbol / type; see per-document status and pipeline stage; open a document's **detail drawer** (metadata sheet + `parsing → chunking → embedding → indexing` progress); start a thread scoped to that one filing; re-upload a revision. |

### Overlays

| Overlay | Component | Purpose |
|---|---|---|
| **Source drawer** | `SourceDrawer` | The citation inspector: company monogram, document type, fiscal year, page number in display type, the quoted chunk, and an animated relevance bar. Deep-links back into the library. |
| **Sidebar / mobile rail** | `Sidebar` | Brand, primary navigation with counts, thread list with inline delete-confirmation, live API health (latency or *unreachable*). Slides in as a drawer below `lg`. |
| **Toasts** | `Toasts` | Success / info / error notifications with optional action button; capped at three, auto-dismiss. |
| **Boot splash** | `App.tsx → Splash` | 1.5 s minimum brand reveal while documents and health load in parallel. |

---

## 2. Design language

The interface is deliberately **not** a generic chat template. It reads like a research desk: paper tones, hairline rules, square corners, tabular numerals, a market ticker, and a touch of film grain.

| Token | Value | Used for |
|---|---|---|
| `--color-bone` / `--color-paper` / `--color-faint` | `#f3efe4` / `#faf7ee` / `#ece7d6` | Page, cards, subtle fills |
| `--color-ink` / `--color-soot` | `#16130b` / `#1e1a0f` | Text, dark rail |
| `--color-moss` | `#736d55` | Secondary text, meta labels |
| `--color-accent` / `--color-accent-deep` | `#e0490b` / `#b2380a` | The Fincite orange: brand mark, active states, streaming caret, relevance bars |
| `--color-pine` / `--color-rust` / `--color-gold` | `#1f7a4d` / `#b3261e` / `#8c6d1f` | Success, error, warning |
| `--font-display` | **Fraunces** (variable, optical sizing) | Headlines, italics, page numbers |
| `--font-sans` | **Space Grotesk** | Body |
| `--font-mono` | **IBM Plex Mono** | Labels, endpoints, numerals, the ticker |

All tokens are declared once in [`src/index.css`](src/index.css) via Tailwind v4's `@theme` block and consumed as utility classes (`bg-bone`, `text-moss`, `font-display`, `animate-marquee`). Motion is restrained and consistent — one easing curve (`[0.32, 0.72, 0, 1]`) for layout transitions, short durations, `AnimatePresence` for view/drawer mount and unmount.

Small details that add up: `.tnum` for tabular numerals everywhere a number can change width, a CSS-only streaming caret, thin scrollbars tuned per surface, custom `::selection`, and `<title>` / `<meta description>` written for the product rather than the framework.

---

## 3. Architecture

### 3.1 Component tree

```
<App>
└── <StoreProvider>                      src/store.tsx — React context, no external state library
    └── <Shell>
        ├── <Ticker/>                    market marquee
        ├── <Sidebar/>                   desktop rail  (and as a motion drawer on mobile)
        ├── <main>
        │   ├── mobile top bar
        │   └── <AnimatePresence mode="wait">
        │       ├── <ChatView/>
        │       │   ├── <ScopePicker/>   per-thread document scope
        │       │   ├── <Hero/>          empty state: stats + suggestions
        │       │   ├── <MessageItem/>*  user bubble | assistant block
        │       │   │   ├── <ResearchTrail/>   sub-process timeline (auto-collapses)
        │       │   │   ├── <CiteMarkdown/>    react-markdown + GFM, [n] → chips
        │       │   │   └── source cards       page, excerpt, score bar
        │       │   └── <Composer/>      auto-grow textarea, send / stop
        │       └── <LibraryView/>
        │           ├── <DocRow/>*       table rows + in-flight upload rows
        │           ├── <UploadDrawer/>  file picker, progress, sample filing
        │           └── <DocDetailDrawer/>
        ├── <SourceDrawer/>              citation inspector
        ├── <Toasts/>
        └── <Splash/>
```

### 3.2 State: `src/store.tsx`

A single provider exposes a typed `Store` through `useStore()`. It owns:

| Slice | Shape | Behaviour |
|---|---|---|
| Navigation | `view`, `mobileNav`, `booted` | `boot()` loads documents + health in parallel; splash waits for both |
| Documents | `documents`, `uploading[]`, `libraryOpenDocId` | `uploadFiles()` tracks per-file progress; `watchDocument()` polls `getDocument` every 900 ms until `ready`/`failed`, then toasts |
| Conversations | `conversations`, `activeId`, `active`, `streaming` | `send()` lazily creates a conversation titled from the first question, then subscribes to the stream; `patchConversation()` keeps the list sorted by `updated_at` |
| Streaming | `cancelStream` ref | `stopStreaming()` cancels the transport subscription and resets state |
| Health | `health { status, latency }` | Probed at boot and every 25 s |
| Citations | `selectedSource` | `openSource()` / `closeSource()` drive the drawer |
| Toasts | `toasts[]` | FIFO, max 3, 4.6 s TTL |

All mutations are immutable updates inside `useCallback`s; message streaming patches only the last assistant message in the active conversation.

### 3.3 Transport: `src/lib/api.ts`

The UI never touches `fetch` directly. It calls a tiny `api` facade whose methods mirror the backend contract one-to-one:

```
api.health()  ·  api.listDocuments()  ·  api.getDocument(id)  ·  api.uploadDocument(file, onProgress)
api.createConversation(body)  ·  api.getConversation(id)  ·  api.deleteConversation(id)
api.streamMessage(conversationId, question, handlers) → cancel()
```

Two implementations sit behind the facade, selected by the `USE_MOCK` constant:

| | `MockTransport` (default) | `RealTransport` |
|---|---|---|
| Documents | Seeded corpus; uploads enter a **simulated indexing pipeline** (`parsing 1.5 s → chunking 1.7 s → embedding 1.6 s → indexing 1.3 s`) that the UI polls | `GET /api/document/`, `GET /api/document/{id}`, `XMLHttpRequest` upload with progress |
| Conversations | In-memory map | `POST` / `GET` / `DELETE /api/conversation` |
| Streaming | Pattern-matched canned answers; emits sub-process steps with realistic durations, then streams tokens in 1–2 word bursts at 12–38 ms | `EventSource` on `/api/conversation/{id}/message` |

The **streaming handler contract** is the seam between transport and store:

```ts
interface StreamHandlers {
  onUserMessage(msg)                       // echo of the user's turn
  onAssistantCreated(msg)                  // placeholder with planned sub_processes
  onSubProcess(stepId, patch)              // status / duration / detail updates
  onToken(token)                           // append to content; status → "streaming"
  onDone({ content, sources })             // finalise; attach citations
  onError(message)                         // mark failed; toast
}
```

Any transport that honours this interface — SSE, WebSocket, or fetch-streaming — plugs in without touching components.

### 3.4 Rendering answers: `CiteMarkdown`

Assistant content is Markdown. `CiteMarkdown` pre-processes `[1]`, `[2]` … into `#cite-n` links, then renders through `react-markdown` + `remark-gfm` with a custom component map: citation links become **clickable chips** wired to `openSource`, external links open in a new tab, tables get horizontal scroll, block-quotes use the display italic. The streaming state renders raw text with the caret and switches to Markdown on completion, so partial syntax never flashes broken.

---

## 4. Directory structure

```
frontend/
├── index.html                  # fonts (Fraunces, Space Grotesk, IBM Plex Mono), SVG favicon, meta
├── vite.config.ts              # @vitejs/plugin-react · @tailwindcss/vite · vite-plugin-singlefile · "@" alias
├── tsconfig.json               # strict, bundler resolution, noUnused*, "@/*" paths
├── package.json
└── src/
    ├── main.tsx                # StrictMode root
    ├── App.tsx                 # Shell + Splash
    ├── store.tsx               # StoreProvider / useStore
    ├── index.css               # Tailwind v4 @theme tokens, grain, caret, scrollbars, md tables
    ├── lib/
    │   ├── api.ts              # facade · MockTransport · RealTransport · StreamHandlers
    │   ├── types.ts            # FinDocument, Conversation, ChatMessage, MessageSubProcess, Source …
    │   ├── format.ts           # DOC_TYPE_LABEL/SHORT, STATUS_LABEL, PIPELINE_STAGES, formatters, uid()
    │   └── mockData.ts         # (see §5) SEED_DOCUMENTS, ANSWER_BANK, FALLBACK_EXCERPT, SUGGESTIONS, COMPANY_HUE, TICKS
    ├── components/
    │   ├── ChatView.tsx        # header + ScopePicker · Hero · message list · composer footer
    │   ├── Composer.tsx        # textarea, shortcuts, send/stop
    │   ├── MessageItem.tsx     # user / assistant rendering, source cards, copy
    │   ├── ResearchTrail.tsx   # sub-process timeline
    │   ├── CiteMarkdown.tsx    # markdown + citation chips
    │   ├── SourceDrawer.tsx    # citation inspector
    │   ├── LibraryView.tsx     # table, drag-drop, UploadDrawer, DocDetailDrawer
    │   ├── Sidebar.tsx         # nav, threads, health
    │   ├── Ticker.tsx          # marquee
    │   ├── Monogram.tsx        # company-coloured initials
    │   └── Toasts.tsx
    └── utils/cn.ts             # clsx + tailwind-merge
```

`vite-plugin-singlefile` inlines JS and CSS into `dist/index.html`, so a production build is a **single static file** that can be dropped on any host or served by the backend.

---

## 5. Current status

| Capability | State |
|---|---|
| Information architecture, visual design, motion, responsive layout (mobile rail, drawers) | ✅ complete |
| Chat flow: threads, streaming render, research trail, citation chips, source drawer, copy, stop | ✅ complete against the mock transport |
| Library flow: drag-drop upload, progress, pipeline stages, filter, detail drawer, scoped threads | ✅ complete against the mock transport |
| Health probe + latency indicator | ✅ |
| `RealTransport` for the FastAPI backend | 🟡 scaffolded — endpoint paths are right, but the SSE event handling, upload body and a few payload shapes need to be aligned with the backend (checklist in §6) |
| Type-check / build on a fresh clone | ⚠️ two blockers, both trivial — see below |

### Known issues on a fresh clone

1. **`src/lib/mockData.ts` is not committed.** Four modules import it (`api.ts`, `ChatView.tsx`, `Monogram.tsx`, `Ticker.tsx`). It must export:
   `SEED_DOCUMENTS: FinDocument[]`, `ANSWER_BANK: CannedAnswer[]`, `FALLBACK_EXCERPT: Record<docId, { page, excerpt }>`, `SUGGESTIONS: { question, tags[] }[]`, `COMPANY_HUE: Record<symbol, cssColor> & { DEFAULT }`, `TICKS: { symbol, price, change }[]`, and the `CannedAnswer` type `{ id, patterns: RegExp[], plan: { name, source, duration_ms, detail }[], answer, sources: { doc_id, page, excerpt, score }[] }`.
2. **`src/lib/types.ts` has an unterminated doc-comment** on line 1 (`/**` with no closing `*/`), which comments out `NSEDocumentType` and `DocumentStatus`. Closing the comment restores both exports.

Until both are fixed, `npm run build` / `tsc --noEmit` fail; nothing else is required to run the mock experience.

---

## 6. Connecting to the real backend

Flip `USE_MOCK = false` in [`src/lib/api.ts`](src/lib/api.ts), set `VITE_API_URL`, and add the Vite origin (`http://localhost:5173`) to the backend's `BACKEND_CORS_ORIGINS`. Then reconcile these contract differences — all of them belong in `RealTransport` / a thin adapter layer, none in components:

| Concern | UI expects (`types.ts`) | Backend provides ([schema.py](../backend/app/schema.py)) | Adapter work |
|---|---|---|---|
| **Create conversation** | `{ title, document_scope?: string[] }` | `{ document_ids: UUID[] }` → `Conversation { id, messages, documents }` | Send `document_ids`; keep `title` client-side (derive from first question) |
| **Message stream** | Named SSE events `sub_process` / `delta` / `done`; query param `q` | Unnamed `message` events, each a **full `Message` snapshot**; query param `user_message`; terminal event has `status ∈ {SUCCESS, ERROR}` | Use `es.onmessage`; diff `content` against the previous snapshot to produce `onToken`; map `sub_processes` by index/`event` to `onSubProcess`; call `onDone` when `status !== "PENDING"` |
| **Sub-process shape** | `{ id, name, source: llm\|retrieval\|rerank\|parser, status: pending\|running\|completed\|failed, duration_ms?, detail? }` | `{ source: <CBEventType name>, status: PENDING\|FINISHED, metadata_map? }` | Map `source` (`retrieve`→`retrieval`, `llm`/`agent_step`/`synthesize`→`llm`, `reranking`→`rerank`), derive `name`/`detail` (e.g. the sub-question text), compute `duration_ms` from timestamps |
| **Citations** | `message.sources: Source[] { index, document_id, page, excerpt, score }` | `sub_processes[].metadata_map.sub_question.citations[] { document_id, page_number, text, score }` | Flatten and number citations; the answer text may not contain `[n]` markers — render source cards regardless |
| **Document shape** | `{ filename, status, progress, uploaded_at, metadata: { company_name, nse_symbol, document_type, fiscal_year, period, pages, file_size, language } }` | `{ url, metadata_map: { nse_document: { company_name, company_symbol, document_type, financial_year, exchange, original_filename }, content_hash, original_filename }, created_at }`; upload is **synchronous** and returns `status: "indexed"` | Map fields; treat every listed document as `ready`; pipeline polling becomes a no-op (or optimistic) until background indexing exists |
| **Document types** | `annual_report · quarterly_results · concall_transcript · investor_presentation · shareholding_pattern · corporate_announcement` | `annual_report · financial_results · corporate_filing · investor_presentation · other` | Map or extend the backend enum |
| **Upload body** | — | multipart `file` + optional `company_name`, `company_symbol`, `financial_year`, `document_type`, `exchange` | Use `formData.append("file", file)` (the current `Object.assign(new FormData(), { file })` does not add a form field) and forward metadata from the upload drawer |
| **Health** | `status: healthy \| degraded \| down` | `{ status: "alive" }` | Map `alive → healthy`; network failure → `down` |
| **Delete document** | not in UI | not in API | — |

The backend's SSE protocol is specified in detail in [backend/README.md § 5](../backend/README.md#5-streaming-protocol-sse).

---

## 7. Getting started

```bash
cd frontend
npm install            # or: npm ci
npm run dev            # http://localhost:5173  (mock transport)
npm run build          # single-file bundle → dist/index.html
npm run preview        # serve the production build locally
npx tsc --noEmit       # type-check
```

| Env var | Default | Purpose |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend origin used by `RealTransport` |

Node 20+ is recommended (Vite 7).

---

## 8. Interaction details

| Interaction | Behaviour |
|---|---|
| `Enter` / `Shift+Enter` | Send / newline in the composer; the textarea auto-grows to 168 px |
| `⌘K` / `Ctrl+K` | Focus the composer from anywhere |
| Stop button | Appears while streaming; cancels the subscription and leaves partial content in place |
| Auto-scroll | Sticks to the bottom while streaming unless you have scrolled more than 260 px up |
| Research trail | Expanded while working; auto-collapses 1.4 s after the last step completes; click to toggle |
| Citation chip `[n]` / source card | Opens the source drawer; "Open filing in library" jumps to that document's detail drawer |
| Scope picker | Empty selection = whole corpus; selecting filings narrows retrieval for *this thread only*; disabled while streaming |
| Drag-and-drop | Anywhere on the library view; depth-counted so nested elements don't flicker the overlay |
| Delete thread | Two-step inline confirmation in the sidebar |
| Health dot | Green pulsing = healthy, amber = degraded, red = unreachable; latency shown in ms |
| Mobile | Sidebar becomes a slide-in rail; table columns collapse below `lg`; drawers go full-width |

---

## 9. Roadmap

- [ ] Commit `mockData.ts` and close the comment in `types.ts` so a fresh clone builds.
- [ ] Implement the `RealTransport` adapter per §6 and switch `USE_MOCK` by environment (`import.meta.env.VITE_USE_MOCK`).
- [ ] Persist thread list across reloads (hydrate from `GET /api/conversation/{id}` for known ids, or add a list endpoint).
- [ ] Upload drawer fields for NSE metadata (company, symbol, FY, type) mapped to the backend form.
- [ ] In-app PDF viewer in the source drawer, scrolled to the cited page.
- [ ] Virtualised message list and library table for large corpora.
- [ ] Component tests (Vitest + Testing Library) for `CiteMarkdown`, `ResearchTrail`, the store's streaming reducer.
- [ ] Accessibility pass: focus trapping in drawers, `aria-live` for streaming, reduced-motion variants.
