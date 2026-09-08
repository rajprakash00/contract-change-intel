import { describe, expect, it } from "vitest";

import { JOB_POLL_INTERVAL_MS, isSettled, refetchIntervalForJob } from "@/lib/jobs";

describe("isSettled", () => {
  it("queued and running jobs are unsettled", () => {
    expect(isSettled("queued")).toBe(false);
    expect(isSettled("running")).toBe(false);
  });

  it("completed and failed jobs are settled", () => {
    expect(isSettled("completed")).toBe(true);
    expect(isSettled("failed")).toBe(true);
  });
});

describe("refetchIntervalForJob", () => {
  it("polls at the fixed cadence while the job is in flight", () => {
    expect(refetchIntervalForJob("queued")).toBe(JOB_POLL_INTERVAL_MS);
    expect(refetchIntervalForJob("running")).toBe(JOB_POLL_INTERVAL_MS);
  });

  it("stops polling once the job is settled", () => {
    expect(refetchIntervalForJob("completed")).toBe(false);
    expect(refetchIntervalForJob("failed")).toBe(false);
  });
});
