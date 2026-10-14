"""Medisy -> scrape pipeline: fetch a day's CKG visits and turn the bundles into patient rows.

Medisy replaces the EPUS Playwright scrape as the clinic-record source. A day's work is:

  1. ``MedisyClient.list_visits(day)``  – the CKG visits of that day (cancelled/deleted excluded by Medisy);
  2. ``MedisyClient.get_bundles(ids)``  – the full native bundle of each (<= 50 per request);
  3. ``extract_patients(...)``          – ``(nik, nama, blob, date)`` rows for ``patient_crud.upsert_from_scrape``.

The stored blob is the bundle **as Medisy returned it** plus ``_meta {source, fetched_at}`` (plan D8), so the
converter can read old records after the API changes. Nothing here interprets clinical content.

Same-day, same-room, same-patient duplicates: the row key is ``(puskesmas, nik, filter_date, ruangan)``, so two visits
of one patient in one poli on one day collapse into ONE row. Bundles are passed in visit-id order, so the LATEST visit wins.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from app.integrations.medisy_client import MAX_BATCH, MedisyClient

SOURCE = "medisy"


def is_medisy_blob(blob: Any) -> bool:
    """True for a stored Medisy bundle (they carry ``api_version`` and a ``visit`` object); legacy EPUS blobs do not."""
    return isinstance(blob, dict) and "api_version" in blob and isinstance(blob.get("visit"), dict)


def with_meta(bundle: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    """The blob that gets stored: the bundle unchanged, plus where/when it came from."""
    return {**bundle, "_meta": {"source": SOURCE, "fetched_at": fetched_at}}


def fetch_day_bundles(
    client: MedisyClient,
    day: date,
    *,
    niks: set[str] | None = None,
    should_cancel: Callable[[], bool] = lambda: False,
    on_log: Callable[[str], None] = lambda _line: None,
) -> list[dict[str, Any]]:
    """Full bundles of EVERY visit of ``day`` (CKG or not) in ascending visit-id order.

    Not only CKG visits: the registries read later non-CKG visits of a patient (follow-up readings, prescriptions) and the
    newborn registry sits on visits that are not CKG. Each bundle carries ``ckg.is_ckg``, which sets ``epus_tandai_ckg``.

    ``niks`` keeps only visits of those patients (filtered on the cheap list, so other patients' bundles are never
    downloaded). ``should_cancel`` is checked before every request; when it turns true the bundles fetched so far are
    returned. ``on_log`` receives short progress lines (counts only — never a NIK or a name).
    """
    visits = client.list_visits(day, ckg_only=False)
    if niks is not None:
        visits = [v for v in visits if (v.get("nik") or "").strip() in niks]
    ids = sorted({int(v["visit_id"]) for v in visits})
    on_log(f"{day.isoformat()}: {len(ids)} visit(s) in Medisy")

    bundles: list[dict[str, Any]] = []
    for i in range(0, len(ids), MAX_BATCH):
        if should_cancel():
            break
        result = client.get_bundles(ids[i:i + MAX_BATCH])
        bundles.extend(result.items)
        if result.missing:
            # cancelled/deleted between the list call and now — not an error, just not ours any more
            on_log(f"{day.isoformat()}: {len(result.missing)} visit(s) vanished before they could be read")
    on_log(f"{day.isoformat()}: fetched {len(bundles)} bundle(s)")
    return bundles


def extract_patients(
    bundles: Iterable[dict[str, Any]], fetched_at: str
) -> tuple[list[tuple[str, str, dict[str, Any], str | None]], list[dict[str, str]], int]:
    """``(rows, skipped, scraped_count)`` — the same contract as the ASIK extractor in ``tasks/scrape.py``.

    ``rows`` are ``(nik, nama, blob, date_iso)``. A visit without a NIK is skipped with the usual reason: Medisy only
    reports a NIK when the identity type is KTP/NIK and the number is non-empty (it does not validate the number).
    A visit whose NIK Medisy flags ``identity.shared`` (one number, several different people) is skipped too, with its own reason.
    """
    rows: list[tuple[str, str, dict[str, Any], str | None]] = []
    skipped: list[dict[str, str]] = []
    count = 0
    for bundle in bundles:
        count += 1
        visit = bundle.get("visit") or {}
        patient = bundle.get("patient") or {}
        identity = patient.get("identity") or {}
        nik = (identity.get("number") or "").strip()
        if not nik:
            skipped.append({"source_id": str(visit.get("id") or ""), "reason": "missing NIK"})
            continue
        if identity.get("shared") is True:
            # Medisy flags a number held by more than one different person (placeholder "00", a reused NIK). Records are keyed
            # by NIK, so saving it would overwrite one patient with another and join unrelated people to ASIK.
            skipped.append({"source_id": str(visit.get("id") or ""), "reason": "shared NIK (more than one person)"})
            continue
        nama = (patient.get("name") or "").strip()
        rows.append((nik, nama, with_meta(bundle, fetched_at), visit.get("date")))
    return rows, skipped, count
