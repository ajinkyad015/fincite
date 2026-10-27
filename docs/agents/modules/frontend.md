# MODULE — frontend (`frontend/src/**`)

React 19 + TypeScript 5.9 (strict) + Vite 7 + Tailwind 4 + framer-motion. No router, no state
library, no test runner. Builds to a single inlined `dist/index.html` via `vite-plugin-singlefile`.

> **M2 status:** real API mode is the default. `wire.ts` maps M1 DTOs, `transport.ts` handles fetch/SSE,
> and `store.tsx` is server-backed. The in-memory transport survives only behind `VITE_USE_MOCK=1`.

---

## 1. File map

| File | Lines | Role |
|---|---|---|
| `main.tsx` | 10 | `createRoot` + `StrictMode` |
| `App.tsx` | 180 | `Shell` (layout, boot splash, health polling, mobile nav), `Splash`, `App` (providers) |
| `store.tsx` | ~600 | server-backed app state, rAF snapshot batching, polling + `useStore()` |
| `lib/api.ts` | ~480 | `USE_MOCK`, facade, explicit `MockTransport` |
| `lib/transport.ts` | ~470 | `BASE_URL`, `StreamHandlers`, real fetch/SSE `RealTransport`, snapshot adapter |
| `lib/wire.ts` | ~500 | backend DTO types, mappers, `ApiError`, source/trail derivation |
| `lib/mockData.ts` | 395 | `COMPANY_HUE`, `SEED_DOCUMENTS` (5), `FALLBACK_EXCERPT`, `ANSWER_BANK` (4), `TICKS`, `SUGGESTIONS` |
| `lib/types.ts` | ~130 | UI domain types |
| `lib/format.ts` | 85 | `initials`, `timeHM`, `shortDate`, `formatFileSize`, label maps, `uid`, `nowIso` |
| `utils/cn.ts` | 6 | `clsx` + `tailwind-merge` — **unused** |
| `index.css` | 121 | `@theme` tokens, grain overlay, scrollbars, `.stream-caret`, markdown rules |

Components: `ChatView` (306) with `Hero` (103) and `ScopePicker` (198); `LibraryView` (639) with
`DocRow` (237), `StatusPill` (289), `UploadDrawer` (317), `DocDetailDrawer` (464); `MessageItem`
(190, memoized); `ResearchTrail` (147); `CiteMarkdown` (100, memoized); `SourceDrawer` (160);
`Composer` (111); `Sidebar` (237); `Toasts` (60); `Ticker` (34); `Monogram` (27).

---

## 2. State model (`store.tsx`)

```ts
interface Store {
  view; setView; booted; boot;
  documents; refreshDocuments; uploadFiles; retryDocument; uploading; libraryOpenDocId;
  conversations; refreshConversations; activeId; active; selectConversation; newChat;
  deleteConversation; renameConversation; setScope; startScopedChat; send; streaming; stopStreaming;
  health; checkHealth;
  selectedSource; openSource; closeSource;
  mobileNav; setMobileNav;
  toasts; pushToast; dismissToast;
}
```

| Function | Detail |
|---|---|
| `boot()` | health + documents + `GET /api/conversation/` in parallel; restores `lastThreadId` from `localStorage` only if still present, then `GET /api/conversation/{id}` |
| `refreshConversations()` | maps thread summaries to domain `Conversation`s and preserves already-hydrated messages |
| `loadConversation(id)` | fetches a full thread; a 15 s cache avoids refetch storms |
| `watchDocument(id)` | `getDocument` polling with 500 ms → 5 s backoff until `ready`/`failed`; real `error` is toasted |
| `uploadFiles(files, metadata?)` | requires real `File` bytes in live mode, sends optional multipart metadata, prepends the server DTO and starts polling |
| `send(q)` | creates `{title, document_ids}` when needed, then consumes `onSnapshot` via one `requestAnimationFrame` batch per frame; rehydrates canonical messages on done/error |
| `stopStreaming()` | aborts the fetch stream, keeps the partial answer, and reloads the persisted thread |
| `deleteConversation(id)` | awaits DELETE, surfaces failures, and only removes locally on success |
| `setScope(id, docIds)` | optimistic `PATCH {document_ids}` with rollback on failure |
| `checkHealth()` | `api.health()` → `{status, latency}`; catch → `"down"` and an App retry banner |

`active` is derived with `useMemo`. On every terminal stream event the store calls
`GET /api/conversation/{id}`, so React state is a view of the database.

---

## 3. Transport (`lib/api.ts`, `lib/transport.ts`, `lib/wire.ts`)

```ts
export const USE_MOCK = env.VITE_USE_MOCK === "1"; // real API by default
export const BASE_URL = env.VITE_API_URL ?? "";    // same-origin /api
export const api = { health, listDocuments, getDocument, uploadDocument, reindexDocument,
                     deleteDocument, listConversations, createConversation, getConversation,
                     updateConversation, deleteConversation, streamMessage };
```

