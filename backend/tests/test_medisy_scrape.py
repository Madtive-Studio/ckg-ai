"""The Medisy clinic-source step: adapter, blob-shape helpers, and the job runner.

Offline: the Medisy client, the DB session, Redis and the CRUD calls are all faked, so what is under test is the
orchestration — which days are read, what is stored, how cancel / failure / progress behave.
"""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.tasks.medisy_scrape as ms
from app.crud.patient import _extract_epus_ruangan, _extract_tandai_ckg
from app.integrations.medisy_client import BundleBatch, MedisyAuthError
from app.models.scrape_job import ScrapeKind
from app.services import medisy_adapter as adapter
from app.services.birthdate import birth_date_for_patient, birth_date_from_medisy
from app.tasks import scrape as scrape_task


def bundle(visit_id, nik="3201000000000001", name="PASIEN FIKTIF", day="2026-09-02", room="KLASTER 3 R DEWASA - CKG",
           dob="1985-03-15", is_ckg=True):
    return {
        "api_version": 1,
        "visit": {"id": visit_id, "date": day, "room": {"id": 1, "name": room}},
        "patient": {"id": 7, "name": name, "date_of_birth": dob,
                    "identity": {"type": "NIK" if nik else None, "number": nik}},
        "ckg": {"is_ckg": is_ckg, "basis": "poli_name", "year": int(day[:4]), "records": []},
    }


class FakeClient:
    """Stands in for MedisyClient: one day -> list of visits; get_bundles answers from a dict of bundles."""

    def __init__(self, days, bundles, missing=()):
        self.days, self.bundles, self.missing = days, bundles, set(missing)
        self.bundle_calls = []
        self.listed = []
        self.ckg_only_calls = []

    def list_visits(self, day, *, ckg_only=True):
        self.listed.append(day)
        self.ckg_only_calls.append(ckg_only)
        return [{"visit_id": b["visit"]["id"], "nik": b["patient"]["identity"]["number"]} for b in self.days.get(day, [])]

    def get_bundles(self, ids):
        self.bundle_calls.append(list(ids))
        items = [self.bundles[i] for i in ids if i not in self.missing]
        return BundleBatch(items=items, missing=[i for i in ids if i in self.missing])

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class FakeRedis:
    def __init__(self, cancel_after_gets=None):
        self.store, self.lists, self.published = {}, {}, []
        self.gets = 0
        self.cancel_after_gets = cancel_after_gets

    def get(self, key):
        self.gets += 1
        if self.cancel_after_gets is not None and self.gets > self.cancel_after_gets:
            return "1"
        return self.store.get(key)

    def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)

    def ltrim(self, *_a):
        pass

    def expire(self, *_a):
        pass

    def publish(self, chan, msg):
        self.published.append(msg)


# ---------------------------------------------------------------------------------------------- adapter


def test_extract_patients_builds_rows_and_adds_meta_without_touching_the_bundle():
    b = bundle(11)
    rows, skipped, count = adapter.extract_patients([b], "2026-10-05T10:00:00+07:00")
    assert count == 1 and skipped == []
    nik, nama, blob, d = rows[0]
    assert (nik, nama, d) == ("3201000000000001", "PASIEN FIKTIF", "2026-09-02")
    assert blob["_meta"] == {"source": "medisy", "fetched_at": "2026-10-05T10:00:00+07:00"}
    assert {k: v for k, v in blob.items() if k != "_meta"} == b          # the bundle itself is stored as-is
    assert "_meta" not in b                                                # ...and the input was not mutated


def test_visit_without_a_nik_is_skipped_with_the_usual_reason():
    rows, skipped, count = adapter.extract_patients([bundle(5, nik=None), bundle(6)], "t")
    assert count == 2 and len(rows) == 1
    assert skipped == [{"source_id": "5", "reason": "missing NIK"}]


def test_visit_with_a_shared_nik_is_skipped_so_two_people_never_overwrite_each_other():
    shared = bundle(7, nik="00")
    shared["patient"]["identity"]["shared"] = True
    unique = bundle(8)
    unique["patient"]["identity"]["shared"] = False
    old_api = bundle(9)                                    # an API version without the flag behaves as before
    rows, skipped, count = adapter.extract_patients([shared, unique, old_api], "t")
    assert count == 3 and [r[0] for r in rows] == [unique["patient"]["identity"]["number"]] * 2
    assert skipped == [{"source_id": "7", "reason": "shared NIK (more than one person)"}]


