"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Check, Pencil, X } from "lucide-react";

import { errorMessage } from "@/lib/api";
import { useApi } from "@/lib/api-context";
import { Disposition, ReviewItemRead, ReviewItemStatus } from "@/lib/types";
import { DataTable, EmptyState, TableSkeleton } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const STATUS_FILTERS: ("all" | ReviewItemStatus)[] = [
  "all",
  "pending",
  "approved",
  "edited",
  "rejected",
];

const columnHelper = createColumnHelper<ReviewItemRead>();

export default function ReviewQueuePage() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"all" | ReviewItemStatus>("pending");
  const [editing, setEditing] = useState<ReviewItemRead | null>(null);

  const items = useQuery({
    queryKey: ["review-items", statusFilter],
    queryFn: () =>
      api.listReviewItems(statusFilter === "all" ? undefined : statusFilter),
  });

  const resolve = useMutation({
    mutationFn: ({
      itemId,
      disposition,
      correctedValues,
    }: {
      itemId: string;
      disposition: Disposition;
      correctedValues?: object;
    }) => api.resolveReviewItem(itemId, disposition, correctedValues),
    onSuccess: () => {
      toast.success("Disposition recorded");
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ["review-items"] });
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not record disposition")),
  });

  const data = items.data?.items ?? [];
  const columns = useMemo(
    () => [
      columnHelper.accessor("source", {
        header: "Source",
        cell: (info) => (
          <Badge variant="outline">{info.getValue().replace("_", " ")}</Badge>
        ),
      }),
      columnHelper.accessor("payload", {
        header: "Item",
        cell: (info) => <PayloadSummary payload={info.getValue()} />,
      }),
      columnHelper.accessor("confidence", {
        header: "Confidence",
        cell: (info) => (
          <span className="font-mono text-xs tabular-nums">
            {Math.round(info.getValue() * 100)}%
          </span>
        ),
      }),
      columnHelper.accessor("status", {
        header: "Status",
        cell: (info) => <Badge variant="secondary">{info.getValue()}</Badge>,
      }),
      columnHelper.display({
        id: "actions",
        cell: (info) => {
          const item = info.row.original;
          if (item.status !== "pending") return null;
          return (
            <div className="flex justify-end gap-1">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Approve"
                onClick={() =>
                  resolve.mutate({ itemId: item.id, disposition: "approved" })
                }
              >
                <Check aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Edit"
                onClick={() => setEditing(item)}
              >
                <Pencil aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Reject"
                onClick={() =>
                  resolve.mutate({ itemId: item.id, disposition: "rejected" })
                }
              >
                <X aria-hidden />
              </Button>
            </div>
          );
        },
      }),
    ],
    [resolve],
  );

  // Known React Compiler incompatibility in @tanstack/react-table v8: the
  // compiler just skips memoizing this component (informational warning).
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-8">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Review queue</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Output whose confidence fell below the threshold, routed here for human
            triage.
          </p>
        </div>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as typeof statusFilter)}>
          <SelectTrigger className="w-40" aria-label="Filter by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((status) => (
              <SelectItem key={status} value={status}>
                {status === "all" ? "All statuses" : status}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {items.isLoading ? (
        <TableSkeleton />
      ) : !data.length ? (
        <EmptyState>Nothing here — the queue is clear.</EmptyState>
      ) : (
        <DataTable table={table} />
      )}

      <EditDialog
        item={editing}
        pending={resolve.isPending}
        onSubmit={(corrected) =>
          editing &&
          resolve.mutate({ itemId: editing.id, disposition: "edited", correctedValues: corrected })
        }
        onOpenChange={(open) => !open && setEditing(null)}
      />
    </div>
  );
}

// The queue must show *something* for each item without knowing every payload
// shape; render the JSON compactly (thin UI, primitives over abstractions).
function PayloadSummary({ payload }: { payload: Record<string, unknown> }) {
  return (
    <span className="line-clamp-2 max-w-md font-mono text-xs text-muted-foreground">
      {JSON.stringify(payload)}
    </span>
  );
}

function EditDialog({
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
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Re-seed the textarea whenever a different item is opened for editing.
  const [seededFor, setSeededFor] = useState<string | null>(null);
  if (item && seededFor !== item.id) {
    setSeededFor(item.id);
    setText(JSON.stringify(item.payload, null, 2));
    setError(null);
  }

  function submit() {
    // The API requires corrected_values to be a JSON object (dict) — catch
    // null/arrays/scalars here with a real message instead of an opaque 422.
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError("Corrected values must be valid JSON.");
      return;
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      setError("Corrected values must be a JSON object, e.g. {\"description\": …}.");
      return;
    }
    setError(null);
    onSubmit(parsed as Record<string, unknown>);
  }

  return (
    <Dialog open={item !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit resolved values</DialogTitle>
          <DialogDescription>
            The corrected JSON replaces the recorded payload for this item.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          rows={12}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="font-mono text-xs"
          aria-label="Corrected values"
        />
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
