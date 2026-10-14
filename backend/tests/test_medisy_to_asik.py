"""medisy_to_asik: the clinical rules, pinned with hand-built bundles (no real patient data).

Each test names the rule it protects (R-ZERO / R-UNIFORM / R-DIAG / R-NOMATCH are defined in the module docstring).
"""
import copy

import pytest

from app.services import medisy_to_asik as m
from app.services.asik_form_labels import ASIK_FORM_LABELS
from app.services.medisy_to_asik import MEDISY_BREADCRUMBS, medisy_to_asik

TD = "Tekanan Darah Dewasa Lansia"
GD = "Pemeriksaan Gula Darah Dewasa Lansia"
PPOK = "Pemeriksaan PPOK (Skrining PUMA)"


def bundle(*, gender="L", years=45, vitals=None, screenings=None, diagnoses=None, hist_dx=None, lab=None,
           programs=None, marital="SUDAH MENIKAH", nik="3201000000000001", dob="1980-05-17"):
    return {
        "api_version": 1,
        "visit": {"id": 1, "date": "2026-09-02", "room": {"id": 1, "name": "CKG"}},
        "patient": {
            "id": 7, "name": "PASIEN FIKTIF", "gender": gender, "date_of_birth": dob, "place_of_birth": "BEKASI",
            "age": None if years is None else {"years": years, "months": 3, "days": 4},
            "identity": {"type": "NIK" if nik else None, "number": nik},
            "address": {"text": "  JL. CONTOH\n NO. 1 ", "village": "X"}, "marital_status": marital,
        },
        "anamnesis": {"vitals": {"systole": None, "diastole": None, "weight_kg": None, "height_cm": None, "waist_cm": None,
                                 "gds": None, "gdp": None, **(vitals or {})}},
        "history": {"diagnoses": hist_dx or []},
        "diagnoses": diagnoses or [],
        "lab": lab or [],
        "programs": programs or {},
        "screenings": screenings or [],
    }


def scr(key, **cols):
    return {"key": key, "performed_at": "2026-09-02T10:00:00+07:00",
            "answers": [{"question_code": c, "value": v} for c, v in cols.items()]}


def dx(code):
    return {"icd10": code, "name": "x", "type": "primary"}


# ───────────────────────────── identity + gating ─────────────────────────────


def test_identity_is_formatted_for_asik():
    out = medisy_to_asik(bundle(gender="P"))["identitas_pasien"]
    assert out == {"NIK": "3201000000000001", "Nama": "PASIEN FIKTIF", "Tanggal Lahir": "17 Mei 1980",
                   "Tempat Lahir": "BEKASI", "Jenis Kelamin": "Perempuan", "Alamat Domisili": "JL. CONTOH NO. 1"}


def test_no_nik_means_no_nik_field_not_an_empty_one():
    assert "NIK" not in medisy_to_asik(bundle(nik=None))["identitas_pasien"]


@pytest.mark.parametrize("kw", [dict(gender=None), dict(years=None)])
def test_undecidable_klaster_gives_identity_only(kw):
    assert set(medisy_to_asik(bundle(**kw))) == {"identitas_pasien"}


def test_a_child_gets_the_pediatric_battery_and_never_the_adult_one():
    out = medisy_to_asik(bundle(years=8, vitals={"weight_kg": 25, "height_cm": 125, "systole": 100, "diastole": 60}))
    assert out["Gizi Anak Sekolah"] == {"Berat Badan": 25, "Tinggi Badan": 125}
    assert out["Tekanan Darah Anak dan Remaja"] == {"Tekanan Darah Sistol": 100, "Tekanan Darah Diastol": 60}
    assert TD not in out and not any(f.startswith("Demografi Dewasa") for f in out)


@pytest.mark.parametrize("years,present,absent", [
    (30, [], [PPOK, "Skrining Kanker Paru (Usia =>45 thn)", "Demografi Lansia"]),
    (40, [PPOK, "POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)"], ["Skrining Kanker Paru (Usia =>45 thn)"]),
    (45, ["Skrining Kanker Paru (Usia =>45 thn)", "Hasil Pemeriksaan - Skrining Jantung"], ["Demografi Lansia"]),
    (60, ["Demografi Lansia", "SKILAS Malnutrisi", "Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia"], ["Demografi Dewasa Laki-Laki"]),
])
def test_age_gating(years, present, absent):
    out = medisy_to_asik(bundle(years=years))
    assert all(f in out for f in present) and not any(f in out for f in absent)


def test_female_only_forms():
    f, mm = medisy_to_asik(bundle(gender="P", years=35)), medisy_to_asik(bundle(gender="L", years=35))
    assert "Pemeriksaan Calon Pengantin Perempuan" in f and "Kanker Leher Rahim" in f
    assert "Pemeriksaan Calon Pengantin Perempuan" not in mm and "Kanker Leher Rahim" not in mm
    assert any("Perempuan" in k for k in f if k.startswith("Gizi")) and any("Laki-laki" in k for k in mm if k.startswith("Gizi"))


# ───────────────────────────── vitals-driven forms ───────────────────────────


def test_vitals_fill_td_gula_gizi_and_null_vitals_stay_blank():
    out = medisy_to_asik(bundle(vitals={"systole": 130, "diastole": 85, "gds": 110, "weight_kg": 70, "height_cm": 170,
                                        "waist_cm": 88}))
    assert out[TD] == {"Tekanan Darah Sistolik": 130, "Tekanan darah diastolik": 85}
    assert out[GD] == {"Gula Darah Sewaktu (GDS) (mg/dl)": 110}          # no GDP -> no key at all
    assert out["Gizi (BB - TB - Lingkar Perut) Laki-laki"] == {
        "Berat Badan (Kg)": 70, "Pengukuran Tinggi Badan (cm)": 170, "Pengukuran Lingkar Perut": 88}


def test_the_exact_sistolik_label_beats_the_longer_ke2_label():
    assert m._q(TD, "Tekanan Darah Sistolik") == "Tekanan Darah Sistolik"
    assert m._q(TD, "Tekanan Darah Sistolik Ke-2").endswith("Ke-2")


