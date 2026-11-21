"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { format, parseISO } from "date-fns";
import { Check, Download, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { asApiError } from "@/lib/api/client";
import { PageHeader } from "@/components/common/page-header";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { WarmProgress } from "@/components/common/warm-progress";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { GdpStatusBadge } from "@/components/gdp/gdp-status-badge";
import { GdpDiagnoseTable } from "@/components/gdp/gdp-diagnose-table";
import { StartGdpDialog } from "@/components/gdp/start-gdp-dialog";
import { MONTHS_ID, fmtGdp, gdpClass } from "@/lib/gdp-format";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useGdpReportListStore } from "@/lib/stores/gdp-report-list-store";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useCancelGdpReport,
  useClearGdpDashboardCache,
  useExportGdpDashboard,
  useExportGdpDiagnose,
  useGdpDashboard,
  useGdpReportList,
} from "@/lib/hooks/use-gdp";
import type { GdpReportRow } from "@/lib/api/types";
import { GDP_PHASE_LABEL } from "@/lib/source-names";

const _NOW_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: 6 }, (_, i) => _NOW_YEAR - i);

const TERKENDALI_LABELS = [
  ["Terkendali Bulan Berjalan", "terkendali_bulan_berjalan"],
  ["Terkendali TW 1", "terkendali_tw1"],
  ["Terkendali TW 2", "terkendali_tw2"],
  ["Terkendali TW 3", "terkendali_tw3"],
  ["Terkendali TW 4", "terkendali_tw4"],
] as const;

function terkendaliClass(v: string) {
  switch (v) {
    case "Terkendali":
      return "bg-green-200 text-green-900";
    case "Tidak terkendali":
      return "bg-red-200 text-red-900";
    case "Belum 3 bulan":
      return "bg-yellow-100 text-yellow-900";
    case "Tidak ada kunjungan":
      return "bg-gray-100 text-gray-700";
    default:
      return "";
  }
}

function TertCheckbox({ checked }: { checked: boolean }) {
  return (
    <span
      role="img"
      aria-label={checked ? "Ya" : "Tidak"}
      className={`mx-auto flex h-5 w-5 items-center justify-center rounded-[5px] ${
        checked
          ? "bg-black text-white"
          : "border-2 border-[var(--foreground)] bg-transparent"
      }`}
    >
      {checked && <Check className="h-3 w-3" strokeWidth={3} />}
    </span>
  );
}