def test_is_medisy_blob_tells_a_bundle_from_a_legacy_epus_blob():
    assert adapter.is_medisy_blob(bundle(1))
    assert not adapter.is_medisy_blob({"data_pasien": {"NIK": "1"}, "tabs": {}})
    assert not adapter.is_medisy_blob(None) and not adapter.is_medisy_blob({"api_version": 1})


def test_fetch_day_bundles_reads_in_chunks_of_50_in_id_order():
    ids = list(range(1000, 1120))                      # 120 visits -> 50 + 50 + 20
    bundles = {i: bundle(i) for i in ids}
    client = FakeClient({date(2026, 9, 2): [bundles[i] for i in reversed(ids)]}, bundles)
    got = adapter.fetch_day_bundles(client, date(2026, 9, 2))
    assert [len(c) for c in client.bundle_calls] == [50, 50, 20]
    assert [b["visit"]["id"] for b in got] == ids       # ascending id => the latest visit wins an upsert collision


def test_fetch_day_bundles_filters_by_nik_before_downloading_anything():
    a, b = bundle(1, nik="111"), bundle(2, nik="222")
    client = FakeClient({date(2026, 9, 2): [a, b]}, {1: a, 2: b})
    got = adapter.fetch_day_bundles(client, date(2026, 9, 2), niks={"222"})
    assert client.bundle_calls == [[2]] and [x["visit"]["id"] for x in got] == [2]


def test_fetch_day_bundles_stops_when_cancelled_and_logs_no_identifiers():
    ids = list(range(1, 121))
    bundles = {i: bundle(i, nik="3201999999999999", name="Rahasia Banget") for i in ids}
    client = FakeClient({date(2026, 9, 2): list(bundles.values())}, bundles)
    calls, lines = [], []

    def should_cancel():
        calls.append(1)
        return len(calls) > 1                      # allow the first chunk, then cancel

    got = adapter.fetch_day_bundles(client, date(2026, 9, 2), should_cancel=should_cancel, on_log=lines.append)
    assert len(client.bundle_calls) == 1 and len(got) == 50
    assert lines and not any("3201999999999999" in line or "Rahasia" in line for line in lines)


def test_visits_that_vanish_between_list_and_read_are_not_an_error():
    a, b = bundle(1), bundle(2)
    client = FakeClient({date(2026, 9, 2): [a, b]}, {1: a, 2: b}, missing={2})
    lines = []
    got = adapter.fetch_day_bundles(client, date(2026, 9, 2), on_log=lines.append)
    assert [x["visit"]["id"] for x in got] == [1] and any("vanished" in line for line in lines)


# ---------------------------------------------------------------------------------------------- blob-shape helpers


def test_tandai_ckg_reads_medisy_is_ckg_and_still_reads_legacy_sudah_ckg():
    assert _extract_tandai_ckg(bundle(1, is_ckg=True)) is True
    assert _extract_tandai_ckg(bundle(1, is_ckg=False)) is False
    assert _extract_tandai_ckg({"ckg": {"sudah_ckg": True}}) is True
    assert _extract_tandai_ckg({"ckg": {}}) is None and _extract_tandai_ckg({}) is None


def test_ruangan_is_the_medisy_room_name_capped_to_the_column_width():
    assert _extract_epus_ruangan(bundle(1)) == "KLASTER 3 R DEWASA - CKG"
    assert len(_extract_epus_ruangan(bundle(1, room="X" * 200))) == 64
    assert _extract_epus_ruangan({"data_pasien": {"Poli/Ruangan": " POLI UMUM "}}) == "POLI UMUM"


def test_birth_date_from_a_medisy_bundle():
    assert birth_date_from_medisy(bundle(1, dob="1985-03-15")) == date(1985, 3, 15)
    assert birth_date_from_medisy(bundle(1, dob=None)) is None
    assert birth_date_from_medisy(bundle(1, dob="0000-00-00")) is None
    assert birth_date_for_patient(bundle(1, dob="1985-03-15"), None) == date(1985, 3, 15)