def test_marital_status_mapping_and_pregnancy_only_turns_on():
    f = medisy_to_asik(bundle(gender="P", years=30, marital="CERAI HIDUP"))["Demografi Dewasa Perempuan"]
    assert f == {"Status Perkawinan": "Cerai Hidup"}                      # R-DIAG: no hamil record -> no "Tidak"
    hamil = {"kia": {"hamil": [{"hari_pertama_haid": "2026-01-01"}]}}
    assert medisy_to_asik(bundle(gender="P", years=30, programs=hamil))["Demografi Dewasa Perempuan"][
        "Apakah Anda sedang hamil?"] == "Ya"
    assert "Status Perkawinan" not in medisy_to_asik(bundle(marital="-"))["Demografi Dewasa Laki-Laki"]


# ───────────────────────────── R-UNIFORM / history ───────────────────────────


def ht(**kw):
    base = {f"question{i}_anamnesis": "Ya" for i in range(1, 9)}
    base.update(kw)
    return scr("hipertensi", **base)


def test_hypertension_history_is_trusted_only_when_the_row_is_not_uniform():
    mixed = medisy_to_asik(bundle(screenings=[ht(question6_anamnesis="Tidak")]))[TD]
    assert mixed["Apakah Anda pernah dinyatakan tekanan darah tinggi?"] == "Ya"
    uniform = medisy_to_asik(bundle(screenings=[ht()]))[TD]                 # all "Ya": a "check to all" row
    assert "Apakah Anda pernah dinyatakan tekanan darah tinggi?" not in uniform


def test_diabetes_history_is_question_5_and_uniform_rows_are_ignored():
    cols = {f"question{i}_anamnesis": "Tidak" for i in range(1, 13)}
    cols["question5_anamnesis"] = "Ya"
    out = medisy_to_asik(bundle(screenings=[scr("diabetes_melitus", **cols)]))[GD]
    assert out["Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?"] == "Ya"
    cols["question5_anamnesis"] = "Tidak"
    out = medisy_to_asik(bundle(screenings=[scr("diabetes_melitus", **cols)]))[GD]
    assert "Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?" not in out


# ───────────────────────────── R-ZERO: PUMA ──────────────────────────────────

PUMA_ZERO = dict(question1=0, question2=0, question3=0, question_child_3_1=0, question_child_3_average=0,
                 question_child_3_year=0, question_child_3_3=0, question4=0, question5=0, question6=0, question7=0)


def test_an_all_zero_puma_row_emits_nothing():
    assert medisy_to_asik(bundle(screenings=[scr("puma", **PUMA_ZERO)]))[PPOK] == {}


def test_a_one_is_trusted_and_zeros_become_tidak_only_in_a_row_with_activity():
    out = medisy_to_asik(bundle(screenings=[scr("puma", **{**PUMA_ZERO, "question4": 1})]))[PPOK]
    assert out["Apakah Anda pernah merasa napas pendek ketika berjalan lebih cepat pada jalan yang datar atau pada jalan yang sedikit menanjak?"] == "Ya"
    assert out["Apakah Anda biasanya batuk saat sedang tidak menderita selesma/flu?"] == "Tidak"
    assert out["Apakah anda sedang/mempunyai riwayat merokok?"] == "Tidak"      # row has activity, no smoking data


def test_puma_smoker_gets_iya_and_the_pack_year_bucket():
    out = medisy_to_asik(bundle(screenings=[scr("puma", **{**PUMA_ZERO, "question_child_3_average": 10,
                                                           "question_child_3_year": 25, "question_child_3_3": 1})]))[PPOK]
    assert out["Apakah anda sedang/mempunyai riwayat merokok?"] == "Iya"
    assert out["Jika Perokok Aktif, berapa bungkus per tahun?"] == "20-30 bungkus per tahun"


def test_puma_only_for_40_and_over():
    assert PPOK not in medisy_to_asik(bundle(years=39, screenings=[scr("puma", **{**PUMA_ZERO, "question4": 1})]))


# ───────────────────────────── ear (nullable columns) ────────────────────────

TM = "Skrining Telinga dan Mata (=>40 tahun)"
SERUMEN = "Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?"


def ear(**cols):
    row = {"serumen_impeksi_right": None, "serumen_impeksi_left": None, "omsk_congek_right_ear": None,
           "omsk_congek_left_ear": None, "tajam_pendengaran_right": None, "tajam_pendengaran_left": None}
    row.update(cols)
    return {"ptm": {"fase_pendengaran": [row]}}


def test_an_all_null_hearing_row_is_unanswered():
    assert medisy_to_asik(bundle(programs=ear()))[TM] == {}


def test_hearing_flags_and_acuity():
    out = medisy_to_asik(bundle(programs=ear(serumen_impeksi_right=0, serumen_impeksi_left=1, omsk_congek_right_ear=0,
                                             omsk_congek_left_ear=0, tajam_pendengaran_right="Normal",
                                             tajam_pendengaran_left="Gangguan pendengaran")))[TM]
    assert out[SERUMEN] == "Ada serumen impaksi"
    assert out["Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?"] == "Tidak ada infeksi telinga"
    assert out["Hasil pemeriksaan tajam pendengaran"] == "Curiga gangguan pendengaran"
    ok = medisy_to_asik(bundle(programs=ear(serumen_impeksi_right=0, tajam_pendengaran_right="Normal",
                                            tajam_pendengaran_left="Normal")))[TM]
    assert ok[SERUMEN] == "Tidak ada serumen impaksi" and ok["Hasil pemeriksaan tajam pendengaran"] == "Normal"


# ───────────────────────────── R-DIAG / labs ─────────────────────────────────


def lab(test, result, unit=None):
    return {"test": test, "result": result, "unit": unit, "parent": None}


