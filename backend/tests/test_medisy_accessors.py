"""Medisy accessors and the registry / dashboard extractors that route a Medisy bundle through them.

Hand-built bundles only (no real patient data). The EPUS branch of every extractor must keep working until the last EPUS row is gone.
"""
from decimal import Decimal

from app.api.routes import gdp_report, hipertensi_report
from app.services import dm_registry_scan, hipertensi_registry_scan, lipid_registry_scan, medisy_accessors as acc
from app.services import obesitas_registry_scan


def bundle(*, vitals=None, diagnoses=None, hist_dx=None, lab=None, prescriptions=None, screenings=None, general=None):
    return {
        "api_version": 1,
        "visit": {"id": 1, "date": "2026-09-02", "room": {"id": 1, "name": "CKG"}},
        "patient": {"id": 7, "name": " PASIEN FIKTIF ", "gender": 2, "date_of_birth": "1970-01-31", "phone": "0812",
                    "age": {"years": 56}, "address": {"text": "JL  CONTOH\n 1"}},
        "anamnesis": {"vitals": {**{"systole": None, "diastole": None, "weight_kg": None, "height_cm": None,
                                    "gds": None, "gdp": None, "hba1c": None}, **(vitals or {})}},
        "history": {"diagnoses": hist_dx or []},
        "diagnoses": diagnoses or [],
        "lab": lab or [],
        "prescriptions": prescriptions or [],
        "screenings": screenings or [],
        "physical_exam": {"general": general or {}},
    }


def lab(test, result):
    return {"test": test, "parent": "X", "result": result}


def scr(key, **cols):
    return {"key": key, "performed_at": "2026-09-02T10:00:00+07:00",
            "answers": [{"question_code": c, "value": v} for c, v in cols.items()]}


def test_blood_pressure_prefers_vitals_then_the_screening_row_and_treats_zero_as_missing():
    assert acc.blood_pressure(bundle(vitals={"systole": 150, "diastole": 95})) == (150, 95)
    assert acc.blood_pressure(bundle(screenings=[scr("hipertensi", sistole="130", diastole="85")])) == (130, 85)
    assert acc.blood_pressure(bundle(vitals={"systole": 0, "diastole": 0})) == (None, None)


def test_hypertension_and_diabetes_records_come_from_icd_or_a_trusted_history_answer():
    assert acc.has_hypertension_record(bundle(diagnoses=[{"icd10": "I10"}]))
    assert acc.has_hypertension_record(bundle(hist_dx=[{"icd10": "i11.9"}]))
    assert not acc.has_hypertension_record(bundle(diagnoses=[{"icd10": "J00"}]))
    assert acc.has_diabetes_record(bundle(diagnoses=[{"icd10": "E11.9"}]))
    ya = scr("hipertensi", question1_anamnesis="Ya", **{f"question{i}_anamnesis": "Tidak" for i in range(2, 9)})
    assert acc.has_hypertension_record(bundle(screenings=[ya]))
    # R-UNIFORM: a "check to all" row is not evidence
    all_ya = scr("hipertensi", **{f"question{i}_anamnesis": "Ya" for i in range(1, 9)})
    assert not acc.has_hypertension_record(bundle(screenings=[all_ya]))


def test_drug_names_are_ordered_deduplicated_and_include_compound_ingredients():
    rx = [{"drug": "Amlodipin 5mg"}, {"drug": None, "items": [{"drug": "Captopril"}, {"drug": None}]}, {"drug": "Amlodipin 5mg"}]
    assert acc.drug_names(bundle(prescriptions=rx)) == ["Amlodipin 5mg", "Captopril"]


def test_glucose_vitals_win_and_the_lab_fills_gaps_with_the_last_result():
    b = bundle(vitals={"gds": 140}, lab=[lab("Glukosa Puasa", "99"), lab("Glukosa Puasa", "105"), lab("HbA1c", "6,5")])
    assert acc.glucose(b) == {"gds1": 140, "gds2": None, "gdp": 105, "gd2pp": None, "hba1c": 6.5}
    assert acc.glucose(bundle(vitals={"gdp": 90}, lab=[lab("Glukosa Puasa", "105")]))["gdp"] == 90
    assert acc.lab_gdp(bundle(vitals={"gdp": 90})) is None and acc.vitals_gdp(bundle(vitals={"gdp": 90})) == 90


def test_lipid_reads_each_analyte_from_the_lab_table():
    b = bundle(lab=[lab("KOLESTEROL TOTAL", "200"), lab("HDL CHOLESTEROL", "45"), lab("LDL CHOLESTEROL", "130"),
                    lab("TRIGLISERIDA", "150"), lab("Hemoglobin", "12")])
    assert acc.lipid(b) == {"kol_total": 200, "hdl": 45, "ldl": 130, "trigliserida": 150}
    assert acc.lipid(bundle()) == {"kol_total": None, "hdl": None, "ldl": None, "trigliserida": None}


def test_identity_block_matches_the_registry_shape():
    assert acc.identity(bundle()) == {"nama": "PASIEN FIKTIF", "jenis_kelamin": "Perempuan", "tanggal_lahir": "1970-01-31",
                                      "no_tlp": "0812", "alamat": "JL CONTOH 1"}


def test_tertatalaksana_is_a_proxy_on_chronic_drugs_and_an_education_note():
    assert acc.tertatalaksana(bundle(prescriptions=[{"drug": "Amlodipin 5 mg"}], general={"edukasi": "diet"})) == (True, True)
    assert acc.tertatalaksana(bundle(prescriptions=[{"drug": "Paracetamol"}])) == (False, False)


