/**
 * fincite API facade
 * ------------------
 * `MockTransport` remains an explicit demo mode. `RealTransport` in
 * `transport.ts` speaks the M1 contract (fetch, POST SSE, PATCH, thread list).
 * `wire.ts` is the only place DTOs are translated to UI domain objects.
 *
 *   VITE_USE_MOCK=1  → in-memory demo transport (default off)
 *   VITE_USE_MOCK=0  → real backend (also the default)
 *
 * `VITE_API_URL` defaults to "" (same origin), so the Vite dev proxy and a
 * production reverse proxy work without baking a host into the single-file build.
 */
import type {
  ChatMessage,
  Conversation,
  ConversationCreate,
  ConversationUpdate,
  DocumentUploadMetadata,
  DocumentUploadResponse,
  FinDocument,
  HealthResponse,
  MessageSubProcess,
  Source,
  UploadableFile,
} from "./types";
import { ANSWER_BANK, FALLBACK_EXCERPT, SEED_DOCUMENTS, type CannedAnswer } from "./mockData";
import { nowIso, uid } from "./format";
import {
  BASE_URL,
  RealTransport,
  createSnapshotAdapter,
  type ApiTransport,
  type StreamHandlers,
} from "./transport";

export { BASE_URL };
export type { StreamHandlers };

const env = (import.meta as unknown as { env?: Record<string, string | boolean> }).env ?? {};

function resolveUseMock(): boolean {
  const raw = env.VITE_USE_MOCK;
  return raw === true || raw === "1" || String(raw ?? "").toLowerCase() === "true";
}

/** Real API is the default; demo data requires an explicit opt-in. */
export const USE_MOCK = resolveUseMock();

/** URL of the backend-proxied original PDF, opened at a cited page. */
export function documentFileUrl(documentId: string, page: number): string {
  return `${BASE_URL}/api/document/${encodeURIComponent(documentId)}/file#page=${Math.max(1, page)}`;
}

/* ================================================================== */
/*  MOCK TRANSPORT (explicit demo mode)                                */
/* ================================================================== */

interface PipelineState {
  doc: FinDocument;
  startedAt: number;
}

const STAGE_MS: Record<string, number> = {
  parsing: 1500,
  chunking: 1700,
  embedding: 1600,
  indexing: 1300,
};

class MockTransport implements ApiTransport {
  documents: FinDocument[];
  pipelines = new Map<string, PipelineState>();
  conversations = new Map<string, Conversation>();

  constructor() {
    this.documents = SEED_DOCUMENTS.map((d) => ({ ...d }));
  }

  health(latencyMs = 20): Promise<{ data: HealthResponse; latency: number }> {
    return this.delay(180).then(() => ({
      data: { status: "healthy" },
      latency: Math.max(8, Math.round(latencyMs + Math.random() * 24)),
    }));
  }

  listDocuments(): Promise<FinDocument[]> {
    return this.delay(320).then(() => this.documents.map((d) => this.refresh(d)));
  }

  getDocument(id: string): Promise<FinDocument> {
    return this.delay(140).then(() => {
      const doc = this.documents.find((d) => d.id === id);
      if (!doc) throw new Error("Document not found");
      return this.refresh(doc);
    });
  }

  /** advance a document's simulated indexing pipeline based on elapsed time */
  private refresh(doc: FinDocument): FinDocument {
    const pipe = this.pipelines.get(doc.id);
    if (!pipe || doc.status === "ready" || doc.status === "failed") return { ...doc };
    const elapsed = Date.now() - pipe.startedAt;
    const stages = Object.keys(STAGE_MS);
    let acc = 0;
    for (const s of stages) {
      acc += STAGE_MS[s];
      if (elapsed < acc) {
        const stageStart = acc - STAGE_MS[s];
        doc.status = s as FinDocument["status"];
        doc.progress = Math.round(((elapsed - stageStart) / STAGE_MS[s]) * 100);
        return { ...doc };
      }
    }
    doc.status = "ready";
    doc.progress = 100;
    this.pipelines.delete(doc.id);
    return { ...doc };
  }

