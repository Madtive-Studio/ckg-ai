# CKG-AI — Repo Guide + ASIK Sync Default Fills

This file has two parts:

1. **Part 1 — How the repo fits together** (read this first if you are adapting the repo).
2. **Part 2 — ASIK sync default fills** (the original design note for one feature: what the
   sync robot does when ASIK requires a question we have no data for).

The filename is kept because code comments point at it
(`backend/app/models/patient.py`, `backend/app/services/asik_defaults.py`).

> **Update 2026-10-14 — Medisy records:** the default fills described in Part 2 no longer apply to records whose clinic source is Medisy
> (`clinical_defaults=false`): a required measurement or clinical answer with no data stays blank instead of receiving an invented value;
> only a free-text `-` placeholder is still filled. EPUS-lineage and ASIK-only records keep the behaviour below. See
> `backend/app/services/MEDISY_TO_ASIK_RULES.md` §5 item 11.

> Everything here was derived from the code. Where the code and this file disagree,
> **the code wins** — see §1.11 for the parts that were not read.

---

# Part 1 — How the repo fits together

## 1.1 What the system does

Indonesian puskesmas (community health centres) record the same patient visit in two
government systems:

- **ePuskesmas ("EPUS")** — the clinic's own record system.
- **ASIK** — the national CKG (Cek Kesehatan Gratis) screening portal.

CKG-AI **scrapes both, matches patients, merges the two records into one, can push the merged
result back into ASIK, and reports on it** (hipertensi, diabetes, lipid, obesitas, bayi, GDP,
school screening dashboards).

```
  ┌──────────┐  scrape   ┌───────────┐
  │   EPUS   │ ────────► │           │            ┌─────────┐   sync (optional)   ┌──────┐
  └──────────┘           │ patients  │  merge     │ merged_ │ ─────────────────►  │ ASIK │
  ┌──────────┐  scrape   │ (Postgres,│ ─────────► │  data   │   Part 2 of this    └──────┘
  │   ASIK   │ ────────► │ encrypted)│  EPUS→ASIK │         │       file
  └──────────┘           └───────────┘  + LLM     └────┬────┘
                                                        │
                                                        ▼
                                  report dashboards (hipertensi · DM · lipid · obesitas · bayi · GDP)
```

Scheduling (cron + backfill) strings these steps together per puskesmas per date.

## 1.2 Top-level layout

| Path | What lives there |
|---|---|
| `backend/` | FastAPI API + Celery tasks + SQLAlchemy models + Alembic migrations (Python ≥ 3.12) |
| `scrapers/` | Playwright scrapers, run as **subprocesses** by Celery: `epus/`, `asik/`, `asik_patient/`, `asik_sekolah/` (school CKG), `asik_sync/` (push to ASIK: `sync.py`, `register.py`) |
| `frontend-internal/` | Admin Next.js app (jobs, cron, LLM config, users, puskesmas, loop runs…) |
| `frontend-dashboard/` | Client-facing Next.js app (reports, patient lists) |
| `frontend-shared/` | UI/logic both frontends show — **single source**, copied into each app's gitignored `_shared/` by `sync.mjs` |
| `chatbot/` | Knowledge packs for the explainer chatbot in the client dashboard (Indonesian markdown + a hash lock) |
| `loop-agent/` | Self-maintaining agent that checks/fixes the EPUS scraper + converter in a throwaway container and opens a PR |
| `.claude/skills/` | `ckg-form-research` (map a data source → ASIK form) and `ckg-deploy` (prod deploy procedure) |
| `CLAUDE.md` | The binding rules for contributors/agents (query discipline, soft-delete, frontend conventions, destructive-command rules) |
| `MERGE_RESILIENCE_AND_LLM_CONFIG_PLAN.md` | Plan doc for merge resilience / LLM config |

## 1.3 Runtime topology (`docker-compose.yml`)

