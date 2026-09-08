// The API's role model (ADR-008): claims map to Tenant + Role, with
// `https://cci/role` carrying "admin" or "reviewer". The claim key must match
// the Auth0 Login Action verbatim. UI gating is presentational only — the API
// remains the enforcement point (docs/w6-decisions.md #3).

export const ROLE_CLAIM = "https://cci/role";

export type Role = "admin" | "reviewer";

// Accepts the whole decoded ID token payload as-is, so callers can pass the
// Auth0 SDK's `user` without casting.
export function roleFromClaims(claims: unknown): Role | null {
  const value =
    typeof claims === "object" && claims !== null
      ? (claims as Record<string, unknown>)[ROLE_CLAIM]
      : undefined;
  return value === "admin" || value === "reviewer" ? value : null;
}

export function isAdmin(claims: unknown): boolean {
  return roleFromClaims(claims) === "admin";
}
