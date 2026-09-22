"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQueries, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ClipboardCopy, Printer } from "lucide-react";
import { toast } from "sonner";

import { useApi } from "@/lib/api-context";
import { loadErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { refetchIntervalForJob } from "@/lib/jobs";
import { reportToMarkdown } from "@/lib/report-markdown";
import type { Change } from "@/lib/types";
import { ChangeExcerpts, ImpactList } from "@/components/change-parts";
import { ChangeKindBadge, JobStatusBadge, SeverityBadge } from "@/components/status-badges";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const SEVERITIES = ["high", "medium", "low"] as const;
type Severity = (typeof SEVERITIES)[number];

const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High severity",
  medium: "Medium severity",
  low: "Low severity",
};

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export default function ChangeReportJobPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const api = useApi();
  const [severityFilter, setSeverityFilter] = useState<Severity | "all">("all");

  const job = useQuery({
    queryKey: ["change-report-job", jobId],
    queryFn: () => api.getChangeReportJob(jobId),
    refetchInterval: (query) =>
      refetchIntervalForJob(query.state.data?.status ?? "queued"),
  });

  const baseDocumentId = job.data?.base_document_id;
  const amendedDocumentId = job.data?.amended_document_id;
  const documents = useQueries({
    queries: [
      {
        queryKey: ["document", baseDocumentId],
        queryFn: () => api.getDocument(baseDocumentId as string),
        enabled: Boolean(baseDocumentId),
        staleTime: 5 * 60_000,
      },
      {
        queryKey: ["document", amendedDocumentId],
        queryFn: () => api.getDocument(amendedDocumentId as string),
        enabled: Boolean(amendedDocumentId),
        staleTime: 5 * 60_000,
      },
    ],
  });
  const baseName = documents[0]?.data?.filename;
  const amendedName = documents[1]?.data?.filename;

  const changes = useMemo(() => job.data?.result?.changes ?? [], [job.data]);

  if (job.isError) {
    return (
      <div className="mx-auto max-w-lg space-y-4 rounded-lg border bg-card p-10 text-center">
        <p className="text-sm text-muted-foreground">{loadErrorMessage(job.error)}</p>
        <Button variant="outline" size="sm" onClick={() => void job.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (job.isLoading || !job.data) {
    return <ReportSkeleton />;
  }

  const report = job.data;

  if (report.status !== "completed") {
    return (
      <div className="mx-auto max-w-lg space-y-3 rounded-lg border bg-card p-10 text-center">
        <p className="flex items-center justify-center gap-2 text-sm">
          <JobStatusBadge status={report.status} />
          {report.status !== "failed" && "Comparing the versions and explaining changes…"}
        </p>
        {report.error && <p className="text-sm text-destructive">{report.error}</p>}
        {report.status === "failed" && (
          <Link
            href={`/documents/${report.base_document_id}`}
            className="inline-block text-sm text-primary underline-offset-4 hover:underline"
          >
            Back to the agreement
          </Link>
        )}
      </div>
    );
  }

  async function copyReport() {
    try {
      await navigator.clipboard.writeText(
        reportToMarkdown(report, { base: baseName, amended: amendedName }),
      );
      toast.success("Report copied as Markdown");
    } catch {
      toast.error("Could not copy the report to the clipboard");
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header className="space-y-4">
        <Link
          href={`/documents/${report.base_document_id}`}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Back to agreement
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold">Change report</h1>
            <p className="text-sm text-muted-foreground">
              {baseName ?? "Agreement"} → {amendedName ?? "Amendment"}
            </p>
            <p className="font-mono text-xs text-muted-foreground">
              job {report.id} · updated {DATE_FORMAT.format(new Date(report.updated_at))}
            </p>
          </div>
          <div className="flex gap-2 print:hidden">
            <Button variant="outline" size="sm" onClick={() => void copyReport()}>
              <ClipboardCopy aria-hidden />
              Copy as Markdown
            </Button>
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer aria-hidden />
              Print
            </Button>
          </div>
        </div>
      </header>

      {!changes.length ? (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <p className="text-sm font-medium">No changes detected between these versions.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            The diff found no added, removed, or modified clauses.
          </p>
        </div>
      ) : (
        <>
          <SeverityFilter
            changes={changes}
            value={severityFilter}
            onChange={setSeverityFilter}
          />
          <div className="space-y-8">
            {(severityFilter === "all" ? SEVERITIES : [severityFilter]).map((severity) => {
              const group = changes.filter((change) => change.severity === severity);
              if (!group.length) return null;
              return (
                <section key={severity} aria-labelledby={`severity-${severity}`}>
                  <h2
                    id={`severity-${severity}`}
                    className="flex items-baseline gap-2 text-sm font-medium"
                  >
                    {SEVERITY_LABEL[severity]}
                    <span className="font-mono text-xs text-muted-foreground">
                      {group.length}
                    </span>
                  </h2>
                  <ol className="mt-1 divide-y">
                    {group.map((change, index) => (
                      <li key={`${change.kind}-${change.clause_ref ?? "preamble"}-${index}`}>
                        <ChangeRow change={change} />
                      </li>
                    ))}
                  </ol>
                </section>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function SeverityFilter({
  changes,
  value,
  onChange,
}: {
  changes: Change[];
  value: Severity | "all";
  onChange: (value: Severity | "all") => void;
}) {
  const counts = useMemo(() => {
    const result: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
    for (const change of changes) result[change.severity] += 1;
    return result;
  }, [changes]);

  const chips: { key: Severity | "all"; label: string; count: number }[] = [
    { key: "all", label: "All", count: changes.length },
    ...SEVERITIES.map((severity) => ({
      key: severity,
      label: severity,
      count: counts[severity],
    })),
  ];

  return (
    <div className="flex flex-wrap items-center gap-2 print:hidden" role="group" aria-label="Filter changes by severity">
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          aria-pressed={value === chip.key}
          onClick={() => onChange(chip.key)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
            value === chip.key
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          {chip.label}
          <span className="font-mono tabular-nums">{chip.count}</span>
        </button>
      ))}
    </div>
  );
}

function ChangeRow({ change }: { change: Change }) {
  return (
    <article className="space-y-3 py-5">
      <div className="flex flex-wrap items-center gap-3">
        <ChangeKindBadge kind={change.kind} />
        <span className="font-mono text-sm">{change.clause_ref ?? "preamble"}</span>
        <SeverityBadge severity={change.severity} />
      </div>
      <p className="max-w-[70ch] text-[1.0625rem] leading-relaxed">{change.description}</p>
      <ChangeExcerpts change={change} />
      <ImpactList impacts={change.impacts} />
    </article>
  );
}

function ReportSkeleton() {
  return (
    <div className="mx-auto max-w-4xl space-y-6" aria-busy="true" aria-label="Loading report">
      <Skeleton className="h-4 w-36" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-80" />
      {[0, 1].map((index) => (
        <div key={index} className="space-y-3 border-t pt-5">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ))}
    </div>
  );
}
