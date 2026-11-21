import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, load_only

from app.api.deps import get_current_admin_id, get_db
from app.api.pagination import Page, PageParams, page_params, paginate
from app.celery_app import celery_app
from app.core.labels import status_label, step_label
from app.crud import cron_run as crud
from app.models.cron_backfill import CronBackfill, CronBackfillStatus
from app.models.cron_run import CronRun, CronRunStatus, CronStep
from app.models.merge_job import MergeJob
from app.models.puskesmas import Puskesmas
from app.models.scrape_job import ScrapeJob
from app.models.sync_job import SyncJob, SyncStatus
from app.schemas.cron_run import CronRunOut, CronRunSyncSummary, cron_run_to_out

router = APIRouter(tags=["cron"])

_RUN_OUT_COLS = (
    CronRun.id, CronRun.cron_config_id, CronRun.cron_backfill_id,
    CronRun.puskesmas_id,
    CronRun.target_date, CronRun.source_scope, CronRun.status, CronRun.current_step,
    CronRun.current_step_attempt, CronRun.failed_step,
    CronRun.asik_scrape_job_id, CronRun.epus_scrape_job_id, CronRun.merge_job_id,
    CronRun.triggered_by_id, CronRun.error_message,
    CronRun.started_at, CronRun.finished_at,
    CronRun.created_at, CronRun.updated_at,
)


_to_out = cron_run_to_out


