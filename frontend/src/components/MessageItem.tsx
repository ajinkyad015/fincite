import { memo, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Check, Copy, FileText } from "lucide-react";
import { useStore } from "../store";
import type { ChatMessage, FinDocument } from "../lib/types";
import { timeHM } from "../lib/format";
import CiteMarkdown from "./CiteMarkdown";
import ResearchTrail from "./ResearchTrail";
import Monogram from "./Monogram";

function MessageItem({
  message,
  documents,
}: {
  message: ChatMessage;
  documents: FinDocument[];
}) {
  const { openSource } = useStore();
  const [copied, setCopied] = useState(false);

  const docById = useMemo(() => {
    const map = new Map<string, FinDocument>();
    documents.forEach((d) => map.set(d.id, d));
    return map;
  }, [documents]);

  if (message.role === "user") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.28, ease: "easeOut" }}
        className="flex justify-end"
      >
        <div className="max-w-[82%] md:max-w-[70%]">
          <div className="bg-ink px-4 py-3 text-[14.5px] leading-relaxed text-paper">
            {message.content}
          </div>
          <div className="tnum mt-1.5 text-right font-mono text-[9.5px] text-moss">
            you · {timeHM(message.created_at)}
          </div>
        </div>
      </motion.div>
    );
  }

  /* ---------------- assistant ---------------- */
  const completed = message.status === "completed";
  const failed = message.status === "failed";

  const cite = (n: number) => {
    const src = message.sources.find((s) => s.index === n);
    if (src)
      openSource({ source: src, messageId: message.id, conversationId: message.conversation_id });
  };

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: "easeOut" }}
      className="w-full"
    >
      <div className="mb-2.5 flex items-center gap-2">
        <span className="flex h-[18px] w-[18px] items-center justify-center bg-accent font-display text-[12px] font-semibold italic text-paper">
          f
        </span>
        <span className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-moss">
          Fincite · research
        </span>
        <span className="tnum ml-auto font-mono text-[9.5px] text-moss">
          {timeHM(message.created_at)}
        </span>
      </div>

      {message.sub_processes.length > 0 && <ResearchTrail steps={message.sub_processes} />}

      {failed && (
        <div className="mb-3 flex items-center gap-2 border border-rust/40 bg-rust-soft px-3 py-2 text-[13px] text-rust">
          <AlertTriangle size={14} />
          The answer stream was interrupted. Try asking again.
        </div>
      )}

      {/* body */}
      {completed || failed ? (
        <CiteMarkdown content={message.content} onCite={cite} />
      ) : message.content ? (
        <div className="stream-caret whitespace-pre-wrap text-[15px] leading-[1.78] text-ink/85">
          {message.content}
        </div>
      ) : (
        <div className="flex items-center gap-2.5 py-2 font-mono text-[11px] text-moss">
          <span className="flex gap-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-1.5 w-1.5 animate-pulse bg-moss/60"
                style={{ animationDelay: `${i * 180}ms` }}
              />
            ))}
          </span>
          assembling context…
        </div>
      )}

      {/* sources */}
      {completed && message.sources.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 flex items-center gap-2">
            <FileText size={11} className="text-moss" />
            <span className="font-mono text-[9.5px] uppercase tracking-[0.18em] text-moss">
              Grounded sources
            </span>
            <span className="tnum font-mono text-[9.5px] text-moss/70">
              {message.sources.length}
            </span>
            <span className="h-px flex-1 bg-line" />
          </div>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {message.sources.map((s) => {
              const doc = docById.get(s.document_id);
              return (
                <button
                  key={s.index}
                  type="button"
                  onClick={() => cite(s.index)}
                  className="group flex flex-col border border-line bg-paper p-3 text-left transition-all hover:-translate-y-0.5 hover:border-accent/60 hover:shadow-[0_10px_26px_-14px_rgba(22,19,11,0.4)]"
                >
                  <div className="flex items-center gap-2">
                    <span className="tnum flex h-[16px] min-w-[16px] items-center justify-center bg-ink px-1 font-mono text-[9px] font-medium text-paper">
                      {s.index}
                    </span>
                    {doc && <Monogram symbol={doc.metadata.nse_symbol} size={16} />}
                    <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">
                      {doc?.metadata.nse_symbol ?? "Filing"}
                    </span>
                    <span className="tnum shrink-0 font-mono text-[9.5px] text-moss">
                      p. {s.page}
                    </span>
                  </div>
                  <p className="mt-2 line-clamp-3 text-[11.5px] leading-[1.6] text-moss">
                    “{s.excerpt}”
                  </p>
                  <div className="mt-2.5 flex items-center gap-2">
                    <span className="h-[3px] flex-1 bg-faint">
                      <span
                        className="block h-full bg-accent transition-all duration-500"
                        style={{ width: `${Math.round(s.score * 100)}%` }}
                      />
                    </span>
                    <span className="tnum font-mono text-[9px] text-moss">
                      {Math.round(s.score * 100)}% match
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* actions */}
      {completed && (
        <div className="mt-3 flex items-center gap-1 opacity-70 transition-opacity hover:opacity-100">
          <button
            type="button"
            onClick={copyAnswer}
            className="flex items-center gap-1.5 border border-transparent px-2 py-1 font-mono text-[10px] text-moss transition-colors hover:border-line hover:text-ink"
          >
            {copied ? <Check size={11} className="text-pine" /> : <Copy size={11} />}
            {copied ? "copied" : "copy answer"}
          </button>
        </div>
      )}
    </motion.div>
  );
}

export default memo(MessageItem);
