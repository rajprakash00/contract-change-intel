# ADR-011: Published Demo Tenant with a Reduced Budget Tier

## Context

The product is a portfolio piece evaluated by strangers who arrive at the
live demo (`change-report.byraj.dev`) with nothing but the README. The demo
credentials are published there (admin + reviewer of a dedicated demo
tenant, provisioned in Auth0 — see `README.md`). Two problems remained:
every LLM-spending tenant shares one budget size, so a visitor could burn
the demo tenant's whole hour (or the operator's, if the tenant were
shared), and a fresh demo tenant shows an empty product until someone pays
the pipeline cost to fill it. Self-serve signup and BYOK were considered
and rejected: the audience is evaluators, not buyers, so a signup flow adds
attack surface for nothing, and BYOK's key storage + per-call routing buys
protection against unbounded anonymous use that published credentials
already bound.

## Decision

**One published demo tenant, seeded by a script, on a reduced per-hour
budget tier configured in settings.**

- **Demo tenant identity is settings**, not a schema concept: a
  `demo_tenant_ids` setting lists the tenant UUIDs on the demo tier
  (Auth0 Action already attaches the dedicated tenant claim — confirmed
  distinct from the operator tenant). No tenants table; ADR-008's
  "no tenants table" stands until a second per-tenant attribute shows up.
- **Budget tier via the existing ADR-010 knobs.** `enforce()` already keys
  per (kind, tenant); the amount lookup now checks the demo list first and
  falls back to the standard thresholds: demo defaults
  5 extractions/hour, 2 change reports/hour (settings-overridable). A 429
  on the demo tier is acceptable product behavior — the seeded artifacts
  let an evaluator see the full output while the budget re-heals hourly.
- **Seeding is a checked-in idempotent script** (`scripts/seed_demo.py`)
  that drives the real services: upload a sample Agreement + Amendment
  into the demo tenant, run Extraction and a Change Report once, leaving
  the artifacts as ordinary rows. It runs on demand (deploy or wipe), not
  per visitor, and doubles as sample data for local runs.
- **Roles stay two** (ADR-008). Visitors get the admin demo login, which
  already covers the full surface including dispositions; the reviewer
  login exists in the README for the review-only view.

## Rejected alternatives

- **Self-serve sandbox signup** — real provisioning flow + unlimited
  account creation against a shared budget, to serve an audience of
  one-at-a-time evaluators.
- **BYOK** — the tester has no OpenAI key of their own to bring; BYOK is a
  future cost pass-through feature for paying customers, not a demo gate.
- **Per-subject budgets inside the demo tenant** — fairness machinery for
  a collision (two evaluators in the same hour) that self-heals hourly and
  costs pennies; noted as the first thing to reach for if demo collisions
  actually bite.
- ** tenants table with a tier column** — one attribute today; hardcoded
  settings list until there are two.

## Consequences

- A visitor exhausting the demo budget gets 429 + `Retry-After`, sees the
  pre-seeded report anyway, and the window resets within the hour.
- The demo tenant's seeded rows are ordinary tenant data; the seed script
  can rebuild them after a wipe.
- If the demo ever becomes a sales funnel, the frontier moves to
  self-serve sandbox tenants (Auth0 self-signup + auto-provisioning) with
  per-tenant trial budgets — a new ADR, not an amendment of this one.
