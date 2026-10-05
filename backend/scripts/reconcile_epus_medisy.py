"""Phase 7 reconciliation: compare the stored ePuskesmas rows of one puskesmas with what Medisy serves, per day.

READ-ONLY on both sides: it selects rows (no commit) and calls Medisy's visit list (E2). It never deletes, updates or
scrapes anything — run it BEFORE the owner replaces the ePuskesmas data, and explain every difference first.

For each day in the range it prints counts only (no NIK, no name unless ``--show-niks``):

  legacy_rows    stored rows whose blob is an ePuskesmas record (not a Medisy bundle), and how many are tagged CKG
  medisy_visits  visits Medisy lists for the day (every room), how many are CKG, how many carry a NIK, how many NIKs are
                 flagged shared (ckg-ai skips those), how many have no NIK
  both           NIKs present on both sides
  legacy_only    NIKs stored from ePuskesmas that Medisy does not list that day
  medisy_only    usable Medisy NIKs (not shared) that have no stored ePuskesmas row that day

Run it inside the backend/worker container (has the DB + decryption key):

  docker exec -it ckg-ai-celery_worker-1 python -m scripts.reconcile_epus_medisy \
      --puskesmas <UUID> --from 2026-09-01 --to 2026-09-30
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import select

from app.core.security import decrypt_json
from app.crud import puskesmas as puskesmas_crud
from app.database import SessionLocal
from app.integrations.medisy_client import MedisyClient, MedisyError
from app.models.patient import Patient
from app.models.puskesmas import Puskesmas
from app.services.medisy_adapter import is_medisy_blob


def reconcile_day(legacy: list[tuple[str, bool]], visits: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Counts for one day. ``legacy`` = ``[(nik, tagged_ckg)]`` of stored ePuskesmas rows; ``visits`` = Medisy E2 items."""
    visits = list(visits)
    legacy_niks = {nik for nik, _ in legacy if nik}
    with_nik = [v for v in visits if (v.get("nik") or "").strip()]
    shared = {(v["nik"] or "").strip() for v in with_nik if v.get("nik_shared") is True}
    usable = {(v["nik"] or "").strip() for v in with_nik} - shared
    return {
        "legacy_rows": len(legacy),
        "legacy_ckg": sum(1 for _, ckg in legacy if ckg),
        "medisy_visits": len(visits),
        "medisy_ckg": sum(1 for v in visits if v.get("is_ckg")),
        "medisy_with_nik": len(with_nik),
        "medisy_no_nik": len(visits) - len(with_nik),
        "medisy_shared_niks": len(shared),
        "both": len(legacy_niks & usable),
        "legacy_only": sorted(legacy_niks - usable),
        "medisy_only": sorted(usable - legacy_niks),
    }


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(d) for d in range((end - start).days + 1)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puskesmas", required=True, type=uuid.UUID)
    ap.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    ap.add_argument("--to", dest="end", required=True, type=date.fromisoformat)
    ap.add_argument("--show-niks", action="store_true", help="also print the NIKs of legacy_only / medisy_only (patient data)")
    args = ap.parse_args()
    if args.end < args.start or (args.end - args.start).days > 92:
        print("the range must be 1-93 days", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        pk = db.get(Puskesmas, args.puskesmas)
        if pk is None or not pk.epus_url:
            print("puskesmas not found or has no Medisy URL", file=sys.stderr)
            return 2
        creds = puskesmas_crud.get_cred_decrypted(pk, "epus") or {}
        token = creds.get("token")
        if not token:
            print("no Medisy token stored for this puskesmas", file=sys.stderr)
            return 2
        rows = db.execute(
            select(Patient.nik, Patient.filter_date, Patient.epus_tandai_ckg, Patient.scraped_epus_data)
            .where(
                Patient.puskesmas_id == args.puskesmas,
                Patient.deleted_at.is_(None),
                Patient.scraped_epus_data.isnot(None),
                Patient.filter_date.between(args.start, args.end),
            )
        ).all()
        legacy_by_day: dict[date, list[tuple[str, bool]]] = {}
        medisy_rows = 0
        for nik, filter_date, tagged, blob in rows:
            try:
                data = decrypt_json(blob)
            except Exception:
                continue
            if is_medisy_blob(data):
                medisy_rows += 1
                continue
            legacy_by_day.setdefault(filter_date, []).append((nik or "", bool(tagged)))

    totals = {k: 0 for k in ("legacy_rows", "medisy_visits", "both", "legacy_only", "medisy_only")}
    print(f"{pk.name}: {args.start} .. {args.end}  (already-Medisy rows ignored: {medisy_rows})")
    print("date        legacy(ckg)  medisy(ckg)  nik/no-nik/shared  both  legacy_only  medisy_only")
    try:
        with MedisyClient(pk.epus_url, token) as client:
            for day in _days(args.start, args.end):
                legacy = legacy_by_day.get(day, [])
                visits = client.list_visits(day, ckg_only=False)
                r = reconcile_day(legacy, visits)
                if not (r["legacy_rows"] or r["medisy_visits"]):
                    continue
                print(f"{day}  {r['legacy_rows']:>5}({r['legacy_ckg']:<3})  {r['medisy_visits']:>5}({r['medisy_ckg']:<3})  "
                      f"{r['medisy_with_nik']:>4}/{r['medisy_no_nik']:<4}/{r['medisy_shared_niks']:<4}  {r['both']:>4}  "
                      f"{len(r['legacy_only']):>11}  {len(r['medisy_only']):>11}")
                if args.show_niks:
                    for label in ("legacy_only", "medisy_only"):
                        for nik in r[label]:
                            print(f"    {label}: {nik}")
                totals["legacy_rows"] += r["legacy_rows"]
                totals["medisy_visits"] += r["medisy_visits"]
                totals["both"] += r["both"]
                totals["legacy_only"] += len(r["legacy_only"])
                totals["medisy_only"] += len(r["medisy_only"])
    except MedisyError as exc:
        print(f"Medisy: {exc}", file=sys.stderr)
        return 1
    print("TOTAL " + "  ".join(f"{k}={v}" for k, v in totals.items()))
    print("Every legacy_only / medisy_only difference must be explained or accepted by the owner before the ePuskesmas rows are replaced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
