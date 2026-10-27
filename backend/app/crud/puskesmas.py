import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.core.security import decrypt_cred, encrypt_cred
from app.integrations.medisy_client import MedisyClient, MedisyError
from app.models.puskesmas import Puskesmas
from app.schemas.puskesmas import CredIn, MedisyCredIn, PuskesmasCreate, PuskesmasUpdate

logger = logging.getLogger(__name__)

CredKind = Literal["epus", "asik"]
AsikSyncResult = Literal["updated", "unchanged", "not_in_medisy", "medisy_not_configured", "medisy_unavailable"]


def create(db: Session, data: PuskesmasCreate) -> Puskesmas:
    obj = Puskesmas(
        name=data.name,
        epus_url=data.epus_url,
        asik_url=data.asik_url,
        asik_default_alamat=(
            data.asik_default_alamat.model_dump() if data.asik_default_alamat else None
        ),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(db: Session, obj: Puskesmas, data: PuskesmasUpdate) -> Puskesmas:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


def soft_delete(db: Session, obj: Puskesmas) -> None:
    obj.deleted_at = datetime.now(UTC)
    db.commit()


def set_cred(db: Session, obj: Puskesmas, kind: CredKind, data: CredIn | MedisyCredIn) -> None:
    encrypted = encrypt_cred(data.model_dump())
    if kind == "epus":
        obj.epus_cred = encrypted
    else:
        obj.asik_cred = encrypted
    db.commit()


def clear_cred(db: Session, obj: Puskesmas, kind: CredKind) -> None:
    if kind == "epus":
        obj.epus_cred = None
    else:
        obj.asik_cred = None
    db.commit()


def get_cred_decrypted(obj: Puskesmas, kind: CredKind) -> dict[str, str] | None:
    token = obj.epus_cred if kind == "epus" else obj.asik_cred
    if token is None:
        return None
    return decrypt_cred(token)


def refresh_asik_cred_from_medisy(db: Session, puskesmas_id: uuid.UUID) -> AsikSyncResult:
    """Make the ASIK login saved in Medisy the one ckg-ai uses, then store it (encrypted) in ``asik_cred``.

    Medisy is the source of truth: a changed login there reaches ckg-ai on the next ASIK job without anyone
    re-typing it here. ``asik_cred`` stays the working copy so everything that checks "is ASIK set up?" keeps
    working. Never raises: if Medisy is not configured, has no login saved, or cannot be reached, the copy we
    already hold (a login entered by hand, or the last one fetched) is left alone and the caller carries on with it.
    """
    obj = db.scalar(
        select(Puskesmas)
        .options(load_only(Puskesmas.id, Puskesmas.epus_url, Puskesmas.epus_cred, Puskesmas.asik_cred))
        .where(Puskesmas.id == puskesmas_id)
    )
    if obj is None or not obj.epus_url or obj.epus_cred is None:
        return "medisy_not_configured"
    token = (get_cred_decrypted(obj, "epus") or {}).get("token")
    if not token:
        return "medisy_not_configured"

    try:
        with MedisyClient(obj.epus_url, token, max_retries=1) as client:
            fetched = client.asik_credential()
    except (MedisyError, ValueError) as exc:
        logger.warning("puskesmas %s: could not read the ASIK login from Medisy: %s", puskesmas_id, exc)
        return "medisy_unavailable"
    if fetched is None:
        return "not_in_medisy"

    new = {"email": fetched.email, "password": fetched.password}
    if obj.asik_cred is not None and get_cred_decrypted(obj, "asik") == new:
        return "unchanged"
    obj.asik_cred = encrypt_cred(new)
    db.commit()
    return "updated"
