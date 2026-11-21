// What each scraper-verification code means, in the admin's words. Codes come from
// backend/app/services/scraper_verification.py (QUESTIONS) — keep both in sync.
export const SCRAPER_VERIFICATION_QUESTION: Record<string, string> = {
  asik_nakes_filled: "Formulir Pelayanan Nakes yang sudah dikirim di ASIK",
  asik_tatalaksana: "Data tatalaksana pasien di ASIK",
  asik_tab_belum: "Pasien di tab Belum Pemeriksaan ASIK",
  asik_tab_sedang: "Pasien di tab Sedang Pemeriksaan ASIK",
  asik_detail_failed: "Detail pasien ASIK yang gagal dibuka (setelah dicoba ulang)",
};

export const SCRAPER_VERIFICATION_OUTCOME: Record<"answered" | "problem", string> = {
  answered: "ditemukan dan berhasil dibaca",
  problem: "ditemukan, tetapi ada yang gagal dibaca",
};
