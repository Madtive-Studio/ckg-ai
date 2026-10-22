"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Eye, EyeOff } from "lucide-react";
import { InviteAsikIn, type InviteAsikInput } from "@/lib/api/types";
import { useInvite, useSubmitInviteAsik } from "@/lib/hooks/use-invite";
import { applyApiErrorToForm } from "@/lib/api/form-errors";
import { asApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{children}</CardDescription>
      </CardHeader>
    </Card>
  );
}

export function InviteAsikForm({ token }: { token: string }) {
  const invite = useInvite(token);
  const submit = useSubmitInviteAsik(token);
  const [reveal, setReveal] = useState(false);
  const form = useForm<InviteAsikInput>({
    resolver: zodResolver(InviteAsikIn),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await submit.mutateAsync(values);
      toast.success("Kredensial ASIK tersimpan");
    } catch (err) {
      if (asApiError(err).status === 410) return; // the page flips to the used/expired notice
      applyApiErrorToForm(err, form.setError, ["email", "password"] as const);
    }
  });

  if (invite.isPending) {
    return <p className="text-sm text-[var(--muted-foreground)]">Memuat…</p>;
  }
  if (invite.isError) {
    const notFound = asApiError(invite.error).status === 404;
    return (
      <Notice title={notFound ? "Tautan tidak valid" : "Gagal memuat"}>
        {notFound
          ? "Tautan ini tidak dikenali. Periksa kembali tautan yang Anda terima atau hubungi admin."
          : asApiError(invite.error).message}
      </Notice>
    );
  }

  const info = invite.data;
  if (info.status === "used") {
    return (
      <Notice title="Kredensial sudah tersimpan">
        Kredensial ASIK sudah diatur. Tautan ini tidak berlaku lagi dan tidak dapat dipakai ulang.
      </Notice>
    );
  }
  if (info.status === "expired") {
    return (
      <Notice title="Tautan kedaluwarsa">
        Tautan ini sudah tidak berlaku. Hubungi admin untuk meminta tautan baru.
      </Notice>
    );
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Kredensial ASIK</CardTitle>
        <CardDescription>
          Masukkan akun ASIK untuk puskesmas berikut. Tautan ini hanya bisa dipakai satu kali dan
          hangus setelah Anda menyimpan.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <dl className="space-y-1 text-sm">
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-[var(--muted-foreground)]">Puskesmas</dt>
            <dd className="font-medium">{info.puskesmas_name}</dd>
          </div>
          {info.asik_url && (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-[var(--muted-foreground)]">ASIK</dt>
              <dd className="break-all">{info.asik_url}</dd>
            </div>
          )}
        </dl>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="asik-email">Email</Label>
            <Input id="asik-email" autoComplete="off" {...form.register("email")} />
            {form.formState.errors.email && (
              <p className="text-xs text-[var(--destructive)]">{form.formState.errors.email.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="asik-password">Kata Sandi</Label>
            <div className="flex gap-2">
              <Input
                id="asik-password"
                type={reveal ? "text" : "password"}
                autoComplete="off"
                {...form.register("password")}
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
            {form.formState.errors.password && (
              <p className="text-xs text-[var(--destructive)]">{form.formState.errors.password.message}</p>
            )}
          </div>
          <Button type="submit" className="w-full" disabled={submit.isPending}>
            {submit.isPending ? "Menyimpan…" : "Simpan"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
