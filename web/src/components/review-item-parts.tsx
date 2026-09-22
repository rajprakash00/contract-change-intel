// Structured rendering of a review item's payload, shared by the queue table
// (clamped) and the item detail page (full). Unknown shapes degrade to their
// raw JSON so every item shows something.

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { reviewPayloadFields } from "@/lib/review-payload";
import type { ReviewItemRead } from "@/lib/types";
import { ChangeKindBadge, SeverityBadge } from "@/components/status-badges";

export function ReviewItemFields({
  item,
  clamp = false,
}: {
  item: ReviewItemRead;
  clamp?: boolean;
}) {
  const fields = reviewPayloadFields(item.item_type, item.payload);

  if (fields.kind === "unknown") {
    return (
      <span
        className={`max-w-md font-mono text-xs text-muted-foreground ${
          clamp ? "line-clamp-2" : "break-words"
        }`}
      >
        {JSON.stringify(fields.raw)}
      </span>
    );
  }

  const obligation =
    fields.kind === "impact"
      ? fields.obligation
      : fields.kind === "obligation"
        ? {
            clauseRef: fields.clauseRef,
            description: fields.description,
            owner: fields.owner,
          }
        : null;

  return (
    <div className={clamp ? "max-w-md space-y-1.5" : "space-y-4"}>
      {fields.kind === "impact" && fields.change && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs">
          <ChangeKindBadge kind={fields.change.kind} />
          <SeverityBadge severity={fields.change.severity} />
          <span className={clamp ? "line-clamp-1 text-muted-foreground" : "text-muted-foreground"}>
            {fields.change.description}
          </span>
        </p>
      )}
      {obligation && (
        <div>
          <span className="font-mono text-xs text-muted-foreground">
            {obligation.clauseRef}
            {obligation.owner ? ` · ${obligation.owner}` : ""}
          </span>
          <p className={`text-sm leading-relaxed ${clamp ? "line-clamp-2" : "max-w-[70ch]"}`}>
            {obligation.description}
          </p>
        </div>
      )}
      {fields.kind === "defined_term" && (
        <div>
          <span className="font-mono text-xs text-muted-foreground">{fields.term}</span>
          <p className={`text-sm leading-relaxed ${clamp ? "line-clamp-2" : "max-w-[70ch]"}`}>
            {fields.definition}
          </p>
        </div>
      )}
      {fields.kind === "impact" && (
        <Link
          href={`/change-report-jobs/${item.job_id}`}
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          View change report
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      )}
    </div>
  );
}
