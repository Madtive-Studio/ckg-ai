"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import { Copy } from "lucide-react";
import { format, parseISO } from "date-fns";
import { useCreateCredentialInvite } from "@/lib/hooks/use-puskesmas";
import { asApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

export function InviteLinkDialog({
  open,
  onOpenChange,
  puskesmasId,
  isCredSet,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  puskesmasId: string;
  isCredSet: boolean;
}) {
  const create = useCreateCredentialInvite();
  const { reset } = create;

  // A link is shown once and is not recoverable; never carry one over to the next open.
  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  const handleCreate = async () => {
    try {
      await create.mutateAsync(puskesmasId);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const handleCopy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Tautan disalin");
    } catch {
      toast.error("Gagal menyalin. Salin manual dari kolom.");
    }
  };

  const invite = create.data;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Tautan undangan ASIK</DialogTitle>
          <DialogDescription>
            Kirim tautan ini ke puskesmas. Mereka mengisi kredensial ASIK sendiri tanpa login. Tautan
            hanya berlaku satu kali dan 7 hari; membuat tautan baru mematikan tautan lama.
          </DialogDescription>
        </DialogHeader>
        {isCredSet && (
          <p className="rounded-md bg-[var(--muted)] p-2 text-xs text-[var(--muted-foreground)]">
            Kredensial ASIK sudah terisi. Jika puskesmas mengirim lewat tautan ini, kredensial lama akan
            tertimpa.
          </p>
        )}
        {invite ? (
          <div className="space-y-2">
            <div className="flex gap-2">
              <Input readOnly value={invite.url} onFocus={(e) => e.currentTarget.select()} />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => handleCopy(invite.url)}
                aria-label="Salin tautan"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
            <p className="text-xs text-[var(--muted-foreground)]">
              Berlaku sampai {format(parseISO(invite.expires_at), "d MMM yyyy HH:mm")}. Tautan ini tidak
              bisa ditampilkan lagi setelah dialog ditutup.
            </p>
          </div>
        ) : (
          <Button onClick={handleCreate} disabled={create.isPending}>
            {create.isPending ? "Membuat…" : "Buat tautan"}
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
}
