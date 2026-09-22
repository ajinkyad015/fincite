import { useState, type ReactNode } from "react";
import {
  Activity,
  BookMarked,
  Check,
  MessagesSquare,
  Plus,
  Terminal,
  Trash2,
  X,
} from "lucide-react";
import { useStore } from "../store";
import { shortDate } from "../lib/format";

export default function Sidebar() {
  const {
    view,
    setView,
    conversations,
    activeId,
    selectConversation,
    newChat,
    deleteConversation,
    documents,
    health,
    setMobileNav,
  } = useStore();
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const nav = (v: "chat" | "library") => {
    setView(v);
    setMobileNav(false);
  };

  return (
    <div className="flex h-full flex-col bg-soot text-bone">
      {/* brand */}
      <div className="px-5 pb-5 pt-5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center bg-accent font-display text-xl font-semibold italic text-paper">
            f
          </span>
          <div className="leading-none">
            <div className="font-display text-[21px] font-semibold tracking-tight text-bone">
              Fincite
            </div>
            <div className="mt-1 font-mono text-[9px] uppercase tracking-[0.22em] text-bone/40">
              Ask the filings
            </div>
          </div>
          <span className="ml-auto border border-line-dark px-1.5 py-0.5 font-mono text-[9px] text-bone/45">
            v0.1.0
          </span>
        </div>
      </div>

      {/* primary nav */}
      <nav className="px-3">
        <NavItem
          active={view === "library"}
          onClick={() => nav("library")}
          icon={<BookMarked size={14} />}
          label="Filing library"
          meta={`${documents.length}`}
        />
        <NavItem
          active={view === "chat"}
          onClick={() => nav("chat")}
          icon={<MessagesSquare size={14} />}
          label="Research chats"
          meta={`${conversations.length}`}
        />
      </nav>

      {/* conversations */}
      <div className="mt-5 flex min-h-0 flex-1 flex-col border-t border-line-dark/70">
        <div className="flex items-center justify-between px-5 pb-2 pt-4">
          <span className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-bone/40">
            Threads
          </span>
          <button
            type="button"
            onClick={newChat}
            className="flex items-center gap-1 border border-line-dark px-2 py-1 font-mono text-[10px] text-bone/70 transition-colors hover:border-accent hover:bg-accent hover:text-paper"
          >
            <Plus size={11} strokeWidth={2.6} /> New
          </button>
        </div>

        <div className="dark-scroll min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {conversations.length === 0 && (
            <div className="mx-1 mt-2 border border-dashed border-line-dark/80 px-4 py-6 text-center">
              <Terminal size={16} className="mx-auto text-bone/25" />
              <p className="mt-3 font-display text-[13.5px] italic leading-snug text-bone/45">
                No threads yet.
                <br />
                Ask a question to begin.
              </p>
            </div>
          )}
          <ul className="mt-1 space-y-0.5">
            {conversations.map((c) => {
              const activeC = c.id === activeId;
              const confirming = confirmId === c.id;
              return (
                <li key={c.id} className="group relative">
                  {confirming ? (
                    <div className="flex items-center gap-2 border border-rust/60 bg-rust/20 px-3 py-2.5">
                      <span className="flex-1 truncate font-mono text-[10px] text-bone/80">
                        Delete thread?
                      </span>
                      <button
                        type="button"
                        aria-label="Confirm delete"
                        onClick={async () => {
                          await deleteConversation(c.id);
                          setConfirmId(null);
                        }}
                        className="flex h-6 w-6 items-center justify-center bg-rust text-paper hover:bg-rust/80"
                      >
                        <Check size={12} strokeWidth={3} />
                      </button>
                      <button
                        type="button"
                        aria-label="Cancel delete"
                        onClick={() => setConfirmId(null)}
                        className="flex h-6 w-6 items-center justify-center border border-line-dark text-bone/70 hover:text-bone"
                      >
                        <X size={12} strokeWidth={3} />
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => selectConversation(c.id)}
                      className={`flex w-full items-center gap-2 border-l-2 px-3 py-2.5 text-left transition-colors ${
                        activeC
                          ? "border-accent bg-bone/[0.07]"
                          : "border-transparent hover:bg-bone/[0.04]"
                      }`}
                    >
                      <span className="min-w-0 flex-1">
                        <span
                          className={`block truncate text-[12.5px] leading-tight ${
                            activeC ? "font-medium text-bone" : "text-bone/70"
                          }`}
                        >
                          {c.title}
                        </span>
                        <span className="mt-1 flex items-center gap-2 font-mono text-[9.5px] text-bone/35">
                          <span className="tnum">{shortDate(c.updated_at)}</span>
                          <span className="h-px w-2 bg-bone/20" />
                          <span className="tnum">{c.messages.length} msgs</span>
                        </span>
                      </span>
                      <span
                        role="button"
                        tabIndex={-1}
                        aria-label="Delete conversation"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmId(c.id);
                        }}
                        className="hidden h-6 w-6 shrink-0 items-center justify-center text-bone/40 hover:bg-rust/20 hover:text-red-300 group-hover:flex"
                      >
                        <Trash2 size={12} />
                      </span>
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {/* api health */}
      <div className="border-t border-line-dark/70 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span
            className={`h-2 w-2 ${
              health?.status === "healthy"
                ? "animate-pulse-dot bg-emerald-400"
                : health?.status === "down"
                  ? "bg-red-400"
                  : health == null
                    ? "bg-bone/30"
                    : "bg-amber-400"
            }`}
          />
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-bone/50">
            <Activity size={10} className="mr-1 inline -translate-y-px" />
            fincite API
          </span>
          <span className="ml-auto tnum font-mono text-[10px] text-bone/60">
            {health ? (health.status === "down" ? "unreachable" : `${health.latency}ms`) : "…"}
          </span>
        </div>
        <div className="mt-2 truncate font-mono text-[9.5px] text-bone/30">
          POST /api/conversation · GET /api/document
        </div>
      </div>
    </div>
  );
}

function NavItem({
  active,
  onClick,
  icon,
  label,
  meta,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
  meta?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`mb-0.5 flex w-full items-center gap-2.5 border-l-2 px-3 py-2.5 text-left text-[13px] transition-colors ${
        active
          ? "border-accent bg-bone/[0.07] text-bone"
          : "border-transparent text-bone/60 hover:bg-bone/[0.04] hover:text-bone"
      }`}
    >
      {icon}
      <span className="font-medium">{label}</span>
      {meta && (
        <span className="tnum ml-auto font-mono text-[10px] text-bone/35">{meta}</span>
      )}
    </button>
  );
}