def test_a_diagnosis_only_turns_a_result_on_and_absence_is_never_a_negative():
    assert medisy_to_asik(bundle())["Pemeriksaan HIV"] == {}
    assert medisy_to_asik(bundle(diagnoses=[dx("B20")]))["Pemeriksaan HIV"] == {"Hasil Pemeriksaan Rapid Test HIV": "Reaktif"}
    assert medisy_to_asik(bundle(hist_dx=[dx("A51.0")]))["Pemeriksaan Sifilis"] == {"Hasil Pemeriksaan Rapid Test Sifilis": "Reaktif"}
    hep = medisy_to_asik(bundle(diagnoses=[dx("B18.2")]))["Pemeriksaan Hepatitis"]
    assert hep == {"Hasil Rapid Test Hepatitis C": "Anti HCV Reaktif"}


def test_an_explicit_lab_result_beats_the_diagnosis_and_can_be_negative():
    out = medisy_to_asik(bundle(lab=[lab("ANTI HIV", "NEGATIF")], diagnoses=[dx("B20")]))["Pemeriksaan HIV"]
    assert out == {"Hasil Pemeriksaan Rapid Test HIV": "Non Reaktif"}
    assert medisy_to_asik(bundle(lab=[lab("ANTI HIV", "POSITIF")]))["Pemeriksaan HIV"] == {
        "Hasil Pemeriksaan Rapid Test HIV": "Reaktif"}


def test_lipid_labs_match_by_exact_name_and_hb_is_not_hba1c():
    L = "POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)"
    out = medisy_to_asik(bundle(years=50, lab=[lab("KOLESTEROL TOTAL", "230"), lab("HDL CHOLESTEROL", "50"),
                                               lab("LDL CHOLESTEROL", "100,5"), lab("TRIGLISERIDA", "150")]))[L]
    assert out == {"Kolesterol Total": 230, "HDL": 50, "LDL": 100.5, "Trigliserida": 150}
    cat = medisy_to_asik(bundle(gender="P", years=30, lab=[lab("HbA1c", "7"), lab("HEMOGLOBIN [MASS/VOLUME] IN BLOOD", "12")]))
    assert cat["Pemeriksaan Calon Pengantin Perempuan"] == {"Kadar Hemoglobin": 12}
    assert medisy_to_asik(bundle(gender="P", years=30, lab=[lab("HbA1c", "7")]))["Pemeriksaan Calon Pengantin Perempuan"] == {}


def test_lab_forms_are_40_plus_and_the_kidney_form_carries_the_age():
    assert "POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)" not in medisy_to_asik(bundle(years=39))
    out = medisy_to_asik(bundle(years=52, gender="P", lab=[lab("KREATININ", "0.9"), lab("UREUM", "30")]))
    ginjal = out["Skrining Fungsi Ginjal Perempuan (hanya untuk =>40 tahun dengan risiko HT DM)"]
    assert ginjal["Hasil Pemeriksaan Kreatinin"] == 0.9 and ginjal["Usia"] == 52


# ───────────────────────────── TB / dental / heart ───────────────────────────


def test_tb_cough_answers_and_each_form_uses_its_own_nbsp_variant():
    out = medisy_to_asik(bundle(screenings=[scr("tbc", batuk="Tidak", kontak_tbc="Tidak Ada")]))
    q = "Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?"
    assert out["Faktor Risiko TB - Dewasa & Lansia"][q] == "Tidak\xa0batuk"
    assert out["Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)"][q] == "Tidak batuk"
    assert out["Pemeriksaan Tuberkulosis (Dewasa & Lansia)"] == {"Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?": "Tidak ada"}
    # clinical sign-off 2026-10-05: Medisy has no duration, a "Ya" means more than 2 weeks
    yes = medisy_to_asik(bundle(screenings=[scr("tbc", batuk="Ya", kontak_tbc="TBC paru bakteriologis")]))
    assert yes["Faktor Risiko TB - Dewasa & Lansia"] == {q: "Ya, lebih dari 2 minggu"}
    assert yes["Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)"][q] == "Ya, lebih dari 2 minggu"
    assert yes["Pemeriksaan Tuberkulosis (Dewasa & Lansia)"] == {}                      # the contact type is still not mapped


def test_adult_dental_questions_3_and_4():
    out = medisy_to_asik(bundle(screenings=[scr("gigi_dewasa", question3="Tidak", question4="Ya")]))
    assert out["Skrining Karies dan Gigi Hilang"] == {"Gigi karies": "Ya", "Gigi hilang/dicabut": "Tidak"}


def test_ekg_from_the_heart_risk_screening():
    f = "Hasil Pemeriksaan - Skrining Jantung"
    assert medisy_to_asik(bundle(screenings=[scr("risiko_jantung", kardiovaskular_ekg="12, Normal")]))[f] == {
        "Hasil Pemeriksaan EKG": "Normal"}
    assert medisy_to_asik(bundle(screenings=[scr("risiko_jantung", kardiovaskular_ekg="100, Tidak Normal")]))[f] == {
        "Hasil Pemeriksaan EKG": "Abnormal"}
    assert f not in medisy_to_asik(bundle(years=35))                        # not 45+, no HT/DM
    assert f in medisy_to_asik(bundle(years=35, diagnoses=[dx("I10")]))     # HT/DM below 45 still gets it


def test_lung_cancer_options_map_and_non_equivalent_ones_are_dropped():
    F = "Skrining Kanker Paru (Usia =>45 thn)"
    out = medisy_to_asik(bundle(screenings=[scr(
        "kanker_paru", question3="Ya, pernah < 5 tahun yang lalu", question4="Ya, Kanker Paru",
        question5="Bekas perokok, berhenti < 15 tahun lalu", question6="Tidak yakin", question7="Tidak",
        question9="Ya, Pernah Penyakit Paru Kronik (PPOK)")]))[F]
    assert out["Apakah pernah didiagnosis/menderita kanker?"] == "Memiliki diagnosis kanker <5 tahun yang lalu"
    assert out["Apakah ada keluarga (ayah/ibu/saudara kandung) didiagnosis/menderita kanker sebelumnya?"] == "Memiliki keluarga yang terdiagnosis kanker paru"
    assert "Riwayat merokok/paparan asap rokok" not in out                  # <15y vs <10y: different thresholds (R-NOMATCH)
    assert out["Pernah didiagnosis penyakit paru kronik?"] == "Pernah didiagnosis penyakit kronis lain (PPOK, ILD, dll)"


