import { useEffect, useRef, useState } from "react";
import { ArrowUp, CornerDownLeft, Square } from "lucide-react";
import { useStore } from "../store";

export default function Composer({ centered = false }: { centered?: boolean }) {
  const { send, streaming, stopStreaming, active, documents } = useStore();
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // auto-grow
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 168) + "px";
  }, [value]);

  // cmd/ctrl+K focuses the composer from anywhere
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = () => {
    const q = value.trim();
    if (!q || streaming) return;
    setValue("");
    void send(q);
    window.setTimeout(() => ref.current?.focus(), 60);
  };

  const readyDocs = documents.filter((d) => d.status === "ready").length;
  const scoped = active && active.document_scope.length > 0 ? active.document_scope.length : readyDocs;

  return (
    <div className={centered ? "" : ""}>
      <div
        className={`border bg-paper transition-shadow focus-within:shadow-[0_14px_44px_-18px_rgba(22,19,11,0.35)] ${
          streaming ? "border-accent/50" : "border-line hover:border-ink/30 focus-within:border-ink/50"
        }`}
      >
        <div className="flex items-end gap-2 px-4 pb-3 pt-3.5">
          <textarea
            ref={ref}
            rows={centered ? 2 : 1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            disabled={streaming}
            placeholder={
              streaming ? "Fincite is researching…" : "Ask across every indexed filing…"
            }
            className="max-h-[168px] flex-1 resize-none bg-transparent text-[15px] leading-relaxed text-ink placeholder:text-moss/70 disabled:opacity-60"
            aria-label="Ask a question"
          />
          {streaming ? (
            <button
              type="button"
              onClick={stopStreaming}
              aria-label="Stop generating"
              className="flex h-9 w-9 shrink-0 items-center justify-center bg-ink text-paper transition-colors hover:bg-accent-deep"
            >
              <Square size={13} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!value.trim()}
              aria-label="Send question"
              className={`flex h-9 w-9 shrink-0 items-center justify-center transition-all ${
                value.trim()
                  ? "bg-accent text-paper hover:bg-accent-deep"
                  : "bg-faint text-moss/50"
              }`}
            >
              <ArrowUp size={16} strokeWidth={2.6} />
            </button>
          )}
        </div>
        <div className="flex items-center gap-3 border-t border-line/80 px-4 py-1.5 font-mono text-[9.5px] text-moss">
          <span className="flex items-center gap-1">
            <CornerDownLeft size={9} /> send
          </span>
          <span className="hidden sm:inline">⇧+↵ newline</span>
          <span className="hidden md:inline">⌘K focus</span>
          <span className="ml-auto tnum">
            {streaming ? (
              <span className="text-accent-deep">retrieving &amp; grounding…</span>
            ) : (
              <>
                scope · <span className="text-ink/70">{scoped} filing{scoped === 1 ? "" : "s"}</span>
              </>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
