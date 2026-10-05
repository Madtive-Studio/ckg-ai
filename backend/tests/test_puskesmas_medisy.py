"""Medisy as the clinic-record source: the {token} credential and "Test connection".

Fully offline: the DB is a MagicMock, redis rate limiting is patched out, and Medisy is
``httpx.MockTransport``. Credentials go through the real Fernet encrypt/decrypt (conftest sets the key).
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.routes.puskesmas as routes
from app.api.deps import Principal, get_db, get_principal
from app.core.security import decrypt_cred, encrypt_cred
from app.integrations.medisy_client import MedisyClient
from app.main import app
from app.schemas.puskesmas import CredIn, MedisyCredIn

TOKEN = "k" * 32 + "-medisy-token"
PID = uuid.uuid4()
PING = {"clinic": {"name": "Puskesmas Contoh"}, "api_version": 1, "timezone": "Asia/Jakarta",
        "server_time": "2026-10-05T10:00:00+07:00"}


def _row(*, url="clinic.medisy.id", cred="token"):
    c = {"token": encrypt_cred({"token": TOKEN}), None: None, "legacy": encrypt_cred({"email": "a@b.id", "password": "pw"})}[cred]
    return SimpleNamespace(id=PID, epus_url=url, epus_cred=c, asik_cred=None)


@pytest.fixture
def api(monkeypatch):
    """(client, fake_db, state) — admin principal, redis limiter patched, MedisyClient on a mock transport."""
    fake_db = MagicMock()
    state = {"requests": [], "handler": lambda req: httpx.Response(200, json=PING), "limited": 0}

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_principal] = lambda: Principal("admin", uuid.uuid4(), None)

    def limiter(_pid):
        state["limited"] += 1

    monkeypatch.setattr(routes, "enforce_medisy_test_rate_limit", limiter)

    def make_client(host, token, **kw):
        def handler(req):
            state["requests"].append(req)
            return state["handler"](req)
        return MedisyClient(host, token, transport=httpx.MockTransport(handler), sleep=lambda _s: None, **kw)

    monkeypatch.setattr(routes, "MedisyClient", make_client)
    with TestClient(app) as client:
        yield client, fake_db, state
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------------- schema


def test_medisy_cred_in_accepts_a_long_token_only():
    assert MedisyCredIn(token=TOKEN).token == TOKEN
    for bad in ("short", "x" * 31, "x" * 257, "has space " + "x" * 30, "tab\t" + "x" * 30, ""):
        with pytest.raises(ValidationError):
            MedisyCredIn(token=bad)


def test_medisy_cred_in_forbids_extra_fields_so_it_never_matches_an_email_password_body():
    with pytest.raises(ValidationError):
        MedisyCredIn(token=TOKEN, email="a@b.id")
    with pytest.raises(ValidationError):
        MedisyCredIn(token=TOKEN, password="x")


def test_cred_in_still_needs_both_email_and_password():
    with pytest.raises(ValidationError):
        CredIn(email="a@b.id")


# ----------------------------------------------------------------------------- PUT credentials


def test_epus_slot_accepts_a_medisy_token_and_stores_it_encrypted(api):
    client, db, _ = api
    obj = SimpleNamespace(id=PID, epus_cred=None, asik_cred=None)
    db.scalar.return_value = obj
    r = client.put(f"/puskesmas/{PID}/credentials/epus", json={"token": TOKEN})
    assert r.status_code == 204
    assert isinstance(obj.epus_cred, bytes) and TOKEN.encode() not in obj.epus_cred     # not stored in clear
    assert decrypt_cred(obj.epus_cred) == {"token": TOKEN}
    db.commit.assert_called_once()


def test_epus_slot_still_accepts_email_and_password_during_the_transition(api):
    client, db, _ = api
    obj = SimpleNamespace(id=PID, epus_cred=None, asik_cred=None)
    db.scalar.return_value = obj
    assert client.put(f"/puskesmas/{PID}/credentials/epus", json={"email": "a@b.id", "password": "pw"}).status_code == 204
    assert decrypt_cred(obj.epus_cred) == {"email": "a@b.id", "password": "pw"}


def test_asik_slot_refuses_a_token(api):
    client, db, _ = api
    obj = SimpleNamespace(id=PID, epus_cred=None, asik_cred=None)
    db.scalar.return_value = obj
    r = client.put(f"/puskesmas/{PID}/credentials/asik", json={"token": TOKEN})
    assert r.status_code == 422 and "email and a password" in r.json()["detail"]
    assert obj.asik_cred is None
    db.commit.assert_not_called()


@pytest.mark.parametrize("body", [{"token": "short"}, {"token": TOKEN, "email": "a@b.id"}, {}, {"password": "x"}, {"token": 123}])
def test_invalid_bodies_are_rejected_with_the_standard_error_shape(api, body):
    client, db, _ = api
    db.scalar.return_value = SimpleNamespace(id=PID, epus_cred=None, asik_cred=None)
    r = client.put(f"/puskesmas/{PID}/credentials/epus", json=body)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)       # {"detail": "<string>"}
    db.commit.assert_not_called()


def test_a_user_of_another_puskesmas_cannot_set_the_token(api):
    client, db, _ = api
    app.dependency_overrides[get_principal] = lambda: Principal("user", uuid.uuid4(), uuid.uuid4())
    assert client.put(f"/puskesmas/{PID}/credentials/epus", json={"token": TOKEN}).status_code == 403
    db.scalar.assert_not_called()


# ----------------------------------------------------------------------------- decrypt


def test_decrypt_returns_the_token_shape_for_a_medisy_credential(api, monkeypatch):
    client, db, _ = api
    monkeypatch.setattr(routes, "enforce_decrypt_rate_limit", lambda *_a: None)
    db.scalar.return_value = _row()
    r = client.post(f"/puskesmas/{PID}/credentials/epus/decrypt")
    assert r.status_code == 200 and r.json() == {"token": TOKEN}


def test_decrypt_still_returns_email_and_password_for_a_legacy_credential(api, monkeypatch):
    client, db, _ = api
    monkeypatch.setattr(routes, "enforce_decrypt_rate_limit", lambda *_a: None)
    db.scalar.return_value = _row(cred="legacy")
    assert client.post(f"/puskesmas/{PID}/credentials/epus/decrypt").json() == {"email": "a@b.id", "password": "pw"}


# ----------------------------------------------------------------------------- test-connection


def test_connection_ok_reports_clinic_and_never_the_token(api):
    client, db, state = api
    db.scalar.return_value = _row()
    r = client.post(f"/puskesmas/{PID}/test-connection")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["error"] is None
    assert body["clinic_name"] == "Puskesmas Contoh" and body["api_version"] == 1 and body["timezone"] == "Asia/Jakarta"
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert TOKEN not in r.text
    (req,) = state["requests"]
    assert str(req.url) == "https://clinic.medisy.id/medisy_api/ckg/ping" and req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert state["limited"] == 1                                    # the rate limiter ran


@pytest.mark.parametrize("status, text", [(401, "rejected the token"), (403, "refused this server"), (500, "server error")])
def test_connection_failures_are_a_200_with_ok_false(api, status, text):
    client, db, state = api
    db.scalar.return_value = _row()
    state["handler"] = lambda req: httpx.Response(status, json={"detail": "nope"})
    r = client.post(f"/puskesmas/{PID}/test-connection")
    assert r.status_code == 200 and r.json()["ok"] is False and text in r.json()["error"]
    assert TOKEN not in r.text


def test_connection_unreachable_is_reported_not_raised(api):
    client, db, state = api
    db.scalar.return_value = _row()

    def boom(req):
        raise httpx.ConnectError("dns failure")

    state["handler"] = boom
    r = client.post(f"/puskesmas/{PID}/test-connection")
    assert r.status_code == 200 and r.json()["ok"] is False and "cannot reach Medisy" in r.json()["error"]
    assert len(state["requests"]) == 2                              # one retry, then give up (fast: this is a button click)


@pytest.mark.parametrize("row, message", [
    (_row(url=None), "URL is not set"),
    (_row(cred=None), "token is not set"),
    (_row(cred="legacy"), "not a Medisy token"),
])
def test_connection_incomplete_setup_says_what_is_missing_without_calling_medisy(api, row, message):
    client, db, state = api
    db.scalar.return_value = row
    r = client.post(f"/puskesmas/{PID}/test-connection")
    assert r.status_code == 200 and r.json()["ok"] is False and message in r.json()["error"]
    assert state["requests"] == []


def test_connection_with_a_malformed_stored_host_is_refused_by_the_client(api):
    client, db, state = api
    db.scalar.return_value = _row(url="localhost")
    r = client.post(f"/puskesmas/{PID}/test-connection")
    assert r.status_code == 200 and r.json()["ok"] is False and "bare domain" in r.json()["error"]
    assert state["requests"] == []


def test_connection_unknown_puskesmas_is_404(api):
    client, db, _ = api
    db.scalar.return_value = None
    assert client.post(f"/puskesmas/{PID}/test-connection").status_code == 404


def test_connection_is_forbidden_for_a_user_of_another_puskesmas_and_makes_no_call(api):
    client, db, state = api
    app.dependency_overrides[get_principal] = lambda: Principal("user", uuid.uuid4(), uuid.uuid4())
    assert client.post(f"/puskesmas/{PID}/test-connection").status_code == 403
    db.scalar.assert_not_called()
    assert state["requests"] == [] and state["limited"] == 0


def test_connection_is_allowed_for_a_user_of_that_puskesmas(api):
    client, db, _ = api
    app.dependency_overrides[get_principal] = lambda: Principal("user", uuid.uuid4(), PID)
    db.scalar.return_value = _row()
    assert client.post(f"/puskesmas/{PID}/test-connection").json()["ok"] is True


def test_connection_query_loads_only_the_columns_it_needs(api):
    """CLAUDE.md §5: never SELECT the whole row (asik_cred / asik_default_alamat are not needed here)."""
    client, db, _ = api
    db.scalar.return_value = _row()
    client.post(f"/puskesmas/{PID}/test-connection")
    stmt = db.scalar.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "asik_cred" not in sql and "epus_cred" in sql and "epus_url" in sql


def test_the_route_requires_authentication():
    with TestClient(app) as client:                                  # no dependency overrides
        assert client.post(f"/puskesmas/{PID}/test-connection").status_code in (401, 403)
