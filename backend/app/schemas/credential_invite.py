from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


class InviteCreatedOut(BaseModel):
    """The only time the link exists in the clear — it is not recoverable afterwards."""

    url: str
    expires_at: datetime


class InviteInfoOut(BaseModel):
    """What the public page may learn from a link. Name/URL only while it is still usable."""

    status: Literal["pending", "used", "expired"]
    puskesmas_name: str | None = None
    asik_url: str | None = None


class InviteAsikIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=320)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]
