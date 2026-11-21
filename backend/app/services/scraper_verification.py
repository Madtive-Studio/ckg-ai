"""Turn a scrape's ``metadata.verify_counts`` into admin notices for still-open scraper questions.

The ASIK scraper counts events that answer the questions in ``scrapers/asik/CLAUDE.md`` → "Not yet verified"
(e.g. a submitted Nakes form was read, a tatalaksana fetch failed). The first job that sees each
(question, outcome) pair gets one ``ScraperVerificationSignal`` row — ever — which the admin dashboard shows until
acknowledged. Later sightings are ignored (ON CONFLICT DO NOTHING), so a recurring event never re-notifies.
"""
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.scraper_verification_signal import ScraperVerificationSignal

ANSWERED = "answered"
PROBLEM = "problem"

# question code -> (scraper count key meaning "seen and read fine", key meaning "seen and failed").
# None = that side doesn't exist for the question. Keep the codes in sync with the frontend-internal labels
# (lib/scraper-verification-labels.ts).
QUESTIONS: dict[str, tuple[str | None, str | None]] = {
    "asik_nakes_filled": ("nakes_submitted_read", "nakes_submitted_empty"),
    "asik_tatalaksana": ("tatalaksana_ok", "tatalaksana_error"),
    "asik_tab_belum": ("tab_belum_ok", "tab_belum_error"),
    "asik_tab_sedang": ("tab_sedang_ok", "tab_sedang_error"),
    "asik_detail_failed": (None, "detail_failed"),
}


def signals_from_counts(counts: dict[str, Any] | None) -> list[dict[str, Any]]:
    """``[{code, outcome, ok_count, problem_count}]`` for every question this scrape saw. Any failure for a
    question makes it a ``problem``; otherwise at least one success makes it ``answered``."""
    counts = counts or {}

    def _n(key: str | None) -> int:
        try:
            return max(int(counts.get(key) or 0), 0) if key else 0
        except (TypeError, ValueError):
            return 0

    out = []
    for code, (ok_key, problem_key) in QUESTIONS.items():
        ok, problem = _n(ok_key), _n(problem_key)
        if problem:
            outcome = PROBLEM
        elif ok:
            outcome = ANSWERED
        else:
            continue
        out.append({"code": code, "outcome": outcome, "ok_count": ok, "problem_count": problem})
    return out


def record_first_sightings(
    db: Session, *, puskesmas_id: uuid.UUID, scrape_job_id: uuid.UUID, counts: dict[str, Any] | None
) -> int:
    """Insert a row for each (code, outcome) pair not recorded before. Caller commits. Returns rows attempted."""
    rows = [
        {**s, "id": uuid.uuid4(), "puskesmas_id": puskesmas_id, "scrape_job_id": scrape_job_id}
        for s in signals_from_counts(counts)
    ]
    if rows:
        db.execute(
            insert(ScraperVerificationSignal)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_scraper_verification_signals_code_outcome")
        )
    return len(rows)
