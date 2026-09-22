import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRight, Check, Layers, SlidersHorizontal } from "lucide-react";
import { useStore } from "../store";
import { SUGGESTIONS } from "../lib/mockData";
import { DOC_TYPE_SHORT } from "../lib/format";
import Composer from "./Composer";
import MessageItem from "./MessageItem";
import Monogram from "./Monogram";

export default function ChatView() {
  const { active, conversations, documents, send, setView } = useStore();
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);

  const messages = active?.messages ?? [];
  const lastLen = messages.length > 0 ? messages[messages.length - 1].content.length : 0;

  // stick to bottom while streaming unless the user scrolls up
  useEffect(() => {
    const el = scrollRef.current;
    if (el && nearBottom.current) el.scrollTop = el.scrollHeight;
  }, [lastLen, messages.length]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 260;
  };

  const ready = documents.filter((d) => d.status === "ready");
  const companies = new Set(ready.map((d) => d.metadata.nse_symbol)).size;
  const pages = ready.reduce((a, d) => a + d.metadata.pages, 0);
  const indexing = documents.length - ready.length;

  const showHero = messages.length === 0;

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-bone/85 px-4 backdrop-blur-sm md:px-6">
        <div className="min-w-0 flex-1">
          {active ? (
            <div className="flex items-baseline gap-3">
              <h1 className="truncate font-display text-[17px] font-semibold text-ink">
                {active.title}
              </h1>
              <span className="tnum hidden shrink-0 font-mono text-[9.5px] text-moss sm:inline">
                thread {active.id.slice(-6).toUpperCase()}
              </span>
            </div>
          ) : (
            <h1 className="font-display text-[17px] font-semibold text-ink">
              New research thread
              <span className="ml-3 hidden font-mono text-[9.5px] font-normal uppercase tracking-[0.16em] text-moss sm:inline">
                {conversations.length > 0 ? "or pick a thread from the rail" : "ask anything to begin"}
              </span>
            </h1>
          )}
        </div>
        <ScopePicker />
      </header>

      {/* body */}
      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
        {showHero ? (
          <Hero
            readyCount={ready.length}
            companies={companies}
            pages={pages}
            indexing={indexing}
            onAsk={(q) => void send(q)}
            onLibrary={() => setView("library")}
          />
        ) : (
          <div className="mx-auto max-w-[780px] space-y-10 px-4 py-8 md:px-6">
            {messages.map((m) => (
              <MessageItem key={m.id} message={m} documents={documents} />
            ))}
            <div className="h-4" />
          </div>
        )}
      </div>

      {/* composer */}
      <div className="shrink-0 border-t border-line bg-gradient-to-b from-bone to-faint/60 px-4 pb-4 pt-3 md:px-6">
        <div className="mx-auto max-w-[780px]">
          <Composer />
          <p className="mt-2 text-center font-mono text-[9px] text-moss/70">
            Prototype data · answers are grounded mock generation · streams from GET
            /api/conversation/{"{id}"}/message
          </p>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Empty-state hero                                                   */
/* ------------------------------------------------------------------ */

