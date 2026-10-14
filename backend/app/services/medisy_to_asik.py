"""Medisy visit bundle -> ASIK CKG form shape.

``medisy_to_asik(bundle)`` turns one stored Medisy bundle (the JSON returned by himed-app's ``/medisy_api/ckg/visits/batch``,
see ``MEDISY_MIGRATION.md`` §5.2) into ``{asik_form_name: {asik_field_label: value}}``. Pure dict-in/dict-out: no network, no LLM,
no randomness; defensive ``.get()`` everywhere, so a shape change degrades to a blank field, never an exception.

**Zero hallucination.** Every emitted value traces to a bundle field (``MEDISY_BREADCRUMBS`` records which). A field Medisy does not
capture is simply absent (blank — ASIK accepts partial forms); the merge keeps the ASIK-side value for it.

Form and field names are the live ASIK ones (``asik_form_labels.py``). The clinical rules below were decided from Medisy's own
templates and data (see ``MEDISY_TO_ASIK_RULES.md`` for the per-form reasoning and the open questions for clinical sign-off):

R-ZERO     Medisy's int-coded screenings (e.g. PUMA) are NULLABLE with DEFAULT 0, so a stored 0 is "No" OR "never answered". A 1
           is always trusted. A 0 is emitted as "Tidak" only when the SAME row has real activity (at least one positive answer);
           an all-zero row emits nothing. Text-coded answers ("Ya"/"Tidak"/option text) and NULLable columns have no such problem.
R-UNIFORM  The hypertension / diabetes / heart-risk questionnaires have a "check to all" button. When every answer of one row is
           identical, the row is treated as untrusted for the single-question mappings (history of hypertension, ...).
R-DIAG     A diagnosis can only ever turn a result ON (HIV/hepatitis/syphilis "Reaktif", TB flag). The absence of a diagnosis is
           never turned into "Non Reaktif" / "Tidak": absence of evidence is not a negative result.
R-NOMATCH  No mapping where the two systems ask different questions. Medisy's mental-health screening is EPDS/SDQ, not PHQ-4;
           its smoking screening is the school-student survey, not the adult one; the eye table stores visus/pupil in scales that
           cannot be verified. Those ASIK fields stay blank.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.asik_form_labels import ASIK_FORM_LABELS

ASIK_Result = dict[str, dict[str, Any]]


# ─── label lookup ─────────────────────────────────────────────────────────────


def _q(form: str, prefix: str) -> str:
    """The exact ASIK label of ``form``: ``prefix`` itself when it is a whole label, else the one label starting with it
    (fails at import time if absent or ambiguous)."""
    if prefix in ASIK_FORM_LABELS[form]:
        return prefix
    hits = [lab for lab in ASIK_FORM_LABELS[form] if lab.startswith(prefix)]
    if len(hits) != 1:
        raise KeyError(f"{form!r}: {len(hits)} labels start with {prefix!r}")
    return hits[0]


# ─── value helpers ────────────────────────────────────────────────────────────

_INDO_MONTHS = ("", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
                "Oktober", "November", "Desember")


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _num(v: Any) -> int | float | None:
    """A number from a number or a numeric string ("180", "180,5"); None for anything else."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = _clean(v)
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else f


def _norm(v: Any) -> str:
    """Fold for tolerant option matching: dashes, decimal comma, whitespace, case. Never fuzzes wording."""
    t = (_clean(v) or "").replace("–", "-").replace("—", "-").replace(",", ".")
    return "".join(t.split()).lower()


def _yatidak(v: Any) -> str | None:
    s = (_clean(v) or "").lower()
    if s in ("ya", "iya", "y", "true", "1"):
        return "Ya"
    if s in ("tidak", "t", "false", "0"):
        return "Tidak"
    return None


def _positive(v: Any) -> bool:
    n = _num(v)
    return n is not None and n > 0


def _pos(v: Any) -> int | float | None:
    """A strictly positive number, else None (a recorded 0 is never trusted as a measurement)."""
    n = _num(v)
    return n if n is not None and n > 0 else None


def _gender(b: dict) -> str | None:
    g = (_clean((b.get("patient") or {}).get("gender")) or "").upper()
    return {"L": "Laki-Laki", "P": "Perempuan"}.get(g)


def _years(b: dict) -> int | None:
    age = (b.get("patient") or {}).get("age")
    y = age.get("years") if isinstance(age, dict) else None
    return y if isinstance(y, int) and not isinstance(y, bool) and y >= 0 else None


def _indo_date(iso: Any) -> str | None:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", _clean(iso) or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{d} {_INDO_MONTHS[mo]} {y}" if 1 <= mo <= 12 else None


# ─── source accessors ─────────────────────────────────────────────────────────


def _vitals(b: dict) -> dict:
    return (b.get("anamnesis") or {}).get("vitals") or {}


def _screens(b: dict) -> dict[str, dict[str, Any]]:
    """``{instrument key: {column: value}}`` using the LATEST entry of each instrument (by performed_at, then order)."""
    best: dict[str, tuple[str, int, dict]] = {}
    for i, s in enumerate(b.get("screenings") or []):
        key = s.get("key")
        if not isinstance(key, str):
            continue
        rank = (s.get("performed_at") or "", i)
        if key not in best or rank >= (best[key][0], best[key][1]):
            best[key] = (rank[0], rank[1], {a.get("question_code"): a.get("value") for a in s.get("answers") or []})
    return {k: v[2] for k, v in best.items()}


def _was_resaved(b: dict, key: str) -> bool:
    """True when the LATEST entry of instrument ``key`` was updated after it was created (``updated_at`` > ``performed_at``)."""
    best: tuple[str, int, dict] | None = None
    for i, sc in enumerate(b.get("screenings") or []):
        if sc.get("key") == key and (best is None or (sc.get("performed_at") or "", i) >= best[:2]):
            best = (sc.get("performed_at") or "", i, sc)
    if best is None:
        return False
    made, saved = _clean(best[2].get("performed_at")), _clean(best[2].get("updated_at"))
    return bool(made and saved and saved > made)


