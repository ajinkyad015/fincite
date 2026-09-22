import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRight, BookOpen, Quote, X } from "lucide-react";
import { useStore } from "../store";
import { DOC_TYPE_LABEL } from "../lib/format";
import Monogram from "./Monogram";

export default function SourceDrawer() {
  const { selectedSource, closeSource, documents, setView, setLibraryOpenDocId } = useStore();

  const src = selectedSource?.source ?? null;
  const doc = src ? documents.find((d) => d.id === src.document_id) : undefined;

  const openInLibrary = () => {
    if (!src) return;
    setLibraryOpenDocId(src.document_id);
    setView("library");
    closeSource();
  };

  return (
    <AnimatePresence>
      {selectedSource && src && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-ink/25 backdrop-blur-[1px] lg:hidden"
            onClick={closeSource}
          />
          <motion.aside
            initial={{ x: 60, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 60, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.32, 0.72, 0, 1] }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[420px] flex-col border-l border-line bg-paper shadow-[-30px_0_80px_-40px_rgba(22,19,11,0.5)]"
          >
            {/* header */}
            <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
              <span className="tnum flex h-[18px] min-w-[18px] items-center justify-center bg-ink px-1 font-mono text-[9.5px] font-medium text-paper">
                {src.index}
              </span>
              <span className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-moss">
                Source passage
              </span>
              <button
                type="button"
                onClick={closeSource}
                aria-label="Close source"
                className="ml-auto flex h-7 w-7 items-center justify-center border border-transparent text-moss transition-colors hover:border-line hover:text-ink"
              >
                <X size={14} />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {doc && (
                <div className="border-b border-line px-5 py-5">
                  <div className="flex items-start gap-3.5">
                    <Monogram symbol={doc.metadata.nse_symbol} size={44} />
                    <div className="min-w-0">
                      <h3 className="font-display text-[19px] font-semibold leading-tight text-ink">
                        {doc.metadata.company_name}
                      </h3>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[9.5px] text-moss">
                        <span className="border border-line bg-faint px-1.5 py-0.5">
                          NSE · {doc.metadata.nse_symbol}
                        </span>
                        <span>{DOC_TYPE_LABEL[doc.metadata.document_type]}</span>
                      </div>
                    </div>
                  </div>
                  <div className="tnum mt-4 grid grid-cols-3 gap-px border border-line bg-line">
                    {[
                      ["Fiscal", doc.metadata.fiscal_year.replace("FY", "FY ’")],
                      ["Pages", String(doc.metadata.pages)],
                      ["Period", doc.metadata.period.split("·")[0]],
                    ].map(([k, v]) => (
                      <div key={k} className="bg-faint/70 px-2.5 py-2">
                        <div className="font-mono text-[8.5px] uppercase tracking-[0.14em] text-moss">
                          {k}
                        </div>
                        <div className="mt-0.5 truncate text-[12.5px] font-medium text-ink">
                          {v}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* page + passage */}
              <div className="px-5 py-5">
                <div className="flex items-baseline justify-between">
                  <span className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-moss">
                    Retrieved from
                  </span>
                  <span className="tnum font-mono text-[9.5px] text-moss/70">
                    {doc ? `of ${doc.metadata.pages} pages` : ""}
                  </span>
                </div>
                <div className="mb-4 mt-1 font-display text-[44px] font-semibold leading-none tracking-tight text-ink">
                  Page {src.page}
                </div>

                <figure className="relative border border-line bg-bone p-4">
                  <Quote size={14} className="absolute -left-[1px] -top-[9px] bg-paper px-[1px] text-accent" />
                  <blockquote className="font-display text-[15px] italic leading-[1.75] text-ink/85">
                    “{src.excerpt}”
                  </blockquote>
                  <figcaption className="mt-3 font-mono text-[9px] text-moss">
                    chunk · {doc?.filename ?? "filing.pdf"}
                  </figcaption>
                </figure>

                <div className="mt-5">
                  <div className="flex items-baseline justify-between">
                    <span className="font-mono text-[9.5px] uppercase tracking-[0.18em] text-moss">
                      Cross-encoder score
                    </span>
                    <span className="tnum font-mono text-[11px] font-medium text-ink">
                      {src.score.toFixed(2)}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 w-full bg-faint">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${src.score * 100}%` }}
                      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
                      className="h-full bg-gradient-to-r from-accent/60 to-accent"
                    />
                  </div>
                  <p className="mt-2 font-mono text-[9px] leading-relaxed text-moss/80">
                    Relevance of this passage to your question, after hybrid retrieval and
                    reranking.
                  </p>
                </div>
              </div>
            </div>

            <div className="shrink-0 border-t border-line p-4">
              <button
                type="button"
                onClick={openInLibrary}
                className="group flex w-full items-center justify-center gap-2 bg-ink px-4 py-3 text-[13px] font-medium text-paper transition-colors hover:bg-accent-deep"
              >
                <BookOpen size={14} />
                Open filing in library
                <ArrowUpRight
                  size={13}
                  className="transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                />
              </button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
