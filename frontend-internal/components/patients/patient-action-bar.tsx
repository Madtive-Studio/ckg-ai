"use client";

import { useRouter } from "next/navigation";
import { RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { asApiError } from "@/lib/api/client";
import { useStartPatientMerge } from "@/lib/hooks/use-merge";
import { useStartPatientScrape } from "@/lib/hooks/use-scrape";
import type { Patient } from "@shared/patients/types";

export function PatientActionBar({ patient }: { patient: Patient }) {
  const router = useRouter();
  const startScrape = useStartPatientScrape(patient.id);
  const startMerge = useStartPatientMerge(patient.id);

  const canMerge = patient.has_asik_data && patient.has_epus_data;

  const onMerge = async () => {
    try {
      const job = await startMerge.mutateAsync();
      toast.success("Gabung data dimulai");
      router.push(`/merge-with-ai/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRescrapeAsik = async () => {
    try {
      const job = await startScrape.mutateAsync({ kind: "asik" });
      toast.success("Ambil ulang data ASIK dimulai");
      router.push(`/scrape-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRescrapeEpus = async () => {
    try {
      const job = await startScrape.mutateAsync({ kind: "epus" });
      toast.success("Ambil ulang data Medisy dimulai");
      router.push(`/scrape-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        onClick={onRescrapeAsik}
        disabled={startScrape.isPending}
        title="Ambil ulang data ASIK pasien ini berdasarkan NIK"
      >
        <RefreshCw className="h-4 w-4" />
        Ambil ulang ASIK
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={onRescrapeEpus}
        disabled={startScrape.isPending}
        title="Ambil ulang data Medisy pasien ini memakai tanggal filternya"
      >
        <RefreshCw className="h-4 w-4" />
        Ambil ulang Medisy
      </Button>
      <Button
        size="sm"
        variant="default"
        onClick={onMerge}
        disabled={!canMerge || startMerge.isPending}
        title={canMerge ? "Gabung ulang data pasien ini dengan AI" : "Butuh data ASIK dan Medisy yang sudah diambil sebelum digabung"}
      >
        <Sparkles className="h-4 w-4" />
        Gabung data dengan AI
      </Button>
    </div>
  );
}
