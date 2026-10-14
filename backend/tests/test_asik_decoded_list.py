"""ASIK now sends the patient list encoded and decodes it in its own page; the scraper reads what the page decoded.

Only the row conversion is tested here (a fake page, fictional rows). The browser side was probed against the live site.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SCRAPER_SESSION_DIR", "/tmp/_asik_test_session")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scrapers" / "asik"))

from helpers.browser import _DECODED_LIST_HOOK, read_decoded_list, reset_decoded_list  # noqa: E402


class FakePage:
    def __init__(self, captured):
        self.captured, self.scripts = captured, []

    def evaluate(self, script):
        self.scripts.append(script)
        return self.captured if script == "window.__ckgList" else None


ROW = {
    "reg_id": "R-1", "faskes_code": "F-1", "register_date": "2025-05-19", "ticket_number": "A001",
    "patient": {"nik": "3201000000000001", "fullname": "PASIEN FIKTIF", "birth_date": "1980-01-01", "gender": "L", "mobile_number": "0"},
    "partner_code": "P", "treatment": None,
}


def test_decoded_rows_are_converted_to_the_shape_the_scraper_already_uses():
    rows = read_decoded_list(FakePage({"rows": [ROW], "pagination": None, "at": 1}))
    assert rows == [{
        "reg_id": "R-1", "faskes_code": "F-1", "screening_date": "2025-05-19", "patient_nik": "3201000000000001",
        "patient_full_name": "PASIEN FIKTIF", "ticket_number": "A001", "raw": ROW,
    }]


def test_nothing_captured_gives_an_empty_list_and_a_missing_patient_does_not_raise():
    assert read_decoded_list(FakePage(None)) == []
    odd = {"reg_id": "R-2", "faskes_code": "F-1", "register_date": None, "patient": None}
    row = read_decoded_list(FakePage({"rows": [odd]}))[0]
    assert row["patient_nik"] is None and row["screening_date"] is None and row["reg_id"] == "R-2"


def test_reset_clears_the_captured_list_and_never_raises():
    page = FakePage(None)
    reset_decoded_list(page)
    assert page.scripts == ["window.__ckgList = null"]

    class Broken:
        def evaluate(self, script):
            raise RuntimeError("page closed")

    reset_decoded_list(Broken())
    assert read_decoded_list(Broken()) == []


def test_the_observer_only_keeps_patient_row_lists_and_decodes_nothing_itself():
    assert "JSON.parse" in _DECODED_LIST_HOOK and "reg_id" in _DECODED_LIST_HOOK
    assert "crypto" not in _DECODED_LIST_HOOK.lower() and "atob" not in _DECODED_LIST_HOOK
