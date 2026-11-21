"use client";

import Link from "next/link";
import { useState } from "react";
import { format, parseISO } from "date-fns";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CronRunStatusBadge } from "@/components/cron/cron-run-status-badge";
import { CronBackfillStatusBadge } from "@/components/cron/cron-backfill-status-badge";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { useCronBackfillChildRuns } from "@/lib/hooks/use-cron-backfill";
import type { CronBackfill } from "@/lib/api/types";
import { STEP_LABEL } from "@/lib/source-names";

export function CronBackfillDetailDialog({
  open,
  onOpenChange,
  backfill,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  backfill: CronBackfill | null;
}) {
  const [page, setPage] = useState(1);
  const runs = useCronBackfillChildRuns(
    backfill?.id,
    { page, size: 50 },
    open && !!backfill,
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setPage(1);
        onOpenChange(v);
      }}
    >
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {backfill
              ? `Rentang tanggal: ${backfill.puskesmas_name}`
              : "Rentang tanggal"}
          </DialogTitle>
          <DialogDescription>
            {backfill
              ? `${backfill.date_from} → ${backfill.date_to} · ${backfill.completed_dates}/${backfill.total_dates} selesai`
              : ""}
          </DialogDescription>
        </DialogHeader>

        {backfill && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--muted-foreground)]">
              <CronBackfillStatusBadge status={backfill.status} />
              {backfill.cursor_date && (
                <span>Posisi: {backfill.cursor_date}</span>
              )}
              {backfill.failed_date && (
                <span className="text-[var(--destructive)]">
                  Gagal pada {backfill.failed_date}
                </span>
              )}
              {backfill.mandiri_only && (
                <span>Pemeriksaan Mandiri saja (ASIK)</span>
              )}
              {!backfill.mandiri_only &&
                backfill.source_scope === "epus_only" && (
                  <span>Medisy saja</span>
                )}
              {!backfill.mandiri_only &&
                backfill.source_scope === "asik_only" && (
                  <span>ASIK saja</span>
                )}
              {backfill.source_scope === "none" && (
                <span>Kirim ke ASIK saja (tanpa ambil ulang)</span>
              )}
              {backfill.merge_mode === "force_remerge" && (
                <span>Gabung ulang paksa</span>
              )}
              {backfill.merge_mode === "no_merge" && (
                <span>Tanpa gabung (ambil data saja)</span>
              )}
              {backfill.sync_mode !== "off" && (
                <span>
                  Isi pemeriksaan ASIK
                  {backfill.sync_mode === "force_resync" ? " (paksa)" : ""}
                </span>
              )}
              {backfill.create_new && <span>Buat pasien baru</span>}
            </div>
            {backfill.error_message && (
              <div className="rounded border border-[var(--border)] bg-[var(--muted)] p-2 text-xs">
                {backfill.error_message}
              </div>
            )}
          </div>
        )}

        {runs.error && <ErrorState error={runs.error} />}

        {runs.data && (
          <>
            <div className="rounded-lg border border-[var(--border)]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tanggal</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Langkah</TableHead>
                    <TableHead>Dimulai</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.data.items.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>{r.target_date}</TableCell>
                      <TableCell>
                        <CronRunStatusBadge status={r.status} />
                      </TableCell>
                      <TableCell className="text-xs uppercase text-[var(--muted-foreground)]">
                        {r.status === "failed" && r.failed_step
                          ? `${STEP_LABEL[r.failed_step]} (gagal)`
                          : r.current_step
                            ? `${STEP_LABEL[r.current_step]} (percobaan ${r.current_step_attempt})`
                            : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {r.started_at
                          ? format(parseISO(r.started_at), "yyyy-MM-dd HH:mm")
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <Button variant="ghost" size="sm" asChild>
                          <Link
                            href={`/cron-runs/${r.id}`}
                            prefetch={false}
                          >
                            Buka
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {runs.data.items.length === 0 && (
                <div className="p-6">
                  <EmptyState title="Belum ada proses" />
                </div>
              )}
            </div>
            <Pagination
              page={runs.data.page}
              pages={runs.data.pages}
              total={runs.data.total}
              onPageChange={setPage}
            />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
