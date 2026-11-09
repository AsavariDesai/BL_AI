"""Screen-level rights (Rights Management): can_export / can_import on each
user controls whether they can reach the Export side, the Import side, or
both. An admin always has both regardless of these flags."""
from fastapi.testclient import TestClient

from app import auth
from app import repository as repo
from app.api import app

from tests.conftest import make_bl_pdf, SAMPLE_BL
from tests.test_pipeline import _ingest


def _login_as(username: str, password: str = "password123") -> TestClient:
    c = TestClient(app)
    c.__enter__()
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


def _make_user(username: str, *, can_export: bool, can_import: bool) -> str:
    return repo.create_user(
        username=username, password_hash=auth.hash_password("password123"),
        role="user", can_export=can_export, can_import=can_import,
    )


def test_new_users_default_to_both_rights(client):
    """Existing accounts (and anyone created without specifying rights) see
    both sides, unchanged — the rights system is opt-in narrower, not
    opt-in wider."""
    resp = client.post("/users", json={"username": "plain", "password": "password123"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["can_export"] is True and body["can_import"] is True

    me = _login_as("plain")
    try:
        assert me.get("/auth/me").json()["can_export"] is True
        assert me.get("/records/overview", params={"category": "export"}).status_code == 200
        assert me.get("/records/overview", params={"category": "import"}).status_code == 200
    finally:
        me.__exit__(None, None, None)


def test_export_only_user_is_blocked_from_import(client):
    _make_user("exporter", can_export=True, can_import=False)
    u = _login_as("exporter")
    try:
        login = u.post("/auth/login", json={"username": "exporter", "password": "password123"}).json()
        assert login["can_export"] is True and login["can_import"] is False

        assert u.get("/records/overview", params={"category": "export"}).status_code == 200
        assert u.get("/records/overview", params={"category": "import"}).status_code == 403
        assert u.get("/activity", params={"category": "import"}).status_code == 403
        # Companies, Vessels and Ports are shared infrastructure between
        # both sides (Export has its own Vessel Workspace now, mirroring
        # Import's) — gated on having *some* screen access, not a specific
        # category; screen-level isolation is enforced at the document
        # level instead (doc_type-scoped upload/list endpoints below).
        assert u.get("/companies").status_code == 200
        assert u.get("/ports").status_code == 200
        assert u.get("/vessels").status_code == 200

        # the export-only upload/ingest paths stay open
        assert _ingest(u, make_bl_pdf(SAMPLE_BL)).status_code == 201
        resp = u.post(
            "/documents", data={"doc_type": "master_bl"},
            files={"file": ("m.pdf", make_bl_pdf("MASTER BILL OF LADING\n"), "application/pdf")},
        )
        assert resp.status_code == 403
    finally:
        u.__exit__(None, None, None)


def test_import_only_user_is_blocked_from_export(client):
    _make_user("importer", can_export=False, can_import=True)
    u = _login_as("importer")
    try:
        assert u.get("/records/overview", params={"category": "import"}).status_code == 200
        assert u.get("/records/overview", params={"category": "export"}).status_code == 403
        assert u.get("/activity", params={"category": "export"}).status_code == 403
        assert u.get("/companies").status_code == 200  # shared across both sides
        assert u.get("/ports").status_code == 200
        assert u.get("/vessels").status_code == 200

        assert _ingest(u, make_bl_pdf(SAMPLE_BL)).status_code == 403
        resp = u.post(
            "/documents", data={"doc_type": "master_bl"},
            files={"file": ("m.pdf", make_bl_pdf("MASTER BILL OF LADING\n"), "application/pdf")},
        )
        assert resp.status_code == 201
    finally:
        u.__exit__(None, None, None)


def test_both_rights_user_reaches_everything(client):
    _make_user("both", can_export=True, can_import=True)
    u = _login_as("both")
    try:
        assert u.get("/records/overview", params={"category": "export"}).status_code == 200
        assert u.get("/records/overview", params={"category": "import"}).status_code == 200
        assert u.get("/companies").status_code == 200
    finally:
        u.__exit__(None, None, None)


def test_admin_ignores_rights_flags(client):
    """An admin sees both sides regardless of what can_export/can_import say
    — rights are a regular-user concept, not an admin restriction."""
    uid = repo.create_user(
        username="super", password_hash=auth.hash_password("password123"),
        role="admin", can_export=False, can_import=False,
    )
    assert uid
    u = _login_as("super")
    try:
        assert u.get("/records/overview", params={"category": "export"}).status_code == 200
        assert u.get("/records/overview", params={"category": "import"}).status_code == 200
        assert u.get("/companies").status_code == 200
    finally:
        u.__exit__(None, None, None)


def test_admin_can_update_rights(client):
    uid = _make_user("flexible", can_export=True, can_import=True)
    resp = client.put(f"/users/{uid}", json={"can_import": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_export"] is True  # untouched field stays as-is
    assert body["can_import"] is False

    u = _login_as("flexible")
    try:
        assert u.get("/records/overview", params={"category": "import"}).status_code == 403
        assert u.get("/records/overview", params={"category": "export"}).status_code == 200
    finally:
        u.__exit__(None, None, None)


def test_rights_update_requires_admin(client):
    uid = _make_user("notme", can_export=True, can_import=True)
    other = _make_user("other", can_export=True, can_import=True)
    u = _login_as("other")
    try:
        assert u.put(f"/users/{uid}", json={"can_import": False}).status_code == 403
    finally:
        u.__exit__(None, None, None)
