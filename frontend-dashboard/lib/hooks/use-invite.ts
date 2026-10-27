"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { asApiError } from "@/lib/api/client";
import { getInvite, submitInviteAsik } from "@/lib/api/invites";
import type { InviteAsikInput, InviteInfo } from "@/lib/api/types";

export const inviteKeys = {
  all: ["invite"] as const,
  detail: (token: string) => [...inviteKeys.all, "detail", token] as const,
};

export function useInvite(token: string) {
  return useQuery({
    queryKey: inviteKeys.detail(token),
    queryFn: () => getInvite(token),
    retry: false, // a 404/410 is the answer, not a blip
  });
}

export function useSubmitInviteAsik(token: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: InviteAsikInput) => submitInviteAsik(token, input),
    onSuccess: () => {
      const used: InviteInfo = { status: "used", puskesmas_name: null, asik_url: null };
      qc.setQueryData(inviteKeys.detail(token), used);
    },
    onError: (err) => {
      // 410 = the link was used/expired between page load and submit; only the server knows which.
      if (asApiError(err).status === 410) {
        qc.invalidateQueries({ queryKey: inviteKeys.detail(token) });
      }
    },
  });
}
