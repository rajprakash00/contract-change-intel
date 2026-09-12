// Shapes a review item's payload into the fields the queue renders as
// structured content (issue #21). Legacy rows predate the enriched payload
// (no `change` block) and unrecognized shapes degrade to their raw payload —
// the queue must render something for every item, whatever it carries.

export interface ReviewImpactFields {
  kind: "impact";
  obligation: { clauseRef: string; description: string; owner: string | null };
  change: {
    kind: string;
    clauseRef: string | null;
    severity: string;
    description: string;
  } | null;
}

export interface ReviewObligationFields {
  kind: "obligation";
  clauseRef: string;
  description: string;
  owner: string | null;
}

export interface ReviewDefinedTermFields {
  kind: "defined_term";
  term: string;
  definition: string;
}

export interface ReviewUnknownFields {
  kind: "unknown";
  raw: Record<string, unknown>;
}

export type ReviewPayloadFields =
  | ReviewImpactFields
  | ReviewObligationFields
  | ReviewDefinedTermFields
  | ReviewUnknownFields;

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function reviewPayloadFields(
  itemType: string,
  payload: Record<string, unknown>,
): ReviewPayloadFields {
  if (itemType === "impact") {
    if (!isRecord(payload) || typeof payload.clause_ref !== "string") {
      return { kind: "unknown", raw: payload };
    }
    const rawChange = payload.change;
    const change =
      isRecord(rawChange) &&
      typeof rawChange.kind === "string" &&
      typeof rawChange.severity === "string"
        ? {
            kind: rawChange.kind,
            clauseRef: asString(rawChange.clause_ref),
            severity: rawChange.severity,
            description: asString(rawChange.description) ?? "",
          }
        : null;
    return {
      kind: "impact",
      obligation: {
        clauseRef: payload.clause_ref,
        description: asString(payload.description) ?? "",
        owner: asString(payload.owner),
      },
      change,
    };
  }

  if (itemType === "obligation") {
    if (
      isRecord(payload) &&
      typeof payload.clause_ref === "string" &&
      typeof payload.description === "string"
    ) {
      return {
        kind: "obligation",
        clauseRef: payload.clause_ref,
        description: payload.description,
        owner: asString(payload.owner),
      };
    }
    return { kind: "unknown", raw: payload };
  }

  if (itemType === "defined_term") {
    if (
      isRecord(payload) &&
      typeof payload.term === "string" &&
      typeof payload.definition === "string"
    ) {
      return {
        kind: "defined_term",
        term: payload.term,
        definition: payload.definition,
      };
    }
    return { kind: "unknown", raw: payload };
  }

  return { kind: "unknown", raw: payload };
}
