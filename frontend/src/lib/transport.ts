/**
 * M2 real API transport.
 *
 * Uses `fetch` throughout. The message endpoint is POST + SSE: each unnamed
 * frame is a complete `Message` snapshot from `backend/app/schema.py`, never a
 * token delta. The adapter below turns snapshots back into the legacy stream
 * callbacks as well, so demo mode and real mode share one UI code path.
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
import {
  ApiError,
  toApiError,
  toChatMessage,
  toConversation,
  toConversationCreate,
  toConversationUpdate,
  toDocumentUploadResponse,
  toFinDocument,
  toHealthResponse,
  type ApiConversation,
  type ApiDocument,
  type ApiMessage,
} from "./wire";
import { uid } from "./format";

const rawEnv = (import.meta as unknown as { env?: Record<string, string | boolean> }).env ?? {};

/** Same-origin by default; the Vite dev proxy and prod reverse proxy handle /api. */
export const BASE_URL = String(rawEnv.VITE_API_URL ?? "").replace(/\/$/, "");

export interface StreamHandlers {
  onUserMessage: (msg: ChatMessage) => void;
  onAssistantCreated: (msg: ChatMessage) => void;
  onSubProcess: (stepId: string, patch: Partial<MessageSubProcess>) => void;
  onToken: (token: string) => void;
  onDone: (result: { content: string; sources: Source[] }) => void;
  onError: (message: string) => void;
  /** Preferred M2 callback: replace the assistant message with a full snapshot. */
  onSnapshot?: (message: ChatMessage) => void;
}

export interface ApiTransport {
  health(latencyMs?: number): Promise<{ data: HealthResponse; latency: number }>;
  listDocuments(): Promise<FinDocument[]>;
  getDocument(id: string): Promise<FinDocument>;
  uploadDocument(
    file: UploadableFile,
    onProgress: (pct: number) => void,
    metadata?: DocumentUploadMetadata
  ): { promise: Promise<DocumentUploadResponse>; cancel: () => void };
  reindexDocument(id: string): Promise<DocumentUploadResponse>;
  deleteDocument(id: string): Promise<void>;
  listConversations(): Promise<Conversation[]>;
  createConversation(body: ConversationCreate): Promise<Conversation>;
  getConversation(id: string): Promise<Conversation>;
  updateConversation(id: string, body: ConversationUpdate): Promise<Conversation>;
  deleteConversation(id: string): Promise<void>;
  streamMessage(conversationId: string, question: string, handlers: StreamHandlers): () => void;
}

export interface SseFrame {
  data: string;
  event?: string;
  id?: string;
}

/** Parse one SSE event block (named or unnamed); comments/pings return null. */
export function parseSseFrame(block: string): SseFrame | null {
  const data: string[] = [];
  let event: string | undefined;
  let id: string | undefined;
  for (const line of block.split(/\r\n|\n|\r/)) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") data.push(value);
    else if (field === "event") event = value;
    else if (field === "id") id = value;
  }
  return data.length ? { data: data.join("\n"), event, id } : null;
}

/** Consume every complete event in `buffer` and return the unterminated tail. */
export function consumeSseFrames(buffer: string, onFrame: (frame: SseFrame) => void, final = false): string {
  let rest = buffer;
  const boundary = /\r\n\r\n|\n\n|\r\r/;
  let match = boundary.exec(rest);
  while (match) {
    const block = rest.slice(0, match.index);
    rest = rest.slice(match.index + match[0].length);
    const frame = parseSseFrame(block);
    if (frame) onFrame(frame);
    match = boundary.exec(rest);
  }
  if (final && rest.trim()) {
    const frame = parseSseFrame(rest);
    if (frame) onFrame(frame);
    return "";
  }
  return rest;
}

/**
 * Translate cumulative `Message` snapshots into the original callback stream.
 * Stores that implement `onSnapshot` can ignore the legacy callbacks safely.
 */
export function createSnapshotAdapter(handlers: StreamHandlers): {
  snapshot: (message: ChatMessage) => void;
  reset: () => void;
} {
  let previous: ChatMessage | undefined;
  return {
    reset: () => {
      previous = undefined;
    },
    snapshot: (message) => {
      handlers.onSnapshot?.(message);
      if (!previous) {
        handlers.onAssistantCreated(message);
        for (const step of message.sub_processes) handlers.onSubProcess(step.id, step);
      } else {
        // Backend content is cumulative. Never append a snapshot that rewound.
        if (message.content.startsWith(previous.content)) {
          const delta = message.content.slice(previous.content.length);
          if (delta) handlers.onToken(delta);
        }
        const oldSteps = new Map(previous.sub_processes.map((step) => [step.id, step]));
        for (const step of message.sub_processes) {
          const old = oldSteps.get(step.id);
          if (!old || JSON.stringify(old) !== JSON.stringify(step)) handlers.onSubProcess(step.id, step);
        }
      }
      previous = message;
    },
  };
}

