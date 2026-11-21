import { Badge } from "@/components/ui/badge";
import { JOB_STATUS_LABEL } from "@/lib/source-names";
import type { MergeStatus } from "@/lib/api/types";

const VARIANT: Record<
  MergeStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function MergeStatusBadge({ status }: { status: MergeStatus }) {
  return <Badge variant={VARIANT[status]}>{JOB_STATUS_LABEL[status]}</Badge>;
}
