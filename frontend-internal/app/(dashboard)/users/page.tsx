"use client";

import { useMemo, useState } from "react";
import { Pencil, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { UserFormDialog } from "@/components/users/user-form-dialog";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { useDeleteUser, useUsersList } from "@/lib/hooks/use-users";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { asApiError } from "@/lib/api/client";
import type { User } from "@/lib/api/types";

export default function UsersPage() {
  const [page, setPage] = useState(1);
  const [nameRaw, setNameRaw] = useState("");
  const [puskesmasId, setPuskesmasIdRaw] = useState<string | undefined>(undefined);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  const setName = (v: string) => { setNameRaw(v); setPage(1); };
  const setPuskesmasId = (v: string | undefined) => { setPuskesmasIdRaw(v); setPage(1); };

  const debouncedName = useDebouncedValue(nameRaw);
  const query = useMemo(
    () => ({
      page,
      size: 20,
      full_name: debouncedName.trim() || undefined,
      puskesmas_id: puskesmasId,
    }),
    [page, debouncedName, puskesmasId],
  );
  const list = useUsersList(query);
  const filterPkDetail = usePuskesmas(puskesmasId);
  const del = useDeleteUser();

  const hasFilters = debouncedName.trim() !== "" || puskesmasId !== undefined;

  const handleDelete = async () => {
    if (!deleting) return;
    try {
      await del.mutateAsync(deleting.id);
      toast.success("Pengguna dihapus");
      setDeleting(null);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pengguna"
        description="Akun pengguna yang terhubung ke puskesmas."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            Pengguna Baru
          </Button>
        }
      />

      <div className="flex flex-wrap gap-3">
        <div className="relative max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-[var(--muted-foreground)]" />
          <Input
            placeholder="Cari berdasarkan nama…"
            value={nameRaw}
            onChange={(e) => setName(e.target.value)}
            className="pl-8"
          />
        </div>
        <div className="w-[220px]">
          <AsyncCombobox
            value={puskesmasId}
            onChange={setPuskesmasId}
            useOptions={usePuskesmasOptions}
            selectedLabel={filterPkDetail.data?.name}
            allOptionLabel="Semua puskesmas"
          />
        </div>
      </div>

      {list.error && <ErrorState error={list.error} />}

      <div className="rounded-lg border border-[var(--border)]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nama lengkap</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Puskesmas</TableHead>
              <TableHead className="w-[120px]">Aksi</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data?.items.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">{u.full_name}</TableCell>
                <TableCell className="text-[var(--muted-foreground)]">
                  {u.email}
                </TableCell>
                <TableCell>{u.puskesmas_name}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setEditing(u)}
                      className="h-8 w-8"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDeleting(u)}
                      className="h-8 w-8 text-[var(--destructive)]"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {list.data && list.data.items.length === 0 && (
          <div className="p-6">
            <EmptyState
              title={hasFilters ? "Tidak ada yang cocok" : "Belum ada pengguna"}
              description={
                hasFilters
                  ? "Tidak ada yang cocok. Coba kata kunci atau filter lain."
                  : undefined
              }
            />
          </div>
        )}
      </div>

      {list.data && (
        <Pagination
          page={list.data.page}
          pages={list.data.pages}
          total={list.data.total}
          onPageChange={setPage}
        />
      )}

      <UserFormDialog
        open={createOpen || !!editing}
        onOpenChange={(v) => {
          if (!v) {
            setCreateOpen(false);
            setEditing(null);
          }
        }}
        user={editing ?? undefined}
      />

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(v) => !v && setDeleting(null)}
        title="Hapus pengguna?"
        description={
          deleting ? `${deleting.email} akan dihapus.` : undefined
        }
        confirmLabel="Hapus"
        destructive
        loading={del.isPending}
        onConfirm={handleDelete}
      />
    </div>
  );
}
