import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, USE_MOCK } from "./lib/api";
import { uid } from "./lib/format";
import type {
  ChatMessage,
  Conversation,
  DocumentUploadMetadata,
  FinDocument,
  HealthResponse,
  MessageSubProcess,
  Source,
  UploadableFile,
  View,
} from "./lib/types";

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
  uploadFiles: (files: UploadableFile[], metadata?: DocumentUploadMetadata) => Promise<void>;
  retryDocument: (id: string) => Promise<void>;
  uploading: { name: string; pct: number; error?: string }[];
  libraryOpenDocId: string | null;
  setLibraryOpenDocId: (id: string | null) => void;

  conversations: Conversation[];
  refreshConversations: () => Promise<Conversation[]>;
  activeId: string | null;
  active: Conversation | null;
  selectConversation: (id: string | null) => Promise<void>;
  newChat: () => void;
  deleteConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  setScope: (conversationId: string, docIds: string[]) => Promise<void>;
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
const ACTIVE_THREAD_KEY = "lastThreadId";
const THREAD_CACHE_MS = 15_000;

let toastSeq = 1;

function readActiveThread(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_THREAD_KEY);
  } catch {
    return null;
  }
}

function rememberActiveThread(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(ACTIVE_THREAD_KEY, id);
    else window.localStorage.removeItem(ACTIVE_THREAD_KEY);
  } catch {
    /* private browsing / storage disabled: threads still work for this session */
  }
}

function sorted(conversations: Conversation[]): Conversation[] {
  return [...conversations].sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));
}

function upsertConversation(list: Conversation[], incoming: Conversation): Conversation[] {
  const cached = list.find((c) => c.id === incoming.id);
  const keepCachedMessages =
    cached && incoming.messages.length === 0 && (incoming.message_count ?? 0) > 0;
  const merged: Conversation = {
    ...(cached ?? {}),
    ...incoming,
    messages: keepCachedMessages ? cached!.messages : incoming.messages,
    message_count: incoming.message_count ?? (keepCachedMessages ? cached!.messages.length : incoming.messages.length),
  };
  return sorted([...list.filter((c) => c.id !== incoming.id), merged]);
}

function appendMessage(conversation: Conversation, message: ChatMessage): Conversation {
  if (conversation.messages.some((m) => m.id === message.id)) return conversation;
  const messages = [...conversation.messages, message];
  return {
    ...conversation,
    messages,
    message_count: messages.length,
    updated_at: message.created_at || conversation.updated_at,
  };
}

