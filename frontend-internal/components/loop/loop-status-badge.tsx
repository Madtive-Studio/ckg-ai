import { Badge } from "@/components/ui/badge";
import type { LoopRunStatus } from "@/lib/api/types";

const VARIANT: Record<
  LoopRunStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  covered: "success",
  no_data: "secondary",
  needs_review: "warning",
  merged: "success",
  pr_rejected: "destructive",
  changes_ready: "default",
  bad_creds: "destructive",
  failed: "destructive",
  cancelled: "secondary",
};

const LABEL: Record<LoopRunStatus, string> = {
  pending: "menunggu",
  running: "berjalan",
  covered: "tercakup",
  no_data: "tidak ada data",
  needs_review: "perlu ditinjau",
  merged: "digabung",
  pr_rejected: "PR ditolak",
  changes_ready: "perubahan siap",
  bad_creds: "kredensial salah",
  failed: "gagal",
  cancelled: "dibatalkan",
};

export function LoopStatusBadge({ status }: { status: LoopRunStatus }) {
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>;
}
