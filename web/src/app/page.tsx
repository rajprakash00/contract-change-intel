"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useAuth0 } from "@auth0/auth0-react";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { Plus, Trash2 } from "lucide-react";

import { errorMessage } from "@/lib/api";
import { useApi } from "@/lib/api-context";
import { isAdmin } from "@/lib/roles";
import { DocumentListPage, DocumentRead } from "@/lib/types";
import { DataTable, EmptyState, TableSkeleton } from "@/components/data-table";
import { DocumentStatusBadge } from "@/components/status-badges";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const uploadFormSchema = z.object({
  file: z.instanceof(File, { message: "Choose a document to upload" }),
  amendsDocumentId: z.string().optional(),
});

type UploadFormValues = z.infer<typeof uploadFormSchema>;

const columnHelper = createColumnHelper<DocumentRead>();

export default function DocumentsPage() {
  const { user } = useAuth0();
  const admin = isAdmin(user);
  const api = useApi();
  const queryClient = useQueryClient();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DocumentRead | null>(null);

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api.listDocuments(),
  });

  const remove = useMutation({
    mutationFn: (documentId: string) => api.deleteDocument(documentId),
    onSuccess: (_data, documentId) => {
      toast.success("Document deleted");
      setDeleteTarget(null);
      queryClient.setQueryData<DocumentListPage>(["documents"], (page) =>
        page
          ? {
              ...page,
              items: page.items.filter((d) => d.id !== documentId),
              total: page.total - 1,
            }
          : page,
      );
    },
    onError: (error) => toast.error(errorMessage(error, "Delete failed")),
  });

  const columns = useMemo(
    () => [
      columnHelper.accessor("filename", {
        header: "Document",
        cell: (info) => (
          <Link href={`/documents/${info.row.original.id}`} className="font-medium hover:underline">
            {info.getValue()}
          </Link>
        ),
      }),
      columnHelper.accessor("status", {
        header: "Status",
        cell: (info) => <DocumentStatusBadge status={info.getValue()} />,
      }),
      columnHelper.accessor("amends_document_id", {
        header: "Amends",
        cell: (info) => (
          <span className="text-muted-foreground">
            {info.getValue() ? "amendment" : "agreement"}
          </span>
        ),
      }),
      ...(admin
        ? [
            columnHelper.display({
              id: "actions",
              cell: (info) => (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete ${info.row.original.filename}`}
                  onClick={() => setDeleteTarget(info.row.original)}
                >
                  <Trash2 aria-hidden />
                </Button>
              ),
            }),
          ]
        : []),
    ],
    [admin],
  );

  // Known React Compiler incompatibility in @tanstack/react-table v8: the
  // compiler just skips memoizing this component (informational warning).
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: documents.data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-8">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Documents</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Agreements and their amendments, with ingestion status.
          </p>
        </div>
        {admin && (
          <Button onClick={() => setUploadOpen(true)}>
            <Plus aria-hidden />
            Upload document
          </Button>
        )}
      </div>

      {documents.isLoading ? (
        <TableSkeleton />
      ) : documents.error ? (
        <p className="text-sm text-destructive">
          Could not load documents. Is the API running?
        </p>
      ) : !documents.data?.items.length ? (
        <EmptyState>No documents yet.</EmptyState>
      ) : (
        <DataTable table={table} />
      )}

      {admin && (
        <UploadDialog
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          documents={documents.data?.items ?? []}
        />
      )}

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{deleteTarget?.filename}”?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the document and its stored file. Documents
              with amendments cannot be deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => deleteTarget && remove.mutate(deleteTarget.id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function UploadDialog({
  open,
  onOpenChange,
  documents,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documents: DocumentRead[];
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const form = useForm<UploadFormValues>({
    resolver: zodResolver(uploadFormSchema),
    defaultValues: { amendsDocumentId: "" },
  });

  const upload = useMutation({
    mutationFn: (values: UploadFormValues) =>
      api.uploadDocument(values.file, values.amendsDocumentId || undefined),
    onSuccess: (document) => {
      toast.success(`Uploaded ${document.filename}`);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      onOpenChange(false);
      form.reset();
    },
    onError: (error) => toast.error(errorMessage(error, "Upload failed")),
  });

  const parents = documents.filter((d) => !d.amends_document_id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload document</DialogTitle>
          <DialogDescription>
            Drop in an agreement, or an amendment that refines one already here.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className="space-y-5"
            onSubmit={form.handleSubmit((values) => upload.mutate(values))}
          >
            <FormField
              control={form.control}
              name="file"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Document</FormLabel>
                  <FormControl>
                    <Input
                      // Browser-managed value: RHF only needs the picked File.
                      type="file"
                      accept=".pdf,.docx,.txt"
                      name={field.name}
                      onBlur={field.onBlur}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) field.onChange(file);
                      }}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="amendsDocumentId"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Amends (optional)</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Not an amendment" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {parents.map((parent) => (
                        <SelectItem key={parent.id} value={parent.id}>
                          {parent.filename}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={upload.isPending}>
                {upload.isPending ? "Uploading…" : "Upload"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