function Hero({
  readyCount,
  companies,
  pages,
  indexing,
  onAsk,
  onLibrary,
}: {
  readyCount: number;
  companies: number;
  pages: number;
  indexing: number;
  onAsk: (q: string) => void;
  onLibrary: () => void;
}) {
  return (
    <div className="mx-auto flex min-h-full max-w-[860px] flex-col justify-center px-5 py-10 md:px-8">
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="flex items-center gap-3 font-mono text-[9.5px] uppercase tracking-[0.22em] text-moss">
          <span className="h-[7px] w-[7px] bg-accent" />
          Research-grade RAG · Indian filings
        </div>

        <h2 className="mt-5 font-display text-[42px] font-medium leading-[1.04] tracking-[-0.015em] text-ink sm:text-[58px] md:text-[64px]">
          Interrogate the filings.
          <br />
          <span className="italic text-accent">Every claim, pinned to a page.</span>
        </h2>

        <p className="tnum mt-6 max-w-xl font-mono text-[11px] leading-relaxed text-moss">
          {readyCount} DOCUMENTS · {companies} NSE COMPANIES · {pages.toLocaleString()} PAGES IN THE
          INDEX
          {indexing > 0 && <span className="text-accent-deep"> · {indexing} INDEXING NOW</span>}
        </p>

        <div className="mt-10 grid gap-2.5 sm:grid-cols-2">
          {SUGGESTIONS.map((s, i) => (
            <motion.button
              key={s.question}
              type="button"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.18 + i * 0.07, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
              onClick={() => onAsk(s.question)}
              className="group relative flex flex-col border border-line bg-paper p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-ink/40 hover:shadow-[0_16px_36px_-20px_rgba(22,19,11,0.45)]"
            >
              <span className="flex items-start justify-between gap-3">
                <span className="font-display text-[15.5px] leading-snug text-ink">
                  {s.question}
                </span>
                <ArrowUpRight
                  size={15}
                  className="mt-0.5 shrink-0 text-moss transition-all duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-accent"
                />
              </span>
              <span className="mt-3 flex flex-wrap gap-1.5">
                {s.tags.map((t) => (
                  <span
                    key={t}
                    className="border border-line bg-faint px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.08em] text-moss"
                  >
                    {t}
                  </span>
                ))}
              </span>
            </motion.button>
          ))}
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-[9.5px] leading-relaxed text-moss/60">
          <span>
            TRY: “what did management say about wage hikes” — retrieval falls back to the nearest
            grounded passage and says so.
          </span>
          <button
            type="button"
            onClick={onLibrary}
            className="text-accent-deep underline decoration-accent/40 underline-offset-[3px] transition-colors hover:decoration-accent"
          >
            or drop your own PDFs into the library →
          </button>
        </div>
      </motion.div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Per-conversation document scope picker                             */
/* ------------------------------------------------------------------ */

function ScopePicker() {
  const { active, documents, setScope, streaming } = useStore();
  const [open, setOpen] = useState(false);
  const ready = useMemo(() => documents.filter((d) => d.status === "ready"), [documents]);

  if (!active) return null;
  const scope = active.document_scope;
  const all = scope.length === 0;

  const toggle = (id: string) => {
    const next = all ? [id] : scope.includes(id) ? scope.filter((x) => x !== id) : [...scope, id];
    setScope(active.id, next);
  };

  return (
    <div className="relative">
      <button
        type="button"
        disabled={streaming}
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 border px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors disabled:opacity-50 ${
          open
            ? "border-ink bg-ink text-paper"
            : "border-line bg-paper text-moss hover:border-ink/40 hover:text-ink"
        }`}
      >
        <SlidersHorizontal size={11} />
        <span className="hidden sm:inline">Scope</span>
        <span className="tnum text-inherit">
          {all ? `all ${ready.length}` : `${scope.length}`}
        </span>
        <Layers size={11} className={all ? "opacity-40" : "text-accent"} />
      </button>

      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, y: -6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -6, scale: 0.98 }}
              transition={{ duration: 0.16 }}
              className="absolute right-0 z-40 mt-2 w-[300px] border border-line bg-paper shadow-[0_24px_60px_-24px_rgba(22,19,11,0.5)]"
            >
              <div className="border-b border-line px-3.5 py-2.5 font-mono text-[9px] uppercase tracking-[0.2em] text-moss">
                Query scope · this thread
              </div>
              <button
                type="button"
                onClick={() => setScope(active.id, [])}
                className="flex w-full items-center gap-2.5 border-b border-line/70 px-3.5 py-2.5 text-left text-[12.5px] transition-colors hover:bg-faint"
              >
                <span
                  className={`flex h-4 w-4 items-center justify-center border ${
                    all ? "border-accent bg-accent text-paper" : "border-line bg-bone"
                  }`}
                >
                  {all && <Check size={10} strokeWidth={3.2} />}
                </span>
                <span className="font-medium text-ink">All filings</span>
                <span className="tnum ml-auto font-mono text-[9.5px] text-moss">
                  {ready.length} docs
                </span>
              </button>
              <div className="max-h-[280px] overflow-y-auto">
                {ready.map((d) => {
                  const on = all || scope.includes(d.id);
                  return (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => toggle(d.id)}
                      className="flex w-full items-center gap-2.5 border-b border-line/50 px-3.5 py-2.5 text-left transition-colors last:border-0 hover:bg-faint"
                    >
                      <span
                        className={`flex h-4 w-4 shrink-0 items-center justify-center border ${
                          on && !all ? "border-accent bg-accent text-paper" : "border-line bg-bone"
                        }`}
                      >
                        {on && !all && <Check size={10} strokeWidth={3.2} />}
                      </span>
                      <Monogram symbol={d.metadata.nse_symbol} size={20} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12.5px] text-ink">
                          {d.metadata.nse_symbol}
                        </span>
                        <span className="block truncate font-mono text-[9px] text-moss">
                          {DOC_TYPE_SHORT[d.metadata.document_type]} · {d.metadata.period}
                        </span>
                      </span>
                      <span className="tnum font-mono text-[9px] text-moss">
                        {d.metadata.pages}p
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="border-t border-line bg-faint/60 px-3.5 py-2 font-mono text-[9px] leading-relaxed text-moss">
                Unchecked mixture = whole corpus. Selecting filings narrows retrieval for this
                thread only.
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
