"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Clock, PlayCircle, Pencil, Trash2 } from "lucide-react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { CronConfigFormDialog } from "./cron-config-form-dialog";
import {
  useCronConfig,
  useDeleteCronConfig,
  useRunCronNow,
  useUpdateCronConfig,
} from "@/lib/hooks/use-cron-config";
import { asApiError } from "@/lib/api/client";

function pad(n: number) {
  return n.toString().padStart(2, "0");
}

function offsetLabel(days: number): string {
  if (days === 0) return "Hari ini (D)";
  if (days === -1) return "Kemarin (D-1)";
  return `D${days >= 0 ? "+" : ""}${days}`;
}

export function CronConfigCard({ puskesmasId }: { puskesmasId: string }) {
  const cfgQuery = useCronConfig(puskesmasId);
  const update = useUpdateCronConfig(puskesmasId);
  const del = useDeleteCronConfig(puskesmasId);
  const runNow = useRunCronNow(puskesmasId);
  const router = useRouter();
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [runNowOpen, setRunNowOpen] = useState(false);

  const cfg = cfgQuery.data;

  const onToggleEnabled = async () => {
    if (!cfg) return;
    try {
      await update.mutateAsync({ enabled: !cfg.enabled });
      toast.success(cfg.enabled ? "Jadwal dinonaktifkan" : "Jadwal diaktifkan");
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRunNow = async () => {
    try {
      const run = await runNow.mutateAsync();
      toast.success("Jadwal dijalankan");
      setRunNowOpen(false);
      router.push(`/cron-runs/${run.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onDelete = async () => {
    try {
      await del.mutateAsync();
      toast.success("Jadwal dihapus");
      setDeleteOpen(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  if (cfgQuery.isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Jadwal Otomatis</CardTitle>
          <CardDescription>Memuat…</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!cfg) {
    return (
      <>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Jadwal Otomatis</CardTitle>
            <CardDescription>
              Belum ada jadwal harian untuk puskesmas ini.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Clock className="h-4 w-4" />
              Atur jadwal
            </Button>
          </CardContent>
        </Card>
        <CronConfigFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          puskesmasId={puskesmasId}
          existing={null}
        />
      </>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">Jadwal Otomatis</CardTitle>
              <CardDescription>
                Harian pukul {pad(cfg.hour)}:{pad(cfg.minute)} (Asia/Jakarta) ·{" "}
                {offsetLabel(cfg.target_offset_days)} ·{" "}
                {cfg.enabled ? "Aktif" : "Nonaktif"}
                {cfg.merge_mode === "force_remerge"
                  ? " · Gabung ulang paksa"
                  : cfg.merge_mode === "no_merge"
                    ? " · Tanpa gabung (ambil data saja)"
                    : ""}
                {cfg.sync_mode !== "off"
                  ? cfg.sync_mode === "force_resync"
                    ? " · Isi pemeriksaan ASIK (paksa)"
                    : " · Isi pemeriksaan ASIK"
                  : ""}
                {cfg.create_new ? " · Buat pasien baru" : ""}
              </CardDescription>
            </div>
            <Button
              variant={cfg.enabled ? "outline" : "default"}
              size="sm"
              onClick={onToggleEnabled}
              disabled={update.isPending}
            >
              {cfg.enabled ? "Nonaktifkan" : "Aktifkan"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2 text-xs text-[var(--muted-foreground)]">
            <div>
              <span className="font-medium">Jalan berikutnya: </span>
              {format(parseISO(cfg.next_run_at), "yyyy-MM-dd HH:mm")}
            </div>
            <div>
              <span className="font-medium">Terakhir dijalankan: </span>
              {cfg.last_fired_at
                ? format(parseISO(cfg.last_fired_at), "yyyy-MM-dd HH:mm")
                : "—"}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() => setRunNowOpen(true)}
              disabled={runNow.isPending}
            >
              <PlayCircle className="h-4 w-4" />
              Jalankan sekarang
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setEditOpen(true)}
            >
              <Pencil className="h-4 w-4" />
              Ubah
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 className="h-4 w-4" />
              Hapus
            </Button>
          </div>
        </CardContent>
      </Card>

      <CronConfigFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        puskesmasId={puskesmasId}
        existing={cfg}
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Hapus jadwal?"
        description="Jadwal akan berhenti berjalan. Riwayat proses yang ada tetap disimpan."
        confirmLabel="Hapus"
        destructive
        loading={del.isPending}
        onConfirm={onDelete}
      />

      <ConfirmDialog
        open={runNowOpen}
        onOpenChange={setRunNowOpen}
        title="Jalankan jadwal sekarang?"
        description={`Ini akan memulai pengambilan data ASIK + Medisy${
          cfg.merge_mode === "no_merge" ? "" : " dan gabung data"
        } untuk ${
          cfg.target_offset_days === 0 ? "hari ini" : "kemarin"
        } sekarang juga. Memakan waktu pengambilan data${
          cfg.merge_mode === "no_merge" ? "" : " + AI"
        }.`}
        confirmLabel="Jalankan sekarang"
        loading={runNow.isPending}
        onConfirm={onRunNow}
      />
    </>
  );
}
