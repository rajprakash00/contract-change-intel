# Product

register: product

## Users

Two audiences, one interface:

- **The working user** — a reviewer or admin at a tenant: legal ops, contract
  management, or an AI engineer running the pipeline on real agreements. They
  are mid-task, read dense documents, and judge the system by whether the
  change report is faster to trust than reading both versions.
- **The evaluating visitor** — an engineer or hiring manager arriving from a
  portfolio link. They decide in seconds whether the product is real; the
  landing showcase and the demo flow are the first impression, not marketing.

## Purpose

Upload an agreement and its amendments. Extract obligations with citations and
confidence. Explain the version diff clause by clause and map each change onto
the obligations it affects. Route low-confidence output to a human review
queue. Multi-tenant, audited, OIDC-authenticated.

## Tone

Calm legal-tech: precise, restrained, document-first. A well-made internal
tool at a law firm. Dense where the work is dense, quiet everywhere else.
Confidence and citations are shown, never decorative.

## Anti-references

- Dashboard-SaaS neon, gradient hero metrics, glassmorphism
- Consumer-AI chat skins, sparkles, "magic" copy
- Cards inside cards; identical card grids as a layout system
- Playful motion; anything that delays the reader

## Strategic principles

1. **The change report is the product.** What changed must be legible before
   the model's explanation of it: show the wording, then the commentary.
2. **Provenance is first-class.** Citations, confidence, and job metadata are
   available at the point of reading, not buried in an admin view.
3. **Earned familiarity.** Standard product patterns over invented ones; the
   tool disappears into the task.
4. **Every empty and error state offers the next action**, or teaches the
   interface. "Nothing here" is not a state.
5. **Light-first, dark is real.** The dark token set is a supported mode, not
   a demo skin.
