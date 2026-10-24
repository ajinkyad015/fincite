# MODULE — frontend (`frontend/src/**`)

React 19 + TypeScript 5.9 (strict) + Vite 7 + Tailwind 4 + framer-motion. No router, no state
library, no test runner. Builds to a single inlined `dist/index.html` via `vite-plugin-singlefile`.

---

## 1. File map

| File | Lines | Role |
|---|---|---|
| `main.tsx` | 10 | `createRoot` + `StrictMode` |
| `App.tsx` | 180 | `Shell` (layout, boot splash, health polling, mobile nav), `Splash`, `App` (providers) |
| `store.tsx` | 392 | the entire app state + `useStore()` |
| `lib/api.ts` | 460 | `USE_MOCK`, `BASE_URL`, `StreamHandlers`, `MockTransport`, `RealTransport`, `api` facade |
| `lib/mockData.ts` | 395 | `COMPANY_HUE`, `SEED_DOCUMENTS` (5), `FALLBACK_EXCERPT`, `ANSWER_BANK` (4), `TICKS`, `SUGGESTIONS` |
| `lib/types.ts` | 114 | domain types (⚠ broken leading comment) |
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
  documents; refreshDocuments; uploadFiles; uploading; libraryOpenDocId; setLibraryOpenDocId;
  conversations; activeId; active; selectConversation; newChat; deleteConversation;
  setScope; startScopedChat; send; streaming; stopStreaming;
  health; checkHealth;
  selectedSource; openSource; closeSource;
  mobileNav; setMobileNav;
  toasts; pushToast; dismissToast;
}
```

Behaviours worth knowing:

| Function | Detail |
|---|---|
| `boot()` | `Promise.all([refreshDocuments(), checkHealth()])`, then `booted = true`; `App` also awaits a 1.5 s minimum splash |
| `refreshDocuments()` | swallows errors and keeps stale state |
| `watchDocument(id)` | 900 ms `getDocument` poll until `ready`/`failed`; toast on success; map `pollers` prevents duplicates |
| `uploadFiles(files)` | sequential per file; optimistic `uploading` entry with progress; on success prepend document + start poller; on error keep the row for 3.2 s with the message |
| `send(q)` | guards `streaming`; creates a conversation when `activeId` is null (title = first 46 chars + `…`); wires the six stream handlers; stores the cancel closure in a ref |
| `stopStreaming()` | cancels the transport, clears `streaming` |
| `deleteConversation(id)` | calls the API, ignores failures ("local delete anyway"), always removes locally |
| `setScope(id, docIds)` | patches `document_scope` (client-side only; the backend has no scope update endpoint) |
| `startScopedChat(doc)` | creates a thread titled `SYMBOL · doc type` with `document_scope: [doc.id]`, switches to chat |
| `checkHealth()` | `api.health()` → `{status, latency}`; catch → `"down"` |

`active` is derived with `useMemo`. Conversations are **not** rehydrated from `GET
/api/conversation/{id}` anywhere — `api.getConversation` is exported but unused.

---

## 3. Transport (`lib/api.ts`)

```ts
export const USE_MOCK = true;                                   // hardcoded
export const BASE_URL = (import.meta as any).env?.VITE_API_URL ?? "http://localhost:8000";
export const api = { health, listDocuments, getDocument, uploadDocument,
                     createConversation, getConversation, deleteConversation, streamMessage };
```

`MockTransport`: `SEED_DOCUMENTS` clone; `STAGE_MS = {parsing:1500, chunking:1700,
embedding:1600, indexing:1300}`; `refresh()` advances a document based on elapsed wall time;
`uploadDocument` ticks progress with `setTimeout`; `pickAnswer` regex-matches `ANSWER_BANK`
(`reliance_revenue`, `it_margins`, `hdfc_asset_quality`, `itc_fmcg`) or builds a grounded-sounding
fallback from `FALLBACK_EXCERPT`; `streamMessage` emits a 4-step plan then tokens.

`RealTransport`: see `../API_REFERENCE.md §6` — incomplete/mismatched.

**To add a real mode**, prefer a new `lib/wire.ts` mapper module + a rewritten `RealTransport`,
keeping the `StreamHandlers` interface so `store.tsx` does not change. Do not silently flip
`USE_MOCK`.

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
| `SourceDrawer` | — | `selectedSource, documents, closeSource, setView, setLibraryOpenDocId` | view switch |
| `LibraryView` | — | `documents, uploadFiles, uploading, setLibraryOpenDocId, refreshDocuments` | uploads |
| `DocRow` / `StatusPill` | `doc` (+`processing`) | — | `onOpen` |
| `UploadDrawer` | `open, onClose` | `uploadFiles, uploading` | uploads |
| `DocDetailDrawer` | — | `libraryOpenDocId, documents, startScopedChat, uploadFiles` | scoped chat |
| `Composer` | `centered?` | `send, streaming, stopStreaming, active, documents` | `send` |
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

1. `lib/types.ts:1-4` — unterminated `/**` swallows four type exports; `tsc` cannot resolve
   `DocumentStatus`/`NSEDocumentType`/`FinDocument`. Fix before any type-sensitive work.
2. `vite build` still succeeds (esbuild strips types without checking) — never use it as your only
   gate.
3. `Sidebar.tsx:3` imports `Activity` but never uses it (`noUnusedLocals` error).
4. `active.document_scope` is client-only; the backend never learns about scope changes, so a real
   transport must create a new conversation when the scope changes.
5. `UploadDrawer` sends only `{name, size, type}` to `uploadFiles` — even in real mode, no NSE
   metadata is collected (the README claims a metadata form exists).
6. `DocDetailDrawer`'s "Re-upload a revision" fabricates a fake file object (`reindexed-…`) rather
   than reading bytes; harmless only because the mock ignores content.
7. `SourceDrawer`'s "open in library" assumes the source's `document_id` exists in `documents`.
8. `Analytics` is mounted unconditionally; it is a no-op outside Vercel.
9. Fonts load from Google Fonts; the app degrades to Georgia/system serif offline.
10. No persistence: a refresh loses all threads (mock); the planned real mode must hydrate from
    `GET /api/conversation/{id}` per thread.
