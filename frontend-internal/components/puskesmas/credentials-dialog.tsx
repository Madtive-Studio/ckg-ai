"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Eye, EyeOff } from "lucide-react";
import {
  CredIn,
  MedisyCredIn,
  type CredInput,
  type MedisyConnectionTest,
  type MedisyCredInput,
} from "@/lib/api/types";
import {
  useClearCredentials,
  useDecryptCredentials,
  useSetCredentials,
  useTestMedisyConnection,
} from "@/lib/hooks/use-puskesmas";
import { asApiError } from "@/lib/api/client";
import { applyApiErrorToForm } from "@/lib/api/form-errors";
import type { CredKind } from "@/lib/api/puskesmas";
import { SOURCE_NAME } from "@/lib/source-names";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDialog } from "@/components/common/confirm-dialog";

export function CredentialsDialog({
  open,
  onOpenChange,
  puskesmasId,
  kind,
  isCredSet,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  puskesmasId: string;
  kind: CredKind;
  isCredSet: boolean;
}) {
  const [reveal, setReveal] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [testResult, setTestResult] = useState<MedisyConnectionTest | null>(null);
  const set = useSetCredentials();
  const clear = useClearCredentials();
  const decrypt = useDecryptCredentials();
  const testConnection = useTestMedisyConnection();
  const isMedisy = kind === "epus";
  const sourceName = SOURCE_NAME[kind];

  // One form for both shapes: ASIK has email + password, Medisy has a token only.
  const form = useForm<CredInput & MedisyCredInput>({
    resolver: zodResolver(isMedisy ? MedisyCredIn : CredIn) as never,
    defaultValues: { email: "", password: "", token: "" },
  });

  const handleReveal = async () => {
    try {
      const data = await decrypt.mutateAsync({ id: puskesmasId, kind });
      form.reset({ email: "", password: "", token: "", ...data });
      setReveal(true);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      const input = isMedisy
        ? { token: values.token }
        : { email: values.email, password: values.password };
      await set.mutateAsync({ id: puskesmasId, kind, input });
      toast.success(`Kredensial ${sourceName} disimpan`);
      setTestResult(null);
      onOpenChange(false);
    } catch (err) {
      applyApiErrorToForm(
        err,
        form.setError,
        (isMedisy ? ["token"] : ["email", "password"]) as never,
      );
    }
  });

  const handleClear = async () => {
    try {
      await clear.mutateAsync({ id: puskesmasId, kind });
      toast.success("Kredensial dihapus");
      form.reset({ email: "", password: "", token: "" });
      setTestResult(null);
      setConfirmClear(false);
      onOpenChange(false);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const handleTest = async () => {
    try {
      setTestResult(await testConnection.mutateAsync(puskesmasId));
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const secretField = isMedisy ? "token" : "password";

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Kredensial {sourceName}</DialogTitle>
          <DialogDescription>
            Disimpan terenkripsi. Tampilkan untuk melihat, simpan untuk memperbarui.
            {isMedisy && " Token diterbitkan oleh Medisy untuk puskesmas ini."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          {!isMedisy && (
            <div className="space-y-2">
              <Label htmlFor="cred-email">Email</Label>
              <Input id="cred-email" autoComplete="off" {...form.register("email")} />
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="cred-secret">{isMedisy ? "Token API" : "Kata Sandi"}</Label>
            <div className="flex gap-2">
              <Input
                id="cred-secret"
                type={reveal ? "text" : "password"}
                autoComplete="off"
                {...form.register(secretField)}
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => setReveal((v) => !v)}
                aria-label="Alihkan visibilitas"
              >
                {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
            {isMedisy && form.formState.errors.token && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.token.message}
              </p>
            )}
          </div>
          {isMedisy && (
            <div className="space-y-2">
              <Button
                type="button"
                variant="outline"
                onClick={handleTest}
                disabled={!isCredSet || testConnection.isPending}
              >
                {testConnection.isPending ? "Menguji…" : "Tes koneksi"}
              </Button>
              {!isCredSet && (
                <p className="text-xs text-[var(--muted-foreground)]">
                  Simpan token dulu, lalu tes koneksi.
                </p>
              )}
              {testResult && (
                <p
                  className={`text-xs ${
                    testResult.ok ? "text-green-700" : "text-[var(--destructive)]"
                  }`}
                >
                  {testResult.ok
                    ? `Terhubung ke ${testResult.clinic_name ?? "Medisy"} (API v${testResult.api_version}, ${testResult.latency_ms} ms)`
                    : `Gagal: ${testResult.error ?? "tidak diketahui"}`}
                </p>
              )}
            </div>
          )}
          <DialogFooter className="flex-row justify-between sm:justify-between">
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={handleReveal}
                disabled={!isCredSet || decrypt.isPending}
              >
                {decrypt.isPending ? "Memuat…" : "Tampilkan"}
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => setConfirmClear(true)}
                disabled={!isCredSet || clear.isPending}
              >
                Hapus
              </Button>
            </div>
            <Button type="submit" disabled={set.isPending}>
              {set.isPending ? "Menyimpan…" : "Simpan"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    <ConfirmDialog
      open={confirmClear}
      onOpenChange={setConfirmClear}
      title={`Hapus kredensial ${sourceName}?`}
      description="Ini akan menghapus kredensial tersimpan secara permanen dan tidak bisa dibatalkan."
      confirmLabel="Hapus"
      destructive
      loading={clear.isPending}
      onConfirm={handleClear}
    />
    </>
  );
}
