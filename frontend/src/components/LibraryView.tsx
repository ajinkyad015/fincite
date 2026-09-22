import { useMemo, useRef, useState, type DragEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Check,
  ChevronRight,
  CircleDashed,
  FileUp,
  FileWarning,
  Files,
  Loader2,
  MessagesSquare,
  Search,
  Upload,
  X,
} from "lucide-react";
import { useStore } from "../store";
import type { FinDocument } from "../lib/types";
import {
  DOC_TYPE_LABEL,
  DOC_TYPE_SHORT,
  PIPELINE_STAGES,
  STATUS_LABEL,
  formatFileSize,
  shortDate,
} from "../lib/format";
import Monogram from "./Monogram";

export default function LibraryView() {
  const { documents, uploadFiles, uploading, setLibraryOpenDocId, refreshDocuments } = useStore();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [query, setQuery] = useState("");
  const dragDepth = useRef(0);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const files = Array.from(e.dataTransfer.files ?? []).map((f) => ({
      name: f.name,
      size: f.size,
      type: f.type,
    }));
    if (files.length) void uploadFiles(files);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return documents;
    return documents.filter(
      (d) =>
        d.metadata.company_name.toLowerCase().includes(q) ||
        d.metadata.nse_symbol.toLowerCase().includes(q) ||
        d.filename.toLowerCase().includes(q) ||
        DOC_TYPE_LABEL[d.metadata.document_type].toLowerCase().includes(q)
    );
  }, [documents, query]);

  const ready = documents.filter((d) => d.status === "ready");
  const pages = ready.reduce((a, d) => a + d.metadata.pages, 0);
  const companies = new Set(ready.map((d) => d.metadata.nse_symbol)).size;

  return (
    <div
      className="relative flex h-full flex-col"
      onDragEnter={(e) => {
        e.preventDefault();
        dragDepth.current++;
        setDragging(true);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={(e) => {
        e.preventDefault();
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragging(false);
      }}
      onDrop={onDrop}
    >
      {/* header */}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-bone/85 px-4 backdrop-blur-sm md:px-6">
        <h1 className="font-display text-[17px] font-semibold text-ink">Filing library</h1>
        <span className="tnum hidden font-mono text-[9.5px] text-moss sm:inline">
          GET /api/document/
        </span>
        <button
          type="button"
          onClick={() => setUploadOpen(true)}
          className="ml-auto flex items-center gap-2 bg-accent px-3.5 py-2 text-[12px] font-medium text-paper transition-colors hover:bg-accent-deep"
        >
          <Upload size={13} strokeWidth={2.4} />
          Upload filing
        </button>
      </header>

      {/* stats + search */}
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-4 py-3 md:px-6">
        <span className="tnum font-mono text-[10px] uppercase tracking-[0.14em] text-moss">
          {documents.length} filings · {companies} companies · {pages.toLocaleString()} pages
          indexed
        </span>
        <button
          type="button"
          onClick={() => void refreshDocuments()}
          className="hidden font-mono text-[10px] text-accent-deep underline decoration-line underline-offset-2 hover:decoration-accent sm:inline"
        >
          resync
        </button>
        <div className="ml-auto flex items-center gap-2 border border-line bg-paper px-3 py-1.5 focus-within:border-ink/40">
          <Search size={12} className="text-moss" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by company, symbol, type…"
            className="w-[180px] bg-transparent text-[12px] text-ink placeholder:text-moss/60 focus:outline-none sm:w-[220px]"
          />
          {query && (
            <button type="button" onClick={() => setQuery("")} aria-label="Clear search">
              <X size={11} className="text-moss hover:text-ink" />
            </button>
          )}
        </div>
      </div>

      {/* table */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="mx-auto max-w-md px-6 py-24 text-center">
            <Files size={22} className="mx-auto text-moss/40" />
            <p className="mt-4 font-display text-[17px] italic text-ink/70">
              {query ? "Nothing matches that filter." : "The library is empty."}
            </p>
            <p className="mt-2 font-mono text-[10px] leading-relaxed text-moss">
              {query ? (
                "Try a different symbol or document type."
              ) : (
                <>Drop PDFs anywhere on this screen — or press “Upload filing”.</>
              )}
            </p>
          </div>
        ) : (
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-bone">
              <tr className="border-b border-ink/80 text-left">
                {["Filing", "Type", "Period", "Pages", "Status", "Uploaded", ""].map((h, i) => (
                  <th
                    key={i}
                    className={`px-4 py-2.5 font-mono text-[9px] font-medium uppercase tracking-[0.14em] text-moss md:px-6 ${
                      i === 3 ? "text-right" : ""
                    } ${i >= 2 && i <= 5 ? "hidden lg:table-cell" : ""}`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((d, i) => (
                <DocRow key={d.id} doc={d} index={i} onOpen={() => setLibraryOpenDocId(d.id)} />
              ))}
              {uploading.map((u) => (
                <tr key={u.name} className="border-b border-line/70 bg-faint/50">
                  <td className="px-4 py-3 md:px-6" colSpan={2}>
                    <div className="flex items-center gap-3">
                      <span className="flex h-[30px] w-[30px] items-center justify-center border border-dashed border-moss/40 text-moss">
                        <FileUp size={13} />
                      </span>
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium text-ink">{u.name}</div>
                        <div className="mt-1 h-1 w-40 bg-line">
                          <div
                            className={`h-full transition-all ${u.error ? "bg-rust" : "bg-accent"}`}
                            style={{ width: `${u.error ? 100 : u.pct}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="hidden px-4 py-3 lg:table-cell" colSpan={3}>
                    <span className="font-mono text-[10px] text-moss">
                      {u.error ? `rejected — ${u.error}` : "POST /api/document/upload"}
                    </span>
                  </td>
                  <td className="px-4 py-3 md:px-6" colSpan={2}>
                    <span
                      className={`flex items-center gap-1.5 font-mono text-[10px] ${
                        u.error ? "text-rust" : "text-accent-deep"
                      }`}
                    >
                      {u.error ? (
                        <FileWarning size={11} />
                      ) : (
                        <Loader2 size={11} className="animate-spin" />
                      )}
                      {u.error ? "Failed" : `${u.pct}%`}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="h-10" />
      </div>

      {/* drag overlay */}
      <AnimatePresence>
        {dragging && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none absolute inset-3 z-30 flex items-center justify-center border-2 border-dashed border-accent bg-bone/85 backdrop-blur-[2px]"
          >
            <div className="text-center">
              <Upload size={26} className="mx-auto text-accent" />
              <p className="mt-3 font-display text-2xl font-medium italic text-ink">
                Drop filings to index
              </p>
              <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.16em] text-moss">
                PDF · parsing → chunking → embedding → indexing
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <UploadDrawer open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <DocDetailDrawer />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Row                                                                */
/* ------------------------------------------------------------------ */

function DocRow({ doc, index, onOpen }: { doc: FinDocument; index: number; onOpen: () => void }) {
  const m = doc.metadata;
  const processing = doc.status !== "ready" && doc.status !== "failed";
  return (
    <motion.tr
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.3), duration: 0.3 }}
      onClick={onOpen}
      className="group cursor-pointer border-b border-line/70 transition-colors hover:bg-faint/70"
    >
      <td className="px-4 py-3.5 md:px-6">
        <div className="flex items-center gap-3">
          <Monogram symbol={m.nse_symbol} size={30} />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate text-[13.5px] font-medium text-ink">{m.company_name}</span>
              <span className="tnum shrink-0 font-mono text-[9px] text-moss">{m.nse_symbol}</span>
            </div>
            <div className="mt-0.5 truncate font-mono text-[9.5px] text-moss/80">{doc.filename}</div>
          </div>
        </div>
      </td>
      <td className="px-4 py-3.5 md:px-6">
        <span className="inline-flex items-center gap-1.5 border border-line bg-paper px-2 py-1 font-mono text-[9px] uppercase tracking-[0.1em] text-moss">
          <span className="h-1 w-1 bg-accent" />
          {DOC_TYPE_SHORT[m.document_type]}
        </span>
      </td>
      <td className="hidden px-4 py-3.5 lg:table-cell">
        <span className="tnum text-[12px] text-ink/80">{m.period}</span>
        <span className="tnum block font-mono text-[9px] text-moss/70">{m.fiscal_year}</span>
      </td>
      <td className="tnum hidden px-4 py-3.5 text-right text-[12.5px] text-ink/80 lg:table-cell">
        {m.pages}
      </td>
      <td className="hidden px-4 py-3.5 lg:table-cell">
        <StatusPill doc={doc} processing={processing} />
      </td>
      <td className="tnum hidden px-4 py-3.5 font-mono text-[10px] text-moss lg:table-cell">
        {shortDate(doc.uploaded_at)}
      </td>
      <td className="w-8 px-2 py-3.5 text-right">
        <ChevronRight
          size={14}
          className="ml-auto text-moss/40 transition-all group-hover:translate-x-0.5 group-hover:text-accent"
        />
      </td>
    </motion.tr>
  );
}

function StatusPill({ doc, processing }: { doc: FinDocument; processing: boolean }) {
  if (doc.status === "ready")
    return (
      <span className="inline-flex items-center gap-1.5 bg-pine-soft px-2 py-1 font-mono text-[9.5px] font-medium text-pine">
        <Check size={10} strokeWidth={3} /> Ready
      </span>
    );
  if (doc.status === "failed")
    return (
      <span className="inline-flex items-center gap-1.5 bg-rust-soft px-2 py-1 font-mono text-[9.5px] font-medium text-rust">
        <FileWarning size={10} /> Failed
      </span>
    );
  if (processing)
    return (
      <span className="inline-flex items-center gap-1.5 bg-accent-soft px-2 py-1 font-mono text-[9.5px] font-medium text-accent-deep">
        <Loader2 size={10} className="animate-spin" />
        {STATUS_LABEL[doc.status]}
        {doc.progress > 0 && <span className="tnum">{doc.progress}%</span>}
      </span>
    );
  return null;
}

/* ------------------------------------------------------------------ */
/*  Upload drawer                                                      */
/* ------------------------------------------------------------------ */

function UploadDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { uploadFiles, uploading } = useStore();
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (files: FileList | null) => {
    if (!files?.length) return;
    void uploadFiles(
      Array.from(files).map((f) => ({ name: f.name, size: f.size, type: f.type }))
    );
  };

  const sample = () =>
    void uploadFiles([
      {
        name: "bajaj-finance-q2-fy25-investor-presentation.pdf",
        size: 4_160_000,
        type: "application/pdf",
      },
    ]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-ink/25 backdrop-blur-[1px]"
            onClick={onClose}
          />
          <motion.aside
            initial={{ x: 60, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 60, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.32, 0.72, 0, 1] }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[420px] flex-col border-l border-line bg-paper"
          >
            <div className="flex h-12 shrink-0 items-center border-b border-line px-4">
              <span className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-moss">
                Upload filing
              </span>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="ml-auto flex h-7 w-7 items-center justify-center text-moss hover:text-ink"
              >
                <X size={14} />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              <input
                ref={inputRef}
                type="file"
                accept="application/pdf,.pdf"
                multiple
                className="hidden"
                onChange={(e) => {
                  pick(e.target.files);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="group flex w-full flex-col items-center justify-center border-2 border-dashed border-line bg-bone px-6 py-12 transition-colors hover:border-accent hover:bg-accent-soft/30"
              >
                <span className="flex h-11 w-11 items-center justify-center bg-ink text-paper transition-colors group-hover:bg-accent">
                  <Upload size={17} />
                </span>
                <span className="mt-4 font-display text-[17px] font-medium text-ink">
                  Choose PDF filings
                </span>
                <span className="mt-1.5 font-mono text-[9.5px] uppercase tracking-[0.14em] text-moss">
                  or drop them anywhere in the library
                </span>
              </button>

              <div className="mt-4 border border-line bg-faint/60 px-3.5 py-3">
                <div className="font-mono text-[9px] uppercase tracking-[0.18em] text-moss">
                  Ingestion pipeline
                </div>
                <ol className="mt-2 space-y-1">
                  {PIPELINE_STAGES.map((s) => (
                    <li key={s} className="flex items-center gap-2 font-mono text-[10px] text-ink/70">
                      <CircleDashed size={9} className="text-moss/60" />
                      {STATUS_LABEL[s].toLowerCase()}
                    </li>
                  ))}
                </ol>
                <p className="mt-3 font-mono text-[9px] leading-relaxed text-moss/80">
                  Documents are queryable as soon as indexing finishes. Symbol, type and fiscal
                  period are inferred from the filing.
                </p>
              </div>

              {uploading.length > 0 && (
                <div className="mt-4 space-y-2">
                  {uploading.map((u) => (
                    <div key={u.name} className="border border-line bg-bone px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <Loader2 size={11} className="animate-spin text-accent" />
                        <span className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-ink">
                          {u.name}
                        </span>
                        <span className="tnum font-mono text-[10px] text-accent-deep">{u.pct}%</span>
                      </div>
                      <div className="mt-2 h-1 w-full bg-line">
                        <div className="h-full bg-accent transition-all" style={{ width: `${u.pct}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-6 border-t border-line pt-4">
                <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-moss">
                  No PDF at hand?
                </p>
                <button
                  type="button"
                  onClick={sample}
                  className="mt-2 flex w-full items-center justify-between border border-ink bg-paper px-3.5 py-3 text-left transition-colors hover:bg-ink hover:text-paper"
                >
                  <span>
                    <span className="block text-[13px] font-medium">Index a sample filing</span>
                    <span className="mt-0.5 block font-mono text-[9px] opacity-60">
                      Bajaj Finance · investor deck · 4.2 MB
                    </span>
                  </span>
                  <FileUp size={15} />
                </button>
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ */
/*  Document detail drawer                                             */
/* ------------------------------------------------------------------ */

function DocDetailDrawer() {
  const { libraryOpenDocId, setLibraryOpenDocId, documents, startScopedChat, uploadFiles } =
    useStore();
  const doc = documents.find((d) => d.id === libraryOpenDocId);

  return (
    <AnimatePresence>
      {doc && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-ink/25 backdrop-blur-[1px]"
            onClick={() => setLibraryOpenDocId(null)}
          />
          <motion.aside
            initial={{ x: 60, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 60, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.32, 0.72, 0, 1] }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col border-l border-line bg-paper"
          >
            <div className="flex h-12 shrink-0 items-center border-b border-line px-4">
              <span className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-moss">
                GET /api/document/{doc.id.slice(-6)}
              </span>
              <button
                type="button"
                onClick={() => setLibraryOpenDocId(null)}
                aria-label="Close"
                className="ml-auto flex h-7 w-7 items-center justify-center text-moss hover:text-ink"
              >
                <X size={14} />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="border-b border-line px-5 py-5">
                <div className="flex items-start gap-3.5">
                  <Monogram symbol={doc.metadata.nse_symbol} size={48} />
                  <div className="min-w-0">
                    <h3 className="font-display text-[22px] font-semibold leading-tight text-ink">
                      {doc.metadata.company_name}
                    </h3>
                    <p className="mt-1 truncate font-mono text-[10px] text-moss">{doc.filename}</p>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  <span className="border border-line bg-faint px-2 py-1 font-mono text-[9px] uppercase tracking-[0.1em] text-ink">
                    {DOC_TYPE_LABEL[doc.metadata.document_type]}
                  </span>
                  <span className="border border-line bg-faint px-2 py-1 font-mono text-[9px] uppercase tracking-[0.1em] text-ink">
                    {doc.metadata.fiscal_year}
                  </span>
                  <span className="tnum border border-line bg-faint px-2 py-1 font-mono text-[9px] uppercase tracking-[0.1em] text-ink">
                    {formatFileSize(doc.metadata.file_size)}
                  </span>
                </div>
              </div>

              {/* metadata sheet */}
              <div className="border-b border-line px-5 py-4">
                <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.2em] text-moss">
                  Metadata keys
                </div>
                <dl>
                  {(
                    [
                      ["company_name", doc.metadata.company_name],
                      ["nse_symbol", doc.metadata.nse_symbol],
                      ["document_type", doc.metadata.document_type],
                      ["fiscal_year", doc.metadata.fiscal_year],
                      ["period", doc.metadata.period],
                      ["pages", String(doc.metadata.pages)],
                      ["file_size", formatFileSize(doc.metadata.file_size)],
                      ["language", doc.metadata.language],
                    ] as [string, string][]
                  ).map(([k, v], i) => (
                    <div
                      key={k}
                      className={`flex items-baseline justify-between gap-4 py-1.5 ${
                        i > 0 ? "border-t border-line/60" : ""
                      }`}
                    >
                      <dt className="font-mono text-[10px] text-moss">{k}</dt>
                      <dd className="tnum truncate text-[12px] font-medium text-ink">{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              {/* pipeline */}
              <div className="px-5 py-4">
                <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.2em] text-moss">
                  Indexing pipeline
                </div>
                <ol>
                  {PIPELINE_STAGES.map((stage) => {
                    const order = ["parsing", "chunking", "embedding", "indexing"];
                    const currentIdx = doc.status === "ready" ? 99 : order.indexOf(doc.status);
                    const stageIdx = order.indexOf(stage);
                    const done = doc.status === "ready" || stageIdx < currentIdx;
                    const activeNow = stageIdx === currentIdx;
                    return (
                      <li
                        key={stage}
                        className="flex items-center gap-2.5 border-b border-line/60 py-2 last:border-0"
                      >
                        <span
                          className={`flex h-[18px] w-[18px] items-center justify-center border ${
                            done
                              ? "border-pine bg-pine text-paper"
                              : activeNow
                                ? "border-accent bg-accent-soft text-accent-deep"
                                : "border-line bg-bone text-moss/50"
                          }`}
                        >
                          {done ? (
                            <Check size={10} strokeWidth={3.2} />
                          ) : activeNow ? (
                            <Loader2 size={10} className="animate-spin" />
                          ) : (
                            <span className="h-1 w-1 bg-current" />
                          )}
                        </span>
                        <span
                          className={`text-[12.5px] ${
                            done || activeNow ? "font-medium text-ink" : "text-moss"
                          }`}
                        >
                          {STATUS_LABEL[stage]}
                        </span>
                        {activeNow && doc.progress > 0 && (
                          <span className="tnum ml-auto font-mono text-[9.5px] text-accent-deep">
                            {doc.progress}%
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ol>
              </div>
            </div>

            <div className="shrink-0 space-y-2 border-t border-line p-4">
              <button
                type="button"
                onClick={() => void startScopedChat(doc)}
                className="flex w-full items-center justify-center gap-2 bg-ink px-4 py-3 text-[13px] font-medium text-paper transition-colors hover:bg-accent-deep"
              >
                <MessagesSquare size={14} />
                Query this filing
              </button>
              <button
                type="button"
                onClick={() =>
                  void uploadFiles([
                    {
                      name: `reindexed-${doc.filename}`,
                      size: doc.metadata.file_size,
                      type: "application/pdf",
                    },
                  ])
                }
                className="w-full border border-line px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.12em] text-moss transition-colors hover:border-ink/40 hover:text-ink"
              >
                Re-upload a revision
              </button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
