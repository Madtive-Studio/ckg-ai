"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCcw, RotateCw, XCircle } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ErrorState } from "@/components/common/error-state";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { CronRunStatusBadge } from "@/components/cron/cron-run-status-badge";
import { ScrapeStatusBadge } from "@/components/scrape/scrape-status-badge";
import { MergeStatusBadge } from "@/components/merge/merge-status-badge";
import {
  cronRunKeys,
  useCancelCronRun,
  useCronRun,
  useCronRunSyncSummary,
  useRetryCronRun,
} from "@/lib/hooks/use-cron-runs";
import { mergeKeys, useMergeJob } from "@/lib/hooks/use-merge";
import { scrapeKeys, useScrapeJob } from "@/lib/hooks/use-scrape";
import { asApiError } from "@/lib/api/client";
import { STEP_LABEL } from "@/lib/source-names";

export default function CronRunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const run = useCronRun(id);
  const cancel = useCancelCronRun();
  const retry = useRetryCronRun();
  const [cancelOpen, setCancelOpen] = useState(false);

  const onRefresh = async () => {
    const r = run.data;
    const tasks = [
      qc.invalidateQueries({ queryKey: cronRunKeys.detail(id) }),
      // The sync step has no child job id to key off, so Refresh must ask for
      // its aggregate explicitly or the row would stay stale.
      qc.invalidateQueries({ queryKey: cronRunKeys.syncSummary(id) }),
    ];
    if (r?.asik_scrape_job_id) {
      tasks.push(
        qc.invalidateQueries({
          queryKey: scrapeKeys.detail(r.asik_scrape_job_id),
        }),
      );
    }
    if (r?.epus_scrape_job_id) {
      tasks.push(
        qc.invalidateQueries({
          queryKey: scrapeKeys.detail(r.epus_scrape_job_id),
        }),
      );
    }
    if (r?.merge_job_id) {
      tasks.push(
        qc.invalidateQueries({ queryKey: mergeKeys.detail(r.merge_job_id) }),
      );
    }
    await Promise.all(tasks);
  };

  if (run.error) return <ErrorState error={run.error} />;
  if (!run.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Proses terjadwal" description="Memuat…" />
      </div>
    );
  }

  const r = run.data;
  const canCancel = r.status === "pending" || r.status === "running";
  const canRetry = r.status === "failed" || r.status === "cancelled";

  const onCancel = async () => {
    try {
      await cancel.mutateAsync(r.id);
      toast.success("Proses terjadwal dibatalkan");
      setCancelOpen(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRetry = async () => {
    try {
      const newRun = await retry.mutateAsync(r.id);
      toast.success("Percobaan ulang dimulai");
      router.push(`/cron-runs/${newRun.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
        <Link href="/cron-runs" prefetch={false}>
          <ArrowLeft className="h-4 w-4" />
          Kembali
        </Link>
      </Button>

      <PageHeader
        title={`Proses terjadwal · ${r.puskesmas_name}`}
        description={`Tanggal target ${r.target_date}`}
        actions={
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={run.isFetching}
            >
              <RotateCw
                className={`h-4 w-4 ${run.isFetching ? "animate-spin" : ""}`}
              />
              Muat ulang
            </Button>
            {canCancel && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCancelOpen(true)}
                disabled={cancel.isPending}
              >
                <XCircle className="h-4 w-4" />
                Batal
              </Button>
            )}
            {canRetry && (
              <Button size="sm" onClick={onRetry} disabled={retry.isPending}>
                <RefreshCcw className="h-4 w-4" />
                Coba lagi
              </Button>
            )}
          </div>
        }
      />

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Ringkasan</CardTitle>
            <CronRunStatusBadge status={r.status} />
          </div>
          <CardDescription>
            {r.failed_step
              ? `Gagal pada langkah ${STEP_LABEL[r.failed_step]}`
              : r.current_step
                ? `Langkah ${STEP_LABEL[r.current_step]} · percobaan ${r.current_step_attempt}`
                : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-2 text-xs text-[var(--muted-foreground)]">
          <div>
            <span className="font-medium">Dimulai: </span>
            {r.started_at
              ? format(parseISO(r.started_at), "yyyy-MM-dd HH:mm")
              : "—"}
          </div>
          <div>
            <span className="font-medium">Selesai: </span>
            {r.finished_at
              ? format(parseISO(r.finished_at), "yyyy-MM-dd HH:mm")
              : "—"}
          </div>
          {r.error_message && (
            <div className="col-span-2 mt-2">
              <span className="font-medium">Kesalahan: </span>
              <pre className="mt-1 whitespace-pre-wrap rounded bg-[var(--muted)] p-2 text-[var(--foreground)]">
                {r.error_message}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Langkah proses</h2>
        <div className="space-y-2">
          <ChildScrapeJobRow label="Ambil data Medisy" jobId={r.epus_scrape_job_id} />
          <ChildScrapeJobRow label="Ambil data ASIK" jobId={r.asik_scrape_job_id} />
          <ChildMergeJobRow label="Gabung data" jobId={r.merge_job_id} />
          <SyncStepRow runId={r.id} />
        </div>
      </div>

      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Batalkan proses terjadwal ini?"
        description="Langkah ambil data atau gabung data yang sedang berjalan akan dibatalkan. Langkah berikutnya tidak dijalankan."
        confirmLabel="Batalkan proses"
        destructive
        loading={cancel.isPending}
        onConfirm={onCancel}
      />
    </div>
  );
}

/** The SYNC step has no single child job — it fans out to one SyncJob per
 * patient — so it shows aggregate progress instead of a job link. Before the
 * step starts `total` is null and the row reads "Belum dimulai", matching how the
 * scrape/merge rows render a null job id. */
function SyncStepRow({ runId }: { runId: string }) {
  const summary = useCronRunSyncSummary(runId);
  const s = summary.data;
  const done = s ? s.success + s.failed + s.cancelled : 0;
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] p-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">Kirim ke ASIK</p>
        <p className="truncate text-xs text-[var(--muted-foreground)]">
          {s && s.total !== null
            ? `${done}/${s.total} pasien${s.failed ? ` · ${s.failed} gagal` : ""}${
                s.running ? ` · ${s.running} berjalan` : ""
              }`
            : "Belum dimulai"}
        </p>
      </div>
      {/* No "Open" link: the sync-jobs list has no cron_run_id filter, so it
          would land on an unfiltered list rather than this run's jobs. */}
      <span className="text-xs text-[var(--muted-foreground)]">
        {s && s.total !== null && done >= s.total ? "Done" : "—"}
      </span>
    </div>
  );
}

function ChildScrapeJobRow({
  label,
  jobId,
}: {
  label: string;
  jobId: string | null;
}) {
  const job = useScrapeJob(jobId ?? undefined);
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] p-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">{label}</p>
          {job.data ? <ScrapeStatusBadge status={job.data.status} /> : null}
        </div>
        <p className="truncate text-xs text-[var(--muted-foreground)]">
          {jobId ?? "Belum dimulai"}
        </p>
      </div>
      {jobId ? (
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/scrape-jobs/${jobId}`} prefetch={false}>
            Buka
          </Link>
        </Button>
      ) : (
        <span className="text-xs text-[var(--muted-foreground)]">—</span>
      )}
    </div>
  );
}

function ChildMergeJobRow({
  label,
  jobId,
}: {
  label: string;
  jobId: string | null;
}) {
  const job = useMergeJob(jobId ?? undefined);
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] p-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">{label}</p>
          {job.data ? <MergeStatusBadge status={job.data.status} /> : null}
        </div>
        <p className="truncate text-xs text-[var(--muted-foreground)]">
          {jobId ?? "Belum dimulai"}
        </p>
      </div>
      {jobId ? (
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/merge-with-ai/${jobId}`} prefetch={false}>
            Buka
          </Link>
        </Button>
      ) : (
        <span className="text-xs text-[var(--muted-foreground)]">—</span>
      )}
    </div>
  );
}
