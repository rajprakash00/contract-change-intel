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
