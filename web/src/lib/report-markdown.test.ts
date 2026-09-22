import { describe, expect, it } from "vitest";

import { reportToMarkdown } from "@/lib/report-markdown";
import type { ChangeReportJobRead } from "@/lib/types";

function job(changes: ChangeReportJobRead["result"]): ChangeReportJobRead {
  return {
    id: "job-1",
    tenant_id: "tenant-1",
    base_document_id: "base-1",
    amended_document_id: "amended-1",
    status: "completed",
    result: changes,
    error: null,
    created_at: "2026-09-22T09:00:00+00:00",
    updated_at: "2026-09-22T09:01:00+00:00",
  };
}

describe("reportToMarkdown", () => {
  it("groups changes by severity, high first", () => {
    const markdown = reportToMarkdown(
      job({
        changes: [
          {
            kind: "modified",
            clause_ref: "2.1",
            base_span: null,
            amended_span: null,
            description: "Delivery window doubles.",
            severity: "medium",
            impacts: [],
          },
          {
            kind: "removed",
            clause_ref: "2.2",
            base_span: null,
            amended_span: null,
            description: "Term clause removed.",
            severity: "high",
            impacts: [],
          },
        ],
      }),
    );

    const high = markdown.indexOf("## High severity");
    const medium = markdown.indexOf("## Medium severity");
    expect(high).toBeGreaterThan(-1);
    expect(medium).toBeGreaterThan(high);
    expect(markdown).toContain("### 2.2 (removed)");
    expect(markdown).toContain("### 2.1 (modified)");
  });

  it("renders one-sided excerpts for added and removed changes", () => {
    const markdown = reportToMarkdown(
      job({
        changes: [
          {
            kind: "added",
            clause_ref: "9.1",
            base_span: null,
            amended_span: null,
            base_excerpt: null,
            amended_excerpt: "9.1 Renewal\n\nAutomatic.",
            description: "Renewal added.",
            severity: "low",
            impacts: [],
          },
        ],
      }),
    );

    expect(markdown).not.toContain("**Before**");
    expect(markdown).toContain("**After**");
    expect(markdown).toContain("> 9.1 Renewal");
    expect(markdown).toContain("> Automatic.");
  });

  it("keeps contract lines that start with markdown syntax inside the quote", () => {
    const markdown = reportToMarkdown(
      job({
        changes: [
          {
            kind: "modified",
            clause_ref: "3",
            base_span: null,
            amended_span: null,
            base_excerpt: "# not a heading",
            amended_excerpt: "- not a list",
            description: "Wording changed.",
            severity: "medium",
            impacts: [],
          },
        ],
      }),
    );

    expect(markdown).toContain("> # not a heading");
    expect(markdown).toContain("> - not a list");
    expect(markdown).not.toContain("\n# not a heading");
  });

  it("lists impacts with owner and rounded confidence", () => {
    const markdown = reportToMarkdown(
      job({
        changes: [
          {
            kind: "modified",
            clause_ref: "2.1",
            base_span: null,
            amended_span: null,
            description: "Delivery window doubles.",
            severity: "high",
            impacts: [
              {
                clause_ref: "2.1",
                description: "Licensor shall deliver within 14 days.",
                owner: "Licensor",
                confidence: 0.8,
              },
              {
                clause_ref: "3.1",
                description: "Plan B shall pay on time.",
                owner: null,
                confidence: 0.667,
              },
            ],
          },
        ],
      }),
    );

    expect(markdown).toContain(
      "- 2.1 · Licensor (80% confidence): Licensor shall deliver within 14 days.",
    );
    expect(markdown).toContain("- 3.1 (67% confidence): Plan B shall pay on time.");
  });

  it("names the compared documents when they are known", () => {
    const markdown = reportToMarkdown(job({ changes: [] }), {
      base: "agreement.pdf",
      amended: "amendment.pdf",
    });

    expect(markdown).toContain("- Agreement: agreement.pdf");
    expect(markdown).toContain("- Amendment: amendment.pdf");
    expect(markdown).toContain("- Changes: 0");
  });

  it("omits the excerpt sections for reports generated before excerpts landed", () => {
    const markdown = reportToMarkdown(
      job({
        changes: [
          {
            kind: "modified",
            clause_ref: "2.1",
            base_span: { char_start: 0, char_end: 10 },
            amended_span: { char_start: 0, char_end: 12 },
            description: "Delivery window doubles.",
            severity: "medium",
            impacts: [],
          },
        ],
      }),
    );

    expect(markdown).not.toContain("**Before**");
    expect(markdown).not.toContain("**After**");
    expect(markdown).toContain("Delivery window doubles.");
  });
});