  uploadDocument(
    file: UploadableFile,
    onProgress: (pct: number) => void,
    metadata: DocumentUploadMetadata = {}
  ): { promise: Promise<DocumentUploadResponse>; cancel: () => void } {
    let cancelled = false;
    const timers: number[] = [];
    const promise = new Promise<DocumentUploadResponse>((resolve, reject) => {
      if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
        reject(new Error("Only PDF filings are supported"));
        return;
      }
      let pct = 0;
      const tick = () => {
        if (cancelled) return reject(new Error("cancelled"));
        pct = Math.min(100, pct + 4 + Math.random() * 9);
        onProgress(Math.round(pct));
        if (pct >= 100) {
          const id = uid("doc");
          const pretty = file.name.replace(/\.pdf$/i, "").replace(/[-_]+/g, " ");
          const doc: FinDocument = {
            id,
            filename: file.name,
            status: "parsing",
            progress: 0,
            uploaded_at: nowIso(),
            metadata: {
              company_name: metadata.company_name ?? titleCase(pretty.split(" ").slice(0, 3).join(" ")),
              nse_symbol: metadata.company_symbol ?? guessSymbol(file.name),
              document_type: metadata.document_type ?? guessType(file.name),
              fiscal_year: metadata.financial_year ?? "FY2024-25",
              period: "Unclassified",
              pages: 40 + Math.floor(Math.random() * 220),
              file_size: file.size,
              language: "en",
            },
          };
          this.documents.unshift(doc);
          this.pipelines.set(id, { doc, startedAt: Date.now() });
          resolve({ document: { ...doc } });
          return;
        }
        timers.push(window.setTimeout(tick, 110 + Math.random() * 90));
      };
      timers.push(window.setTimeout(tick, 200));
    });
    return {
      promise,
      cancel: () => {
        cancelled = true;
        timers.forEach(clearTimeout);
      },
    };
  }

  async reindexDocument(id: string): Promise<DocumentUploadResponse> {
    const doc = this.documents.find((d) => d.id === id);
    if (!doc) throw new Error("Document not found");
    doc.status = "parsing";
    doc.progress = 0;
    doc.error = null;
    this.pipelines.set(id, { doc, startedAt: Date.now() });
    await this.delay(140);
    return { document: { ...doc } };
  }

  async deleteDocument(id: string): Promise<void> {
    this.documents = this.documents.filter((d) => d.id !== id);
    this.pipelines.delete(id);
  }

  /* -------- conversations -------- */
  createConversation(body: ConversationCreate): Promise<Conversation> {
    return this.delay(160).then(() => {
      const convo: Conversation = {
        id: uid("conv"),
        title: body.title,
        document_scope: body.document_scope ?? [],
        messages: [],
        created_at: nowIso(),
        updated_at: nowIso(),
        message_count: 0,
      };
      this.conversations.set(convo.id, convo);
      return cloneConversation(convo);
    });
  }

  listConversations(): Promise<Conversation[]> {
    return this.delay(120).then(() =>
      [...this.conversations.values()].map(cloneConversation).sort(byUpdatedAt)
    );
  }

  getConversation(id: string): Promise<Conversation> {
    return this.delay(120).then(() => {
      const c = this.conversations.get(id);
      if (!c) throw new Error("Conversation not found");
      return cloneConversation(c);
    });
  }

  updateConversation(id: string, body: ConversationUpdate): Promise<Conversation> {
    return this.delay(100).then(() => {
      const c = this.conversations.get(id);
      if (!c) throw new Error("Conversation not found");
      if (body.title !== undefined) c.title = body.title;
      if (body.document_scope !== undefined) c.document_scope = [...body.document_scope];
      c.updated_at = nowIso();
      return cloneConversation(c);
    });
  }

  deleteConversation(id: string): Promise<void> {
    return this.delay(140).then(() => void this.conversations.delete(id));
  }

  /* -------- message streaming -------- */
  streamMessage(conversationId: string, question: string, h: StreamHandlers): () => void {
    const timers: number[] = [];
    let cancelled = false;
    const after = (ms: number, fn: () => void) =>
      timers.push(window.setTimeout(() => !cancelled && fn(), ms));
    const start = Date.now();

    const convo =
      this.conversations.get(conversationId) ??
      ({
        id: conversationId,
        title: question.slice(0, 80),
        document_scope: [],
        messages: [],
        created_at: nowIso(),
        updated_at: nowIso(),
      } satisfies Conversation);
    this.conversations.set(conversationId, convo);
    const scoped = this.scopedDocs(convo);
    const canned = this.pickAnswer(question, scoped);

    const userMsg: ChatMessage = {
      id: uid("msg"),
      conversation_id: conversationId,
      role: "user",
      content: question,
      status: "completed",
      sub_processes: [],
      sources: [],
      created_at: nowIso(),
    };
    const steps: MessageSubProcess[] = canned.plan.map((p) => ({
      id: uid("sp"),
      name: p.name,
      source: p.source,
      status: "pending",
    }));
    let assistant: ChatMessage = {
      id: uid("msg"),
      conversation_id: conversationId,
      role: "assistant",
      content: "",
      status: "processing",
      sub_processes: steps.map((s) => ({ ...s })),
      sources: [],
      created_at: nowIso(),
    };

    convo.messages = [...convo.messages, userMsg, assistant];
    convo.updated_at = userMsg.created_at;
    convo.message_count = convo.messages.length;
    h.onUserMessage({ ...userMsg });

    const adapter = createSnapshotAdapter(h);
    const sync = (next: ChatMessage) => {
      assistant = {
        ...next,
        sub_processes: next.sub_processes.map((s) => ({ ...s })),
        sources: next.sources.map((s) => ({ ...s })),
      };
      const stored = this.conversations.get(conversationId);
      if (stored) {
        const index = stored.messages.findIndex((m) => m.id === assistant.id);
        if (index >= 0) stored.messages[index] = { ...assistant };
        else stored.messages.push({ ...assistant });
        stored.updated_at = nowIso();
        stored.message_count = stored.messages.length;
      }
      adapter.snapshot({ ...assistant });
    };

    after(0, () => sync(assistant));

    let t = 260;
    steps.forEach((_, i) => {
      const dur = canned.plan[i].duration_ms || 400;
      after(t, () => {
        steps[i] = { ...steps[i], status: "running" };
        sync({ ...assistant, sub_processes: [...steps] });
      });
      after(t + dur, () => {
        steps[i] = {
          ...steps[i],
          status: "completed",
          duration_ms: dur,
          detail: canned.plan[i].detail,
        };
        sync({ ...assistant, sub_processes: [...steps] });
      });
      t += dur;
    });

    after(t + 60, () => {
      steps[steps.length - 1] = { ...steps[steps.length - 1], status: "running" };
      sync({ ...assistant, sub_processes: [...steps] });
    });

    const tokens = canned.answer.match(/\S+\s*/g) ?? [canned.answer];
    let i = 0;
    const synthStart = t + 60;
    const emit = () => {
      if (cancelled) return;
      const burst = 1 + Math.floor(Math.random() * 2);
      const chunk = tokens.slice(i, i + burst).join("");
      i += burst;
      sync({ ...assistant, status: "streaming", content: assistant.content + chunk });
      if (i < tokens.length) {
        timers.push(window.setTimeout(emit, 12 + Math.random() * 26));
        return;
      }
      const synthMs = Date.now() - start - synthStart;
      steps[steps.length - 1] = {
        ...steps[steps.length - 1],
        status: "completed",
        duration_ms: Math.max(600, synthMs),
        detail: `Grounded generation · cited ${canned.sources.length} sources`,
      };
      const sources: Source[] = canned.sources.map((s, idx) => ({
        index: idx + 1,
        document_id: s.doc_id,
        page: s.page,
        excerpt: s.excerpt,
        score: s.score,
      }));
      const final: ChatMessage = {
        ...assistant,
        status: "completed",
        content: canned.answer,
        sub_processes: [...steps],
        sources,
      };
      sync(final);
      h.onDone({ content: canned.answer, sources });
    };
    after(synthStart, emit);

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }

  private scopedDocs(convo?: Conversation | null): FinDocument[] {
    const ready = this.documents.filter((d) => d.status === "ready");
    if (!convo || convo.document_scope.length === 0) return ready;
    const scoped = ready.filter((d) => convo.document_scope.includes(d.id));
    return scoped.length ? scoped : ready;
  }

  private pickAnswer(question: string, scope: FinDocument[]): CannedAnswer {
    const hit = ANSWER_BANK.find((a) => a.patterns.some((p) => p.test(question)));
    if (hit) return hit;
    const pool = scope.filter((d) => FALLBACK_EXCERPT[d.id]).slice(0, 2);
    const refs = pool.length ? pool : this.documents.slice(0, 2);
    const cites = refs
      .map((d, i) => {
        const f = FALLBACK_EXCERPT[d.id];
        return f
          ? `${d.metadata.company_name} states in its ${d.metadata.fiscal_year} ${
              d.metadata.document_type === "annual_report" ? "annual report" : "filing"
            } that “${f.excerpt.split(". ")[0]}.” [${i + 1}]`
          : "";
      })
      .filter(Boolean)
      .join("\n\n");
    return {
      id: "fallback",
      patterns: [],
      plan: [
        { name: "Query understanding", source: "llm", duration_ms: 590, detail: "Rewrote question · resolved entities" },
        { name: "Hybrid retrieval", source: "retrieval", duration_ms: 1050, detail: `${refs.length * 6} chunks from ${refs.length} document${refs.length > 1 ? "s" : ""}` },
        { name: "Rerank", source: "rerank", duration_ms: 690, detail: "Cross-encoder kept top 4 passages" },
        { name: "Answer synthesis", source: "llm", duration_ms: 0, detail: "Grounded generation" },
      ],
      answer: `The corpus does not contain a dedicated passage that directly answers this, so here is the closest grounded context I retrieved [1]:\n\n${cites}\n\nIf you can point me at a specific company, period or metric — or upload the relevant filing — I can retrieve a sharper, fully-cited answer.`,
      sources: refs.map((d, i) => {
        const f = FALLBACK_EXCERPT[d.id] ?? { page: 1, excerpt: d.filename };
        return { doc_id: d.id, page: f.page, excerpt: f.excerpt, score: 0.61 - i * 0.04 };
      }),
    };
  }

  private delay(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }
}

