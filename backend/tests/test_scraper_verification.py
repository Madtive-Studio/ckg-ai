"""Admin notices for open scraper questions: counts → signals, first-sighting insert, list + acknowledge routes.

Fully offline (MagicMock DB). The "one row ever per (code, outcome)" rule is Postgres's ON CONFLICT; it is asserted
from the compiled SQL.
"""
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.deps import get_current_admin_id, get_db
from app.main import app
from app.services.scraper_verification import QUESTIONS, record_first_sightings, signals_from_counts

SCRAPER_DIR = Path(__file__).resolve().parents[2] / "scrapers" / "asik"


# ----------------------------------------------------------------------------- counts → signals


def test_no_counts_means_no_signals():
    assert signals_from_counts(None) == []
    assert signals_from_counts({}) == []
    assert signals_from_counts({"nakes_submitted_read": 0}) == []


def test_success_only_is_answered_and_any_failure_is_a_problem():
    by_code = {s["code"]: s for s in signals_from_counts({
        "nakes_submitted_read": 4,
        "tatalaksana_ok": 2, "tatalaksana_error": 1,
        "detail_failed": 3,
    })}
    assert by_code["asik_nakes_filled"] == {
        "code": "asik_nakes_filled", "outcome": "answered", "ok_count": 4, "problem_count": 0,
    }
    assert by_code["asik_tatalaksana"]["outcome"] == "problem"
    assert (by_code["asik_tatalaksana"]["ok_count"], by_code["asik_tatalaksana"]["problem_count"]) == (2, 1)
    assert by_code["asik_detail_failed"]["outcome"] == "problem"
    assert "asik_tab_belum" not in by_code


def test_garbage_counts_are_ignored():
    assert signals_from_counts({"nakes_submitted_read": "x", "tatalaksana_ok": -5, "tab_belum_ok": None}) == []


def test_first_sighting_insert_never_duplicates_a_code_outcome_pair():
    db = MagicMock()
    n = record_first_sightings(db, puskesmas_id=uuid.uuid4(), scrape_job_id=uuid.uuid4(),
                               counts={"tab_sedang_ok": 7})
    assert n == 1
    sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_scraper_verification_signals_code_outcome DO NOTHING" in sql


def test_nothing_to_record_issues_no_sql():
    db = MagicMock()
    assert record_first_sightings(db, puskesmas_id=uuid.uuid4(), scrape_job_id=uuid.uuid4(), counts={}) == 0
    db.execute.assert_not_called()


def test_every_count_key_is_emitted_by_the_asik_scraper():
    """A renamed counter in the scraper would silently stop a notice from ever firing — keep both sides in sync."""
    src = "\n".join(p.read_text() for p in (SCRAPER_DIR / "scraper.py", SCRAPER_DIR / "patient_scraper.py"))
    tab_names = set(re.findall(r'"(tab_[a-z]+)"', src))
    for ok_key, problem_key in QUESTIONS.values():
        for key in (ok_key, problem_key):
            if key is None:
                continue
            if key.startswith("tab_"):
                base, suffix = key.rsplit("_", 1)
                assert base in tab_names and f'f"{{tab_signal}}_{suffix}"' in src, key
            else:
                assert f'"{key}"' in src, key


# ----------------------------------------------------------------------------- routes


@pytest.fixture
def api():
    db = MagicMock()
    admin = uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin_id] = lambda: admin
    with TestClient(app) as client:
        yield client, db, admin
    app.dependency_overrides.clear()


def test_list_returns_pending_notices_with_the_puskesmas_name(api):
    client, db, _ = api
    sid, pid, jid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(_mapping={
        "id": sid, "code": "asik_nakes_filled", "outcome": "answered", "ok_count": 3, "problem_count": 0,
        "puskesmas_id": pid, "puskesmas_name": "Puskesmas Contoh", "scrape_job_id": jid,
        "created_at": datetime(2026, 11, 21, tzinfo=UTC),
    })
    db.execute.return_value.all.return_value = [row]
    r = client.get("/admin/scraper-verification")
    assert r.status_code == 200
    assert r.json()[0]["puskesmas_name"] == "Puskesmas Contoh"
    assert r.json()[0]["scrape_job_id"] == str(jid)
    sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "acknowledged_at IS NULL" in sql


def test_acknowledge_stamps_the_admin_and_commits(api):
    client, db, admin = api
    db.execute.return_value.rowcount = 1
    r = client.post(f"/admin/scraper-verification/{uuid.uuid4()}/acknowledge")
    assert r.status_code == 204
    params = db.execute.call_args.args[0].compile(dialect=postgresql.dialect()).params
    assert admin in params.values()
    db.commit.assert_called_once()


def test_acknowledge_unknown_or_already_seen_is_404(api):
    client, db, _ = api
    db.execute.return_value.rowcount = 0
    r = client.post(f"/admin/scraper-verification/{uuid.uuid4()}/acknowledge")
    assert r.status_code == 404
    db.commit.assert_not_called()