# ───────────────────────────── lansia battery ────────────────────────────────


def test_skilas_question1_is_one_radio_with_recall_and_orientation_outcomes():
    K = "SKILAS Penurunan Kognitif - Lansia"
    pick = lambda v: medisy_to_asik(bundle(years=70, screenings=[scr("skilas", question1=v)]))[K]  # noqa: E731
    assert set(pick("Dapat mengulang kata yang harus diingat").values()) == {"Ya"}
    assert set(pick("Tidak dapat mengulang ketiga kata").values()) == {"Tidak"}
    assert list(pick("Semua pertanyaan dijawab tepat").values()) == ["Benar semua"]
    assert list(pick("Salah pada salah satu pertanyaan").values()) == ["Salah satu/Dua"]
    assert pick("something else") == {}


def test_skilas_malnutrisi_depresi_mobilisasi():
    out = medisy_to_asik(bundle(years=70, screenings=[scr("skilas", question2="Ya", question3a="Ya", question3b="Tidak",
                                                           question3c="Tidak", question6a="Ya", question6b="Tidak")]))
    assert list(out["SKILAS Mobilisasi - Lansia"].values()) == ["Ya"]
    assert list(out["SKILAS Malnutrisi"].values()) == ["Ya", "Tidak", "Tidak"]
    assert list(out["SKILAS Pemeriksaan Gejala Depresi - Lansia"].values()) == ["Ya", "Tidak"]


def test_barthel_scores_in_both_storage_styles_and_null_is_blank():
    a = {f"question{i}": None for i in range(1, 11)}
    a.update(question1="0, Tidak terkendali/tak teratur (perlu pencahar)", question2="2", question3="1, Mandiri", question7=3)
    out = medisy_to_asik(bundle(years=70, screenings=[scr("activity_living", **a)]))["Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia"]
    assert out["Dapat mengendalikan rangsang buang air besar (BAB)?"] == "Tidak terkendali/tak teratur (perlu pencahar)"
    assert out["Dapat mengendalikan rangsang berkemih/buar air kecil (BAK)?"] == "Mandiri"
    assert out["Membersihkan diri (seka wajah, sisir rambut, sikat gigi)?"] == "Mandiri"
    assert out["Berpindah/berjalan"] == "Mandiri" and len(out) == 4


def test_minicog_recall_sppb_and_mna_options():
    out = medisy_to_asik(bundle(years=70, screenings=[
        scr("pemeriksaan_cog", instruction1="2, Tepat 2 Kata"),
        scr("short_physical_performance", question1a="Bertahan 10 detik", question1b="Tidak dilakukan",
            question1c="Bertahan 3 - 9.99 detik", question2="4,82 detik - 6,20 detik", question3="11,2 - 13,69 detik"),
        scr("pengkajian_nutrisi", penapisan1="Nafsu makan sedikit berkurang (sedang)", penapisan2="Penurunan berat badan 1-3 kg",
            penapisan4="Ya", penapisan5="Demensia ringan", penapisan6="IMT 19 - < 21")]))
    assert list(out["Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)"].values()) == ["Benar 2 Kata"]
    sppb = list(out["Mobilisasi - Pemeriksaan Lanjutan (SPPB)"].values())
    assert sppb == ["Bertahan 10 detik", "Tidak dilakukan", "Bertahan 3 - 9.99 detik", "4.83 - 6.20 detik", "11.2 - 13,69 detik"]
    mna = out["Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)"]
    assert mna["Penurunan berat badan dalam tiga bulan terakhir ?"] == "Penurunan BB antara 1 - 3 Kg"
    assert mna["Berapa Nilai IMT (Indeks Massa Tubuh)?"] == "IMT 19 - <21" and len(mna) == 5


def test_catin_tetanus_needs_t2_or_more():
    f = "Riwayat Imunisasi Tetanus(Status T) - Hanya untuk Catin"
    assert medisy_to_asik(bundle(gender="P", years=25, screenings=[scr("imunisasi_tetanus_wus", imunisasi_tetanus="Sudah mendapat T4")]))[f]
    assert medisy_to_asik(bundle(gender="P", years=25, screenings=[scr("imunisasi_tetanus_wus", imunisasi_tetanus="Sudah mendapat T1")]))[f] == {}


# ───────────────────────────── R-NOMATCH ─────────────────────────────────────


def test_instruments_that_ask_a_different_question_are_never_mapped():
    out = medisy_to_asik(bundle(years=70, screenings=[
        scr("kesehatan_jiwa", question1="Sebagaimana Biasanya", question2="Jarang"),            # EPDS, not PHQ-4
        scr("merokok", questionC1a="Setiap hari"),                                              # school-student survey
        scr("ptm_mata", visus_kanan=5.0, pupil_kanan="725289009")]))                            # unverifiable scales
    assert out["Kesehatan Jiwa"] == {} and out["Perilaku Merokok"] == {}
    telmat = out["Skrining Telinga dan Mata (=>40 tahun)"]
    assert "Apa hasil skrining tajam penglihatan?" not in telmat and "Hasil pemeriksaan pupil" not in telmat


# ───────────────────────────── pediatric ─────────────────────────────────────


@pytest.mark.parametrize("years,form", [(2, "Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun"),
                                        (5, "Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun"),
                                        (10, "Gizi Anak Sekolah")])
def test_pediatric_growth_form_by_age_band(years, form):
    assert form in medisy_to_asik(bundle(years=years, vitals={"weight_kg": 12, "height_cm": 90}))


def test_pediatric_glucose_diabetes_flag_only_turns_on_and_tb_anak():
    out = medisy_to_asik(bundle(years=16, vitals={"gds": 100}, diagnoses=[dx("E10")]))
    assert out["Pemeriksaan Gula Darah Remaja"] == {
        "Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?": "Ya", "Gula Darah Sewaktu (GDS)": 100}
    assert "Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?" not in medisy_to_asik(
        bundle(years=16, vitals={"gds": 100}))["Pemeriksaan Gula Darah Remaja"]
    tb = medisy_to_asik(bundle(years=5, screenings=[scr("tbc", bb_turun="Ya", demam="Tidak")]))
    assert tb["Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun)"] == {
        "Apakah berat badan anak Anda turun tanpa penyebab jelas/ BB tidak naik dalam 2 bulan sebelumnya/ nafsu makan turun?": "Ya",
        "Apakah anak anda mengalami demam hilang timbul tanpa sebab yang jelas lebih dari 2 minggu?": "Tidak"}


