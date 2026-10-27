# CKG Backend

FastAPI + SQLAlchemy + Postgres backend.

## Quickstart

### Local dev (backend on host, infra in Docker)

```bash
# from repo root: bring up Postgres + Redis
docker compose -f docker-compose.local.yml up -d

cd backend
cp .env.example .env
# ensure CRED_ENCRYPTION_KEY in .env — see scrapers/README.md §1-2 to generate
python3 -m venv .venv && source .venv/bin/activate
pip3 install -e ".[dev]"
playwright install chromium      # required by scraper Celery tasks
alembic upgrade head

# Terminal A — API
uvicorn app.main:app --reload

# Terminal B — Celery worker (handles /scrape/*, /merge/*, cron tasks)
celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=4

# Terminal C — Celery beat (cron scheduler; singleton — only run one)
celery -A app.celery_app.celery_app beat --loglevel=info
```

API at http://localhost:8000. OpenAPI docs at /docs.

### Production-like stack (everything in Docker)

```bash
# from repo root — requires backend/.env to exist
cp backend/.env.example backend/.env  # edit values for prod
docker compose up --build -d
```

Backend container runs `alembic upgrade head` on start, then `uvicorn` with 4 workers (no reload).

## Auth

Login as the seeded admin:

```bash
curl -X POST http://localhost:8000/admin/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@ckg.com","password":"Admin123!"}'
```

Use the returned `access_token` as `Authorization: Bearer <token>` for admin endpoints.

## ASIK login

The ASIK email + password are kept in Medisy (Konfigurasi → Akun ASIK) and read through
`GET /medisy_api/ckg/asik-credential`. ckg-ai stores the fetched login encrypted in `puskesmas.asik_cred` and
refreshes it when the Medisy token is saved, on "Test connection", and before every ASIK scrape / sync / create-patient
job (`crud.puskesmas.refresh_asik_cred_from_medisy`). If Medisy has no login or is unreachable, the copy already held
(for example one entered by hand) is used unchanged.

## Soft Delete

All tables carry `deleted_at`. ORM queries auto-exclude soft-deleted rows. No hard deletes.
