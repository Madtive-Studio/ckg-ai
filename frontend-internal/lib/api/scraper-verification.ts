import { z } from "zod";
import { http } from "./client";
import { ScraperVerificationSignalOut, type ScraperVerificationSignal } from "./types";

export async function listScraperVerificationSignals(): Promise<ScraperVerificationSignal[]> {
  const { data } = await http.get("/admin/scraper-verification");
  return z.array(ScraperVerificationSignalOut).parse(data);
}

export async function acknowledgeScraperVerificationSignal(id: string): Promise<void> {
  await http.post(`/admin/scraper-verification/${id}/acknowledge`);
}