# ───────────────────────────── contract ──────────────────────────────────────


def test_deterministic_and_does_not_mutate_its_input():
    b = bundle(years=70, vitals={"systole": 120, "diastole": 80}, screenings=[scr("skilas", question2="Ya")])
    before = copy.deepcopy(b)
    assert medisy_to_asik(b) == medisy_to_asik(b) and b == before


@pytest.mark.parametrize("junk", [None, {}, [], "x", {"patient": None}, {"patient": {"age": "old", "gender": 5}},
                                  {"screenings": [None, {"key": 3}, {"key": "puma", "answers": None}], "lab": [None, {}],
                                   "diagnoses": [None], "programs": {"kia": None}, "anamnesis": None}])
def test_garbage_degrades_to_blank_never_raises(junk):
    medisy_to_asik(junk)


def test_the_latest_screening_entry_wins():
    old = scr("hipertensi", **{f"question{i}_anamnesis": ("Ya" if i == 1 else "Tidak") for i in range(1, 9)})
    old["performed_at"] = "2025-01-01T00:00:00+07:00"
    new = scr("hipertensi", **{f"question{i}_anamnesis": ("Tidak" if i == 1 else "Ya") for i in range(1, 9)})
    out = medisy_to_asik(bundle(screenings=[new, old]))[TD]                  # order in the list must not matter
    assert out["Apakah Anda pernah dinyatakan tekanan darah tinggi?"] == "Tidak"


def test_every_emitted_field_is_a_real_asik_label_with_a_breadcrumb():
    """Fuzz-ish: a rich bundle that triggers as many forms as possible. Names must match live ASIK labels byte for byte."""
    rich = bundle(gender="P", years=72, vitals={"systole": 120, "diastole": 80, "gds": 100, "gdp": 90, "weight_kg": 60,
                                                "height_cm": 150, "waist_cm": 90},
                  screenings=[ht(question6_anamnesis="Tidak"), scr("puma", **{**PUMA_ZERO, "question4": 1}),
                              scr("skilas", question1="Semua pertanyaan dijawab tepat", question2="Ya", question3a="Ya",
                                  question6a="Ya"), scr("tbc", batuk="Tidak", kontak_tbc="Tidak Ada"),
                              scr("kanker_paru", question3="Tidak Pernah"), scr("risiko_jantung", kardiovaskular_ekg="1, Normal"),
                              scr("gigi_dewasa", question3="Ya", question4="Ya"), scr("pemeriksaan_cog", instruction1="3, Tepat 3 Kata"),
                              scr("imunisasi_tetanus_wus", imunisasi_tetanus="Sudah mendapat T5 (lengkap)")],
                  diagnoses=[dx("B20")], lab=[lab("KOLESTEROL TOTAL", "200"), lab("HEMOGLOBIN", "12")],
                  programs={**ear(serumen_impeksi_right=1), "kia": {"hamil": [{"x": 1}]}})
    out = medisy_to_asik(rich)
    for form, fields in out.items():
        if form == "identitas_pasien":
            continue
        assert form in ASIK_FORM_LABELS or fields == {}, f"unknown form {form!r}"
        for label in fields:
            assert label in ASIK_FORM_LABELS[form], f"{form!r}: {label!r} is not a live ASIK label"
            assert MEDISY_BREADCRUMBS[form][label], f"{form!r}: {label!r} has no source in MEDISY_BREADCRUMBS"


def test_breadcrumbs_cover_exactly_the_live_forms():
    assert set(MEDISY_BREADCRUMBS) == set(ASIK_FORM_LABELS)
    assert all(set(MEDISY_BREADCRUMBS[f]) == set(labels) for f, labels in ASIK_FORM_LABELS.items())


def test_dropdown_screenings_emit_fields_with_breadcrumbs():
    """SPPB and MNA-SF are mapped through option tables; every field they can emit must have a source breadcrumb."""
    from app.services.medisy_to_asik import _MNA, _SPPB

    sppb = scr("short_physical_performance", **{col: next(iter(opts)) for col, _p, opts in _SPPB})
    mna = scr("pengkajian_nutrisi", **{col: next(iter(opts)) for col, _p, opts in _MNA})
    out = medisy_to_asik(bundle(gender="P", years=72, screenings=[sppb, mna]))
    for form, n in (("Mobilisasi - Pemeriksaan Lanjutan (SPPB)", len(_SPPB)), ("Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)", len(_MNA))):
        assert len(out[form]) == n, (form, out[form])
        for label in out[form]:
            assert MEDISY_BREADCRUMBS[form][label], f"{form!r}: {label!r} has no source in MEDISY_BREADCRUMBS"


# ───────────────── PTM questionnaire (Faktor Risiko PTM modal) and eyes ─────────────────

MEROKOK = "Perilaku Merokok"
AKTIVITAS = "Tingkat Aktivitas Fisik (sedang dan berat)"
SMOKE_Q = "Apakah Anda merokok dalam setahun terakhir ini?"
EXPOSE_Q = "Apakah Anda terpapar asap rokok atau menghirup asap rokok dari orang lain dalam sebulan terakhir?"
MEDIUM_Q = "Apakah Anda melakukan olahraga intensitas sedang seperti latihan beban < 20 kg, senam aerobic, yoga, bermain bola, bersepeda dan berenang (santai)?"
HEAVY_Q = "Apakah Anda melakukan olahraga intensitas berat seperti bersepeda cepat (>16 km/jam), jalan cepat (>7 km/jam), lari, sepak bola, futsal, bulutangkis, tenis, basket dan lompat tali?"


