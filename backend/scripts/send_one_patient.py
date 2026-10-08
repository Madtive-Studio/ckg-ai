"""Register ONE Medisy-only patient in ASIK and fill their forms — a REAL write to ASIK (government production).

Same flow as the admin "create in ASIK" button (``create_one_patient``: register COMMIT → Konfirmasi Hadir → fill via the
sync machinery), run in this process so it uses the current code. It refuses anything but exactly one eligible patient,
and needs ``--confirm-nik-suffix`` (the last 4 digits) to prove which patient was approved. Output is masked (no NIK).

Needs a fresh saved ASIK session (``scripts/seed_asik_session.py``):

  cd backend
  .venv/bin/python -m scripts.send_one_patient --puskesmas <UUID> --confirm-nik-suffix 780008 --visit-date 2026-02-03
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import date


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puskesmas", required=True, type=uuid.UUID)
    ap.add_argument("--confirm-nik-suffix", required=True, help="last 4-8 digits of the approved patient's NIK")
    ap.add_argument("--visit-date", required=True, type=date.fromisoformat, help="the approved visit's date (YYYY-MM-DD)")
    ap.add_argument("--fill-only", action="store_true", help="the patient is already registered in ASIK: skip registration, only fill the forms")
    ap.add_argument("--visible", action="store_true", help="show the browser window instead of running headless")
    args = ap.parse_args()
    if not re.fullmatch(r"\d{4,8}", args.confirm_nik_suffix):
        print("--confirm-nik-suffix must be 4-8 digits", file=sys.stderr)
        return 2

    import redis
    from sqlalchemy import select

    from app.config import settings
    from app.crud import patient as patient_crud
    from app.crud import puskesmas as puskesmas_crud
    from app.crud import sync_job as sync_job_crud
    from app.database import SessionLocal
    from app.models.admin import Admin
    from app.models.patient import MatchStatus, Patient
    from app.models.puskesmas import Puskesmas
    from app.models.scrape_job import ScrapeKind, TriggererType
    from app.tasks.create_patient import create_one_patient
    from app.tasks.scrape import _build_captcha_solver
    from app.tasks.sync import _cancel_key

    with SessionLocal() as db:
        pk = db.get(Puskesmas, args.puskesmas)
        if pk is None or not pk.asik_url:
            print("puskesmas not found or has no ASIK URL", file=sys.stderr)
            return 2
        creds = puskesmas_crud.get_cred_decrypted(pk, "asik")
        if not creds:
            print("no ASIK credential stored", file=sys.stderr)
            return 2
        year_start = date(date.today().year, 1, 1)
        candidates = [
            p for p in db.scalars(
                select(Patient).where(
                    Patient.puskesmas_id == pk.id, Patient.match_status == MatchStatus.EPUS_ONLY,
                    Patient.epus_tandai_ckg.is_(True), Patient.filter_date >= year_start,
                    Patient.asik_synced_at.is_(None), Patient.scraped_epus_data.isnot(None),
                )
            ).all()
            if str(p.nik).endswith(args.confirm_nik_suffix) and p.filter_date == args.visit_date
        ]
        if len(candidates) != 1:
            print(f"expected exactly 1 eligible patient ending in {args.confirm_nik_suffix}, found {len(candidates)} — nothing done",
                  file=sys.stderr)
            return 2
        patient = candidates[0]
        epus = patient_crud.decrypt_field(patient, ScrapeKind.EPUS)
        admin = db.scalar(select(Admin).limit(1))
        if admin is None:
            print("no admin row to attribute the job to", file=sys.stderr)
            return 2

        job = sync_job_crud.create(
            db, puskesmas_id=pk.id, patient_id=patient.id, triggered_by_id=admin.id, triggered_by_type=TriggererType.ADMIN,
        )
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        print(f"sending patient …{args.confirm_nik_suffix[-4:]} (visit {patient.filter_date}) — job {job.id}")
        if args.fill_only:
            from datetime import UTC, datetime
            from app.services.clinic_source import clinic_to_asik
            from app.tasks.sync import _execute_sync

            sync_job_crud.mark_running(db, job, "", datetime.now(UTC), 0)
            merged = clinic_to_asik(epus)
            forms_total = sum(1 for v in (merged or {}).values() if isinstance(v, dict) and any(x not in (None, "") for x in v.values()))
            status = _execute_sync(
                db=db, redis_client=redis_client, job=job, patient=patient, base_url_full=f"https://{pk.asik_url}", creds=creds,
                captcha_solver=_build_captcha_solver(db), merged=merged, forms_total=forms_total, headless=not args.visible,
                celery_task_id="", cancel_key_str=_cancel_key(str(job.id)),
            )
            outcome = "fill_only"
        else:
            outcome, status = create_one_patient(
                db, job=job, patient=patient, epus=epus, puskesmas=pk, base_url=f"https://{pk.asik_url}", creds=creds,
                captcha_solver=_build_captcha_solver(db), headless=not args.visible, redis_client=redis_client,
                cancel_key_str=_cancel_key(str(job.id)),
            )
        db.refresh(job)
        print(f"register outcome={outcome} job status={status}")
        print(f"forms: total={job.forms_total} ok={job.forms_succeeded} failed={job.forms_failed} skipped={job.forms_skipped}")
        if job.error_message:
            print("error: " + re.sub(r"\d{9,}", "<num>", str(job.error_message))[-600:])
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
