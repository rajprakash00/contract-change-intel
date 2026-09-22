# ADR-012: Published Demo Access via a Sample Report and Visible Credentials

## Context

The product is a portfolio piece evaluated by strangers who arrive from a
GitHub profile, a CV, or a portfolio page. ADR-011 already publishes demo
credentials in the README and bounds demo spend with a reduced hourly budget,
but the arrival experience dead-ends: a signed-out visitor sees a landing page
with two sign-in buttons, and the credentials sit one file deep on GitHub. The
first interactive impression is an Auth0 login screen, not the product.

The product's value is a Change Report — what changed between two versions and
which obligations it touches. A visitor should be able to judge that value
before creating a session, and reach a working interactive demo in as few
steps as possible.

## Decision

**A public Sample Report plus visible, prefillable demo credentials; no
anonymous sessions.**

- **Sample Report is public.** A real Change Report produced by the pipeline
  for the demo tenant is committed as a JSON artifact (generator in
  `scripts/`) and rendered on the landing page for signed-out visitors. It is
  never a hand-written mockup — the artifact is regenerated from an actual
  run, so the landing page cannot drift from real output.
- **Demo credentials are shown on the landing page**, with a copy button. The
  "Try the demo" button starts the normal Auth0 PKCE flow with the demo email
  prefilled (`login_hint`); the visitor pastes the visible password. ADR-008
  stays intact: the API still accepts only Auth0-issued bearer tokens, and
  every visitor action lands in the audit log under the demo account.
- **The demo stays continuously available while published.** `api`, `ui`, and
  `worker` run at desired count 1 for the portfolio window;
  `scripts/demo-up.sh` / `demo-down.sh` are the documented lifecycle. The
  worker's return to idle-at-zero waits for W7·B queue-depth autoscaling.
- **Abuse stays bounded by ADR-011**: the demo tenant's reduced per-hour
  budget is the ceiling on anonymous-ish use; a 429 with `Retry-After` is
  acceptable product behavior.

## Rejected alternatives

- **Anonymous demo-session endpoint** minting scoped tokens for the demo
  tenant — smoothest UX, but a new token-issuing security surface that bends
  ADR-008's "identity comes only from the IdP" stance, plus abuse controls
  the hourly budget does not cover (upload volume, storage growth). If the
  demo ever becomes a sales funnel, this is a new ADR with a real threat
  model, not an amendment here.
- **Static mockup or video instead of a real Sample Report** — cheap, but a
  portfolio audience discounts mockups; a committed artifact from a real run
  is the honest version and is almost as cheap.
- **Request-a-demo form** — friction of a sales funnel with none of the
  funnel's value; the audience is evaluators, not buyers (ADR-011).
- **Keep credentials README-only** — the status quo this ADR exists to fix.

## Consequences

- Demo credentials are public by design; the demo tenant holds only demo
  content, and its budget bounds damage. Rotating them is a settings/Auth0
  action, not a schema change.
- The landing page carries a copy of report-shaped data; the artifact is
  regenerated (and committed) whenever the report payload changes, so the
  showcase cannot silently rot.
- Continuous availability adds roughly the three Fargate task costs to the
  monthly bill while the portfolio window is open; the down script is the
  documented exit.
