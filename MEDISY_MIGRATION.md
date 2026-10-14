# Migration plan — ePuskesmas (EPUS) → Medisy (`himed-app`) as the clinic data source

> **Direction change (2026-10-05, decided with the owner): the whole app moves to Medisy. There is no rollback to EPUS,
> no per-puskesmas source switch and no per-row source tag.** Existing EPUS-sourced patient rows are **replaced** with
> Medisy data (re-pulled, then deleted), and the EPUS scraper, converter and loop-agent are **removed — as the last
> step**, once the Medisy path exists, so the live app is never left unable to scrape, merge or sync. Where an older
> paragraph below still describes a dual-source design (D3, D7, §2.4, Phase 3b, the rollback in Phase 7), the **Direction
> change notes in those sections win**.

**Scope.** Replace EPUS as the *clinic-record source* for ckg-ai with Medisy
(`/Users/fahlaosa/Documents/Projects/himed-app`, CodeIgniter 3 HMVC, MySQL). ASIK stays as it is.
You write the **data mapping** (Medisy → ASIK forms) yourself; this document covers **which APIs
Medisy must expose**, **what ckg-ai must change**, and **the order to do it in**.

**Decisions taken** (see §1): **Option B** — Medisy gets its own `medisy_to_asik` converter and the
code that reads the source blob is refactored to be source-neutral. **CKG = the visit's poli name
*contains* `CKG`, OR the visit's insurance is a PKG/CKG insurance** (§5.4; settled in Phase 0 against UAT
data). **Single tenant** — Medisy
returns one clinic, so there is no per-clinic scoping anywhere in this plan.

> Everything below was read from both repos. Items marked **(verify)** are inferred from names or
> from code I did not run, and must be confirmed against real rows before you rely on them.

---

## 0. TL;DR

1. ckg-ai currently **scrapes EPUS's website** with Playwright (login → list → ~33 HTML tabs per
   patient). Medisy is *your* system, so **don't scrape it — give it a read-only JSON API** and have
   ckg-ai call that. No captcha, no HTML drift, no loop-agent needed for it.
2. Medisy already has a small `medisy_api` module, but **none of it fits** (no visits-by-date, no bulk
   detail, no screenings, no CKG flag, no change feed). You need **5 required endpoints + 2
   recommended** (§5).
3. Because you chose **Option B**, ckg-ai stores Medisy's **native** JSON (not an EPUS look-alike) and
   gets a `medisy_to_asik.py` converter. ~15 files read the EPUS blob directly; since the whole app moves to Medisy
   they are **re-pointed at the Medisy bundle** (no source interface, no dual support), and five of them are
   **hash-pinned by the chatbot lock**, so that change needs a re-bless (§6, Phase 3b).
4. Order of work: Medisy API ✅ → Medisy client + `{token}` credential + Test connection ✅ → Medisy fetch path
   (replaces the EPUS scrape) → converter + accessors, consumers re-pointed (clinical rules unchanged) → quality gate →
   **replace the EPUS rows with Medisy data** → **remove the EPUS code (last)**.

---

## 1. Decisions

| # | Decision | Status | Notes |
|---|---|---|---|
| D1 | EPUS-shaped output (A) or a new Medisy converter (B)? | ✅ **B** | Native Medisy blob + `medisy_to_asik.py` + source interface (§2.4). |
| D2 | Where does the mapping live? | ✅ ckg-ai: `medisy_to_asik.py` | The Medisy API stays native/neutral; mapping bugs are fixed in one repo with tests. |
| D3 | How do puskesmas switch? | ✅ **They don't.** *(was: `puskesmas.source_system` flag)* | **Direction change:** the whole app uses Medisy; there is **no rollback to EPUS** and no per-puskesmas flag. No `source_system` column anywhere, so Phase 3a needs **no migration**. |
| D4 | Medisy API auth | Proposed | One **dedicated bearer token for ckg-ai** (not the global `MEDISY_API_TOKEN` that other integrations use), HTTPS, optional IP allow-list. |
| D5 | What is a "CKG visit" in Medisy? | ✅ **Poli name contains `CKG` OR PKG/CKG insurance** | See §5.4. (Was "poli `CKG` now, insurance later"; UAT has no poli named exactly `CKG`.) |
| D6 | Multi-tenant? | ✅ **Not needed** | Medisy returns one clinic. No `id_perusahaan` filtering, no per-clinic tokens. One puskesmas in ckg-ai ↔ one `(base_url, token)`. |
| D7 | Where does a Medisy record live in the `patients` table? | ✅ **Same column, no tag** | Medisy records go in `patients.scraped_epus_data` (the column name stays; renaming is a separate, optional PR). **Direction change:** there is no per-row `source_system` tag because there is no mixed history — the existing EPUS rows are **replaced** with Medisy data (§6 Phase 7). Until that replacement runs, a Medisy blob is recognisable by its own `api_version` / `_meta.source` keys (D8). |
| D8 | Version number inside the stored record | ✅ **Yes** | Each stored Medisy record carries `api_version` (the API already returns it, §5.2) plus `_meta {source, fetched_at}`. Costs nothing now; lets the converter read old records after you change the API shape. |
| D11 | What happens to the existing EPUS rows and code? | ✅ **Replace the rows; remove the code last** | Re-pull the history from Medisy, reconcile per puskesmas and date, **then** delete the EPUS rows (a script the owner runs — irreversible, never run by the assistant). Remove the EPUS scraper, `epus_to_asik`, the loop-agent and the EPUS-only paths **after** the Medisy fetch path and converter are live (deleting them earlier leaves the app unable to scrape, merge or sync). |
| D13 | Shared / placeholder NIKs (`00`, one number for several people) | ✅ **(b) flag, don't hide** (2026-10-05) | The API keeps returning the number (D10 stands) and adds `nik_shared` (E2) / `identity.shared` (E3, E4, E6). "Shared" = more than one non-deleted registration with that number and a different name or birth date; a duplicate registration of the same person is not shared. ckg-ai skips flagged visits (reason `shared NIK (more than one person)` in the job notes). |
| D14 | Which visits does the scrape ingest? | ✅ **Every visit of the day, not only CKG** (2026-10-05) | The registries read later non-CKG visits of a patient (Follow Up readings, prescriptions for the tertatalaksana gap) and the newborn registry sits on visits that are not CKG; the old ePuskesmas scrape also read every room. `fetch_day_bundles` asks E2 with `ckg_only=false`; each bundle's `ckg.is_ckg` sets `epus_tandai_ckg`. UAT volume: 46 visits on a day with 18 CKG. |
| D15 | Registration domicile for a Medisy-only patient | ✅ **The patient's own** province/city/district/village from Medisy (2026-10-07) | All four levels required; the puskesmas default alamat is only the fallback; neither = skip that patient. On Pelabuhanratu all 55 CKG patients have a full domicile (some live outside the puskesmas district, so one default would be wrong). The ASIK picker matches whole names case-insensitively incl. KAB./KABUPATEN; unverified against live ASIK. |
| D9 | Which Medisy visits count? | ✅ **Visits matching the §5.4 rule** | `kk_poli.nama LIKE '%CKG%'` **OR** insurance `LIKE` `PKG` / `CKG` / `Pemeriksaan kesehatan gratis`. The clinical data is recorded **in that visit**, so E2 lists those visits and `ruangan` = the visit's own poli (which, for insurance matches, need not be a CKG poli). |
| D10 | What counts as a NIK? | ✅ **`type_identitas` ∈ {`1`, `KTP`, `NIK`} and the number is non-empty** | No length/format validation — the CKG website validates. Visits without a NIK are skipped (the existing "missing NIK" reason). A number with **no** identity type (`-`, `0`, empty) is **not** treated as a NIK. `type_identitas` is an id into `kk_kategori` (`type='IDENTITAS'`): `1` KTP, `2` SIM, `3` PASSPORT, `4` KARTU PELAJAR; older rows hold the strings `NIK` / `KTP` / `-`. Normalise all of them to `identity.type`. |

---

## 2. What ckg-ai takes from the source today

### 2.1 Ingestion shape (today, EPUS)

The EPUS scraper writes `{"patients":[ <blob>, … ]}` (or `{"by_date":{"2026-07-01":{"patients":[…]}}}`).
`tasks/scrape.py::_extract_patients` turns each blob into `(nik, nama, blob, date)`; the upsert stores
it Fernet-encrypted in `patients.scraped_epus_data`, keyed by `(puskesmas, nik, filter_date, ruangan)`.

- **`nik` is mandatory** — entries without a NIK are skipped ("missing NIK").
- `birth_date` is derived from the blob (`services/birthdate.py`); `epus_tandai_ckg` from `ckg.sudah_ckg`.
- Under Option B the Medisy equivalent of `_extract_patients` is written for the **native** bundle.

### 2.2 What information the source must supply

Derived from `EPUS_BREADCRUMBS` (63 ASIK forms / 175 fields) and the registry scans. **This is what your
Medisy API must be able to provide** — how you shape and map it is yours.

| Needed data | Used by | Notes |
|---|---|---|
| **Identity & demographics**: NIK, name, sex, birth place + date, age, address (+ RT/RW, desa/kecamatan/kota/provinsi), phone, marital status | Identity merge (ASIK wins on identity), age/sex gating of **every** ASIK form, birth-date filter, `create_patient` (registers missing patients in ASIK) | The converter emits **no forms** if sex or age is unreadable. |
| **Chronic-disease list** (ICD-10 + name) | Disease flags → form gating (HT/DM/TB/HIV/…), registry eligibility | Prefix scans (A15–A19 TB, A50–A53 syphilis, B16–B24 hepatitis/HIV, …). |
| **Illness history** (self / past / family), **allergies** | Self-reported HT/DM flags | |
| **Vitals & anamnesis**: complaint, BP (+ 2nd reading), HR, RR, temp, SpO₂, height, weight, waist, GDS/GDP/HbA1c | gizi, tekanan darah, gula darah forms; HT/DM/obesitas registries | `kk_kunjungan` / `v_kunjungan` already hold most of these. |
| **Physical exam** and **dental / eye / ear** exam | Periksa Fisik, gigi, mata, telinga forms | |
| **Diagnoses** (ICD-10, primary/secondary, chronic mark) | Flag gating, TB/HIV/IMS forms | |
| **Prescriptions** (drug, dose, qty, compound/racik, every line) | HT/DM registries (drug families) | |
| **Lab results** (test name, result, unit, date, panel parent) | Hb, trombosit, lipid panel, kreatinin/eGFR, SGOT, albumin urin, … | Matched on **normalised test name**, exactly (`hb` ≠ `hba1c`). |
| **Program modules**: PTM questionnaire, PKPR (teen), KIA / kartu bayi (newborn ikterus, PJB), TB Paru register, konseling HIV, KB, imunisasi, catin | Per-program ASIK forms | |
| **Screening battery** (30+ instruments: SKILAS, ADL, PUMA, PHQ-4, SPPB, Mini-Cog, kanker paru/serviks/payudara/kolorektal, thalasemia, imunisasi dewasa, hipertensi, DM, …) | **Primary source** for many answers — a screening value overrides the module value | Needs the **answer and its score** (PHQ-4 item 0–3 → frequency label). |
| **CKG flag** (per calendar year) | `epus_tandai_ckg`, dashboard "tandai CKG", `create_patient` population | A 2025 CKG record must **not** count for a 2026 visit. |
| **CPPT / SOAP notes** | Stored with the blob | Lower priority. |

Not needed: billing, pharmacy stock, accounting, queue ops, BPJS/SatuSehat plumbing.

### 2.3 What a converter must produce (the Option B contract)

From `.claude/skills/ckg-form-research/references/converter-pattern.md`:

```python
def medisy_to_asik(raw: dict) -> dict:      # {asik_form_name: {asik_field_label: value}}
MEDISY_BREADCRUMBS: dict[str, dict[str, str | None]]   # {form: {field label: "source path" | None}}
```

Rules: pure dict-in/dict-out (no LLM, no network, no randomness), defensive `.get()`, **zero
hallucination** (every emitted value traces to the source), `None` = blank, **form and field names
byte-identical to live ASIK**, klaster gating from age + sex, two-tier disease flags (self-report drives
the parent radios; the clinical union only gates forms). The merge, sync and previews consume this
**ASIK-shaped** output, so they stay source-neutral once they can *pick* the converter.

### 2.4 The refactor surface — code that reads the source blob directly

> **Direction change:** the `Source` registry below is **no longer built** — with the whole app on Medisy there is nothing to dispatch between. The table is still the list of code that must be **re-pointed at the Medisy bundle** (Phase 3b/4); the proposed interface can be ignored.

This is the real cost of Option B. Counts are from grep; "pinned" = hash-locked by
`chatbot/knowledge.lock.json` (editing it without re-blessing turns master red — `CLAUDE.md` §10).

| Consumer | How it depends on the EPUS blob | Pinned |
|---|---|---|
| `services/epus_to_asik.py` (3,368 lines) | the converter + `EPUS_BREADCRUMBS`; private helpers `_detect_chronic_flags`, `_disabilitas`, `_status_perkawinan` are imported by others | — |
| `tasks/merge.py` | `epus_to_asik(epus)` (≈L1336) and `EPUS_BREADCRUMBS` for form-name lookup and "ASIK-only form" detection | — |
| `tasks/sync.py` | `epus_to_asik` (EPUS-only fallback, currently disabled by `ALLOW_EPUS_ONLY_SYNC=False`) | — |
| `tasks/create_patient.py` | `epus_to_asik` + `_disabilitas`, `_status_perkawinan`, phone from `data_pasien["No Telp / HP"]` | — |
| `api/routes/patients.py` | `epus_to_asik` for the convert/asik-preview endpoint | — |
| `services/hipertensi_registry_scan.py` | `_extract_td1` (reads `tabs.Anamnesa.fields["Periksa Fisik"]`), riwayat, `_extract_obat` (`tabs.Resep.tables`), `_extract_identitas`, `_parse_birthdate`; imports `_detect_chronic_flags` | **yes** |
| `services/dm_registry_scan.py` | same family of extractors; imports `_detect_chronic_flags` | **yes** |
| `services/lipid_registry_scan.py`, `obesitas_registry_scan.py` | extractors over `scraped_epus_data` | **yes** |
| `services/bayi_registry_scan.py` | extractors over the blob (10 refs) | no (verify) |
| `services/dashboard_scan.py` | queries `scraped_epus_data`, `epus_tandai_ckg` | **yes** |
| `services/birthdate.py` | `data_pasien["Tempat/Tgl Lahir"]` | — |
| `services/coverage_hunt.py`, `data/build_mapping.py` | import `EPUS_BREADCRUMBS` | — |
| `crud/patient.py` | upsert / twin / cross-date match-group logic on `scraped_epus_data` (≈10 sites) | — |

**Proposed shape of the fix** — a small registry, e.g. `app/services/sources/`:

```python
class Source(Protocol):
    name: str                                         # "epus" | "medisy"
    def to_asik(self, blob) -> dict: ...              # medisy_to_asik / epus_to_asik
    breadcrumbs: dict
    def identity(self, blob) -> dict: ...             # nik, nama, sex, birth, phone, address…
    def birth_date(self, blob) -> date | None: ...
    def chronic_flags(self, blob) -> dict: ...        # {"self_report": {...}, "clinical": {...}}
    def td1(self, blob) -> tuple[float|None, float|None]: ...
    def riwayat(self, blob) -> ...: ...
    def drugs(self, blob) -> list[str]: ...
    def is_ckg(self, blob) -> bool: ...
def get_source(name: str) -> Source: ...
```

The `epus` implementation **wraps the existing functions unchanged**; consumers switch from
`epus_to_asik(...)` / `_extract_td1(...)` to `get_source(row.source_system).…`. Only the **accessors the
consumers actually use** go in the interface — add methods when a consumer needs them, not speculatively.

---

## 3. Where EPUS is wired into ckg-ai (blast radius under Option B)

| Area | Files / places | Change |
|---|---|---|
| Scrape orchestration | `tasks/scrape.py` (`run_scrape`, `_extract_patients`, `_build_config`), `scrapers/epus/` | **Replace** the EPUS Playwright path with the Medisy API client (`medisy_client.py` ✅): **no Playwright subprocess**; Medisy-native `_extract_patients`; reuse the upsert, job status, Redis log/cancel. |
| Credentials | `puskesmas.epus_url`, `puskesmas.epus_cred`, `PUT /puskesmas/{id}/credentials/epus` | Reuse the columns: `epus_url` = Medisy base URL; `epus_cred` = `{token}`. ✅ Built in Phase 3a. With no rollback, overwriting the EPUS URL/login is fine. |
| Source switch | — | **Dropped** (direction change): no `source_system` columns, no migration. |
| Converter + consumers | §2.4 | **New** `medisy_to_asik.py` (+ accessors); ~15 consumers re-pointed at the Medisy bundle. No source interface (direction change). |
| Scheduling | `tasks/cron.py`, `models/cron_config.py` (`CronStep.EPUS`, `source_scope`) | None — `CronStep.EPUS` / `ScrapeKind.EPUS` keep meaning "clinic-EMR step". |
| Match + merge + sync | `tasks/merge.py`, `tasks/sync.py` | Use `medisy_to_asik` / `MEDISY_BREADCRUMBS`; logic unchanged. |
| Reports | five registry scans + dashboard scan | Extractors move behind the interface; **clinical rules unchanged**; 4 pinned files → re-bless. |
| Column / enum names | `scraped_epus_data`, `epus_only` (17 Alembic files, 19 services, 39 `epus_only` sites) | **Keep** (D7). Renaming is pure churn — a separate, later PR if ever. |
| Research tooling | `.claude/skills/ckg-form-research/scripts/*` | `audit_coverage`, `audit_uncovered`, `verify_converter`, `inspect_source`, `profile_source` take `--source`; `_regions.py::source_column()` assumes `Patient.scraped_<source>_data` (needs a tweak under D7); **`audit_source_completeness.py` is EPUS-only** (it checks the *scraper* against the live site) — replace with API contract tests for Medisy. |
| Loop-agent | `loop-agent/`, `tasks/loop_agent.py` | Exclude `medisy` puskesmas — no scraper to drift. |
| UI labels | `frontend-shared/*` (≈25+ files say "ePus"), `frontend-internal` puskesmas/cron forms | Show the source name; Medisy credential form. Shared UI goes in `frontend-shared/` (`CLAUDE.md` §11). |
| Chatbot packs | `chatbot/knowledge/*.md` (11 files mention EPUS) | Update claims **and** re-bless. |

---

## 4. What Medisy already has — and the gaps

### 4.1 Existing API (`app/application/modules/medisy_api/`)

| Controller | Does | Auth |
|---|---|---|
| `Patient::identity($id)` | one patient's identity | `check_token()` |
| `Checkup::lists($patientId)` / `detail($visitId)` | a patient's visits / one visit (anamnesis, physic, lab, diagnosis, treatment, recipe/racik, KIA, odontogram) | `check_token()` |
| `Queue`, `Doctor`, `Service::poly` | queue / doctor / poli | `check_token()` |
| `Referral`, `Regions`, `Metrics` | referrals, regions, dashboards | **no `check_token()` call found** in the files I read **(verify)** |

Auth today (`helpers/login_helper.php::check_token`): header `x-api-token` must equal the single env
constant `MEDISY_API_TOKEN`. The separate `api` module has `rest_auth = FALSE`, `rest_enable_keys = FALSE`.

### 4.2 Gaps vs. what ckg-ai needs

- ❌ No "all visits for a date / room" — only per-patient history.
- ❌ No bulk detail — `Checkup::detail` is one visit per call.
- ❌ No screening data (`kk_skrining_*`, `kk_skilas`, PTM questionnaires) and no CKG flag.
- ❌ No change feed (ckg-ai re-reads the last `lookback_days` = 3 days because data lands late).
- ❌ No NIK lookup, no dedicated token for ckg-ai, no pagination convention.
- ⚠️ `Checkup::detail` builds SQL by string interpolation (`WHERE id = '$visitId'`) — don't copy it; bind parameters in the new endpoints.

### 4.3 Medisy data that looks like the right source (all **(verify)**)

