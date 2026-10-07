"""NON-COMMITTING test of the ASIK registration form for Medisy-only patients: fills step 1 and step 2 (including the
patient's own domicile cascade) and STOPS before "Daftarkan" — nothing is registered in ASIK.

``commit`` is hard-wired to False here (and asserted), so this can never create an ASIK record. It prints one line per
patient: the register robot's outcome and, for a failure, its error text; NIKs are masked.

Needs a valid saved ASIK session for the puskesmas (``scripts/seed_asik_session.py``). Run on the worker's machine:

  cd backend
  .venv/bin/python -m scripts.probe_register_step2 --puskesmas <UUID> [--limit 2]
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import date


def _tail(error: object, n: int = 900) -> str:
    """The end of a failure message (where the robot's last log lines are), with long digit strings (NIKs) masked."""
    return re.sub(r"\d{9,}", "<num>", str(error or "")[-n:]).replace("\n", " | ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puskesmas", required=True, type=uuid.UUID)
    ap.add_argument("--limit", type=int, default=2)
    args = ap.parse_args()

    from sqlalchemy import select

    from app.config import settings
    from app.crud import patient as patient_crud
    from app.crud import puskesmas as puskesmas_crud
    from app.database import SessionLocal
    from app.models.patient import MatchStatus, Patient
    from app.models.puskesmas import Puskesmas
    from app.models.scrape_job import ScrapeKind
    from app.tasks import create_patient as cp
    from app.tasks.scrape import _asik_session_dir, _build_captcha_solver

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
        patients = list(db.scalars(
            select(Patient).where(
                Patient.puskesmas_id == pk.id, Patient.match_status == MatchStatus.EPUS_ONLY,
                Patient.epus_tandai_ckg.is_(True), Patient.filter_date >= year_start, Patient.asik_synced_at.is_(None),
            ).order_by(Patient.filter_date.desc()).limit(max(1, args.limit))
        ).all())
        captcha = _build_captcha_solver(db)
        session_dir = _asik_session_dir(pk.id)
        base_url = f"https://{pk.asik_url}"
        timeout = max(1, int(settings.SYNC_SUBPROCESS_TIMEOUT_SECONDS))

        for p in patients:
            masked = f"…{str(p.nik)[-4:]}"
            epus = patient_crud.decrypt_field(p, ScrapeKind.EPUS)
            block = cp._wali_block_reason(p.nik, p.birth_date, p.filter_date)
            step2 = cp._build_step2(p, epus, pk)
            if block or step2 is None:
                print(f"{masked}: not attempted — {block or 'no domicile'}")
                continue
            cfg = cp._build_register_config(
                asik_creds=creds, base_url=base_url, patient=p, epus=epus, exam_date=p.filter_date, dry_run_probe=False,
                captcha_solver=captcha, headless=True, step2=step2, commit=False,
            )
            assert cfg["register"]["commit"] is False, "this probe must never commit"
            out = cp._run_register(cfg=cfg, session_dir=session_dir, timeout=timeout)
            alamat = step2["alamat"]
            print(f"{masked}: outcome={out.get('outcome')} | domicile typed: {alamat['provinsi']} / {alamat['kota']} / "
                  f"{alamat['kecamatan']} / {alamat['kelurahan']} | error={_tail(out.get('error'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
