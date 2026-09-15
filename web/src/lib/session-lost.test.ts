import { describe, expect, it } from "vitest";

import { ApiError, loadErrorMessage } from "@/lib/api";
import { isSessionLost } from "@/lib/api-context";

describe("isSessionLost", () => {
  it("treats every unrecoverable silent-refresh failure as a lost session", () => {
    for (const code of [
      "login_required",
      "consent_required",
      "missing_refresh_token",
      "invalid_grant",
      "invalid_refresh_token",
    ]) {
      expect(isSessionLost({ error: code })).toBe(true);
    }
  });

  it("keeps transient refresh failures recoverable", () => {
    expect(isSessionLost({ error: "timeout" })).toBe(false);
    expect(isSessionLost(new Error("network down"))).toBe(false);
    expect(isSessionLost(undefined)).toBe(false);
    expect(isSessionLost({})).toBe(false);
  });
});

describe("loadErrorMessage", () => {
  it("reads a dead session as a session problem, not an API outage", () => {
    expect(loadErrorMessage(new ApiError(401, "token has expired"))).toBe(
      "Session expired. Sign in again to continue.",
    );
  });

  it("names permission failures instead of blaming the API", () => {
    expect(loadErrorMessage(new ApiError(403, "admin role required"))).toBe(
      "You do not have access to these documents.",
    );
  });

  it("keeps the connectivity hint for non-HTTP failures", () => {
    expect(loadErrorMessage(new Error("fetch failed"))).toBe(
      "Could not load documents. Is the API running?",
    );
  });
});
