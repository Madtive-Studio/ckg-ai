import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin


class ScraperVerificationSignal(UUIDPKMixin, Base):
    """First sighting, in a real scrape, of data that answers an open scraper question.

    Some scraper paths could not be tested when they were written because no such data existed yet (see
    ``scrapers/asik/CLAUDE.md`` → "Not yet verified"). The scraper counts those events; the worker records the
    FIRST job that saw each (question, outcome) pair — one row ever per pair — and the admin dashboard shows it
    until an admin acknowledges it. Counts and ids only: no patient data.
    """

    __tablename__ = "scraper_verification_signals"
    __table_args__ = (UniqueConstraint("code", "outcome", name="uq_scraper_verification_signals_code_outcome"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    # "answered" — the data appeared and was read; "problem" — it appeared and reading it failed.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    ok_count: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_count: Mapped[int] = mapped_column(Integer, nullable=False)
    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("puskesmas.id"), nullable=False
    )
    scrape_job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("scrape_jobs.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("admins.id"), nullable=True
    )
