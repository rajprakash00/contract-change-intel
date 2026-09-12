// Browser→API access: same-origin always (docs/w6-decisions.md #1). The
// browser says /api/... — dev strips the prefix via a Next rewrite, prod
// path-routes at the ALB. The bearer token is attached per request from the
// Auth0 SDK; the API (ADR-008) remains the enforcement point.

import type {
  ChangeReportJobRead,
  Disposition,
  DocumentListPage,
  DocumentRead,
  ExtractionJobRead,
  IngestionJobRead,
  ReviewItemRead,
  ReviewItemStatus,
  ReviewItemsResponse,
} from "@/lib/types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

async function detailOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail !== undefined) return JSON.stringify(body.detail);
    return JSON.stringify(body);
  } catch {
    return response.statusText;
  }
}

export type TokenGetter = () => Promise<string>;

// One shared mutation-failure message: the API's detail when it sent one
// (409s carry the blocking job id, 404/413/415 carry their rules), a
// fallback otherwise.
export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.detail : fallback;
}

export function createApi(getAccessToken: TokenGetter) {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = await getAccessToken();
    const response = await fetch(`/api${path}`, {
      ...init,
      headers: {
        ...(init?.headers ?? {}),
        Authorization: `Bearer ${token}`,
      },
    });
    if (!response.ok) {
      throw new ApiError(response.status, await detailOf(response));
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  return {
    listDocuments(limit = 50, offset = 0) {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      return request<DocumentListPage>(`/documents?${params}`);
    },

    getDocument(documentId: string) {
      return request<DocumentRead>(`/documents/${documentId}`);
    },

    deleteDocument(documentId: string) {
      return request<void>(`/documents/${documentId}`, { method: "DELETE" });
    },

    uploadDocument(file: File, amendsDocumentId?: string) {
      const form = new FormData();
      form.append("file", file);
      if (amendsDocumentId) form.append("amends_document_id", amendsDocumentId);
      // No Content-Type header: the browser sets the multipart boundary.
      return request<DocumentRead>("/documents", { method: "POST", body: form });
    },

    enqueueIngestion(documentId: string) {
      return request<IngestionJobRead>(`/documents/${documentId}/ingestion`, {
        method: "POST",
      });
    },

    getIngestionJob(jobId: string) {
      return request<IngestionJobRead>(`/ingestion-jobs/${jobId}`);
    },

    enqueueExtraction(documentId: string) {
      return request<ExtractionJobRead>(`/documents/${documentId}/extraction`, {
        method: "POST",
      });
    },

    getExtractionJob(jobId: string) {
      return request<ExtractionJobRead>(`/extraction-jobs/${jobId}`);
    },

    enqueueChangeReport(baseDocumentId: string, amendmentDocumentId: string) {
      return request<ChangeReportJobRead>(`/agreements/${baseDocumentId}/change-report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amendment_document_id: amendmentDocumentId }),
      });
    },

    getChangeReportJob(jobId: string) {
      return request<ChangeReportJobRead>(`/change-report-jobs/${jobId}`);
    },

    listChangeReportJobs(agreementId: string) {
      return request<ChangeReportJobRead[]>(
        `/agreements/${agreementId}/change-report-jobs`,
      );
    },

    listReviewItems(status?: ReviewItemStatus) {
      const suffix = status ? `?status=${status}` : "";
      return request<ReviewItemsResponse>(`/review-items${suffix}`);
    },

    resolveReviewItem(itemId: string, disposition: Disposition, correctedValues?: object) {
      return request<ReviewItemRead>(`/review-items/${itemId}/disposition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          disposition,
          ...(correctedValues !== undefined ? { corrected_values: correctedValues } : {}),
        }),
      });
    },
  };
}

export type Api = ReturnType<typeof createApi>;
