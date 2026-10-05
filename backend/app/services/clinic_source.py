"""Source-neutral access to the stored clinic blob (``patients.scraped_epus_data``).

The clinic-record source is Medisy now. Until the existing EPUS rows are replaced, one column holds both shapes, so every
consumer asks THIS module and never inspects a blob itself. The shape is read from the blob (a Medisy bundle carries
``api_version`` + ``visit``, see ``medisy_adapter.is_medisy_blob``), never from a flag: a row decodes correctly even if the
puskesmas's setup changes later.

When the last EPUS row is gone, delete the EPUS branches here and in ``epus_to_asik.py``; nothing else has to change.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.epus_to_asik import EPUS_BREADCRUMBS, _disabilitas, epus_to_asik
from app.services.epus_to_asik import _status_perkawinan as _epus_status_perkawinan
from app.services.medisy_adapter import is_medisy_blob
from app.services.medisy_to_asik import MEDISY_BREADCRUMBS, medisy_to_asik
from app.services.medisy_to_asik import _status_perkawinan as _medisy_status_perkawinan


def clinic_to_asik(blob: dict | None) -> dict:
    """ASIK form shape of one stored clinic blob."""
    if is_medisy_blob(blob):
        return medisy_to_asik(blob)
    return epus_to_asik(blob or {})


def breadcrumbs_for(blob: dict | None) -> dict[str, dict[str, str | None]]:
    """The ``{asik_form: {field: source path}}`` table that matches the blob's shape."""
    return MEDISY_BREADCRUMBS if is_medisy_blob(blob) else EPUS_BREADCRUMBS


# ─── registration fields (used when a patient has to be created in ASIK) ──────


def clinic_name(blob: dict | None) -> str | None:
    if is_medisy_blob(blob):
        return ((blob.get("patient") or {}).get("name") or "").strip() or None
    return ((blob or {}).get("data_pasien") or {}).get("Nama Pasien") or None


def clinic_phone(blob: dict | None) -> str | None:
    if is_medisy_blob(blob):
        return (blob.get("patient") or {}).get("phone")
    return ((blob or {}).get("data_pasien") or {}).get("No Telp / HP")


def clinic_address(blob: dict | None) -> str | None:
    """Free-text address on one line, or None."""
    raw: Any
    if is_medisy_blob(blob):
        raw = ((blob.get("patient") or {}).get("address") or {}).get("text")
    else:
        raw = ((blob or {}).get("data_pasien") or {}).get("Alamat")
    return re.sub(r"\s+", " ", str(raw)).strip() if raw else None


def clinic_marital_status(blob: dict | None) -> str | None:
    """ASIK marital-status option (``Belum Menikah`` / ``Menikah`` / ``Cerai Hidup`` / ``Cerai Mati``), or None."""
    if is_medisy_blob(blob):
        return _medisy_status_perkawinan((blob.get("patient") or {}).get("marital_status"))
    return _epus_status_perkawinan(((blob or {}).get("data_pasien") or {}).get("Status Perkawinan"))


def clinic_is_disabled(blob: dict | None) -> bool:
    """True only when the source says the patient has a disability. Medisy does not record it, so it is always False there."""
    if is_medisy_blob(blob):
        return False
    return _disabilitas(blob or {}) == "Penyandang disabilitas"
