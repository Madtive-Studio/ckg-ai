"""The sync robot's NIK-search gate with ASIK's encoded list answer (fake page / interceptor, fictional NIKs).

The gate must keep three distinct outcomes — rows, a genuinely empty result, and "cannot verify" — because the robot skips a tab
on the last one and must never click Mulai for a patient it could not identify.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SCRAPER_SESSION_DIR", "/tmp/_asik_sync_test_session")
ROOT = Path(__file__).resolve().parents[2] / "scrapers"
sys.path.insert(0, str(ROOT / "asik"))
sys.path.insert(0, str(ROOT / "asik_sync"))

import sync  # noqa: E402

LIST_URL = "https://asik.example/api/pkg/ssi/list-kunjungan-umum"


class FakePage:
    def __init__(self, captured=None):
        self.captured = captured

    def evaluate(self, script):
        return self.captured if script == "window.__ckgList" else None

    def wait_for_timeout(self, ms):
        pass


def row(nik, date="2026-09-15"):
    return {"reg_id": "R", "faskes_code": "F", "register_date": date, "ticket_number": "T", "patient": {"nik": nik, "fullname": "FIKTIF"}}


def interceptor(*entries):
    return SimpleNamespace(all_responses=list(entries))


ANSWERED = {"url": LIST_URL, "status": 200, "body": {"_d": "encoded"}}


def test_decoded_rows_become_search_rows_with_nik_and_screening_date():
    page = FakePage({"rows": [row("3201000000000001")]})
    rows = sync._wait_search_rows(page, interceptor(ANSWERED), 0)
    assert rows == [{"nik": "3201000000000001", "screening_date": "2026-09-15", "name": "FIKTIF"}]


def test_foreign_rows_are_returned_so_the_caller_can_refuse_the_tab():
    page = FakePage({"rows": [row("3201000000000001"), row("3201000000000002")]})
    niks = [r["nik"] for r in sync._wait_search_rows(page, interceptor(ANSWERED), 0)]
    assert niks == ["3201000000000001", "3201000000000002"]          # the caller compares each with the searched NIK


def test_an_answered_search_with_no_patient_rows_is_an_empty_result_not_unknown():
    assert sync._wait_search_rows(FakePage(None), interceptor(ANSWERED), 0) == []


def test_no_answer_at_all_is_cannot_verify():
    assert sync._wait_search_rows(FakePage(None), interceptor(), 0, timeout_ms=300) is None
    other = {"url": "https://asik.example/api/other", "status": 200, "body": {"_d": "x"}}
    assert sync._wait_search_rows(FakePage(None), interceptor(other), 0, timeout_ms=300) is None
    failed = {"url": LIST_URL, "status": 500, "body": {}}
    assert sync._wait_search_rows(FakePage(None), interceptor(failed), 0, timeout_ms=300) is None


def test_only_responses_after_the_mark_count():
    assert sync._wait_search_rows(FakePage(None), interceptor(ANSWERED), 1, timeout_ms=300) is None


def test_the_old_specific_search_response_still_wins_when_present():
    legacy = {"url": "https://asik.example/api/pkg/specific-search/layanan-ckg", "status": 200,
              "body": {"data": [{"patient_nik": "3201000000000009", "screening_date": "2026-01-02", "patient_full_name": "LAMA"}]}}
    rows = sync._wait_search_rows(FakePage({"rows": [row("3201000000000001")]}), interceptor(legacy), 0)
    assert rows == [{"nik": "3201000000000009", "screening_date": "2026-01-02", "name": "LAMA"}]


class RerenderPage:
    """Detail page whose rows come back only after `empty_reads` enumerations (Vue still re-rendering)."""

    def __init__(self, rows, empty_reads):
        self.rows, self.empty_reads, self.reads, self.gotos = rows, empty_reads, 0, 0

    def evaluate(self, script, *a):
        self.reads += 1
        return [] if self.reads <= self.empty_reads else [dict(r) for r in self.rows]

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **kw):
        self.gotos += 1


FORM = {"kind": "nakes", "layanan": "Tekanan Darah Dewasa Lansia", "parent_layanan": "Skrining", "idx": 3, "occurrence": 0}


def test_row_found_once_the_page_finishes_rerendering(monkeypatch):
    monkeypatch.setattr(sync, "close_popups", lambda *a, **k: None)
    page = RerenderPage([FORM], empty_reads=3)
    _, row = sync._find_row_after_rerender(page, FORM, "https://asik.example/detail")
    assert row is not None and row["layanan"] == FORM["layanan"] and page.gotos == 0


def test_row_found_after_reloading_the_detail_page(monkeypatch):
    monkeypatch.setattr(sync, "close_popups", lambda *a, **k: None)
    page = RerenderPage([FORM], empty_reads=12)
    _, row = sync._find_row_after_rerender(page, FORM, "https://asik.example/detail")
    assert row is not None and page.gotos == 1


def test_row_really_gone_returns_none(monkeypatch):
    monkeypatch.setattr(sync, "close_popups", lambda *a, **k: None)
    other = dict(FORM, layanan="Pemeriksaan HIV")
    page = RerenderPage([other], empty_reads=0)
    _, row = sync._find_row_after_rerender(page, FORM, "https://asik.example/detail")
    assert row is None and page.gotos == 1


def test_initial_enumeration_waits_for_the_rows_to_render(monkeypatch):
    monkeypatch.setattr(sync, "close_popups", lambda *a, **k: None)
    page = RerenderPage([FORM, dict(FORM, layanan="Pemeriksaan HIV")], empty_reads=4)
    forms = sync._enumerate_forms_settled(page, "https://asik.example/detail")
    assert len(forms) == 2 and page.gotos == 0


def test_initial_enumeration_reloads_once_then_gives_up_empty(monkeypatch):
    monkeypatch.setattr(sync, "close_popups", lambda *a, **k: None)
    page = RerenderPage([FORM], empty_reads=10**6)
    assert sync._enumerate_forms_settled(page, "https://asik.example/detail") == [] and page.gotos == 1