# ── the extractors route Medisy bundles here, and leave the EPUS shape alone ──


def test_registry_scans_read_a_medisy_bundle():
    b = bundle(vitals={"systole": 150, "diastole": 95, "weight_kg": 70, "height_cm": 160, "gdp": 130},
               diagnoses=[{"icd10": "I10"}], prescriptions=[{"drug": "Amlodipin 5 mg"}, {"drug": "Paracetamol"}],
               lab=[lab("KOLESTEROL TOTAL", "210")])
    assert hipertensi_registry_scan._extract_td1(b) == (150.0, 95.0)
    assert hipertensi_registry_scan._riwayat_epus_hit(b) is True
    assert hipertensi_registry_scan._extract_obat(b) == ["Amlodipin 5 mg"]
    assert hipertensi_registry_scan._parse_birthdate(b) == "1970-01-31"
    assert hipertensi_registry_scan._extract_identitas(b)["nama"] == "PASIEN FIKTIF"
    assert dm_registry_scan._extract_glucose_epus(b)["gdp"] == 130.0
    assert dm_registry_scan._riwayat_epus_hit(b) is False
    assert lipid_registry_scan._extract_lipid_epus(b)["kol_total"] == 210.0
    antro = obesitas_registry_scan._extract_antro_epus(b)
    assert (antro["bb"], antro["tb"]) == (70.0, 160.0)


def test_dashboard_extractors_read_a_medisy_bundle():
    b = bundle(vitals={"systole": 150, "diastole": 95, "gdp": 88}, lab=[lab("Glukosa Puasa", "101")],
               prescriptions=[{"drug": "Metformin 500"}], general={"edukasi": "x"})
    assert hipertensi_report._extract_bp(b) == (Decimal("150"), Decimal("95"))
    assert gdp_report._extract_lab_gdp(b) == Decimal("101")
    assert gdp_report._extract_ptm_gdp(b) == Decimal("88")
    assert gdp_report._extract_tertatalaksana(b) == (True, True)


def test_the_epus_shape_still_takes_the_legacy_path():
    epus = {"data_pasien": {"Nama Pasien": "X"},
            "tabs": {"Anamnesa": {"fields": {"Periksa Fisik": {"Sistole": "140", "Diastole": "90"}}}}}
    assert hipertensi_registry_scan._extract_td1(epus) == (140.0, 90.0)
    assert hipertensi_report._extract_bp(epus) == (Decimal("140"), Decimal("90"))


# ── newborn registry ──


def _baby(**kw):
    b = bundle(**kw)
    b["patient"]["age"] = {"years": 0, "months": 0, "days": 5}
    b["patient"]["name"] = "BAYI NYONYA X"
    return b


def test_bayi_registry_reads_a_medisy_newborn():
    from app.services import bayi_registry_scan as bayi

    b = _baby(diagnoses=[{"icd10": "P59", "name": "Neonatal jaundice"}, {"icd10": "P59", "name": "Neonatal jaundice"}])
    b["programs"] = {
        "kia": {"pjb": [{"id": 1, "tanggal_pjb": "2026-09-01", "saturasi_tangan": "98", "saturasi_kaki": "99",
                         "kesimpulan": "Lolos", "tindakan": "Tidak Rujuk"},
                        {"id": 2, "tanggal_pjb": "2026-09-02", "saturasi_tangan": "90", "saturasi_kaki": "85",
                         "kesimpulan": "Gagal", "tindakan": "Rujuk"}]},
        "child": {"mtbs": [{"kode_jenis": "Imunisasi", "jenis": "IMUNISASI", "klasifikasi": "HB 0"},
                           {"kode_jenis": "Ikterus", "jenis": "IKTERUS", "klasifikasi": "Ikterus Berat"}]},
    }
    assert bayi._is_bayi(b) is True
    assert bayi._extract_identitas(b)["tanggal_lahir"] == "1970-01-31"
    assert bayi._extract_diagnosis(b) == "Neonatal jaundice"
    pjb = bayi._extract_pjb(b)
    assert (pjb["saturasi_tangan_kanan"], pjb["saturasi_kaki"], pjb["interpretasi"]) == ("90", "85", "Gagal")
    assert bayi._pjb_qualifies(pjb) is True                       # "Gagal" is a positive screen
    assert bayi._extract_ikterus_klasifikasi(b) == ("Ikterus berat", "EPUS")
    assert bayi._extract_rujuk_eksternal(b) == ""                                  # no referral on this visit
    b["visit"]["referral"] = {"referred": True, "type": "EXTERNAL", "destination": "RS CONTOH"}
    assert bayi._extract_rujuk_eksternal(b) == "RS CONTOH"
    assert bayi._extract_pjb(b)["rujuk_eksternal"] == "RS CONTOH"
    b["visit"]["referral"] = {"referred": True, "type": "INTERNAL", "destination": None}
    assert bayi._extract_rujuk_eksternal(b) == ""


def test_bayi_registry_ignores_an_adult_and_a_lolos_screen():
    from app.services import bayi_registry_scan as bayi

    assert bayi._is_bayi(bundle()) is False
    b = _baby()
    b["programs"] = {"kia": {"pjb": [{"id": 1, "tanggal_pjb": "2026-09-01", "saturasi_tangan": "98", "kesimpulan": "Lolos"}]}}
    assert bayi._pjb_qualifies(bayi._extract_pjb(b)) is False
    assert bayi._extract_pjb(_baby()) is None
    assert bayi._extract_ikterus_klasifikasi(_baby()) == ("", "")
