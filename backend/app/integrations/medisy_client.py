"""HTTP client for Medisy's read-only CKG API (himed-app ``/medisy_api/ckg``).

Medisy is the clinic-record source. This client replaces the EPUS Playwright scrape: instead of
logging in and walking ~33 HTML tabs per patient it makes a handful of JSON calls.

    ping()                 E0  token check + clinic info ("Test connection")
    rooms()                E1  poli list and which of them match the CKG rule
    list_visits(day)       E2  the CKG visits of one calendar day (all pages)
    get_bundles(ids)       E3  full visit bundles, chunked to the server's 50-id limit

Safety properties (each is covered by tests/test_medisy_client.py):
  * HTTPS only, no redirects followed (a redirect would carry the bearer token to another host).
  * Retries only what is safe to repeat — every call here is a read — and only on transient
    failures: network errors/timeouts, 429 (honours ``Retry-After``) and 502/503/504. Exponential
    backoff with jitter. Everything else (401/403/404/422/other 5xx) fails immediately.
  * The token is never part of an exception message or a log line. Neither are request bodies:
    bundles contain patient data.
  * Concurrency is bounded (``concurrency`` parallel batch requests, default 3) so a large day
    cannot trip the server's per-IP rate limit.

Sync on purpose: it is called from Celery tasks and FastAPI sync handlers.
"""
from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

API_PATH = "/medisy_api/ckg"
MAX_BATCH = 50           # E3: the server rejects more than 50 visit ids per request
PAGE_LIMIT = 100         # E2: the server's maximum page size
_MAX_PAGES = 500         # E2 safety valve: 50k visits in one day is not a real day

# Same shape the puskesmas form enforces (schemas/puskesmas.py ``BaseUrl``): dotted labels and an alphabetic TLD,
# so a bare host such as "localhost" or an IP literal can never be used as the target.
_LOCAL_DEV_RE = re.compile(r"^(?:localhost|127\.0\.0\.1):[0-9]{2,5}$")
_HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")
_MAX_RETRY_AFTER = 30.0  # never sleep longer than this because a server asked us to
_RETRY_STATUSES = frozenset({502, 503, 504})


# --------------------------------------------------------------------------- errors


class MedisyError(Exception):
    """Base class. ``str(exc)`` is always safe to show to a user (no token, no patient data)."""


class MedisyAuthError(MedisyError):
    """401 / 403: wrong token, or this server's IP / transport is not allowed."""


class MedisyNotFoundError(MedisyError):
    """404: unknown path or visit."""