| Service | Role |
|---|---|
| `postgres` (16) | The only durable store. Data volume `ckg_pg_data` |
| `redis` (7, AOF) | Celery broker + result backend, **plus** job log ring buffers, SSE pub/sub, and cancel flags (`<resource>:job:<id>:cancel`) |
| `backend` | Runs `alembic upgrade head`, then `uvicorn app.main:app` (4 workers) on `127.0.0.1:8000` |
| `celery_worker` | Default queue, concurrency 4. Runs scrape / merge / sync / cron / report tasks. `init: true` (tini) reaps orphaned Chromium zombies; `shm_size: 2gb` for Chromium |
| `celery_worker_loop` | **Only** the `loop` queue — runs the loop-agent via the host docker socket. Inert until a loop-agent LLM config + a puskesmas with EPUS creds exist |
| `celery_beat` | Scheduler. **Singleton — never scale above 1** or cron fires twice |

Beat schedule (`backend/app/celery_app.py`, timezone `Asia/Jakarta`):

- `cron.dispatch_due` every 60 s — fires due puskesmas cron configs
- `cron.dispatch_school_due` every 60 s — same for school CKG
- `cron.warm_reports` daily 05:00 — pre-warms report caches
- `loop_agent.run_nightly` daily 00:00 — no-op unless `loop_config.nightly_enabled`

## 1.4 Backend map (`backend/app/`)

| Dir | Contents |
|---|---|
| `api/routes/` | One router per resource. `main.py` registers them all. Auth: `admin_auth` (internal admins), `prod_auth` (prod-scope admins for the client dashboard), `auth` (puskesmas users) |
| `tasks/` | Celery tasks: `scrape.py`, `merge.py`, `sync.py`, `cron.py`, `create_patient.py`, `gdp_report.py`, `loop_agent.py` |
| `models/` | SQLAlchemy models. Most carry `SoftDeleteMixin` (global auto-filter in `core/soft_delete.py`) |
| `crud/`, `schemas/` | Data access + Pydantic schemas |
| `services/` | Pure-ish logic: `epus_to_asik.py` (converter), `*_registry_scan.py` (report rules), `asik_defaults.py` (Part 2), exports, `chatbot_knowledge.py` |
| `data/` | `asik_form_mapping.json` (the ASIK form catalogue), `paket_map.py`, report templates, school form catalogue |
| `prompts/` | LLM prompts (`merge_patient.md`) |
| `integrations/` | `llm_chat.py` — the OpenAI-compatible chat client |
| `core/` | Security (Fernet encrypt/decrypt, JWT), rate limit, token revocation, soft-delete filter, report warm, resource sampler |
| `config.py` | All settings (pydantic-settings). **Production refuses to boot** with a placeholder/short `JWT_SECRET` or an invalid Fernet `CRED_ENCRYPTION_KEY` |

Tests: `backend/tests/` (pytest). Utility/backfill scripts: `backend/scripts/`.

## 1.5 Data model essentials

- **`puskesmas`** — one per health centre; holds `epus_cred` / `asik_cred` (encrypted login blobs).
- **`patients`** — one row per `(puskesmas, nik, filter_date, ruangan)`. Key columns:
  - `scraped_epus_data`, `scraped_asik_data`, `merged_data` — **Fernet-encrypted blobs**
  - `match_status` — `asik_only` / `epus_only` / `matched`
  - `match_group_id` — links the same visit scraped on different dates (ASIK lags EPUS by days–weeks; window = `MATCH_WINDOW_DAYS`, default 7)
  - `merged_at`, `asik_synced_at`, `asik_default_fills` (Part 2)
  - denormalised plain columns (`birth_date`, `epus_tandai_ckg`, `has_mandiri`, `is_ckg_sekolah`) so SQL can filter without decrypting
