"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Upload, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { PatientActionBar } from "@/components/patients/patient-action-bar";
import { PatientDetail } from "@shared/patients/components/patient-detail";
import { usePatient } from "@shared/patients/use-patients";
import { useStartCreateAsik, useStartResendAsik, useStartSyncAsik } from "@/lib/hooks/use-sync";
import { asApiError } from "@/lib/api/client";

export default function PatientDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const patient = usePatient(id);
  const router = useRouter();
  const startSync = useStartSyncAsik();
  const startCreate = useStartCreateAsik();
  const startResend = useStartResendAsik();

  const handleSyncAsik = async () => {
    try {
      const job = await startSync.mutateAsync({ patientId: id });
      toast.success("Pengiriman ke ASIK dimulai");
      router.push(`/sync-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const handleCreateAsik = async () => {
    try {
      const job = await startCreate.mutateAsync({ patientId: id });
      toast.success("Pendaftaran ke ASIK dimulai");
      router.push(`/sync-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const handleResendAsik = async () => {
    try {
      const job = await startResend.mutateAsync({ patientId: id });
      toast.success("Kirim ulang ke ASIK dimulai");
      router.push(`/sync-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const p = patient.data;
  // Sync requires matched + AI-merged data. The Medisy-only fallback is disabled by
  // scope (kept behind this flag so it can be restored later; mirrors the backend
  // ALLOW_EPUS_ONLY_SYNC in tasks/sync.py).
  const ALLOW_EPUS_ONLY_SYNC = false;
  const canSync =
    !!p &&
    (p.has_merged_data ||
      (ALLOW_EPUS_ONLY_SYNC && p.match_status === "epus_only" && p.has_epus_data));
  // Create-in-ASIK: an epus_only + Tandai-CKG patient not yet in ASIK (no merged
  // data). Registers them into ASIK from scratch, then fills — same job/log UI as
  // sync. Backend re-validates; it also needs a default alamat on the puskesmas.
  const canCreate =
    !!p &&
    p.match_status === "epus_only" &&
    p.epus_tandai_ckg === true &&
    p.has_epus_data &&
    !p.has_merged_data &&
    p.ever_sent_to_asik !== true; // already in ASIK → "Kirim ulang", never register again
  // Kirim ulang: already sent once → straight to Pelayanan from the stored Medisy data (re-fetch Medisy from the
  // puskesmas page first if it changed).
  const canResend = !!p && p.has_epus_data && p.ever_sent_to_asik === true;

  return (
    <PatientDetail
      id={id}
      actions={
        p ? (
          <>
            <PatientActionBar patient={p} />
            {canSync && (
              <Button
                size="sm"
                onClick={handleSyncAsik}
                disabled={startSync.isPending}
                title={
                  p.has_merged_data
                    ? "Kirim data gabungan ke ASIK"
                    : "Kirim data yang hanya ada di Medisy (dikonversi otomatis ke bentuk ASIK) ke ASIK"
                }
              >
                <Upload className="h-4 w-4" />
                Kirim ke ASIK
              </Button>
            )}
            {canResend && (
              <Button
                size="sm"
                variant="outline"
                onClick={handleResendAsik}
                disabled={startResend.isPending}
                title="Kirim ulang data Medisy yang tersimpan ke ASIK: langsung ke halaman Pelayanan tanpa cek pendaftaran"
              >
                <RefreshCw className="h-4 w-4" />
                Kirim ulang
              </Button>
            )}
            {canCreate && (
              <Button
                size="sm"
                onClick={handleCreateAsik}
                disabled={startCreate.isPending}
                title="Daftarkan pasien ini ke ASIK dari awal, lalu isi pemeriksaannya"
              >
                <UserPlus className="h-4 w-4" />
                Daftarkan ke ASIK
              </Button>
            )}
          </>
        ) : null
      }
    />
  );
}
