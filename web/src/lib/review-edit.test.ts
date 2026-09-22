import { describe, expect, it } from "vitest";

import { buildCorrectedValues, initialDraft } from "@/lib/review-edit";

const IMPACT_PAYLOAD = {
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
};

describe("initialDraft", () => {
  it("seeds impact fields from the obligation", () => {
    expect(initialDraft("impact", IMPACT_PAYLOAD)).toEqual({
      clauseRef: "2.1",
      owner: "Licensor",
      description: "Licensor shall deliver within 14 days.",
      term: "",
      definition: "",
    });
  });

  it("seeds defined-term fields", () => {
    expect(
      initialDraft("defined_term", { term: "Term", definition: "One year." }),
    ).toEqual({
      clauseRef: "",
      owner: "",
      description: "",
      term: "Term",
      definition: "One year.",
    });
  });

  it("seeds an empty draft for unknown payload shapes", () => {
    expect(initialDraft("obligation", { nonsense: true })).toEqual({
      clauseRef: "",
      owner: "",
      description: "",
      term: "",
      definition: "",
    });
  });
});

describe("buildCorrectedValues", () => {
  it("replaces the judged fields and preserves the rest of the payload", () => {
    const corrected = buildCorrectedValues("impact", IMPACT_PAYLOAD, {
      clauseRef: "2.2",
      owner: " plan_b ",
      description: "  plan_b shall pay within 30 days. ",
      term: "",
      definition: "",
    });

    expect(corrected).toEqual({
      clause_ref: "2.2",
      description: "plan_b shall pay within 30 days.",
      owner: "plan_b",
      confidence: 0.4,
      change: IMPACT_PAYLOAD.change,
    });
  });

  it("nulls an owner cleared by the reviewer", () => {
    const corrected = buildCorrectedValues("obligation", IMPACT_PAYLOAD, {
      clauseRef: "2.1",
      owner: "   ",
      description: "Licensor shall deliver within 14 days.",
      term: "",
      definition: "",
    });

    expect(corrected.owner).toBeNull();
  });

  it("edits defined terms without inventing obligation fields", () => {
    const payload = { term: "Term", definition: "One year.", confidence: 0.5 };
    const corrected = buildCorrectedValues("defined_term", payload, {
      clauseRef: "ignored",
      owner: "ignored",
      description: "ignored",
      term: "Initial Term",
      definition: "Two years.",
    });

    expect(corrected).toEqual({
      term: "Initial Term",
      definition: "Two years.",
      confidence: 0.5,
    });
  });

  it("returns unknown payloads untouched (they are edited as JSON)", () => {
    const payload = { surprise: "value" };
    const corrected = buildCorrectedValues("obligation", payload, {
      clauseRef: "1",
      owner: "x",
      description: "y",
      term: "",
      definition: "",
    });

    expect(corrected).toBe(payload);
  });
});
