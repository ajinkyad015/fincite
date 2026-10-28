/**
 * M2 wire ↔ domain mappers.
 *
 * The backend shapes are defined in `backend/app/schema.py`. This is the only
 * module allowed to know their names; every other UI module consumes the domain
 * shapes from `types.ts`. Unknown/missing fields deliberately get safe defaults
 * so an older backend or a partial SSE snapshot cannot crash the app.
 */
import type {
  ChatMessage,
  Conversation,
  ConversationCreate,
  ConversationUpdate,
  DocumentStatus,
  DocumentUploadResponse,
  FinDocument,
  HealthResponse,
  MessageStatus,
  MessageSubProcess,
  NSEDocumentType,
  Source,
  SubProcessSource,
  SubProcessStatus,
} from "./types";

type UnknownRecord = Record<string, unknown>;

export interface ApiDocument {
  id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  url?: string | null;
  metadata_map?: UnknownRecord | null;
  status?: string | null;
  progress?: number | null;
  error?: string | null;
  page_count?: number | null;
  file_size?: number | null;
  content_hash?: string | null;
  [key: string]: unknown;
}

export interface ApiSource {
  index?: number | null;
  document_id?: string | null;
  page?: number | string | null;
  page_number?: number | string | null;
  excerpt?: string | null;
  text?: string | null;
  score?: number | null;
  [key: string]: unknown;
}

export interface ApiSubProcess {
  id?: string | null;
  event_id?: string | null;
  message_id?: string | null;
  source?: string | null;
  status?: string | null;
  name?: string | null;
  detail?: string | null;
  duration_ms?: number | null;
  metadata_map?: UnknownRecord | null;
  created_at?: string | null;
  [key: string]: unknown;
}

export interface ApiMessage {
  id?: string | null;
  conversation_id?: string | null;
  role?: string | null;
  content?: string | null;
  status?: string | null;
  sub_processes?: ApiSubProcess[] | null;
  sources?: ApiSource[] | null;
  created_at?: string | null;
  updated_at?: string | null;
  [key: string]: unknown;
}

export interface ApiConversation {
  id?: string | null;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_message_at?: string | null;
  messages?: ApiMessage[] | null;
  documents?: ApiDocument[] | null;
  [key: string]: unknown;
}

export interface ApiConversationSummary {
  id?: string | null;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_message_at?: string | null;
  message_count?: number | null;
  document_ids?: Array<string | null> | null;
  preview?: string | null;
  [key: string]: unknown;
}

const FALLBACK_DATE = new Date(0).toISOString();

/** A typed API failure used by the transport and shown as friendly toast copy. */
export class ApiError extends Error {
  readonly status: number;
  readonly retryable: boolean;

  constructor(status: number, message: string, retryable?: boolean) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryable = retryable ?? (status === 0 || status === 408 || status === 429 || status >= 500);
  }
}

/** Convert FastAPI's `{detail}` (or any thrown value) into a typed error. */
export function toApiError(
  statusOrError: number | Error | unknown,
  payload?: unknown,
  fallback = "Request failed"
): ApiError {
  if (statusOrError instanceof ApiError) return statusOrError;
  if (statusOrError instanceof Error) return new ApiError(0, statusOrError.message, true);
  if (typeof statusOrError !== "number") return new ApiError(0, fallback, true);

  const record = asRecord(payload);
  const detail = record.detail ?? record.message;
  let message = fallback;
  if (typeof detail === "string" && detail.trim()) message = detail.trim();
  else if (Array.isArray(detail)) {
    message = detail
      .map((item) => {
        const entry = asRecord(item);
        return firstString(entry.msg, entry.message) ?? String(item);
      })
      .join("; ");
  } else if (typeof payload === "string" && payload.trim()) {
    message = payload.trim().slice(0, 300);
  }
  return new ApiError(statusOrError, message);
}

function asRecord(value: unknown): UnknownRecord {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as UnknownRecord;
  if (typeof value === "string") {
    try {
      const parsed: unknown = JSON.parse(value);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as UnknownRecord;
    } catch {
      /* metadata is sometimes a plain string, not JSON */
    }
  }
  return {};
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return undefined;
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return undefined;
}

function iso(value: unknown, fallback = FALLBACK_DATE): string {
  const raw = firstString(value);
  return raw && !Number.isNaN(new Date(raw).getTime()) ? raw : fallback;
}

function truncate(value: string, length: number): string {
  return value.length <= length ? value : `${value.slice(0, length - 1).trimEnd()}…`;
}

function humanise(value: string): string {
  const words = value.toLowerCase().replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Processing";
}

