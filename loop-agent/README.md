# loop-agent

The self-maintaining agent that keeps the **Medisy client, adapter and
`medisy_to_asik.py`** converter correct as puskesmas are onboarded (~5,000
target). One OpenCode session (GLM-5.3-Flash) per run: it calls the puskesmas's
live Medisy API with plain HTTP, captures what the API truly serves, runs our
code on the same day, compares the two, and judges — because any
script-encoded assumption goes stale the moment Medisy changes or a puskesmas
uses a form we have not seen. On a gap the agent fixes the code and re-proves it
in the same session; an in-container reviewer (GLM-5.3) then checks the diff
before a PR opens. It **never deploys**, **never writes to ASIK** and **never
writes to Medisy** (the Medisy API is a separate project; a missing field is a
finding).

Full design + rationale: **`.claude/plan/loop-agent/PLAN.md`**. This folder holds
everything the container runs; the orchestration code lives in
`backend/app/tasks/loop_agent.py` + `backend/app/api/routes/loop_runs.py`, the UI in
`frontend-internal/app/(dashboard)/loop-runs/`.

## Files here

| File | What it is |
|---|---|
| `run.sh` | Entrypoint + scaffolding: prepare workspace → one agent session → reviewer → PR → LOOP_RESULT. Never judges coverage. |
| `PROMPT.md` | The fixed per-run checker prompt (`{name}` / `{region_url}` / `{region}` / `{detail_n}` / `{max_fix}`). The agent follows the ckg-form-research skill and `MEDISY_TO_ASIK_RULES.md`. |
| `render_prompt.py` | Substitutes the placeholders in `PROMPT.md` for one run. |
| `reviewer.py` | One-shot LLM review of the fix diff → `.review_result.json` (approve / request_changes / error). |
| `notes_lint.py` | Enforces the LOOP_NOTES.md rules: format, dedupe (`xN`), 50-line cap + archive, PII strip. |
| `format_stream.py` | Pipes the session stream into readable lines (drops OpenCode's JSON firehose; tool calls become one-liners). |
| `AGENTS.md` | The agent's operating rules — identity + the NEVER list. OpenCode reads this. |
| `LOOP_NOTES.md` | The agent's working memory: bug records + Known-empty registry. Clean runs write NOTHING. |
| `opencode.json` | Committed guardrails (permission deny-list). Model/key injected at launch. |
| `gen_opencode_config.py` | Merges `opencode.json` with the injected provider/model/key → final config. |
| `Dockerfile` | The throwaway agent container (ckg-backend + Node + OpenCode PINNED + git + gh). |
| `worker.Dockerfile` | The loop celery-worker image (ckg-backend + docker CLI). |

## Ownership map (maintenance rules, PLAN §7)

- Changing HOW the agent behaves → edit only this folder (mostly `PROMPT.md`).
- Changing WHEN/WHY runs happen → `backend/app/tasks/loop_agent.py` + routes + config.
- Changing what the dashboard shows → `frontend-internal` loop files.
- The image almost never needs rebuilding: the agent reads the client +
  converter + skill scripts from the cloned repo at runtime. Rebuild only when
  `run.sh`, the pinned opencode version, or the base image changes.

## The one interface: env contract (worker → container)

| Var | Meaning |
|---|---|
| `LOOP_RUN_ID` / `LOOP_PUSKESMAS_NAME` / `LOOP_PORTAL_URL` | run metadata (no credentials) |
| `LOOP_LLM_MODEL/BASE_URL/API_KEY/REASONING` | the agent (from the loop-agent llm_config) |
| `LOOP_REVIEWER_ENABLED` + `LOOP_REVIEWER_MODEL/BASE_URL/API_KEY/REASONING` | the reviewer (optional by design) |
| `LOOP_PIN_REF` | optional git ref to pin (acceptance tests) |
| `LOOP_MERGE_MODE` / `LOOP_MAX_FIX_ITERS` / `LOOP_MAX_REVIEW_ITERS` / `LOOP_DETAIL_LIMIT` | loop knobs (fix-pass ceiling, review rounds, patients deep-checked per run) |
| `LOOP_GITHUB_TOKEN` / `LOOP_GITHUB_REPO` | branch push + PR (unset = local branch + patch to log) |
| `LOOP_LLM_ROUTE_ORDER` / `LOOP_REVIEWER_ROUTE_ORDER` | OpenRouter provider-order locks (e.g. `z-ai`) |
| `DATABASE_URL` / `CRED_ENCRYPTION_KEY` / `JWT_SECRET` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` | app-config env the agent's DB reads + regression check need; DATABASE_URL should be a READ-ONLY role in prod |

The Medisy token is NOT in env: the agent decrypts it from the DB by
`epus_url` (the column holds the Medisy host) into a temp file (never
printed), the same way production scrapes do. The verdict protocol back is the LAST stdout line:
`LOOP_RESULT:{json}` with `decision` (covered / no_data / bad_login / gap /
fixed), `test_date`, `live_count`, `scraped_count`, `gap_summary`,
`branch_name`, `pr_url`, `review_verdict`, `review_comments`. The decision
comes from the agent's own `loop-agent/.check_result.json`.

## How one run works

1. The API (`POST /loop/runs`) or the nightly trigger creates a `LoopRun` row and
   enqueues `loop_agent.run_one` on the dedicated `loop` Celery queue (own worker —
   no collision with scrape/merge/sync).
2. The loop worker `docker run`s a throwaway `loop-run-<id>` container (this image)
   with the env contract above; the repo is bind-mounted read-only at `/seed`.
3. `run.sh` clones `/seed` to `/work`, (optionally) pins a git ref, overlays the
   current tooling, generates `opencode.json`, and starts ONE agent session.
4. The session (PROMPT.md): read the token → pick a recent weekday with CKG
   visits (`GET /visits`) → capture the API's truth with plain HTTP (the full day
   list + the bundles of `LOOP_DETAIL_LIMIT` visits) → run our client, adapter
   and converter on the same date (no database writes) → compare → judge. On a
   gap: fix the Medisy client / adapter / converter files listed in PROMPT.md
   STEP 7, re-run the whole check, up to `LOOP_MAX_FIX_ITERS` passes — then the
   `tests/test_medisy_*.py` suite (and `verify_converter --source medisy` when
   patients with both a Medisy and an ASIK record exist) must pass.
5. The reviewer (GLM-5.3, optional) reviews the diff; a PR opens for a human to
   merge (auto-merge only when config=auto + reviewer approve + agent verdict
   covered). The worker streams stdout to the dashboard (Redis ring + SSE) and
   parses LOOP_RESULT to finalize the run.

Every run is a real agent session: expect minutes + tokens per puskesmas, even
when it comes back covered on the first pass.
