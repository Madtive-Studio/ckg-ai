"""Tests for the ASIK create-patient helpers (app/tasks/create_patient.py).

These guard the parts where a SILENT wrong answer would register wrong data into a
real citizen's ASIK record:
  - identity derived from the NIK (Dukcapil validates the NIK's own DDMMYY, so a
    disagreeing DB birth_date must never win — the documented ARYANATA class);
  - the "never guess a domicile" skip (no configured alamat → SKIP, not a blank/wrong
    address).
The create_batch orchestration itself is straight branching glue over these + the
scraper subprocess, so it is not unit-tested here.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.tasks.create_patient import (
    _build_step2,
    _derive_from_nik,
    _title_case_name,
    _wali_block_reason,
    _whatsapp_from_epus,
)


# --- _derive_from_nik: DOB + gender come from the NIK, NOT patient.birth_date ---
def test_derive_from_nik_male_recent_century():
    # digits 7-12 = 240699 → 24 Jun 1999, male (day <= 40). The ARYANATA class: a DB
    # birth_date that disagrees with the NIK must NOT win — Dukcapil checks the NIK.
    dob, gender = _derive_from_nik("1301112406990003")
    assert dob == date(1999, 6, 24)
    assert gender == "Laki-laki"


def test_derive_from_nik_female_day_plus_40():
    # digits 7-12 = 430303 → day 43 > 40 ⇒ female, real day 3 → 3 Mar 2003 (MARIANA,
    # the live-verified registration).
    dob, gender = _derive_from_nik("3275044303030016")
    assert dob == date(2003, 3, 3)
    assert gender == "Perempuan"


def test_derive_from_nik_century_prefers_recent_past():
    # yy=85 → 1985 (a 2085 birth date is in the future ⇒ rejected).
    dob, _ = _derive_from_nik("3275041505850001")
    assert dob == date(1985, 5, 15)


def test_derive_from_nik_rejects_short():
    with pytest.raises(ValueError):
        _derive_from_nik("12345")


# --- _build_step2: never guess a domicile ---
_ALAMAT_CFG = {
    "provinsi": {"name": "Jawa Barat", "code": "32"},
    "kota": {"name": "Kota Bekasi", "code": "3275"},
    "kecamatan": {"name": "Bekasi Selatan", "code": "327504"},
    "kelurahan": {"name": "Pekayonjaya", "code": "3275041003"},
}


def test_build_step2_skips_when_no_default_alamat():
    # No configured alamat ⇒ None ⇒ caller SKIPs (we never fabricate an address).
    pk = SimpleNamespace(asik_default_alamat=None)
    assert _build_step2(None, {"data_pasien": {"Alamat": "JL X"}}, pk) is None


def test_build_step2_uses_cfg_names_and_epus_detail():
    pk = SimpleNamespace(asik_default_alamat=_ALAMAT_CFG)
    epus = {"data_pasien": {
        "Alamat": "JL. KEMANDORAN  RT 008\n RW 022",
        "Status Perkawinan": None,
    }}
    s = _build_step2(None, epus, pk)
    assert s["pekerjaan"] == "Lainnya"
    assert s["status_pernikahan"] == "Belum Menikah"
    assert s["disabilitas"] == "Tidak memiliki disabilitas"
    assert s["alamat"] == {
        "provinsi": "Jawa Barat",
        "kota": "Kota Bekasi",
        "kecamatan": "Bekasi Selatan",
        "kelurahan": "Pekayonjaya",
    }
    # ePus free-text address → Detail Alamat, whitespace-collapsed.
    assert s["detail_alamat"] == "JL. KEMANDORAN RT 008 RW 022"


# --- _whatsapp_from_epus: a fabricated number must be flagged, real ones normalized ---
def test_whatsapp_normalizes_leading_zero():
    wa, used_default = _whatsapp_from_epus(
        {"data_pasien": {"No Telp / HP": "081319373789"}}
    )
    assert wa == "81319373789"
    assert used_default is False


def test_whatsapp_falls_back_and_flags_default():
    wa, used_default = _whatsapp_from_epus({"data_pasien": {"No Telp / HP": "-"}})
    assert used_default is True
    assert wa.startswith("8")


def test_title_case_name():
    assert _title_case_name("SANTI ANI") == "Santi Ani"


# --- _wali_block_reason: the own-NIK / age create gate (a wrong pass mis-assigns a
# real citizen's ASIK identity — the fatal case the wali flow exists to prevent) ---
_EXAM = date(2026, 8, 31)


def test_wali_block_own_nik_school_age_ok():
    # NIK DDMMYY 150518 → 15 May 2018 (age 8 at exam), own NIK → creatable via own NIK.
    assert _wali_block_reason("3275041505180001", date(2018, 5, 15), _EXAM) is None


def test_wali_block_under_6_needs_wali_even_with_own_nik():
    # 10 Jan 2022 → age 4 at exam. Own NIK, but ASIK mandates wali for <6 (live-verified).
    r = _wali_block_reason("3275041001220001", date(2022, 1, 10), _EXAM)
    assert r is not None and "under 6" in r


def test_wali_block_minor_recorded_under_guardian_nik():
    # A child (birth_date 15 May 2018, age 8) recorded under an ADULT's NIK (24 Jun 1999)
    # → NIK's DOB ≠ birth_date → guardian's NIK → blocked (registering by it mis-assigns).
    r = _wali_block_reason("1301112406990003", date(2018, 5, 15), _EXAM)
    assert r is not None and "guardian" in r


def test_wali_block_adult_mismatch_not_gated():
    # An adult (age 36) whose DB birth_date disagrees with the NIK is NOT own-NIK-gated —
    # only minors are; an adult's NIK is their own and registration derives DOB from it.
    assert _wali_block_reason("3275041505850001", date(1990, 1, 1), _EXAM) is None


def test_wali_block_missing_birth_date():
    assert _wali_block_reason("3275041505180001", None, _EXAM) is not None


# --- the patient's own domicile (Medisy) is the source; the puskesmas default is only the fallback ---
def _medisy(address):
    return {"api_version": 1, "visit": {"id": 1, "date": "2026-02-03"},
            "patient": {"name": "PASIEN FIKTIF", "address": address}}


_FULL = {"province": " Jawa Barat ", "city": "KAB.  SUKABUMI", "district": "Pelabuhanratu", "village": "Citarik", "text": "JL X"}


def test_clinic_domicile_needs_all_four_levels_and_collapses_whitespace():
    from app.services.clinic_source import clinic_domicile

    assert clinic_domicile(_medisy(_FULL)) == {
        "provinsi": "Jawa Barat", "kota": "KAB. SUKABUMI", "kecamatan": "Pelabuhanratu", "kelurahan": "Citarik"}
    assert clinic_domicile(_medisy({**_FULL, "village": None})) is None
    assert clinic_domicile(_medisy({**_FULL, "district": "  "})) is None
    assert clinic_domicile({"data_pasien": {"Alamat": "JL X"}}) is None                    # a legacy ePuskesmas blob has no levels


def test_step2_prefers_the_patients_own_domicile_over_the_puskesmas_default():
    pk = SimpleNamespace(asik_default_alamat=_ALAMAT_CFG)
    s = _build_step2(None, _medisy(_FULL), pk)
    assert s["alamat"]["kota"] == "KAB. SUKABUMI" and s["alamat"]["kelurahan"] == "Citarik"
    assert s["detail_alamat"] == "JL X"


def test_step2_works_without_any_puskesmas_default_when_the_patient_has_a_domicile():
    s = _build_step2(None, _medisy(_FULL), SimpleNamespace(asik_default_alamat=None))
    assert s is not None and s["alamat"]["provinsi"] == "Jawa Barat"


def test_step2_falls_back_to_the_default_for_an_incomplete_domicile_and_skips_when_there_is_neither():
    incomplete = _medisy({**_FULL, "village": ""})
    assert _build_step2(None, incomplete, SimpleNamespace(asik_default_alamat=_ALAMAT_CFG))["alamat"]["kelurahan"] == "Pekayonjaya"
    assert _build_step2(None, incomplete, SimpleNamespace(asik_default_alamat=None)) is None


def test_place_name_variants_are_whole_name_spellings_only():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scrapers" / "asik_sync"))
    from register import _name_variants

    assert _name_variants("KAB. SUKABUMI") == ["KAB. SUKABUMI", "KABUPATEN SUKABUMI"]
    assert _name_variants("Kabupaten Sukabumi") == ["Kabupaten Sukabumi", "KAB. Sukabumi"]
    assert _name_variants("KOTA BOGOR") == ["KOTA BOGOR"]
    assert _name_variants("Jawa  Barat") == ["Jawa Barat"]


def test_closest_option_accepts_only_a_very_close_unambiguous_spelling():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scrapers" / "asik_sync"))
    from register import _closest_option, _norm_place

    assert _norm_place("Pelabuhan-ratu") == _norm_place("pelabuhan ratu") == "PELABUHANRATU"
    kec = ["CIEMAS", "CIKAKAK", "PALABUHANRATU", "SIMPENAN", "CISOLOK"]
    assert _closest_option("Pelabuhanratu", kec) == "PALABUHANRATU"                       # one letter off, unique
    assert _closest_option("Simpenan", kec) == "SIMPENAN"
    assert _closest_option("Cibadak", kec) is None                                        # nothing close: refuse, never guess
    assert _closest_option("Citarik", ["CITARIK", "CITARIKA"]) == "CITARIK"               # an identical spelling wins
    assert _closest_option("Citarik", ["CITARIKI", "CITARIKU"]) is None                   # two equally close options: ambiguous
    assert _closest_option("Pelabuhanratu", []) is None
