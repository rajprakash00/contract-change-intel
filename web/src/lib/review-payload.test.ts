import { describe, expect, it } from "vitest";

import { reviewPayloadFields } from "@/lib/review-payload";

describe("reviewPayloadFields", () => {
  it("an enriched impact item yields the affected obligation and its source change", () => {
    const fields = reviewPayloadFields("impact", {
      clause_ref: "2.1",
      description: "Licensor shall deliver within 14 days.",
      owner: "Licensor",
      confidence: 0.4,
      change: {
        kind: "modified",
        clause_ref: "2.1",
        severity: "high",
        description: "The delivery window doubles.",
      },
    });

    expect(fields).toEqual({
      kind: "impact",
      obligation: {
        clauseRef: "2.1",
        description: "Licensor shall deliver within 14 days.",
        owner: "Licensor",
      },
      change: {
        kind: "modified",
        clauseRef: "2.1",
        severity: "high",
        description: "The delivery window doubles.",
      },
    });
  });

  it("a legacy impact item without the source change still yields the obligation", () => {
    const fields = reviewPayloadFields("impact", {
      clause_ref: "5.2",
      description: "The licensee shall not sublicense.",
      owner: null,
      confidence: 0.3,
    });

    expect(fields).toEqual({
      kind: "impact",
      obligation: {
        clauseRef: "5.2",
        description: "The licensee shall not sublicense.",
        owner: null,
      },
      change: null,
    });
  });

  it("a malformed change block degrades to change: null rather than throwing", () => {
    const fields = reviewPayloadFields("impact", {
      clause_ref: "2.1",
      description: "Licensor shall deliver within 14 days.",
      owner: "Licensor",
      change: "modified",
    });

    expect(fields).toMatchObject({ kind: "impact", change: null });
  });

  it("an obligation item yields its clause, description and owner", () => {
    const fields = reviewPayloadFields("obligation", {
      clause_ref: "7.3",
      description: "Licensee shall pay within 30 days.",
      owner: "Licensee",
      citation: { char_start: 10, char_end: 60 },
      confidence: 0.5,
    });

    expect(fields).toEqual({
      kind: "obligation",
      clauseRef: "7.3",
      description: "Licensee shall pay within 30 days.",
      owner: "Licensee",
    });
  });

  it("a defined term item yields its term and definition", () => {
    const fields = reviewPayloadFields("defined_term", {
      term: "Effective Date",
      definition: "The date this agreement takes effect.",
      citation: { char_start: 0, char_end: 40 },
      confidence: 0.6,
    });

    expect(fields).toEqual({
      kind: "defined_term",
      term: "Effective Date",
      definition: "The date this agreement takes effect.",
    });
  });

  it("an unrecognized payload shape falls back to the raw payload", () => {
    const payload = { odd: "shape" };
    expect(reviewPayloadFields("impact", payload)).toEqual({ kind: "unknown", raw: payload });
  });
});
