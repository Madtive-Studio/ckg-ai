import { Badge } from "@/components/ui/badge";
import { JOB_STATUS_LABEL } from "@/lib/source-names";
import type { GdpReportStatus } from "@/lib/api/types";

const VARIANT: Record<
  GdpReportStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function GdpStatusBadge({ status }: { status: GdpReportStatus }) {
  return <Badge variant={VARIANT[status]}>{JOB_STATUS_LABEL[status]}</Badge>;
}
