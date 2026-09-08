"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useAuth0 } from "@auth0/auth0-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, Cog, FileSearch, GitCompareArrows } from "lucide-react";

import { errorMessage } from "@/lib/api";
import { useApi } from "@/lib/api-context";
import { JOB_POLL_INTERVAL_MS, isSettled, refetchIntervalForJob } from "@/lib/jobs";
import { isAdmin } from "@/lib/roles";
import { JobStatus } from "@/lib/types";
import { DocumentStatusBadge, JobStatusBadge } from "@/components/status-badges";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";

// Job ids survive a reload in localStorage so an in-flight pipeline job keeps
// polling after the user navigates away and back (there is no jobs-by-document
// endpoint to recover them server-side).
function usePersistedJobId(documentId: string, kind: string) {
  const key = `cci:job:${kind}:${documentId}`;
  const [jobId, setJobId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.localStorage.getItem(key),
  );
  const update = (next: string | null) => {
    setJobId(next);
    if (next) window.localStorage.setItem(key, next);
    else window.localStorage.removeItem(key);
  };
  return [jobId, update] as const;
}

export default function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const documentId = params.id;
  const { user } = useAuth0();
  const admin = isAdmin(user);
  const api = useApi();
  const router = useRouter();

  const [ingestionJobId, setIngestionJobId] = usePersistedJobId(documentId, "ingestion");
  const [extractionJobId, setExtractionJobId] = usePersistedJobId(documentId, "extraction");
  const [amendmentId, setAmendmentId] = useState("");

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api.listDocuments(100),
  });

  const ingestionJob = useQuery({
    queryKey: ["ingestion-job", ingestionJobId],
    queryFn: () => api.getIngestionJob(ingestionJobId!),
    enabled: ingestionJobId !== null,
    refetchInterval: (query) => refetchIntervalForJob(jobStatus(query.state.data)),
  });

  const extractionJob = useQuery({
    queryKey: ["extraction-job", extractionJobId],
    queryFn: () => api.getExtractionJob(extractionJobId!),
    enabled: extractionJobId !== null,
    refetchInterval: (query) => refetchIntervalForJob(jobStatus(query.state.data)),
  });

  // While a pipeline job is in flight the document row itself is stale the
  // moment the job lands — keep it fresh until everything settles.
  const pipelineInFlight =
    (ingestionJobId !== null &&
      (ingestionJob.isLoading || !isSettled(jobStatus(ingestionJob.data)))) ||
    (extractionJobId !== null &&
      (extractionJob.isLoading || !isSettled(jobStatus(extractionJob.data))));

  const document = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api.getDocument(documentId),
    refetchInterval: pipelineInFlight ? JOB_POLL_INTERVAL_MS : false,
  });

  const ingestionStatus = ingestionJob.data?.status;
  const extractionStatus = extractionJob.data?.status;

  useEffect(() => {
    if (ingestionStatus === "completed") {
      toast.success("Ingestion completed");
    }
  }, [ingestionStatus]);

  useEffect(() => {
    if (extractionStatus === "completed") {
      toast.success("Extraction completed");
    }
  }, [extractionStatus]);

  const enqueueIngestion = useMutation({
    mutationFn: () => api.enqueueIngestion(documentId),
    onSuccess: (job) => {
      setIngestionJobId(job.id);
      toast.success("Ingestion queued");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not queue ingestion")),
  });

  const enqueueExtraction = useMutation({
    mutationFn: () => api.enqueueExtraction(documentId),
    onSuccess: (job) => {
      setExtractionJobId(job.id);
      toast.success("Extraction queued");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not queue extraction")),
  });

  const generateReport = useMutation({
    mutationFn: () => api.enqueueChangeReport(documentId, amendmentId),
    onSuccess: (job) => router.push(`/change-report-jobs/${job.id}`),
    onError: (error) =>
      toast.error(errorMessage(error, "Could not queue change report")),
  });

  if (document.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  if (document.error || !document.data) {
    return <p className="text-sm text-destructive">Document not found.</p>;
  }

  const doc = document.data;
  const amendments = (documents.data?.items ?? []).filter(
    (d) => d.amends_document_id === doc.id,
  );
  const parent = (documents.data?.items ?? []).find((d) => d.id === doc.amends_document_id);

  return (
    <div className="space-y-8">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
          <Link href="/">
            <ArrowLeft aria-hidden />
            All documents
          </Link>
        </Button>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{doc.filename}</h1>
          <DocumentStatusBadge status={doc.status} />
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {parent ? (
            <>
              Amends{" "}
              <Link href={`/documents/${parent.id}`} className="hover:underline">
                {parent.filename}
              </Link>
            </>
          ) : (
            "Agreement"
          )}
          {" · "}
          {doc.mime_type}
        </p>
      </div>

      {admin && (
        <>
          <Separator />
          <section className="space-y-4">
            <h2 className="text-lg font-semibold">Pipeline</h2>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="outline"
                onClick={() => enqueueIngestion.mutate()}
                disabled={enqueueIngestion.isPending}
              >
                <Cog aria-hidden />
                Run ingestion
              </Button>
              <Button
                variant="outline"
                onClick={() => enqueueExtraction.mutate()}
                disabled={enqueueExtraction.isPending || doc.status !== "parsed"}
              >
                <FileSearch aria-hidden />
                Run extraction
              </Button>
            </div>
            {ingestionJob.data && (
              <JobRow
                kind="Ingestion"
                status={ingestionJob.data.status}
                error={ingestionJob.data.error}
              />
            )}
            {extractionJob.data && (
              <JobRow
                kind="Extraction"
                status={extractionJob.data.status}
                error={extractionJob.data.error}
              />
            )}
          </section>
        </>
      )}

      {admin && (
        <>
          <Separator />
          <section className="space-y-4">
            <h2 className="text-lg font-semibold">Change report</h2>
            {amendments.length ? (
              <div className="flex max-w-xl flex-col gap-3">
                <div className="space-y-2">
                  <Label htmlFor="amendment">Amendment</Label>
                  <Select value={amendmentId} onValueChange={setAmendmentId}>
                    <SelectTrigger id="amendment" className="w-full">
                      <SelectValue placeholder="Choose an amendment" />
                    </SelectTrigger>
                    <SelectContent>
                      {amendments.map((amendment) => (
                        <SelectItem key={amendment.id} value={amendment.id}>
                          {amendment.filename}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  className="w-fit"
                  disabled={!amendmentId || generateReport.isPending}
                  onClick={() => generateReport.mutate()}
                >
                  <GitCompareArrows aria-hidden />
                  Generate change report
                </Button>
              </div>
            ) : (
              <p className="max-w-xl text-sm text-muted-foreground">
                Upload an amendment of this agreement to see what changed. Amendments
                are uploaded from the documents page with “Amends” set to this
                agreement.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function jobStatus(job: { status: JobStatus } | undefined): JobStatus {
  return job?.status ?? "queued";
}

function JobRow({
  kind,
  status,
  error,
}: {
  kind: string;
  status: JobStatus;
  error: string | null;
}) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-24 text-muted-foreground">{kind}</span>
      <JobStatusBadge status={status} />
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}