function lastAssistantIndex(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return i;
  return -1;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Request failed";
}

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
  const loadedAt = useRef(new Map<string, number>());
  const pendingSnapshot = useRef<{ cid: string; message: ChatMessage } | null>(null);
  const snapshotFrame = useRef<number | null>(null);
  const snapshotDriven = useRef(false);

  /* ---------- toasts ---------- */
  const pushToast = useCallback((t: Omit<ToastItem, "id">) => {
    const id = toastSeq++;
    setToasts((prev) => [...prev, { ...t, id }].slice(-3));
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 4600);
  }, []);
  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  /* ---------- conversations ---------- */
  const patchConversation = useCallback((id: string, fn: (c: Conversation) => Conversation) => {
    setConversations((prev) => sorted(prev.map((c) => (c.id === id ? fn(c) : c))));
  }, []);

  const upsert = useCallback((conversation: Conversation) => {
    setConversations((prev) => upsertConversation(prev, conversation));
  }, []);

  const loadConversation = useCallback(
    async (id: string, force = false) => {
      const loaded = loadedAt.current.get(id) ?? 0;
      if (!force && Date.now() - loaded < THREAD_CACHE_MS) return;
      const conversation = await api.getConversation(id);
      upsert(conversation);
      loadedAt.current.set(id, Date.now());
    },
    [upsert]
  );

  const refreshConversations = useCallback(async () => {
    const list = await api.listConversations();
    setConversations((prev) => {
      const byId = new Map(prev.map((c) => [c.id, c]));
      return sorted(
        list.map((incoming) => {
          const cached = byId.get(incoming.id);
          if (!cached) return incoming;
          return {
            ...incoming,
            messages: cached.messages,
            message_count: incoming.message_count ?? cached.messages.length,
          };
        })
      );
    });
    return list;
  }, []);

  /* ---------- documents ---------- */
  const refreshDocuments = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments());
    } catch {
      /* keep stale; the health indicator says the backend is down */
    }
  }, []);

  const watchDocument = useCallback(
    (id: string) => {
      if (pollers.current.has(id)) return;
      let delay = 500;
      const finish = () => {
        const timer = pollers.current.get(id);
        if (timer !== undefined) window.clearTimeout(timer);
        pollers.current.delete(id);
      };
      const schedule = () => {
        const timer = window.setTimeout(() => void tick(), delay);
        pollers.current.set(id, timer);
      };
      const tick = async () => {
        try {
          const doc = await api.getDocument(id);
          setDocuments((prev) => prev.map((d) => (d.id === id ? doc : d)));
          if (doc.status === "ready" || doc.status === "failed") {
            finish();
            pushToast(
              doc.status === "ready"
                ? {
                    kind: "success",
                    title: "Filing indexed",
                    body: `${doc.metadata.company_name} · ${doc.metadata.pages} pages are now searchable.`,
                  }
                : {
                    kind: "error",
                    title: "Indexing failed",
                    body: doc.error ?? "The filing could not be indexed.",
                  }
            );
            return;
          }
        } catch {
          finish();
          return;
        }
        delay = Math.min(5000, Math.round(delay * 1.5));
        schedule();
      };
      schedule();
    },
    [pushToast]
  );

  const uploadFiles = useCallback(
    async (files: UploadableFile[], metadata?: DocumentUploadMetadata) => {
      for (const f of files) {
        const hasBytes =
          (typeof Blob !== "undefined" && f instanceof Blob) ||
          typeof (f as unknown as { arrayBuffer?: unknown }).arrayBuffer === "function";
        if (!USE_MOCK && !hasBytes) {
          pushToast({ kind: "error", title: "Choose a PDF file", body: `${f.name} has no file bytes.` });
          continue;
        }
        setUploading((prev) => [...prev, { name: f.name, pct: 0 }]);
        try {
          const { promise } = api.uploadDocument(
            f,
            (pct) => setUploading((prev) => prev.map((u) => (u.name === f.name ? { ...u, pct } : u))),
            metadata
          );
          const { document } = await promise;
          setUploading((prev) => prev.filter((u) => u.name !== f.name));
          setDocuments((prev) => [document, ...prev.filter((d) => d.id !== document.id)]);
          if (document.status === "ready" || document.status === "failed") {
            pushToast({
              kind: document.status === "ready" ? "success" : "error",
              title: document.status === "ready" ? "Filing ready" : "Indexing failed",
              body: document.error ?? document.metadata.company_name,
            });
          } else {
            watchDocument(document.id);
          }
        } catch (e) {
          const message = errorMessage(e);
          setUploading((prev) =>
            prev.map((u) => (u.name === f.name ? { ...u, error: message } : u))
          );
          window.setTimeout(
            () => setUploading((prev) => prev.filter((u) => u.name !== f.name)),
            3200
          );
        }
      }
    },
    [pushToast, watchDocument]
  );

  const retryDocument = useCallback(
    async (id: string) => {
      try {
        const { document } = await api.reindexDocument(id);
        setDocuments((prev) => prev.map((d) => (d.id === id ? document : d)));
        watchDocument(id);
      } catch (e) {
        pushToast({ kind: "error", title: "Could not retry indexing", body: errorMessage(e) });
      }
    },
    [pushToast, watchDocument]
  );

  /* ---------- rAF-batched snapshot streaming ---------- */
  const applySnapshot = useCallback(
    (cid: string, message: ChatMessage) => {
      patchConversation(cid, (c) => {
        const messages = [...c.messages];
        let index = messages.findIndex((m) => m.id === message.id && m.role === "assistant");
        if (index < 0) {
          const last = lastAssistantIndex(messages);
          if (last >= 0 && messages[last].status !== "completed") index = last;
        }
        if (index >= 0) messages[index] = message;
        else messages.push(message);
        return {
          ...c,
          messages,
          message_count: messages.length,
          updated_at: new Date().toISOString(),
        };
      });
    },
    [patchConversation]
  );

  const flushSnapshot = useCallback(() => {
    snapshotFrame.current = null;
    const pending = pendingSnapshot.current;
    pendingSnapshot.current = null;
    if (pending) applySnapshot(pending.cid, pending.message);
  }, [applySnapshot]);

  const scheduleSnapshot = useCallback(
    (cid: string, message: ChatMessage) => {
      snapshotDriven.current = true;
      const terminal = message.status === "completed" || message.status === "failed";
      if (terminal) {
        if (snapshotFrame.current !== null) window.cancelAnimationFrame(snapshotFrame.current);
        snapshotFrame.current = null;
        pendingSnapshot.current = null;
        applySnapshot(cid, message);
        return;
      }
      pendingSnapshot.current = { cid, message };
      if (snapshotFrame.current === null) {
        snapshotFrame.current = window.requestAnimationFrame(flushSnapshot);
      }
    },
    [applySnapshot, flushSnapshot]
  );

  const finishMessage = useCallback(
    (
      cid: string,
      status: "completed" | "failed",
      content: string | undefined,
      sources: Source[] | undefined,
      errorText: string
    ) => {
      patchConversation(cid, (c) => {
        const messages = [...c.messages];
        let index = lastAssistantIndex(messages);
        if (index < 0) {
          messages.push({
            id: uid("failed"),
            conversation_id: cid,
            role: "assistant",
            content: content || errorText,
            status,
            sub_processes: [],
            sources: sources ?? [],
            created_at: new Date().toISOString(),
          });
          index = messages.length - 1;
        } else {
          messages[index] = {
            ...messages[index],
            status,
            content: content || messages[index].content || errorText,
            sources: sources ?? messages[index].sources,
          };
        }
        return { ...c, messages, message_count: messages.length, updated_at: new Date().toISOString() };
      });
    },
    [patchConversation]
  );

  /* ---------- send / stream ---------- */
  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || streaming) return;
      setStreaming(true);
      setView("chat");
      setSelectedSource(null);
      snapshotDriven.current = false;

      let convoId = activeId;
      if (!convoId) {
        const title = q.length > 46 ? q.slice(0, 46).trimEnd() + "…" : q;
        try {
          const convo = await api.createConversation({ title });
          upsert(convo);
          convoId = convo.id;
          setActiveId(convo.id);
          rememberActiveThread(convo.id);
        } catch (e) {
          setStreaming(false);
          pushToast({ kind: "error", title: "Could not create conversation", body: errorMessage(e) });
          return;
        }
      }
      const cid = convoId;

      const cancel = api.streamMessage(cid, q, {
        onUserMessage: (msg) => patchConversation(cid, (c) => appendMessage(c, msg)),
        onAssistantCreated: (msg) => {
          if (snapshotDriven.current) return;
          patchConversation(cid, (c) => appendMessage(c, msg));
        },
        onSubProcess: (stepId, patch) => {
          if (snapshotDriven.current) return;
          patchConversation(cid, (c) => ({
            ...c,
            messages: c.messages.map((m) => {
              if (!m.sub_processes.some((s) => s.id === stepId)) {
                if (!patch.name || !patch.source || !patch.status) return m;
                return {
                  ...m,
                  sub_processes: [
                    ...m.sub_processes,
                    {
                      id: stepId,
                      name: patch.name,
                      source: patch.source,
                      status: patch.status,
                      detail: patch.detail,
                      duration_ms: patch.duration_ms,
                    } satisfies MessageSubProcess,
                  ],
                };
              }
              return {
                ...m,
                sub_processes: m.sub_processes.map((s) => (s.id === stepId ? { ...s, ...patch } : s)),
              };
            }),
          }));
        },
        onToken: (token) => {
          if (snapshotDriven.current) return;
          patchConversation(cid, (c) => {
            const messages = [...c.messages];
            const index = lastAssistantIndex(messages);
            if (index < 0) return c;
            messages[index] = {
              ...messages[index],
              status: "streaming",
              content: messages[index].content + token,
            };
            return { ...c, messages, updated_at: new Date().toISOString() };
          });
        },
        onSnapshot: (message) => scheduleSnapshot(cid, message),
        onDone: ({ content, sources }) => {
          if (snapshotFrame.current !== null) flushSnapshot();
          finishMessage(cid, "completed", content, sources, "");
          setStreaming(false);
          cancelStream.current = null;
          snapshotDriven.current = false;
          void loadConversation(cid, true).catch(() => undefined);
          void refreshConversations().catch(() => undefined);
        },
        onError: (message) => {
          if (snapshotFrame.current !== null) flushSnapshot();
          finishMessage(cid, "failed", undefined, undefined, message);
          setStreaming(false);
          cancelStream.current = null;
          snapshotDriven.current = false;
          pushToast({ kind: "error", title: "Answer interrupted", body: message });
          void loadConversation(cid, true).catch(() => undefined);
        },
      });
      cancelStream.current = cancel;
    },
    [
      activeId,
      streaming,
      patchConversation,
      pushToast,
      upsert,
      scheduleSnapshot,
      flushSnapshot,
      finishMessage,
      loadConversation,
      refreshConversations,
    ]
  );

  const stopStreaming = useCallback(() => {
    cancelStream.current?.();
    cancelStream.current = null;
    setStreaming(false);
    if (activeId) {
      finishMessage(activeId, "failed", undefined, undefined, "Generation stopped.");
      void loadConversation(activeId, true).catch(() => undefined);
    }
  }, [activeId, finishMessage, loadConversation]);

  /* ---------- thread actions ---------- */
  const selectConversation = useCallback(
    async (id: string | null) => {
      setActiveId(id);
      setView("chat");
      setSelectedSource(null);
      setMobileNav(false);
      rememberActiveThread(id);
      if (!id) return;
      try {
        await loadConversation(id);
      } catch (e) {
        pushToast({ kind: "error", title: "Could not load thread", body: errorMessage(e) });
      }
    },
    [loadConversation, pushToast]
  );

  const newChat = useCallback(() => {
    setActiveId(null);
    setView("chat");
    setSelectedSource(null);
    setMobileNav(false);
    rememberActiveThread(null);
  }, []);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        loadedAt.current.delete(id);
        setConversations((prev) => prev.filter((c) => c.id !== id));
        setActiveId((cur) => {
          if (cur === id) rememberActiveThread(null);
          return cur === id ? null : cur;
        });
        pushToast({ kind: "info", title: "Conversation deleted" });
      } catch (e) {
        pushToast({ kind: "error", title: "Could not delete conversation", body: errorMessage(e) });
      }
    },
    [pushToast]
  );

  const renameConversation = useCallback(
    async (id: string, title: string) => {
      try {
        upsert(await api.updateConversation(id, { title }));
      } catch (e) {
        pushToast({ kind: "error", title: "Could not rename thread", body: errorMessage(e) });
      }
    },
    [pushToast, upsert]
  );

  const setScope = useCallback(
    async (conversationId: string, docIds: string[]) => {
      const previous = conversations.find((c) => c.id === conversationId)?.document_scope ?? [];
      patchConversation(conversationId, (c) => ({ ...c, document_scope: docIds }));
      try {
        upsert(await api.updateConversation(conversationId, { document_scope: docIds }));
      } catch (e) {
        patchConversation(conversationId, (c) => ({ ...c, document_scope: previous }));
        pushToast({ kind: "error", title: "Could not update scope", body: errorMessage(e) });
      }
    },
    [conversations, patchConversation, pushToast, upsert]
  );

  const startScopedChat = useCallback(
    async (doc: FinDocument) => {
      try {
        const convo = await api.createConversation({
          title: `${doc.metadata.nse_symbol} · ${doc.metadata.document_type.replace(/_/g, " ")}`,
          document_scope: [doc.id],
        });
        upsert(convo);
        setActiveId(convo.id);
        rememberActiveThread(convo.id);
        setView("chat");
        setLibraryOpenDocId(null);
        setSelectedSource(null);
        pushToast({
          kind: "info",
          title: "Scoped thread created",
          body: `Retrieval is narrowed to ${doc.metadata.company_name}.`,
        });
      } catch (e) {
        pushToast({ kind: "error", title: "Could not create thread", body: errorMessage(e) });
      }
    },
    [pushToast, upsert]
  );

  /* ---------- health / boot ---------- */
  const checkHealth = useCallback(async () => {
    try {
      const { data, latency } = await api.health();
      setHealth({ status: data.status, latency });
    } catch {
      setHealth({ status: "down", latency: 0 });
    }
  }, []);

  const boot = useCallback(async () => {
    const [threads] = await Promise.all([
      refreshConversations().catch(() => [] as Conversation[]),
      refreshDocuments(),
      checkHealth(),
    ]);
    const saved = readActiveThread();
    if (saved && threads.some((c) => c.id === saved)) {
      setActiveId(saved);
      await loadConversation(saved, true).catch(() => undefined);
    } else if (saved) {
      rememberActiveThread(null);
    }
    setBooted(true);
  }, [checkHealth, loadConversation, refreshConversations, refreshDocuments]);

  useEffect(
    () => () => {
      pollers.current.forEach((timer) => window.clearTimeout(timer));
      if (snapshotFrame.current !== null) window.cancelAnimationFrame(snapshotFrame.current);
    },
    []
  );

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
    retryDocument,
    uploading,
    libraryOpenDocId,
    setLibraryOpenDocId,
    conversations,
    refreshConversations,
    activeId,
    active,
    selectConversation,
    newChat,
    deleteConversation,
    renameConversation,
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