function cloneConversation(conversation: Conversation): Conversation {
  return {
    ...conversation,
    document_scope: [...conversation.document_scope],
    messages: conversation.messages.map((message) => ({
      ...message,
      sub_processes: message.sub_processes.map((step) => ({ ...step })),
      sources: message.sources.map((source) => ({ ...source })),
    })),
    message_count: conversation.message_count ?? conversation.messages.length,
  };
}

function byUpdatedAt(a: Conversation, b: Conversation): number {
  return +new Date(b.updated_at) - +new Date(a.updated_at);
}

function titleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
}

function guessSymbol(name: string): string {
  const n = name.toLowerCase();
  for (const sym of ["reliance", "tcs", "hdfc", "infosys", "infy", "itc", "bajaj", "tata"]) {
    if (n.includes(sym)) {
      if (sym === "infosys" || sym === "infy") return "INFY";
      if (sym === "hdfc") return "HDFCBANK";
      if (sym === "bajaj") return "BAJFINANCE";
      if (sym === "tata") return "TATAMOTORS";
      return sym.toUpperCase();
    }
  }
  return "UNLISTED";
}

function guessType(name: string): FinDocument["metadata"]["document_type"] {
  const n = name.toLowerCase();
  if (n.includes("annual")) return "annual_report";
  if (n.includes("transcript") || n.includes("concall") || n.includes("call")) return "concall_transcript";
  if (n.includes("presentation") || n.includes("deck")) return "investor_presentation";
  if (n.includes("shareholding")) return "shareholding_pattern";
  if (n.match(/q[1-4]|quarter|result/)) return "quarterly_results";
  return "corporate_announcement";
}

