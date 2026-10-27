import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, load_only

from app.api.deps import get_current_admin_id, get_db
from app.config import settings
from app.core.rate_limit import enforce_invite_rate_limit
from app.crud import puskesmas as crud
from app.models.credential_invite import CredentialInvite
from app.models.puskesmas import Puskesmas
from app.schemas.credential_invite import InviteAsikIn, InviteCreatedOut, InviteInfoOut
from app.schemas.puskesmas import CredIn

INVITE_TTL = timedelta(days=7)

# Admin issues the link (internal admins only, like every other management endpoint).
admin_router = APIRouter(prefix="/puskesmas", tags=["credential-invites"])
# Public: no login — the unguessable link token is the only credential.
public_router = APIRouter(prefix="/invites", tags=["credential-invites"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@admin_router.post(
    "/{id}/credential-invites",
    response_model=InviteCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
def create_credential_invite(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> InviteCreatedOut:
    if db.scalar(select(Puskesmas.id).where(Puskesmas.id == id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Puskesmas not found")
    # A new link supersedes any still-pending one so a stale link left in a chat stops working.
    db.execute(
        update(CredentialInvite)
        .where(
            CredentialInvite.puskesmas_id == id,
            CredentialInvite.used_at.is_(None),
            CredentialInvite.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    )
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + INVITE_TTL
    db.add(
        CredentialInvite(
            puskesmas_id=id,
            token_hash=_hash(token),
            expires_at=expires_at,
            created_by=admin_id,
        )
    )
    db.commit()
    base = settings.DASHBOARD_PUBLIC_URL.rstrip("/")
    return InviteCreatedOut(url=f"{base}/invite/{token}", expires_at=expires_at)


@public_router.get("/{token}", response_model=InviteInfoOut)
def get_credential_invite(
    token: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> InviteInfoOut:
    enforce_invite_rate_limit(request)
    response.headers["Cache-Control"] = "no-store"
    # Joins Puskesmas, so the soft-delete filter hides links of a deleted puskesmas (→ 404).
    row = db.execute(
        select(
            CredentialInvite.expires_at,
            CredentialInvite.used_at,
            CredentialInvite.revoked_at,
            Puskesmas.name,
            Puskesmas.asik_url,
        )
        .join(Puskesmas, Puskesmas.id == CredentialInvite.puskesmas_id)
        .where(CredentialInvite.token_hash == _hash(token))
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    if row.used_at is not None:
        return InviteInfoOut(status="used")
    if row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        return InviteInfoOut(status="expired")
    return InviteInfoOut(status="pending", puskesmas_name=row.name, asik_url=row.asik_url)


@public_router.post("/{token}/asik", status_code=status.HTTP_204_NO_CONTENT)
def submit_invite_asik_cred(
    token: str,
    data: InviteAsikIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> None:
    enforce_invite_rate_limit(request)
    response.headers["Cache-Control"] = "no-store"
    # Claim the link and save the credential in ONE transaction: the conditional UPDATE is the
    # single-use gate (two racing submits → exactly one row comes back), and a failure before the
    # commit below rolls the claim back so the link is not burned without a saved credential.
    puskesmas_id = db.scalar(
        update(CredentialInvite)
        .where(
            CredentialInvite.token_hash == _hash(token),
            CredentialInvite.used_at.is_(None),
            CredentialInvite.revoked_at.is_(None),
            CredentialInvite.expires_at > func.now(),
        )
        .values(used_at=func.now())
        .returning(CredentialInvite.puskesmas_id)
    )
    if puskesmas_id is None:
        db.rollback()
        known = db.scalar(select(CredentialInvite.id).where(CredentialInvite.token_hash == _hash(token)))
        if known is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
        raise HTTPException(status.HTTP_410_GONE, "This invite link has already been used or has expired")
    obj = db.scalar(
        select(Puskesmas).options(load_only(Puskesmas.id, Puskesmas.asik_cred)).where(Puskesmas.id == puskesmas_id)
    )
    if obj is None:  # puskesmas soft-deleted since the link was issued
        db.rollback()
        raise HTTPException(status.HTTP_410_GONE, "This invite link has already been used or has expired")
    crud.set_cred(db, obj, "asik", CredIn(email=data.email, password=data.password))
