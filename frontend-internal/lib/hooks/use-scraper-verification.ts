"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acknowledgeScraperVerificationSignal,
  listScraperVerificationSignals,
} from "@/lib/api/scraper-verification";
import type { ScraperVerificationSignal } from "@/lib/api/types";

export const scraperVerificationKeys = {
  all: ["scraper-verification"] as const,
  pending: () => [...scraperVerificationKeys.all, "pending"] as const,
};

export function usePendingScraperVerification() {
  return useQuery({
    queryKey: scraperVerificationKeys.pending(),
    queryFn: listScraperVerificationSignals,
    staleTime: 5 * 60_000,
  });
}

export function useAcknowledgeScraperVerification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => acknowledgeScraperVerificationSignal(id),
    onSuccess: (_data, id) => {
      qc.setQueryData<ScraperVerificationSignal[]>(scraperVerificationKeys.pending(), (old) =>
        old ? old.filter((s) => s.id !== id) : old,
      );
    },
  });
}
