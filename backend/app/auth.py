"""Password hashing and session tokens. Stdlib only — no new dependency, so
this doesn't add another compiled-extension install to an already fragile
Windows deployment (see: the pydantic-core saga).

Sessions are opaque random tokens stored server-side (SQLite), handed to the
browser as an HttpOnly cookie. There is no JWT, no client-side session state
to tamper with — revoking access is just deleting the row.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from . import repository as repo

_PBKDF2_ITERATIONS = 260_000
_SESSION_TTL = timedelta(days=14)
SESSION_COOKIE = "bl_session"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, hex_digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hex_digest)
    except (ValueError, AttributeError):
        return False


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    repo.create_session(
        token=token, user_id=user_id,
        created_at=now.isoformat(timespec="seconds"),
        expires_at=(now + _SESSION_TTL).isoformat(timespec="seconds"),
    )
    return token


def user_for_session(token: str | None):
    """Returns the users row for a valid, unexpired session token, else None."""
    if not token:
        return None
    session = repo.get_session(token)
    if session is None:
        return None
    expires = datetime.fromisoformat(session["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        repo.delete_session(token)
        return None
    return repo.get_user(session["user_id"])


def logout(token: str | None) -> None:
    if token:
        repo.delete_session(token)
