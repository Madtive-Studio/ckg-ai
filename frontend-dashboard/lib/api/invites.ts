import { http } from "./client";
import { InviteInfoOut, type InviteAsikInput, type InviteInfo } from "./types";

export async function getInvite(token: string): Promise<InviteInfo> {
  const { data } = await http.get(`/invites/${encodeURIComponent(token)}`);
  return InviteInfoOut.parse(data);
}

export async function submitInviteAsik(token: string, input: InviteAsikInput): Promise<void> {
  await http.post(`/invites/${encodeURIComponent(token)}/asik`, input);
}
