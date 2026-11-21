import { Badge } from "@/components/ui/badge";
import { JOB_STATUS_LABEL } from "@/lib/source-names";
import type { ScrapeStatus } from "@/lib/api/types";

const VARIANT: Record<
  ScrapeStatus,
  "default" | "secondary" | "destructive" | "success" | "warning"
> = {
  pending: "secondary",
  running: "warning",
  success: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function ScrapeStatusBadge({ status }: { status: ScrapeStatus }) {
  return <Badge variant={VARIANT[status]}>{JOB_STATUS_LABEL[status]}</Badge>;
}
