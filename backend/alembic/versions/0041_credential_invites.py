"""credential invites: one-time links for a puskesmas to set its own ASIK credential

Only the SHA-256 of the link token is stored. ``used_at`` is stamped atomically with the credential
write (single use); ``revoked_at`` retires older pending links when a new one is issued.

Revision ID: 0041_credential_invites
Revises: 0040_loop_changes_ready
Create Date: 2026-10-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_credential_invites"
down_revision: str | None = "0040_loop_changes_ready"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credential_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("puskesmas_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("puskesmas.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("admins.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credential_invites_puskesmas_id", "credential_invites", ["puskesmas_id"])


def downgrade() -> None:
    op.drop_index("ix_credential_invites_puskesmas_id", table_name="credential_invites")
    op.drop_table("credential_invites")
