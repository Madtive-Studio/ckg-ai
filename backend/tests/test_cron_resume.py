"""Resume a failed scheduled run from the failed step, reusing the earlier steps' jobs (and retry still starts over).

Fully offline: MagicMock DB, crud.create / celery send_task patched.
"""
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.routes.cron_run as routes
from app.api.deps import get_current_admin_id, get_db
from app.main import app
from app.models.cron_config import CronSourceScope
from app.models.cron_run import CronRunStatus, CronStep
from app.models.merge_job import MergeStatus
from app.models.scrape_job import ScrapeStatus

NOW = datetime(2026, 11, 21, tzinfo=UTC)


def _run(**kw):
    base = dict(
        id=uuid.uuid4(), cron_config_id=uuid.uuid4(), cron_backfill_id=None, puskesmas_id=uuid.uuid4(),
        puskesmas=SimpleNamespace(name="PKM Contoh"), target_date=date(2026, 11, 20),
        source_scope=CronSourceScope.BOTH, status=CronRunStatus.FAILED, current_step=CronStep.MERGE,
        current_step_attempt=1, failed_step=CronStep.MERGE,
        asik_scrape_job_id=uuid.uuid4(), epus_scrape_job_id=uuid.uuid4(), merge_job_id=uuid.uuid4(),
        triggered_by_id=None, error_message="no active llm_config configured",
        started_at=NOW, finished_at=NOW, created_at=NOW, updated_at=NOW,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def api(monkeypatch):
    db = MagicMock()
    sent: list = []
    created: list = []

    def fake_create(_db, **kw):
        new = _run(status=CronRunStatus.PENDING, failed_step=None, current_step=None, error_message=None,
                   asik_scrape_job_id=None, epus_scrape_job_id=None, merge_job_id=None, **{
                       k: kw[k] for k in ("puskesmas_id", "target_date", "cron_config_id", "source_scope")})
        created.append(new)
        return new

    monkeypatch.setattr(routes.crud, "create", fake_create)
    monkeypatch.setattr(routes.celery_app, "send_task", lambda name, args: sent.append((name, args)))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin_id] = lambda: uuid.uuid4()
    with TestClient(app) as client:
        yield client, db, sent, created
    app.dependency_overrides.clear()


def _scalars(db, *values):
    """db.scalar returns these in order (load run, then any merge-status / active-run lookups)."""
    db.scalar.side_effect = list(values)


def test_resume_at_merge_reuses_both_scrapes_and_dispatches_merge(api):
    client, db, sent, created = api
    old = _run()
    db.execute.return_value.all.return_value = [
        (old.epus_scrape_job_id, ScrapeStatus.SUCCESS), (old.asik_scrape_job_id, ScrapeStatus.SUCCESS),
    ]
    _scalars(db, old, None)  # load run, no active run
    r = client.post(f"/admin/cron-runs/{old.id}/resume")
    assert r.status_code == 200, r.text
    new = created[0]
    assert new.epus_scrape_job_id == old.epus_scrape_job_id
    assert new.asik_scrape_job_id == old.asik_scrape_job_id
    assert new.merge_job_id is None  # the failed step runs again
    assert sent == [("cron.advance", [str(new.id), "merge"])]


def test_resume_at_sync_also_reuses_the_merge(api):
    client, db, sent, created = api
    old = _run(failed_step=CronStep.SYNC)
    db.execute.return_value.all.return_value = [
        (old.epus_scrape_job_id, ScrapeStatus.SUCCESS), (old.asik_scrape_job_id, ScrapeStatus.SUCCESS),
    ]
    _scalars(db, old, MergeStatus.SUCCESS, None)
    r = client.post(f"/admin/cron-runs/{old.id}/resume")
    assert r.status_code == 200, r.text
    assert created[0].merge_job_id == old.merge_job_id
    assert sent[0][1][1] == "sync"


def test_resume_refuses_when_the_first_step_failed(api):
    client, db, sent, _ = api
    old = _run(failed_step=CronStep.EPUS)
    _scalars(db, old)
    r = client.post(f"/admin/cron-runs/{old.id}/resume")
    assert r.status_code == 409
    assert "Coba lagi" in r.json()["detail"]
    assert sent == []


def test_resume_refuses_when_a_reused_step_did_not_succeed(api):
    client, db, sent, _ = api
    old = _run()
    db.execute.return_value.all.return_value = [
        (old.epus_scrape_job_id, ScrapeStatus.SUCCESS), (old.asik_scrape_job_id, ScrapeStatus.FAILED),
    ]
    _scalars(db, old)
    r = client.post(f"/admin/cron-runs/{old.id}/resume")
    assert r.status_code == 409
    assert "Ambil data ASIK" in r.json()["detail"]
    assert sent == []


def test_resume_refuses_a_cancelled_run(api):
    client, db, sent, _ = api
    old = _run(status=CronRunStatus.CANCELLED, failed_step=None)
    _scalars(db, old)
    r = client.post(f"/admin/cron-runs/{old.id}/resume")
    assert r.status_code == 409
    assert sent == []


def test_retry_still_starts_over_from_medisy(api):
    client, db, sent, created = api
    old = _run()
    _scalars(db, old, None)
    r = client.post(f"/admin/cron-runs/{old.id}/retry")
    assert r.status_code == 200, r.text
    assert created[0].asik_scrape_job_id is None and created[0].epus_scrape_job_id is None
    assert sent == [("cron.advance", [str(created[0].id), "epus"])]
