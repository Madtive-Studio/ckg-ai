"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { applyApiErrorToForm } from "@/lib/api/form-errors";
import { GdpReportCreate, type GdpReportCreateInput } from "@/lib/api/types";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { useStartGdpReport } from "@/lib/hooks/use-gdp";

const KNOWN_FIELDS = [
  "puskesmas_id",
  "date_from",
  "date_to",
  "skip_asik_detail",
] as const;

export function StartGdpDialog() {
  const [open, setOpen] = useState(false);
  const start = useStartGdpReport();

  const form = useForm<GdpReportCreateInput>({
    resolver: zodResolver(GdpReportCreate),
    defaultValues: {
      puskesmas_id: "",
      date_from: "",
      date_to: "",
      skip_asik_detail: false,
    },
  });

  useEffect(() => {
    if (open)
      form.reset({
        puskesmas_id: "",
        date_from: "",
        date_to: "",
        skip_asik_detail: false,
      });
  }, [open, form]);

  const puskesmasId = form.watch("puskesmas_id");
  const skipAsik = form.watch("skip_asik_detail");
  const pkDetail = usePuskesmas(puskesmasId || undefined);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      const job = await start.mutateAsync(values);
      toast.success(`Proses laporan GDP dimulai untuk ${job.puskesmas_name}`);
      setOpen(false);
    } catch (err) {
      applyApiErrorToForm(err, form.setError, KNOWN_FIELDS);
    }
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button onClick={() => setOpen(true)}>Mulai Laporan GDP</Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Mulai Kertas Kerja DM Terkendali</DialogTitle>
          <DialogDescription>
            Menelusuri ASIK + Medisy untuk setiap tanggal dalam rentang, lalu
            merangkum GD Puasa per bulan per NIK pada dashboard di bawah.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label>Puskesmas</Label>
            <AsyncCombobox
              value={puskesmasId || undefined}
              onChange={(v) => form.setValue("puskesmas_id", v ?? "")}
              useOptions={usePuskesmasOptions}
              selectedLabel={pkDetail.data?.name}
              placeholder="Pilih puskesmas…"
            />
            {form.formState.errors.puskesmas_id && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.puskesmas_id.message}
              </p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date_from">Dari tanggal</Label>
              <Input id="date_from" type="date" {...form.register("date_from")} />
              {form.formState.errors.date_from && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.date_from.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="date_to">Sampai tanggal</Label>
              <Input id="date_to" type="date" {...form.register("date_to")} />
              {form.formState.errors.date_to && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.date_to.message}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-start justify-between gap-4 rounded-md border border-[var(--border)] p-3">
            <div className="space-y-1">
              <Label htmlFor="skip_asik_detail" className="text-sm">
                Lewati pengambilan tab formulir ASIK (NIK saja)
              </Label>
              <p className="text-xs text-[var(--muted-foreground)]">
                ASIK tetap ditelusuri per tanggal untuk NIK + Nama, tetapi formulir
                Mandiri / Nakes tidak dibuka. ~10x lebih cepat — disarankan untuk
                laporan GDP karena nilai GDP hanya diambil dari Medisy.
              </p>
            </div>
            <Switch
              id="skip_asik_detail"
              checked={skipAsik}
              onCheckedChange={(v) =>
                form.setValue("skip_asik_detail", Boolean(v), {
                  shouldDirty: true,
                })
              }
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Batal
            </Button>
            <Button type="submit" disabled={start.isPending}>
              {start.isPending ? "Memulai…" : "Mulai"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
