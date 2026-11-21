"use client";

import { Fragment, useMemo, useState } from "react";
import { format, parseISO } from "date-fns";
import { ChevronDown, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import {
  useClearMergeConflictCache,
  useMergeConflictSummary,
} from "@/lib/hooks/use-merge-conflicts";
import { Button } from "@/components/ui/button";

const TOP_OPTIONS = [10, 20, 50] as const;

// Production build: clear-cache control hidden. Flip to true to re-enable.
const SHOW_CLEAR_CACHE = false;

export default function MergeConflictsPage() {
  const [puskesmasId, setPuskesmasId] = useState<string | undefined>(undefined);
  const [top, setTop] = useState<number>(50);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const pkDetail = usePuskesmas(puskesmasId);

  const query = useMemo(
    () => ({ puskesmas_id: puskesmasId, top }),
    [puskesmasId, top],
  );
  const summary = useMergeConflictSummary(query);
  const data = summary.data;
  const clearCache = useClearMergeConflictCache();
  // computing = backend is recomputing in the background (cold cache / refresh);
  // treat it as loading so we never render the empty placeholder payload.
  const computing = !!data?.computing;
  const summaryLoading =
    summary.isLoading ||
    computing ||
    (summary.isFetching && !summary.isPlaceholderData);
  const summaryRefreshing =
    !summaryLoading && (summary.isFetching || clearCache.isPending);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analisis Konflik"
        description="Pertanyaan yang jawabannya benar-benar berbeda antara Medisy dan ASIK pada data gabungan."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Puskesmas</Label>
          <AsyncCombobox
            value={puskesmasId}
            onChange={(v) => setPuskesmasId(v)}
            useOptions={usePuskesmasOptions}
            selectedLabel={pkDetail.data?.name}
            placeholder="Pilih puskesmas…"
            allOptionLabel="Semua puskesmas"
          />
        </div>
        <div className="space-y-2">
          <Label>Teratas</Label>
          <Select
            value={String(top)}
            onValueChange={(v) => setTop(Number(v))}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TOP_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  Top {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {data && !computing && data.computed_at && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
          <span>
            <span className="font-medium text-[var(--foreground)]">
              {data.total_patients.toLocaleString()}
            </span>{" "}
            matched patients (last 12 months)
          </span>
          <span className="inline-flex items-center gap-2">
            <span>
              Dihitung{" "}
              {format(parseISO(data.computed_at!), "yyyy-MM-dd HH:mm")}
              {data.cache_hit ? " · dari cache" : " · baru dihitung"}
              {summaryRefreshing && (
                <span className="ml-2 inline-flex items-center gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  refreshing…
                </span>
              )}
            </span>
            {SHOW_CLEAR_CACHE && data.cache_hit && (
              <Button
                size="sm"
                variant="outline"
                className="h-6 gap-1 px-2 text-xs"
                onClick={() => clearCache.mutate(puskesmasId)}
                disabled={clearCache.isPending}
              >
                <RefreshCw
                  className={`h-3 w-3 ${clearCache.isPending ? "animate-spin" : ""}`}
                />
                Hapus cache
              </Button>
            )}
          </span>
        </div>
      )}

      {summary.error && <ErrorState error={summary.error} />}

      {summaryLoading && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] py-16 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="h-6 w-6 animate-spin" />
          <div className="text-center">
            <div className="font-medium text-[var(--foreground)]">
              Memuat analisis konflik…
            </div>
            <div className="text-xs">
              Perhitungan pertama memeriksa data gabungan setiap pasien yang cocok
              pada cakupan yang dipilih. Hasilnya disimpan (cache) selama 24 jam.
            </div>
          </div>
        </div>
      )}

      {!summaryLoading && data && (
        <div className="rounded-lg border border-[var(--border)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"></TableHead>
                <TableHead>Bagian</TableHead>
                <TableHead>Kunci Gabungan</TableHead>
                <TableHead className="text-right">Pasien Terdampak</TableHead>
                <TableHead className="text-right">%</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.conflicts.map((c) => {
                const id = `${c.section}::${c.merged_key}`;
                const isOpen = expanded.has(id);
                return (
                  <Fragment key={id}>
                    <TableRow
                      className="cursor-pointer"
                      onClick={() => toggle(id)}
                    >
                      <TableCell className="w-8 align-top">
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4 text-[var(--muted-foreground)]" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
                        )}
                      </TableCell>
                      <TableCell className="align-top font-medium">
                        {c.section_label}
                      </TableCell>
                      <TableCell className="align-top">{c.merged_key}</TableCell>
                      <TableCell className="text-right align-top tabular-nums">
                        {c.conflict_count.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right align-top tabular-nums">
                        {c.conflict_pct.toFixed(2)}%
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell></TableCell>
                        <TableCell colSpan={4} className="py-3">
                          <div className="overflow-hidden rounded-lg border border-[var(--border)] text-sm">
                            <div className="grid grid-cols-2 divide-x divide-[var(--border)]">
                              <div className="bg-blue-50 p-3">
                                <div className="mb-1 text-xs font-bold uppercase tracking-wide text-blue-700">
                                  ASIK
                                </div>
                                <div className="break-words text-xs leading-snug text-blue-500">
                                  {c.asik_question ?? "—"}
                                </div>
                              </div>
                              <div className="bg-emerald-50 p-3">
                                <div className="mb-1 text-xs font-bold uppercase tracking-wide text-emerald-700">
                                  Medisy
                                </div>
                                <div className="break-words text-xs leading-snug text-emerald-600">
                                  {c.epus_question ?? "—"}
                                </div>
                              </div>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
          {data.conflicts.length === 0 && (
            <div className="p-6">
              <EmptyState
                title="Tidak ada konflik"
                description={
                  data.total_patients === 0
                    ? "Tidak ada pasien cocok dengan data gabungan pada cakupan yang dipilih."
                    : "Semua pasien yang cocok memiliki jawaban sama untuk setiap pertanyaan pada cakupan ini."
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
