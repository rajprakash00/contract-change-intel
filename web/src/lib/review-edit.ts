// Structured editing of review-item payloads (W7·A): the reviewer corrects
// the fields they can judge — clause, owner, description, or a defined term —
// and the corrected payload keeps every other key (confidence, the source
// change block) untouched.

import { reviewPayloadFields } from "@/lib/review-payload";

export interface ReviewDraft {
  clauseRef: string;
  owner: string;
  description: string;
  term: string;
  definition: string;
}

const EMPTY_DRAFT: ReviewDraft = {
  clauseRef: "",
  owner: "",
  description: "",
  term: "",
  definition: "",
};

export function initialDraft(
  itemType: string,
  payload: Record<string, unknown>,
): ReviewDraft {
  const fields = reviewPayloadFields(itemType, payload);
  switch (fields.kind) {
    case "impact":
    case "obligation":
      return {
        ...EMPTY_DRAFT,
        clauseRef: fields.kind === "impact" ? fields.obligation.clauseRef : fields.clauseRef,
        owner:
          (fields.kind === "impact" ? fields.obligation.owner : fields.owner) ?? "",
        description:
          fields.kind === "impact" ? fields.obligation.description : fields.description,
      };
    case "defined_term":
      return { ...EMPTY_DRAFT, term: fields.term, definition: fields.definition };
    case "unknown":
      return EMPTY_DRAFT;
  }
}

export function buildCorrectedValues(
  itemType: string,
  payload: Record<string, unknown>,
  draft: ReviewDraft,
): Record<string, unknown> {
  const fields = reviewPayloadFields(itemType, payload);
  const owner = draft.owner.trim();
  switch (fields.kind) {
    case "impact":
    case "obligation":
      return {
        ...payload,
        clause_ref: draft.clauseRef.trim(),
        description: draft.description.trim(),
        owner: owner.length ? owner : null,
      };
    case "defined_term":
      return {
        ...payload,
        term: draft.term.trim(),
        definition: draft.definition.trim(),
      };
    case "unknown":
      // Unknown payload shapes are edited as raw JSON, never through the draft.
      return payload;
  }
}
