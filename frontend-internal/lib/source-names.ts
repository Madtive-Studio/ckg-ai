/** Display names of the two data sources. The API keeps the old kind/column names (`epus`, `epus_url`, `epus_cred`); the clinic-record source is Medisy now — never show "EPUS" to users. */
export const SOURCE_NAME = { epus: "Medisy", asik: "ASIK" } as const;

/** Scrape-job kind → label (API values stay `asik` / `epus` / `asik_sekolah`). */
export const SCRAPE_KIND_LABEL = {
  asik: "ASIK",
  epus: "Medisy",
  asik_sekolah: "CKG Sekolah",
} as const;

/** Pipeline step of a scheduled run / backfill → label. */
export const STEP_LABEL = {
  asik: "Ambil data ASIK",
  epus: "Ambil data Medisy",
  merge: "Gabung data",
  sync: "Kirim ke ASIK",
  create: "Buat pasien di ASIK",
} as const;

/** Status shared by every job type (scrape, merge, sync, schedule, backfill, GDP). */
export const JOB_STATUS_LABEL = {
  pending: "menunggu",
  running: "berjalan",
  success: "berhasil",
  failed: "gagal",
  cancelled: "dibatalkan",
} as const;

/** GDP-report job phase → label. */
export const GDP_PHASE_LABEL = {
  pending: "menunggu",
  asik: "ASIK",
  epus: "Medisy",
  done: "selesai",
} as const;
