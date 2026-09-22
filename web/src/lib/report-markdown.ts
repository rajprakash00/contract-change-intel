// The change report as a shareable memo: "Copy as Markdown" on the report
// page. Pure and unit-tested — the page only wires the clipboard.

import type { ChangeReportJobRead } from "@/lib/types";

const SEVERITIES = ["high", "medium", "low"] as const;

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// Excerpts are contract text: blockquote so embedded Markdown (a clause
// starting with "#" or "-") cannot restructure the memo.
function quote(text: string): string {
  return text
    .split("\n")
    .map((line) => (line.length ? `> ${line}` : ">"))
    .join("\n");
}

export function reportToMarkdown(
  job: ChangeReportJobRead,
  documents: { base?: string; amended?: string } = {},
): string {
  const changes = job.result?.changes ?? [];
  const lines: string[] = ["# Change report", ""];
  if (documents.base) lines.push(`- Agreement: ${documents.base}`);
  if (documents.amended) lines.push(`- Amendment: ${documents.amended}`);
  lines.push(`- Generated: ${job.updated_at}`);
  lines.push(`- Changes: ${changes.length}`);

  for (const severity of SEVERITIES) {
    const group = changes.filter((change) => change.severity === severity);
    if (!group.length) continue;
    lines.push("", `## ${capitalize(severity)} severity`, "");
    for (const change of group) {
      lines.push(`### ${change.clause_ref ?? "Preamble"} (${change.kind})`, "");
      lines.push(change.description, "");
      if (change.base_excerpt) lines.push("**Before**", "", quote(change.base_excerpt), "");
      if (change.amended_excerpt) lines.push("**After**", "", quote(change.amended_excerpt), "");
      if (change.impacts.length) {
        lines.push("**Affected obligations**", "");
        for (const impact of change.impacts) {
          const owner = impact.owner ? ` · ${impact.owner}` : "";
          const confidence = Math.round(impact.confidence * 100);
          lines.push(
            `- ${impact.clause_ref}${owner} (${confidence}% confidence): ${impact.description}`,
          );
        }
        lines.push("");
      }
    }
  }
  return `${lines.join("\n").trimEnd()}\n`;
}
