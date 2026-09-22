// Wire contracts mirrored from app/schemas — the UI's view of the API surface.
// These are structural copies, not generated code: the surface is small and
// stable, and a codegen pipeline would outweigh it (primitives over
// abstractions).

export type DocumentStatus = "uploaded" | "parsed" | "failed";
export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface DocumentRead {
  id: string;
  tenant_id: string;
  filename: string;
  mime_type: string;
  sha256: string;
  amends_document_id: string | null;
  status: DocumentStatus;
}

export interface DocumentListPage {
  items: DocumentRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface IngestionJobRead {
  id: string;
  tenant_id: string;
  document_id: string;
  status: JobStatus;
  result: { chunk_count?: number } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExtractionJobRead {
  id: string;
  tenant_id: string;
  document_id: string;
  status: JobStatus;
  result: { obligations?: unknown[]; defined_terms?: unknown[] } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChangeSpan {
  char_start: number;
  char_end: number;
}

export interface ChangeImpact {
  clause_ref: string;
  description: string;
  owner: string | null;
  confidence: number;
}

export interface Change {
  kind: "added" | "removed" | "modified";
  clause_ref: string | null;
  base_span: ChangeSpan | null;
  amended_span: ChangeSpan | null;
  // Changed wording, snapshotted at generation time (W7·A). Optional because
  // reports created before the field landed lack it.
  base_excerpt?: string | null;
  amended_excerpt?: string | null;
  description: string;
  severity: "low" | "medium" | "high";
  impacts: ChangeImpact[];
}

export interface ChangeReportJobRead {
  id: string;
  tenant_id: string;
  base_document_id: string;
  amended_document_id: string;
  status: JobStatus;
  result: { changes: Change[] } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export type ReviewItemStatus = "pending" | "approved" | "edited" | "rejected";

// The terminal resolutions a reviewer can apply (pending is not one).
export type Disposition = Exclude<ReviewItemStatus, "pending">;
export type ReviewItemSource = "extraction" | "impact_mapping";

export interface ReviewItemRead {
  id: string;
  tenant_id: string;
  source: ReviewItemSource;
  item_type: string;
  document_id: string;
  job_id: string;
  payload: Record<string, unknown>;
  confidence: number;
  status: ReviewItemStatus;
  corrected_values: Record<string, unknown> | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReviewItemsResponse {
  items: ReviewItemRead[];
}
