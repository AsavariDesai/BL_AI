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


def test_third_wrong_password_locks_the_account(client):
    client.post("/auth/logout")
    for _ in range(auth.MAX_FAILED_LOGIN_ATTEMPTS):
        r = client.post("/auth/login", json={"username": TEST_USERNAME, "password": "wrong"})
        assert r.status_code == 401

    # the 4th attempt is refused even though the lockout came from bad
    # guesses, not from this (correct) password
    locked = client.post("/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    assert locked.status_code == 423
    assert "minute" in locked.json()["detail"]


def test_lockout_clears_once_it_expires(client):
    client.post("/auth/logout")
    for _ in range(auth.MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/auth/login", json={"username": TEST_USERNAME, "password": "wrong"})
    row = repo.get_user_by_username(TEST_USERNAME)
    assert row["locked_until"] is not None

    # back-date the lock as if LOCKOUT_DURATION had already passed
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
    repo.lock_user(row["id"], expired)

    r = client.post("/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    assert r.status_code == 200
    row = repo.get_user_by_username(TEST_USERNAME)
    assert row["failed_login_attempts"] == 0
    assert row["locked_until"] is None


def test_successful_login_resets_the_failed_counter(client):
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": TEST_USERNAME, "password": "wrong"})
    client.post("/auth/login", json={"username": TEST_USERNAME, "password": "wrong"})
    row = repo.get_user_by_username(TEST_USERNAME)
    assert row["failed_login_attempts"] == 2

    ok = client.post("/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    assert ok.status_code == 200
    row = repo.get_user_by_username(TEST_USERNAME)
    assert row["failed_login_attempts"] == 0


def test_admin_password_reset_also_lifts_a_lockout(client):
    client.post("/auth/logout")
    for _ in range(auth.MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/auth/login", json={"username": TEST_USERNAME, "password": "wrong"})
    row = repo.get_user_by_username(TEST_USERNAME)
    assert row["locked_until"] is not None

    # log back in as an admin to perform the reset (the test fixture's own
    # session cookie is for TEST_USERNAME, now locked out)
    admin_id = repo.create_user(
        username="unlocker", password_hash=auth.hash_password("admin-password"), role="admin",
    )
    with TestClient(app) as admin_client:
        admin_client.post("/auth/login", json={"username": "unlocker", "password": "admin-password"})
        r = admin_client.put(f"/users/{row['id']}", json={"password": "a-new-password123"})
        assert r.status_code == 200

    row = repo.get_user_by_username(TEST_USERNAME)
    assert row["locked_until"] is None
    assert row["failed_login_attempts"] == 0


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
