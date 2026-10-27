/**
 * Domain types
 *
 * These are the shapes the UI renders. The wire DTOs live in `wire.ts` and
 * `transport.ts`; UI components must never consume API payloads directly.
 */

export type NSEDocumentType =
  | "annual_report"
  | "quarterly_results"
  | "concall_transcript"
  | "investor_presentation"
  | "shareholding_pattern"
  | "corporate_announcement";

export type DocumentStatus =
  | "uploading"
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed";

/** The minimum file shape the upload UI and mock transport need. */
export interface UploadableFile {
  name: string;
  size: number;
  type: string;
}

/** Optional multipart fields accepted by POST /api/document/upload. */
export interface DocumentUploadMetadata {
  company_name?: string;
  company_symbol?: string;
  financial_year?: string;
  document_type?: NSEDocumentType;
  exchange?: string;
}

/** DocumentMetadataKeysEnum */
export interface DocumentMetadata {
  company_name: string;
  nse_symbol: string;
  document_type: NSEDocumentType;
  fiscal_year: string;
  period: string;
  pages: number;
  file_size: number;
  language: string;
}

/** Document */
export interface FinDocument {
  id: string;
  filename: string;
  status: DocumentStatus;
  progress: number; // 0..100 for upload
  metadata: DocumentMetadata;
  uploaded_at: string;
  /** Present on M1 API documents; mock documents omit these two fields. */
  url?: string;
  error?: string | null;
}

/** MessageSubProcessSourceEnum */
export type SubProcessSource = "llm" | "retrieval" | "rerank" | "parser";

/** MessageSubProcessStatusEnum */
export type SubProcessStatus = "pending" | "running" | "completed" | "failed";

/** MessageSubProcess */
export interface MessageSubProcess {
  id: string;
  name: string;
  source: SubProcessSource;
  status: SubProcessStatus;
  /** SubProcessMetadataKeysEnum values flattened to readable detail */
  detail?: string;
  duration_ms?: number;
}

/** MessageRoleEnum */
export type MessageRole = "user" | "assistant";

/** MessageStatusEnum */
export type MessageStatus = "pending" | "processing" | "streaming" | "completed" | "failed";

/** A grounded citation attached to an assistant message */
export interface Source {
  index: number;
  document_id: string;
  page: number;
  excerpt: string;
  score: number; // 0..1 relevance
}

/** Message */
export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  sub_processes: MessageSubProcess[];
  sources: Source[];
  created_at: string;
}

/** Conversation */
export interface Conversation {
  id: string;
  title: string;
  /** document ids this conversation is scoped to; empty = all filings */
  document_scope: string[];
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
  /** Set by GET /api/conversation/ summaries; hydrated threads use messages.length. */
  message_count?: number;
  preview?: string | null;
}

/** ConversationCreate */
export interface ConversationCreate {
  title: string;
  document_scope?: string[];
}

/** ConversationUpdate */
export interface ConversationUpdate {
  title?: string;
  document_scope?: string[];
}

/** DocumentUploadResponse (normalised from the M1 API's bare Document DTO) */
export interface DocumentUploadResponse {
  document: FinDocument;
}

export interface HealthResponse {
  status: "healthy" | "degraded" | "down";
  db?: boolean;
  vector_store?: boolean | null;
  version?: string;
  uptime_s?: number;
}

export type View = "chat" | "library";
