"""scraper verification signals: first sighting of data that answers an open scraper question

One row ever per (code, outcome); shown on the admin dashboard until acknowledged.

Revision ID: 0042_scraper_verification
Revises: 0041_credential_invites
Create Date: 2026-11-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_scraper_verification"
down_revision: str | None = "0041_credential_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scraper_verification_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("ok_count", sa.Integer(), nullable=False),
        sa.Column("problem_count", sa.Integer(), nullable=False),
        sa.Column("puskesmas_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("puskesmas.id"), nullable=False),
        sa.Column("scrape_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scrape_jobs.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("admins.id"), nullable=True),
        sa.UniqueConstraint("code", "outcome", name="uq_scraper_verification_signals_code_outcome"),
    )


def downgrade() -> None:
    op.drop_table("scraper_verification_signals")
