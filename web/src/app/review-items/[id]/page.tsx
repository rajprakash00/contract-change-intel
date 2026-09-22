"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Pencil, X } from "lucide-react";
import { toast } from "sonner";

import { errorMessage, loadErrorMessage } from "@/lib/api";
import { useApi } from "@/lib/api-context";
import { ReviewEditDialog } from "@/components/review-edit-dialog";
import { ReviewItemFields } from "@/components/review-item-parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export default function ReviewItemPage() {
  const params = useParams<{ id: string }>();
  const itemId = params.id;
  const api = useApi();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);

  const item = useQuery({
    queryKey: ["review-item", itemId],
    queryFn: () => api.getReviewItem(itemId),
  });

  const resolve = useMutation({
    mutationFn: (disposition: "approved" | "rejected") =>
      api.resolveReviewItem(itemId, disposition),
    onSuccess: (_data, disposition) => {
      toast.success(`Item ${disposition}`);
      queryClient.invalidateQueries({ queryKey: ["review-item", itemId] });
      queryClient.invalidateQueries({ queryKey: ["review-items"] });
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not record disposition")),
  });

  const edit = useMutation({
    mutationFn: (corrected: Record<string, unknown>) =>
      api.resolveReviewItem(itemId, "edited", corrected),
    onSuccess: () => {
      toast.success("Disposition recorded");
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["review-item", itemId] });
      queryClient.invalidateQueries({ queryKey: ["review-items"] });
    },
    onError: (error) => toast.error(errorMessage(error, "Could not record disposition")),
  });

  if (item.isError) {
    return (
      <div className="mx-auto max-w-lg space-y-4 rounded-lg border bg-card p-10 text-center">
        <p className="text-sm text-muted-foreground">{loadErrorMessage(item.error)}</p>
        <Button variant="outline" size="sm" onClick={() => void item.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (item.isLoading || !item.data) {
    return (
      <div className="mx-auto max-w-3xl space-y-6" aria-busy="true" aria-label="Loading item">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const data = item.data;

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <Link
        href="/review-items"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Back to review queue
      </Link>

      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">Review item</h1>
          <Badge variant="outline">{data.source.replace("_", " ")}</Badge>
          <Badge variant="secondary">{data.status}</Badge>
          <span
            className="ml-auto font-mono text-sm tabular-nums text-muted-foreground"
            title="Model-reported confidence (ADR-007)"
          >
            {Math.round(data.confidence * 100)}% confidence
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Routed here because confidence fell below the threshold. A reviewer&apos;s
          disposition is terminal.
        </p>
      </header>

      <section className="rounded-lg border bg-card p-5">
        <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Recorded values
        </h2>
        <div className="mt-3">
          <ReviewItemFields item={data} />
        </div>
      </section>

      {data.corrected_values && (
        <section className="rounded-lg border bg-card p-5">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Corrected values
          </h2>
          <div className="mt-3">
            <ReviewItemFields item={{ ...data, payload: data.corrected_values }} />
          </div>
        </section>
      )}

      <section className="space-y-2 text-sm text-muted-foreground">
        <p>
          Document:{" "}
          <Link
            href={`/documents/${data.document_id}`}
            className="text-primary hover:underline"
          >
            open document
          </Link>
        </p>
        <p>Created {DATE_FORMAT.format(new Date(data.created_at))}</p>
        {data.resolved_at && <p>Resolved {DATE_FORMAT.format(new Date(data.resolved_at))}</p>}
        <p className="font-mono text-xs">item {data.id}</p>
      </section>

      {data.status === "pending" && (
        <div className="flex flex-wrap gap-2 print:hidden">
          <Button onClick={() => resolve.mutate("approved")} disabled={resolve.isPending}>
            <Check aria-hidden />
            Approve
          </Button>
          <Button variant="outline" onClick={() => setEditing(true)}>
            <Pencil aria-hidden />
            Edit
          </Button>
          <Button
            variant="destructive"
            onClick={() => resolve.mutate("rejected")}
            disabled={resolve.isPending}
          >
            <X aria-hidden />
            Reject
          </Button>
        </div>
      )}

      <ReviewEditDialog
        item={editing ? data : null}
        pending={edit.isPending}
        onSubmit={(corrected) => edit.mutate(corrected)}
        onOpenChange={(open) => !open && setEditing(false)}
      />
    </div>
  );
}
