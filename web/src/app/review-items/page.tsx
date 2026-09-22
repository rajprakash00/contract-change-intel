"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import Link from "next/link";
import { ArrowUpRight, Check, Pencil, X } from "lucide-react";

import { errorMessage } from "@/lib/api";
import { useApi } from "@/lib/api-context";
import { Disposition, ReviewItemRead, ReviewItemStatus } from "@/lib/types";
import { DataTable, EmptyState, TableSkeleton } from "@/components/data-table";
import { ReviewEditDialog } from "@/components/review-edit-dialog";
import { ReviewItemFields } from "@/components/review-item-parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
        cell: (info) => <ReviewItemFields item={info.row.original} clamp />,
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
          return (
            <div className="flex justify-end gap-1">
              <Button variant="ghost" size="icon" aria-label="Open item" asChild>
                <Link href={`/review-items/${item.id}`}>
                  <ArrowUpRight aria-hidden />
                </Link>
              </Button>
              {item.status === "pending" && (
                <>
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
                </>
              )}
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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Review queue</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Output whose confidence fell below the threshold, routed here for human
            triage.
          </p>
        </div>
        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as typeof statusFilter)}
        >
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
        <EmptyState>Nothing here. The queue is clear.</EmptyState>
      ) : (
        <DataTable table={table} />
      )}

      <ReviewEditDialog
        item={editing}
        pending={resolve.isPending}
        onSubmit={(corrected) =>
          editing &&
          resolve.mutate({
            itemId: editing.id,
            disposition: "edited",
            correctedValues: corrected,
          })
        }
        onOpenChange={(open) => !open && setEditing(null)}
      />
    </div>
  );
}