export default function GdpReportPage() {
  const puskesmasId = useGdpReportListStore((s) => s.puskesmasId);
  const year = useGdpReportListStore((s) => s.year);
  const q = useGdpReportListStore((s) => s.q);
  const ckgOnly = useGdpReportListStore((s) => s.ckgOnly);
  const page = useGdpReportListStore((s) => s.page);
  const tab = useGdpReportListStore((s) => s.tab);
  const setPuskesmasId = useGdpReportListStore((s) => s.setPuskesmasId);
  const setYear = useGdpReportListStore((s) => s.setYear);
  const setQ = useGdpReportListStore((s) => s.setQ);
  const setCkgOnly = useGdpReportListStore((s) => s.setCkgOnly);
  const setPage = useGdpReportListStore((s) => s.setPage);
  const setTab = useGdpReportListStore((s) => s.setTab);

  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const debouncedQ = useDebouncedValue(q);

  const dashboardQuery = useMemo(
    () => ({
      puskesmas_id: puskesmasId,
      year,
      q: debouncedQ.trim() || undefined,
      ckg_only: ckgOnly || undefined,
      page,
      size: 20,
    }),
    [puskesmasId, year, debouncedQ, ckgOnly, page],
  );
  const dashboard = useGdpDashboard(dashboardQuery, !!puskesmasId);
  const clearDashboardCache = useClearGdpDashboardCache();
  const exportDashboard = useExportGdpDashboard();
  const exportDiagnose = useExportGdpDiagnose();
  // computing = backend recomputing in the background (cold cache / refresh);
  // treat as loading so we never render the empty placeholder payload.
  const dashboardComputing = !!dashboard.data?.computing;
  const dashboardLoading =
    !!puskesmasId &&
    (dashboard.isLoading ||
      dashboardComputing ||
      (dashboard.isFetching && !dashboard.isPlaceholderData));
  const dashboardRefreshing =
    !!puskesmasId &&
    !dashboardLoading &&
    (dashboard.isFetching || clearDashboardCache.isPending);

  const jobsQuery = useMemo(
    () => ({
      page: 1,
      size: 5,
      puskesmas_id: puskesmasId || undefined,
    }),
    [puskesmasId],
  );
  const jobs = useGdpReportList(jobsQuery);
  const cancelJob = useCancelGdpReport();
  const [cancelTargetId, setCancelTargetId] = useState<string | null>(null);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Kertas Kerja DM Terkendali"
        description="NIK ASIK dicocokkan dengan Medisy pada rentang tanggal. GDP bulanan per pasien."
        actions={<StartGdpDialog />}
      />

      <ConfirmDialog
        open={!!cancelTargetId}
        onOpenChange={(v) => !v && setCancelTargetId(null)}
        title="Batalkan proses laporan GDP?"
        description="Ini menghentikan proses utama dan membatalkan proses ambil data ASIK / Medisy di bawahnya. Data yang sudah tersimpan tetap ada."
        confirmLabel="Batalkan proses"
        destructive
        loading={cancelJob.isPending}
        onConfirm={() => {
          if (!cancelTargetId) return;
          const id = cancelTargetId;
          cancelJob.mutate(id, {
            onSettled: () => setCancelTargetId(null),
          });
        }}
      />

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--muted-foreground)]">
          Proses Terbaru
        </h2>
        {jobs.error && <ErrorState error={jobs.error} />}
        {jobs.data && jobs.data.items.length > 0 && (
          <div className="rounded-lg border border-[var(--border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Puskesmas</TableHead>
                  <TableHead>Rentang</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Tahap</TableHead>
                  <TableHead>Tanggal</TableHead>
                  <TableHead>Proses Medisy</TableHead>
                  <TableHead>Dimulai</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.data.items.map((j) => (
                  <TableRow key={j.id}>
                    <TableCell>{j.puskesmas_name}</TableCell>
                    <TableCell className="text-xs">
                      {j.date_from} → {j.date_to}
                    </TableCell>
                    <TableCell>
                      <GdpStatusBadge status={j.status} />
                    </TableCell>
                    <TableCell className="text-xs">{GDP_PHASE_LABEL[j.phase]}</TableCell>
                    <TableCell className="tabular-nums text-xs">
                      {j.dates_done}/{j.dates_total}
                    </TableCell>
                    <TableCell className="tabular-nums text-xs">
                      {j.epus_jobs_done}/{j.epus_jobs_total ?? "—"}
                      {j.epus_jobs_failed > 0 && (
                        <span className="ml-1 text-[var(--destructive)]">
                          ({j.epus_jobs_failed} failed)
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-[var(--muted-foreground)]">
                      {j.started_at
                        ? format(parseISO(j.started_at), "yyyy-MM-dd HH:mm")
                        : "—"}
                    </TableCell>
                    <TableCell className="space-x-1">
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={`/gdp-report/${j.id}`} prefetch={false}>
                          Buka
                        </Link>
                      </Button>
                      {(j.status === "pending" || j.status === "running") && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setCancelTargetId(j.id)}
                          disabled={cancelJob.isPending}
                        >
                          Batal
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {jobs.data && jobs.data.items.length === 0 && (
          <EmptyState
            title="Belum ada proses laporan GDP"
            description="Klik Mulai Laporan GDP untuk mengambil data ASIK + Medisy pada rentang tanggal."
          />
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-[var(--muted-foreground)]">
          Dashboard
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <Label>Puskesmas</Label>
            <AsyncCombobox
              value={puskesmasId || undefined}
              onChange={(v) => setPuskesmasId(v ?? "")}
              useOptions={usePuskesmasOptions}
              selectedLabel={pkDetail.data?.name}
              placeholder="Pilih puskesmas…"
            />
          </div>
          <div className="space-y-2">
            <Label>Tahun Pelaporan</Label>
            <Select
              value={String(year)}
              onValueChange={(v) => setYear(Number(v))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {YEAR_OPTIONS.map((y) => (
                  <SelectItem key={y} value={String(y)}>
                    {y}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Cari Nama / NIK</Label>
            <Input
              placeholder="Cari…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        </div>
        <label className="flex w-fit cursor-pointer items-center gap-2 text-sm">
          <Switch checked={ckgOnly} onCheckedChange={setCkgOnly} />
          <span>Hanya yang di Tandai CKG</span>
        </label>
        {!puskesmasId && (
          <EmptyState
            title="Pilih puskesmas"
            description="Dashboard ditampilkan per satu puskesmas."
          />
        )}
        {dashboard.error && <ErrorState error={dashboard.error} />}
        {puskesmasId && dashboard.data && !dashboardComputing && dashboard.data.computed_at && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
            <span>
              <span className="font-medium text-[var(--foreground)]">
                {dashboard.data.total.toLocaleString()}
              </span>{" "}
              pasien dengan data GDP
            </span>
            <span className="inline-flex items-center gap-2">
              <span>
                Dihitung{" "}
                {format(parseISO(dashboard.data.computed_at!), "yyyy-MM-dd HH:mm")}
                {dashboard.data.cache_hit ? " · dari cache" : " · baru dihitung"}
                {dashboardRefreshing && (
                  <span className="ml-2 inline-flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    refreshing…
                  </span>
                )}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="h-6 gap-1 px-2 text-xs"
                onClick={() =>
                  clearDashboardCache.mutate({ puskesmasId, year })
                }
                disabled={clearDashboardCache.isPending}
              >
                <RefreshCw
                  className={`h-3 w-3 ${clearDashboardCache.isPending ? "animate-spin" : ""}`}
                />
                Hapus cache
              </Button>
              {tab === "report" ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 gap-1 px-2 text-xs"
                  onClick={() =>
                    exportDashboard.mutate(
                      {
                        puskesmasId,
                        year,
                        ckgOnly,
                        filename: `GD Puasa - ${pkDetail.data?.name ?? "Puskesmas"} - ${year}.xlsx`,
                      },
                      {
                        onError: (err) =>
                          toast.error(asApiError(err).message),
                      },
                    )
                  }
                  disabled={
                    dashboardLoading ||
                    dashboardRefreshing ||
                    dashboard.data.total === 0 ||
                    exportDashboard.isPending
                  }
                >
                  {exportDashboard.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="h-3 w-3" />
                  )}
                  Unduh Kertas Kerja DM Terkendali
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 gap-1 px-2 text-xs"
                  onClick={() =>
                    exportDiagnose.mutate(
                      {
                        puskesmasId,
                        year,
                        ckgOnly,
                        filename: `Tinjauan Lengkap Diagnosis -  ${pkDetail.data?.name ?? "Puskesmas"} - ${year}.xlsx`,
                      },
                      {
                        onError: (err) =>
                          toast.error(asApiError(err).message),
                      },
                    )
                  }
                  disabled={
                    dashboardLoading ||
                    dashboardRefreshing ||
                    dashboard.data.total === 0 ||
                    exportDiagnose.isPending
                  }
                >
                  {exportDiagnose.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="h-3 w-3" />
                  )}
                  Unduh Tinjauan Lengkap Diagnosis
                </Button>
              )}
            </span>
          </div>
        )}
        {dashboardLoading && (
          <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] py-16 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-6 w-6 animate-spin" />
            <div className="text-center">
              <div className="font-medium text-[var(--foreground)]">
                Memuat dashboard GDP…
              </div>
              <div className="text-xs">
                Perhitungan pertama membuka semua data Medisy puskesmas ini
                untuk tahun ini. Hasilnya disimpan (cache) selama 24 jam.
              </div>
            </div>
            {dashboard.data?.progress && (
              <WarmProgress
                progress={dashboard.data.progress}
                label={null}
                className="max-w-xs"
              />
            )}
          </div>
        )}
        {puskesmasId && !dashboardLoading && dashboard.data && (
          <Tabs
            value={tab}
            onValueChange={(v) => setTab(v as "report" | "diagnose")}
          >
            <TabsList>
              <TabsTrigger value="report">
                Kertas Kerja DM Terkendali
              </TabsTrigger>
              <TabsTrigger value="diagnose">Tinjauan Lengkap Diagnosis</TabsTrigger>
            </TabsList>
            <TabsContent value="report">
              <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                <Table className="min-w-[2250px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[200px]">Nama Puskesmas</TableHead>
                    <TableHead className="w-[80px]">Tahun Pelaporan</TableHead>
                    <TableHead className="w-[160px]">Nama Pasien</TableHead>
                    <TableHead className="w-[160px]">NIK</TableHead>
                    <TableHead className="w-[120px]">Tanggal Diagnosis</TableHead>
                    <TableHead className="w-[160px] text-center text-xs">
                      Tertatalaksana (Pemberian Obat)
                    </TableHead>
                    <TableHead className="w-[160px] text-center text-xs">
                      Tertatalaksana (Pemberian Edukasi)
                    </TableHead>
                    {MONTHS_ID.map((m) => (
                      <TableHead
                        key={m}
                        className="w-[110px] text-center text-xs"
                      >
                        Hasil GD {m}
                      </TableHead>
                    ))}
                    {TERKENDALI_LABELS.map(([label]) => (
                      <TableHead
                        key={label}
                        className="w-[150px] text-center text-xs"
                      >
                        {label}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dashboard.data.items.map((row: GdpReportRow) => (
                    <TableRow key={row.nik}>
                      <TableCell className="text-xs">
                        {row.puskesmas_name}
                      </TableCell>
                      <TableCell className="tabular-nums text-xs">
                        {row.tahun_pelaporan}
                      </TableCell>
                      <TableCell>{row.nama || "—"}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {row.nik}
                      </TableCell>
                      <TableCell className="text-xs">
                        {row.tanggal_diagnosis
                          ? format(
                              parseISO(row.tanggal_diagnosis),
                              "dd/MM/yyyy",
                            )
                          : "—"}
                      </TableCell>
                      <TableCell className="text-center">
                        <TertCheckbox checked={row.tertatalaksana_obat} />
                      </TableCell>
                      <TableCell className="text-center">
                        <TertCheckbox checked={row.tertatalaksana_edukasi} />
                      </TableCell>
                      {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                        const v = row.gdp_by_month?.[String(m)] ?? null;
                        return (
                          <TableCell
                            key={m}
                            className={`text-center tabular-nums text-sm ${gdpClass(v)}`}
                          >
                            {fmtGdp(v)}
                          </TableCell>
                        );
                      })}
                      {TERKENDALI_LABELS.map(([label, key]) => {
                        const v = row[key];
                        return (
                          <TableCell
                            key={label}
                            className={`text-center text-xs ${terkendaliClass(v)}`}
                          >
                            {v || "—"}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
                {dashboard.data.items.length === 0 && (
                  <div className="p-6">
                    <EmptyState
                      title="Tidak ada pasien dengan GDP"
                      description="Tidak ada pasien di puskesmas dan tahun ini yang memiliki nilai GDP."
                    />
                  </div>
                )}
              </div>
            </TabsContent>
            <TabsContent value="diagnose">
              <GdpDiagnoseTable items={dashboard.data.items} />
            </TabsContent>
            <Pagination
              page={dashboard.data.page}
              pages={dashboard.data.pages}
              total={dashboard.data.total}
              onPageChange={setPage}
            />
          </Tabs>
        )}
      </section>
    </div>
  );
}
