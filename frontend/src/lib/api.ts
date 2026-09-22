/**
 * fincite API client
 * ------------------
 * Mirrors the FastAPI backend contract exactly:
 *
 *   GET    /api/health/
 *   POST   /api/conversation/
 *   GET    /api/conversation/{id}
 *   DELETE /api/conversation/{id}
 *   GET    /api/conversation/{id}/message          (streamed answer)
 *   GET    /api/conversation/{id}/test_message
 *   POST   /api/document/upload
 *   GET    /api/document/
 *   GET    /api/document/{id}
 *
 * Set USE_MOCK = false (and VITE_API_URL) to talk to the real backend.
 */

import type {
  ChatMessage,
  Conversation,
  ConversationCreate,
  DocumentUploadResponse,
  FinDocument,
  HealthResponse,
  MessageSubProcess,
  Source,
} from "./types";
import { ANSWER_BANK, FALLBACK_EXCERPT, SEED_DOCUMENTS, type CannedAnswer } from "./mockData";
import { nowIso, uid } from "./format";

export const USE_MOCK = true;
export const BASE_URL: string =
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_URL ??
  "http://localhost:8000";

/* ------------------------------------------------------------------ */
/*  Streaming handler contract                                         */
/* ------------------------------------------------------------------ */

export interface StreamHandlers {
  onUserMessage: (msg: ChatMessage) => void;
  onAssistantCreated: (msg: ChatMessage) => void;
  onSubProcess: (stepId: string, patch: Partial<MessageSubProcess>) => void;
  onToken: (token: string) => void;
  onDone: (result: { content: string; sources: Source[] }) => void;
  onError: (message: string) => void;
}

/* ================================================================== */
/*  MOCK TRANSPORT                                                     */
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

class MockTransport {
  documents: FinDocument[];
  pipelines = new Map<string, PipelineState>();
  conversations = new Map<string, Conversation>();

  constructor() {
    this.documents = SEED_DOCUMENTS.map((d) => ({ ...d }));
  }

  /* -------- health -------- */
  health(latencyMs: number): Promise<{ data: HealthResponse; latency: number }> {
    return this.delay(180).then(() => ({
      data: { status: "healthy" },
      latency: Math.max(8, Math.round(latencyMs + Math.random() * 24)),
    }));
  }

