"""The ASIK login comes from Medisy's clinic configuration (E7 ``GET /asik-credential``) instead of being typed into ckg-ai.

Offline: Medisy is ``httpx.MockTransport``, the DB is a MagicMock, credentials go through the real Fernet encrypt/decrypt.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

import app.crud.puskesmas as crud
from app.core.security import decrypt_cred, encrypt_cred
from app.integrations.medisy_client import MedisyAsikCredential, MedisyAuthError, MedisyClient, MedisyUnavailableError

HOST = "clinic.medisy.id"
TOKEN = "k" * 32 + "-medisy-token"
PID = uuid.uuid4()
LOGIN = {"email": "klinik@asik.id", "password": "S3cret-ASIK-pw"}


def _client(handler) -> MedisyClient:
    return MedisyClient(HOST, TOKEN, transport=httpx.MockTransport(handler), sleep=lambda _s: None)


# ----------------------------------------------------------------------------- client


def test_asik_credential_is_a_bearer_get_on_the_ckg_path():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=LOGIN)

    cred = _client(handler).asik_credential()
    assert cred == MedisyAsikCredential(email=LOGIN["email"], password=LOGIN["password"])
    assert seen[0].method == "GET" and seen[0].url.path == "/medisy_api/ckg/asik-credential"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_nobody_saved_a_login_is_none_not_an_error():
    assert _client(lambda r: httpx.Response(404, json={"detail": "No ASIK login saved in the clinic configuration"})).asik_credential() is None


@pytest.mark.parametrize("body", [{}, {"email": "a@b.id"}, {"email": "", "password": "x"}, {"email": "a@b.id", "password": 5}, []])
def test_a_body_without_a_login_is_refused(body):
    with pytest.raises(MedisyUnavailableError):
        _client(lambda r: httpx.Response(200, json=body)).asik_credential()


def test_a_wrong_token_is_an_auth_error():
    with pytest.raises(MedisyAuthError):
        _client(lambda r: httpx.Response(401, json={"detail": "Invalid or missing token"})).asik_credential()


def test_the_password_never_appears_in_repr():
    assert LOGIN["password"] not in repr(MedisyAsikCredential(email="a@b.id", password=LOGIN["password"]))


# ----------------------------------------------------------------------------- refresh


@pytest.fixture
def world(monkeypatch):
    """(db, row, state): a puskesmas row with a Medisy URL + token; Medisy answers with ``state['handler']``."""
    row = SimpleNamespace(id=PID, epus_url=HOST, epus_cred=encrypt_cred({"token": TOKEN}), asik_cred=None)
    db = MagicMock()
    db.scalar.return_value = row
    state = {"calls": 0, "handler": lambda r: httpx.Response(200, json=LOGIN)}

    def make_client(host, token, **kw):
        def handler(req):
            state["calls"] += 1
            return state["handler"](req)
        return MedisyClient(host, token, transport=httpx.MockTransport(handler), sleep=lambda _s: None, **kw)

    monkeypatch.setattr(crud, "MedisyClient", make_client)
    return db, row, state


def test_the_login_from_medisy_is_stored_encrypted_in_asik_cred(world):
    db, row, _ = world
    assert crud.refresh_asik_cred_from_medisy(db, PID) == "updated"
    assert LOGIN["password"].encode() not in row.asik_cred
    assert decrypt_cred(row.asik_cred) == {"email": LOGIN["email"], "password": LOGIN["password"]}
    assert crud.get_cred_decrypted(row, "asik") == {"email": LOGIN["email"], "password": LOGIN["password"]}
    db.commit.assert_called_once()


def test_an_unchanged_login_is_not_rewritten(world):
    db, row, _ = world
    row.asik_cred = encrypt_cred({"email": LOGIN["email"], "password": LOGIN["password"]})
    before = row.asik_cred
    assert crud.refresh_asik_cred_from_medisy(db, PID) == "unchanged"
    assert row.asik_cred is before
    db.commit.assert_not_called()


def test_a_login_changed_in_medisy_replaces_the_old_copy(world):
    db, row, _ = world
    row.asik_cred = encrypt_cred({"email": "old@asik.id", "password": "old"})
    assert crud.refresh_asik_cred_from_medisy(db, PID) == "updated"
    assert decrypt_cred(row.asik_cred)["email"] == LOGIN["email"]


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(404, json={"detail": "No ASIK login saved in the clinic configuration"}),
    lambda r: httpx.Response(401, json={"detail": "Invalid or missing token"}),
    lambda r: httpx.Response(500, json={"detail": "Internal server error"}),
    lambda r: httpx.Response(200, json={"nope": 1}),
])
def test_when_medisy_has_nothing_usable_the_existing_login_is_kept(world, handler):
    db, row, state = world
    kept = encrypt_cred({"email": "typed@by.hand", "password": "pw"})
    row.asik_cred = kept
    state["handler"] = handler
    assert crud.refresh_asik_cred_from_medisy(db, PID) in {"not_in_medisy", "medisy_unavailable"}
    assert row.asik_cred is kept
    db.commit.assert_not_called()


def test_it_never_raises_when_medisy_is_down(world):
    db, row, state = world

    def boom(req):
        raise httpx.ConnectError("down")

    state["handler"] = boom
    assert crud.refresh_asik_cred_from_medisy(db, PID) == "medisy_unavailable"
    assert row.asik_cred is None


@pytest.mark.parametrize("change", [
    {"epus_url": None},
    {"epus_cred": None},
    {"epus_cred": encrypt_cred({"email": "a@b.id", "password": "legacy"})},     # an old EPUS email/password, not a token
])
def test_without_a_medisy_url_and_token_medisy_is_not_called(world, change):
    db, row, state = world
    for k, v in change.items():
        setattr(row, k, v)
    assert crud.refresh_asik_cred_from_medisy(db, PID) == "medisy_not_configured"
    assert state["calls"] == 0


def test_an_unknown_puskesmas_is_not_configured(world):
    db, _, state = world
    db.scalar.return_value = None
    assert crud.refresh_asik_cred_from_medisy(db, PID) == "medisy_not_configured"
    assert state["calls"] == 0


def test_a_malformed_stored_host_does_not_raise(world, monkeypatch):
    db, row, _ = world
    monkeypatch.undo()                                  # real MedisyClient: the host check raises ValueError, which is swallowed
    row.epus_url = "https://not-a-bare-host/x"
    assert crud.refresh_asik_cred_from_medisy(db, PID) == "medisy_unavailable"
