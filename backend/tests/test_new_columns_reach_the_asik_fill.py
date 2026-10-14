"""The screening columns Medisy added for the ASIK CKG forms must reach the ASIK form fill (fictitious bundle, nothing is sent).

Three things have to hold for each new answer, or the robot silently drops it:
  1. the converter emits it under the exact ASIK question label;
  2. the sync robot's section index finds it from the form title ASIK shows on the patient's detail page;
  3. a choice answer is one of the options of that live ASIK question (``asik_form_mapping.json``).
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("SCRAPER_SESSION_DIR", "/tmp/_asik_sync_test_session")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scrapers" / "asik"))
sys.path.insert(0, str(ROOT / "scrapers" / "asik_sync"))

import sync  # noqa: E402

from app.services.asik_form_labels import ASIK_FORM_LABELS  # noqa: E402
from app.services.medisy_to_asik import medisy_to_asik  # noqa: E402
from test_medisy_to_asik import bundle, scr  # noqa: E402

MAPPING = json.loads((ROOT / "backend" / "app" / "data" / "asik_form_mapping.json").read_text())

# (form key in the converter output, the title the robot reads on ASIK's detail page, new question label prefix, expected value)
EXPECTED = (
    ("Tekanan Darah Dewasa Lansia", "Tekanan Darah Dewasa Lansia", "Tekanan Darah Sistolik Ke-2", 150),
    ("Tekanan Darah Dewasa Lansia", "Tekanan Darah Dewasa Lansia", "Tekanan darah diastolik ke-2", 95),
    ("Tekanan Darah Dewasa Lansia", "Tekanan Darah Dewasa Lansia", "Sudah Berapa Bulan Anda Didiagnosis Hipertensi", 18),
    ("Pemeriksaan Gula Darah Dewasa Lansia", "Pemeriksaan Gula Darah Dewasa Lansia", "Gula Darah Sewaktu Kedua", 155),
    ("Pemeriksaan Gula Darah Dewasa Lansia", "Pemeriksaan Gula Darah Dewasa Lansia", "Gula Darah 2 Jam PP", 130),
    ("Pemeriksaan Gula Darah Dewasa Lansia", "Pemeriksaan Gula Darah Dewasa Lansia", "Sudah Berapa Bulan Anda Didiagnosis Diabetes", 7),
    ("Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)", "Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)",
     "Apakah pasien memiliki pembesaran kelenjar getah bening", "Ya"),
    ("Pemeriksaan Tuberkulosis (Dewasa & Lansia)", "Pemeriksaan Tuberkulosis (Dewasa & Lansia)", "Metode Pemeriksaan (untuk terduga TB)", "TCM"),
    ("Skrining Penyakit Periodontal", "Skrining Penyakit Periodontal", "Gigi Goyang", "Ya"),
    ("Skrining Penyakit Periodontal", "Skrining Penyakit Periodontal", "Penyakit Periodontal", "Ya"),
    ("Penapisan Risiko Kanker Paru", "Penapisan Risiko Kanker Paru", "Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir", "Ya"),
    ("Penapisan Risiko Kanker Paru", "Penapisan Risiko Kanker Paru", "Apakah Anda sedang mengalami salah satu atau lebih gejala", "Tidak"),
    ("Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)",
     "Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)", "Kadar CO Pernapasan", 7.5),
    ("Skrining Kanker Payudara", "Skrining Kanker Payudara", "Pemeriksaan yang dilakukan", "SADANIS"),
    ("Skrining Kanker Payudara", "Skrining Kanker Payudara", "Hasil pemeriksaan SADANIS", "Normal"),
    ("Skrining Kanker Payudara", "Skrining Kanker Payudara", "Hasil pemeriksaan USG Payudara", "Simple cyst"),
    ("Kanker Leher Rahim", "Kanker Leher Rahim", "Apakah pernah melakukan hubungan intim/seksual", "Ya"),
    ("Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)", "Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)",
     "Katakan seluruh frase berikut", "Salah"),
)


def _fictitious_bundle():
    screenings = [
        scr("hipertensi", question1_anamnesis="Ya", question2_anamnesis="Tidak", sistole_2=150, diastole_2=95, lama_hipertensi_bulan=18),
        scr("diabetes_melitus", question5_anamnesis="Ya", question1_anamnesis="Tidak", gds_2="155", gula_darah_2jam_pp="130", lama_diabetes_bulan=7),
        scr("tbc", batuk="Tidak", pembesaran_kgb="Ya", metode_pemeriksaan_tb="TCM"),
        scr("gigi_dewasa", gigi_goyang="Ya", penyakit_periodontal="Gingivitis"),
        scr("kanker_paru", riwayat_merokok_15th="Ya", gejala_kanker_paru="Tidak", kadar_co="7,5"),
        scr("risiko_kanker_payudara", checkup_result1="Tidak ada benjolan", hasil_usg_payudara="Kista Simpleks"),
        scr("kanker_serviks", pernah_hubungan_seksual="Ya"),
        scr("pemeriksaan_cog", instruction1="3 kata", clock_drawing_test="Abnormal"),
    ]
    return bundle(gender="P", years=65, screenings=screenings)


def _choices(form_title: str, label_prefix: str):
    """Options of the live ASIK question (None for a free number / text question), from the committed ASIK form catalogue."""
    for f in MAPPING["forms"]:
        for q in f.get("questions") or f.get("fields") or []:
            label = q.get("label") or ""
            if label.startswith(label_prefix):
                ch = q.get("choices")
                if isinstance(ch, list) and ch:
                    return [c["line"] for c in ch if isinstance(c, dict)]
    return None


def _index():
    return sync._build_section_index(medisy_to_asik(_fictitious_bundle()))


def test_every_new_answer_is_found_by_the_robot_from_the_asik_form_title():
    index = _index()
    missing = []
    for _form, title, prefix, expected in EXPECTED:
        items = sync._match_section_items(index, sync._slugify_form(title))
        hit = next((it for it in items if it["merged_key"].startswith(prefix)), None)
        if hit is None or hit["merged_value"] != expected:
            missing.append((title, prefix, expected, hit and hit["merged_value"]))
    assert not missing, missing


def test_every_new_choice_answer_is_an_option_of_the_live_asik_question():
    index = _index()
    bad = []
    for _form, title, prefix, expected in EXPECTED:
        if isinstance(expected, (int, float)):
            continue
        options = _choices(title, prefix)
        if options is None or expected not in options:
            bad.append((title, prefix, expected, options))
    assert not bad, bad
    assert index  # the bundle did convert


def test_the_new_answers_are_the_ones_the_fill_loop_matches_by_label():
    """The fill loop compares ``merged_key`` with the question label case-insensitively and in full."""
    index = _index()
    for _form, title, prefix, _expected in EXPECTED:
        items = sync._match_section_items(index, sync._slugify_form(title))
        keys = [it["merged_key"] for it in items if it["merged_key"].startswith(prefix)]
        assert len(keys) == 1, (title, prefix, keys)
        assert keys[0] in ASIK_FORM_LABELS[_form], (title, keys[0])