function url(path: string, base = BASE_URL): string {
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

async function readPayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export class RealTransport implements ApiTransport {
  constructor(private readonly baseUrl: string = BASE_URL) {}

  private async requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(url(path, this.baseUrl), {
        ...init,
        headers: { Accept: "application/json", ...(init?.headers as Record<string, string> | undefined) },
      });
    } catch (error) {
      throw toApiError(error, undefined, "Backend unreachable");
    }
    if (!response.ok) {
      throw toApiError(response.status, await readPayload(response), `Request failed (${response.status})`);
    }
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    if (!text) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError(response.status, "The backend returned an invalid JSON response.", true);
    }
  }

  async health(): Promise<{ data: HealthResponse; latency: number }> {
    const started = Date.now();
    const data = toHealthResponse(await this.requestJson<unknown>("/api/health/"));
    return { data, latency: Math.max(1, Date.now() - started) };
  }

  async listDocuments(): Promise<FinDocument[]> {
    const docs = await this.requestJson<ApiDocument[]>("/api/document/");
    return (Array.isArray(docs) ? docs : []).map(toFinDocument);
  }

  async getDocument(id: string): Promise<FinDocument> {
    return toFinDocument(await this.requestJson<ApiDocument>(`/api/document/${encodeURIComponent(id)}`));
  }

  uploadDocument(
    file: UploadableFile,
    onProgress: (pct: number) => void,
    metadata: DocumentUploadMetadata = {}
  ): { promise: Promise<DocumentUploadResponse>; cancel: () => void } {
    const xhr = new XMLHttpRequest();
    const promise = new Promise<DocumentUploadResponse>((resolve, reject) => {
      const maybeBlob =
        typeof Blob !== "undefined" && file instanceof Blob
          ? file
          : typeof (file as unknown as { arrayBuffer?: unknown }).arrayBuffer === "function"
            ? (file as unknown as Blob)
            : null;
      if (!maybeBlob) {
        reject(new ApiError(0, "Choose a real PDF file to upload.", false));
        return;
      }

      const form = new FormData();
      form.append("file", maybeBlob, file.name);
      for (const key of [
        "company_name",
        "company_symbol",
        "financial_year",
        "document_type",
        "exchange",
      ] as const) {
        const value = metadata[key];
        if (value !== undefined && value !== "") form.append(key, String(value));
      }

      xhr.open("POST", url("/api/document/upload", this.baseUrl));
      xhr.setRequestHeader("Accept", "application/json");
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
      };
      xhr.onload = () => {
        let payload: unknown = null;
        try {
          payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
        } catch {
          payload = xhr.responseText;
        }
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(toApiError(xhr.status, payload, "Upload failed"));
          return;
        }
        onProgress(100);
        resolve(toDocumentUploadResponse((payload ?? {}) as ApiDocument));
      };
      xhr.onerror = () => reject(new ApiError(0, "Upload failed", true));
      xhr.onabort = () => reject(new ApiError(0, "Upload cancelled", false));
      xhr.send(form);
    });
    return { promise, cancel: () => xhr.abort() };
  }

  async reindexDocument(id: string): Promise<DocumentUploadResponse> {
    return toDocumentUploadResponse(
      await this.requestJson<ApiDocument>(`/api/document/${encodeURIComponent(id)}/reindex`, { method: "POST" })
    );
  }

  async deleteDocument(id: string): Promise<void> {
    await this.requestJson<void>(`/api/document/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  async listConversations(): Promise<Conversation[]> {
    const rows = await this.requestJson<unknown[]>("/api/conversation/?limit=200");
    return (Array.isArray(rows) ? rows : []).map((row) => toConversation((row ?? {}) as ApiConversation));
  }

  async createConversation(body: ConversationCreate): Promise<Conversation> {
    const dto = await this.requestJson<ApiConversation>("/api/conversation/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toConversationCreate(body)),
    });
    return toConversation(dto);
  }

  async getConversation(id: string): Promise<Conversation> {
    return toConversation(await this.requestJson<ApiConversation>(`/api/conversation/${encodeURIComponent(id)}`));
  }

  async updateConversation(id: string, body: ConversationUpdate): Promise<Conversation> {
    const dto = await this.requestJson<ApiConversation>(`/api/conversation/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toConversationUpdate(body)),
    });
    return toConversation(dto);
  }

  async deleteConversation(id: string): Promise<void> {
    await this.requestJson<void>(`/api/conversation/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  private async rehydrateLastAssistant(
    conversationId: string,
    lastEventId?: string
  ): Promise<ChatMessage | null> {
    try {
      const dto = await this.requestJson<ApiConversation>(
        `/api/conversation/${encodeURIComponent(conversationId)}`,
        { headers: lastEventId ? { "Last-Event-ID": lastEventId } : undefined }
      );
      const conversation = toConversation(dto);
      const assistants = conversation.messages.filter((message) => message.role === "assistant");
      return assistants.length ? assistants[assistants.length - 1] : null;
    } catch {
      return null;
    }
  }

  streamMessage(conversationId: string, question: string, handlers: StreamHandlers): () => void {
    const controller = new AbortController();
    const adapter = createSnapshotAdapter(handlers);
    let cancelled = false;
    let settled = false;
    let latest: ChatMessage | undefined;
    let lastEventId: string | undefined;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

    const complete = (message: ChatMessage): void => {
      if (settled || cancelled) return;
      settled = true;
      handlers.onDone({ content: message.content, sources: message.sources });
    };
    const fail = (message: string): void => {
      if (settled || cancelled) return;
      settled = true;
      handlers.onError(message);
    };

    const processFrame = (frame: SseFrame): void => {
      if (frame.id) lastEventId = frame.id;
      if (settled || cancelled || frame.event === "ping") return;
      let snapshot: ApiMessage;
      try {
        snapshot = JSON.parse(frame.data) as ApiMessage;
      } catch {
        return; // tolerate malformed keep-alive frames
      }
      latest = toChatMessage(snapshot ?? {});
      adapter.snapshot(latest);
      if (latest.status === "completed") complete(latest);
      else if (latest.status === "failed") fail(latest.content || "The answer could not be generated.");
    };

    void (async () => {
      try {
        const response = await fetch(url(`/api/conversation/${encodeURIComponent(conversationId)}/message`, this.baseUrl), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({ content: question }),
          signal: controller.signal,
        });
        if (!response.ok) {
          fail(toApiError(response.status, await readPayload(response), "Could not send the question").message);
          return;
        }
        if (!response.body) {
          fail("The server did not return an answer stream.");
          return;
        }

        // The backend persists the user message; this local copy is only for
        // immediate UI feedback and is replaced by rehydration on completion.
        handlers.onUserMessage({
          id: uid("pending-user"),
          conversation_id: conversationId,
          role: "user",
          content: question,
          status: "completed",
          sub_processes: [],
          sources: [],
          created_at: new Date().toISOString(),
        });

        reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!cancelled && !settled) {
          const { done, value } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          buffer = consumeSseFrames(buffer, processFrame, done);
          if (done) break;
        }
        if (settled && reader) await reader.cancel().catch(() => undefined);

        if (!settled && !cancelled) {
          const recovered = await this.rehydrateLastAssistant(conversationId, lastEventId);
          if (recovered) {
            if (JSON.stringify(recovered) !== JSON.stringify(latest)) adapter.snapshot(recovered);
            if (recovered.status === "completed") complete(recovered);
            else fail("Connection lost; the saved answer was restored.");
          } else {
            fail("The answer stream ended before it completed.");
          }
        }
      } catch (error) {
        if (cancelled || settled) return;
        // One GET rehydrate (never a second POST, which would duplicate the
        // question). The backend flushes partial answers durably.
        const recovered = await this.rehydrateLastAssistant(conversationId, lastEventId);
        if (recovered) {
          if (JSON.stringify(recovered) !== JSON.stringify(latest)) adapter.snapshot(recovered);
          if (recovered.status === "completed") complete(recovered);
          else fail(toApiError(error, undefined, "Connection lost; the saved answer was restored.").message);
        } else {
          fail(toApiError(error, undefined, "The answer stream was interrupted.").message);
        }
      } finally {
        reader?.releaseLock();
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      adapter.reset();
    };
  }
}

export default RealTransport;