@router.get("/admin/cron-runs", response_model=Page[CronRunOut])
def list_runs(
    params: PageParams = Depends(page_params),
    puskesmas_id: uuid.UUID | None = Query(None),
    run_status: CronRunStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Page[CronRunOut]:
    stmt = (
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .order_by(CronRun.created_at.desc())
    )
    if puskesmas_id is not None:
        stmt = stmt.where(CronRun.puskesmas_id == puskesmas_id)
    if run_status is not None:
        stmt = stmt.where(CronRun.status == run_status)
    items, total, pages = paginate(db, stmt, params)
    return Page[CronRunOut](
        items=[_to_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )


@router.get("/admin/cron-runs/{run_id}", response_model=CronRunOut)
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    obj = db.scalar(
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proses terjadwal tidak ditemukan")
    return _to_out(obj, obj.puskesmas.name)


@router.get(
    "/admin/cron-runs/{run_id}/sync-summary", response_model=CronRunSyncSummary
)
def get_run_sync_summary(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunSyncSummary:
    """Per-patient sync progress for the run's SYNC step.

    One GROUP BY over the partial index ix_sync_jobs_cron_run_status, plus the
    run's stamped denominator. The page fetches it on load and on the run's SSE
    terminal event — no polling.
    """
    total = db.scalar(
        select(CronRun.sync_total).where(CronRun.id == run_id)
    )
    counts = dict(
        db.execute(
            select(SyncJob.status, func.count())
            .where(SyncJob.cron_run_id == run_id)
            .group_by(SyncJob.status)
        ).all()
    )
    return CronRunSyncSummary(
        total=total,
        pending=counts.get(SyncStatus.PENDING, 0),
        running=counts.get(SyncStatus.RUNNING, 0),
        success=counts.get(SyncStatus.SUCCESS, 0),
        failed=counts.get(SyncStatus.FAILED, 0),
        cancelled=counts.get(SyncStatus.CANCELLED, 0),
    )


@router.post("/admin/cron-runs/{run_id}/cancel", response_model=CronRunOut)
def cancel_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    obj = db.scalar(
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proses terjadwal tidak ditemukan")
    if obj.status not in (CronRunStatus.PENDING, CronRunStatus.RUNNING):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Proses terjadwal berstatus {status_label(obj.status.value)}, tidak bisa dibatalkan",
        )
    pk_name = obj.puskesmas.name
    crud.cancel_cron_run_and_children(db, obj)
    db.refresh(obj)
    return _to_out(obj, pk_name)


def _load_restartable_run(db: Session, run_id: uuid.UUID, *, allow_backfill: bool = False) -> CronRun:
    obj = db.scalar(
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(load_only(*_RUN_OUT_COLS), contains_eager(CronRun.puskesmas).load_only(Puskesmas.name))
        .where(CronRun.id == run_id)
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proses terjadwal tidak ditemukan")
    if obj.status not in (CronRunStatus.FAILED, CronRunStatus.CANCELLED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Proses terjadwal berstatus {status_label(obj.status.value)}; hanya proses yang gagal/dibatalkan yang bisa diulang",
        )
    if obj.cron_backfill_id is not None and not allow_backfill:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Proses ini bagian dari proses rentang tanggal; gunakan Lanjutkan dari langkah yang gagal, "
            "atau buat proses rentang tanggal baru",
        )
    return obj


def _start_run(
    db: Session,
    obj: CronRun,
    admin_id: uuid.UUID,
    first_step: CronStep,
    carried: dict[str, uuid.UUID] | None = None,
    backfill_id: uuid.UUID | None = None,
) -> CronRunOut:
    """Create a fresh run for the same puskesmas / date / config and dispatch it at ``first_step``.
    ``carried`` pre-fills child job ids (epus_scrape_job_id / asik_scrape_job_id / merge_job_id) of steps
    that already succeeded, so cron.advance's previous-step check passes and they are not run again.
    With ``backfill_id`` the run stays bound to that date-range process, which is reactivated (it stopped
    as failed on this date), so once this date finishes cron.advance moves the range on to the next date."""
    pk_name = obj.puskesmas.name

    # Pre-check is advisory (nice 409 message); the lane partial UNIQUE indexes
    # (uq_cron_runs_active_epus / _asik) are the actual race-safe guard. Restart is
    # restricted to non-backfill runs (always source_scope=BOTH), and BOTH
    # occupies both lanes — so any active run conflicts.
    active = db.scalar(
        select(CronRun.id)
        .where(
            CronRun.puskesmas_id == obj.puskesmas_id,
            CronRun.status.in_((CronRunStatus.PENDING, CronRunStatus.RUNNING)),
        )
        .limit(1)
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Masih ada proses terjadwal yang berjalan untuk puskesmas ini",
        )

    try:
        new_run = crud.create(
            db,
            puskesmas_id=obj.puskesmas_id,
            target_date=obj.target_date,
            cron_config_id=obj.cron_config_id,
            triggered_by_id=admin_id,
            cron_backfill_id=backfill_id,
            source_scope=obj.source_scope,
        )
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Masih ada proses terjadwal yang berjalan untuk puskesmas ini",
        ) from e
    if carried:
        for col, job_id in carried.items():
            setattr(new_run, col, job_id)
        db.commit()
        db.refresh(new_run)
    if backfill_id is not None:
        # Conditional so a range that moved on (or was restarted) meanwhile is never hijacked. UPDATE is not
        # auto-filtered for soft-delete (CLAUDE.md §6).
        try:
            reactivated = db.execute(
                update(CronBackfill)
                .where(
                    CronBackfill.id == backfill_id,
                    CronBackfill.status == CronBackfillStatus.FAILED,
                    CronBackfill.failed_date == obj.target_date,
                    CronBackfill.deleted_at.is_(None),
                )
                .values(
                    status=CronBackfillStatus.RUNNING, failed_date=None, error_message=None,
                    finished_at=None, current_cron_run_id=new_run.id,
                )
            ).rowcount
            db.commit()
        except IntegrityError:
            db.rollback()
            reactivated = 0
        if not reactivated:
            msg = "Proses rentang tanggal tidak bisa dilanjutkan (sudah berubah atau ada yang sedang berjalan)"
            crud.mark_failed(db, new_run, first_step, msg, datetime.now(UTC))
            raise HTTPException(status.HTTP_409_CONFLICT, msg)
    try:
        celery_app.send_task("cron.advance", args=[str(new_run.id), first_step.value])
    except Exception as e:
        crud.mark_failed(
            db, new_run, first_step,
            f"broker unreachable: {e}", datetime.now(UTC),
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Antrean proses terjadwal sedang tidak tersedia"
        ) from e
    return _to_out(new_run, pk_name)


@router.post("/admin/cron-runs/{run_id}/retry", response_model=CronRunOut)
def retry_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    """Run the whole chain again from its first step."""
    obj = _load_restartable_run(db, run_id)
    # Restart is restricted to non-backfill runs (always source_scope=BOTH), so EPUS is always the first step.
    return _start_run(db, obj, admin_id, CronStep.EPUS)


# Step order and the child-job column each step leaves on the run (SYNC / CREATE have none).
_STEP_ORDER = (CronStep.EPUS, CronStep.ASIK, CronStep.MERGE, CronStep.SYNC, CronStep.CREATE)
_STEP_JOB_COL = {
    CronStep.EPUS: "epus_scrape_job_id",
    CronStep.ASIK: "asik_scrape_job_id",
    CronStep.MERGE: "merge_job_id",
}


@router.post("/admin/cron-runs/{run_id}/resume", response_model=CronRunOut)
def resume_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> CronRunOut:
    """Continue a failed run from the step that failed, reusing the jobs of the steps before it.

    The new run carries the earlier steps' (successful) child job ids, so only the failed step and the ones
    after it run again — e.g. a run that failed at Gabung data does not re-scrape Medisy and ASIK. A run that is
    part of a date-range process (backfill) resumes that range too, when the range stopped as failed on this date."""
    obj = _load_restartable_run(db, run_id, allow_backfill=True)
    failed = obj.failed_step
    if obj.status != CronRunStatus.FAILED or failed is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Hanya proses yang gagal pada suatu langkah yang bisa dilanjutkan; gunakan Coba lagi",
        )

    carried: dict[str, uuid.UUID] = {}
    for step in _STEP_ORDER[: _STEP_ORDER.index(failed)]:
        col = _STEP_JOB_COL.get(step)
        job_id = getattr(obj, col) if col else None
        if job_id is not None:
            carried[col] = job_id
    if not carried:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Langkah pertama ({step_label(failed.value)}) yang gagal, tidak ada yang bisa dipakai ulang; gunakan Coba lagi",
        )

    # Every reused step must have finished successfully — otherwise resuming would build on a broken step.
    scrape_ids = [carried[c] for c in ("epus_scrape_job_id", "asik_scrape_job_id") if c in carried]
    statuses = dict(db.execute(
        select(ScrapeJob.id, ScrapeJob.status).where(ScrapeJob.id.in_(scrape_ids))
    ).all()) if scrape_ids else {}
    if "merge_job_id" in carried:
        statuses[carried["merge_job_id"]] = db.scalar(
            select(MergeJob.status).where(MergeJob.id == carried["merge_job_id"])
        )
    for col, job_id in carried.items():
        st = statuses.get(job_id)
        if st is None or st.value != "success":
            step = next(s for s, c in _STEP_JOB_COL.items() if c == col)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Langkah {step_label(step.value)} sebelumnya tidak berhasil; gunakan Coba lagi",
            )

    if obj.cron_backfill_id is not None:
        bf = db.scalar(
            select(CronBackfill)
            .options(load_only(CronBackfill.id, CronBackfill.status, CronBackfill.failed_date))
            .where(CronBackfill.id == obj.cron_backfill_id)
        )
        if bf is None or bf.status != CronBackfillStatus.FAILED or bf.failed_date != obj.target_date:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Proses rentang tanggal ini tidak sedang berhenti gagal di tanggal ini; "
                "buat proses rentang tanggal baru untuk melanjutkan",
            )

    return _start_run(db, obj, admin_id, failed, carried, backfill_id=obj.cron_backfill_id)


@router.get(
    "/admin/puskesmas/{puskesmas_id}/cron-runs",
    response_model=Page[CronRunOut],
)
def list_runs_for_puskesmas(
    puskesmas_id: uuid.UUID,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Page[CronRunOut]:
    stmt = (
        select(CronRun)
        .join(CronRun.puskesmas)
        .options(
            load_only(*_RUN_OUT_COLS),
            contains_eager(CronRun.puskesmas).load_only(Puskesmas.name),
        )
        .where(CronRun.puskesmas_id == puskesmas_id)
        .order_by(CronRun.created_at.desc())
    )
    items, total, pages = paginate(db, stmt, params)
    return Page[CronRunOut](
        items=[_to_out(i, i.puskesmas.name) for i in items],
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )
