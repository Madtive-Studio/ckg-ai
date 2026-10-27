import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin


class CredentialInvite(UUIDPKMixin, Base):
    """One-time link that lets a puskesmas set its own ASIK credential without an account.

    Only the SHA-256 of the token is stored, so a DB leak cannot be turned into working links. The
    link is consumed by stamping ``used_at`` in the same transaction that saves the credential;
    ``revoked_at`` is stamped on older pending links when an admin issues a new one.
    """

    __tablename__ = "credential_invites"

    puskesmas_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("puskesmas.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("admins.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
