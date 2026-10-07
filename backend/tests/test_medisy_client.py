"""Tests for app/integrations/medisy_client.py.

No network: every call goes through ``httpx.MockTransport``. ``sleep`` is injected so the retry
tests run instantly, and the recorded delays prove the backoff / Retry-After behaviour.
"""
import threading
import time
from datetime import date

import httpx
import pytest

from app.integrations.medisy_client import (
    MAX_BATCH,
    PAGE_LIMIT,
    BundleBatch,
    MedisyAuthError,
    MedisyClient,
    MedisyNotFoundError,
    MedisyPing,
    MedisyRateLimitedError,
    MedisyRequestError,
    MedisyServerError,
    MedisyUnavailableError,
)

HOST = "clinic.medisy.id"
TOKEN = "t" * 40 + "-SECRET-TOKEN-VALUE"


def _client(handler, **kw) -> tuple[MedisyClient, list[float]]:
    delays: list[float] = []
    kw.setdefault("sleep", delays.append)
    return MedisyClient(HOST, TOKEN, transport=httpx.MockTransport(handler), **kw), delays


def _json(data, status=200, headers=None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


PING_OK = {"clinic": {"name": "Puskesmas Contoh"}, "api_version": 1, "timezone": "Asia/Jakarta",
           "server_time": "2026-10-05T10:00:00+07:00"}


# ----------------------------------------------------------------------------- construction


@pytest.mark.parametrize("host", ["", "https://clinic.medisy.id", "clinic.medisy.id/x", "a b.id", "clinic.id:8443",
                                  "user@clinic.id", "-bad.id", "bad-.id", "bad..id", "localhost", "10.0.0.1", "[::1]",
                                  "clinic.medisy.id.", "clinic.medisy.id?x=1"])
def test_host_must_be_a_bare_domain(host):
    with pytest.raises(ValueError):
        MedisyClient(host, TOKEN)


@pytest.mark.parametrize("token", ["", "has space", "tab\there", "new\nline"])
def test_token_must_be_non_empty_without_whitespace(token):
    with pytest.raises(ValueError):
        MedisyClient(HOST, token)


def test_concurrency_must_be_positive():
    with pytest.raises(ValueError):
        MedisyClient(HOST, TOKEN, concurrency=0)


# ----------------------------------------------------------------------------- request shape


def test_requests_are_https_bearer_json_and_under_the_api_path():
    seen = []

    def handler(req):
        seen.append(req)
        return _json(PING_OK)

    c, _ = _client(handler)
    c.ping()
    (req,) = seen
    assert str(req.url) == f"https://{HOST}/medisy_api/ckg/ping"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert req.headers["Accept"] == "application/json"
    assert "token" not in str(req.url).lower()          # never in the URL


def test_redirects_are_not_followed_and_the_token_does_not_leave():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    c, _ = _client(handler)
    with pytest.raises(MedisyRequestError) as e:
        c.ping()
    assert e.value.status_code == 302
    assert calls == [f"https://{HOST}/medisy_api/ckg/ping"]       # only the original host was contacted
    assert TOKEN not in str(e.value)


# ----------------------------------------------------------------------------- ping / rooms


def test_ping_parses_the_response():
    c, _ = _client(lambda r: _json(PING_OK))
    assert c.ping() == MedisyPing("Puskesmas Contoh", 1, "Asia/Jakarta", "2026-10-05T10:00:00+07:00")


def test_ping_rejects_a_server_that_is_not_the_ckg_api():
    c, _ = _client(lambda r: _json({"hello": "world"}))
    with pytest.raises(MedisyUnavailableError, match="not like a CKG API"):
        c.ping()


def test_ping_tolerates_a_missing_clinic_name():
    c, _ = _client(lambda r: _json({"api_version": 1}))
    assert c.ping().clinic_name is None


def test_rooms_returns_the_items():
    rooms = [{"id": 1, "name": "KLASTER 3 - CKG", "is_ckg": True}]
    c, _ = _client(lambda r: _json({"items": rooms, "poli_patterns": ["CKG"]}))
    assert c.rooms() == rooms


# ----------------------------------------------------------------------------- error mapping


@pytest.mark.parametrize("status, exc, text", [
    (401, MedisyAuthError, "rejected the token"),
    (403, MedisyAuthError, "HTTPS is required"),
    (404, MedisyNotFoundError, "Visit not found"),
    (422, MedisyRequestError, "date is required"),
    (500, MedisyServerError, "Internal server error"),
])
def test_error_statuses_map_to_exceptions_without_retrying(status, exc, text):
    calls = []

    def handler(req):
        calls.append(1)
        return _json({"detail": text}, status)

    c, delays = _client(handler)
    with pytest.raises(exc) as e:
        c.ping()
    assert text in str(e.value)
    assert len(calls) == 1 and delays == []            # none of these is retried


def test_error_messages_never_contain_the_token_or_a_raw_body():
    c, _ = _client(lambda r: httpx.Response(401, text=f"your token {TOKEN} is bad <html>"))
    with pytest.raises(MedisyAuthError) as e:
        c.ping()
    assert TOKEN not in str(e.value) and "<html>" not in str(e.value)


def test_detail_is_capped_and_non_string_detail_is_ignored():
    c, _ = _client(lambda r: _json({"detail": "x" * 5000}, 422))
    with pytest.raises(MedisyRequestError) as e:
        c.ping()
    assert len(str(e.value)) <= 200
    c, _ = _client(lambda r: _json({"detail": {"nested": TOKEN}}, 422))
    with pytest.raises(MedisyRequestError) as e:
        c.ping()
    assert TOKEN not in str(e.value) and "HTTP 422" in str(e.value)


def test_a_body_that_is_not_json_is_unavailable():
    c, _ = _client(lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(MedisyUnavailableError, match="not JSON"):
        c.ping()


# ----------------------------------------------------------------------------- retries


def test_503_is_retried_with_exponential_backoff_then_succeeds():
    answers = iter([503, 502, 200])

    def handler(req):
        s = next(answers)
        return _json(PING_OK) if s == 200 else _json({"detail": "down"}, s)

    c, delays = _client(handler, backoff_base=1.0)
    assert c.ping().api_version == 1
    assert len(delays) == 2
    assert 0.5 <= delays[0] <= 1.5 and 1.0 <= delays[1] <= 3.0      # base * 2**attempt * jitter(0.5..1.5)


def test_429_honours_retry_after_but_never_sleeps_longer_than_the_cap():
    answers = iter([(429, "2"), (429, "999"), (200, None)])

    def handler(req):
        s, ra = next(answers)
        return _json(PING_OK) if s == 200 else _json({"detail": "slow down"}, s, {"Retry-After": ra})

    c, delays = _client(handler)
    c.ping()
    assert delays == [2.0, 30.0]


def test_429_without_retry_after_falls_back_to_backoff():
    answers = iter([429, 200])
    c, delays = _client(lambda r: _json(PING_OK) if (s := next(answers)) == 200 else _json({"detail": "x"}, s), backoff_base=1.0)
    c.ping()
    assert len(delays) == 1 and 0.5 <= delays[0] <= 1.5


def test_retries_are_bounded_and_the_final_error_is_raised():
    calls = []

    def handler(req):
        calls.append(1)
        return _json({"detail": "slow down"}, 429, {"Retry-After": "1"})

    c, delays = _client(handler, max_retries=2)
    with pytest.raises(MedisyRateLimitedError) as e:
        c.ping()
    assert len(calls) == 3 and len(delays) == 2          # first try + 2 retries
    assert e.value.retry_after == 1.0


def test_503_that_never_recovers_becomes_a_server_error():
    c, _ = _client(lambda r: _json({"detail": "down"}, 503), max_retries=1)
    with pytest.raises(MedisyServerError) as e:
        c.ping()
    assert e.value.status_code == 503


@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow"),
                                   httpx.RemoteProtocolError("reset"), httpx.ConnectTimeout("dns")])
