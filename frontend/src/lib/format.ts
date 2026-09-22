import type { DocumentStatus, NSEDocumentType, SubProcessSource } from "./types";

export function initials(company: string): string {
  return company
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

export function timeHM(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function shortDate(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  if (sameDay) return timeHM(iso);
  return d.toLocaleDateString([], { day: "2-digit", month: "short" });
}

export function formatFileSize(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

export const DOC_TYPE_LABEL: Record<NSEDocumentType, string> = {
  annual_report: "Annual Report",
  quarterly_results: "Quarterly Results",
  concall_transcript: "Concall Transcript",
  investor_presentation: "Investor Deck",
  shareholding_pattern: "Shareholding",
  corporate_announcement: "Announcement",
};

export const DOC_TYPE_SHORT: Record<NSEDocumentType, string> = {
  annual_report: "AR",
  quarterly_results: "QR",
  concall_transcript: "CT",
  investor_presentation: "ID",
  shareholding_pattern: "SP",
  corporate_announcement: "CA",
};

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  uploading: "Uploading",
  parsing: "Parsing PDF",
  chunking: "Chunking",
  embedding: "Embedding",
  indexing: "Indexing",
  ready: "Ready",
  failed: "Failed",
};

export const PIPELINE_STAGES: DocumentStatus[] = [
  "parsing",
  "chunking",
  "embedding",
  "indexing",
];

export const SUBPROCESS_META: Record<
  SubProcessSource,
  { label: string }
> = {
  llm: { label: "LLM" },
  retrieval: { label: "Vector store" },
  rerank: { label: "Reranker" },
  parser: { label: "Parser" },
};

export function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

let nowCounter = 0;
export function nowIso(): string {
  // keep ordering stable inside the same tick
  return new Date(Date.now() + nowCounter++).toISOString();
}
