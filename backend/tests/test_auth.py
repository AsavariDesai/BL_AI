"""Login/session behavior: password hashing, the /auth/* endpoints, and that
every other route actually requires a valid session now.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import auth
from app import repository as repo
from app.api import app

from tests.conftest import TEST_PASSWORD, TEST_USERNAME


def test_password_hash_round_trips_and_rejects_wrong_password():
    hashed = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", hashed)
    assert not auth.verify_password("wrong password", hashed)
    assert not auth.verify_password("correct horse battery staple", "garbage$not$a$real$hash")


def test_health_and_login_work_without_a_session():
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        # wrong credentials on a fresh (unauthenticated) client is still a
        # reachable 401, not blocked by the auth gate itself
        r = c.post("/auth/login", json={"username": "nobody", "password": "x"})
        assert r.status_code == 401


def test_protected_route_requires_a_session():
    with TestClient(app) as c:
        assert c.get("/documents").status_code == 401
        assert c.get("/hierarchy").status_code == 401


def test_login_logout_flow(client):  # `client` fixture is already logged in
    assert client.get("/documents").status_code == 200
    assert client.get("/auth/me").json()["username"] == TEST_USERNAME

    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert client.get("/documents").status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_login_rejects_wrong_password(client):
    client.post("/auth/logout")
    r = client.post("/auth/login", json={"username": TEST_USERNAME, "password": "wrong"})
    assert r.status_code == 401
    assert client.get("/documents").status_code == 401  # still logged out


def test_expired_session_is_rejected_and_cleaned_up():
    with TestClient(app) as c:
        user_id = repo.create_user(
            username="stale", password_hash=auth.hash_password("whatever123")
        )
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        repo.create_session(
            token="stale-token", user_id=user_id,
            created_at=expired, expires_at=expired,
        )
        assert auth.user_for_session("stale-token") is None
        assert repo.get_session("stale-token") is None  # cleaned up on rejection


def test_manage_create_and_delete_user(monkeypatch):
    import manage

    pws = iter(["a-good-password", "a-good-password"])
    monkeypatch.setattr(manage.getpass, "getpass", lambda *_: next(pws))
    manage.create_user("alice")

    row = repo.get_user_by_username("alice")
    assert row is not None
    assert auth.verify_password("a-good-password", row["password_hash"])

    manage.delete_user("alice")
    assert repo.get_user_by_username("alice") is None
