"use client";

// Structured correction of a review item (W7·A): the reviewer edits the
// fields they can judge; everything else in the payload is preserved. Unknown
// payload shapes fall back to raw-JSON editing.

import { useState } from "react";

import { buildCorrectedValues, initialDraft, type ReviewDraft } from "@/lib/review-edit";
import { reviewPayloadFields } from "@/lib/review-payload";
import type { ReviewItemRead } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export function ReviewEditDialog({
  item,
  pending,
  onSubmit,
  onOpenChange,
}: {
  item: ReviewItemRead | null;
  pending: boolean;
  onSubmit: (corrected: Record<string, unknown>) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  const [jsonText, setJsonText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [seededFor, setSeededFor] = useState<string | null>(null);

  // Re-seed the form whenever a different item is opened for editing.
  if (item && seededFor !== item.id) {
    setSeededFor(item.id);
    setDraft(initialDraft(item.item_type, item.payload));
    setJsonText(JSON.stringify(item.payload, null, 2));
    setError(null);
  }

  const fields = item ? reviewPayloadFields(item.item_type, item.payload) : null;

  function submit() {
    if (!item || !fields || !draft) return;
    if (fields.kind === "unknown") {
      // The API requires corrected_values to be a JSON object (dict) — catch
      // null/arrays/scalars here with a real message instead of an opaque 422.
      let parsed: unknown;
      try {
        parsed = JSON.parse(jsonText);
      } catch {
        setError("Corrected values must be valid JSON.");
        return;
      }
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        setError('Corrected values must be a JSON object, e.g. {"description": "…"}.');
        return;
      }
      setError(null);
      onSubmit(parsed as Record<string, unknown>);
      return;
    }
    const missing =
      fields.kind === "defined_term"
        ? !draft.term.trim() || !draft.definition.trim()
        : !draft.clauseRef.trim() || !draft.description.trim();
    if (missing) {
      setError(
        fields.kind === "defined_term"
          ? "Term and definition are required."
          : "Clause reference and description are required.",
      );
      return;
    }
    setError(null);
    onSubmit(buildCorrectedValues(item.item_type, item.payload, draft));
  }

  return (
    <Dialog open={item !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Correct the extracted values</DialogTitle>
          <DialogDescription>
            The corrected values replace the recorded payload for this item.
            Everything you do not change is kept.
          </DialogDescription>
        </DialogHeader>

        {fields?.kind === "unknown" ? (
          <Textarea
            rows={12}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            className="font-mono text-xs"
            aria-label="Corrected values"
          />
        ) : fields?.kind === "defined_term" ? (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="review-term">Term</Label>
              <Input
                id="review-term"
                value={draft?.term ?? ""}
                onChange={(e) => setDraft((d) => d && { ...d, term: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="review-definition">Definition</Label>
              <Textarea
                id="review-definition"
                rows={4}
                value={draft?.definition ?? ""}
                onChange={(e) => setDraft((d) => d && { ...d, definition: e.target.value })}
              />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="review-clause">Clause reference</Label>
                <Input
                  id="review-clause"
                  value={draft?.clauseRef ?? ""}
                  onChange={(e) =>
                    setDraft((d) => d && { ...d, clauseRef: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="review-owner">Owner</Label>
                <Input
                  id="review-owner"
                  value={draft?.owner ?? ""}
                  onChange={(e) => setDraft((d) => d && { ...d, owner: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="review-description">Description</Label>
              <Textarea
                id="review-description"
                rows={4}
                value={draft?.description ?? ""}
                onChange={(e) =>
                  setDraft((d) => d && { ...d, description: e.target.value })
                }
              />
            </div>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" onClick={submit} disabled={pending}>
            Save disposition
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
