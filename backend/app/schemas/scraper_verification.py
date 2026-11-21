import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ScraperVerificationSignalOut(BaseModel):
    id: uuid.UUID
    code: str
    outcome: Literal["answered", "problem"]
    ok_count: int
    problem_count: int
    puskesmas_id: uuid.UUID
    puskesmas_name: str
    scrape_job_id: uuid.UUID
    created_at: datetime
