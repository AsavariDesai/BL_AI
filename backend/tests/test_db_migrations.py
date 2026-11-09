"""Schema migrations that run on every startup against a possibly pre-
existing database — see db.py's _MIGRATIONS and _ensure_bootstrap_admin."""
from app import auth, db
from app import repository as repo


def test_init_db_promotes_the_first_user_to_admin_if_no_admin_exists(isolated_data):
    """A database that only has 'user'-role accounts (e.g. one migrated from
    before roles existed, where the role column defaults everyone to
    'user') would otherwise have no way to ever create an admin — /users is
    itself admin-only. init_db() must self-heal this on every startup."""
    uid = repo.create_user(username="first", password_hash=auth.hash_password("pw12345678"), role="user")
    repo.create_user(username="second", password_hash=auth.hash_password("pw12345678"), role="user")

    db.init_db()

    users = {u["id"]: u["role"] for u in repo.list_users()}
    assert users[uid] == "admin"
    assert sum(1 for r in users.values() if r == "admin") == 1


def test_init_db_leaves_roles_alone_once_an_admin_exists(isolated_data):
    repo.create_user(username="boss", password_hash=auth.hash_password("pw12345678"), role="admin")
    uid = repo.create_user(username="staff", password_hash=auth.hash_password("pw12345678"), role="user")

    db.init_db()

    assert {u["id"]: u["role"] for u in repo.list_users()}[uid] == "user"