def test_network_errors_are_retried_then_reported_as_unavailable(error):
    calls = []

    def handler(req):
        calls.append(1)
        raise error

    c, delays = _client(handler, max_retries=2)
    with pytest.raises(MedisyUnavailableError) as e:
        c.ping()
    assert len(calls) == 3 and len(delays) == 2
    assert TOKEN not in str(e.value) and type(error).__name__ in str(e.value)


def test_a_network_blip_then_success():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("blip")
        return _json(PING_OK)

    c, delays = _client(handler)
    assert c.ping().api_version == 1 and len(delays) == 1


def test_max_retries_zero_never_retries():
    calls = []
    c, delays = _client(lambda r: (calls.append(1), _json({"detail": "x"}, 503))[1], max_retries=0)
    with pytest.raises(MedisyServerError):
        c.ping()
    assert len(calls) == 1 and delays == []


# ----------------------------------------------------------------------------- list_visits


def _visit(i):
    return {"visit_id": i, "nik": f"{i:016d}", "is_ckg": True}


def test_list_visits_follows_every_page_and_sends_the_documented_params():
    total = 205
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        page, limit = int(req.url.params["page"]), int(req.url.params["limit"])
        lo = (page - 1) * limit
        return _json({"items": [_visit(i) for i in range(lo, min(lo + limit, total))], "page": page, "limit": limit, "total": total})

    c, _ = _client(handler)
    items = c.list_visits(date(2026, 9, 2))
    assert [v["visit_id"] for v in items] == list(range(total))
    assert [p["page"] for p in seen] == ["1", "2", "3"]
    assert all(p["date"] == "2026-09-02" and p["ckg_only"] == "true" and p["limit"] == str(PAGE_LIMIT) for p in seen)


