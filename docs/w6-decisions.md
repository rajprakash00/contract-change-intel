# W6·A thin UI: settled decisions

Settled in the W6 grill session (2026-09-08). Scope from docs/w5-decisions.md
("UI (W6·A)"): upload + document list, change-report view with
Citations/Confidence, review-queue triage, Auth0 SPA login → bearer token.
Build target is production-grade: consistent design system, not a throwaway demo skin.

## Design system

**shadcn/ui + Tailwind**, theme tokens layered on top. shadcn components are
vendored source (owned in-repo), not runtime dependencies — consistent with
the anti-slop rule, which targets runtime dependency sprawl. Radix primitives
are the accessibility hard part; we don't hand-roll it.

## Interface decisions

1. **Browser→API origin — same-origin always.** No CORS middleware, no
   allowed-origins setting. Dev: Next.js rewrites proxy the API. Prod:
   ALB path-routes (topology detail: see API path prefix below).
2. **Token lifecycle — `@auth0/auth0-react` SDK.** PKCE, silent refresh with
   rotating refresh tokens, in-memory cache. Bearer per request; API
   unchanged (ADR-008 stays the server-side authority).
3. **Role gating — hide.** Role read client-side from the decoded JWT claim
   (`https://cci/role`); reviewers never see admin-only controls (upload,
   delete). The API remains the enforcement point; UI gating is
   presentational only.
4. **Job status — light polling.** While any job row is pending/running,
   poll ~5s; stop when settled. No SSE/WebSocket (deferred hardening), no
   API change.
5. **Frontend directory — `web/`.** Next.js/TS sibling directory in-repo.

## Library stack (selected against feature requirements)

- `shadcn/ui` + Tailwind + `lucide-react` (icons) — component base
- `@tanstack/react-query` — server state: fetching, mutations, the Q4 polling
  loop (refetchInterval while pending)
- `react-hook-form` + `zod` + shadcn Form — upload form (file +
  `amends_document_id` parent select)
- `@tanstack/react-table` — document list + review-queue tables
- `sonner` — toasts (shadcn's default)

Nothing from registry marketplaces (21st.dev etc.) as a dependency; canonical
shadcn only, for consistency.

6. **API path prefix — `root_path` setting.** The browser always says
   `/api/...`; the prefix lives in exactly one place. FastAPI gets a
   `root_path` setting (empty in dev, `/api` in prod via env → uvicorn
   `--root-path /api`); zero route changes, zero test churn (ASGITransport
   scope carries no root_path). Dev: Next rewrite `/api/:path* →
   localhost:8000/:path*` strips the prefix. Prod: ALB rule `/api/*` → API
   service (ALB forwards paths as-is; no rewrite layer needed).

## Visual direction

**"Calm legal-tech"**: light-first with a dark-mode token set; serif display
face for document/report headings against a neutral sans for UI chrome; one
restrained deep accent (ink blue or oxblood); generous whitespace;
document-dense tables. Stripe-docs restraint, not dashboard-saaS neon.
Uniqueness comes from the token layer on top of shadcn's consistent skeleton.
