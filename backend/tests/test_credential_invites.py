"""One-time ASIK credential links: admin issues, the puskesmas submits once, no login.

Fully offline: the DB is a MagicMock and the redis limiter is patched out. Credentials go through the real
Fernet encrypt/decrypt (conftest sets the key). The conditional UPDATE that makes a link single-use is
asserted from its compiled SQL — the atomicity itself is Postgres's.
"""
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

import app.api.routes.credential_invites as routes
from app.api.deps import get_current_admin_id, get_db
from app.core.security import decrypt_cred
from app.main import app

TOKEN = "t" * 43
PID = uuid.uuid4()
NOW = datetime.now(UTC)


@pytest.fixture
def api(monkeypatch):
    """(client, fake_db, limiter_calls) — admin dependency stubbed, redis limiter patched out."""
    fake_db = MagicMock()
    calls: list[int] = []
    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_admin_id] = lambda: uuid.uuid4()
    monkeypatch.setattr(routes, "enforce_invite_rate_limit", lambda _req: calls.append(1))
    monkeypatch.setattr(routes.settings, "DASHBOARD_PUBLIC_URL", "https://dash.example/")
    with TestClient(app) as client:
        yield client, fake_db, calls
    app.dependency_overrides.clear()


def _info_row(*, used=None, revoked=None, expires=NOW + timedelta(days=1)):
    return SimpleNamespace(
        expires_at=expires, used_at=used, revoked_at=revoked, name="Puskesmas Contoh", asik_url="asik.example"
    )


# ----------------------------------------------------------------------------- admin: create


def test_create_returns_a_dashboard_link_and_stores_only_the_hash(api):
    client, db, _ = api
    db.scalar.return_value = PID  # puskesmas exists
    r = client.post(f"/puskesmas/{PID}/credential-invites")
    assert r.status_code == 201
    url = r.json()["url"]
    assert url.startswith("https://dash.example/invite/")
    token = url.rsplit("/", 1)[1]
    assert len(token) >= 43
    stored = db.add.call_args.args[0]
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in repr(stored.__dict__)
    assert timedelta(days=6) < stored.expires_at - NOW <= timedelta(days=7, seconds=5)
    db.commit.assert_called_once()


def test_create_retires_older_pending_links_first(api):
    client, db, _ = api
    db.scalar.return_value = PID
    client.post(f"/puskesmas/{PID}/credential-invites")
    sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE credential_invites SET revoked_at=now()")
    assert "used_at IS NULL" in sql and "revoked_at IS NULL" in sql


def test_create_404s_for_an_unknown_puskesmas(api):
    client, db, _ = api
    db.scalar.return_value = None
    assert client.post(f"/puskesmas/{PID}/credential-invites").status_code == 404
    db.add.assert_not_called()


def test_create_needs_an_admin():
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.post(f"/puskesmas/{PID}/credential-invites").status_code in (401, 403)


# ----------------------------------------------------------------------------- public: info


def test_info_pending_shows_only_name_and_asik_url(api):
    client, db, calls = api
    db.execute.return_value.one_or_none.return_value = _info_row()
    r = client.get(f"/invites/{TOKEN}")
    assert r.status_code == 200
    assert r.json() == {"status": "pending", "puskesmas_name": "Puskesmas Contoh", "asik_url": "asik.example"}
    assert r.headers["cache-control"] == "no-store"
    assert calls == [1]


@pytest.mark.parametrize(
    "row,expected",
    [
        (_info_row(used=NOW), "used"),
        (_info_row(revoked=NOW), "expired"),
        (_info_row(expires=NOW - timedelta(seconds=1)), "expired"),
    ],
)
def test_info_for_a_dead_link_reveals_no_puskesmas_data(api, row, expected):
    client, db, _ = api
    db.execute.return_value.one_or_none.return_value = row
    assert client.get(f"/invites/{TOKEN}").json() == {"status": expected, "puskesmas_name": None, "asik_url": None}


def test_info_404s_for_an_unknown_token(api):
    client, db, _ = api
    db.execute.return_value.one_or_none.return_value = None
    assert client.get(f"/invites/{TOKEN}").status_code == 404


# ----------------------------------------------------------------------------- public: submit


def test_submit_claims_the_link_saves_asik_creds_and_commits_once(api):
    client, db, calls = api
    obj = SimpleNamespace(id=PID, asik_cred=None)
    db.scalar.side_effect = [PID, obj]  # claim UPDATE ... RETURNING puskesmas_id, then the puskesmas row
    r = client.post(f"/invites/{TOKEN}/asik", json={"email": "  a@b.id ", "password": "pw"})
    assert r.status_code == 204
    assert decrypt_cred(obj.asik_cred) == {"email": "a@b.id", "password": "pw"}
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    assert r.headers["cache-control"] == "no-store"
    assert calls == [1]


def test_submit_claim_is_one_conditional_update_keyed_on_the_hash(api):
    client, db, _ = api
    db.scalar.side_effect = [PID, SimpleNamespace(id=PID, asik_cred=None)]
    client.post(f"/invites/{TOKEN}/asik", json={"email": "a@b.id", "password": "pw"})
    claim = db.scalar.call_args_list[0].args[0]
    sql = str(claim.compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE credential_invites SET used_at=now()")
    for guard in ("token_hash =", "used_at IS NULL", "revoked_at IS NULL", "expires_at > now()", "RETURNING"):
        assert guard in sql
    assert hashlib.sha256(TOKEN.encode()).hexdigest() in claim.compile(dialect=postgresql.dialect()).params.values()


def test_submit_on_a_used_or_expired_link_is_410_and_saves_nothing(api):
    client, db, _ = api
    db.scalar.side_effect = [None, uuid.uuid4()]  # claim matched no row, but the link exists
    r = client.post(f"/invites/{TOKEN}/asik", json={"email": "a@b.id", "password": "pw"})
    assert r.status_code == 410
    db.commit.assert_not_called()


def test_submit_with_an_unknown_token_is_404(api):
    client, db, _ = api
    db.scalar.side_effect = [None, None]
    assert client.post(f"/invites/{TOKEN}/asik", json={"email": "a@b.id", "password": "pw"}).status_code == 404
    db.commit.assert_not_called()


def test_submit_for_a_soft_deleted_puskesmas_rolls_the_claim_back(api):
    client, db, _ = api
    db.scalar.side_effect = [PID, None]  # claimed, but the (soft-delete-filtered) puskesmas row is gone
    r = client.post(f"/invites/{TOKEN}/asik", json={"email": "a@b.id", "password": "pw"})
    assert r.status_code == 410
    db.rollback.assert_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [{"email": "", "password": "pw"}, {"email": "   ", "password": "pw"}, {"email": "a@b.id", "password": ""}, {"email": "a@b.id"}],
)
def test_submit_rejects_empty_fields_before_touching_the_link(api, body):
    client, db, _ = api
    assert client.post(f"/invites/{TOKEN}/asik", json=body).status_code == 422
    db.scalar.assert_not_called()


def test_submit_does_not_accept_a_medisy_token(api):
    client, db, _ = api
    r = client.post(f"/invites/{TOKEN}/asik", json={"token": "k" * 40})
    assert r.status_code == 422
    db.scalar.assert_not_called()
