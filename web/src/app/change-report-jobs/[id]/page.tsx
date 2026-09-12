"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { useApi } from "@/lib/api-context";
import { refetchIntervalForJob } from "@/lib/jobs";
import { Change, ChangeSpan, ChangeImpact } from "@/lib/types";
import { JobStatusBadge, ChangeKindBadge, SeverityBadge } from "@/components/status-badges";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function ChangeReportJobPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const api = useApi();

  const job = useQuery({
    queryKey: ["change-report-job", jobId],
    queryFn: () => api.getChangeReportJob(jobId),
    refetchInterval: (query) =>
      refetchIntervalForJob(query.state.data?.status ?? "queued"),
  });

  if (job.isLoading || !job.data) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Loading report…
      </p>
    );
  }

  if (job.data.status !== "completed") {
    return (
      <div className="mx-auto max-w-lg space-y-3 rounded-lg border bg-card p-10 text-center">
        <p className="flex items-center justify-center gap-2 text-sm">
          <JobStatusBadge status={job.data.status} />
          {job.data.status !== "failed" && "Comparing the versions and explaining changes…"}
        </p>
        {job.data.error && (
          <p className="text-sm text-destructive">{job.data.error}</p>
        )}
      </div>
    );
  }

  const changes = job.data.result?.changes ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Change report</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {changes.length} {changes.length === 1 ? "change" : "changes"} between the
          versions, mapped onto affected obligations.
        </p>
      </div>

      {!changes.length ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          No changes detected between the two versions.
        </div>
      ) : (
        <ol className="space-y-4">
          {changes.map((change, index) => (
            <li key={index}>
              <ChangeCard change={change} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ChangeCard({ change }: { change: Change }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <ChangeKindBadge kind={change.kind} />
          {change.clause_ref && (
            <span className="font-mono text-sm text-muted-foreground">
              {change.clause_ref}
            </span>
          )}
          <SeverityBadge severity={change.severity} className="ml-auto" />
        </div>
        <CardTitle className="text-base font-normal leading-relaxed">
          {change.description}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <CitationRow change={change} />
        {change.impacts.length > 0 && (
          <>
            <p className="mb-3 mt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Affected obligations
            </p>
            <ul className="space-y-3">
              {change.impacts.map((impact, index) => (
                <li key={index} className="rounded-md border p-3">
                  <ImpactRow impact={impact} />
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// Citations are the char spans the versions were compared at — pointers back
// into the source text (CONTEXT.md), not quoted excerpts.
function CitationRow({ change }: { change: Change }) {
  const citations: [string, ChangeSpan][] = [
    ...(change.base_span ? ([["base", change.base_span]] as [string, ChangeSpan][]) : []),
    ...(change.amended_span
      ? ([["amended", change.amended_span]] as [string, ChangeSpan][])
      : []),
  ];
  if (!citations.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {citations.map(([label, span]) => (
        <span
          key={label}
          className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground"
          title={`${label} text, characters ${span.char_start}–${span.char_end}`}
        >
          {label} · {span.char_start}–{span.char_end}
        </span>
      ))}
    </div>
  );
}

function ImpactRow({ impact }: { impact: ChangeImpact }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-mono text-xs text-muted-foreground">
          {impact.clause_ref}
          {impact.owner ? ` · ${impact.owner}` : ""}
        </span>
        <span
          className="font-mono text-xs tabular-nums text-muted-foreground"
          title="Model-reported confidence (ADR-007)"
        >
          {Math.round(impact.confidence * 100)}%
        </span>
      </div>
      <p className="mt-1 text-sm leading-relaxed">{impact.description}</p>
    </div>
  );
}