/* ------------------------------------------------------------------ */

const mock = new MockTransport();
const real = new RealTransport();

export const api = {
  health: () => (USE_MOCK ? mock.health(performance.now() % 30) : real.health()),
  listDocuments: () => (USE_MOCK ? mock.listDocuments() : real.listDocuments()),
  getDocument: (id: string) => (USE_MOCK ? mock.getDocument(id) : real.getDocument(id)),
  uploadDocument: (file: UploadableFile, onProgress: (pct: number) => void, metadata?: DocumentUploadMetadata) =>
    USE_MOCK ? mock.uploadDocument(file, onProgress, metadata) : real.uploadDocument(file, onProgress, metadata),
  reindexDocument: (id: string) => (USE_MOCK ? mock.reindexDocument(id) : real.reindexDocument(id)),
  deleteDocument: (id: string) => (USE_MOCK ? mock.deleteDocument(id) : real.deleteDocument(id)),
  listConversations: () => (USE_MOCK ? mock.listConversations() : real.listConversations()),
  createConversation: (body: ConversationCreate) =>
    USE_MOCK ? mock.createConversation(body) : real.createConversation(body),
  getConversation: (id: string) => (USE_MOCK ? mock.getConversation(id) : real.getConversation(id)),
  updateConversation: (id: string, body: ConversationUpdate) =>
    USE_MOCK ? mock.updateConversation(id, body) : real.updateConversation(id, body),
  deleteConversation: (id: string) => (USE_MOCK ? mock.deleteConversation(id) : real.deleteConversation(id)),
  streamMessage: (conversationId: string, question: string, h: StreamHandlers) =>
    USE_MOCK ? mock.streamMessage(conversationId, question, h) : real.streamMessage(conversationId, question, h),
};