def ptm(questionnaire, link, code=None, label=None, value=None):
    return {"questionnaire": questionnaire, "question_code": link, "question": "x", "answer_type": "t",
            "answer_code": code, "answer_label": label, "value": value}


def with_q(rows, **kw):
    return bundle(programs={"ptm_questionnaire": rows}, **kw)


def test_smoking_status_and_exposure_come_from_the_ptm_questionnaire():
    smoker = medisy_to_asik(with_q([ptm("Q0013", "1.4", "77176002"), ptm("Q0013", "1.5", "QRI000016", "Ya, setiap hari")]))[MEROKOK]
    assert smoker == {SMOKE_Q: "Ya", EXPOSE_Q: "Ya"}
    non = medisy_to_asik(with_q([ptm("Q0013", "1.4", "8392000"), ptm("Q0013", "1.5", "QRI000014", "Tidak")]))[MEROKOK]
    assert non == {SMOKE_Q: "Tidak", EXPOSE_Q: "Tidak"}


def test_smoking_with_no_status_is_only_tidak_when_the_patient_never_smoked():
    assert medisy_to_asik(with_q([ptm("Q0013", "1.1", value="0")]))[MEROKOK] == {SMOKE_Q: "Tidak"}
    assert medisy_to_asik(with_q([ptm("Q0013", "1.1", value="1")]))[MEROKOK] == {}          # ever-smoker, current status unknown
    assert medisy_to_asik(bundle())[MEROKOK] == {}                                         # no questionnaire: shell


def test_the_answer_text_is_only_a_fallback_for_a_frequency_answer():
    out = medisy_to_asik(with_q([ptm("Q0013", "1.5", None, "Tidaks")]))[MEROKOK]           # UAT data carries typos in the display
    assert out == {EXPOSE_Q: "Tidak"}


def test_physical_activity_rule_is_the_one_the_epuskesmas_converter_used():
    assert medisy_to_asik(with_q([ptm("Q0013", "1.10", "QRI000016")]))[AKTIVITAS] == {MEDIUM_Q: "Tidak", HEAVY_Q: "Tidak"}
    assert medisy_to_asik(with_q([ptm("Q0013", "1.10", "QRI000014")]))[AKTIVITAS] == {MEDIUM_Q: "Ya"}
    assert medisy_to_asik(bundle())[AKTIVITAS] == {}


def test_lung_cancer_questionnaire_fills_the_screening_form_and_the_table_wins_on_conflict():
    rows = [ptm("Q0019", "1.1", "QRI000034"), ptm("Q0019", "1.2", "429011007"), ptm("Q0019", "1.3", "QRI000023"),
            ptm("Q0019", "1.6", "QRI000029"), ptm("Q0019", "1.7", "414415007")]
    out = medisy_to_asik(with_q(rows, years=50))
    kp = out["Skrining Kanker Paru (Usia =>45 thn)"]
    assert kp["Apakah pernah didiagnosis/menderita kanker?"] == "Tidak pernah didiagnosis menderita kanker"
    assert kp["Riwayat merokok/paparan asap rokok"] == "Perokok/bekas perokok berhenti <10 tahun lalu"
    assert kp["Pernah didiagnosis penyakit paru kronik?"] == "Pernah didiagnosis penyakit kronis lain (PPOK, ILD, dll)"
    conflict = with_q(rows, years=50, screenings=[scr("kanker_paru", question3="Ya, Pernah > 5 Tahun yang lalu")])
    assert medisy_to_asik(conflict)["Skrining Kanker Paru (Usia =>45 thn)"]["Apakah pernah didiagnosis/menderita kanker?"] \
        == "Memiliki diagnosis kanker >5 tahun yang lalu"


def test_lung_screening_and_colorectal_forms_take_only_same_question_answers():
    rows = [ptm("Q0013", "1.4", "77176002"), ptm("Q0013", "1.5", "QRI000015"), ptm("Q0019", "1.2", "QRI000035"),
            ptm("Q0019", "1.7", "160258000"), ptm("Q0020", "1.1", None, None, "0"), ptm("Q0020", "1.1", "QRI000020")]
    out = medisy_to_asik(with_q(rows, years=50))
    pen = out["Penapisan Risiko Kanker Paru"]
    assert pen["Apakah Anda merokok dalam setahun terakhir ini?"] == "Ya"
    assert pen["Apakah memiliki riwayat kanker paru pada keluarga (ayah/ibu/saudara kandung)?"] == "Tidak"
    assert pen["Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK?"] == "Tidak"
    assert not any("15 tahun" in k or "gejala" in k for k in pen)                          # asked differently in Medisy: not mapped
    usus = out["Faktor Risiko Kanker Usus"]
    assert usus["Apakah ada anggota keluarga Anda, yang pernah dinyatakan menderita kanker kolorektal atau kanker usus?"] == "Ya"
    assert usus["Apakah Anda merokok?"] == "Ya"                                            # the answered row beats the header row


def eyes(**cols):
    return scr("ptm_mata", **cols)


VISUS_Q = "Apa hasil skrining tajam penglihatan?"


def test_visus_is_judged_by_the_snellen_ratio_of_every_measured_eye():
    ok = medisy_to_asik(bundle(screenings=[eyes(visus_kanan=6, visus_kanan_denominator=6, visus_kiri=6, visus_kiri_denominator=12)]))
    assert ok["Skrining Telinga dan Mata (=>40 tahun)"][VISUS_Q] == "Normal (visus 6/6 - 6/12)"
    bad = medisy_to_asik(bundle(screenings=[eyes(visus_kanan=6, visus_kanan_denominator=6, visus_kiri=6, visus_kiri_denominator=18)]))
    assert bad["Skrining Telinga dan Mata (=>40 tahun)"][VISUS_Q] == "Curiga gangguan penglihatan (visus <6/12)"
    one = medisy_to_asik(bundle(years=30, screenings=[eyes(visus_kanan=6, visus_kanan_denominator=6)]))
    assert one["Skrining Telinga dan Mata (18-39 tahun)"][VISUS_Q] == "Normal (visus 6/6 - 6/12)"
    none = medisy_to_asik(bundle(screenings=[eyes(visus_kanan=0, visus_kanan_denominator=6)]))
    assert VISUS_Q not in none["Skrining Telinga dan Mata (=>40 tahun)"]