def _program_rows(b: dict, program: str, alias: str) -> list[dict]:
    block = (b.get("programs") or {}).get(program)
    rows = block.get(alias) if isinstance(block, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _icd_codes(b: dict) -> set[str]:
    """ICD-10 codes of this visit's diagnoses plus the patient's earlier ones, upper-cased."""
    out: set[str] = set()
    for d in (b.get("diagnoses") or []) + ((b.get("history") or {}).get("diagnoses") or []):
        code = _clean((d or {}).get("icd10"))
        if code:
            out.add(code.upper())
    return out


def _has_icd(codes: set[str], prefixes: tuple[str, ...]) -> bool:
    return any(c.startswith(p) for c in codes for p in prefixes)


_HT_ICD = ("I10", "I11", "I12", "I13", "I15")
_DM_ICD = ("E10", "E11", "E12", "E13", "E14")
_TB_ICD = ("A15", "A16", "A17", "A18", "A19")
_HIV_ICD = ("B20", "B21", "B22", "B23", "B24")
_SYPH_ICD = ("A50", "A51", "A52", "A53")
_HEPB_ICD = ("B16", "B18.0", "B18.1")
_HEPC_ICD = ("B17.1", "B18.2")


def _uniform(values: list[Any]) -> bool:
    """R-UNIFORM: >= 4 answers, all identical (a "check to all" row)."""
    vals = [_clean(v) for v in values if _clean(v) is not None]
    return len(vals) >= 4 and len(set(vals)) == 1


def _lab_results(b: dict) -> dict[str, str]:
    """``{normalised test name: result}`` — last non-empty result per test. Matched on the EXACT leaf name (hb != hba1c)."""
    out: dict[str, str] = {}
    for row in b.get("lab") or []:
        name, res = _norm((row or {}).get("test")), _clean((row or {}).get("result"))
        if name and res:
            out[name] = res
    return out


def _lab_num(results: dict[str, str], aliases: tuple[str, ...]) -> int | float | None:
    for a in aliases:
        if _norm(a) in results:
            n = _num(results[_norm(a)])
            if n is not None:
                return n
    return None


_LAB_CHOL = ("kolesterol total", "cholesterol total", "kolesterol", "cholesterol")
_LAB_HDL = ("hdl cholesterol", "hdl kolesterol", "hdl")
_LAB_LDL = ("ldl cholesterol", "ldl kolesterol", "ldl")
_LAB_TG = ("trigliserida", "trigliserid", "triglycerides")
_LAB_HB = ("hemoglobin", "hb", "hb (hemoglobin)", "hemoglobin (hgb)", "hemoglobin [mass/volume] in blood")
_LAB_CREAT = ("kreatinin", "creatinine")
_LAB_UREUM = ("ureum", "urea")
_LAB_EGFR = ("egfr", "e-lfg", "e-lfg (ckd-epi)")
_LAB_SGOT = ("sgot", "ast", "sgot (ast)")
_LAB_PLT = ("trombosit", "trombosit (plt)", "platelet", "plt")
_LAB_ALB_URIN = ("microalbuminuria", "microalbuminuria kuantitatif", "albumin urin")


def _lab_rapid(results: dict[str, str], names: tuple[str, ...], pos: str, neg: str) -> str | None:
    """A rapid-test lab result ("POSITIF"/"NEGATIF"/"REAKTIF"/"NON REAKTIF") -> the ASIK option ``pos`` / ``neg``."""
    for n in names:
        val = _norm(results.get(_norm(n)))
        if not val:
            continue
        if val in ("positif", "reaktif", "positive") or val.startswith("reaktif"):
            return pos
        if val in ("negatif", "nonreaktif", "negative", "tidakreaktif"):
            return neg
    return None


# ─── identity ─────────────────────────────────────────────────────────────────


def _map_identitas(b: dict) -> dict[str, Any]:
    p = b.get("patient") or {}
    out: dict[str, Any] = {}
    nik = _clean((p.get("identity") or {}).get("number"))
    if nik:
        out["NIK"] = nik
    if _clean(p.get("name")):
        out["Nama"] = _clean(p.get("name"))
    tgl = _indo_date(p.get("date_of_birth"))
    if tgl:
        out["Tanggal Lahir"] = tgl
    if _clean(p.get("place_of_birth")):
        out["Tempat Lahir"] = _clean(p.get("place_of_birth"))
    g = _gender(b)
    if g:
        out["Jenis Kelamin"] = g
    alamat = _clean((p.get("address") or {}).get("text"))
    if alamat:
        out["Alamat Domisili"] = alamat
    return out


# ─── adult core: tekanan darah / gula darah / gizi / demografi ────────────────

_F_TD = "Tekanan Darah Dewasa Lansia"
_F_GD = "Pemeriksaan Gula Darah Dewasa Lansia"


def _ht_history(scr: dict) -> str | None:
    """"Riwayat Pribadi Hipertensi" is question 1 of the hypertension screening (R-UNIFORM applies)."""
    ht = scr.get("hipertensi") or {}
    if _uniform([ht.get(f"question{i}_anamnesis") for i in range(1, 9)]):
        return None
    return _yatidak(ht.get("question1_anamnesis"))


def _dm_history(scr: dict) -> str | None:
    """"Riwayat Pribadi Diabetes Melitus" is question 5 of the diabetes screening (R-UNIFORM applies)."""
    dm = scr.get("diabetes_melitus") or {}
    if _uniform([dm.get(f"question{i}_anamnesis") for i in range(1, 13)]):
        return None
    return _yatidak(dm.get("question5_anamnesis"))


def _map_tekanan_darah(b: dict, scr: dict) -> dict[str, Any]:
    v = _vitals(b)
    ht = scr.get("hipertensi") or {}
    out: dict[str, Any] = {}
    riwayat = _ht_history(scr)
    if riwayat:
        out[_q(_F_TD, "Apakah Anda pernah dinyatakan tekanan darah tinggi")] = riwayat
    sis = _num(v.get("systole")) or (_num(ht.get("sistole")) or None)
    dia = _num(v.get("diastole")) or (_num(ht.get("diastole")) or None)
    if sis:
        out[_q(_F_TD, "Tekanan Darah Sistolik")] = sis
    if dia:
        out[_q(_F_TD, "Tekanan darah diastolik")] = dia
    # columns added for the ASIK CKG form (db/2026/20261014-skrining-asik-ckg); NULL until a nurse answers
    _put(out, _q(_F_TD, "Tekanan Darah Sistolik Ke-2"), _pos(ht.get("sistole_2")))
    _put(out, _q(_F_TD, "Tekanan darah diastolik ke-2"), _pos(ht.get("diastole_2")))
    if riwayat == "Ya":                  # ASIK reveals the duration only after "Ya"
        _put(out, _q(_F_TD, "Sudah Berapa Bulan Anda Didiagnosis Hipertensi"), _pos(ht.get("lama_hipertensi_bulan")))
    return out


def _map_gula_darah(b: dict, scr: dict) -> dict[str, Any]:
    v = _vitals(b)
    dm = scr.get("diabetes_melitus") or {}
    out: dict[str, Any] = {}
    riwayat = _dm_history(scr)
    if riwayat:
        out[_q(_F_GD, "Apakah Anda pernah dinyatakan diabetes")] = riwayat
    gds = _num(v.get("gds")) or _num(dm.get("gds_hasil"))
    gdp = _num(v.get("gdp")) or _num(dm.get("gdp_hasil"))
    if gds:
        out[_q(_F_GD, "Gula Darah Sewaktu (GDS) (mg/dl)")] = gds
    if gdp:
        out[_q(_F_GD, "Gula Darah Puasa (GDP)")] = gdp
    _put(out, _q(_F_GD, "Gula Darah Sewaktu Kedua"), _pos(dm.get("gds_2")))
    _put(out, _q(_F_GD, "Gula Darah 2 Jam PP"), _pos(dm.get("gula_darah_2jam_pp")))
    if riwayat == "Ya":
        _put(out, _q(_F_GD, "Sudah Berapa Bulan Anda Didiagnosis Diabetes"), _pos(dm.get("lama_diabetes_bulan")))
    return out


def _map_gizi(b: dict, scr: dict, gender: str) -> tuple[str, dict[str, Any]]:
    form = ("Gizi (BB - TB - Lingkar Perut) Perempuan" if gender == "Perempuan"
            else "Gizi (BB - TB - Lingkar Perut) Laki-laki")
    v = _vitals(b)
    dm = scr.get("diabetes_melitus") or {}
    out: dict[str, Any] = {}
    bb = _num(v.get("weight_kg")) or _num(dm.get("bb"))
    tb = _num(v.get("height_cm")) or _num(dm.get("tb"))
    lp = _num(v.get("waist_cm")) or _num(dm.get("lingkar_perut"))
    if bb:
        out[_q(form, "Berat Badan (Kg)")] = bb
    if tb:
        out[_q(form, "Pengukuran Tinggi Badan (cm)")] = tb
    if lp:
        out[_q(form, "Pengukuran Lingkar Perut")] = lp
    return form, out


def _status_perkawinan(v: Any) -> str | None:
    s = (_clean(v) or "").lower()
    return {"belum menikah": "Belum Menikah", "belum kawin": "Belum Menikah", "sudah menikah": "Menikah", "menikah": "Menikah",
            "kawin": "Menikah", "cerai hidup": "Cerai Hidup", "cerai mati": "Cerai Mati", "janda": "Cerai Mati",
            "duda": "Cerai Mati", "janda/duda": "Cerai Mati"}.get(s)


def _map_demografi(b: dict, gender: str, years: int) -> tuple[str, dict[str, Any]]:
    kawin = _status_perkawinan((b.get("patient") or {}).get("marital_status"))
    if years >= 60:
        form = "Demografi Lansia"
    else:
        form = "Demografi Dewasa Perempuan" if gender == "Perempuan" else "Demografi Dewasa Laki-Laki"
    out: dict[str, Any] = {}
    if kawin:
        out[_q(form, "Status Perkawinan")] = kawin
    # R-DIAG: an active pregnancy record turns "hamil" ON; its absence is not a "Tidak".
    if gender == "Perempuan" and years < 60 and _program_rows(b, "kia", "hamil"):
        out[_q(form, "Apakah Anda sedang hamil?")] = "Ya"
    return form, out


# ─── PUMA / PPOK ──────────────────────────────────────────────────────────────

_F_PPOK = "Pemeriksaan PPOK (Skrining PUMA)"
_PUMA_YN = (("question4", "Apakah Anda pernah merasa napas pendek"),
            ("question5", "Apakah Anda biasanya mempunyai dahak"),
            ("question6", "Apakah Anda biasanya batuk"),
            ("question7", "Apakah Dokter atau tenaga medis lainnya"))
_PUMA_PACKYEAR = {0: "<20 bungkus per tahun", 1: "20-30 bungkus per tahun", 2: ">30 bungkus per tahun"}


def _map_ppok(scr: dict, resaved: bool = False) -> dict[str, Any]:
    p = scr.get("puma") or {}
    if not p:
        return {}
    smoking_cols = ("question_child_3_average", "question_child_3_year", "question_child_3_3")
    answered_cols = ("question4", "question5", "question6", "question7", *smoking_cols)
    # R-ZERO: evidence the row was really filled — a positive answer, or (sign-off 2026-10-05) a row saved again after it was created
    active = resaved or any(_positive(p.get(c)) for c in answered_cols)
    out: dict[str, Any] = {}
    for col, prefix in _PUMA_YN:
        n = _num(p.get(col))
        if n == 1:
            out[_q(_F_PPOK, prefix)] = "Ya"
        elif n == 0 and active:
            out[_q(_F_PPOK, prefix)] = "Tidak"
    smoker = any(_positive(p.get(c)) for c in smoking_cols)
    if smoker:
        out[_q(_F_PPOK, "Apakah anda sedang/mempunyai riwayat merokok?")] = "Iya"
        bucket = _num(p.get("question_child_3_3"))
        if bucket in _PUMA_PACKYEAR and _positive(p.get("question_child_3_average")) and _positive(p.get("question_child_3_year")):
            out[_q(_F_PPOK, "Jika Perokok Aktif, berapa bungkus per tahun?")] = _PUMA_PACKYEAR[bucket]
    elif active:
        out[_q(_F_PPOK, "Apakah anda sedang/mempunyai riwayat merokok?")] = "Tidak"
    return out


# ─── ear and eye ─────────────────────────────

_TELMAT_ADULT = ("Skrining Telinga dan Mata (=>40 tahun)", "Skrining Telinga dan Mata (18-39 tahun)")


def _map_telinga(b: dict, form: str) -> dict[str, Any]:
    """Hearing from ``satusehat_ptm_phase`` (NULLable, no default: NULL = unanswered, 0/1 = answered)."""
    rows = [r for r in _program_rows(b, "ptm", "fase_pendengaran")
            if any(r.get(c) is not None for c in ("serumen_impeksi_right", "serumen_impeksi_left", "omsk_congek_right_ear",
                                                  "omsk_congek_left_ear", "tajam_pendengaran_right", "tajam_pendengaran_left"))]
    if not rows:
        return {}
    r = rows[-1]
    out: dict[str, Any] = {}

    def flag(cols: tuple[str, ...], yes: str, no: str) -> str | None:
        vals = [_num(r.get(c)) for c in cols if _num(r.get(c)) is not None]
        if not vals:
            return None
        return yes if any(v == 1 for v in vals) else no

    ser = flag(("serumen_impeksi_right", "serumen_impeksi_left"), "Ada serumen impaksi", "Tidak ada serumen impaksi")
    inf = flag(("omsk_congek_right_ear", "omsk_congek_left_ear"), "Ada infeksi telinga", "Tidak ada infeksi telinga")
    if ser:
        out[_q(form, "Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?")] = ser
    if inf:
        out[_q(form, "Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?")] = inf
    tajam = [(_clean(r.get(c)) or "").lower() for c in ("tajam_pendengaran_right", "tajam_pendengaran_left") if _clean(r.get(c))]
    if tajam:
        if any("gangguan" in t for t in tajam):
            out[_q(form, "Hasil pemeriksaan tajam pendengaran")] = "Curiga gangguan pendengaran"
        elif all(t.startswith("normal") for t in tajam):
            out[_q(form, "Hasil pemeriksaan tajam pendengaran")] = "Normal"
    return out


_SUSPECT_CATARACT = "OV000393"          # "Suspek Katarak" in Medisy's snomed_kelainan_mata list
_VISUS_Q = "Apa hasil skrining tajam penglihatan?"


def _map_mata(b: dict, form: str) -> dict[str, Any]:
    """Eyes from ``satusehat_skrining_ptm_mata`` (screening key ``ptm_mata``).

    Visus is entered as a Snellen fraction (``visus_<side>`` / ``visus_<side>_denominator``, e.g. 6 / 12): the ratio decides, 6/12 (0.5)
    or better in every measured eye = Normal, worse in any eye = Curiga. Pupil: only "Suspek Katarak" is placed (Curiga Katarak);
    any other pupil entry, or none, is not turned into "Normal" (R-DIAG: absence of a finding is not a normal result)."""
    m = _screens(b).get("ptm_mata") or {}
    out: dict[str, Any] = {}
    ratios = []
    for side in ("kanan", "kiri"):
        num, den = _num(m.get(f"visus_{side}")), _num(m.get(f"visus_{side}_denominator"))
        if num and den and num > 0 and den > 0:
            ratios.append(num / den)
    if ratios:
        out[_q(form, _VISUS_Q)] = "Normal (visus 6/6 - 6/12)" if min(ratios) >= 0.5 - 1e-9 else "Curiga gangguan penglihatan (visus <6/12)"
    if "Hasil pemeriksaan pupil" in ASIK_FORM_LABELS[form] and _SUSPECT_CATARACT in {_clean(m.get("pupil_kanan")), _clean(m.get("pupil_kiri"))}:
        out[_q(form, "Hasil pemeriksaan pupil")] = "Curiga Katarak"
    return out

# ─── TB / HIV / hepatitis / syphilis ──────────────────────────────────────────

_F_TB_RISK = ("Faktor Risiko TB - Dewasa & Lansia", "Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)")
_F_TB_EXAM = "Pemeriksaan Tuberkulosis (Dewasa & Lansia)"


def _tbc(scr: dict) -> dict[str, Any]:
    t = scr.get("tbc") or {}
    return t if any(_clean(t.get(c)) for c in ("batuk", "kontak_tbc", "bb_turun", "demam", "berkeringat_malam")) else {}


_NO_COUGH = {"Faktor Risiko TB - Dewasa & Lansia": "Tidak\xa0batuk",              # the live ASIK option carries a NBSP here...
             "Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)": "Tidak batuk"}  # ...and a plain space here


_COUGH_YES = "Ya, lebih dari 2 minggu"


def _map_tb_risk(scr: dict) -> dict[str, dict[str, Any]]:
    """Cough question. Medisy records Ya/Tidak WITHOUT a duration; clinical sign-off (2026-10-05): a "Ya" means more than
    2 weeks, so it becomes the ASIK option "Ya, lebih dari 2 minggu"."""
    t = _tbc(scr)
    cough = {"Tidak": _NO_COUGH, "Ya": dict.fromkeys(_F_TB_RISK, _COUGH_YES)}.get(_yatidak(t.get("batuk")) or "", {})
    out = {form: ({_q(form, "Apakah Anda pernah atau sedang mengalami batuk"): cough[form]} if cough else {})
           for form in _F_TB_RISK}
    # the X-Ray form also asks the three TB symptoms and whether a chest X-ray was done; Medisy records the same questions
    xray = out[_F_TB_RISK[1]]
    _put(xray, _q(_F_TB_RISK[1], "Apakah berat badan Anda turun"), _yatidak(t.get("bb_turun")))
    _put(xray, _q(_F_TB_RISK[1], "Apakah Anda mengalami demam hilang timbul"), _yatidak(t.get("demam")))
    _put(xray, _q(_F_TB_RISK[1], "Apakah Anda mengalami berkeringat di malam hari"), _yatidak(t.get("berkeringat_malam")))
    if _clean(t.get("pemeriksaan_foto_toraks")) not in (None, "-") or _clean(t.get("abnormalitas_tbc")):
        xray[_q(_F_TB_RISK[1], "Apakah dilakukan pemeriksaan radiografi toraks?")] = "Ya"
    _put(xray, _q(_F_TB_RISK[1], "Apakah pasien memiliki pembesaran kelenjar getah bening"), _yatidak((scr.get("tbc") or {}).get("pembesaran_kgb")))
    return out


# Medisy test method (normalised) -> ASIK option; "Foto Toraks" and "Pemeriksaan Klinis" have no ASIK equivalent and are not sent.
_TB_METHOD = {_norm("TCM"): "TCM", _norm("BTA Mikroskopis"): "BTA", _norm("BTA"): "BTA"}


def _map_tb_exam(scr: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _put(out, _q(_F_TB_EXAM, "Metode Pemeriksaan (untuk terduga TB)"), _TB_METHOD.get(_norm((scr.get("tbc") or {}).get("metode_pemeriksaan_tb"))))
    # kontak_tbc holds the TB type of the contact, not the kind of contact: only "Tidak Ada" is sourceable.
    if _norm(_tbc(scr).get("kontak_tbc")) == _norm("Tidak Ada"):
        out[_q(_F_TB_EXAM, "Apakah anda ada kontak dengan pasien Tuberkulosis")] = "Tidak ada"
    return out


def _map_hiv(codes: set[str], labs: dict[str, str]) -> dict[str, Any]:
    f = "Pemeriksaan HIV"
    res = _lab_rapid(labs, ("anti hiv", "hiv", "rapid test hiv"), "Reaktif", "Non Reaktif")
    if res is None and _has_icd(codes, _HIV_ICD):
        res = "Reaktif"
    return {_q(f, "Hasil Pemeriksaan Rapid Test HIV"): res} if res else {}


def _map_sifilis(codes: set[str], labs: dict[str, str]) -> dict[str, Any]:
    f = "Pemeriksaan Sifilis"
    res = _lab_rapid(labs, ("rapid test sifilis", "sifilis", "syphilis", "tpha", "vdrl"), "Reaktif", "Non Reaktif")
    if res is None and _has_icd(codes, _SYPH_ICD):
        res = "Reaktif"
    return {_q(f, "Hasil Pemeriksaan Rapid Test Sifilis"): res} if res else {}


def _map_hepatitis(codes: set[str], labs: dict[str, str]) -> dict[str, Any]:
    f = "Pemeriksaan Hepatitis"
    out: dict[str, Any] = {}
    b = _lab_rapid(labs, ("hbsag", "rapid test hepatitis b"), "HBsAg Reaktif", "HBsAg Non Reaktif")
    if b is None and _has_icd(codes, _HEPB_ICD):
        b = "HBsAg Reaktif"
    c = _lab_rapid(labs, ("anti hcv", "rapid test hepatitis c"), "Anti HCV Reaktif", "Anti HCV Non Reaktif")
    if c is None and _has_icd(codes, _HEPC_ICD):
        c = "Anti HCV Reaktif"
    if b:
        out[_q(f, "Hasil Rapid Test Hepatitis B")] = b
    if c:
        out[_q(f, "Hasil Rapid Test Hepatitis C")] = c
    return out


# ─── dental ───────────────────────────────────────────────────────────────────


def _map_dental(scr: dict) -> dict[str, dict[str, Any]]:
    """Adult dental screening: Q3 "ada gigi yang hilang?" and Q4 "ada gigi yang berlubang?" (text Ya/Tidak)."""
    g = scr.get("gigi_dewasa") or {}
    f = "Skrining Karies dan Gigi Hilang"
    out: dict[str, Any] = {}
    karies, hilang = _yatidak(g.get("question4")), _yatidak(g.get("question3"))
    if karies:
        out[_q(f, "Gigi karies")] = karies
    if hilang:
        out[_q(f, "Gigi hilang/dicabut")] = hilang
    return {f: out, _F_PERIO: _map_periodontal(scr)}


_F_PERIO = "Skrining Penyakit Periodontal"
_PERIO = {_norm("Tidak Ada"): "Tidak", _norm("Gingivitis"): "Ya", _norm("Periodontitis"): "Ya"}


def _map_periodontal(scr: dict) -> dict[str, Any]:
    """Loose teeth (Ya/Tidak) and periodontal disease (none -> Tidak; gingivitis / periodontitis -> Ya, the same reading the
    ePuskesmas converter uses). The adult screening is used first, the elderly one when the adult one has no answer."""
    out: dict[str, Any] = {}
    for key in ("gigi_dewasa", "gigi_lansia"):
        g = scr.get(key) or {}
        _put(out, _q(_F_PERIO, "Gigi Goyang"), out.get(_q(_F_PERIO, "Gigi Goyang")) or _yatidak(g.get("gigi_goyang")))
        _put(out, _q(_F_PERIO, "Penyakit Periodontal"), out.get(_q(_F_PERIO, "Penyakit Periodontal")) or _PERIO.get(_norm(g.get("penyakit_periodontal"))))
    return out


# ─── labs (>= 40) ─────────────────────────────────────────────────────────────

_F_LIPID = "POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)"
_F_KERUSAKAN_GINJAL = "Skrining Kerusakan Ginjal (hanya untuk =>40 tahun dengan risiko HT DM)"
_F_FIBROSIS = "Pemeriksaan Fibrosis/Sirosis Hati"


def _put(d: dict, label: str, val: Any) -> None:
    if val is not None:
        d[label] = val


def _map_lab_forms(labs: dict[str, str], gender: str, years: int) -> ASIK_Result:
    out: ASIK_Result = {}
    lipid: dict[str, Any] = {}
    _put(lipid, _q(_F_LIPID, "Kolesterol Total"), _lab_num(labs, _LAB_CHOL))
    _put(lipid, _q(_F_LIPID, "HDL"), _lab_num(labs, _LAB_HDL))
    _put(lipid, _q(_F_LIPID, "LDL"), _lab_num(labs, _LAB_LDL))
    _put(lipid, _q(_F_LIPID, "Trigliserida"), _lab_num(labs, _LAB_TG))
    out[_F_LIPID] = lipid

    ginjal_form = ("Skrining Fungsi Ginjal " + ("Perempuan" if gender == "Perempuan" else "Laki-Laki")
                   + " (hanya untuk =>40 tahun dengan risiko HT DM)")
    ginjal: dict[str, Any] = {}
    _put(ginjal, _q(ginjal_form, "Hasil Pemeriksaan Kreatinin"), _lab_num(labs, _LAB_CREAT))
    _put(ginjal, _q(ginjal_form, "Hasil Pemeriksaan Ureum"), _lab_num(labs, _LAB_UREUM))
    _put(ginjal, _q(ginjal_form, "Nilai Hasil pemeriksaan (e-LFG"), _lab_num(labs, _LAB_EGFR))
    ginjal[_q(ginjal_form, "Usia")] = years          # derived from the bundle's own age, as the EPUS converter does
    out[ginjal_form] = ginjal

    rusak: dict[str, Any] = {}
    _put(rusak, _q(_F_KERUSAKAN_GINJAL, "Konsentrasi Albumin Urin"), _lab_num(labs, _LAB_ALB_URIN))
    out[_F_KERUSAKAN_GINJAL] = rusak

    fib: dict[str, Any] = {}
    _put(fib, _q(_F_FIBROSIS, "Nilai SGOT"), _lab_num(labs, _LAB_SGOT))
    _put(fib, _q(_F_FIBROSIS, "Pemeriksaan Trombosit"), _lab_num(labs, _LAB_PLT))
    out[_F_FIBROSIS] = fib
    return out


# ─── lung cancer (>= 45) ──────────────────────────────────────────────────────

_F_KP = "Skrining Kanker Paru (Usia =>45 thn)"
# Medisy option text (normalised) -> ASIK option text, per question. Same Kemenkes questionnaire, wording differs slightly.
_KP: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("question3", "Apakah pernah didiagnosis/menderita kanker?", {
        "ya,pernah>5tahunyanglalu": "Memiliki diagnosis kanker >5 tahun yang lalu",
        "ya,pernah<5tahunyanglalu": "Memiliki diagnosis kanker <5 tahun yang lalu",
        "tidakpernah": "Tidak pernah didiagnosis menderita kanker"}),
    ("question4", "Apakah ada keluarga", {
        "ya,kankerparu": "Memiliki keluarga yang terdiagnosis kanker paru",
        "ya,kankerjenislain": "Memiliki keluarga yang terdiagnosis kanker lain",
        "tidakada": "Tidak ada keluarga yang terdiagnosis kanker"}),
    ("question5", "Riwayat merokok/paparan asap rokok", {
        "perokokaktif,masihmerokok1tahunini": "Perokok aktif (dalam 1 tahun ini masih merokok)",
        "tidakmerokok": "Tidak pernah merokok"}),
    ("question6", "Riwayat tempat kerja", {
        "ya": "Ya, memiliki tempat kerja mengandung zat karsinogenik",
        "tidakyakin": "Tidak yakin tempat kerja mengandung zat karsinogenik",
        "tidak": "Tidak tempat kerja mengandung zat karsinogenik"}),
    ("question7", "Lingkungan tempat tinggal berpotensi tinggi", {
        "ya": "Memiliki tempat tinggal berpotensi tinggi",
        "tidakyakin": "Tidak yakin memiliki tempat tinggal berpotensi tinggi",
        "tidak": "Tidak memiliki tempat tinggal berpotensi tinggi"}),
    ("question8", "Lingkungan dalam rumah yang tidak sehat", {
        "ya": "Memiliki lingkungan dalam rumah yang tidak sehat",
        "tidakyakin": "Tidak yakin memiliki lingkungan dalam rumah yang tidak sehat",
        "tidak": "Memiliki lingkungan dalam rumah yang sehat"}),
    ("question9", "Pernah didiagnosis penyakit paru kronik?", {
        "ya,pernahtuberkulosis(tbc)": "Pernah didiagnosis tuberkulosis (TBC)",
        "tidak": "Tidak pernah didiagnosis penyakit paru kronik"}),
)
# "Bekas perokok, berhenti < 15 tahun lalu" (Medisy) vs "berhenti <10 tahun lalu" (ASIK): different thresholds, so NOT mapped.
# "Ya, pernah penyakit paru kronik (PPOK)" -> ASIK "...penyakit kronis lain (PPOK, ILD, dll)":
_KP_CHRONIC_OTHER = "Pernah didiagnosis penyakit kronis lain (PPOK, ILD, dll)"


def _map_kanker_paru(scr: dict) -> dict[str, Any]:
    k = scr.get("kanker_paru") or {}
    out: dict[str, Any] = {}
    for col, prefix, options in _KP:
        raw = _norm(k.get(col))
        if not raw:
            continue
        label = _q(_F_KP, prefix)
        by_norm = {_norm(opt): asik for opt, asik in options.items()}      # keys are folded exactly like the value
        if col == "question9" and raw.startswith(_norm("Ya, Pernah Penyakit Paru Kronik")):
            out[label] = _KP_CHRONIC_OTHER
        elif raw in by_norm:
            out[label] = by_norm[raw]
    return out


# ─── PTM questionnaire (SATUSEHAT Q0013 PTM risk factors, Q0019 lung cancer, Q0020 colorectal) ─────────────────────────────
# Medisy's "Faktor Risiko Penyakit Tidak Menular" modal. Answers are coded (answer_code); the display text is only a fallback
# because UAT data carries typos in it. Same-question mappings only (R-NOMATCH): where Medisy asks something else, nothing is emitted.

_PTM, _CA_PARU, _CA_USUS = "Q0013", "Q0019", "Q0020"
_SNOMED_SMOKER, _SNOMED_NONSMOKER = "77176002", "8392000"
_FREQ_CODES = {"QRI000014": "Tidak", "QRI000015": "Ya", "QRI000016": "Ya"}     # Tidak / Ya, tidak setiap hari / Ya, setiap hari


def _ptm_answers(b: dict) -> dict[tuple[str, str], dict]:
    """``{(questionnaire, question_code): row}`` — an answered row (it has an answer code or value) never loses to a header row."""
    out: dict[tuple[str, str], dict] = {}
    for r in (b.get("programs") or {}).get("ptm_questionnaire") or []:
        if not isinstance(r, dict):
            continue
        key = (_clean(r.get("questionnaire")) or "", _clean(r.get("question_code")) or "")
        if not key[0] or not key[1]:
            continue
        old = out.get(key)
        if old is None or _clean(r.get("answer_code")) or not _clean(old.get("answer_code")):
            out[key] = r
    return out


def _code(row: dict | None) -> str | None:
    return _clean((row or {}).get("answer_code"))


def _freq_yatidak(row: dict | None) -> str | None:
    """Tidak / Ya (either "Ya" frequency) from a frequency question; the label's first word is the fallback."""
    code = _code(row)
    if code in _FREQ_CODES:
        return _FREQ_CODES[code]
    word = (_clean((row or {}).get("answer_label")) or "").lower()
    return "Tidak" if word.startswith("tidak") else "Ya" if word.startswith("ya") else None


def _smoking_now(q: dict) -> str | None:
    """Smoker -> Ya; Non-smoker -> Tidak (an ex-smoker is a non-smoker here, the same call the ePuskesmas converter made); with no
    status, "never smoked" (1.1 = 0) -> Tidak. An ever-smoker without a status stays blank."""
    code = _code(q.get((_PTM, "1.4")))
    if code == _SNOMED_SMOKER:
        return "Ya"
    if code == _SNOMED_NONSMOKER:
        return "Tidak"
    ever = q.get((_PTM, "1.1"))
    if ever and _clean(ever.get("value")) in ("0", "false") and not code:
        return "Tidak"
    return None


_F_MEROKOK = "Perilaku Merokok"
_F_AKTIVITAS = "Tingkat Aktivitas Fisik (sedang dan berat)"
_F_KP_SCREEN = "Penapisan Risiko Kanker Paru"
_F_USUS = "Faktor Risiko Kanker Usus"


def _map_perilaku_merokok(q: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _put(out, _q(_F_MEROKOK, "Apakah Anda merokok dalam setahun terakhir ini?"), _smoking_now(q))
    _put(out, _q(_F_MEROKOK, "Apakah Anda terpapar asap rokok"), _freq_yatidak(q.get((_PTM, "1.5"))))
    return out


_MEDIUM = "Apakah Anda melakukan olahraga intensitas sedang"
_HEAVY = "Apakah Anda melakukan olahraga intensitas berat"


def _map_aktivitas_fisik(q: dict) -> dict[str, Any]:
    """"Kurang aktivitas fisik" (< 30 min/day or < 150 min/week) is the same PTM question the ePuskesmas converter used, with the
    same inheritance: insufficient -> no moderate and no vigorous exercise; sufficient -> moderate exercise "Ya" (Medisy, like
    ePuskesmas, does not split moderate from vigorous). Inherited rule, see MEDISY_TO_ASIK_RULES.md."""
    kurang = _freq_yatidak(q.get((_PTM, "1.10")))
    if kurang == "Ya":
        return {_q(_F_AKTIVITAS, _MEDIUM): "Tidak", _q(_F_AKTIVITAS, _HEAVY): "Tidak"}
    if kurang == "Tidak":
        return {_q(_F_AKTIVITAS, _MEDIUM): "Ya"}
    return {}


# Q0019 answer code -> the ASIK option text (the two systems share the SATUSEHAT value sets).
_KP_Q: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("1.1", "Apakah pernah didiagnosis/menderita kanker?", {
        "QRI000032": "Memiliki diagnosis kanker >5 tahun yang lalu", "QRI000033": "Memiliki diagnosis kanker <5 tahun yang lalu",
        "QRI000034": "Tidak pernah didiagnosis menderita kanker"}),
    ("1.2", "Apakah ada keluarga", {
        "429011007": "Memiliki keluarga yang terdiagnosis kanker paru", "QRI000035": "Memiliki keluarga yang terdiagnosis kanker lain",
        "QRI000036": "Tidak ada keluarga yang terdiagnosis kanker"}),
    ("1.3", "Riwayat merokok/paparan asap rokok", {
        "QRI000022": "Perokok aktif (dalam 1 tahun ini masih merokok)", "QRI000023": "Perokok/bekas perokok berhenti <10 tahun lalu",
        "16090771000119104": "Perokok pasif dari lingkungan rumah/tempat kerja", "266919005": "Tidak pernah merokok"}),
    ("1.4", "Riwayat tempat kerja", {
        "QRI000017": "Ya, memiliki tempat kerja mengandung zat karsinogenik",
        "QRI000018": "Tidak yakin tempat kerja mengandung zat karsinogenik", "QRI000019": "Tidak tempat kerja mengandung zat karsinogenik"}),
    ("1.5", "Lingkungan tempat tinggal berpotensi tinggi", {
        "QRI000024": "Memiliki tempat tinggal berpotensi tinggi", "QRI000025": "Tidak yakin memiliki tempat tinggal berpotensi tinggi",
        "QRI000026": "Tidak memiliki tempat tinggal berpotensi tinggi"}),
    ("1.6", "Lingkungan dalam rumah yang tidak sehat", {
        "QRI000027": "Memiliki lingkungan dalam rumah yang tidak sehat",
        "QRI000038": "Tidak yakin memiliki lingkungan dalam rumah yang tidak sehat",      # (sic) Medisy's code for this option is QRI000038
        "QRI000029": "Memiliki lingkungan dalam rumah yang sehat"}),
    ("1.7", "Pernah didiagnosis penyakit paru kronik?", {
        "161414005": "Pernah didiagnosis tuberkulosis (TBC)", "414415007": _KP_CHRONIC_OTHER,
        "160258000": "Tidak pernah didiagnosis penyakit paru kronik"}),
)


def _map_kanker_paru_q(q: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for link, prefix, options in _KP_Q:
        val = options.get(_code(q.get((_CA_PARU, link))) or "")
        if val:
            out[_q(_F_KP, prefix)] = val
    return out


def _map_kanker_paru_extra(scr: dict) -> dict[str, Any]:
    """"Penapisan Risiko Kanker Paru": the two Ya/Tidak questions the lung screening table now stores (NULL until answered)."""
    k = scr.get("kanker_paru") or {}
    out: dict[str, Any] = {}
    _put(out, _q(_F_KP_SCREEN, "Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir"), _yatidak(k.get("riwayat_merokok_15th")))
    _put(out, _q(_F_KP_SCREEN, "Apakah Anda sedang mengalami salah satu atau lebih gejala"), _yatidak(k.get("gejala_kanker_paru")))
    return out


_F_CO = "Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)"


def _map_kadar_co(scr: dict) -> dict[str, Any]:
    """Exhaled CO (ppm). The column is NULL until measured, so a typed 0 is a real reading here (not a form default)."""
    co = _num((scr.get("kanker_paru") or {}).get("kadar_co"))
    return {_q(_F_CO, "Kadar CO Pernapasan"): co} if co is not None and co >= 0 else {}


def _map_kanker_paru_screen(q: dict) -> dict[str, Any]:
    """"Penapisan Risiko Kanker Paru": only the questions Medisy asks in the same words."""
    out: dict[str, Any] = {}
    _put(out, _q(_F_KP_SCREEN, "Apakah Anda merokok dalam setahun terakhir ini?"), _smoking_now(q))
    _put(out, _q(_F_KP_SCREEN, "Apakah Anda terpapar atau menghirup asap rokok"), _freq_yatidak(q.get((_PTM, "1.5"))))
    # family history: "lung cancer" -> Ya; "other cancer" / "none" -> Tidak (Medisy offers lung / other / none as exclusive options)
    _put(out, _q(_F_KP_SCREEN, "Apakah memiliki riwayat kanker paru pada keluarga"),
         {"429011007": "Ya", "QRI000035": "Tidak", "QRI000036": "Tidak"}.get(_code(q.get((_CA_PARU, "1.2"))) or ""))
    _put(out, _q(_F_KP_SCREEN, "Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK?"),
         {"161414005": "Ya", "414415007": "Ya", "160258000": "Tidak"}.get(_code(q.get((_CA_PARU, "1.7"))) or ""))
    return out


_F_PAYUDARA = "Skrining Kanker Payudara"
_SADANIS = {_norm("Tidak ada benjolan"): "Normal", _norm("Benjolan"): "Ditemukan benjolan", _norm("Curiga Kanker"): "Curiga kanker"}
# Only the ultrasound results with an identical ASIK option; "Tumor Jinak (Fibroadenoma)" / "Curiga Keganasan" have no match and are not sent.
_USG = {_norm("Normal"): "Normal", _norm("Kista Simpleks"): "Simple cyst"}


def _map_payudara(scr: dict) -> dict[str, Any]:
    """SADANIS (clinical breast exam) from ``checkup_result1`` and the ultrasound result; "Pemeriksaan yang dilakukan" names the
    exam whose result is sent (SADANIS first, as the ePuskesmas converter does)."""
    p = scr.get("risiko_kanker_payudara") or {}
    out: dict[str, Any] = {}
    sadanis = _SADANIS.get(_norm(p.get("checkup_result1")))
    usg = _USG.get(_norm(p.get("hasil_usg_payudara")))
    if sadanis:
        out[_q(_F_PAYUDARA, "Pemeriksaan yang dilakukan")] = "SADANIS"
        out[_q(_F_PAYUDARA, "Hasil pemeriksaan SADANIS")] = sadanis
    if usg:
        out.setdefault(_q(_F_PAYUDARA, "Pemeriksaan yang dilakukan"), "USG Payudara")
        out[_q(_F_PAYUDARA, "Hasil pemeriksaan USG Payudara")] = usg
    return out


def _map_leher_rahim(scr: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _put(out, _q("Kanker Leher Rahim", "Apakah pernah melakukan hubungan intim/seksual"),
         _yatidak((scr.get("kanker_serviks") or {}).get("pernah_hubungan_seksual")))
    return out


def _map_kanker_usus(q: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    fam = _code(q.get((_CA_USUS, "1.1")))
    _put(out, _q(_F_USUS, "Apakah ada anggota keluarga Anda"), {"QRI000020": "Ya", "QRI000021": "Tidak"}.get(fam or ""))
    _put(out, _q(_F_USUS, "Apakah Anda merokok?"), _smoking_now(q))
    return out

# ─── heart ────────────────────────────────────────────────────────────────────


def _map_ekg(scr: dict) -> dict[str, Any]:
    raw = (_clean((scr.get("risiko_jantung") or {}).get("kardiovaskular_ekg")) or "").lower()
    # stored as "<n>, Normal" / "<n>, Tidak Normal"
    if "tidak normal" in raw or "abnormal" in raw:
        val = "Abnormal"
    elif "normal" in raw:
        val = "Normal"
    else:
        return {}
    return {_q("Hasil Pemeriksaan - Skrining Jantung", "Hasil Pemeriksaan EKG"): val}


# ─── lansia battery (>= 60) ───────────────────────────────────────────────────

_SKILAS_DEPRESI = "SKILAS Pemeriksaan Gejala Depresi - Lansia"
_SKILAS_MALNUTRISI = "SKILAS Malnutrisi"
_SKILAS_MOBILISASI = "SKILAS Mobilisasi - Lansia"
_SKILAS_KOGNITIF = "SKILAS Penurunan Kognitif - Lansia"
_F_BARTHEL = "Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia"
_F_MINICOG = "Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)"
_F_SPPB = "Mobilisasi - Pemeriksaan Lanjutan (SPPB)"
_F_MNA = "Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)"


# Medisy's own nutrition screening (`gizi`, MST-like) asks nearly the same two SKILAS questions. Sign-off 2026-10-05: map only the
# unambiguous answers, SKILAS's own answer wins. "Weight loss in 6 months": none -> Tidak; "not sure (clothes loose)" matches
# SKILAS's "or clothes became looser" -> Ya; 6 kg or more -> Ya; "1-5 kg" straddles SKILAS's 3 kg line -> blank.
# "Intake reduced by lack of appetite": Ya -> Ya; Tidak stays blank (SKILAS also asks about difficulty eating).
_GIZI_WEIGHT_LOSS = {_norm("tidak"): "Tidak", _norm("tidak yakin"): "Ya", _norm("6-10 kg"): "Ya", _norm("11-15 kg"): "Ya", _norm(">15 kg"): "Ya"}
_GIZI_APPETITE = {_norm("ya"): "Ya"}


def _map_skilas(scr: dict) -> dict[str, dict[str, Any]]:
    s = scr.get("skilas") or {}
    out: dict[str, dict[str, Any]] = {}

    def yn(col: str) -> str | None:
        return _yatidak(s.get(col))

    dep: dict[str, Any] = {}
    _put(dep, _q(_SKILAS_DEPRESI, "Apakah dalam 2 minggu terakhir Anda merasa sedih"), yn("question6a"))
    _put(dep, _q(_SKILAS_DEPRESI, "Apakah dalam 2 minggu terakhir Anda sedikit minat"), yn("question6b"))
    if dep:
        out[_SKILAS_DEPRESI] = dep
    mal: dict[str, Any] = {}
    gizi = scr.get("gizi") or {}
    _put(mal, _q(_SKILAS_MALNUTRISI, "Apakah berat badan Anda berkurang"), yn("question3a") or _GIZI_WEIGHT_LOSS.get(_norm(gizi.get("penurunan_bb"))))
    _put(mal, _q(_SKILAS_MALNUTRISI, "Apakah Anda hilang nafsu makan"), yn("question3b") or _GIZI_APPETITE.get(_norm(gizi.get("asupan_makanan"))))
    _put(mal, _q(_SKILAS_MALNUTRISI, "Apakah ukuran lingkar lengan atas"), yn("question3c"))
    if mal:
        out[_SKILAS_MALNUTRISI] = mal
    mob = yn("question2")      # POSITIVE question in Medisy too: "can the person stand 5 times in 14 s?"
    if mob:
        out[_SKILAS_MOBILISASI] = {_q(_SKILAS_MOBILISASI, "Tes Berdiri di kursi"): mob}
    # question1 is ONE radio holding either the recall outcome or the orientation outcome.
    kog: dict[str, Any] = {}
    q1 = _norm(s.get("question1"))
    if q1.startswith(_norm("Dapat mengulang")):
        kog[_q(_SKILAS_KOGNITIF, "Apakah dapat mengingat tiga kata")] = "Ya"
        kog[_q(_SKILAS_KOGNITIF, "Apakah peserta dapat mengingat tiga kata sebelumnya")] = "Ya"
    elif q1 == _norm("Tidak dapat mengulang ketiga kata"):
        kog[_q(_SKILAS_KOGNITIF, "Apakah dapat mengingat tiga kata")] = "Tidak"
        kog[_q(_SKILAS_KOGNITIF, "Apakah peserta dapat mengingat tiga kata sebelumnya")] = "Tidak"
    elif q1 == _norm("Semua pertanyaan dijawab tepat"):
        kog[_q(_SKILAS_KOGNITIF, "Tanggal berapakah hari ini")] = "Benar semua"
    elif q1 == _norm("Salah pada salah satu pertanyaan"):
        kog[_q(_SKILAS_KOGNITIF, "Tanggal berapakah hari ini")] = "Salah satu/Dua"
    if kog:
        out[_SKILAS_KOGNITIF] = kog
    return out


# ASIK Barthel option text per score, byte-exact from live ASIK data (2026-06-04 scan); Medisy item N -> ASIK question.
_BARTHEL: tuple[tuple[str, str, dict[int, str]], ...] = (
    ("question1", "Dapat mengendalikan rangsang buang air besar (BAB)?",
     {0: "Tidak terkendali/tak teratur (perlu pencahar)", 1: "Kadang-kadang tak terkendali (1 x / minggu)", 2: "Terkendali teratur"}),
    ("question2", "Dapat mengendalikan rangsang berkemih/buar air kecil (BAK)?",
     {0: "Tak terkendali atau pakai kateter", 1: "Kadang-kadang tak terkendali (hanya 1 x / 24 jam)", 2: "Mandiri"}),
    ("question3", "Membersihkan diri (seka wajah, sisir rambut, sikat gigi)?",
     {0: "Butuh pertolongan orang lain", 1: "Mandiri"}),
    ("question4", "Penggunaan jamban (keluar masuk jamban, melepas/memakai celana, membersihkan, menyiram)?",
     {0: "Tergantung pertolongan orang lain",
      1: "Perlu pertolongan pada beberapa kegiatan tetapi dapat mengerjakan sendiri beberapa kegiatan yang lain",
      2: "Mandiri"}),
    ("question5", "Makan dan Minum (jika makan harus berupa potongan, dianggap dibantu)",
     {0: "Tidak mampu", 1: "Perlu ditolong memotong makanan", 2: "Mandiri"}),
    ("question6", "Berubah sikap dari berbaring ke duduk",
     {0: "Tidak mampu", 1: "Perlu banyak bantuan untuk bisa duduk (2 orang)", 2: "Bantuan minimal 1 orang", 3: "Mandiri"}),
    ("question7", "Berpindah/berjalan",
     {0: "Tidak mampu", 1: "Bisa (pindah) dengan kursi roda", 2: "Bantuan minimal 1 orang", 3: "Mandiri"}),
    ("question8", "Memakai baju",
     {0: "Tergantung orang lain", 1: "Sebagian dibantu (misalnya: mengancing baju)", 2: "Mandiri"}),
    ("question9", "Naik turun tangga", {0: "Tidak mampu", 1: "Butuh pertolongan", 2: "Mandiri"}),
    ("question10", "Mandi", {0: "Tergantung orang lain", 1: "Mandiri"}),
)


def _map_barthel(scr: dict) -> dict[str, Any]:
    """Medisy stores "<score>, <text>" (or just the score on older rows); NULL = unanswered, so the score is trustworthy."""
    a = scr.get("activity_living") or {}
    out: dict[str, Any] = {}
    for col, label, by_score in _BARTHEL:
        raw = _clean(a.get(col))
        m = re.match(r"^(\d+)\b", raw or "")
        if m and int(m.group(1)) in by_score:
            out[_q(_F_BARTHEL, label)] = by_score[int(m.group(1))]
    return out


_MINICOG_RECALL = {"0": "Tidak dapat mengingat/mengulang kata", "1": "Benar 1 kata", "2": "Benar 2 Kata", "3": "Benar semua kata"}


# Medisy clock-drawing result -> ASIK "Benar" / "Salah" (the same drawing test, different wording).
_CLOCK = {_norm("Normal"): "Benar", _norm("Abnormal"): "Salah"}


def _map_minicog(scr: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.match(r"^(\d)\b", _clean((scr.get("pemeriksaan_cog") or {}).get("instruction1")) or "")
    if m and m.group(1) in _MINICOG_RECALL:
        out[_q(_F_MINICOG, "Mintalah pasien untuk MENGULANG")] = _MINICOG_RECALL[m.group(1)]
    # the Mini-Cog table first, the SKILAS cognitive step when the Mini-Cog one has no answer
    clock = _CLOCK.get(_norm((scr.get("pemeriksaan_cog") or {}).get("clock_drawing_test"))) \
        or _CLOCK.get(_norm((scr.get("skilas") or {}).get("clock_drawing_test")))
    _put(out, _q(_F_MINICOG, "Katakan seluruh frase berikut"), clock)
    return out


# Medisy option text (normalised) -> byte-exact ASIK option, per SPPB item / MNA item.
_SPPB: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("question1a", "Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri berdampingan",
     {"bertahan10detik": "Bertahan 10 detik", "tidakbertahan10detik": "Tidak bertahan 10 detik"}),
    ("question1b", "Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri semi tandem",
     {"bertahan10detik": "Bertahan 10 detik", "tidakbertahan10detik": "Tidak bertahan 10 detik",
      "tidakdilakukan": "Tidak dilakukan"}),
    ("question1c", "Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri Tandem",
     {"bertahan10detik": "Bertahan 10 detik", "bertahan3-9.99detik": "Bertahan 3 - 9.99 detik",
      "bertahan<3detik": "Bertahan < 3 detik"}),
    ("question2", "tes kecepatan berjalan: Waktu untuk berjalan sejauh empat meter",
     {"<4.82detik": "4,82 detik", "4.82detik": "4,82 detik", "4.82detik-6.20detik": "4.83 - 6.20 detik",
      "6.21detik-8.70detik": "6.21 - 8.70 detik", ">8.70detik": ">8,70 detik", "8.70detik": ">8,70 detik"}),
    ("question3", "Tes berdiri dari kursi: Waktu untuk bangkit dari kursi lima kali",
     {"<11.19detik": "<11.19 detik", "11.19detik": "<11.19 detik", "11.2-13.69detik": "11.2 - 13,69 detik",
      "13.7-16.69detik": "13.7 - 16.69 detik", "16.7-59.9detik": "16.7 - 59.9 detik"}),
)
_MNA: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("penapisan1", "Apakah anda mengalami penurunan asupan makanan dalam 3 bulan terakhir",
     {"nafsumakanyangsangatberkurang": "Nafsu Makan Yang Sangat Berkurang",
      "nafsumakansedikitberkurang(sedang)": "Nafsu Makan Sedikit Berkurang"}),
    ("penapisan2", "Penurunan berat badan dalam tiga bulan terakhir",
     {"penurunanberatbadanlebihdari3kg": "Penurunan BB > 3 Kg", "tidaktahu": "Tidak Tahu",
      "penurunanberatbadan1-3kg": "Penurunan BB antara 1 - 3 Kg"}),
    ("penapisan3", "Kemampuan melakukan mobilitas",
     {"harusberbaringditempattidurataumenggunakankursiroda": "Harus berbaring di tempat tidur atau menggunakan kursi roda",
      "bisakeluardaritempattidurataukursiroda,tetapitidakbisakeluarrumah":
          "Bisa bangun dari tempat tidur atau kursi roda, tetapi tidak bisa keluar rumah",
      "bisakeluarrumah": "Bisa bepergian keluar rumah"}),
    ("penapisan4", "Menderita stress psikologis atau penyakit akut", {"ya": "Ya", "tidak": "Tidak"}),
    ("penapisan5", "Mengalami masalah neuropsikologis",
     {"demensiaberatataudepresiberat": "Dementia atau depresi berat", "demensiaringan": "Demensia/kepikunan ringan",
      "tidakadamasalahpsikologis": "Tidak ada masalah psikologis"}),
    ("penapisan6", "Berapa Nilai IMT",
     {"imt<19": "IMT <19", "imt19-<21": "IMT 19 - <21", "imt21-<23": "IMT 21 - <23", "imt23ataulebih": "IMT >= 23"}),
)


def _map_dropdown(form: str, source: dict, spec: tuple[tuple[str, str, dict[str, str]], ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col, prefix, options in spec:
        asik = {_norm(opt): val for opt, val in options.items()}.get(_norm(source.get(col)))
        if asik:
            out[_q(form, prefix)] = asik
    return out


# ─── female screening (>= 30) and catin ───────────────────────────────────────

_F_TETANUS = "Riwayat Imunisasi Tetanus(Status T) - Hanya untuk Catin"


def _map_tetanus(scr: dict) -> dict[str, Any]:
    m = re.search(r"\bT([1-5])\b", _clean((scr.get("imunisasi_tetanus_wus") or {}).get("imunisasi_tetanus")) or "")
    # T2 or higher => "minimal dua kali" (same rule the EPUS converter uses). Below T2 stays blank: ASIK has no "belum" option.
    if m and int(m.group(1)) >= 2:
        return {_q(_F_TETANUS, "Apakah anda pernah mendapatkan imunisasi tetanus"): "Pernah imunisasi tetanus minimal dua kali"}
    return {}


# ─── pediatric (< 18) ─────────────────────────────────────────────────────────

_F_GD_ANAK = "Pemeriksaan Gula Darah Anak"
_F_GD_REMAJA = "Pemeriksaan Gula Darah Remaja"
_SKIN_SHELLS = ("Pemeriksaan Penyakit Frambusia (untuk daerah endemis atau berisiko frambusia)",
                "Pemeriksaan Penyakit Kusta", "Pemeriksaan Penyakit Skabies")


def _pediatric(b: dict, scr: dict, years: int, codes: set[str]) -> ASIK_Result:
    v = _vitals(b)
    bb, tb = _num(v.get("weight_kg")) or None, _num(v.get("height_cm")) or None
    out: ASIK_Result = {}

    if years < 1:
        f = "Berat Lahir"
        bl: dict[str, Any] = {}
        _put(bl, _q(f, "Berat Badan Saat Ini"), bb)       # birth weight has no Medisy source
        out[f] = bl
        out["Pemeriksaan PJB"] = {}
    if 1 <= years <= 4:
        f = "Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun"
        g: dict[str, Any] = {}
        _put(g, _q(f, "Berat Badan Balita"), bb)
        _put(g, _q(f, "Pengukuran Tinggi Badan (cm)"), tb)
        out[f] = g
    elif 5 <= years <= 6:
        f = "Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun"
        g = {}
        _put(g, _q(f, "Pengukuran Tinggi Badan (cm)"), tb)
        out[f] = g
    elif 7 <= years <= 17:
        f = "Gizi Anak Sekolah"
        g = {}
        _put(g, _q(f, "Berat Badan"), bb)
        _put(g, _q(f, "Tinggi Badan"), tb)
        out[f] = g

    if 7 <= years <= 17:
        f = "Tekanan Darah Anak dan Remaja"
        td: dict[str, Any] = {}
        _put(td, _q(f, "Tekanan Darah Sistol"), _num(v.get("systole")) or None)
        _put(td, _q(f, "Tekanan Darah Diastol"), _num(v.get("diastole")) or None)
        out[f] = td

    gd_form = _F_GD_REMAJA if 15 <= years <= 17 else _F_GD_ANAK if 2 <= years <= 14 else None
    if gd_form:
        gd: dict[str, Any] = {}
        if _has_icd(codes, _DM_ICD):                                                    # R-DIAG: only ever turns "Ya" on
            gd[_q(gd_form, "Apakah Anak Anda pernah dinyatakan diabetes")] = "Ya"
        _put(gd, _q(gd_form, "Gula Darah Sewaktu (GDS)"), _num(v.get("gds")) or None)
        out[gd_form] = gd

    if 1 <= years <= 17:
        out["Pemeriksaan Gigi - Anak"] = {}

    if 1 <= years <= 9:
        f = "Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun)"
        t = _tbc(scr)
        tb_out: dict[str, Any] = {}
        _put(tb_out, _q(f, "Apakah berat badan anak Anda turun"), _yatidak(t.get("bb_turun")))
        _put(tb_out, _q(f, "Apakah anak anda mengalami demam hilang timbul"), _yatidak(t.get("demam")))
        if _clean(t.get("pemeriksaan_foto_toraks")) not in (None, "-") or _clean(t.get("abnormalitas_tbc")):
            tb_out[_q(f, "Apakah dilakukan pemeriksaan radiografi toraks?")] = "Ya"
        out[f] = tb_out
        out["Pemeriksaan Tuberkulosis Anak"] = (
            {_q("Pemeriksaan Tuberkulosis Anak", "Apakah anda ada kontak"): "Tidak ada"}
            if _norm(t.get("kontak_tbc")) == _norm("Tidak Ada") else {}
        )

    for shell in _SKIN_SHELLS:
        out[shell] = {}
    if _has_icd(codes, _SYPH_ICD):
        f = "Penapisan dan Pemeriksaan Sifilis Anak"
        out[f] = {_q(f, "Hasil Pemeriksaan Rapid Test Sifilis"): "Reaktif"}
    return out


# ─── public entry point ───────────────────────────────────────────────────────


def medisy_to_asik(bundle: dict) -> ASIK_Result:
    """Convert one stored Medisy bundle to ASIK form shape. Only forms the patient is eligible for (age / sex) are emitted;
    an unfillable-but-eligible form is an empty ``{}`` shell so the convert preview still shows it."""
    if not isinstance(bundle, dict):
        return {}
    gender, years = _gender(bundle), _years(bundle)
    out: ASIK_Result = {}

    identitas = _map_identitas(bundle)
    if identitas:
        out["identitas_pasien"] = identitas
    if gender is None or years is None:
        return out                       # klaster undecidable: identity only (same as the EPUS converter)

    scr = _screens(bundle)
    codes = _icd_codes(bundle)
    labs = _lab_results(bundle)

    if years < 18:
        out.update(_pediatric(bundle, scr, years, codes))
        return out

    out[_F_TD] = _map_tekanan_darah(bundle, scr)
    out[_F_GD] = _map_gula_darah(bundle, scr)
    gizi_form, gizi = _map_gizi(bundle, scr, gender)
    out[gizi_form] = gizi

    if years >= 40:
        out[_F_PPOK] = _map_ppok(scr, _was_resaved(bundle, "puma"))

    demo_form, demo = _map_demografi(bundle, gender, years)
    out[demo_form] = demo

    telmat = _TELMAT_ADULT[0] if years >= 40 else _TELMAT_ADULT[1]
    out[telmat] = {**_map_telinga(bundle, telmat), **_map_mata(bundle, telmat)}
    ptm_q = _ptm_answers(bundle)

    out.update(_map_tb_risk(scr))
    out[_F_TB_EXAM] = _map_tb_exam(scr)
    out["Pemeriksaan HIV"] = _map_hiv(codes, labs)
    out["Pemeriksaan Sifilis"] = _map_sifilis(codes, labs)
    out["Pemeriksaan Hepatitis"] = _map_hepatitis(codes, labs)

    # Forms the live klaster runs but Medisy cannot fill (R-NOMATCH): empty shells so eligibility shows in the preview.
    for shell in ("Perilaku Merokok", "Tingkat Aktivitas Fisik (sedang dan berat)", "Kesehatan Jiwa", *_SKIN_SHELLS, "Hati"):
        out[shell] = {}
    out[_F_CO] = _map_kadar_co(scr)
    out[_F_MEROKOK] = _map_perilaku_merokok(ptm_q)
    out[_F_AKTIVITAS] = _map_aktivitas_fisik(ptm_q)
    out.update(_map_dental(scr))

    if years >= 40:
        out.update(_map_lab_forms(labs, gender, years))

    ht_or_dm = _has_icd(codes, _HT_ICD + _DM_ICD) or _ht_history(scr) == "Ya" or _dm_history(scr) == "Ya"
    if years >= 45:
        out[_F_KP] = {**_map_kanker_paru_q(ptm_q), **_map_kanker_paru(scr)}        # the screening table wins over the questionnaire
        out[_F_KP_SCREEN] = {**_map_kanker_paru_screen(ptm_q), **_map_kanker_paru_extra(scr)}
        out[_F_USUS] = _map_kanker_usus(ptm_q)
        out["Pemeriksaan Lanjutan Kanker Usus"] = {}
        out["Hasil Pemeriksaan - Skrining Jantung"] = _map_ekg(scr)
    elif ht_or_dm:
        out["Hasil Pemeriksaan - Skrining Jantung"] = _map_ekg(scr)

    if years >= 60:
        for shell in (_SKILAS_MOBILISASI, _SKILAS_KOGNITIF, _SKILAS_DEPRESI, _SKILAS_MALNUTRISI, _F_BARTHEL, _F_SPPB, _F_MNA,
                      "Penurunan Kognitif - Tindak Lanjut (AD-8 INA)", _F_MINICOG, "Pemeriksaan Gejala Depresi - Pemeriksaan Lanjutan"):
            out[shell] = {}
        for form, fields in _map_skilas(scr).items():
            out[form] = fields
        out[_F_BARTHEL] = _map_barthel(scr)
        out[_F_MINICOG] = _map_minicog(scr)
        out[_F_SPPB] = _map_dropdown(_F_SPPB, scr.get("short_physical_performance") or {}, _SPPB)
        out[_F_MNA] = _map_dropdown(_F_MNA, scr.get("pengkajian_nutrisi") or {}, _MNA)

    if gender == "Perempuan":
        if years >= 30:
            out["Hasil Pemeriksaan HPV-DNA"] = {}
            out["Kanker Leher Rahim"] = _map_leher_rahim(scr)
            out[_F_PAYUDARA] = _map_payudara(scr)
        catin: dict[str, Any] = {}
        _put(catin, _q("Pemeriksaan Calon Pengantin Perempuan", "Kadar Hemoglobin"), _lab_num(labs, _LAB_HB))
        out["Pemeriksaan Calon Pengantin Perempuan"] = catin
        out[_F_TETANUS] = _map_tetanus(scr)

    return out


# ─── breadcrumbs ──────────────────────────────────────────────────────────────

# Every ASIK field the converter can emit, mapped to the bundle path it comes from (None = no Medisy source / computed).
MEDISY_BREADCRUMBS: dict[str, dict[str, str | None]] = {form: {label: None for label in labels}
                                                         for form, labels in ASIK_FORM_LABELS.items()}


def _bc(form: str, prefix: str, path: str) -> None:
    MEDISY_BREADCRUMBS[form][_q(form, prefix)] = path


_VIT = "anamnesis.vitals."
for _f, _p, _path in (
    ("identitas_pasien", "NIK", "patient.identity.number (type KTP/NIK, non-empty)"),
    ("identitas_pasien", "Nama", "patient.name"),
    ("identitas_pasien", "Tanggal Lahir", "patient.date_of_birth"),
    ("identitas_pasien", "Tempat Lahir", "patient.place_of_birth"),
    ("identitas_pasien", "Jenis Kelamin", "patient.gender (1=L, 2=P)"),
    ("identitas_pasien", "Alamat Domisili", "patient.address.text"),
    (_F_TD, "Apakah Anda pernah dinyatakan tekanan darah tinggi", "screenings[hipertensi].question1_anamnesis (R-UNIFORM)"),
    (_F_TD, "Tekanan Darah Sistolik", _VIT + "systole (fallback screenings[hipertensi].sistole)"),
    (_F_TD, "Tekanan darah diastolik", _VIT + "diastole (fallback screenings[hipertensi].diastole)"),
    (_F_GD, "Apakah Anda pernah dinyatakan diabetes", "screenings[diabetes_melitus].question5_anamnesis (R-UNIFORM)"),
    (_F_GD, "Gula Darah Sewaktu (GDS) (mg/dl)", _VIT + "gds (fallback screenings[diabetes_melitus].gds_hasil)"),
    (_F_GD, "Gula Darah Puasa (GDP)", _VIT + "gdp (fallback screenings[diabetes_melitus].gdp_hasil)"),
    (_F_PPOK, "Apakah anda sedang/mempunyai riwayat merokok?", "screenings[puma].question_child_3_* (R-ZERO)"),
    (_F_PPOK, "Apakah Anda pernah merasa napas pendek", "screenings[puma].question4 (R-ZERO)"),
    (_F_PPOK, "Apakah Anda biasanya mempunyai dahak", "screenings[puma].question5 (R-ZERO)"),
    (_F_PPOK, "Apakah Anda biasanya batuk", "screenings[puma].question6 (R-ZERO)"),
    (_F_PPOK, "Apakah Dokter atau tenaga medis lainnya", "screenings[puma].question7 (R-ZERO)"),
    (_F_PPOK, "Jika Perokok Aktif, berapa bungkus per tahun?", "screenings[puma].question_child_3_3 (smokers only)"),
    (_F_KP, "Apakah pernah didiagnosis/menderita kanker?", "screenings[kanker_paru].question3"),
    (_F_KP, "Apakah ada keluarga", "screenings[kanker_paru].question4"),
    (_F_KP, "Riwayat merokok/paparan asap rokok", "screenings[kanker_paru].question5 (only options with identical meaning)"),
    (_F_KP, "Riwayat tempat kerja", "screenings[kanker_paru].question6"),
    (_F_KP, "Lingkungan tempat tinggal berpotensi tinggi", "screenings[kanker_paru].question7"),
    (_F_KP, "Lingkungan dalam rumah yang tidak sehat", "screenings[kanker_paru].question8"),
    (_F_KP, "Pernah didiagnosis penyakit paru kronik?", "screenings[kanker_paru].question9"),
    ("Hasil Pemeriksaan - Skrining Jantung", "Hasil Pemeriksaan EKG", "screenings[risiko_jantung].kardiovaskular_ekg"),
    ("Pemeriksaan HIV", "Hasil Pemeriksaan Rapid Test HIV", "lab[ANTI HIV].result (R-DIAG: or diagnoses B20-B24 -> Reaktif)"),
    ("Pemeriksaan Sifilis", "Hasil Pemeriksaan Rapid Test Sifilis", "lab[sifilis].result (R-DIAG: or diagnoses A50-A53 -> Reaktif)"),
    ("Pemeriksaan Hepatitis", "Hasil Rapid Test Hepatitis B", "lab[HBsAg].result (R-DIAG: or diagnoses B16/B18.0/B18.1 -> Reaktif)"),
    ("Pemeriksaan Hepatitis", "Hasil Rapid Test Hepatitis C", "lab[Anti HCV].result (R-DIAG: or diagnoses B17.1/B18.2 -> Reaktif)"),
    ("Skrining Karies dan Gigi Hilang", "Gigi karies", "screenings[gigi_dewasa].question4"),
    ("Skrining Karies dan Gigi Hilang", "Gigi hilang/dicabut", "screenings[gigi_dewasa].question3"),
    (_F_LIPID, "Kolesterol Total", "lab[KOLESTEROL TOTAL].result"),
    (_F_LIPID, "HDL", "lab[HDL CHOLESTEROL].result"),
    (_F_LIPID, "LDL", "lab[LDL CHOLESTEROL].result"),
    (_F_LIPID, "Trigliserida", "lab[TRIGLISERIDA].result"),
    (_F_FIBROSIS, "Nilai SGOT", "lab[SGOT].result"),
    (_F_FIBROSIS, "Pemeriksaan Trombosit", "lab[Trombosit].result"),
    (_F_KERUSAKAN_GINJAL, "Konsentrasi Albumin Urin", "lab[Microalbuminuria].result"),
    ("Pemeriksaan Calon Pengantin Perempuan", "Kadar Hemoglobin", "lab[Hemoglobin].result"),
    (_F_BARTHEL, "Dapat mengendalikan rangsang buang air besar", "screenings[activity_living].question1"),
    (_F_BARTHEL, "Dapat mengendalikan rangsang berkemih", "screenings[activity_living].question2"),
    (_F_BARTHEL, "Membersihkan diri", "screenings[activity_living].question3"),
    (_F_BARTHEL, "Penggunaan jamban", "screenings[activity_living].question4"),
    (_F_BARTHEL, "Makan dan Minum", "screenings[activity_living].question5"),
    (_F_BARTHEL, "Berubah sikap dari berbaring ke duduk", "screenings[activity_living].question6"),
    (_F_BARTHEL, "Berpindah/berjalan", "screenings[activity_living].question7"),
    (_F_BARTHEL, "Memakai baju", "screenings[activity_living].question8"),
    (_F_BARTHEL, "Naik turun tangga", "screenings[activity_living].question9"),
    (_F_BARTHEL, "Mandi", "screenings[activity_living].question10"),
    (_F_MINICOG, "Mintalah pasien untuk MENGULANG", "screenings[pemeriksaan_cog].instruction1"),
    (_SKILAS_DEPRESI, "Apakah dalam 2 minggu terakhir Anda merasa sedih", "screenings[skilas].question6a"),
    (_SKILAS_DEPRESI, "Apakah dalam 2 minggu terakhir Anda sedikit minat", "screenings[skilas].question6b"),
    (_SKILAS_MALNUTRISI, "Apakah berat badan Anda berkurang", "screenings[skilas].question3a / screenings[gizi].penurunan_bb (unambiguous answers only)"),
    (_SKILAS_MALNUTRISI, "Apakah Anda hilang nafsu makan", "screenings[skilas].question3b / screenings[gizi].asupan_makanan (Ya only)"),
    (_SKILAS_MALNUTRISI, "Apakah ukuran lingkar lengan atas", "screenings[skilas].question3c"),
    (_SKILAS_MOBILISASI, "Tes Berdiri di kursi", "screenings[skilas].question2"),
    (_SKILAS_KOGNITIF, "Apakah dapat mengingat tiga kata", "screenings[skilas].question1 (recall outcome)"),
    (_SKILAS_KOGNITIF, "Tanggal berapakah hari ini", "screenings[skilas].question1 (orientation outcome)"),
    (_SKILAS_KOGNITIF, "Apakah peserta dapat mengingat tiga kata sebelumnya", "screenings[skilas].question1 (recall outcome)"),
    (_F_TETANUS, "Apakah anda pernah mendapatkan imunisasi tetanus", "screenings[imunisasi_tetanus_wus].imunisasi_tetanus (>= T2)"),
    # columns added for the ASIK CKG forms (himed-app db/2026/20261013-add-ilp-screening-fields); NULL until a nurse answers
    (_F_TD, "Tekanan Darah Sistolik Ke-2", "screenings[hipertensi].sistole_2"),
    (_F_TD, "Tekanan darah diastolik ke-2", "screenings[hipertensi].diastole_2"),
    (_F_TD, "Sudah Berapa Bulan Anda Didiagnosis Hipertensi", "screenings[hipertensi].lama_hipertensi_bulan (only when the history answer is Ya)"),
    (_F_GD, "Gula Darah Sewaktu Kedua", "screenings[diabetes_melitus].gds_2"),
    (_F_GD, "Gula Darah 2 Jam PP", "screenings[diabetes_melitus].gula_darah_2jam_pp"),
    (_F_GD, "Sudah Berapa Bulan Anda Didiagnosis Diabetes", "screenings[diabetes_melitus].lama_diabetes_bulan (only when the history answer is Ya)"),
    (_F_TB_RISK[1], "Apakah pasien memiliki pembesaran kelenjar getah bening", "screenings[tbc].pembesaran_kgb"),
    (_F_TB_EXAM, "Metode Pemeriksaan (untuk terduga TB)", "screenings[tbc].metode_pemeriksaan_tb (TCM, BTA Mikroskopis only; Foto Toraks / Klinis have no ASIK option)"),
    (_F_PERIO, "Gigi Goyang", "screenings[gigi_dewasa | gigi_lansia].gigi_goyang"),
    (_F_PERIO, "Penyakit Periodontal", "screenings[gigi_dewasa | gigi_lansia].penyakit_periodontal (Tidak Ada -> Tidak; Gingivitis / Periodontitis -> Ya)"),
    (_F_KP_SCREEN, "Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir", "screenings[kanker_paru].riwayat_merokok_15th"),
    (_F_KP_SCREEN, "Apakah Anda sedang mengalami salah satu atau lebih gejala", "screenings[kanker_paru].gejala_kanker_paru"),
    (_F_CO, "Kadar CO Pernapasan", "screenings[kanker_paru].kadar_co"),
    (_F_PAYUDARA, "Pemeriksaan yang dilakukan", "screenings[risiko_kanker_payudara].checkup_result1 / hasil_usg_payudara (SADANIS first)"),
    (_F_PAYUDARA, "Hasil pemeriksaan SADANIS", "screenings[risiko_kanker_payudara].checkup_result1 (Tidak ada benjolan -> Normal; Benjolan; Curiga Kanker)"),
    (_F_PAYUDARA, "Hasil pemeriksaan USG Payudara", "screenings[risiko_kanker_payudara].hasil_usg_payudara (Normal; Kista Simpleks -> Simple cyst)"),
    ("Kanker Leher Rahim", "Apakah pernah melakukan hubungan intim/seksual", "screenings[kanker_serviks].pernah_hubungan_seksual"),
    (_F_MINICOG, "Katakan seluruh frase berikut", "screenings[pemeriksaan_cog | skilas].clock_drawing_test (Normal -> Benar; Abnormal -> Salah)"),
):
    _bc(_f, _p, _path)
for _form, _table, _spec in ((_F_SPPB, "short_physical_performance", _SPPB), (_F_MNA, "pengkajian_nutrisi", _MNA)):
    for _col, _prefix, _opts in _spec:
        _bc(_form, _prefix, f"screenings[{_table}].{_col}")

# Fields that exist on several form variants (gendered / age-banded / adult+pediatric): one loop each, so the variants cannot drift.
for _f in ("Gizi (BB - TB - Lingkar Perut) Laki-laki", "Gizi (BB - TB - Lingkar Perut) Perempuan"):
    _bc(_f, "Berat Badan (Kg)", _VIT + "weight_kg (fallback screenings[diabetes_melitus].bb)")
    _bc(_f, "Pengukuran Tinggi Badan (cm)", _VIT + "height_cm (fallback screenings[diabetes_melitus].tb)")
    _bc(_f, "Pengukuran Lingkar Perut", _VIT + "waist_cm (fallback screenings[diabetes_melitus].lingkar_perut)")
for _f in ("Demografi Dewasa Laki-Laki", "Demografi Dewasa Perempuan", "Demografi Lansia"):
    _bc(_f, "Status Perkawinan", "patient.marital_status")
_bc("Demografi Dewasa Perempuan", "Apakah Anda sedang hamil?", "programs.kia.hamil (an active record turns it on; absence is not 'Tidak')")
for _f in _TELMAT_ADULT:
    _bc(_f, "Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?", "programs.ptm.fase_pendengaran.serumen_impeksi_right/left")
    _bc(_f, "Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?", "programs.ptm.fase_pendengaran.omsk_congek_right_ear/left_ear")
    _bc(_f, "Hasil pemeriksaan tajam pendengaran", "programs.ptm.fase_pendengaran.tajam_pendengaran_right/left")
for _f in _F_TB_RISK:
    _bc(_f, "Apakah Anda pernah atau sedang mengalami batuk", "screenings[tbc].batuk (Tidak -> no cough; Ya -> '> 2 weeks' by clinical sign-off: Medisy has no duration)")
_bc(_F_TB_EXAM, "Apakah anda ada kontak dengan pasien Tuberkulosis", "screenings[tbc].kontak_tbc (only 'Tidak Ada')")
_bc("Pemeriksaan Tuberkulosis Anak", "Apakah anda ada kontak", "screenings[tbc].kontak_tbc (only 'Tidak Ada')")
for _f in ("Skrining Fungsi Ginjal Laki-Laki (hanya untuk =>40 tahun dengan risiko HT DM)",
           "Skrining Fungsi Ginjal Perempuan (hanya untuk =>40 tahun dengan risiko HT DM)"):
    _bc(_f, "Hasil Pemeriksaan Kreatinin", "lab[Kreatinin].result")
    _bc(_f, "Hasil Pemeriksaan Ureum", "lab[Ureum].result")
    _bc(_f, "Nilai Hasil pemeriksaan (e-LFG", "lab[eGFR].result")
    _bc(_f, "Usia", "patient.age.years (derived)")
_bc("Berat Lahir", "Berat Badan Saat Ini", _VIT + "weight_kg (birth weight has no Medisy source)")
_bc("Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun", "Berat Badan Balita", _VIT + "weight_kg")
_bc("Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun", "Pengukuran Tinggi Badan (cm)", _VIT + "height_cm")
_bc("Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun", "Pengukuran Tinggi Badan (cm)", _VIT + "height_cm")
_bc("Gizi Anak Sekolah", "Berat Badan", _VIT + "weight_kg")
_bc("Gizi Anak Sekolah", "Tinggi Badan", _VIT + "height_cm")
_bc("Tekanan Darah Anak dan Remaja", "Tekanan Darah Sistol", _VIT + "systole")
_bc("Tekanan Darah Anak dan Remaja", "Tekanan Darah Diastol", _VIT + "diastole")
for _f in (_F_GD_ANAK, _F_GD_REMAJA):
    _bc(_f, "Apakah Anak Anda pernah dinyatakan diabetes", "diagnoses / history.diagnoses ICD E10-E14 (R-DIAG: only turns 'Ya' on)")
    _bc(_f, "Gula Darah Sewaktu (GDS)", _VIT + "gds")
_f = "Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun)"
_bc(_f, "Apakah berat badan anak Anda turun", "screenings[tbc].bb_turun")
_bc(_f, "Apakah anak anda mengalami demam hilang timbul", "screenings[tbc].demam")
_bc(_f, "Apakah dilakukan pemeriksaan radiografi toraks?", "screenings[tbc].pemeriksaan_foto_toraks / abnormalitas_tbc")
_f = _F_TB_RISK[1]
_bc(_f, "Apakah berat badan Anda turun", "screenings[tbc].bb_turun")
_bc(_f, "Apakah Anda mengalami demam hilang timbul", "screenings[tbc].demam")
_bc(_f, "Apakah Anda mengalami berkeringat di malam hari", "screenings[tbc].berkeringat_malam")
_bc(_f, "Apakah dilakukan pemeriksaan radiografi toraks?", "screenings[tbc].pemeriksaan_foto_toraks / abnormalitas_tbc")
_bc("Penapisan dan Pemeriksaan Sifilis Anak", "Hasil Pemeriksaan Rapid Test Sifilis", "diagnoses / history.diagnoses ICD A50-A53 (R-DIAG)")

# PTM questionnaire, eye
_bc(_F_MEROKOK, "Apakah Anda merokok dalam setahun terakhir ini?", "programs.ptm_questionnaire[Q0013 1.4 Status merokok] (1.1 = 0 when never smoked)")
_bc(_F_MEROKOK, "Apakah Anda terpapar asap rokok", "programs.ptm_questionnaire[Q0013 1.5]")
_bc(_F_AKTIVITAS, _MEDIUM, "programs.ptm_questionnaire[Q0013 1.10] (inherited rule: sufficient activity -> Ya, insufficient -> Tidak)")
_bc(_F_AKTIVITAS, _HEAVY, "programs.ptm_questionnaire[Q0013 1.10] (inherited rule: insufficient activity -> Tidak)")
for _link, _prefix, _opts in _KP_Q:
    _label = _q(_F_KP, _prefix)
    MEDISY_BREADCRUMBS[_F_KP][_label] = f"{MEDISY_BREADCRUMBS[_F_KP][_label]} / programs.ptm_questionnaire[Q0019 {_link}]"
_bc(_F_KP_SCREEN, "Apakah Anda merokok dalam setahun terakhir ini?", "programs.ptm_questionnaire[Q0013 1.4 Status merokok]")
_bc(_F_KP_SCREEN, "Apakah Anda terpapar atau menghirup asap rokok", "programs.ptm_questionnaire[Q0013 1.5]")
_bc(_F_KP_SCREEN, "Apakah memiliki riwayat kanker paru pada keluarga", "programs.ptm_questionnaire[Q0019 1.2]")
_bc(_F_KP_SCREEN, "Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK?", "programs.ptm_questionnaire[Q0019 1.7]")
_bc(_F_USUS, "Apakah ada anggota keluarga Anda", "programs.ptm_questionnaire[Q0020 1.1]")
_bc(_F_USUS, "Apakah Anda merokok?", "programs.ptm_questionnaire[Q0013 1.4 Status merokok]")
for _f in _TELMAT_ADULT:
    _bc(_f, _VISUS_Q, "screenings[ptm_mata].visus_kanan/visus_kiri over *_denominator (Snellen ratio, 6/12 = Normal boundary)")
_bc(_TELMAT_ADULT[0], "Hasil pemeriksaan pupil", "screenings[ptm_mata].pupil_kanan/pupil_kiri (only OV000393 Suspek Katarak -> Curiga Katarak)")