| Need | Candidate Medisy source |
|---|---|
| Patient / identity | `kk_pendaftaran` (`no_identitas`, `type_identitas`, `nama`, `tanggal_lahir`, `place_of_birth`, `alamat`, RT/RW, `desa/kecamatan/kota/provinsi`) |
| Visit + vitals | `kk_kunjungan` — view **`v_kunjungan`** already joins patient + poli + doctor + region and exposes height, weight, BP, HR, RR, SpO₂, temp, GDP, GDS, HbA1c, waist, `created`, `updated`, `ket` |
| Physical exam / diagnoses / procedures | `kk_pemeriksaan_pasien`, `kk_pemeriksaan_diagnosa`, `kk_pemeriksaan_tindakan` |
| Prescriptions | `kk_resep_obat`, `kk_racik`, `kk_racik_obat` |
| Lab | `kk_pemeriksaan_lab`, `kk_pemeriksaan_tambahan_lab` |
| Programs | `kk_pemeriksaan_hamil`, `kk_pemeriksaan_kb`, `kk_pemeriksaan_imunisasi`, `kk_mtbs*`, `kk_questionnaire_ptm*`, `kk_questionnaire_kunjungan` |
| Screenings | `kk_skrining_*` (hipertensi, diabetes_melitus, puma, ppok, tbc, hiv, ims, kesehatan_jiwa, risiko_jantung, risiko_stroke, kanker_paru, kanker_serviks, risiko_kanker_payudara, kolorektal, thalasemia, anemia, obesitas, gizi, rapuh, pemeriksaan_cog, short_physical_performance, activity_living, pengkajian_nutrisi, imunisasi_tetanus_wus, …), `kk_skilas` |
| CKG/PKG concept | `Laporan/Pkg_model::_get_pkg_data` (rule in §5.4) |
| Incremental sync | `kk_kunjungan.created`, `updated`, `terakhir_ubah_rme`; soft delete via `ket` (`DELETE` / `CANCEL`) |
| Not the CKG screening | `kk_hasil_skrining_rajal` / `kk_config_skrining_rajal` are outpatient **triage** — don't confuse them with the klaster screening |

---

## 5. The APIs to store in Medisy

Put them in the existing module, e.g. `modules/medisy_api/controllers/Ckg.php` (+ `Ckg_model.php`),
routed under `/medisy_api/ckg/…`. **Read-only** (GET; POST only for the batch read).

### 5.1 Endpoint list

| # | Endpoint | Priority | Replaces (EPUS) | Purpose |
|---|---|---|---|---|
| E0 | `GET /medisy_api/ckg/ping` | **Required** | `/login` | Validates the token; returns `{clinic:{name}, api_version, timezone, server_time}` — ckg-ai's "Test connection". |
| E1 | `GET /medisy_api/ckg/rooms` | **Required** | `ruangan_id` values | Poli/rooms `{id, name, is_ckg}` — `is_ckg` = the poli-name half of the §5.4 rule; tells ckg-ai which poli matched. |
| E2 | `GET /medisy_api/ckg/visits?date=YYYY-MM-DD&ckg_only=true&page=1&limit=100` | **Required** | `GET /pelayanan` list | Light list: `visit_id, patient_id, nik, name, room, queue_no, started_at, finished_at, is_ckg, updated_at`. **Max `limit` 100**; `{items, page, limit, total}`. Excludes `ket IN ('DELETE','CANCEL')`. **`ckg_only` defaults to `true`** (visits matching the §5.4 rule, D9); `false` returns all rooms (debugging). |
| E3 | `POST /medisy_api/ckg/visits/batch` body `{"visit_ids":[…]}` (≤ 50) | **Required** | `/pelayanan/show/{id}` + ~33 tab fetches + skrining + ckg + cppt, per patient | The **full visit bundle** (§5.2) for many visits in **one round trip**, built with set-based queries (`CLAUDE.md` §8). |
| E4 | `GET /medisy_api/ckg/visits/{id}` | **Required** | single show | Same bundle for one id (debugging, "re-pull this patient"). |
| E5 | `GET /medisy_api/ckg/visits/changes?since=ISO8601&page=&limit=` | Recommended — **built** (§5.2.2) | — | Ids whose `updated` / `terakhir_ubah_rme` **or any child row** changed since `since`, including cancellations (`deleted: true`). |
| E6 | `GET /medisy_api/ckg/patients/by-nik/{nik}` | Recommended — **built** (§5.2.2) | — | Patient + visit history for one NIK (create-patient checks, "why is this patient missing?"). |

### 5.2 Visit bundle (E3/E4, one object per visit) — this is also the stored blob

Native Medisy naming (English keys, like the existing `medisy_api`). Under Option B the bundle is
**stored as-is** (plus `_meta`, D8) and read by `medisy_to_asik`. **Rules:** unanswered = `null` (never
`""`, never a fabricated default); coded answers carry both `code` and `label`; screening answers carry
the numeric `score` when the instrument has one; ISO-8601 dates with the `Asia/Jakarta` offset; a section
that does not apply is `[]`/`null`, not absent; stable ordering (same visit → byte-identical JSON).

```jsonc
{
  "api_version": 1,
  "visit": { "id": 123, "date": "2026-07-01", "started_at": "...", "finished_at": "...",
             "room": {"id": 1, "name": "CKG"}, "doctor": {"id": 9, "name": "..."},
             "queue_no": "A012", "insurance": {"id": 3, "name": "..."}, "updated_at": "..." },
  "patient": { "id": 55, "no_registration": "...",
               "identity": {"type": "NIK", "number": "3175…"},   // D10: emitted only for type 1/KTP/NIK + non-empty; no format check
               // `gender` normalised from kk_pendaftaran.jenis_kelamin: 1 → "L" (Laki-laki), 2 → "P" (Perempuan);
               // 0 / NULL / '' / anything else → null. Legacy 'L'/'P' strings also occur. Sex null ⇒ converter emits no forms.
               "name": "…", "gender": "P", "place_of_birth": "…", "date_of_birth": "1985-03-15",
               "age": {"years": 41, "months": 3, "days": 16},       // computed AT the visit date
               "address": {"text": "…", "rt": "…", "rw": "…", "village": "…", "district": "…",
                           "city": "…", "province": "…"},
               "phone": "…", "marital_status": "…", "occupation": "…" },
  "chronic_conditions": [ {"icd10": "I10", "name": "Hipertensi"} ],
  "history": { "personal": [ {"name": "…", "since": "…"} ], "family": [ … ], "allergies": [ … ] },
  "anamnesis": { "complaint": "…", "current_illness": "…",
                 "vitals": { "systole": 120, "diastole": 80, "heart_rate": 80, "resp_rate": 18,
                             "temperature": 36.5, "spo2": 98, "height_cm": 160, "weight_kg": 60,
                             "waist_cm": 80, "gds": null, "gdp": null, "hba1c": null } },
  "physical_exam": { "fields": { "<label>": "<value>" }, "dental": { … }, "eye": { … }, "ear": { … } },
  "diagnoses": [ {"icd10": "I10", "name": "…", "type": "primary", "is_chronic": true} ],
  "procedures": [ … ],
  "prescriptions": [ {"drug": "…", "dose": "…", "qty": 30, "signa": "…", "is_compound": false} ],
  "lab": [ {"parent": "Profil Lipid", "test": "Kolesterol Total", "result": "180", "unit": "mg/dL", "date": "…"} ],
  "programs": { "ptm": { … }, "kia": { … }, "kb": { … }, "immunization": [ … ],
                "baby": { … }, "tb": { … }, "hiv_counseling": { … }, "catin": { … }, "pkpr": { … } },
  "screenings": [ { "key": "skilas", "name": "SKILAS", "done": true, "performed_at": "…",
                    "answers": [ {"question_code": "…", "question": "…", "code": "…", "label": "Ya", "score": 1} ] } ],
  "ckg": { "is_ckg": true, "basis": "poli_name",   // "poli_name" | "insurance_name" | "both"
           "year": 2026,
           "records": [ {"date": "2026-07-01", "year": 2026} ] },
  "notes": [ {"date": "…", "doctor": "…", "subjective": "…", "objective": "…", "assessment": "…", "plan": "…"} ]
}
```

Section → ckg-ai need is §2.2; section → Medisy source is §4.3. You decide final field names; the above
is the minimum information, not a fixed schema. **Because the blob persists, treat the schema as
versioned:** additive changes only within an `api_version`, and a new version means `medisy_to_asik`
must read both.

#### 5.2.1 As built (E3/E4, 2026-10-05) — where the real bundle differs from the sketch above

E3 returns `{"items": [bundle…], "missing": [ids]}` (`missing` = unknown, deleted or cancelled visits); E4 returns one
bundle or `404`. Verified on the UAT copy for **all 786 CKG visits**: valid JSON, byte-identical on repeat calls, E4 == E3,
a 50-visit batch in ~0.1 s, and a **flat query count** (86 queries for 1 visit, 87 for 50). An independent SQL audit
matched every section count (diagnoses, procedures, prescriptions, lab, notes, screenings) and the vitals, gender,
age and NIK values for every visit.