# ---------------------------------------------------------------------------------------------- the job runner


@pytest.fixture
def env(monkeypatch):
    """Wire run_medisy_scrape to fakes; returns a namespace to inspect what happened."""
    e = SimpleNamespace(upserts=[], failed=[], success=[], commits=0, client=None)
    db = MagicMock()
    db.commit.side_effect = lambda: setattr(e, "commits", e.commits + 1)
    e.db = db
    e.rc = FakeRedis()

    def upsert(_db, pk, kind, nik, nama, blob, d):
        e.upserts.append((kind, nik, nama, blob, d))
        return "inserted" if len(e.upserts) % 2 else "updated"

    monkeypatch.setattr(ms.patient_crud, "upsert_from_scrape", upsert)
    monkeypatch.setattr(ms.scrape_job_crud, "mark_failed", lambda db, job, msg, now, **k: e.failed.append(msg))
    monkeypatch.setattr(ms.scrape_job_crud, "mark_success", lambda *a, **k: e.success.append((a[2:5], k.get("notes"))))
    monkeypatch.setattr(ms, "MedisyClient", lambda host, token, **k: e.client)
    return e


def run(env, *, job=None, pk=None, creds=None, nik=None):
    job = job or SimpleNamespace(puskesmas_id="p1", date_filter="2026-09-02", date_filters=None, target_niks=None)
    pk = pk or SimpleNamespace(epus_url="clinic.medisy.id")
    ms.run_medisy_scrape(env.db, env.rc, job, pk, {"token": "t" * 40} if creds is None else creds, nik,
                         cancel_key="c", log_key="l", chan="ch")


def test_a_single_day_is_fetched_upserted_and_reported(env):
    b1, b2 = bundle(1, nik="111"), bundle(2, nik="222")
    env.client = FakeClient({date(2026, 9, 2): [b1, b2]}, {1: b1, 2: b2})
    run(env)
    assert [u[1] for u in env.upserts] == ["111", "222"]
    assert all(u[0] == ScrapeKind.EPUS and u[4] == "2026-09-02" and u[3]["_meta"]["source"] == "medisy" for u in env.upserts)
    assert env.success == [((2, 1, 1), None)]          # scraped, inserted, updated
    assert env.commits == 1 and env.failed == []
    assert env.rc.published[-1] == "__done__"
    assert any("saved 2 patient" in line for line in env.rc.lists["l"])


def test_multi_day_job_commits_per_day(env):
    days = {date(2026, 9, 1): [bundle(1, day="2026-09-01")], date(2026, 9, 2): [bundle(2, day="2026-09-02")]}
    env.client = FakeClient(days, {1: days[date(2026, 9, 1)][0], 2: days[date(2026, 9, 2)][0]})
    run(env, job=SimpleNamespace(puskesmas_id="p1", date_filter=None, date_filters=json.dumps(["2026-09-01", "2026-09-02"]), target_niks=None))
    assert env.client.listed == [date(2026, 9, 1), date(2026, 9, 2)]
    assert env.commits == 2 and env.success[0][0][0] == 2


def test_per_nik_job_reads_only_that_patient(env):
    a, b = bundle(1, nik="111"), bundle(2, nik="222")
    env.client = FakeClient({date(2026, 9, 2): [a, b]}, {1: a, 2: b})
    run(env, nik="222")
    assert [u[1] for u in env.upserts] == ["222"] and env.client.bundle_calls == [[2]]


def test_target_niks_filter_applies_to_a_multi_patient_job(env):
    a, b, c = bundle(1, nik="111"), bundle(2, nik="222"), bundle(3, nik="333")
    env.client = FakeClient({date(2026, 9, 2): [a, b, c]}, {1: a, 2: b, 3: c})
    run(env, job=SimpleNamespace(puskesmas_id="p1", date_filter="2026-09-02", date_filters=None, target_niks=json.dumps(["111", "333"])))
    assert sorted(u[1] for u in env.upserts) == ["111", "333"]


