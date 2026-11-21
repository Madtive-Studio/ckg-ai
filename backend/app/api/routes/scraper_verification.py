"""Admin notices for open scraper questions answered by a production scrape (see services/scraper_verification.py)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_id, get_db
from app.models.puskesmas import Puskesmas
from app.models.scraper_verification_signal import ScraperVerificationSignal as Signal
from app.schemas.scraper_verification import ScraperVerificationSignalOut

router = APIRouter(prefix="/admin/scraper-verification", tags=["scraper-verification"])


@router.get("", response_model=list[ScraperVerificationSignalOut])
def list_pending_signals(
    db: Session = Depends(get_db),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> list[ScraperVerificationSignalOut]:
    """Unacknowledged notices, newest first. One row per (question, outcome), so the list stays tiny."""
    rows = db.execute(
        select(
            Signal.id, Signal.code, Signal.outcome, Signal.ok_count, Signal.problem_count,
            Signal.puskesmas_id, Puskesmas.name.label("puskesmas_name"), Signal.scrape_job_id, Signal.created_at,
        )
        .join(Puskesmas, Puskesmas.id == Signal.puskesmas_id)
        .where(Signal.acknowledged_at.is_(None))
        .order_by(Signal.created_at.desc())
    ).all()
    return [ScraperVerificationSignalOut.model_validate(r._mapping) for r in rows]


@router.post("/{signal_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
def acknowledge_signal(
    signal_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> Response:
    result = db.execute(
        update(Signal)
        .where(Signal.id == signal_id, Signal.acknowledged_at.is_(None))
        .values(acknowledged_at=func.now(), acknowledged_by=admin_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pemberitahuan tidak ditemukan atau sudah ditandai dilihat")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
