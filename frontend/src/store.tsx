import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "./lib/api";
import type { Conversation, FinDocument, HealthResponse, Source, View } from "./lib/types";

export interface ToastItem {
  id: number;
  kind: "success" | "info" | "error";
  title: string;
  body?: string;
  action?: { label: string; run: () => void };
}

export interface SelectedSource {
  source: Source;
  messageId: string;
  conversationId: string;
}

interface Store {
  view: View;
  setView: (v: View) => void;
  booted: boolean;
  boot: () => Promise<void>;

  documents: FinDocument[];
  refreshDocuments: () => Promise<void>;
  uploadFiles: (files: { name: string; size: number; type: string }[]) => Promise<void>;
  uploading: { name: string; pct: number; error?: string }[];
  libraryOpenDocId: string | null;
  setLibraryOpenDocId: (id: string | null) => void;

  conversations: Conversation[];
  activeId: string | null;
  active: Conversation | null;
  selectConversation: (id: string | null) => void;
  newChat: () => void;
  deleteConversation: (id: string) => Promise<void>;
  setScope: (conversationId: string, docIds: string[]) => void;
  startScopedChat: (doc: FinDocument) => Promise<void>;
  send: (question: string) => Promise<void>;
  streaming: boolean;
  stopStreaming: () => void;

  health: { status: HealthResponse["status"]; latency: number } | null;
  checkHealth: () => Promise<void>;

  selectedSource: SelectedSource | null;
  openSource: (s: SelectedSource) => void;
  closeSource: () => void;

  mobileNav: boolean;
  setMobileNav: (b: boolean) => void;

  toasts: ToastItem[];
  pushToast: (t: Omit<ToastItem, "id">) => void;
  dismissToast: (id: number) => void;
}

const Ctx = createContext<Store | null>(null);

let toastSeq = 1;

