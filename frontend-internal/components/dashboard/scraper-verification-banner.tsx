"use client";

import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { asApiError } from "@/lib/api/client";
import type { ScraperVerificationSignal } from "@/lib/api/types";
import {
  useAcknowledgeScraperVerification,
  usePendingScraperVerification,
} from "@/lib/hooks/use-scraper-verification";
import {
  SCRAPER_VERIFICATION_OUTCOME,
  SCRAPER_VERIFICATION_QUESTION,
} from "@/lib/scraper-verification-labels";

function SignalRow({ signal }: { signal: ScraperVerificationSignal }) {
  const ack = useAcknowledgeScraperVerification();
  const question = SCRAPER_VERIFICATION_QUESTION[signal.code] ?? signal.code;
  const problem = signal.outcome === "problem";

  return (
    <li className="flex flex-col gap-2 border-t border-amber-500/30 pt-3 first:border-t-0 first:pt-0 sm:flex-row sm:items-start sm:justify-between">
      <div className="space-y-1 text-sm">
        <p>
          <span className="font-medium">{question}</span>{" "}
          <span className={problem ? "text-[var(--destructive)]" : ""}>
            {SCRAPER_VERIFICATION_OUTCOME[signal.outcome]}
          </span>
        </p>
        <p className="text-xs text-[var(--muted-foreground)]">
          Berhasil {signal.ok_count}, gagal {signal.problem_count} · {signal.puskesmas_name} ·{" "}
          {new Date(signal.created_at).toLocaleString("id-ID")} ·{" "}
          <Link href={`/scrape-jobs/${signal.scrape_job_id}`} className="underline underline-offset-2">
            Lihat proses
          </Link>
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        disabled={ack.isPending}
        onClick={() =>
          ack.mutate(signal.id, { onError: (err) => toast.error(asApiError(err).message) })
        }
      >
        Tandai sudah dilihat
      </Button>
    </li>
  );
}

/** Shown on the admin dashboard when a production scrape first saw data that answers a scraper question still
 * marked "Not yet verified" in scrapers/asik/CLAUDE.md. Renders nothing when there is nothing pending. */
export function ScraperVerificationBanner() {
  const pending = usePendingScraperVerification();
  if (!pending.data?.length) return null;

  return (
    <div className="space-y-3 rounded-lg border border-amber-500/60 bg-amber-500/10 p-4">
      <div>
        <h2 className="text-sm font-semibold">Ada data baru untuk verifikasi scraper ASIK</h2>
        <p className="text-xs text-[var(--muted-foreground)]">
          Data ini belum pernah ada saat scraper diuji. Minta pengembang memeriksanya (sertakan tautan
          prosesnya), lalu tandai sudah dilihat.
        </p>
      </div>
      <ul className="space-y-3">
        {pending.data.map((s) => (
          <SignalRow key={s.id} signal={s} />
        ))}
      </ul>
    </div>
  );
}
