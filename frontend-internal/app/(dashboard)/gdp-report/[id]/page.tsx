"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Ban, RotateCw } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/pagination";
import { ErrorState } from "@/components/common/error-state";
import { EmptyState } from "@/components/common/empty-state";
import { GdpStatusBadge } from "@/components/gdp/gdp-status-badge";
import { ScrapeStatusBadge } from "@/components/scrape/scrape-status-badge";
import {
  useCancelGdpReport,
  useGdpReport,
  useRetryGdpReport,
} from "@/lib/hooks/use-gdp";
import { useScrapeJobList } from "@/lib/hooks/use-scrape";
import { asApiError } from "@/lib/api/client";
import { GDP_PHASE_LABEL, SCRAPE_KIND_LABEL } from "@/lib/source-names";

export default function GdpReportDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const job = useGdpReport(id);
  const cancel = useCancelGdpReport();
  const retry = useRetryGdpReport();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [childPage, setChildPage] = useState(1);

  const childQuery = useMemo(
    () => ({
      page: childPage,
      size: 20,
      parent_gdp_job_id: id,
    }),
    [childPage, id],
  );
  const children = useScrapeJobList(childQuery);

  const handleCancel = async () => {
    try {
      await cancel.mutateAsync(id);
      toast.success("Proses dibatalkan — proses turunannya ikut dibatalkan");
      setConfirmOpen(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const handleRetry = async () => {
    try {
      await retry.mutateAsync(id);
      toast.success(
        "Percobaan ulang diantrekan — proses turunan yang berhasil dipakai ulang, yang masih berjalan ditunggu",
      );
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  if (job.error) return <ErrorState error={job.error} />;

  const live = job.data?.status === "pending" || job.data?.status === "running";
  const retryable =
    job.data?.status === "cancelled" || job.data?.status === "failed";

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
        <Link href="/gdp-report" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Kembali
        </Link>
      </Button>

      <PageHeader
        title="Proses Laporan GDP"
        description={
          job.data
            ? `${job.data.puskesmas_name} • ${job.data.date_from} → ${job.data.date_to}`
            : "Memuat…"
        }
        actions={
          live ? (
            <Button
              variant="destructive"
              onClick={() => setConfirmOpen(true)}
              disabled={cancel.isPending}
            >
              <Ban className="h-4 w-4" />
              Batal
            </Button>
          ) : retryable ? (
            <Button onClick={handleRetry} disabled={retry.isPending}>
              <RotateCw className="h-4 w-4" />
              {retry.isPending ? "Mengantre…" : "Coba lagi"}
            </Button>
          ) : undefined
        }
      />

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Batalkan proses laporan GDP?"
        description="Ini menghentikan proses utama dan membatalkan proses ambil data ASIK / Medisy di bawahnya. Data pasien yang sudah tersimpan tetap ada."
        confirmLabel="Batalkan proses"
        destructive
        loading={cancel.isPending}
        onConfirm={handleCancel}
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            {job.data ? <GdpStatusBadge status={job.data.status} /> : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Tahap
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold capitalize">
            {job.data ? GDP_PHASE_LABEL[job.data.phase] : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Tanggal selesai
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data ? `${job.data.dates_done}/${job.data.dates_total}` : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Proses Medisy
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data
              ? `${job.data.epus_jobs_done}/${job.data.epus_jobs_total ?? "—"}`
              : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Medisy gagal
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.epus_jobs_failed ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Dipicu oleh
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            {job.data?.triggered_by_type ?? "—"}
          </CardContent>
        </Card>
      </div>

      {job.data?.error_message && (
        <div className="rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/10 p-3 text-sm text-[var(--destructive)]">
          <p className="font-medium">Kesalahan</p>
          <p className="font-mono text-xs">{job.data.error_message}</p>
        </div>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--muted-foreground)]">
          Proses ambil data turunan
        </h2>
        {children.error && <ErrorState error={children.error} />}
        {children.data && (
          <>
            <div className="rounded-lg border border-[var(--border)]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Jenis</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Diambil / Baru / Diperbarui</TableHead>
                    <TableHead>Durasi</TableHead>
                    <TableHead>Dimulai</TableHead>
                    <TableHead>Selesai</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {children.data.items.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="text-xs">
                        {SCRAPE_KIND_LABEL[c.kind]}
                      </TableCell>
                      <TableCell>
                        <ScrapeStatusBadge status={c.status} />
                      </TableCell>
                      <TableCell className="tabular-nums text-xs">
                        {c.scraped_count ?? "—"} / {c.inserted_count ?? "—"} /{" "}
                        {c.updated_count ?? "—"}
                      </TableCell>
                      <TableCell className="tabular-nums text-xs">
                        {c.duration_seconds != null
                          ? `${c.duration_seconds.toFixed(1)}s`
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {c.started_at
                          ? format(parseISO(c.started_at), "yyyy-MM-dd HH:mm")
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-[var(--muted-foreground)]">
                        {c.finished_at
                          ? format(parseISO(c.finished_at), "yyyy-MM-dd HH:mm")
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <Button variant="ghost" size="sm" asChild>
                          <Link
                            href={`/scrape-jobs/${c.id}`}
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
              {children.data.items.length === 0 && (
                <div className="p-6">
                  <EmptyState
                    title="Belum ada proses turunan"
                    description="Proses utama belum memulai pengambilan data."
                  />
                </div>
              )}
            </div>
            <Pagination
              page={children.data.page}
              pages={children.data.pages}
              total={children.data.total}
              onPageChange={setChildPage}
            />
          </>
        )}
      </section>

      {job.data && (
        <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
          <Meta label="Dimulai" value={fmt(job.data.started_at)} />
          <Meta label="Selesai" value={fmt(job.data.finished_at)} />
          <Meta label="Dibuat" value={fmt(job.data.created_at)} />
          <Meta label="ID tugas" value={job.data.celery_task_id ?? "—"} />
          <Meta
            label="Mode ASIK"
            value={
              job.data.skip_asik_detail
                ? "daftar saja (NIK + Nama)"
                : "lengkap (formulir ikut diambil)"
            }
          />
        </div>
      )}
    </div>
  );
}

function fmt(iso: string | null) {
  return iso ? format(parseISO(iso), "yyyy-MM-dd HH:mm:ss") : "—";
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[var(--muted-foreground)]">{label}</p>
      <p className="truncate font-mono text-xs">{value}</p>
    </div>
  );
}