def test_pupil_only_places_a_suspected_cataract_and_never_invents_normal():
    sus = medisy_to_asik(bundle(screenings=[eyes(pupil_kanan="OV000393", pupil_kiri=None)]))
    assert sus["Skrining Telinga dan Mata (=>40 tahun)"]["Hasil pemeriksaan pupil"] == "Curiga Katarak"
    other = medisy_to_asik(bundle(screenings=[eyes(pupil_kanan="72124005", pupil_kiri="72124005")]))
    assert "Hasil pemeriksaan pupil" not in other["Skrining Telinga dan Mata (=>40 tahun)"]


def test_adult_xray_tb_form_takes_the_symptom_and_radiograph_answers_medisy_also_records():
    form = "Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)"
    out = medisy_to_asik(bundle(screenings=[scr("tbc", batuk="Tidak", bb_turun="Ya", demam="Tidak", berkeringat_malam="Ya",
                                                 pemeriksaan_foto_toraks="Normal")]))[form]
    assert out["Apakah berat badan Anda turun tanpa penyebab jelas/ BB tidak naik/ nafsu makan turun?"] == "Ya"
    assert out["Apakah Anda mengalami demam hilang timbul tanpa sebab yang jelas?"] == "Tidak"
    assert out["Apakah Anda mengalami berkeringat di malam hari tanpa kegiatan?"] == "Ya"
    assert out["Apakah dilakukan pemeriksaan radiografi toraks?"] == "Ya"
    assert "Apakah pasien memiliki pembesaran kelenjar getah bening?" not in out          # Medisy has no such column


def test_an_all_zero_puma_row_saved_again_after_creation_counts_as_answered():
    row = scr("puma", **PUMA_ZERO)
    row["updated_at"] = "2026-09-02T10:05:00+07:00"                                       # performed_at is 10:00
    out = medisy_to_asik(bundle(screenings=[row]))[PPOK]
    assert out and set(out.values()) == {"Tidak"}
    untouched = scr("puma", **PUMA_ZERO)
    untouched["updated_at"] = untouched["performed_at"]
    assert medisy_to_asik(bundle(screenings=[untouched]))[PPOK] == {}


SK_MAL = "SKILAS Malnutrisi"
WEIGHT_Q = "Apakah berat badan Anda berkurang >3 kg dalam 3 bulan terakhir atau pakaian menjadi lebih longgar?"
APPETITE_Q = "Apakah Anda hilang nafsu makan Atau mengalami kesulitan makan (misal batuk atau tersedak saat makan, menggunakan selang makan/sonde)?"


def test_medisy_nutrition_screening_fills_skilas_malnutrition_only_where_unambiguous():
    def mal(**gizi):
        return medisy_to_asik(bundle(years=70, screenings=[scr("gizi", **gizi)]))[SK_MAL]

    assert mal(penurunan_bb="tidak", asupan_makanan="ya") == {WEIGHT_Q: "Tidak", APPETITE_Q: "Ya"}
    assert mal(penurunan_bb="tidak yakin")[WEIGHT_Q] == "Ya"                               # "clothes feel looser"
    assert mal(penurunan_bb="11-15 kg")[WEIGHT_Q] == "Ya"
    assert mal(penurunan_bb="1-5 kg", asupan_makanan="tidak") == {}                         # straddles 3 kg; "no" misses difficulty eating


def test_skilas_own_answer_wins_over_the_nutrition_screening():
    out = medisy_to_asik(bundle(years=70, screenings=[scr("skilas", question3a="Tidak"), scr("gizi", penurunan_bb=">15 kg")]))
    assert out[SK_MAL][WEIGHT_Q] == "Tidak"


# ───────── columns added for the ASIK CKG forms (himed-app db/2026/20261013-add-ilp-screening-fields) ─────────

NEW_ASIK_COLUMNS = (
    "sistole_2", "diastole_2", "lama_hipertensi_bulan", "gds_2", "gula_darah_2jam_pp", "lama_diabetes_bulan", "pembesaran_kgb",
    "metode_pemeriksaan_tb", "gigi_goyang", "penyakit_periodontal", "riwayat_merokok_15th", "gejala_kanker_paru", "kadar_co",
    "hasil_usg_payudara", "pernah_hubungan_seksual", "clock_drawing_test",
)


def test_second_blood_pressure_and_months_since_diagnosis():
    ht = scr("hipertensi", question1_anamnesis="Ya", question2_anamnesis="Tidak", sistole_2=150, diastole_2="95", lama_hipertensi_bulan=18)
    out = medisy_to_asik(bundle(screenings=[ht]))[TD]
    assert out["Tekanan Darah Sistolik Ke-2"] == 150 and out["Tekanan darah diastolik ke-2"] == 95
    assert out[next(k for k in out if k.startswith("Sudah Berapa Bulan"))] == 18


def test_months_are_only_sent_when_the_history_answer_is_ya():
    ht = scr("hipertensi", question1_anamnesis="Tidak", question2_anamnesis="Ya", lama_hipertensi_bulan=18)
    assert not any(k.startswith("Sudah Berapa Bulan") for k in medisy_to_asik(bundle(screenings=[ht]))[TD])


@pytest.mark.parametrize("empty", [None, "", 0, "0", "abc"])
def test_unanswered_or_zero_new_numbers_are_never_sent(empty):
    ht = scr("hipertensi", sistole_2=empty, diastole_2=empty, lama_hipertensi_bulan=empty)
    dm = scr("diabetes_melitus", gds_2=empty, gula_darah_2jam_pp=empty, lama_diabetes_bulan=empty)
    out = medisy_to_asik(bundle(screenings=[ht, dm]))
    assert not any("Ke-2" in k or "ke-2" in k or k.startswith("Sudah") for k in out[TD])
    assert not any("Kedua" in k or "2 Jam" in k or k.startswith("Sudah") for k in out[GD])