def test_list_visits_ckg_only_false_and_an_empty_day():
    seen = []
    c, _ = _client(lambda r: (seen.append(dict(r.url.params)), _json({"items": [], "page": 1, "limit": 100, "total": 0}))[1])
    assert c.list_visits(date(2000, 1, 1), ckg_only=False) == []
    assert seen == [{"date": "2000-01-01", "ckg_only": "false", "page": "1", "limit": "100"}]


def test_list_visits_stops_on_an_empty_page_even_if_total_lies():
    pages = iter([{"items": [_visit(1)], "total": 999}, {"items": [], "total": 999}])
    c, _ = _client(lambda r: _json(next(pages)))
    assert [v["visit_id"] for v in c.list_visits(date(2026, 9, 2))] == [1]


# ----------------------------------------------------------------------------- get_bundles


def _bundle(i):
    return {"api_version": 1, "visit": {"id": i}, "patient": {"identity": {"number": f"{i:016d}"}}}


def _batch_handler(known=lambda i: True, log=None, delay=0.0):
    def handler(req):
        import json
        ids = json.loads(req.content)["visit_ids"]
        if log is not None:
            log.append(ids)
        if delay:
            time.sleep(delay)
        return _json({"items": [_bundle(i) for i in ids if known(i)], "missing": [i for i in ids if not known(i)]})
    return handler


def test_get_bundles_chunks_to_the_server_limit_and_keeps_request_order():
    log = []
    ids = list(range(1000, 1000 + 120))
    c, _ = _client(_batch_handler(log=log))
    out = c.get_bundles(ids)
    assert isinstance(out, BundleBatch)
    assert sorted(len(x) for x in log) == [20, 50, 50]
    assert all(len(x) <= MAX_BATCH for x in log)
    assert [b["visit"]["id"] for b in out.items] == ids          # order preserved across parallel chunks
    assert out.missing == []


def test_get_bundles_reports_missing_ids_across_chunks():
    ids = list(range(1, 121))
    c, _ = _client(_batch_handler(known=lambda i: i % 10 != 0))
    out = c.get_bundles(ids)
    assert out.missing == [i for i in ids if i % 10 == 0]
    assert [b["visit"]["id"] for b in out.items] == [i for i in ids if i % 10 != 0]


def test_get_bundles_dedupes_and_makes_no_request_for_no_ids():
    log = []
    c, _ = _client(_batch_handler(log=log))
    assert c.get_bundles([5, 5, 6, 5]).items[0]["visit"]["id"] == 5
    assert log == [[5, 6]]
    log.clear()
    assert c.get_bundles([]) == BundleBatch(items=[], missing=[])
    assert log == []


@pytest.mark.parametrize("bad", [[0], [-1], ["1"], [1.5], [True], [None]])
def test_get_bundles_rejects_non_positive_integers_before_any_request(bad):
    log = []
    c, _ = _client(_batch_handler(log=log))
    with pytest.raises(ValueError):
        c.get_bundles(bad)
    assert log == []


