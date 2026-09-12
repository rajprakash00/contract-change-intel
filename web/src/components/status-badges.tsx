import type { DocumentStatus, JobStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const JOB_VARIANT: Record<JobStatus, "secondary" | "default" | "destructive" | "outline"> = {
  queued: "outline",
  running: "secondary",
  completed: "default",
  failed: "destructive",
};

const DOCUMENT_VARIANT: Record<DocumentStatus, "secondary" | "default" | "destructive" | "outline"> = {
  uploaded: "outline",
  parsed: "default",
  failed: "destructive",
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return <Badge variant={JOB_VARIANT[status]}>{status}</Badge>;
}

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return <Badge variant={DOCUMENT_VARIANT[status]}>{status}</Badge>;
}

export function ChangeKindBadge({ kind }: { kind: string }) {
  return (
    <span className="rounded-md bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
      {kind}
    </span>
  );
}

export function SeverityBadge({
  severity,
  className = "",
}: {
  severity: string;
  className?: string;
}) {
  const tone =
    severity === "high"
      ? "bg-destructive text-white"
      : severity === "medium"
        ? "bg-[var(--severity-medium)] text-black"
        : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${className} ${tone}`}>
      {severity} impact
    </span>
  );
}
