import type { JobStatus } from "@/lib/types";

// Job status — light polling (docs/w6-decisions.md #4): while any job row is
// queued/running, poll at a fixed cadence; stop once settled. React Query's
// refetchInterval accepts a number (ms) or false (stop).

export const JOB_POLL_INTERVAL_MS = 5000;

export function isSettled(status: JobStatus): boolean {
  return status === "completed" || status === "failed";
}

export function refetchIntervalForJob(status: JobStatus): number | false {
  return isSettled(status) ? false : JOB_POLL_INTERVAL_MS;
}