export function StoreProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<View>("chat");
  const [booted, setBooted] = useState(false);
  const [documents, setDocuments] = useState<FinDocument[]>([]);
  const [uploading, setUploading] = useState<Store["uploading"]>([]);
  const [libraryOpenDocId, setLibraryOpenDocId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [health, setHealth] = useState<Store["health"]>(null);
  const [selectedSource, setSelectedSource] = useState<SelectedSource | null>(null);
  const [mobileNav, setMobileNav] = useState(false);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const cancelStream = useRef<(() => void) | null>(null);
  const pollers = useRef(new Map<string, number>());

  /* ---------- toasts ---------- */
  const pushToast = useCallback((t: Omit<ToastItem, "id">) => {
    const id = toastSeq++;
    setToasts((prev) => [...prev, { ...t, id }].slice(-3));
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 4600);
  }, []);
  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  /* ---------- documents ---------- */
  const refreshDocuments = useCallback(async () => {
    try {
      const docs = await api.listDocuments();
      setDocuments(docs);
    } catch {
      /* keep stale */
    }
  }, []);

  const watchDocument = useCallback(
    (id: string) => {
      if (pollers.current.has(id)) return;
      const timer = window.setInterval(async () => {
        try {
          const doc = await api.getDocument(id);
          setDocuments((prev) => prev.map((d) => (d.id === id ? doc : d)));
          if (doc.status === "ready" || doc.status === "failed") {
            window.clearInterval(timer);
            pollers.current.delete(id);
            if (doc.status === "ready") {
              pushToast({
                kind: "success",
                title: "Filing indexed",
                body: `${doc.metadata.company_name} · ${doc.metadata.pages} pages are now searchable.`,
              });
            }
          }
        } catch {
          window.clearInterval(timer);
          pollers.current.delete(id);
        }
      }, 900);
      pollers.current.set(id, timer);
    },
    [pushToast]
  );

  const uploadFiles = useCallback(
    async (files: { name: string; size: number; type: string }[]) => {
      for (const f of files) {
        const key = f.name + f.size;
        setUploading((prev) => [...prev, { name: f.name, pct: 0 }]);
        try {
          const { promise } = api.uploadDocument(f, (pct) =>
            setUploading((prev) =>
              prev.map((u) => (u.name + "" === key || u.name === f.name ? { ...u, pct } : u))
            )
          );
          const { document } = await promise;
          setUploading((prev) => prev.filter((u) => u.name !== f.name));
          setDocuments((prev) => [document, ...prev.filter((d) => d.id !== document.id)]);
          watchDocument(document.id);
        } catch (e) {
          setUploading((prev) =>
            prev.map((u) =>
              u.name === f.name ? { ...u, error: e instanceof Error ? e.message : "Upload failed" } : u
            )
          );
          window.setTimeout(
            () => setUploading((prev) => prev.filter((u) => u.name !== f.name)),
            3200
          );
        }
      }
    },
    [watchDocument]
  );

  /* ---------- conversations ---------- */
  const patchConversation = useCallback((id: string, fn: (c: Conversation) => Conversation) => {
    setConversations((prev) => {
      const next = prev.map((c) => (c.id === id ? fn(c) : c));
      return [...next].sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));
    });
  }, []);

  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || streaming) return;
      setStreaming(true);
      setView("chat");
      setSelectedSource(null);

      let convoId = activeId;
      if (!convoId) {
        const title = q.length > 46 ? q.slice(0, 46).trimEnd() + "…" : q;
        try {
          const convo = await api.createConversation({ title });
          setConversations((prev) => [convo, ...prev]);
          convoId = convo.id;
          setActiveId(convo.id);
        } catch {
          setStreaming(false);
          pushToast({ kind: "error", title: "Could not create conversation" });
          return;
        }
      }
      const cid = convoId;

      const cancel = api.streamMessage(cid, q, {
        onUserMessage: (msg) =>
          patchConversation(cid, (c) => ({
            ...c,
            updated_at: msg.created_at,
            messages: [...c.messages, msg],
          })),
        onAssistantCreated: (msg) =>
          patchConversation(cid, (c) => ({ ...c, messages: [...c.messages, msg] })),
        onSubProcess: (stepId, patch) =>
          patchConversation(cid, (c) => ({
            ...c,
            messages: c.messages.map((m) =>
              m.sub_processes.some((s) => s.id === stepId)
                ? {
                    ...m,
                    sub_processes: m.sub_processes.map((s) =>
                      s.id === stepId ? { ...s, ...patch } : s
                    ),
                  }
                : m
            ),
          })),
        onToken: (token) =>
          patchConversation(cid, (c) => ({
            ...c,
            messages: c.messages.map((m, i) =>
              i === c.messages.length - 1 && m.role === "assistant"
                ? { ...m, status: "streaming", content: m.content + token }
                : m
            ),
          })),
        onDone: ({ content, sources }) => {
          patchConversation(cid, (c) => ({
            ...c,
            messages: c.messages.map((m, i) =>
              i === c.messages.length - 1 && m.role === "assistant"
                ? { ...m, status: "completed", content, sources }
                : m
            ),
          }));
          setStreaming(false);
          cancelStream.current = null;
        },
        onError: (message) => {
          patchConversation(cid, (c) => ({
            ...c,
            messages: c.messages.map((m, i) =>
              i === c.messages.length - 1 && m.role === "assistant"
                ? { ...m, status: "failed", content: m.content || message }
                : m
            ),
          }));
          setStreaming(false);
          cancelStream.current = null;
          pushToast({ kind: "error", title: "Answer interrupted", body: message });
        },
      });
      cancelStream.current = cancel;
    },
    [activeId, streaming, patchConversation, pushToast]
  );

  const stopStreaming = useCallback(() => {
    cancelStream.current?.();
    cancelStream.current = null;
    setStreaming(false);
  }, []);

  const selectConversation = useCallback((id: string | null) => {
    setActiveId(id);
    setView("chat");
    setSelectedSource(null);
    setMobileNav(false);
  }, []);

  const newChat = useCallback(() => {
    setActiveId(null);
    setView("chat");
    setSelectedSource(null);
    setMobileNav(false);
  }, []);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
      } catch {
        /* local delete anyway for prototype */
      }
      setConversations((prev) => prev.filter((c) => c.id !== id));
      setActiveId((cur) => (cur === id ? null : cur));
      pushToast({ kind: "info", title: "Conversation deleted" });
    },
    [pushToast]
  );

  const setScope = useCallback(
    (conversationId: string, docIds: string[]) => {
      patchConversation(conversationId, (c) => ({ ...c, document_scope: docIds }));
    },
    [patchConversation]
  );

  const startScopedChat = useCallback(
    async (doc: FinDocument) => {
      try {
        const convo = await api.createConversation({
          title: `${doc.metadata.nse_symbol} · ${doc.metadata.document_type.replace(/_/g, " ")}`,
          document_scope: [doc.id],
        });
        setConversations((prev) => [convo, ...prev]);
        setActiveId(convo.id);
        setView("chat");
        setLibraryOpenDocId(null);
        setSelectedSource(null);
        pushToast({
          kind: "info",
          title: "Scoped thread created",
          body: `Retrieval is narrowed to ${doc.metadata.company_name}.`,
        });
      } catch {
        pushToast({ kind: "error", title: "Could not create thread" });
      }
    },
    [pushToast]
  );

  /* ---------- health ---------- */
  const checkHealth = useCallback(async () => {
    try {
      const { data, latency } = await api.health();
      setHealth({ status: data.status, latency });
    } catch {
      setHealth({ status: "down", latency: 0 });
    }
  }, []);

  /* ---------- boot ---------- */
  const boot = useCallback(async () => {
    await Promise.all([refreshDocuments(), checkHealth()]);
    setBooted(true);
  }, [refreshDocuments, checkHealth]);

  const openSource = useCallback((s: SelectedSource) => setSelectedSource(s), []);
  const closeSource = useCallback(() => setSelectedSource(null), []);

  const active = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? null,
    [conversations, activeId]
  );

  const value: Store = {
    view,
    setView,
    booted,
    boot,
    documents,
    refreshDocuments,
    uploadFiles,
    uploading,
    libraryOpenDocId,
    setLibraryOpenDocId,
    conversations,
    activeId,
    active,
    selectConversation,
    newChat,
    deleteConversation,
    setScope,
    startScopedChat,
    send,
    streaming,
    stopStreaming,
    health,
    checkHealth,
    selectedSource,
    openSource,
    closeSource,
    mobileNav,
    setMobileNav,
    toasts,
    pushToast,
    dismissToast,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useStore outside provider");
  return ctx;
}
