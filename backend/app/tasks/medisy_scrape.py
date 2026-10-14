"""The clinic-source step of a scrape job, served by Medisy's API instead of a browser.

Called by ``tasks/scrape.py::run_scrape`` for ``ScrapeKind.EPUS`` (the kind keeps its name — it now means "the
clinic-record source"; the column and enum names are deliberately not renamed). There is no subprocess, no Playwright and no
CAPTCHA: a few JSON calls per day, upserted day by day so a cancel keeps everything finished so far.

Reuses the existing job plumbing — ``scrape_job_crud`` status helpers, the Redis log ring + SSE channel, the Redis cancel flag
(CLAUDE.md §8.2: never poll Postgres for it) — and ``patient_crud.upsert_from_scrape``.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, date, datetime
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.crud import patient as patient_crud
from app.crud import scrape_job as scrape_job_crud
from app.integrations.medisy_client import MedisyClient, MedisyError
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeJob, ScrapeKind
from app.services.medisy_adapter import extract_patients, fetch_day_bundles

log = logging.getLogger(__name__)

_LOG_RING_MAX = 500
_LOG_TTL_SECONDS = 86400


def _emit(rc: redis.Redis, log_key: str, chan: str, line: str) -> None:
    """One line into the job's live log (ring buffer + pub/sub), best effort like the subprocess drain."""
    try:
        rc.rpush(log_key, line)
        rc.ltrim(log_key, -_LOG_RING_MAX, -1)
        rc.expire(log_key, _LOG_TTL_SECONDS)
        rc.publish(chan, line)
    except Exception:
        pass


def _json_list(raw: str | None, what: str) -> list[str]:
    try:
        return [str(x) for x in json.loads(raw) if x] if raw else []
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid {what}: {exc}") from exc


def _plan(job: ScrapeJob, patient_nik: str | None) -> tuple[list[date], set[str] | None]:
    """The days to read and the optional NIK filter. Raises ValueError (shown as the job's error) on bad input."""
    if patient_nik is None and job.date_filters:
        iso_days = _json_list(job.date_filters, "date_filters")
        if not iso_days:
            raise ValueError("date_filters is empty")
    else:
        if not job.date_filter:
            raise ValueError("the clinic-source scrape requires date_filter")
        iso_days = [job.date_filter]
    try:
        days = [date.fromisoformat(d) for d in iso_days]
    except ValueError as exc:
        raise ValueError(f"invalid date: {exc}") from exc

    if patient_nik is not None:
        return days, {patient_nik}
    niks = _json_list(job.target_niks, "target_niks")
    return days, (set(niks) if niks else None)


def run_medisy_scrape(
    db: Session,
    rc: redis.Redis,
    job: ScrapeJob,
    puskesmas: Puskesmas,
    creds: dict[str, Any],
    patient_nik: str | None,
    *,
    cancel_key: str,
    log_key: str,
    chan: str,
) -> None:
    """Run the whole job and leave it in a terminal state (success / failed / left cancelled). The caller has already
    marked it RUNNING. Anything unexpected propagates so ``run_scrape``'s outer handler marks the job failed."""
    t0 = time.monotonic()

    def now() -> datetime:
        return datetime.now(UTC)

    def finish_failed(message: str) -> None:
        scrape_job_crud.mark_failed(db, job, message[:2000], now())
        _emit(rc, log_key, chan, f"failed: {message[:300]}")
        try:
            rc.publish(chan, "__failed__")
        except Exception:
            pass

    token = creds.get("token")
    if not token:
        finish_failed("Medisy token is not set for this puskesmas (the stored credential is not a token) — enter it again")
        return
    if not puskesmas.epus_url:
        finish_failed("Medisy URL is not set for this puskesmas")
        return
    try:
        days, niks = _plan(job, patient_nik)
    except ValueError as exc:
        finish_failed(str(exc))
        return

    def cancelled() -> bool:
        try:
            return rc.get(cancel_key) == "1"
        except Exception:
            return False

    fetched_at = now().isoformat()
    scraped = inserted = updated = 0
    skipped: list[dict[str, str]] = []
    try:
        with MedisyClient(puskesmas.epus_url, token) as client:
            for day in days:
                if cancelled():
                    break
                bundles = fetch_day_bundles(
                    client, day, niks=niks, should_cancel=cancelled,
                    on_log=lambda line: _emit(rc, log_key, chan, line),
                )
                if cancelled():
                    break                # a half-read day is dropped, never saved: only whole days land (re-running it is idempotent)
                rows, day_skipped, day_count = extract_patients(bundles, fetched_at)
                scraped += day_count
                skipped += day_skipped
                try:
                    for nik, nama, blob, per_record_date in rows:
                        res = patient_crud.upsert_from_scrape(
                            db, job.puskesmas_id, ScrapeKind.EPUS, nik, nama, blob, per_record_date or day.isoformat(),
                        )
                        if res == "inserted":
                            inserted += 1
                        else:
                            updated += 1
                    db.commit()          # per day: a mid-run cancel or crash keeps every finished day
                except Exception:
                    db.rollback()
                    raise
                _emit(rc, log_key, chan, f"{day.isoformat()}: saved {len(rows)} patient(s), skipped {len(day_skipped)}")
    except MedisyError as exc:
        finish_failed(f"Medisy: {exc}")
        return

    if cancelled():
        # the cancel route already wrote CANCELLED + finished_at; just tell the stream
        try:
            rc.publish(chan, "__cancelled__")
        except Exception:
            pass
        return

    notes = None
    if skipped:
        notes = f"skipped {len(skipped)}:\n" + "\n".join(f"source_id={s['source_id']} reason={s['reason']}" for s in skipped)
    scrape_job_crud.mark_success(db, job, scraped, inserted, updated, time.monotonic() - t0, now(), notes=notes)
    try:
        rc.publish(chan, "__done__")
    except Exception:
        pass

