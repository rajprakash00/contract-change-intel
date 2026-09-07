# ADR-008: OIDC Bearer Auth via Auth0

## Context

Until W5·C the API's only principal was the `X-Tenant-Id` header: whoever
could reach the port read or wrote any tenant's data by naming it. The
system is multi-tenant and audited, and W6 adds a deployed API plus a thin
UI — a real identity boundary has to exist before that. Self-built identity
(credential storage, password reset, MFA, sessions) is exactly the
boilerplate this project should not hand-roll.

## Decision

**OIDC via Auth0, verified bearer JWTs, and that is the whole surface.**

- **Verification, not login.** Auth0 issues the tokens; this API only
  verifies them. The verifier (`app/auth/verifier.py`) checks RS256
  signatures against Auth0's published JWKS, plus issuer, audience, expiry
  (30 s leeway), and required standard claims (`exp`, `iat`, `sub`).
- **Claims map to Tenant + Role.** Two namespaced custom claims carry the
  domain mapping — `https://cci/tenant_id` (the tenant UUID, the same
  identifier every repository already scopes on) and `https://cci/role`
  (`admin` or `reviewer`). There is no tenants table and no org mapping in
  this codebase: the tenant UUID is minted at provisioning time and an
  Auth0 Action attaches it (and the role) to the access token. Auth0
  Organizations-per-tenant is the provisioning flow *outside* this repo;
  the API never sees an org id, only the resulting claims.
- **Roles are enforced, minimally.** Document and job mutations require
  `admin`; the review queue (dispositions) accepts `reviewer` or `admin`;
  reads are for any authenticated principal, always scoped to the token's
  tenant. Two roles, three dependency shapes (`PrincipalDep`,
  `AdminPrincipal`, `ReviewerPrincipal`) — no permission matrix.
- **JWKS keys are cached in-process with a TTL** (`auth_jwks_cache_seconds`,
  default 600); an unknown `kid` forces a refresh, rate-limited to at most
  one per 30 s, so Auth0 key rotation is picked up quickly without letting
  a flood of forged kids hammer the issuer's endpoint.
- **No "auth off" mode.** Missing `AUTH0_DOMAIN`/`AUTH0_AUDIENCE` surfaces
  503 per request (same posture as the missing OpenAI key), never a
  silently open API. `/healthz` stays unauthenticated for probes.
- **The header is gone.** Tenant now comes only from the token; the
  `X-Tenant-Id` header is removed rather than kept as a fallback, so there
  is exactly one principal source. `audit_log` gains its `actor` column —
  the token subject — landing the promise made in W5·B that today's
  actor-is-tenant compromise would be replaced by auth.
- **Tests fake the JWKS wire at the transport seam**
  (`tests/fake_jwks.py`, mirroring `tests/fake_openai.py`): tests sign real
  JWTs with a test RSA key and the `JwksClient` transport serves the matching
  JWKS, so signing, fetching, verification and claim mapping all run real.

## Consequences

- Every HTTP caller needs a bearer token; the eval harness and worker are
  unaffected (they call services/repos directly with explicit `tenant_id`).
- Review routing and audit reads now have a human-meaningful actor; audit
  rows written before this block keep `actor = NULL` (the column is
  nullable by design).
- Auth0 becomes a runtime dependency of the deployed system (JWKS
  fetchability); its unavailability maps to 502, invalid tokens to 401 with
  `WWW-Authenticate: Bearer`, insufficient role to 403.
- The W6·A UI uses Auth0 SPA login and forwards the bearer token; nothing
  in this API needs to change for that.
- User/role provisioning lives in Auth0 (dashboard, org invites, Action
  for claims). There is no user-management API here, by intent.

## Rejected alternatives

- Keep `X-Tenant-Id` as a fallback when auth is unconfigured — two
  principal sources, and "auth off" is a footgun one misconfiguration away
  from open.
- Self-built identity or a local JWT issuer — the boilerplate ADR exists to
  avoid.
- Map Auth0 `org_id` directly to tenant ids — couples this schema to an
  Auth0 identifier format and requires a tenants table for no current use;
  the custom claim keeps the boundary at one string parse.