`RealTransport` uses `fetch` and a `ReadableStream` reader for `POST /message`; `consumeSseFrames()`
handles unnamed frames, CRLF, comments and named frames. `createSnapshotAdapter()` emits both
`onSnapshot` and the legacy token/trail callbacks. A dropped stream performs one `GET` rehydrate with
`Last-Event-ID` rather than a duplicate POST. Uploads use XHR only to retain progress events.

`wire.ts` maps `Document`, `ConversationSummary`, `Conversation`, and `Message` DTOs; derives citations
from old trail metadata when `sources` is absent; normalises fiscal years, statuses, document types and
`CBEventType` names; and centralises friendly FastAPI errors via `ApiError`.

`MockTransport` remains for explicit demo mode and now emits the same full snapshots as the real path.

---

## 4. Component contracts

| Component | Props | Reads from store | Emits |
|---|---|---|---|
| `ChatView` | — | `active, conversations, documents, send, setView` | `send`, `setView("library")` |
| `Hero` | `readyCount, companies, pages, indexing, onAsk, onLibrary` | — | `onAsk(question)` |
| `ScopePicker` | — | `active, documents, setScope, streaming` | `setScope` |
| `MessageItem` | `message, documents` | `openSource` | `openSource` |
| `ResearchTrail` | `steps: MessageSubProcess[]` | — | local `open` state; auto-collapse |
| `CiteMarkdown` | `content, onCite(n)` | — | `onCite` |
| `SourceDrawer` | — | `selectedSource, documents, closeSource, setView, setLibraryOpenDocId` | PDF page link, view switch |
| `LibraryView` | — | `documents, uploadFiles, uploading, setLibraryOpenDocId, refreshDocuments` | uploads |
| `DocRow` / `StatusPill` | `doc` (+`processing`) | — | `onOpen` |
| `UploadDrawer` | `open, onClose` | `uploadFiles, uploading` | uploads |
| `DocDetailDrawer` | — | `libraryOpenDocId, documents, startScopedChat, uploadFiles` | scoped chat |
| `Composer` | `centered?` | `send, streaming, stopStreaming, active, documents` plus a per-thread localStorage draft | `send` |
| `Sidebar` | — | `view, conversations, activeId, documents, health, …` | nav/delete |
| `Toasts` | — | `toasts, dismissToast` | dismiss |
| `Ticker` | — | `TICKS` | marquee |
| `Monogram` | `symbol, size?, className?` | `COMPANY_HUE` | colour tile |

There is no component that receives a `children` render prop; composition is direct.

---

## 5. Design system cheatsheet (`index.css`)

| Token group | Values |
|---|---|
| Surfaces | `bone #f3efe4` (page), `paper #faf7ee` (cards), `faint #ece7d6`, `soot #1e1a0f` (sidebar), `soot-2` |
| Text | `ink #16130b`, `moss #736d55` (secondary) |
| Lines | `line #e0d9c3`, `line-dark #37321f` |
| Accent | `accent #e0490b`, `accent-deep #b2380a`, `accent-soft #f7e2d2` |
| Status | `pine #1f7a4d` / `pine-soft`, `rust #b3261e` / `rust-soft`, `gold` |
| Type | `font-display` Fraunces, `font-sans` Space Grotesk, `font-mono` IBM Plex Mono; numeric cells use `.tnum` |
| Motion | `animate-marquee`, `animate-pulse-dot`; framer easings `[0.22,1,0.36,1]`, `[0.32,0.72,0,1]` |

Conventions: square corners, 1 px hairlines, 9-10 px uppercase mono labels with `tracking-[0.18em]`
or `0.2em`, generous whitespace, one accent colour. Body carries an SVG noise overlay at 0.32
opacity (multiply). `.stream-caret::after` renders the blinking block cursor while streaming.

---

## 6. Frontend gotchas

1. `npm run typecheck` is green, but `vite build` alone does not typecheck — keep both in CI.
2. `wire.ts` is the only place backend field names belong. Components consume `types.ts` domain shapes.
3. `uploadFiles` needs actual `File`/`Blob` bytes in real mode. Demo-only sample/revision shortcuts are
   hidden when `USE_MOCK` is false.
4. Optional upload metadata is accepted by `uploadFiles(files, metadata)`; there is deliberately no M3
   metadata form yet, so the backend infers company/type from the filename.
5. A failed document exposes `error` and offers `POST /reindex`; the fake "Re-upload a revision" action
   is demo-only.
6. `SourceDrawer` opens `/api/document/{id}/file#page=N` directly and assumes `document_id` is in the
   current library for its rich header.
7. `Analytics` is mounted unconditionally; it is a no-op outside Vercel.
8. Fonts load from Google Fonts; the app degrades to Georgia/system serif offline.
9. Real mode persists threads server-side; demo mode is intentionally session-only.