| Section | As built | Why it differs |
|---|---|---|
| `screenings[]` | `{key, table, done, performed_at, updated_at, performed_by, answers:[{question_code, value}]}` — **no** `code`/`label`/`score` | Medisy stores one **column per question**; the question text lives only in the PHP views. `question_code` is the column name and `value` the raw (typed) value; the converter maps columns to ASIK questions. An instrument that was not done is absent. `key` = table name minus the `kk_skrining_` prefix (`kk_skilas` → `skilas`). 45 tables are read dynamically, so a new `kk_skrining_*` table appears with no code change. |
| `history` | `{current_illness, personal: [], family: [], allergies: [], diagnoses: […]}` | Medisy has **no history or allergy tables** at all (only `kk_kunjungan.riwayat_peny_sekarang`). `personal/family/allergies` are empty because they are **not captured**, not because the patient has none. `history.diagnoses` lists the patient's diagnoses on earlier visits so the converter can derive chronic flags. |
| `chronic_conditions` | always `[]` | Medisy has no chronic-disease register and no chronic mark on a diagnosis (`diagnoses[].is_chronic` is `null`). Derive from `diagnoses` + `history.diagnoses`. |
| `physical_exam` | `{general, groups:[{group, items:[{name, value}]}], dental}` | `general` = `kk_pemeriksaan_pasien`; `groups` = `kk_pemeriksaan_fisik` grouped by region (eye/ear findings are groups); `dental.odontogram` is Medisy's own chart JSON passed through verbatim (its template contains empty strings — the only place `""` appears). |
| `programs` | `{kia, kb, immunization, catin, child, tb, nutrition, ptm, ptm_questionnaire}`; each value is `{alias: [rows]}` of native columns, or `null` | Generic typed dump of the matching `kk_*` tables (internal keys stripped). `ptm_questionnaire` = FHIR-style question + coded answer (`kk_questionnaire_ptm*`). `hiv_counseling` and `pkpr` have no Medisy table. |
| `anamnesis.vitals` | adds `head_cm`, `arm_cm`, `bmi`; **0 → `null`** | Medisy stores `0` for "not measured" (e.g. 242 visits with height 0 vs 807 NULL). |
| `patient.age` | `null` when DOB is missing **or after the visit date** | 16 of the 786 CKG visits have no usable age; 8 of them have a DOB later than the visit (UAT data error). |
| `patient.occupation` / `religion` | `{id, label}` | Stored as ids into `kk_kategori`; older rows hold the text itself (`id: null`). |
| `visit.insurances` | list `{id, name}` | A visit can have several. |
| `prescriptions[]` | `is_compound` + `items` | Single drugs from `kk_resep_obat`; compounds from `kk_racik` + `kk_racik_obat`. `signa = {times, amount, period, text}` raw. |
| `lab[]` | `{test, parent, result, unit, reference{type,min,max}, …}` | The lab master is a self-referencing tree; `parent` is reported as stored — match on the normalised `test` leaf. |