- **`school_patients`** — CKG Sekolah, separate table and separate scrape kind (`asik_sekolah`).
- **Job tables** — `scrape_jobs` (kinds: `asik`, `epus`, `asik_sekolah`), `merge_jobs`, `sync_jobs`, `gdp_report_jobs`, `loop_runs`.
- **Scheduling** — `cron_configs` (per puskesmas schedule), `cron_runs` (one date's execution), `cron_backfills` (date-range runs).
- **`llm_configs`** — provider/model/base_url/encrypted key, with role flags: `is_active` (merge), `is_active_captcha`, `is_active_chatbot`, `is_active_loop_agent`, `is_active_loop_reviewer`.
- **`users` / `admins`** — admins are partitioned by `scope` (`internal` vs `prod`); the split is enforced only at login.

## 1.6 The pipeline in detail

**1. Scrape** (`tasks/scrape.py` → `scrapers/*`). Celery launches a Playwright subprocess per job and
streams its stdout to Redis (log ring + SSE). A puskesmas can have at most one active scrape job
across `asik` and `epus` (a second start returns 409). Cancel is cooperative via a Redis flag.
A hung subprocess is killed after `SCRAPE_SUBPROCESS_TIMEOUT_SECONDS` (6 h). ASIK login can use a
captcha solver driven by the `is_active_captcha` LLM config.

**2. Match.** The scrape write-path upserts patients and links EPUS/ASIK rows by NIK (+ the cross-date
window), setting `match_status`.

**3. Merge** (`tasks/merge.py`). The merge is **backend-deterministic, not LLM-driven** (also stated in
`CLAUDE.md` §9):

- EPUS data is first converted into ASIK's form shape by `services/epus_to_asik.py`.
- The LLM only judges fields filled on **both** sides for conflict. Patient identity is withheld from the prompt.
- The backend owns field presence, raw values and status (`_complete_source_fields`, `_rebuild_identitas`, `_normalize_status_flags`) and prunes anything not in a source → no hallucinated fields.
- **Clinical fields: EPUS wins; ASIK fills gaps. Identity is the inverse: ASIK wins.**
- Consequence: merge quality ≈ **converter quality**, not model/prompt quality.

**4. Sync** (`tasks/sync.py` → `scrapers/asik_sync/sync.py`) — pushes `merged_data` back into ASIK's
forms. See Part 2.

**5. Create** (`tasks/create_patient.py` → `scrapers/asik_sync/register.py`) — optional step *after* sync:
registers `epus_only + tandai_ckg` patients that are not yet in ASIK, then fills them. Runs in the same
one-account ASIK lane as sync.

**6. Reports.** `services/*_registry_scan.py` apply the clinical rules per registry (hipertensi, DM,
lipid, obesitas, bayi) over decrypted merged data; routes serve them to the dashboards; caches are
pre-warmed daily at 05:00.

## 1.7 Cron and backfill

A cron run executes steps in order; the chain depends on `source_scope` (`cron.py::_next_step`):

```
 BOTH       EPUS → ASIK → MERGE → [SYNC] → [CREATE] → done
 EPUS_ONLY  EPUS → MERGE → [SYNC] → [CREATE] → done
 ASIK_ONLY  ASIK → MERGE → [SYNC] → [CREATE] → done
 NONE       MERGE → [SYNC] → [CREATE] → done      (no scraping; sync-only backfill)
```

| Setting | Values |
|---|---|
| `merge_mode` | `normal` (merge only un-merged) · `force_remerge` (re-merge all matched, re-calls the LLM) · `no_merge` (scrape only — lets scraping continue while the LLM provider is down) |
| `sync_mode` | `off` (default) · `normal` (only `asik_synced_at IS NULL`) · `force_resync` (everyone, ignores the guard) |
| `source_scope` | `both` · `epus_only` · `asik_only` · `none` (backfill) |
| `lookback_days` | Default **3**. Each scheduled fire re-processes the last N days so late-arriving data that matches only once both sides land is still picked up. `1` = single-day |
| create step | Off by default; only meaningful when `sync_mode != off` |

`no_merge` + a sync mode is a no-op: the run short-circuits to `done` at the merge step.

## 1.8 Frontends

Both are Next.js (App Router) + TypeScript + Tailwind v4 + TanStack Query v5 + zod + react-hook-form.
Conventions (cache-update-over-refetch, lazy fetching, zustand list-filter stores, debounced search,
`AsyncCombobox`, single error shape `{"detail": "<string>"}`) are in `CLAUDE.md` §7.

- **frontend-internal** pages: dashboard, puskesmas, patients, scrape-jobs, merge-with-ai, merge-conflicts, sync-jobs, cron-runs, loop-runs, llm-configs, llm-logs, users, school-patients, visit-summary, mapping-reference, calculator, and the report pages (hipertensi, dm, lipid, obesitas, bayi-kuning-ikterus(-berat), gdp).
- **frontend-dashboard** pages: dashboard, patients, school-patients, merge-conflicts, and the same report pages.
- **frontend-shared** holds the report/patient UI both show (`hipertensi/`, `dm/`, `lipid/`, `obesitas/`, `bayi/`, `patients/`, `school-patients/`). Rule: **if both apps show it, it lives in `frontend-shared/`**; app-specific actions (Sync buttons, Diagnose tab, clear-cache) are injected as slots so they never ship in the client bundle. Details: `frontend-shared/README.md`.

## 1.9 Run it locally

```bash
docker compose -f docker-compose.local.yml up -d     # Postgres + Redis
cd backend
cp .env.example .env                                 # set CRED_ENCRYPTION_KEY (Fernet), JWT_SECRET, ADMIN_*
python3 -m venv .venv && source .venv/bin/activate
pip3 install -e ".[dev]" && playwright install chromium
alembic upgrade head
uvicorn app.main:app --reload                        # terminal A — API  (docs at /docs when APP_ENV=local)
celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=4   # terminal B
celery -A app.celery_app.celery_app beat   --loglevel=info                   # terminal C (singleton)
```

Full production-like stack: `docker compose up --build -d` (needs `backend/.env`).
Generating the Fernet key and the scrape-via-API walkthrough: `scrapers/README.md`.

## 1.10 Adapting it — what you will actually touch

| You want to… | Start here |
|---|---|
| Point at different portals / a different source system | `scrapers/epus/`, `services/epus_to_asik.py`, and the `ckg-form-research` skill (`.claude/skills/ckg-form-research/`) |
| Change which fields get merged or who wins a conflict | `tasks/merge.py` (`_complete_source_fields`, `_rebuild_identitas`), `prompts/merge_patient.md` |
| Use a different LLM provider | Admin UI → LLM configs (OpenAI-compatible `base_url`); defaults in `config.py` (`LLM_MODEL`, `LLM_BASE_URL`) |
| Change default values the sync fills | Part 2, `services/asik_defaults.py` |
| Add or change a report | `services/<x>_registry_scan.py`, `api/routes/<x>_report.py`, `frontend-shared/<x>/` — then the chatbot packs (`CLAUDE.md` §10) |
| Change the schedule / pipeline | `tasks/cron.py`, `models/cron_config.py` |
| Rename/rebrand | `config.py` (`ADMIN_*`, `CORS_ORIGINS`), the two frontends' `app/layout.tsx` + `globals.css`, `chatbot/system.md` |

**Before you publish or fork, scrub:** `CLAUDE.md` mentions a specific prod host, a named maintainer,
and operational incidents (check `chatbot/` and the skills too — not read for this); `scrapers/file_reference/` holds a spreadsheet; the old
copy of this file contained a real patient name (removed below). Default credentials in docs
(`admin@ckg.com` / `Admin123!`) are for local seed only — change them.

## 1.11 What I did *not* read

So you know where this guide is thin: the scraper internals (`scrapers/*/`), the merge prompt text,
the sync scraper's fill logic (`scrapers/asik_sync/sync.py`), the report-scan rule details, the
loop-agent internals beyond its README, and the Alembic history. The `chatbot/`, `loop-agent/`,
`scrapers/` and `frontend-shared/` READMEs are the authoritative detail for those.

---

# Part 2 — ASIK sync default fills

**Goal:** let the robot submit a patient's ASIK forms even when ASIK *requires* a question we
have no data for — by putting a safe **default value** and **logging it**, so reports can always
tell real data from auto-filled.

> *ASIK won't let us submit with blanks on required questions. So we fill the blanks with a safe
> default and write down exactly what we faked.*

**Status:** implemented on `master` — `patients.asik_default_fills` exists
(`backend/app/models/patient.py`), the policy lives in `backend/app/services/asik_defaults.py`,
and `backend/tests/test_asik_defaults.py` covers it. (The original note said "implemented on a
feature branch, not deployed"; that is out of date for the code. Whether it has run in your
production is something only your own `sync_jobs` table can tell you.)

## 2.1 The rule per form

```
  For each form the patient has on ASIK:

     ≥1 real answer in that form ? ──NO──►  ⏭  SKIP the whole form (don't submit)
              │
             YES
              ▼
     ①  fill every field we DO have real data for
     ②  any REQUIRED field still empty?   ← read the "*" LIVE from the form
              └─ yes ─►  put a DEFAULT value   +   log {layanan, question, value, kind}
     ③  click "Kirim"  ✔
```

*Why skip a form with 0 real answers?* Submitting a 100 % invented form (e.g. a mental-health
screen) adds no real data. One real answer is enough to keep and complete the form.

## 2.2 How a default is chosen

| Question type | Default | Example |
|---|---|---|
| **Choice** (radio / dropdown) | the clinically-safe pole — see the order below | lab → **Negatif** · HIV → **Non Reaktif** · finding → **Normal** · risk → **Tidak** · PHQ mood → **Tidak sama sekali** · gait → **fastest band** |
| **Positive / abnormal result** | 🚫 **never auto-filled** — left blank so the form fails safe | EKG "abnormal-only", TB-type |
| **Number** | a fixed clinically-normal, in-range value (table below) | BB → **60** · Hb → **13** · Sistolik → **120** |
| **Free text** | an obvious placeholder | **"-"** |
| **Usia (age)** | 🚫 never faked — derived from birth date | — |

Choice order (`asik_defaults._choice_default`, first match wins):

1. an unambiguous negative/normal **result** option (Negatif, Non Reaktif, Normal, "Tidak ada", …);
2. a Ya/Tidak pair → **Tidak**;
3. a graded time/performance band ("… detik") → the **best** band (highest score);
4. otherwise the lowest `nilai_poin` — **but never a disease-present option**;
5. otherwise a keyword net over non-disease options; else **nothing** (don't fabricate a finding).

> **Why not just take ASIK's lowest `nilai_poin`?** ASIK's score is not a universal risk scale. On
> the newborn (SHK/G6PD/HAK) and geriatric (SPPB/SKILAS) forms it is *inverted*, so "lowest score"
> would default a congenital-disease screen to **Positif** and a mobility test to the *worst* band.
> Explicit safe signals therefore beat the raw score (steps 1–3), and a positive/abnormal finding
> is never submitted. *(The module docstring at the top of `asik_defaults.py` still describes the
> older "lowest score wins" wording; the function body above is the real behaviour.)*

> **Why not "all numbers = 50"?** 50 is impossible for Hb and dangerous for blood pressure, and it
> would fail ASIK's own min/max check and re-block the submit. A normal in-range value always passes
> — and every default is logged, so each one stays identifiable.

### Number defaults (`_NUMBER_DEFAULTS`, matched by substring on the normalised label — order matters)

| Field | Default | Field | Default |
|---|---|---|---|
| Usia | **never** | Kolesterol total | 180 |
| Berat badan | 60 | Trigliserida | 120 |
| Tinggi badan | 160 | HDL | 55 |
| Lingkar perut | 80 | LDL | 100 |
| Hemoglobin | 13 | Kreatinin (serum) | 0.9 |
| SGOT | 25 | Kreatinin urin | 100 |
| Trombosit | 250 000 | Ureum | 25 |
| GDS / GDS ke-2 | 100 | e-LFG / CKD-EPI | 95 |
| GDP | 90 | Albumin urin | 15 |
| GD 2 jam PP | 110 | Sistolik (+ ke-2) | 120 |
| Kadar CO napas | 3 | Diastolik (+ ke-2) | 80 |

The list is ordered most-specific-first on purpose (e.g. "gula darah sewaktu kedua" before "gula
darah sewaktu", "kreatinin urin" before "kreatinin"). A number not in this list is **not** guessed.

## 2.3 "Required" is read LIVE, never trusted from a document

The documented list and the live portal disagreed during research: the "Hati" form was documented
0/9 required and live ASIK showed 9/9 with "*". ASIK changes its rules silently, so the robot reads
the "*" on the live form at fill time. The documentation (`data/asik_form_mapping.json`) is only a
starting reference — it supplies the default *value*; whether a field is *needed* is decided live.

## 2.4 Live safety net (when the catalogue has no answer)

`build_default_values_map()` derives a default for every catalogued question where one can be
trusted, and passes the map to the sync scraper. Anything not in the map falls back to a live
heuristic in the scraper, which handles three drift cases seen on the GPAQ form:

- **radio/checkbox** — read the visible options, pick the safe/negative one;
- **dropdown** — open it, read its real options (SurveyJS hides them until opened), pick the safe one;
- **behavioural follow-up numbers** — "days/week", "minutes/day" that appear after an activity is
  answered "Ya" get a minimal in-range value (1 day / 30 min). An unknown *clinical* number (e.g. Hb)
  is still left blank.

A still-blank required field means the form can't submit — the honest outcome rather than a
fabricated number.

## 2.5 What gets logged

`patients.asik_default_fills` — plain JSONB (not encrypted; it is metadata, not clinical data),
overwritten on each successful sync, `NULL` = never synced or nothing needed defaulting:

```json
[
  { "layanan": "Tingkat Aktivitas Fisik", "question": "Apakah Anda melakukan olahraga…", "value": "Tidak", "kind": "radio" },
  { "layanan": "Faktor Risiko X-Ray TB",  "question": "Apakah Anda mengalami demam…",   "value": "Tidak", "kind": "radio" }
]
```

Reports can subtract these entries to separate real measurements from auto-filled placeholders.

## 2.6 Worked example (anonymised adult female)

| Her forms | Real answers | What sync does |
|---|---|---|
| Gizi, Tekanan Darah, Gula Darah, Telinga/Mata, Karies, Demografi | full | already done — no action |
| Faktor Risiko TB | 1/1 | submit, no default needed |
| Perilaku Merokok | 1/2 | submit **+ 1 default** |
| Tingkat Aktivitas Fisik | 1/6 | submit **+ 7 defaults** (5 activity-dropdown gaps + 2 number follow-ups revealed by her one real "Ya") |
| Faktor Risiko X-Ray TB | 1/6 | submit **+ 5 defaults** |
| Hati, Kesehatan Jiwa, TB, Fibrosis, Hepatitis, HIV, Sifilis, Hemoglobin, Frambusia, Kusta, Skabies, Kadar CO, Catin | 0 | ⏭ **skipped** |

Lab-result forms are skipped for her because she has zero real data in each, so defaults only ever
touch partial questionnaires. Other patients (e.g. an elderly patient or a male patient) carry
different forms; the live rule covers them.

## 2.7 Sync behaviour and cron integration

- **Only matched + AI-merged data is ever submitted.** Sync requires `merged_data` on every path
  (cron and manual button). The older EPUS-only fallback (push raw ePus without merging) is
  disabled by the constant `ALLOW_EPUS_ONLY_SYNC = False` in `tasks/sync.py` (kept, not deleted).
  The create-patient step deliberately bypasses that gate — it fills a patient that has no ASIK
  record to merge with.
- `patients.asik_synced_at` is stamped on success (manual button too), **only when no form failed**,
  so `normal` retries a patient whose forms hit a transient error.
- **Re-submit updates in place** (ASIK keys a screening by patient + date), so `force_resync` is a
  deliberate "push again", not a duplicate.
- **Gap:** `normal` skips already-synced patients, so **re-merged data is not re-pushed** by `normal`.
  Use `force_resync` after a re-merge.
- **One ASIK login, several browsers.** ASIK invalidates a session on a *second login*, not on
  concurrent requests, so a cron sync batch shares one login across `ASIK_SYNC_CONCURRENCY` browsers
  (default **2**; `1` = strictly sequential). Each extra Chromium costs roughly 400–600 MB — raise it
  only while watching memory, CPU and the `validation_error` rate in `sync_jobs` (rising
  `validation_error` means the box is overloaded, not that ASIK is rate-limiting).
- A single sync subprocess is killed after `SYNC_SUBPROCESS_TIMEOUT_SECONDS` (30 min per patient;
  typical is about 94 s) so a hung browser cannot hold a Celery slot forever.
- `sync_mode` options and the cron step order are in §1.7.

## 2.8 Where to change things

| Change | File |
|---|---|
| A default value or the choice policy | `backend/app/services/asik_defaults.py` (+ `backend/tests/test_asik_defaults.py`) |
| The ASIK form catalogue the defaults are derived from | `backend/app/data/asik_form_mapping.json` (built by `backend/app/data/build_mapping.py`) |
| How defaults are applied at fill time and the live fallback | `scrapers/asik_sync/sync.py` (`_fill_required_defaults`, `_resolve_default`) |
| Persisting the log, stamping `asik_synced_at` | `backend/app/tasks/sync.py` (calls `build_default_values_map()`, then `set_asik_default_fills`) |
| Skipping a form with 0 real answers | `scrapers/asik_sync/sync.py` (the `if filled == 0` branch) |

After editing anything under `backend/app/`, **restart the Celery worker** (it does not hot-reload),
and re-sync affected patients with `force_resync`.