def test_get_bundles_concurrency_is_bounded():
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def handler(req):
        import json
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        ids = json.loads(req.content)["visit_ids"]
        return _json({"items": [_bundle(i) for i in ids], "missing": []})

    c, _ = _client(handler, concurrency=2)
    c.get_bundles(list(range(1, 1 + MAX_BATCH * 6)))            # 6 chunks
    assert state["max"] == 2                                      # parallel, but never above the limit

    state.update(now=0, max=0)
    c, _ = _client(handler, concurrency=1)
    c.get_bundles(list(range(1, 1 + MAX_BATCH * 3)))
    assert state["max"] == 1


def test_get_bundles_a_failing_chunk_fails_the_whole_call():
    def handler(req):
        import json
        ids = json.loads(req.content)["visit_ids"]
        if 75 in ids:
            return _json({"detail": "Internal server error"}, 500)
        return _json({"items": [_bundle(i) for i in ids], "missing": []})

    c, _ = _client(handler)
    with pytest.raises(MedisyServerError):
        c.get_bundles(list(range(1, 121)))


def test_get_bundles_rejects_a_response_for_visits_that_were_not_asked_for():
    c, _ = _client(lambda r: _json({"items": [_bundle(999)], "missing": []}))
    with pytest.raises(MedisyUnavailableError, match="different set of visits"):
        c.get_bundles([1])


def test_get_bundles_rejects_a_response_that_drops_a_visit_silently():
    c, _ = _client(lambda r: _json({"items": [_bundle(1)], "missing": []}))     # asked for 1 and 2
    with pytest.raises(MedisyUnavailableError):
        c.get_bundles([1, 2])


def test_get_bundles_retries_a_chunk_on_429_and_still_returns_everything():
    state = {"n": 0}

    def handler(req):
        import json
        state["n"] += 1
        if state["n"] == 1:
            return _json({"detail": "Too many requests"}, 429, {"Retry-After": "1"})
        ids = json.loads(req.content)["visit_ids"]
        return _json({"items": [_bundle(i) for i in ids], "missing": []})

    c, delays = _client(handler)
    assert len(c.get_bundles([1, 2, 3]).items) == 3
    assert delays == [1.0]


def test_request_bodies_are_not_logged(caplog):
    caplog.set_level("DEBUG")
    c, _ = _client(lambda r: _json({"detail": "down"}, 503), max_retries=1)
    with pytest.raises(MedisyServerError):
        c.get_bundles([123456])
    text = caplog.text
    assert TOKEN not in text and "123456" not in text and "visit_ids" not in text


def test_context_manager_closes_the_client():
    with MedisyClient(HOST, TOKEN, transport=httpx.MockTransport(lambda r: _json(PING_OK))) as c:
        c.ping()
    with pytest.raises(RuntimeError):
        c.ping()                       # httpx refuses a closed client


# ── local-testing escape hatch: plain http to localhost, guarded three ways ──


def _client_for(host, monkeypatch, *, flag, env="local"):
    from app.config import settings

    monkeypatch.setattr(settings, "MEDISY_ALLOW_INSECURE_LOCALHOST", flag)
    monkeypatch.setattr(settings, "APP_ENV", env)
    return MedisyClient(host, "t" * 40)


def test_localhost_with_a_port_uses_http_only_when_the_flag_is_on_and_env_is_local(monkeypatch):
    with _client_for("localhost:62082", monkeypatch, flag=True) as c:
        assert str(c._http.base_url).startswith("http://localhost:62082/")
    with _client_for("127.0.0.1:8081", monkeypatch, flag=True) as c:
        assert str(c._http.base_url).startswith("http://127.0.0.1:8081/")


def test_localhost_is_refused_by_default_and_in_production(monkeypatch):
    with pytest.raises(ValueError):
        _client_for("localhost:62082", monkeypatch, flag=False)
    with pytest.raises(ValueError):
        _client_for("localhost:62082", monkeypatch, flag=True, env="production")


def test_the_flag_never_opens_any_other_host_to_http(monkeypatch):
    for host in ("clinic.example.id:8080", "localhost", "10.0.0.5:8080", "localhost:80/x"):
        with pytest.raises(ValueError):
            _client_for(host, monkeypatch, flag=True)
    with _client_for("clinic.medisy.id", monkeypatch, flag=True) as c:      # a normal domain stays https
        assert str(c._http.base_url).startswith("https://clinic.medisy.id/")