Soft deletes differ per table (`ket='DELETE'` on most, only `deleted` on `kk_resep_obat`); the model picks whichever
column exists. Free text is forced to valid UTF-8 (PHP 5.6's `json_encode` fails on one bad byte).

**UAT data findings for the converter:** 310 of 786 CKG visits have no usable NIK (D10), 21 have no gender, 16 no age;
only 75 have any screening row and 34 any physical-exam finding, so UAT cannot validate the small instruments.
538 active visits have `tanggal = '0000-00-00'` (none are CKG).

#### 5.2.2 As built: E5 `visits/changes` and E6 `patients/by-nik/{nik}`

**E5** — `GET /medisy_api/ckg/visits/changes?since=<ISO 8601>&ckg_only=true&page=1&limit=100` (limit ≤ 500). Returns
`{items:[{visit_id, patient_id, date, room, changed_at, deleted, is_ckg, ckg_basis}], page, limit, total, since, window_start, server_time}`,
ordered by `changed_at` then `visit_id`.

- `changed_at` is the **latest timestamp over the visit row and every child table E3 reads** (`updated`, `created`, `deleted`,
  `terakhir_ubah_rme`, `created_at`, `updated_at` — whichever each table has). `kk_kunjungan.updated` alone is not enough: a lab
  result or a screening row can change without touching the visit. Cancelled/deleted visits are included with `deleted: true`.
- **Window rule:** only visits dated within `CKG_CHANGES_WINDOW_DAYS` (default 90) **before `since`** are examined. That keeps the scan
  on the `kk_kunjungan.tanggal` index and reaches each child table through its `id_kunjungan` index (forced with `STRAIGHT_JOIN`, so the
  cost follows the window, not the table size). **A child row edited on a visit older than the window is not reported** — use E2 (by
  date) for a full re-read. Rows with no usable timestamp at all can never appear. `kk_racik_obat` (compound ingredients) has no
  timestamp, so a change there shows only if `kk_racik` moves.
- `since` accepts a date, a naive datetime (read as clinic time, `Asia/Jakarta`) or an offset/`Z` datetime. An unencoded `+07:00` in a
  query string arrives as a space; that is repaired. **Use `server_time` from the response as the next `since`** (minus a small overlap)
  instead of the caller's clock. Years before 2000 or after next year are rejected (422).
- Verified on the UAT copy: `since=2000` returns all 790 CKG visits (786 active + 4 cancelled/deleted, all flagged); edits to a new
  screening row, a prescription, the visit row, and a child soft-delete each surface exactly their own visit; cancelling a visit
  reports `deleted: true`; non-CKG visits appear only with `ckg_only=false`; paging covers every visit once; the throw-away test DB was
  restored and diffed against the pristine copy. `EXPLAIN`: range on `tanggal`, then `ref` into each child's index.

**E6** — `GET /medisy_api/ckg/patients/by-nik/{nik}` → `{patients:[{patient, ckg_years, total_visits, truncated, visits:[…]}], total_patients, truncated}`.
Matches `kk_pendaftaran.no_identitas = nik` **and** the D10 identity types only (a SIM number or an untyped number is not found → `404`).
Visits are newest first, up to 200 per registration, and **include deleted/cancelled visits with `status`** (that is the point: "why is
this patient missing?"). `ckg_years` = calendar years with an *active* CKG visit. At most **50 registrations** are returned (`total_patients`
reports the real number). The NIK is in the URL path, so it ends up in web-server access logs — filter them (§5.3 Privacy).
The lookup needed an index: `no_identitas` was only the 3rd column of two composite keys (full scan); `ckg_api.sql` adds one.

**Data finding that affects ckg-ai — shared and placeholder NIKs.** On the UAT copy, **534 registrations have the NIK-type number `00`** and 56
have `000`; another NIK is shared by 17. Among CKG visits that carry a NIK, **149 of 467 (32%)** have a number shared by more than one
registration. Under D10 ("no validation — the CKG website validates") these are all returned as NIKs. The risk is on the ckg-ai side:
its records are keyed by `(puskesmas, nik, filter_date, ruangan)`, so two different patients with NIK `00` on the same day in the same
room would **overwrite each other**, and NIK-based matching to ASIK would join unrelated people. Options considered (**decision D13: (b)**, implemented 2026-10-05): (a) API returns `nik: null` for numbers that are not exactly 16 digits (reverses "no validation"); (b) the API keeps
returning them but adds `nik_shared: true` so ckg-ai can skip or key by `patient_id`; (c) ckg-ai keys by `(patient_id, date)` instead.

**As built (D13).** `Ckg_model::sharedNumbers()` (one grouped query per page/batch on the `no_identitas` index) → `nik_shared` in E2, `patient.identity.shared` in E3/E4, `identity.shared` in E6. On the UAT copy: of 24 sixteen-digit NIKs with several registrations, 17 are different people (flagged) and 7 are duplicate registrations of one person (not flagged). ckg-ai: `medisy_adapter.extract_patients` skips flagged visits. Visits skipped this way are not in ckg-ai at all; if many real patients turn out to be affected, option (c) can follow.

### 5.3 Cross-cutting rules for every endpoint

- **Auth:** `Authorization: Bearer <token>` with a **dedicated token for ckg-ai** (new env var,
  `CKG_API_TOKEN`; Phase 2 also added `CKG_API_TOKEN_NEXT` for rotation) — do **not** reuse the global `MEDISY_API_TOKEN`. `401` on a missing/wrong token;
  constant-time compare (`hash_equals`); rotatable by changing the env var; HTTPS only; optional IP
  allow-list for the ckg-ai host. No per-clinic scoping (single tenant, D6).
- **Errors:** every non-2xx body is `{"detail": "<string>"}` (several messages joined with `"; "`) — the
  shape ckg-ai's own API and clients already use.
- **Privacy:** NIK + clinical data. Don't log request/response bodies; use a **read-only DB user**
  (ideally a replica).
- **Performance:** E2 needs no new index (the existing `kk_kunjungan.tanggal` index is used — see Phase 1 status); E5 needs `kk_kunjungan(updated)`; E3 must
  load children with `WHERE id_kunjungan IN (…)` **per table**, then assemble in PHP — never a query per
  visit. Verify with `EXPLAIN`; target a 50-visit batch in a few seconds.
- **Tests:** a script or test cases hitting each endpoint: missing token; wrong token; a visit id that
  does not exist (404); a visit matching neither half of the §5.4 rule (must not appear in E2 by default); a visit matching only the insurance half; a NIK-type patient with an empty number; a patient with a number but no identity type (must **not** be returned as a NIK, D10); cancelled
  visit; patient without NIK; empty screening; 50-id batch; 51-id batch (must 422).

### 5.4 The CKG rule — poli name OR PKG/CKG insurance

Implement **one** server-side function (e.g. `Ckg_model::is_ckg_visit($visit)`) and use it everywhere:
E1 `is_ckg`, E2 `is_ckg`, E3 `ckg` block. ckg-ai only reads the boolean and `basis`, so any later change
to the rule touches **Medisy only**.

A visit is a CKG visit when **either** half matches (and `ket NOT IN ('DELETE','CANCEL')`):

| Half | Rule | `ckg.basis` |
|---|---|---|
| Poli | `kk_poli.nama LIKE '%CKG%'` (via `kk_kunjungan.id_layanan`) | `poli_name` |
| Insurance | `kk_asuransi.nama LIKE` `%PKG%` / `%CKG%` / `%Pemeriksaan kesehatan gratis%` (via `kk_kunjungan_asuransi`) | `insurance_name` |
| Both | — | `both` |

Put the patterns in a **config list**, not literals, so a clinic that spells it differently needs no code
change. Things to be deliberate about:

1. **Not the same as the existing PKG report.** `Pkg_model::_get_pkg_data` also requires
   `jenis_kunjungan = 'ASURANSI'`; this rule does **not**, and its poli half is `LIKE '%CKG%'` only (the
   report also matches a poli named `PKG`). Write that into the function's comment and expect small count
   differences when you compare against that report.
2. **`LIKE '%CKG%'` is broad.** UAT's CKG poli is named `KLASTER 3 R DEWASA - CKG`; any other poli whose name
   contains "CKG" would also match. E1 returns every poli name so ckg-ai can show what matched.
3. **Insurance names need review per clinic.** UAT has insurances `PKG`, `PKG Contoh` and
   `PENGOBATAN GRATIS`. The last one is a different programme and is **not** matched (it contains neither
   `PKG`, `CKG` nor `Pemeriksaan kesehatan gratis`) — confirm the same on the production list.
4. **Per year.** `ckg.year` is the visit's calendar year; `ckg.records` lists the patient's CKG visits across
   years so the consumer can ignore other years (a 2025 CKG visit must not mark a 2026 visit).

**Measured on the UAT copy (`medisy_ckg`, 2026-10-05):** poli half 767 visits, insurance half 30, both 11 →
**786 distinct visits** (2024: 83, 2025: 410, 2026: 293).

---

## 6. Step-by-step migration

Each step ends with a **Verify** gate — don't start the next phase until it passes.
`CLAUDE.md` rules apply throughout (no commits/branches unless you say so; restart the Celery worker after
`backend/app/` changes; typecheck **both** frontends for anything in `frontend-shared/`).

### Phase 0 — Close the open decisions  *(no code)*

**Status (2026-10-05): done except the pilot and fixtures.** Worked against a local copy of the UAT dump
(`medisy_ckg`; MariaDB 10.1 source, loaded into MySQL 8 — one 19-column index on `kk_pendaftaran` had to be
dropped locally because MySQL caps indexes at 16 columns, so don't use that copy for `EXPLAIN`/index tuning).

1. ✅ **Poli / CKG rule.** No poli is named exactly `CKG`; the CKG poli is `KLASTER 3 R DEWASA - CKG` (id 1)
   and there is a separate poli `PKG` (id 34). Rule agreed: §5.4 / D9. **786 CKG visits** in UAT, mostly
   1–6 per day (peak 18 on 2026-09-02) — one batch call per day is plenty.
2. ⬜ **Pilot puskesmas and date range** — needs a Medisy clinic with ≥ 2 weeks of data **and** ASIK data for
   the same days. *Not decided.*
3. ⏸ **Anonymised fixtures** — *skipped for now.* An export-and-scrub script was drafted but not run (the
   session blocked moving patient rows into files). Build the fixtures later, by hand or after explicit
   approval; never commit `medisy_ckg.dump` (424 MB, untracked, real patient data, not gitignored).

**Findings that change the build** (all measured on UAT; re-check on production):

| Finding | Consequence |
|---|---|
| `kk_pendaftaran.jenis_kelamin`: `1` Laki-laki, `2` Perempuan (confirmed in PHP), but also `0`, NULL, `''`, legacy `L`/`P` — among the 767 poli-half visits, 23 are not 1/2 (8 × `0`, 11 × NULL, 4 × legacy `L`) | Normalise to `L`/`P`/`null` (legacy `L`/`P` map straight through); `null` sex ⇒ no ASIK forms. |
| `type_identitas` is an id into `kk_kategori` (`type='IDENTITAS'`), with legacy strings `NIK`/`KTP`/`-` | D10. |
| Of the 786 CKG visits: 476 NIK-type with a number, 10 NIK-type but empty, 71 untyped with a number, 225 with neither, 3 SIM/Passport/Pelajar | ~235 (30%) have no usable NIK and are skipped; the 71 untyped are skipped by D10 (open to revisit if production clinics leave the type blank). |
| NIK lengths vary (16 is correct; 5, 17, 18, 24 and NULL occur) | No validation here (D10) — the CKG website validates. |
| Screening tables: 45 `kk_skrining_*` + `kk_skilas`; populated: `puma` 1.7k, `tbc` 1.1k, `ppok` 216, `kesehatan_jiwa` 202, `skilas` 88; most others < 10 rows | UAT is too thin to validate coverage for the small instruments; Phase 5 needs production-like data. |
| Diagnoses link as `kk_pemeriksaan_diagnosa.id_kategori_penyakit → kk_kategori_penyakit.kode` (ICD-10) | Use this join for `diagnoses` / `chronic_conditions`. |
| `kk_ckg_log` exists but has 0 rows and nothing in the PHP references it | Ignore. |
| MariaDB **10.1** on the UAT server | No `JSON_*` functions — assemble bundles in PHP, as §5.3 already says. |

**Verify:** ✅ rule and daily volume confirmed; ⬜ pilot date range named; fixtures deferred.

### Phase 1 — Build the Medisy API  *(himed-app)*

**Status (2026-10-05, branch `feature/ckg-api`): E0–E6 all built and tested.**
Code: `modules/medisy_api/controllers/Ckg.php`, `models/Ckg_model.php` (E0–E2, the CKG rule, NIK rule), `models/Ckg_bundle_model.php` (E3/E4), `models/Ckg_sync_model.php` (E5/E6); `CKG_API_TOKEN` / `CKG_POLI_PATTERNS` /
`CKG_INSURANCE_PATTERNS` in `config/constants.php`; routes for E3–E6 in `config/routes.php`.

- **Runtime is PHP 5.6** (`Dockerfile`: `amd64/php:5.6-apache`) — no `??`, no scalar type hints. Tested on PHP 5.6.40 +
  **MariaDB 10.1.48** (a throw-away container loaded from the UAT dump), i.e. the same versions as production.
  MySQL 8 does **not** work as a local test DB for this app: PHP 5.6's client fails the handshake (`2054`).
- Auth: `Authorization: Bearer <CKG_API_TOKEN>`; empty token ⇒ everything is rejected; token in the query string is
  not accepted. Errors are `{"detail": …}`. (Not the existing `$this->response()` envelope, which is `{success, data}`.)
- E2 reconciles with independent SQL for **all 322 dates** that have CKG visits (786 = 786). It uses `LEFT JOIN
  kk_pendaftaran`: UAT visit 2637 points at a registration row that no longer exists, and must still be counted
  (it is returned with `nik: null`, so ckg-ai skips it as "missing NIK").
- **Indexes:** E2 needs none (`EXPLAIN`: the existing `kk_kunjungan.tanggal` index). E5 needs none either (window on `tanggal`, then each child's
  `id_kunjungan` index). E6 needs `kk_pendaftaran(no_identitas)` — in `ckg_api.sql`.
- **Schema file for other installs:** `db/2026/20261002-ckg-api-config/ckg_api.sql` — guarded and idempotent. It adds 6
  late columns (`kk_kunjungan.terakhir_ubah_rme`/`nilai_bmi`, `kk_pendaftaran.place_of_birth`, `kk_resep_obat.signa_desc`/
  `indikasi`, `kk_racik.indikasi`), recreates `kk_pemeriksaan_fisik` if absent, adds an `id_kunjungan` index to 8 small program/
  screening tables that lack one and a `no_identitas` index to `kk_pendaftaran` (E6) (skipped if the table is missing or already indexed), and ends with a read-only pre-flight
  that lists every missing table/column (183 checks). Tested on MariaDB 10.1 against the current schema, a simulated old
  install, and a re-run. **MariaDB 10.1 has no `ALTER TABLE IF EXISTS`** — the first draft used it and failed.
- Deploy: set `CKG_API_TOKEN` in the environment (the dev `docker-compose.yml` is gitignored, so add it there by hand).
  `db/2026/20261002-ckg-api-config/` is an empty, untracked directory that predates this work — not ours.

1. `Ckg` controller + `Ckg_model` in `modules/medisy_api/` (E0–E4 first; E5/E6 after).
2. Bearer-token auth (§5.3) as one helper used by all `ckg/*` actions.
3. E2 on top of `v_kunjungan`; `is_ckg_visit()` per §5.4.
4. E3 with set-based child queries: vitals, physical exam, diagnoses, procedures, prescriptions/racik, lab,
   programs, **screenings (`kk_skrining_*`, `kk_skilas`)**, history/allergies, notes.
5. Indexes (§5.3) as a dated SQL file under `db/2026/…`, like the existing migrations.
6. Confirm/fix the unauthenticated `medisy_api` controllers (§4.1) — not part of the migration, but you
   are exposing patient data from the same module.

**Verify:** `curl` each endpoint with a valid and an invalid token; a 50-visit batch is fast; `EXPLAIN` uses
the indexes; E2 returns only §5.4-matching visits by default (786 on the UAT copy).

### Phase 2 — Harden and document  *(himed-app)*

**Status (2026-10-05): done.** Reference: `docs/ckg-api.md`. Tests: `docs/ckg-api-tests/` (`smoke_test.py` + `README.md`).

1. **Hardening — `libraries/Ckg_guard.php`**, run before the token check, in this order: HTTPS (`CKG_API_REQUIRE_HTTPS`, default **on**) →
   IP allow-list (`CKG_API_ALLOWED_IPS`: exact IPs / IPv4 CIDR) → rate limit (`CKG_API_RATE_LIMIT`, 120/min/IP, file counters, fails open and
   says so) → token (constant-time; **≥ 32 chars**; `CKG_API_TOKEN` + `CKG_API_TOKEN_NEXT` for zero-downtime **rotation**; wrong tokens throttled by
   `CKG_API_AUTH_FAIL_LIMIT`, 10/min/IP, without blocking a valid token). `X-Forwarded-For/Proto` are believed **only** from `CKG_API_TRUSTED_PROXIES`
   (rightmost non-proxy address wins, so a forged left entry cannot win).
2. **Nothing internal reaches the client:** `db_debug` off, a method allow-list (`_remap`), and a JSON 500 for exceptions *and* PHP fatals.
   Getting the fatal case right needed two fixes found by testing: CodeIgniter's own shutdown handler `exit()`s on fatals and would stop ours, so the
   fatal error classes are masked from `error_reporting()` for this controller; and the handler is registered when the file loads, because
   `CI_Controller::__construct` (which autoloads the session/DB libraries) can itself die when the DB is down. CodeIgniter also has no status text
   for **429** and turned it into a 500 until the text was supplied.
3. **No body logging:** nothing logs bodies, tokens or NIKs; security events are single `CKG API: denied <status> (<reason>) from <ip>` lines.
   `log_threshold` must stay `0` (a higher value makes CI log failed queries with their bound values).
4. **E6 POST form** `POST /patients/lookup {"nik":…}`: verified on **real Apache** that the GET form writes the NIK into the access log and the POST form does not.
5. **Endpoint reference** and operations guide (configuration table, deployment checklist, token-rotation procedure, logging/privacy, troubleshooting): `docs/ckg-api.md`.
6. **§5.3 test list** — all nine cases are covered by `smoke_test.py` (97 checks; runs against any environment, read-only, paced to stay under the
   default rate limit; a broken CKG rule or a wrong token makes it **fail**). Verified on the PHP built-in server **and Apache + mod_php**
   (the `Authorization` header reaches PHP through `.htaccess`). A further 67 access-control checks were run with per-case server settings.

**Verify:** someone else can call the API from the docs alone → `docs/ckg-api.md` + `smoke_test.py`. ✅

### Phase 3a — ckg-ai foundations  *(additive, no behaviour change)*

**Status (2026-10-05): done — uncommitted in the working tree of `ckg-ai` (no branch, no commit, per its `CLAUDE.md` §14.3).**

**Direction change:** no `source_system` migration (see D3/D7), so the original item 1 is dropped. What was built:

1. **`backend/app/integrations/medisy_client.py`** (sync `httpx`, called from Celery tasks and sync handlers) — `ping()` (E0),
   `rooms()` (E1), `list_visits(day, ckg_only)` (E2, all pages), `get_bundles(ids)` (E3: de-duplicated, chunked to the server's 50-id limit,
   `concurrency` (default 3) requests in flight, **request order preserved**, `missing` ids reported). HTTPS only; **redirects are not followed**
   (they would carry the bearer token elsewhere); retries only transient failures of reads (network errors/timeouts, `429` honouring `Retry-After`
   capped at 30 s, `502/503/504`) with jittered exponential backoff — never `401/403/404/422/500`; the token and request bodies never appear in an
   exception message or log line; the host is re-validated (same shape as the puskesmas form: dotted labels, alphabetic TLD, so `localhost`/IP literals
   are impossible). Typed errors: `MedisyAuthError`, `MedisyNotFoundError`, `MedisyRateLimitedError`, `MedisyRequestError`, `MedisyServerError`,
   `MedisyUnavailableError`.
2. **Credential**: `PUT /puskesmas/{id}/credentials/epus` now also accepts `{"token": "<≥ 32 chars, no whitespace>"}` (`MedisyCredIn`, `extra="forbid"`) —
   stored Fernet-encrypted in `epus_cred`; `…/decrypt` returns the stored shape; the old `{email, password}` is still accepted until the EPUS code is
   removed; the ASIK slot refuses a token. (The plan said `PUT /puskesmas/{id}` — the real routes are `PATCH /puskesmas/{id}` and the credentials `PUT`.)
3. **`POST /puskesmas/{id}/test-connection`** — calls Medisy's `/ping` with the stored URL + token. Always HTTP 200 once authorised: a failure is
   `{"ok": false, "error": "…"}` (never the token), like `POST /llm-configs/test`; admin or a user of that puskesmas; rate-limited
   (10/min/principal, `enforce_medisy_test_rate_limit`); loads only `id, epus_url, epus_cred` (`CLAUDE.md` §5).

**Verified:** 63 client tests + 28 route tests (all offline: `httpx.MockTransport`, mocked DB, real Fernet); the full backend suite is **526 passed, 14 skipped,
4 failed — the same 4 that fail without these changes** (3 × `test_llm_test_endpoint`, `test_security_hardening::…allowlist`, whose expected set lacks the
`bayi-reports` / `dm-reports` routes); ruff clean on every touched file; each security property was proven by *breaking it and watching a test fail*
(redirects, token in an error, uncapped `Retry-After`, retrying 500, order, de-duplication, missing authorization / rate limit / `load_only`).
**Against the real himed-app API** (local PHP 5.6 + MariaDB 10.1): `ping`, `rooms`, `list_visits` (18 visits on 2026-09-02, as expected), and `get_bundles` for
130 ids = 3 parallel chunks → 130 bundles in 0.25 s, order preserved, an unknown id reported in `missing`, a wrong token → `MedisyAuthError` without the token.
No Celery worker was running and no task code changed, so there was nothing to restart.

**Verify:** `pytest tests/test_medisy_client.py tests/test_puskesmas_medisy.py` green; client works against the live API. ✅

### Phase 3b — Re-point the code at the Medisy bundle  *(was: make the code source-neutral)*

> **Direction change:** no source interface and no zero-behaviour-change EPUS refactor — the whole app moves to Medisy, so the consumers listed in §2.4
> are **re-pointed directly** at the Medisy bundle in Phase 4. What survives from the old Phase 3b is its discipline: **clinical rules must not change
> silently**, and the **chatbot lock** must be re-blessed.

1. **Characterise the clinical rules before touching a consumer.** Build **anonymised Medisy bundle fixtures** (one per ASIK form family and registry) and pin the
   *outputs* the dashboards depend on — chronic flags, td1 / riwayat / obat / identitas / birth-date, the registry scans, the dashboard counts — so that
   moving a consumer from EPUS paths to Medisy paths can only change *where* it reads, not *what it concludes*. (There is no converter test in `backend/tests/` today.)
2. Re-point consumers one at a time (§2.4 list), running the pinned outputs after each.
3. **Chatbot lock:** five of the touched files are pinned (`hipertensi_registry_scan.py`, `dm_registry_scan.py`, `lipid_registry_scan.py`,
   `obesitas_registry_scan.py`, `dashboard_scan.py`). Re-read the affected packs, then `cd backend && python scripts/bless_chatbot_knowledge.py` and
   `pytest tests/test_chatbot_knowledge.py` — **watch it pass before you finish** (`CLAUDE.md` §10 records a master that shipped red because this was skipped).

**Verify:** pinned clinical outputs unchanged on the fixtures; `pytest` green incl. the chatbot test.

### Phase 3c — Medisy fetch path  *(this repo)*

**Status (2026-10-05): done — and the EPUS scraper is removed (uncommitted in `ckg-ai`; no branch, no commit, per its `CLAUDE.md` §14.3).**

Built (additive, then the removal):

1. **`services/medisy_adapter.py`** — `fetch_day_bundles(client, day, niks, should_cancel, on_log)` (list the day's CKG visits → filter by NIK on the cheap
   list → bundles in chunks of 50, **ascending visit id**), `extract_patients(bundles, fetched_at)` → `(nik, nama, blob, date)` rows (a visit without a NIK is
   skipped with the usual `missing NIK` reason), `with_meta` (the stored blob = the bundle **unchanged** + `_meta {source, fetched_at}`, D8), `is_medisy_blob`.
2. **`tasks/medisy_scrape.py::run_medisy_scrape`** — the whole job in one function, **no subprocess / Playwright / CAPTCHA**. Reuses the job status helpers, the
   Redis log ring + SSE channel and the Redis cancel flag. Handles single-day, multi-day (`date_filters`), `target_niks` and per-NIK jobs; upserts and commits **per
   day**; a cancel (checked before every request) drops a half-read day and never saves it, so only whole days land and a re-run is idempotent; failures become a job
   error with a safe message (no token, no NIK, no old EPUS password); anything unexpected rolls back and propagates to `run_scrape`'s handler.
3. **`tasks/scrape.py::run_scrape`** — for `ScrapeKind.EPUS` (the kind keeps its name = "clinic-record source") it now calls `run_medisy_scrape` right after the job
   is marked running. The ASIK branches are untouched (verified in the diff).
4. **Blob-shape helpers (additive):** `birth_date_from_medisy` (`patient.date_of_birth`; `birth_date_for_patient` also tries it), `_extract_tandai_ckg` reads
   `ckg.is_ckg` (legacy `sudah_ckg` still read), `_extract_epus_ruangan` reads `visit.room.name` (capped at 64 chars). All three keep reading legacy EPUS blobs.

**Removed (EPUS scraper only):** `scrapers/epus/` (13 files, 5,411 lines — all tracked, recoverable from git), the EPUS branches of `run_scrape` / `_build_config` /
`_extract_patients` (progressive per-date upsert, `--dates`/`--niks`/`--patient-workers` argument building, `EPUS_PATIENT_WORKERS`), `_iso_to_ddmmyyyy`, the
`epus/` requirement in `_resolve_scrapers_root`, and the obsolete one-time script `scripts/backfill_ckg.py` (it logged into the EPUS portal through the deleted helpers).
`scrapers/README.md` / `SCRAPE.md` updated. **ASIK is untouched** (`scrapers/asik*`, `tasks/sync.py`, `tasks/create_patient.py`).

**Not removed, on purpose** — `services/epus_to_asik.py` and its ~15 consumers (`sync.py` and `routes/patients.py` import it at module level, so deleting it now would stop
the API from starting) stay until Phase 4 provides `medisy_to_asik`; the existing EPUS patient rows stay until the Phase 7 replacement. **Open decision — the loop-agent**:
it is wired deeply (own tables + migrations 0036–0040, `routes/loop_runs.py`, a nightly Celery job, a compose worker, `github_pr`, an LLM-config role, 14 frontend files), so it
is a separate removal. Its nightly run is **off by default** (`loop_config.nightly_enabled=False`); leave it off — a manual run would aim the EPUS-fixing agent at a Medisy host.

**Known behaviour:** two visits of one patient in one poli on one day collapse into one row (row key `(puskesmas, nik, filter_date, ruangan)`); the **latest visit wins**.
On the UAT copy, 2026-09-02 has 18 CKG visits → 8 rows (8 had no NIK, 2 were same-patient duplicates).

**Verified:** 26 new tests (adapter, helpers, the runner: success, multi-day, per-NIK, `target_niks`, no-NIK notes, missing token/URL, bad input, Medisy error, cancel, DB error);
full backend suite **552 passed, 14 skipped, 4 failed — the same 4 as before any change**; ruff clean on every touched file. **End to end** against a scratch Postgres
(created and dropped for the test) migrated to head and the real himed API: job SUCCESS, rows with `filter_date`, `ruangan` = the CKG poli, `match_status` `epus_only`,
`epus_tandai_ckg` true, `birth_date` filled (7/8), the stored blob is the bundle + `_meta`, the job log holds no NIK/name, re-run idempotent (0 inserted), multi-day and per-NIK
jobs work, a cancel saves nothing, a wrong token and an old EPUS password in the slot both fail with safe messages. No Celery worker was running, so none needed a restart.


1. `medisy_adapter.fetch_day(puskesmas, date)` → list of native bundles (with `_meta`, D8); a Medisy
   `_extract_patients` yielding `(nik, nama, blob, date)` (skip missing NIK, same reason string).
2. `tasks/scrape.py::run_scrape`: for kind `EPUS` (the "clinic-EMR step"), **call the Medisy adapter instead of the Playwright subprocess**; reuse upsert, job status, progress log (Redis ring + SSE) and
   the Redis cancel flag (per `CLAUDE.md` §8.2). *(Superseded: the EPUS scraper was removed in the same change — see the status above.)*
3. Medisy accessors (birth date, `is_ckg`, identity, …) as plain functions, returning "unknown" (`None`/`{}`) until Phase 4 fills them in.
4. Pause the loop-agent nightly selection (it exists to repair the EPUS scraper). *(Already off by default — see the open decision above.)*

**Verify:** a manual scrape of one pilot date writes `patients` rows from Medisy bundles,
`birth_date` and `epus_tandai_ckg` (from `ckg.is_ckg`) populated; cancel works.

### Phase 4 — `medisy_to_asik` and the Medisy accessors  *(your mapping)*

Use the **`ckg-form-research` skill** (`.claude/skills/ckg-form-research/`; start at `RESEARCH_STATUS.md`)
— it is the canonical tooling for adding a source (`CLAUDE.md` §9: do **not** hand-roll audits). Read its
`references/converter-pattern.md` and `references/asik-target.md` first.

Work **consumer-first**, in this order:

1. **Identity + age + sex** (without them the converter emits nothing) and the `identitas_pasien` form.
2. **Accessors the registries need**: `chronic_flags`, `td1`, `riwayat`, `drugs`, `birth_date`, `is_ckg`
   — the dashboards depend on these before any ASIK form does.
3. **Core adult forms**: tekanan darah, gula darah, gizi, riwayat HT/DM.
4. Lab, prescriptions, programs (KIA/bayi, PTM, TB, HIV, KB, imunisasi).
5. The **screening battery** — the largest and most valuable block.
6. `MEDISY_BREADCRUMBS` for every field you emit (drives the merge backfill and the coverage audit).
7. Tooling tweaks for `--source medisy`: `_regions.source_column()` (D7), and replace
   `audit_source_completeness.py` (EPUS-only) with the Phase 2 API contract tests.

**Verify:** `medisy_to_asik(blob)` returns forms for every fixture (no `{}` for an adult with sex + age);
`audit_coverage.py --source medisy` shows **0 form/field name drift** against live ASIK labels;
`verify_converter.py --source medisy` reports zero hallucination (every value traces to the source).

**Status (2026-10-05) — converter + dispatch + tooling DONE; accessors + gates PARTIAL.**
- Done: `services/medisy_to_asik.py` (+ `asik_form_labels.py`, `MEDISY_TO_ASIK_RULES.md`, 51 tests), `services/clinic_source.py`
  (shape-aware dispatch; `merge`, `sync`, `create_patient`, patient routes re-pointed), `--source medisy` support in the skill
  scripts (`_regions.py`, `audit_uncovered.py`, `verify_converter.py`).
- Measured on a scratch Postgres filled by `run_medisy_scrape` from the real local API (53 patients) + 786 real bundles offline:
  `audit_coverage.py --source medisy` → **0 name/label drift**; converter ran with **0 exceptions** and **0 emitted fields without a
  breadcrumb**; `audit_uncovered.py` → no uncovered Medisy field has an ASIK target label (the one near-miss, the `gizi` screening,
  is a different instrument — open question Q5 in `MEDISY_TO_ASIK_RULES.md`).
- **Not run (cannot, yet):** `verify_converter.py --source medisy` (needs patients with both a Medisy and an ASIK blob; also LLM
  keys) and `run_full_pass.py` (no GATE line exists for Medisy). Both belong to Phase 5.
- Done (2026-10-05): registry/dashboard accessors — `services/medisy_accessors.py`; hipertensi/dm/lipid/obesitas/bayi scans, the
  GD Puasa and Hipertensi report extractors branch on `is_medisy_blob` (EPUS path untouched until the last EPUS row is gone).
  Chatbot packs (`registri-bayi-kuning`, `registri-diabetes-melitus`, `registri-hipertensi`) updated, lock re-blessed, tests green.
  The dashboard "tertatalaksana" flags are PROXIES (Q6) and the bayi registry has caveats (Q7), both in `MEDISY_TO_ASIK_RULES.md` §5.
- Still open in this phase: `coverage_hunt.py` / `build_mapping.py` / the mapping page still import `EPUS_BREADCRUMBS`
  (no Medisy column), and the one-off `backend/scripts/backfill_*` helpers still parse the EPUS blob.
- Clinical sign-off questions: `backend/app/services/MEDISY_TO_ASIK_RULES.md` §5.

### Phase 5 — Quality gate

1. Run the skill's full pass for `--source medisy` and **echo the `GATE:` line verbatim** (`SKILL.md`
   rule 8). A step that did not run is `NOT_RUN`, never "probably fine".
2. Take patients that exist in **both** Medisy and ASIK for the same visit, merge them, and read the
   **conflict list**. Expect conflicts to be real data drift, not mapping errors.
3. Check population **per klaster**, not just adults (`SKILL.md` rule 5): a tab/field can exist and be
   empty for children.

**Verify:** per-form coverage and conflict rates acceptable to the clinic; every miss is either fixed or
recorded as "Medisy does not capture this".

### Phase 6 — Pilot

1. Pick the pilot puskesmas (the Medisy clinic) — there is no per-puskesmas switch; use a **scratch/test puskesmas or a date range that Phase 7 will replace anyway**.
2. Date-range backfill with `merge_mode=normal`, `sync_mode=off` — **no ASIK writes yet**.
3. Compare the merged patients and one registry (e.g. hipertensi) against Medisy's own numbers for the same
   period.
4. Enable `sync_mode=normal` for **one date**, inspect `asik_default_fills`
   (`ASIK_DEFAULT_FILLS.md`) and the result in ASIK, then widen.

**Verify:** registry counts reconcile with Medisy within an explained tolerance; a synced patient shows the
expected answers in ASIK; no unexplained `validation_error` in `sync_jobs`.

### Phase 7 — Cut-over: replace the EPUS data  *(was: cut-over and rollback — there is no rollback)*

> **Direction change:** nothing is flipped per puskesmas and there is **no way back to EPUS**. The cut-over replaces the data, then the code goes.

1. **Back-fill from Medisy** for every puskesmas over the dates its EPUS rows cover (`merge_mode=normal`, `sync_mode=off`; keep `lookback_days=3`, or E5 `changes`).
2. **Reconcile before anything is deleted** (read-only tool: `python -m scripts.reconcile_epus_medisy --puskesmas <UUID> --from … --to …` prints per-day counts of stored ePuskesmas rows vs Medisy visits, shared and no-NIK ones separated; `--show-niks` lists the differences): per puskesmas and date, compare the EPUS rows with the Medisy rows (counts, NIK sets, `epus_only` / `matched`
   counts). Every difference must be explained (a visit that exists only in the old system, a NIK-less visit, a placeholder NIK) or accepted by the owner.
3. **Delete the EPUS rows — a script the owner runs, never the assistant** (irreversible; patient data; see `CLAUDE.md` §13/§14). Take a backup first,
   and do it puskesmas by puskesmas.
4. Only now **remove the EPUS code** (Phase 8). Doing it earlier would leave the live app unable to scrape, merge or sync.

**Verify:** the next scheduled cron run completes every step; match / merge counts for the following day are within the clinic's normal range.

### Phase 8 — Clean-up and docs

1. **UI:** show the source name instead of hard-coded "ePus"; Medisy credential form
   (`frontend-internal`); shared labels once in `frontend-shared/`. Typecheck **both** apps and state
   honestly whether you looked at it in a browser (`CLAUDE.md` §12.1).
2. **Chatbot packs:** update every claim that names EPUS, re-bless, run
   `pytest tests/test_chatbot_knowledge.py`.
3. **Docs:** update `ASIK_DEFAULT_FILLS.md` (§1 data sources), `RESEARCH_STATUS.md` (new source row), and
   `CLAUDE.md` where it says "ePuskesmas".
4. **Remove `epus_to_asik.py` and the remaining EPUS-only code paths — as the LAST step** *(the loop-agent is NOT removed: it is kept and re-pointed at Medisy, decision 2026-10-05)* *(the EPUS scraper `scrapers/epus/` and its `run_scrape` branches were already removed in Phase 3c)* (after Phase 7: they must exist until the Medisy fetch path, the converter and the data replacement are live). Direction change: nothing else is using them. Keep the column / enum *names* (`scraped_epus_data`, `epus_only`, `CronStep.EPUS`) — renaming them stays a separate, deliberate PR.
5. Rename `scraped_epus_data` / `epus_only` **only** as a separate, deliberate PR.

---

## 7. ckg-ai change checklist

- [x] ~~`source_system` migration~~ — **dropped** (direction change: no flag, no tag)
- [x] `backend/app/schemas/puskesmas.py` (`MedisyCredIn`, `MedisyCredOut`, `MedisyConnectionTestOut`), `crud/puskesmas.py`, `api/routes/puskesmas.py` (token credential + `POST /puskesmas/{id}/test-connection`), `core/rate_limit.py`
- [x] `backend/app/integrations/medisy_client.py` (new) + `tests/test_medisy_client.py`, `tests/test_puskesmas_medisy.py`
- [x] `backend/app/services/medisy_to_asik.py` (new — your mapping, with `MEDISY_BREADCRUMBS`; rules in `MEDISY_TO_ASIK_RULES.md`)
- [x] `backend/app/tasks/scrape.py` (Medisy branch; EPUS branches removed), `services/medisy_adapter.py`, `tasks/medisy_scrape.py`, `crud/patient.py` + `services/birthdate.py` (Medisy-aware helpers) + `tests/test_medisy_scrape.py`
- [x] `tasks/merge.py`, `tasks/sync.py`, `tasks/create_patient.py`, `api/routes/patients.py` (via `services/clinic_source.py`)
- [x] Registry scans (`hipertensi`, `dm`, `lipid`, `obesitas`, `bayi`), GD Puasa / Hipertensi report extractors (`services/medisy_accessors.py`), `birthdate.py`, `coverage_hunt.py`, `data/build_mapping.py` (`--refresh`)
- [x] `scrapers/epus/` and `scripts/backfill_ckg.py` — **removed** (Phase 3c)
- [ ] `services/epus_to_asik.py` and the EPUS branches — **remove, as the last step** (Phase 8, after the data replacement). **The loop-agent is KEPT and re-pointed at Medisy** (decision 2026-10-05): `loop-agent/PROMPT.md`, `AGENTS.md`, `run.sh`, `reviewer.py`, `coverage_hunt.py` (hunts `MEDISY_BREADCRUMBS`), ledger entries tagged `"source": "epus"`; `screenshot.py` removed
- [x] `backend/tests/`: `test_medisy_client.py`, `test_medisy_to_asik.py`, `test_medisy_accessors.py`, `test_medisy_scrape.py`, `test_clinic_source.py` (no fixtures export: decision D12)
- [x] `.claude/skills/ckg-form-research/` tweaks (`source_column`, `_url_of`, `source_age`, `audit_uncovered`, `verify_converter`); the EPUS-only completeness audit is replaced by the API smoke test (`docs/ckg-api-tests/`)
- [x] `frontend-internal` Medisy token dialog + connection test + labels; `frontend-shared` / `frontend-dashboard` labels (typechecked; **not looked at in a browser**)
- [x] `chatbot/knowledge/*.md` + `chatbot/knowledge.lock.json` (re-blessed 2026-10-05; re-bless again after Phase 8 step 4)
- [ ] Docs: this file ✅, `RESEARCH_STATUS.md` ✅, `CLAUDE.md` ✅, `ASIK_DEFAULT_FILLS.md` (§1 data sources — not touched: it has uncommitted edits of its own)

**Not** on the list: `scrapers/asik_sync/`, `tasks/cron.py`, `models/cron_config.py` (the cron step keeps its name).

---

## 8. Traps

- **Converter naming is the #1 failure** (`converter-pattern.md`): form and field names must equal live
  ASIK **byte-for-byte** (parens, slashes, `=> N tahun`). Settle them against a fresh live dump, never an old sheet.
- **Conditional reveals:** a new parent→child ASIK question pair needs a rule in `_CONDITIONAL_REVEALS`
  (`tasks/merge.py`), or the merge keeps orphan children.
- **Self-report vs clinical flags:** parent radios mirror the *self-report* field only; the clinical union
  gates forms. Mixing them creates fake conflicts.
- **Don't recompute what the merge owns** (presence, source-wins value, status).
- **Unanswered = `null`.** A phantom default (the first radio option) is the exact bug the ASIK scraper had
  to fix (2026-06-16); the merge treats any value as real data.
- **Age is computed at the visit date**, not today; sex must normalise to `Perempuan`/`Laki-laki` or no
  forms are emitted.
- **NIK:** a missing/blank NIK drops the patient. Decided (D10): only `type_identitas` `1`/`KTP`/`NIK` with a
  non-empty number counts; an untyped number is skipped; no format validation (the CKG website validates).
- **Lab names** are matched on the normalised leaf name, exactly — keep Medisy's names stable or keep an
  alias table.
- **CKG year:** a CKG record from another calendar year must not mark this visit (§5.4).
- **Blob versions:** a blob stored at `api_version=1` must still convert after you ship version 2 (D8).
- **Mixed history (transition only):** until Phase 7 replaces the EPUS rows, `scraped_epus_data` holds both kinds of blob. There is no tag (direction change); a Medisy blob is the one with `api_version` / `_meta.source` (D8). After Phase 7 only Medisy blobs exist.
- **Refactor discipline:** change the extractors' *location*, not their *logic*, in Phase 3b — a
  clinical-rule change hidden inside a refactor is how dashboards drift unnoticed.

---

## 9. Risks and open questions

| Risk / question | Mitigation |
|---|---|
| `LIKE '%CKG%'` could match an unrelated poli, and the rule differs from the existing PKG report (§5.4) | E1 lists all poli names; review the poli and insurance lists on production before go-live; expect small count differences vs the PKG report. |
| Phase 3b touches live clinical dashboards | Characterisation snapshots before any edit; one consumer at a time; compare dashboard numbers for an existing puskesmas. |
| Pinned chatbot sources | Re-bless in the same change; run `test_chatbot_knowledge.py` and watch it pass. |
| Medisy may not capture every CKG instrument ASIK asks for | Phase 5 audit; missing fields stay `null`; the sync's default-fill policy fills only **required** gaps and logs them (`ASIK_DEFAULT_FILLS.md`). Agree acceptable gaps with the clinic. |
| `kk_kunjungan.updated` may not move when a child row (lab, screening) changes | Add child `updated` columns or a trigger/outbox for E5; until then rely on `lookback_days`. |
| Same real-world NIK recorded differently in Medisy vs ASIK | Existing match is by NIK (± `MATCH_WINDOW_DAYS`); review `asik_only` / `epus_only` counts in the pilot. |
| Medisy's existing API uses one global secret, and some controllers have no check at all | A dedicated ckg-ai token (D4) **before** any production traffic; fix the unchecked controllers (§4.1). |
| Patient data crossing systems (NIK + clinical) | HTTPS, allow-list, no body logging, read-only DB role; confirm data-protection obligations with the clinic. |
| Deleting the EPUS rows loses history Medisy does not have | Reconcile per puskesmas and date **before** deleting (Phase 7 step 2); back up first; the owner runs the script. |
| `epus_only` now means "source-only" for Medisy rows too (D7) | Document it; rename later as a separate PR if it confuses people. |
| **(verify)** items above | Confirm each against real rows in Phase 0/1. |

---

## 10. Appendix — screening instrument ↔ Medisy table (candidates, **verify**)

ckg-ai's `skrining_klaster` keys (from `EPUS_BREADCRUMBS`) and the Medisy table that looks like the
source. Matched **by name only**.

| `skrining_klaster` key | Medisy candidate |
|---|---|
| `hipertensi` | `kk_skrining_hipertensi` |
| `diabetes_melitus` | `kk_skrining_diabetes_melitus` |
| `puma` | `kk_skrining_puma` |
| `skilas` | `kk_skilas` |
| `adl` | `kk_skrining_activity_living` |
| `skrining_phq_4` | `kk_skrining_kesehatan_jiwa` |
| `sppb` | `kk_skrining_short_physical_performance` |
| `mini_cog` | `kk_skrining_pemeriksaan_cog` |
| `skriningkankerparu` | `kk_skrining_kanker_paru` |
| `skrining_resiko_kanker_serviks` | `kk_skrining_kanker_serviks` |
| `payudara` | `kk_skrining_risiko_kanker_payudara` |
| `kolorektal` | `kk_skrining_kolorektal` |
| `thalasemia` | `kk_skrining_thalasemia` |
| `pengkajian_nutrisi` | `kk_skrining_pengkajian_nutrisi` |
| `gejala_tbc` | `kk_skrining_tbc` |
| `resiko_penyakit_jantung` | `kk_skrining_risiko_jantung` |
| `skrining_imunisasi_dewasa` | `kk_skrining_imunisasi_tetanus_wus` |
| `faktor_risiko`, `fungsi_ginjal`, `penglihatan`, `skrining_indra_pendengaran`, `skrining_sdidtk` | no obvious table — check `kk_questionnaire_ptm*`, `kk_skrining_risiko_penyakit`, or build the capture in Medisy |

## 11. Appendix — EPUS scraper calls this replaces

| EPUS (scraper) | Medisy API |
|---|---|
| `POST /login` | E0 `ping` (token) |
| `GET /pelayanan?…` DataTables, 100/page | E2 `visits` |
| `GET /pelayanan/show/{id}` | E3/E4 `patient`, `chronic_conditions`, `history` |
| `GET /anamnesa/create/{id}` + ~33 module tabs | E3/E4 `anamnesis`, `physical_exam`, `diagnoses`, `prescriptions`, `lab`, `programs`, … |
| `POST /klaster_siklushidup/{id}/getlist` + `/edit` detail | E3/E4 `screenings` |
| `POST /pelayanan/getdatapkg` | E3/E4 `ckg` |
| CPPT DataTables XHR | E3/E4 `notes` |
| (none — re-scraped the last N days) | E5 `changes` |


## 12. Findings from the Pelabuhanratu production copy (2026-10-07)

Local copy of the production DB (`medisy_pelabuhanratu`, 32,552 registrations, 104,594 visits) served by a second API instance; the dev ckg-ai database holds the scraped rows. **Local only, never committed.**

- **The workflow this repo serves:** staff register the CKG visit once in Medisy ("POLI CKG" room or PKG insurance) and ckg-ai delivers it to ASIK (no double input). Same-day check on 2025-07-07: 23 of 23 ASIK people had a same-day POLI CKG visit. ASIK-only days (e.g. 2026-09-15: 160 people, 4 with a same-day Medisy visit) are people entered straight into ASIK, i.e. the double input; Medisy "POLI CKG" visits with nothing in ASIK (2026-02-03: 49) are the backlog to send. The CKG rule is therefore right as is.
- **ASIK changed (scrapers/asik):** the patient list is now `POST /api/pkg/ssi/list-kunjungan-umum` with an encoded `{"_d": …}` request and response that the site's page decodes. The scraper now reads what the page decodes (`helpers/browser.py` observer, commit cc5b555). `detail-screening` is unchanged. **Still broken or unverified:** the per-patient form pages (`form.kemkes.go.id` answered 404 for a year-old record; current-year not tested), `asik_sync` (its NIK-search gate fails closed when it cannot parse the response, so it will skip, not write), `asik_patient`, `asik_sekolah`.
- **ASIK sessions last well under an hour** (CAPTCHA at login). Jobs need a vision-LLM CAPTCHA config (admin app, LLM) or a person re-running `scripts/seed_asik_session.py`.
- **What a send would contain (55 Medisy-only CKG patients, dry run):** 3-5 forms and 6-10 answers per patient (vitals, glucose, nutrition, marital status; kidney form carries only the derived age). About 80% of Medisy's own diabetes/hypertension/obesity screening rows are bulk-ticked ("all Tidak") and ignored by rule R-UNIFORM.
- **Medisy rows are ingested for every visit of the day** (D14), not only CKG ones.