def test_visits_without_a_nik_end_up_in_the_job_notes(env):
    env.client = FakeClient({date(2026, 9, 2): [bundle(9, nik=None), bundle(1)]}, {9: bundle(9, nik=None), 1: bundle(1)})
    run(env)
    (counts, notes), = env.success
    assert counts[0] == 2 and "source_id=9 reason=missing NIK" in notes


@pytest.mark.parametrize("creds,pk,fragment", [
    ({"email": "a@b.c", "password": "x"}, None, "token"),           # an old EPUS login stored in the slot
    ({}, None, "token"),
    (None, SimpleNamespace(epus_url=None), "URL"),
])
def test_missing_token_or_url_fails_the_job_cleanly(env, creds, pk, fragment):
    env.client = FakeClient({}, {})
    run(env, creds=creds, pk=pk)
    assert len(env.failed) == 1 and fragment in env.failed[0]
    assert env.upserts == [] and env.rc.published[-1] == "__failed__"


@pytest.mark.parametrize("job", [
    SimpleNamespace(puskesmas_id="p", date_filter=None, date_filters=None, target_niks=None),
    SimpleNamespace(puskesmas_id="p", date_filter=None, date_filters="[]", target_niks=None),
    SimpleNamespace(puskesmas_id="p", date_filter="02-09-2026", date_filters=None, target_niks=None),
    SimpleNamespace(puskesmas_id="p", date_filter="2026-09-02", date_filters=None, target_niks="{not json"),
])
def test_bad_job_input_fails_before_any_request(env, job):
    env.client = FakeClient({}, {})
    run(env, job=job)
    assert len(env.failed) == 1 and env.client.listed == []


def test_a_medisy_error_fails_the_job_with_a_safe_message(env):
    class Boom(FakeClient):
        def list_visits(self, day, *, ckg_only=True):
            raise MedisyAuthError("Medisy rejected the token (401)")
    env.client = Boom({}, {})
    run(env, creds={"token": "SECRET-" + "t" * 40})
    assert env.failed == ["Medisy: Medisy rejected the token (401)"]
    assert "SECRET" not in env.failed[0] and not any("SECRET" in line for line in env.rc.lists.get("l", []))
    assert env.rc.published[-1] == "__failed__"


def test_a_cancel_between_days_keeps_the_finished_days_and_does_not_report_success(env):
    d1, d2 = bundle(1, day="2026-09-01"), bundle(2, day="2026-09-02")
    env.client = FakeClient({date(2026, 9, 1): [d1], date(2026, 9, 2): [d2]}, {1: d1, 2: d2})
    env.rc = FakeRedis(cancel_after_gets=3)            # polls: before day 1, inside day 1, after day 1 -> then "1"
    run(env, job=SimpleNamespace(puskesmas_id="p1", date_filter=None, date_filters=json.dumps(["2026-09-01", "2026-09-02"]), target_niks=None))
    assert [u[4] for u in env.upserts] == ["2026-09-01"] and env.commits == 1
    assert env.success == [] and env.failed == []
    assert env.rc.published[-1] == "__cancelled__"


def test_an_unexpected_db_error_rolls_back_and_propagates_to_the_task_handler(env):
    env.client = FakeClient({date(2026, 9, 2): [bundle(1)]}, {1: bundle(1)})
    env.db.commit.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        run(env)
    env.db.rollback.assert_called_once()


# ---------------------------------------------------------------------------------------------- what is gone


def test_the_browser_scrape_path_no_longer_knows_epus():
    with pytest.raises(ValueError):
        scrape_task._build_config(ScrapeKind.EPUS, {}, "2026-09-02", "https://clinic.medisy.id", MagicMock())
    with pytest.raises(ValueError):
        scrape_task._extract_patients(ScrapeKind.EPUS, {"patients": []})
    assert not hasattr(scrape_task, "_iso_to_ddmmyyyy")


def test_every_visit_of_the_day_is_fetched_not_only_ckg_ones():
    client = FakeClient({date(2026, 9, 2): [bundle(1), bundle(2, is_ckg=False)]}, {1: bundle(1), 2: bundle(2, is_ckg=False)})
    got = adapter.fetch_day_bundles(client, date(2026, 9, 2))
    assert client.ckg_only_calls == [False] and [b["visit"]["id"] for b in got] == [1, 2]
