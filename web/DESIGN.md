# Design

Ground truth is `src/app/globals.css` (Tailwind v4 `@theme inline` tokens);
this file records the intent so new work does not drift from it.

## Color

OKLCH throughout. Restrained strategy: tinted neutrals plus one ink-blue
accent for primary actions, selection, and state.

- Background `oklch(0.985 0.002 247)`, foreground `oklch(0.22 0.02 258)`
- Primary (ink blue) `oklch(0.38 0.075 258)`; dark mode lifts it to
  `oklch(0.72 0.07 258)`
- Severity: high uses `destructive`, medium `--severity-medium`
  (`oklch(0.75 0.12 75)`), low is muted
- Borders are hairlines (`oklch(0.912 0.008 253)`); no heavy rules
- Never pure black or white; every neutral carries a trace of the blue hue

## Typography

- UI and body: Geist Sans at a 17px base
- Display headings: Source Serif 4 (`--font-heading`) — the one carryover
  from the brand side; used for page and report headings, never for labels,
  buttons, or data
- Mono: Geist Mono for clause refs, character spans, IDs, confidence numbers
- Product scale, ~1.2 ratio between steps; no fluid clamp headings
- Prose capped near 70ch; tables and report rows may run denser

## Shape and elevation

- Radius `0.625rem` base (`--radius`), scaled tokens for smaller/larger
- Elevation is minimal: hairline borders and background tints carry
  structure; shadows are not a hierarchy tool here
- Cards only when a card is the right affordance; never nest them

## Components

- shadcn/ui vendored in `src/components/ui`; Radix supplies focus and
  keyboard behavior
- Status vocabulary: `JobStatusBadge`, `DocumentStatusBadge`,
  `ChangeKindBadge`, `SeverityBadge` in `src/components/status-badges.tsx`
- Loading uses skeletons (rows shaped like content), not centered spinners
  inside content
- Motion 150–250 ms, state changes only

## Layout

- Page chrome: `max-w-6xl`, `px-6 py-10`, sections at `space-y-8`
- Reading surfaces (report, documents) may go narrower for prose
- Responsive behavior is structural (columns collapse, tables scroll), not
  fluid type
