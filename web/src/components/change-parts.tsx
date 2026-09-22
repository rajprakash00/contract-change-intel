// Change rendering shared by the change report page and the landing sample
// report: the before/after wording and the affected-obligation list.

import { cn } from "@/lib/utils";
import type { Change, ChangeImpact, ChangeSpan } from "@/lib/types";

export function ChangeExcerpts({ change }: { change: Change }) {
  const blocks: { label: string; text: string; span: ChangeSpan | null }[] = [];
  if (change.base_excerpt) {
    blocks.push({ label: "Before", text: change.base_excerpt, span: change.base_span });
  }
  if (change.amended_excerpt) {
    blocks.push({ label: "After", text: change.amended_excerpt, span: change.amended_span });
  }
  if (!blocks.length) return <SpanFallback change={change} />;
  return (
    <div className={cn("grid gap-3", blocks.length === 2 && "md:grid-cols-2")}>
      {blocks.map((block) => {
        const truncated = block.span
          ? block.span.char_end - block.span.char_start > block.text.length
          : false;
        return (
          <figure key={block.label} className="rounded-md bg-muted/60 px-3 py-2">
            <figcaption className="mb-1 text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">
              {block.label}
            </figcaption>
            <div className="max-h-80 overflow-auto overscroll-contain print:max-h-none print:overflow-visible">
              <p className="whitespace-pre-wrap font-heading text-[0.9375rem] leading-relaxed">
                {block.text}
              </p>
            </div>
            {truncated && (
              <p className="mt-1 text-[0.6875rem] text-muted-foreground">
                excerpt truncated; open the document for the full clause
              </p>
            )}
          </figure>
        );
      })}
    </div>
  );
}

// Reports generated before excerpts were stored carry only char spans; show
// them rather than nothing.
function SpanFallback({ change }: { change: Change }) {
  const spans: [string, ChangeSpan][] = [];
  if (change.base_span) spans.push(["base", change.base_span]);
  if (change.amended_span) spans.push(["amended", change.amended_span]);
  if (!spans.length) return null;
  return (
    <p className="font-mono text-xs text-muted-foreground">
      {spans.map(([label, span]) => `${label} ${span.char_start}–${span.char_end}`).join(" · ")}
      {" · "}
      <span className="font-sans">excerpt unavailable in this older report</span>
    </p>
  );
}

export function ImpactList({ impacts }: { impacts: ChangeImpact[] }) {
  if (!impacts.length) return null;
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Affected obligations <span className="font-mono">{impacts.length}</span>
      </h3>
      <ul className="mt-1 divide-y">
        {impacts.map((impact, index) => (
          <li
            key={`${impact.clause_ref}-${impact.owner ?? ""}-${index}`}
            className="py-2 first:pt-1 last:pb-0"
          >
            <div className="flex items-baseline justify-between gap-4">
              <span className="font-mono text-xs text-muted-foreground">
                {impact.clause_ref}
                {impact.owner ? ` · ${impact.owner}` : ""}
              </span>
              <span
                className="font-mono text-xs tabular-nums text-muted-foreground"
                title="Model-reported confidence (ADR-007)"
              >
                {Math.round(impact.confidence * 100)}%
              </span>
            </div>
            <p className="mt-1 max-w-[70ch] text-sm leading-relaxed">{impact.description}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