class MedisyRateLimitedError(MedisyError):
    """429 that survived the retries."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MedisyRequestError(MedisyError):
    """Any other 4xx (typically 422: we sent something the API refuses) or an unexpected redirect."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class MedisyServerError(MedisyError):
    """5xx that survived the retries (500 is never retried: the API only returns it for a real fault)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class MedisyUnavailableError(MedisyError):
    """Cannot talk to the server: DNS / connect / TLS failure, timeout, or a body that is not JSON."""


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class MedisyPing:
    clinic_name: str | None
    api_version: int
    timezone: str | None
    server_time: str | None


@dataclass(frozen=True)
class BundleBatch:
    """``items`` are in the order the ids were requested; ``missing`` are ids that are unknown,
    cancelled or deleted in Medisy (not an error)."""

    items: list[dict[str, Any]]
    missing: list[int]


# --------------------------------------------------------------------------- client


class MedisyClient:
    def __init__(
        self,
        host: str,
        token: str,
        *,
        timeout: httpx.Timeout | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        concurrency: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # ``host`` is a bare domain (validated when the puskesmas is saved); re-check here so a
        # malformed value can never turn into a request to another place.
        local_dev = (
            settings.MEDISY_ALLOW_INSECURE_LOCALHOST and settings.APP_ENV == "local" and bool(_LOCAL_DEV_RE.match(host or ""))
        )
        if not local_dev and not _HOST_RE.match(host or ""):
            raise ValueError("host must be a bare domain name such as 'clinic.medisy.id'")
        if not token or any(c.isspace() for c in token):
            raise ValueError("token must be a non-empty string without whitespace")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")

        self._max_retries = max(0, max_retries)
        self._backoff_base = backoff_base
        self._concurrency = concurrency
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=f"{'http' if local_dev else 'https'}://{host}{API_PATH}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout or httpx.Timeout(60.0, connect=10.0),
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> MedisyClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ endpoints

    def ping(self) -> MedisyPing:
        data = self._request("GET", "/ping")
        if not isinstance(data, dict) or "api_version" not in data:
            raise MedisyUnavailableError("Medisy answered, but not like a CKG API (unexpected /ping body)")
        clinic = data.get("clinic")
        return MedisyPing(
            clinic_name=clinic.get("name") if isinstance(clinic, dict) else None,
            api_version=int(data["api_version"]),
            timezone=data.get("timezone"),
            server_time=data.get("server_time"),
        )

    def rooms(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/rooms").get("items", []))

    def list_visits(self, day: date, *, ckg_only: bool = True) -> list[dict[str, Any]]:
        """Every visit of ``day`` (all pages). With ``ckg_only`` (the default) only visits matching
        the CKG rule; cancelled / deleted visits are never listed."""
        items: list[dict[str, Any]] = []
        for page in range(1, _MAX_PAGES + 1):
            data = self._request("GET", "/visits", params={
                "date": day.isoformat(), "ckg_only": "true" if ckg_only else "false",
                "page": page, "limit": PAGE_LIMIT,
            })
            batch = data.get("items", [])
            items.extend(batch)
            if not batch or len(items) >= int(data.get("total", 0)):
                return items
        raise MedisyRequestError(f"more than {_MAX_PAGES} pages of visits for {day}", 200)

    def get_bundles(self, visit_ids: Iterable[int]) -> BundleBatch:
        """Full bundles for ``visit_ids`` (duplicates ignored), fetched in chunks of ``MAX_BATCH``
        with at most ``concurrency`` requests in flight."""
        ids = self._clean_ids(visit_ids)
        if not ids:
            return BundleBatch(items=[], missing=[])

        chunks = [ids[i:i + MAX_BATCH] for i in range(0, len(ids), MAX_BATCH)]
        if len(chunks) == 1 or self._concurrency == 1:
            results = [self._fetch_chunk(c) for c in chunks]
        else:
            with ThreadPoolExecutor(max_workers=min(self._concurrency, len(chunks))) as pool:
                results = list(pool.map(self._fetch_chunk, chunks))   # map keeps chunk order

        items: list[dict[str, Any]] = []
        missing: list[int] = []
        for chunk_items, chunk_missing in results:
            items.extend(chunk_items)
            missing.extend(chunk_missing)
        return BundleBatch(items=items, missing=missing)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _clean_ids(visit_ids: Iterable[int]) -> list[int]:
        out: list[int] = []
        seen: set[int] = set()
        for v in visit_ids:
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ValueError("visit ids must be positive integers")
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    def _fetch_chunk(self, chunk: list[int]) -> tuple[list[dict[str, Any]], list[int]]:
        data = self._request("POST", "/visits/batch", json={"visit_ids": chunk})
        items = data.get("items", [])
        missing = [int(i) for i in data.get("missing", [])]
        asked = set(chunk)
        returned = {b.get("visit", {}).get("id") for b in items}
        if not returned <= asked or len(items) + len(missing) != len(chunk):
            raise MedisyUnavailableError("Medisy returned a different set of visits than requested")
        return items, missing

    def _delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(max(retry_after, 0.0), _MAX_RETRY_AFTER)
        return self._backoff_base * (2 ** attempt) * (0.5 + random.random())   # jitter: 50%-150%

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            try:
                resp = self._http.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_retries:
                    raise MedisyUnavailableError(
                        f"cannot reach Medisy ({type(exc).__name__}) after {attempt + 1} attempts"
                    ) from exc
                logger.warning("medisy %s %s: %s, retrying", method, path, type(exc).__name__)
                self._sleep(self._delay(attempt))
                attempt += 1
                continue

            if (resp.status_code == 429 or resp.status_code in _RETRY_STATUSES) and attempt < self._max_retries:
                logger.warning("medisy %s %s: HTTP %s, retrying", method, path, resp.status_code)
                self._sleep(self._delay(attempt, self._retry_after(resp)))
                attempt += 1
                continue
            return self._parse(resp)

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        try:
            return float(resp.headers["Retry-After"])
        except (KeyError, ValueError):
            return None

    @staticmethod
    def _detail(resp: httpx.Response) -> str:
        """The API's ``{"detail": "..."}`` message, or a generic fallback. Capped; never the raw body."""
        try:
            detail = resp.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        return (detail if isinstance(detail, str) and detail else f"HTTP {resp.status_code}")[:200]

    def _parse(self, resp: httpx.Response) -> Any:
        code = resp.status_code
        if 200 <= code < 300:
            try:
                return resp.json()
            except ValueError as exc:
                raise MedisyUnavailableError("Medisy answered with a body that is not JSON") from exc
        detail = self._detail(resp)
        if code == 401:
            raise MedisyAuthError("Medisy rejected the token (401)")
        if code == 403:
            raise MedisyAuthError(f"Medisy refused this server ({detail})")
        if code == 404:
            raise MedisyNotFoundError(detail)
        if code == 429:
            raise MedisyRateLimitedError("Medisy rate limit hit (429)", self._retry_after(resp))
        if 300 <= code < 400:
            raise MedisyRequestError(f"unexpected redirect (HTTP {code}); redirects are not followed", code)
        if code >= 500:
            raise MedisyServerError(f"Medisy server error ({detail})", code)
        raise MedisyRequestError(detail, code)
