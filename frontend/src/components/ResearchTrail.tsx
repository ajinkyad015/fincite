import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Check,
  ChevronDown,
  Database,
  FileSearch,
  ListFilter,
  Loader2,
  ScanSearch,
  X,
} from "lucide-react";
import type { MessageSubProcess, SubProcessSource } from "../lib/types";

const SOURCE_ICON: Record<SubProcessSource, typeof Brain> = {
  llm: Brain,
  retrieval: Database,
  rerank: ListFilter,
  parser: FileSearch,
};

function StatusIcon({ status }: { status: MessageSubProcess["status"] }) {
  if (status === "running")
    return <Loader2 size={12} className="animate-spin text-accent" strokeWidth={2.6} />;
  if (status === "completed") return <Check size={12} className="text-pine" strokeWidth={3} />;
  if (status === "failed") return <X size={12} className="text-rust" strokeWidth={3} />;
  return <span className="block h-[9px] w-[9px] border border-line bg-paper" />;
}

export default function ResearchTrail({ steps }: { steps: MessageSubProcess[] }) {
  const doneCount = steps.filter((s) => s.status === "completed" || s.status === "failed").length;
  const running = steps.some((s) => s.status === "running");
  const [open, setOpen] = useState(true);
  const collapsedOnce = useRef(false);

  const totalMs = useMemo(
    () => steps.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0),
    [steps]
  );

  // auto-collapse shortly after the last step completes
  useEffect(() => {
    if (!running && doneCount === steps.length && steps.length > 0 && !collapsedOnce.current) {
      collapsedOnce.current = true;
      const t = window.setTimeout(() => setOpen(false), 1400);
      return () => window.clearTimeout(t);
    }
  }, [running, doneCount, steps.length]);

  return (
    <div className="mb-4 border border-line bg-paper">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="group flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-faint"
      >
        <ScanSearch size={13} className={running ? "text-accent" : "text-moss"} />
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-moss">
          Research trail
        </span>
        {running ? (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-accent-deep">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute h-full w-full animate-ping bg-accent opacity-60" />
              <span className="h-full w-full bg-accent" />
            </span>
            working
          </span>
        ) : (
          <span className="tnum font-mono text-[10px] text-moss">
            {steps.length} steps · {(totalMs / 1000).toFixed(1)}s
          </span>
        )}
        <ChevronDown
          size={13}
          className={`ml-auto text-moss transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
            className="overflow-hidden border-t border-line"
          >
            {steps.map((s, i) => {
              const Icon = SOURCE_ICON[s.source] ?? Database;
              return (
                <li
                  key={s.id}
                  className={`flex items-start gap-3 px-3 py-2.5 ${
                    i > 0 ? "border-t border-line/70" : ""
                  } ${s.status === "running" ? "bg-accent-soft/30" : ""}`}
                >
                  <span className="mt-[3px] flex h-5 w-5 shrink-0 items-center justify-center border border-line bg-bone">
                    <StatusIcon status={s.status} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span
                        className={`text-[13px] font-medium ${
                          s.status === "pending" ? "text-moss" : "text-ink"
                        }`}
                      >
                        {s.name}
                      </span>
                      <span className="font-mono text-[9.5px] uppercase tracking-[0.12em] text-moss/80">
                        <Icon size={9} className="mr-1 inline -translate-y-px" />
                        {s.source}
                      </span>
                      {s.duration_ms != null && (
                        <span className="tnum ml-auto font-mono text-[10px] text-moss">
                          {s.duration_ms}ms
                        </span>
                      )}
                    </div>
                    {s.detail && s.status === "completed" && (
                      <p className="mt-0.5 text-[12px] leading-snug text-moss">{s.detail}</p>
                    )}
                    {s.status === "running" && (
                      <p className="mt-0.5 font-mono text-[10.5px] text-accent-deep">
                        <AnimatedEllipsis />
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}

function AnimatedEllipsis() {
  const [n, setN] = useState(1);
  useEffect(() => {
    const t = window.setInterval(() => setN((v) => (v % 3) + 1), 420);
    return () => window.clearInterval(t);
  }, []);
  return <span>running{".".repeat(n)}</span>;
}
