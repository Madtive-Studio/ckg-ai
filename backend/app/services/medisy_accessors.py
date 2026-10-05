"""Plain readers over a stored Medisy visit bundle, for the registries and dashboards (no ASIK form shape involved).

The registry scans and the GD Puasa / Hipertensi dashboards used to dig into the ePuskesmas blob (``tabs.PTM.fields…``); each of
them now asks here when ``is_medisy_blob`` says the blob is a Medisy bundle. Pure functions, defensive ``.get()`` everywhere:
a missing or reshaped field gives ``None`` / ``[]`` / ``False``, never an exception. Numbers are plain ``int | float``; callers
convert (``Decimal`` in the dashboards, ``float`` in the scans).

Same discipline as the converter (``MEDISY_TO_ASIK_RULES.md``): nothing is guessed, a value that Medisy does not hold is ``None``.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.medisy_to_asik import (
    _DM_ICD,
    _HT_ICD,
    _clean,
    _dm_history,
    _has_icd,
    _ht_history,
    _icd_codes,
    _num,
    _screens,
    _vitals,
)


def blood_pressure(b: dict) -> tuple[int | float | None, int | float | None]:
    """(systole, diastole): this visit's vitals, per field falling back to the hypertension screening row. 0 counts as missing."""
    v = _vitals(b)
    ht = _screens(b).get("hipertensi") or {}
    sis = _num(v.get("systole")) or _num(ht.get("sistole")) or None
    dia = _num(v.get("diastole")) or _num(ht.get("diastole")) or None
    return sis, dia


def has_hypertension_record(b: dict) -> bool:
    """A recorded hypertension diagnosis (ICD I10-I13/I15, this visit or earlier) or "Ya" to the history question (R-UNIFORM guarded)."""
    return _has_icd(_icd_codes(b), _HT_ICD) or _ht_history(_screens(b)) == "Ya"


def has_diabetes_record(b: dict) -> bool:
    """A recorded diabetes diagnosis (ICD E10-E14, this visit or earlier) or "Ya" to the history question (R-UNIFORM guarded)."""
    return _has_icd(_icd_codes(b), _DM_ICD) or _dm_history(_screens(b)) == "Ya"


def drug_names(b: dict) -> list[str]:
    """Names of the drugs prescribed at this visit, in order, de-duplicated (compound prescriptions contribute their ingredients)."""
    out: list[str] = []
    seen: set[str] = set()
    for p in b.get("prescriptions") or []:
        if not isinstance(p, dict):
            continue
        names = [p.get("drug")] + [i.get("drug") for i in (p.get("items") or []) if isinstance(i, dict)]
        for n in names:
            name = _clean(n)
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _lab_rows(b: dict) -> list[tuple[str, int | float]]:
    """``(lower-cased test name, numeric result)`` in order; rows without a numeric result are dropped."""
    out: list[tuple[str, int | float]] = []
    for row in b.get("lab") or []:
        if not isinstance(row, dict):
            continue
        val = _num(row.get("result"))
        name = (_clean(row.get("test")) or "").casefold()
        if name and val is not None:
            out.append((name, val))
    return out


def _last_lab(rows: list[tuple[str, int | float]], match) -> int | float | None:
    """The LAST matching result (a re-test on the same visit supersedes the earlier one)."""
    hit = None
    for name, val in rows:
        if match(name):
            hit = val
    return hit


def glucose(b: dict) -> dict[str, int | float | None]:
    """``{gds1, gds2, gdp, gd2pp, hba1c}``. Vitals are the source of truth; the lab table fills the gaps (same rule as the
    ePuskesmas scan). Medisy stores one GDS, so ``gds2`` is always None."""
    v = _vitals(b)
    out: dict[str, int | float | None] = {
        "gds1": _num(v.get("gds")) or None, "gds2": None, "gdp": _num(v.get("gdp")) or None, "gd2pp": None,
        "hba1c": _num(v.get("hba1c")) or None,
    }
    rows = _lab_rows(b)
    if out["gdp"] is None:
        out["gdp"] = _last_lab(rows, _GDP_LAB)
    if out["hba1c"] is None:
        out["hba1c"] = _last_lab(rows, lambda n: "hba1c" in n or "hb1ac" in n)
    out["gd2pp"] = _last_lab(rows, lambda n: "2 jam pp" in n or "2jam pp" in n or "gd2pp" in n)
    return out


_GDP_LAB = lambda n: "glukosa puasa" in n or "gula puasa" in n or "gula darah puasa" in n  # noqa: E731


def lab_gdp(b: dict) -> int | float | None:
    """Fasting glucose from the lab table only (the latest result)."""
    return _last_lab(_lab_rows(b), _GDP_LAB)


def vitals_gdp(b: dict) -> int | float | None:
    """Fasting glucose recorded with the vitals only (the Medisy counterpart of the ePuskesmas PTM field)."""
    return _num(_vitals(b).get("gdp")) or None