def test_second_glucose_two_hour_pp_and_months():
    dm = scr("diabetes_melitus", question5_anamnesis="Ya", question1_anamnesis="Tidak", gds_2="155,5", gula_darah_2jam_pp="130", lama_diabetes_bulan=7)
    out = medisy_to_asik(bundle(screenings=[dm]))[GD]
    assert out[next(k for k in out if k.startswith("Gula Darah Sewaktu Kedua"))] == 155.5
    assert out["Gula Darah 2 Jam PP (mg/dl)"] == 130
    assert out[next(k for k in out if k.startswith("Sudah Berapa Bulan"))] == 7


def test_tb_lymph_nodes_and_test_method():
    out = medisy_to_asik(bundle(screenings=[scr("tbc", batuk="Tidak", pembesaran_kgb="Ya", metode_pemeriksaan_tb="BTA Mikroskopis")]))
    xray = out["Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)"]
    assert xray["Apakah pasien memiliki pembesaran kelenjar getah bening?"] == "Ya"
    assert out["Pemeriksaan Tuberkulosis (Dewasa & Lansia)"]["Metode Pemeriksaan (untuk terduga TB)"] == "BTA"


@pytest.mark.parametrize("method", ["Foto Toraks (Rontgen)", "Pemeriksaan Klinis", None, ""])
def test_tb_methods_without_an_asik_option_are_not_sent(method):
    out = medisy_to_asik(bundle(screenings=[scr("tbc", batuk="Tidak", metode_pemeriksaan_tb=method)]))
    assert "Metode Pemeriksaan (untuk terduga TB)" not in out["Pemeriksaan Tuberkulosis (Dewasa & Lansia)"]


@pytest.mark.parametrize("table", ["gigi_dewasa", "gigi_lansia"])
@pytest.mark.parametrize("disease, expected", [("Tidak Ada", "Tidak"), ("Gingivitis", "Ya"), ("Periodontitis", "Ya"), (None, None)])
def test_periodontal_form_reads_either_dental_table(table, disease, expected):
    out = medisy_to_asik(bundle(screenings=[scr(table, gigi_goyang="Ya", penyakit_periodontal=disease)]))["Skrining Penyakit Periodontal"]
    assert out["Gigi Goyang"] == "Ya"
    assert out.get("Penyakit Periodontal") == expected


def test_lung_screening_questions_and_exhaled_co():
    kp = scr("kanker_paru", riwayat_merokok_15th="Ya", gejala_kanker_paru="Tidak", kadar_co="7,5")
    out = medisy_to_asik(bundle(years=50, screenings=[kp]))
    screen = out["Penapisan Risiko Kanker Paru"]
    assert screen[next(k for k in screen if "15 tahun" in k)] == "Ya"
    assert screen[next(k for k in screen if "gejala" in k)] == "Tidak"
    assert out["Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)"] == {"Kadar CO Pernapasan": 7.5}


def test_a_recorded_co_of_zero_is_a_real_reading_but_blank_is_not():
    co = "Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)"
    assert medisy_to_asik(bundle(years=50, screenings=[scr("kanker_paru", kadar_co="0")]))[co] == {"Kadar CO Pernapasan": 0}
    assert medisy_to_asik(bundle(years=50, screenings=[scr("kanker_paru", kadar_co=None)]))[co] == {}


def test_breast_screening_sadanis_and_ultrasound():
    risk = scr("risiko_kanker_payudara", checkup_result1="Tidak ada benjolan", hasil_usg_payudara="Kista Simpleks")
    out = medisy_to_asik(bundle(gender="P", years=47, screenings=[risk]))["Skrining Kanker Payudara"]
    assert out == {"Pemeriksaan yang dilakukan": "SADANIS", "Hasil pemeriksaan SADANIS": "Normal", "Hasil pemeriksaan USG Payudara": "Simple cyst"}


def test_ultrasound_results_without_an_asik_option_are_not_sent():
    risk = scr("risiko_kanker_payudara", checkup_result1=None, hasil_usg_payudara="Tumor Jinak (Fibroadenoma)")
    assert medisy_to_asik(bundle(gender="P", years=47, screenings=[risk]))["Skrining Kanker Payudara"] == {}


def test_breast_form_is_for_women_from_30_only():
    risk = scr("risiko_kanker_payudara", checkup_result1="Benjolan")
    assert "Skrining Kanker Payudara" not in medisy_to_asik(bundle(gender="L", years=47, screenings=[risk]))
    assert "Skrining Kanker Payudara" not in medisy_to_asik(bundle(gender="P", years=25, screenings=[risk]))


def test_cervical_sexual_history_and_clock_drawing():
    out = medisy_to_asik(bundle(gender="P", years=65, screenings=[
        scr("kanker_serviks", pernah_hubungan_seksual="Ya"), scr("pemeriksaan_cog", instruction1="3 kata", clock_drawing_test="Abnormal")]))
    assert out["Kanker Leher Rahim"] == {"Apakah pernah melakukan hubungan intim/seksual?": "Ya"}
    minicog = out[m._F_MINICOG]
    assert minicog[next(k for k in minicog if k.startswith("Katakan seluruh frase"))] == "Salah"


def test_clock_drawing_falls_back_to_the_skilas_step():
    out = medisy_to_asik(bundle(gender="P", years=65, screenings=[scr("skilas", clock_drawing_test="Normal")]))[m._F_MINICOG]
    assert out[next(k for k in out if k.startswith("Katakan seluruh frase"))] == "Benar"


def test_nothing_new_is_invented_from_empty_columns():
    """New columns are NULL until answered: a bundle where they are all null must produce none of the new answers."""
    cols = {c: None for c in NEW_ASIK_COLUMNS}
    shots = [scr(k, **cols) for k in ("hipertensi", "diabetes_melitus", "tbc", "gigi_dewasa", "kanker_paru",
                                      "risiko_kanker_payudara", "kanker_serviks", "pemeriksaan_cog", "skilas")]
    with_nulls = medisy_to_asik(bundle(gender="P", years=65, screenings=shots))
    without = medisy_to_asik(bundle(gender="P", years=65))
    assert with_nulls == without
