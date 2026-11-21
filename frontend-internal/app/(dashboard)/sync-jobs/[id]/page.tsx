"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Ban } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ErrorState } from "@/components/common/error-state";
import { SyncStatusBadge } from "@/components/sync/sync-status-badge";
import { SyncLogStream, SyncLogHistory } from "@/components/sync/sync-log-stream";
import { useCancelSyncJob, useSyncJob } from "@/lib/hooks/use-sync";
import { asApiError } from "@/lib/api/client";

export default function SyncJobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const job = useSyncJob(id);
  const cancel = useCancelSyncJob();

  const handleCancel = async () => {
    try {
      await cancel.mutateAsync(id);
      toast.success("Pengiriman dibatalkan");
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  if (job.error) return <ErrorState error={job.error} />;

  const live =
    job.data?.status === "pending" || job.data?.status === "running";
  const cancellable = live;

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="h-8 -ml-2 px-2">
        <Link
          href={
            job.data ? `/patients/${job.data.patient_id}` : "/patients"
          }
          prefetch={false}
        >
          <ArrowLeft className="h-4 w-4" />
          Kembali ke pasien
        </Link>
      </Button>

      <PageHeader
        title="Kirim ke ASIK"
        description={
          job.data
            ? `${job.data.patient_name} • NIK ${job.data.patient_nik} • ${job.data.puskesmas_name}`
            : "Memuat…"
        }
        actions={
          cancellable ? (
            <Button
              variant="destructive"
              onClick={handleCancel}
              disabled={cancel.isPending}
            >
              <Ban className="h-4 w-4" />
              Batal
            </Button>
          ) : undefined
        }
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            {job.data ? <SyncStatusBadge status={job.data.status} /> : "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Total formulir
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.forms_total ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Terkirim
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums text-emerald-700">
            {job.data?.forms_succeeded ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Gagal
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums text-rose-700">
            {job.data?.forms_failed ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Dilewati
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.forms_skipped ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Durasi
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold tabular-nums">
            {job.data?.duration_seconds != null
              ? `${job.data.duration_seconds.toFixed(1)}s`
              : "—"}
          </CardContent>
        </Card>
      </div>

      {job.data?.error_message && (
        <div className="rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/10 p-3 text-sm text-[var(--destructive)]">
          <p className="font-medium">Kesalahan</p>
          <p className="font-mono text-xs whitespace-pre-wrap">
            {job.data.error_message}
          </p>
        </div>
      )}

      {job.data?.notes && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-[var(--muted-foreground)]">
              Hasil per formulir
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="font-mono text-xs whitespace-pre-wrap">
              {job.data.notes}
            </pre>
          </CardContent>
        </Card>
      )}

      {live ? (
        <SyncLogStream jobId={id} enabled={live} />
      ) : job.data ? (
        <SyncLogHistory jobId={id} />
      ) : null}

      {job.data && (
        <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
          <Meta label="Dimulai" value={fmt(job.data.started_at)} />
          <Meta label="Selesai" value={fmt(job.data.finished_at)} />
          <Meta label="Dipicu oleh" value={job.data.triggered_by_type} />
          <Meta label="ID tugas" value={job.data.celery_task_id ?? "—"} />
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
