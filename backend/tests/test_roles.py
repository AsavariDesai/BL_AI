"""User management, roles, and per-user scoping: an admin sees every
record and manages accounts; a regular user only sees what they created."""
from fastapi.testclient import TestClient

from app import auth
from app import repository as repo
from app.api import app

from tests.conftest import TEST_PASSWORD, TEST_USERNAME  # noqa: F401 (admin via `client`)
from tests.test_pipeline import _ingest
from tests.conftest import make_bl_pdf, SAMPLE_BL


def _login_as(username: str, password: str) -> TestClient:
    c = TestClient(app)
    c.__enter__()
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


def _make_user(username: str, role: str = "user") -> str:
    return repo.create_user(username=username, password_hash=auth.hash_password("password123"), role=role)


def test_auth_me_and_login_report_role(client):
    me = client.get("/auth/me").json()
    assert me["role"] == "admin"


def test_regular_user_defaults_and_admin_endpoints_are_gated(client):
    # the `client` fixture's user is an admin, so /users works for it
    assert client.get("/users").status_code == 200

    _make_user("bob", role="user")
    bob = _login_as("bob", "password123")
    try:
        assert bob.get("/auth/me").json()["role"] == "user"
        assert bob.get("/users").status_code == 403
        assert bob.post("/users", json={"username": "x", "password": "password123"}).status_code == 403
    finally:
        bob.__exit__(None, None, None)


def test_admin_can_create_list_and_delete_users(client):
    resp = client.post("/users", json={"username": "carol", "password": "password123", "role": "user"})
    assert resp.status_code == 201
    carol = resp.json()
    assert carol["role"] == "user"

    listed = client.get("/users").json()
    assert any(u["username"] == "carol" for u in listed)

    upd = client.put(f"/users/{carol['id']}", json={"role": "admin"})
    assert upd.status_code == 200
    assert upd.json()["role"] == "admin"

    dele = client.delete(f"/users/{carol['id']}")
    assert dele.status_code == 200
    assert not any(u["username"] == "carol" for u in client.get("/users").json())


def test_admin_cannot_delete_own_account(client):
    me = client.get("/auth/me").json()
    assert client.delete(f"/users/{me['id']}").status_code == 400


def test_create_user_rejects_short_password_and_duplicate_username(client):
    assert client.post("/users", json={"username": "short", "password": "x"}).status_code == 400
    client.post("/users", json={"username": "dupe", "password": "password123"})
    dup = client.post("/users", json={"username": "dupe", "password": "password123"})
    assert dup.status_code == 400


def test_regular_users_only_see_their_own_documents(client):
    # admin uploads one document
    admin_doc = _ingest(client, make_bl_pdf(SAMPLE_BL)).json()["id"]

    _make_user("alice", role="user")
    alice = _login_as("alice", "password123")
    try:
        alice_doc = _ingest(alice, make_bl_pdf(SAMPLE_BL)).json()["id"]

        alice_ids = {d["id"] for d in alice.get("/documents").json()}
        assert alice_ids == {alice_doc}  # not the admin's document

        # the admin (sees everything) finds both
        admin_ids = {d["id"] for d in client.get("/documents").json()}
        assert {admin_doc, alice_doc} <= admin_ids
    finally:
        alice.__exit__(None, None, None)


def test_legacy_records_with_no_owner_stay_visible_to_everyone(client):
    """A document created before per-user ownership existed has
    created_by = NULL — it must stay visible to every user (not just an
    admin), or it silently vanishes for regular users. (Companies/vessels/
    ports are a separate, deliberately stricter story now — see
    test_masters.py's admin-assignment tests: an unassigned company is
    admin-only, full stop, not "visible to everyone".)"""
    legacy_doc_id = _ingest(client, make_bl_pdf(SAMPLE_BL)).json()["id"]
    # /ingest always sets created_by from the logged-in session, so blank it
    # out directly to simulate a document from before ownership existed
    from app import db as dbmod
    with dbmod.get_conn() as conn:
        conn.execute("UPDATE documents SET created_by = NULL WHERE id = ?", (legacy_doc_id,))

    _make_user("holly", role="user")
    holly = _login_as("holly", "password123")
    try:
        assert legacy_doc_id in {d["id"] for d in holly.get("/documents").json()}
        assert legacy_doc_id in {r["id"] for r in holly.get("/uploads").json()}
    finally:
        holly.__exit__(None, None, None)


def test_regular_users_only_see_their_own_masters_and_cannot_edit_others(client):
    # Company Master is admin-only now — the admin creates the company and
    # assigns it to dave before dave can do anything with it.
    _make_user("dave", role="user")
    dave_id = client.get("/users").json()
    dave_id = next(u["id"] for u in dave_id if u["username"] == "dave")
    dave_company_id = client.post("/companies", json={
        "assigned_user_id": dave_id,
        "company_code": "DAVECO", "company_name": "Dave Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }).json()["id"]

    dave = _login_as("dave", "password123")
    try:
        mine = dave.post("/ports", json={
            "company_id": dave_company_id,
            "port_type": "SEA PORT", "port_code": "DAVE1", "port_name": "Dave Port", "country": "India",
        })
        assert mine.status_code == 201
        port_id = mine.json()["id"]

        # a second regular user, with no company assigned, doesn't see
        # dave's port, and can't edit/delete it
        _make_user("erin", role="user")
        erin = _login_as("erin", "password123")
        try:
            erin_ports = erin.get("/ports").json()
            assert not any(p["id"] == port_id for p in erin_ports)

            upd = erin.put(f"/ports/{port_id}", json={
                "company_id": dave_company_id,
                "port_type": "SEA PORT", "port_code": "DAVE1", "port_name": "Hijacked", "country": "India",
            })
            assert upd.status_code == 403
            assert erin.delete(f"/ports/{port_id}").status_code == 403
        finally:
            erin.__exit__(None, None, None)

        # the admin sees it regardless
        admin_ports = client.get("/ports").json()
        assert any(p["id"] == port_id for p in admin_ports)
    finally:
        dave.__exit__(None, None, None)
