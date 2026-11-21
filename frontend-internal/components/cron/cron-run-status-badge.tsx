import { Badge } from "@/components/ui/badge";
import { JOB_STATUS_LABEL } from "@/lib/source-names";
import type { CronRunStatus } from "@/lib/api/types";

const VARIANT: Record<
  CronRunStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function CronRunStatusBadge({ status }: { status: CronRunStatus }) {
  return <Badge variant={VARIANT[status]}>{JOB_STATUS_LABEL[status]}</Badge>;
}