  /* -------- documents -------- */
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
    file: { name: string; size: number; type: string },
    onProgress: (pct: number) => void
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
              company_name: titleCase(pretty.split(" ").slice(0, 3).join(" ")),
              nse_symbol: guessSymbol(file.name),
              document_type: guessType(file.name),
              fiscal_year: "FY2024-25",
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
    return { promise, cancel: () => { cancelled = true; timers.forEach(clearTimeout); } };
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
      };
      this.conversations.set(convo.id, convo);
      return { ...convo };
    });
  }

  getConversation(id: string): Promise<Conversation> {
    return this.delay(120).then(() => {
      const c = this.conversations.get(id);
      if (!c) throw new Error("Conversation not found");
      return { ...c };
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

    const convo = this.conversations.get(conversationId);
    const scoped = this.scopedDocs(convo);

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

    const canned = this.pickAnswer(question, scoped);
    const steps: MessageSubProcess[] = canned.plan.map((p, i) => ({
      id: uid("sp"),
      name: p.name,
      source: p.source,
      status: i === 0 ? "pending" : "pending",
    }));

    const assistant: ChatMessage = {
      id: uid("msg"),
      conversation_id: conversationId,
      role: "assistant",
      content: "",
      status: "processing",
      sub_processes: steps,
      sources: [],
      created_at: nowIso(),
    };

    // 1. user message lands immediately
    after(0, () => h.onUserMessage(userMsg));

    // 2. assistant placeholder, then walk the sub-process plan
    after(240, () => {
      h.onAssistantCreated(assistant);
      let t = 260;
      steps.forEach((step, i) => {
        const dur = canned.plan[i].duration_ms || 400;
        after(t, () => h.onSubProcess(step.id, { status: "running" }));
        after(t + dur, () =>
          h.onSubProcess(step.id, {
            status: "completed",
            duration_ms: dur,
            detail: canned.plan[i].detail,
          })
        );
        t += dur;
      });

      // 3. synthesis streams tokens
      after(t + 60, () => h.onSubProcess(steps[steps.length - 1].id, { status: "running" }));
      const tokens = canned.answer.match(/\S+\s*/g) ?? [canned.answer];
      let i = 0;
      const synthStart = t + 60;
      const emit = () => {
        if (cancelled) return;
        const burst = 1 + Math.floor(Math.random() * 2);
        const chunk = tokens.slice(i, i + burst).join("");
        i += burst;
        h.onToken(chunk);
        if (i < tokens.length) {
          timers.push(window.setTimeout(emit, 12 + Math.random() * 26));
          return;
        }
        const synthMs = Date.now() - start - synthStart;
        h.onSubProcess(steps[steps.length - 1].id, {
          status: "completed",
          duration_ms: Math.max(600, synthMs),
          detail: `Grounded generation · cited ${canned.sources.length} sources`,
        });
        h.onDone({
          content: canned.answer,
          sources: canned.sources.map((s, idx) => ({
            index: idx + 1,
            document_id: s.doc_id,
            page: s.page,
            excerpt: s.excerpt,
            score: s.score,
          })),
        });
      };
      after(t + 60, emit);
    });

    const start = Date.now();
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
    // generic grounded fallback across the scoped corpus
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

/* ================================================================== */
/*  REAL TRANSPORT (swap-in when the FastAPI server is running)        */
/* ================================================================== */

class RealTransport {
  async health() {
    const t = performance.now();
    const res = await fetch(`${BASE_URL}/api/health/`);
    return { data: (await res.json()) as HealthResponse, latency: Math.round(performance.now() - t) };
  }
  async listDocuments(): Promise<FinDocument[]> {
    const res = await fetch(`${BASE_URL}/api/document/`);
    return res.json();
  }
  async getDocument(id: string): Promise<FinDocument> {
    const res = await fetch(`${BASE_URL}/api/document/${id}`);
    return res.json();
  }
  uploadDocument(file: File, onProgress: (pct: number) => void) {
    const xhr = new XMLHttpRequest();
    const promise = new Promise<DocumentUploadResponse>((resolve, reject) => {
      xhr.open("POST", `${BASE_URL}/api/document/upload`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
      xhr.onload = () => resolve(JSON.parse(xhr.responseText));
      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.send(Object.assign(new FormData(), { file }));
    });
    return { promise, cancel: () => xhr.abort() };
  }
  async createConversation(body: ConversationCreate): Promise<Conversation> {
    const res = await fetch(`${BASE_URL}/api/conversation/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.json();
  }
  async getConversation(id: string): Promise<Conversation> {
    const res = await fetch(`${BASE_URL}/api/conversation/${id}`);
    return res.json();
  }
  async deleteConversation(id: string): Promise<void> {
    await fetch(`${BASE_URL}/api/conversation/${id}`, { method: "DELETE" });
  }
  /** SSE stream — adjust event names to the backend's emitter */
  streamMessage(conversationId: string, question: string, h: StreamHandlers): () => void {
    const es = new EventSource(
      `${BASE_URL}/api/conversation/${conversationId}/message?q=${encodeURIComponent(question)}`
    );
    let acc = "";
    es.addEventListener("sub_process", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      h.onSubProcess(d.id, d);
    });
    es.addEventListener("delta", (e) => {
      const t = (e as MessageEvent).data;
      acc += t;
      h.onToken(t);
    });
    es.addEventListener("done", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      h.onDone({ content: acc, sources: d.sources ?? [] });
      es.close();
    });
    es.onerror = () => {
      h.onError("Stream interrupted");
      es.close();
    };
    return () => es.close();
  }
}

/* ------------------------------------------------------------------ */

const mock = new MockTransport();

export const api = {
  health: () => (USE_MOCK ? mock.health(performance.now() % 30) : new RealTransport().health()),
  listDocuments: () => (USE_MOCK ? mock.listDocuments() : new RealTransport().listDocuments()),
  getDocument: (id: string) => (USE_MOCK ? mock.getDocument(id) : new RealTransport().getDocument(id)),
  uploadDocument: (file: File | { name: string; size: number; type: string }, onProgress: (pct: number) => void) =>
    USE_MOCK
      ? mock.uploadDocument(file, onProgress)
      : new RealTransport().uploadDocument(file as File, onProgress),
  createConversation: (body: ConversationCreate) =>
    USE_MOCK ? mock.createConversation(body) : new RealTransport().createConversation(body),
  getConversation: (id: string) => (USE_MOCK ? mock.getConversation(id) : new RealTransport().getConversation(id)),
  deleteConversation: (id: string) => (USE_MOCK ? mock.deleteConversation(id) : new RealTransport().deleteConversation(id)),
  streamMessage: (conversationId: string, question: string, h: StreamHandlers) =>
    USE_MOCK ? mock.streamMessage(conversationId, question, h) : new RealTransport().streamMessage(conversationId, question, h),
};