/** `2024-25`, `FY2024-25`, `2024`, `FY24-25` → `FY2024-25`. */
export function normaliseFiscalYear(value: unknown): string {
  const original = firstString(value);
  if (!original) return "—";
  let raw = original.trim().toUpperCase().replace(/\s+/g, "");
  if (raw.startsWith("FY")) raw = raw.slice(2);
  raw = raw.replace(/\//g, "-");
  const parts = raw.split("-");
  const year = /^\d{2,4}$/;

  if (parts.length === 2 && parts.every((p) => year.test(p))) {
    const startRaw = parts[0].length === 4 ? parts[0] : `20${parts[0]}`;
    const endRaw = parts[1].length === 4 ? parts[1] : `${startRaw.slice(0, 2)}${parts[1]}`;
    return `FY${startRaw}-${endRaw.slice(-2)}`;
  }
  if (parts.length === 1 && /^\d{4}$/.test(parts[0])) {
    const start = Number(parts[0]);
    return `FY${start}-${String(start + 1).slice(-2)}`;
  }
  if (parts.length === 1 && /^\d{2}$/.test(parts[0])) {
    const start = 2000 + Number(parts[0]);
    return `FY${start}-${String(start + 1).slice(-2)}`;
  }
  return original.trim();
}

const DOCUMENT_TYPE_MAP: Record<string, NSEDocumentType> = {
  annual_report: "annual_report",
  quarterly_results: "quarterly_results",
  financial_results: "quarterly_results",
  concall_transcript: "concall_transcript",
  investor_presentation: "investor_presentation",
  shareholding_pattern: "shareholding_pattern",
  corporate_announcement: "corporate_announcement",
  corporate_filing: "corporate_announcement",
  other: "corporate_announcement",
};

const DOCUMENT_STATUS_MAP: Record<string, DocumentStatus> = {
  uploaded: "uploading",
  uploading: "uploading",
  parsing: "parsing",
  chunking: "chunking",
  embedding: "embedding",
  indexing: "indexing",
  ready: "ready",
  failed: "failed",
};

function nseMetadata(dto: ApiDocument): UnknownRecord {
  const map = asRecord(dto.metadata_map);
  return asRecord(map.nse_document ?? map.NSE_DOCUMENT ?? map.nseDocument);
}

function filenameFrom(dto: ApiDocument, metadata: UnknownRecord): string {
  const direct = firstString(
    asRecord(dto.metadata_map).original_filename,
    metadata.original_filename,
    dto.url
  );
  if (!direct) return "filing.pdf";
  try {
    const url = new URL(direct, "http://local");
    const name = url.pathname.split("/").filter(Boolean).pop();
    return name ? decodeURIComponent(name) : "filing.pdf";
  } catch {
    return direct;
  }
}

function companyFromFilename(filename: string): string {
  return filename
    .replace(/\.pdf$/i, "")
    .replace(/[-_]+/g, " ")
    .trim()
    .split(/\s+/)
    .slice(0, 4)
    .map((word) => word[0]?.toUpperCase() + word.slice(1).toLowerCase())
    .join(" ") || "Untitled filing";
}

/** Map an M1 `Document` or `DocumentUploadResponse` DTO to the UI shape. */
export function toFinDocument(dto: ApiDocument): FinDocument {
  const metadataMap = asRecord(dto.metadata_map);
  const nse = nseMetadata(dto);
  const filename = filenameFrom(dto, nse);
  const rawType = firstString(nse.document_type, metadataMap.document_type) ?? "annual_report";
  const fiscalYear = normaliseFiscalYear(firstString(nse.financial_year, metadataMap.financial_year));
  const reportDate = firstString(nse.report_date, metadataMap.report_date);
  const status = DOCUMENT_STATUS_MAP[String(dto.status ?? "uploaded").toLowerCase()] ?? "uploading";
  const progressValue = firstNumber(dto.progress) ?? (status === "ready" ? 100 : 0);

  return {
    id: firstString(dto.id) ?? "",
    filename,
    status,
    progress: Math.max(0, Math.min(100, Math.round(progressValue))),
    uploaded_at: iso(dto.created_at ?? dto.updated_at),
    url: firstString(dto.url),
    error: firstString(dto.error) ?? null,
    metadata: {
      company_name:
        firstString(nse.company_name, metadataMap.company_name) ?? companyFromFilename(filename),
      nse_symbol: firstString(nse.company_symbol, metadataMap.company_symbol, nse.nse_symbol) ?? "—",
      document_type: DOCUMENT_TYPE_MAP[rawType.toLowerCase()] ?? "corporate_announcement",
      fiscal_year: fiscalYear,
      period: firstString(metadataMap.period, reportDate) ?? fiscalYear,
      pages: firstNumber(dto.page_count, metadataMap.pages) ?? 0,
      file_size: firstNumber(dto.file_size, metadataMap.file_size) ?? 0,
      language: firstString(metadataMap.language, nse.language) ?? "en",
    },
  };
}

export function toDocumentUploadResponse(dto: ApiDocument): DocumentUploadResponse {
  return { document: toFinDocument(dto) };
}

export function toHealthResponse(dto: unknown): HealthResponse {
  const record = asRecord(dto);
  const status = firstString(record.status);
  return {
    ...(record as object),
    status: status === "degraded" ? "degraded" : "healthy",
    db: typeof record.db === "boolean" ? record.db : undefined,
  } as HealthResponse;
}

const SUB_PROCESS_SOURCE_MAP: Record<string, SubProcessSource> = {
  LLM: "llm",
  SYNTHESIZE: "llm",
  RETRIEVE: "retrieval",
  QUERY: "retrieval",
  SUB_QUESTION: "retrieval",
  RERANK: "rerank",
  RERANKING: "rerank",
  CONSTRUCTED_QUERY_ENGINE: "parser",
  CHUNKING: "parser",
  NODE_PARSING: "parser",
  PARSER: "parser",
  TREE: "parser",
};

export function toSubProcessSource(source: unknown): SubProcessSource {
  return SUB_PROCESS_SOURCE_MAP[String(source ?? "").toUpperCase()] ?? "parser";
}

/**
 * Derive a readable research-trail label from a LlamaIndex `CBEventType` and
 * its metadata. Never throws: unknown event types fall back to `parser`.
 */
export function subProcessLabel(
  source: string,
  metadata: UnknownRecord | null | undefined
): { name: string; detail: string } {
  const sourceKey = String(source ?? "").toUpperCase();
  const name =
    ({
      LLM: "Language model call",
      SYNTHESIZE: "Answer synthesis",
      RETRIEVE: "Retrieval",
      QUERY: "Query planning",
      SUB_QUESTION: "Sub-question research",
      RERANK: "Reranking",
      RERANKING: "Reranking",
      CONSTRUCTED_QUERY_ENGINE: "Query engine",
      CHUNKING: "Chunking",
      NODE_PARSING: "Document parsing",
    } as Record<string, string>)[sourceKey] ?? humanise(sourceKey || "Processing");

  const map = asRecord(metadata);
  const subQuestion = asRecord(map.sub_question ?? map.SUB_QUESTION ?? map.subQuestion);
  const citations = Array.isArray(subQuestion.citations) ? subQuestion.citations.length : 0;
  const question = firstString(subQuestion.question, subQuestion.sub_question, map.question);
  const answer = firstString(subQuestion.answer, map.answer);
  const chunks = firstNumber(map.chunks, map.num_chunks, map.chunk_count, map.nodes);
  const company = firstString(map.company, map.company_name, map.company_symbol);
  const details: string[] = [];
  if (company) details.push(company);
  if (question) details.push(truncate(question, 90));
  if (chunks != null) details.push(`${chunks} chunks`);
  if (citations) details.push(`${citations} citation${citations === 1 ? "" : "s"}`);
  if (!details.length && answer) details.push(truncate(answer, 90));
  return { name, detail: details.join(" · ") };
}

function toSubProcessStatus(status: unknown): SubProcessStatus {
  const raw = String(status ?? "").toUpperCase();
  if (raw === "FINISHED" || raw === "SUCCESS" || raw === "COMPLETED") return "completed";
  if (raw === "ERROR" || raw === "FAILED" || raw === "FAILURE") return "failed";
  if (raw === "PENDING" || raw === "RUNNING") return "running";
  return raw.toLowerCase() === "pending" || raw.toLowerCase() === "running" || raw.toLowerCase() === "completed" || raw.toLowerCase() === "failed"
    ? (raw.toLowerCase() as SubProcessStatus)
    : "pending";
}

function toSubProcess(dto: ApiSubProcess, messageId: string, index: number): MessageSubProcess {
  const source = toSubProcessSource(dto.source);
  const label = subProcessLabel(String(dto.source ?? ""), dto.metadata_map);
  return {
    id: firstString(dto.id, dto.event_id) ?? `${messageId}:${source}:${index}`,
    name: firstString(dto.name) ?? label.name,
    source,
    status: toSubProcessStatus(dto.status),
    detail: firstString(dto.detail) ?? (label.detail || undefined),
    duration_ms: firstNumber(dto.duration_ms) ?? undefined,
  };
}

/** Normalise `message.sources`, including the legacy `Citation` field names. */
export function toSources(value: unknown): Source[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const sources: Source[] = [];
  for (const raw of value) {
    const record = asRecord(raw);
    const documentId = firstString(record.document_id, record.doc_id);
    const page = firstNumber(record.page, record.page_number) ?? 0;
    const excerpt = firstString(record.excerpt, record.text) ?? "";
    if (!documentId) continue;
    const key = `${documentId}:${page}:${excerpt.slice(0, 64)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push({
      index: sources.length + 1,
      document_id: documentId,
      page,
      excerpt,
      score: firstNumber(record.score) ?? 0,
    });
  }
  return sources;
}

function citationsFromTrail(subProcesses: ApiSubProcess[] | null | undefined): Source[] {
  const citations: unknown[] = [];
  for (const step of subProcesses ?? []) {
    const map = asRecord(step?.metadata_map);
    const subQuestion = asRecord(map.sub_question ?? map.SUB_QUESTION ?? map.subQuestion);
    if (Array.isArray(subQuestion.citations)) citations.push(...subQuestion.citations);
    if (Array.isArray(map.citations)) citations.push(...map.citations);
  }
  return toSources(citations);
}

/** Prefer flat `message.sources`; derive them from the trail for old rows. */
export function citationsToSources(dto: ApiMessage | ApiSubProcess[] | null | undefined): Source[] {
  if (Array.isArray(dto)) return citationsFromTrail(dto);
  if (!dto) return [];
  const direct = toSources(dto.sources);
  return direct.length ? direct : citationsFromTrail(dto.sub_processes);
}

function toMessageStatus(dto: ApiMessage): MessageStatus {
  const raw = String(dto.status ?? "").toUpperCase();
  if (raw === "SUCCESS" || raw === "FINISHED" || raw === "COMPLETED") return "completed";
  if (raw === "ERROR" || raw === "FAILED" || raw === "FAILURE") return "failed";
  if (raw === "STREAMING") return "streaming";
  if (raw === "PENDING" || raw === "PROCESSING") return dto.content ? "streaming" : "processing";
  const lower = raw.toLowerCase();
  return lower === "pending" || lower === "processing" || lower === "streaming" || lower === "completed" || lower === "failed"
    ? (lower as MessageStatus)
    : "processing";
}

/** Map one complete SSE/API `Message` snapshot. */
export function toChatMessage(dto: ApiMessage): ChatMessage {
  const conversationId = firstString(dto.conversation_id) ?? "";
  const id = firstString(dto.id) ?? `${conversationId || "message"}:assistant`;
  const subProcesses = (dto.sub_processes ?? []).map((step, index) => toSubProcess(step, id, index));
  return {
    id,
    conversation_id: conversationId,
    role: dto.role === "user" ? "user" : "assistant",
    content: firstString(dto.content) ?? "",
    status: toMessageStatus(dto),
    sub_processes: subProcesses,
    sources: citationsToSources(dto),
    created_at: iso(dto.created_at ?? dto.updated_at),
  };
}

/** Map either a full conversation or a thread-list summary. */
export function toConversation(dto: ApiConversation | ApiConversationSummary): Conversation {
  const full = "messages" in dto || "documents" in dto ? (dto as ApiConversation) : null;
  const summary = dto as ApiConversationSummary;
  const messages = (full?.messages ?? []).map(toChatMessage);
  const preview = firstString(summary.preview) ?? null;
  const createdAt = iso(dto.created_at ?? dto.last_message_at);
  const updatedAt = iso(dto.updated_at ?? dto.last_message_at ?? createdAt);
  const documentScope =
    full?.documents?.map((doc) => firstString(doc.id)).filter((id): id is string => Boolean(id)) ??
    (summary.document_ids ?? []).map((id) => String(id ?? "")).filter(Boolean);

  return {
    id: firstString(dto.id) ?? "",
    title: firstString(dto.title) ?? (preview ? truncate(preview, 80) : "Untitled thread"),
    document_scope: documentScope,
    messages,
    created_at: createdAt,
    updated_at: updatedAt,
    message_count: firstNumber(summary.message_count) ?? messages.length,
    preview,
  };
}

export function toConversationCreate(body: ConversationCreate): { title?: string; document_ids: string[] } {
  return {
    title: body.title || undefined,
    document_ids: body.document_scope ?? [],
  };
}

export function toConversationUpdate(body: ConversationUpdate): { title?: string; document_ids?: string[] } {
  const payload: { title?: string; document_ids?: string[] } = {};
  if (body.title !== undefined) payload.title = body.title;
  if (body.document_scope !== undefined) payload.document_ids = body.document_scope;
  return payload;
}
