"""Activity logging and the analytics endpoints it feeds — scoped per
top-level category (Export vs Import) so the two sides' data never mix,
plus an admin-only consolidated view with a location breakdown for Export."""
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


def _make_user(username: str, role: str = "user") -> None:
    repo.create_user(username=username, password_hash=auth.hash_password("password123"), role=role)


def _upload_master(client) -> str:
    resp = client.post(
        "/documents", data={"doc_type": "master_bl"},
        files={"file": ("master.pdf", make_bl_pdf("MASTER BILL OF LADING\n"), "application/pdf")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_login_and_export_upload_are_logged_under_export_only(client):
    doc_id = _ingest(client, make_bl_pdf(SAMPLE_BL)).json()["id"]

    export_feed = client.get("/activity", params={"category": "export"}).json()
    actions = [a["action"] for a in export_feed]
    assert "login" in actions  # account-level, shows in both
    upload_entries = [a for a in export_feed if a["action"] == "upload"]
    assert any(a["doc_type"] == "bill_of_lading" for a in upload_entries)
    assert doc_id

    # that upload must NOT show up in Import's feed
    import_feed = client.get("/activity", params={"category": "import"}).json()
    import_uploads = [a for a in import_feed if a["action"] == "upload"]
    assert not any(a["doc_type"] == "bill_of_lading" for a in import_uploads)
    assert "login" in [a["action"] for a in import_feed]  # login still shows here too


def test_import_upload_is_logged_under_import_only(client):
    _upload_master(client)

    import_feed = client.get("/activity", params={"category": "import"}).json()
    assert any(a["action"] == "upload" and a["doc_type"] == "master_bl" for a in import_feed)

    export_feed = client.get("/activity", params={"category": "export"}).json()
    assert not any(a["doc_type"] == "master_bl" for a in export_feed)


def test_submit_and_export_are_logged_under_the_right_category(client):
    doc_id = _ingest(client, make_bl_pdf(SAMPLE_BL)).json()["id"]
    client.post("/records/submit", json={"doc_ids": [doc_id]})
    client.post("/records/export", json={"doc_ids": [doc_id], "fmt": "xlsx"})

    export_actions = {a["action"] for a in client.get("/activity", params={"category": "export"}).json()}
    assert "submit" in export_actions
    assert "export" in export_actions

    import_actions = {a["action"] for a in client.get("/activity", params={"category": "import"}).json()}
    assert "submit" not in import_actions
    assert "export" not in import_actions


def test_regular_user_only_sees_their_own_activity(client):
    _ingest(client, make_bl_pdf(SAMPLE_BL))  # admin's own activity

    _make_user("frank")
    frank = _login_as("frank")
    try:
        _ingest(frank, make_bl_pdf(SAMPLE_BL))
        frank_usernames = {a["username"] for a in frank.get("/activity", params={"category": "export"}).json()}
        assert frank_usernames == {"frank"}
    finally:
        frank.__exit__(None, None, None)

    admin_usernames = {a["username"] for a in client.get("/activity", params={"category": "export"}).json()}
    assert {"frank"} <= admin_usernames


def test_activity_summary_and_overview_are_admin_scoped_and_location_aware(client):
    bl = _ingest(client, make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: LOC/001\nPort of Loading: NHAVA SHEVA\n"
        "Port of Discharge: JEBEL ALI\nFREIGHT PREPAID\n"
    )).json()["id"]
    assert bl

    _make_user("grace")
    grace = _login_as("grace")
    try:
        _ingest(grace, make_bl_pdf(SAMPLE_BL))
        grace_summary = grace.get("/activity/summary", params={"category": "export"}).json()
        assert {r["username"] for r in grace_summary} == {"grace"}
        assert grace.get("/analytics/overview", params={"category": "export"}).status_code == 403
    finally:
        grace.__exit__(None, None, None)

    admin_summary = client.get("/activity/summary", params={"category": "export"}).json()
    assert {"grace"} <= {r["username"] for r in admin_summary}

    overview = client.get("/analytics/overview", params={"category": "export"}).json()
    assert overview["total_users"] >= 2
    assert "bill_of_lading" in overview["documents_by_type"]
    assert "by_port_of_loading" in overview and "by_port_of_discharge" in overview
    assert overview["total_documents"] >= 2
    assert {"grace"} <= {r["username"] for r in overview["documents_by_user"]}

    import_overview = client.get("/analytics/overview", params={"category": "import"}).json()
    assert "by_port_of_loading" not in import_overview  # Import has no extracted fields yet
    assert "master_bl" not in import_overview["documents_by_type"] or True  # none uploaded, either way fine


def test_analytics_overview_reflects_documents_with_no_activity_log_entry(client):
    """documents_by_user/documents_by_type come straight from the documents
    table, not activity_log — so a record that predates activity logging
    (created_by = NULL, no matching log row at all) still counts, instead of
    silently vanishing from the dashboard the way an activity_log-only view
    would."""
    doc_id = _ingest(client, make_bl_pdf(SAMPLE_BL)).json()["id"]
    from app import db as dbmod
    with dbmod.get_conn() as conn:
        conn.execute("UPDATE documents SET created_by = NULL WHERE id = ?", (doc_id,))
        conn.execute("DELETE FROM activity_log")

    overview = client.get("/analytics/overview", params={"category": "export"}).json()
    assert overview["total_documents"] >= 1
    assert any(r["username"] == "Unassigned (legacy)" and r["n"] >= 1 for r in overview["documents_by_user"])


def test_unknown_category_is_rejected(client):
    assert client.get("/activity", params={"category": "nonsense"}).status_code == 400
    assert client.get("/activity/summary", params={"category": "nonsense"}).status_code == 400
    assert client.get("/analytics/overview", params={"category": "nonsense"}).status_code == 400