def lipid(b: dict) -> dict[str, int | float | None]:
    """``{kol_total, ldl, hdl, trigliserida}`` from the lab table (the latest result per analyte)."""
    rows = _lab_rows(b)

    def last(*names: str):
        return _last_lab(rows, lambda n: n in names)

    return {
        "kol_total": last("kolesterol total", "cholesterol total", "kolesterol", "cholesterol"),
        "hdl": last("hdl cholesterol", "hdl kolesterol", "hdl"),
        "ldl": last("ldl cholesterol", "ldl kolesterol", "ldl"),
        "trigliserida": last("trigliserida", "trigliserid", "triglycerides"),
    }


def weight_height(b: dict) -> tuple[int | float | None, int | float | None]:
    """(weight kg, height cm) from the vitals; 0 counts as missing."""
    v = _vitals(b)
    return _num(v.get("weight_kg")) or None, _num(v.get("height_cm")) or None


def identity(b: dict) -> dict[str, Any]:
    """Registry identity block: ``nama``, ``jenis_kelamin`` (Laki-Laki / Perempuan), ``tanggal_lahir`` (ISO), ``no_tlp``, ``alamat``."""
    p = b.get("patient") or {}
    g = p.get("gender")
    jk = {1: "Laki-Laki", "1": "Laki-Laki", 2: "Perempuan", "2": "Perempuan"}.get(g, "")
    dob = _clean(p.get("date_of_birth"))
    alamat = (p.get("address") or {}).get("text")
    return {
        "nama": _clean(p.get("name")) or "",
        "jenis_kelamin": jk,
        "tanggal_lahir": dob if dob and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob) else None,
        "no_tlp": _clean(p.get("phone")) or "",
        "alamat": re.sub(r"\s+", " ", str(alamat)).strip() if alamat else "",
    }


def tertatalaksana(b: dict) -> tuple[bool, bool]:
    """(drug given, education given) for the GD Puasa / Hipertensi dashboards.

    ePuskesmas has two explicit PTM checkboxes for this; Medisy does not expose them, so these are PROXIES (open clinical
    question Q7 in ``MEDISY_TO_ASIK_RULES.md``): a drug counts when a chronic-disease drug (antihypertensive / antidiabetic /
    lipid-lowering) was prescribed at the visit; education counts when the education form of the examination (type select ``edukasi_term`` or the free text ``edukasi``) is filled."""
    from app.services.dm_registry_scan import _DM_DRUG_RE
    from app.services.hipertensi_registry_scan import _HT_DRUG_RE
    from app.services.lipid_registry_scan import _LIPID_DRUG_RE

    obat = any(_HT_DRUG_RE.search(n) or _DM_DRUG_RE.search(n) or _LIPID_DRUG_RE.search(n) for n in drug_names(b))
    general = (b.get("physical_exam") or {}).get("general") or {}
    edukasi = bool(_clean(general.get("edukasi_term")) or _clean(general.get("edukasi")))
    return obat, edukasi


# ── newborn registry (bayi) ────────────────────────────────────────────────


def is_newborn_age(b: dict) -> bool:
    """Age under one year (the Medisy counterpart of ePuskesmas's "0 Thn …" Umur)."""
    age = (b.get("patient") or {}).get("age")
    years = age.get("years") if isinstance(age, dict) else None
    return isinstance(years, int) and not isinstance(years, bool) and years == 0


def latest_pjb(b: dict) -> dict[str, Any] | None:
    """The newest critical-congenital-heart-disease pulse-ox row of the visit's KIA program: ``{saturasi_tangan, saturasi_kaki,
    kesimpulan, tindakan}`` (``kesimpulan`` is Lolos / Gagal in Medisy's form), or None."""
    block = (b.get("programs") or {}).get("kia")
    rows = [r for r in ((block or {}).get("pjb") or []) if isinstance(r, dict)] if isinstance(block, dict) else []
    if not rows:
        return None
    r = max(rows, key=lambda x: (str(x.get("tanggal_pjb") or ""), _num(x.get("id")) or 0))
    return {k: _clean(r.get(k)) for k in ("saturasi_tangan", "saturasi_kaki", "kesimpulan", "tindakan")}


def ikterus_classification(b: dict) -> str:
    """Raw ikterus klasifikasi text from the child (MTBM) rows — "Ikterus Berat" / "Ikterus" / "Tidak ada Ikterus" in Medisy's form —
    or "". Only rows whose type mentions ikterus count."""
    block = (b.get("programs") or {}).get("child")
    for r in ((block or {}).get("mtbs") or []) if isinstance(block, dict) else []:
        if isinstance(r, dict) and "ikterus" in f"{r.get('kode_jenis')} {r.get('jenis')}".casefold():
            text = _clean(r.get("klasifikasi"))
            if text:
                return text
    return ""


def diagnosis_names(b: dict) -> list[str]:
    """Diagnosis names of THIS visit, de-duplicated, in order."""
    out: list[str] = []
    for d in b.get("diagnoses") or []:
        name = _clean((d or {}).get("name")) if isinstance(d, dict) else None
        if name and name not in out:
            out.append(name)
    return out


def external_referral_destination(b: dict) -> str:
    """Facility an EXTERNAL referral at this visit went to, or "" (an internal referral, no referral, or a destination Medisy does not hold)."""
    ref = (b.get("visit") or {}).get("referral")
    if isinstance(ref, dict) and ref.get("referred") is True and (_clean(ref.get("type")) or "").upper() == "EXTERNAL":
        return _clean(ref.get("destination")) or ""
    return ""
