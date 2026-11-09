"""Export workflow: Company Master is now shared infrastructure — a Bill of
Lading / Shipping Bill belongs to one Company Workspace the same way a
Master BL belongs to one Vessel Workspace (see test_vessel_workspace.py)."""
from fastapi.testclient import TestClient

from app import auth
from app import repository as repo
from app.api import app

from tests.conftest import make_bl_pdf, SAMPLE_BL, SAMPLE_SB


def _login_as(username: str, password: str = "password123") -> TestClient:
    c = TestClient(app)
    c.__enter__()
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


def _make_user(username: str, *, can_export=True, can_import=True) -> str:
    return repo.create_user(
        username=username, password_hash=auth.hash_password("password123"),
        role="user", can_export=can_export, can_import=can_import,
    )


def _company_body(code="ECO", **extra):
    body = {
        "company_code": code, "company_name": "Export Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }
    body.update(extra)
    return body


def _ingest(client, pdf, *, doc_type=None, company_id=None, background=False):
    data = {}
    if doc_type:
        data["doc_type"] = doc_type
    if company_id:
        data["company_id"] = company_id
    if background:
        data["background"] = "true"
    return client.post("/ingest", data=data, files={"file": ("d.pdf", pdf, "application/pdf")})


def test_ingest_scopes_bl_to_its_company(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]

    resp = _ingest(client, make_bl_pdf(SAMPLE_BL), company_id=company_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["company_id"] == company_id
    assert body["company_name"] == "Export Co"

    overview = client.get(
        "/records/overview", params={"category": "export", "company_id": company_id}
    ).json()
    assert body["id"] in {r["id"] for r in overview}

    other_company_id = client.post("/companies", json=_company_body(code="ECO2")).json()["id"]
    other_scoped = client.get(
        "/records/overview", params={"category": "export", "company_id": other_company_id}
    ).json()
    assert body["id"] not in {r["id"] for r in other_scoped}


def test_legacy_export_records_with_no_company_stay_visible_everywhere(client):
    """A record uploaded before Export required a company (company_id NULL)
    doesn't vanish once every Export screen starts scoping by company — it
    shows up inside every company's workspace instead, same precedent as the
    existing created_by-NULL leniency elsewhere in this app."""
    resp = _ingest(client, make_bl_pdf(SAMPLE_BL))  # no company_id
    assert resp.status_code == 201
    doc_id = resp.json()["id"]
    assert resp.json()["company_id"] is None

    company_id = client.post("/companies", json=_company_body()).json()["id"]
    overview = client.get(
        "/records/overview", params={"category": "export", "company_id": company_id}
    ).json()
    assert doc_id in {r["id"] for r in overview}


def test_linked_shipping_bill_inherits_bls_company(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    bl_id = _ingest(client, make_bl_pdf(SAMPLE_BL), company_id=company_id).json()["id"]

    resp = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        files={"files": ("sb.pdf", make_bl_pdf(SAMPLE_SB), "application/pdf")},
        data={"background": "false"},
    )
    assert resp.status_code == 201
    sb = resp.json()["linked_shipping_bills"][0]
    sb_row = repo.get_document(sb["id"])
    assert sb_row["company_id"] == company_id


def test_link_existing_sb_rejects_a_different_companys_shipping_bill(client):
    company_a = client.post("/companies", json=_company_body(code="ECOA")).json()["id"]
    company_b = client.post("/companies", json=_company_body(code="ECOB")).json()["id"]
    bl_id = _ingest(client, make_bl_pdf(SAMPLE_BL), company_id=company_a).json()["id"]
    sb_id = _ingest(client, make_bl_pdf(SAMPLE_SB), doc_type="shipping_bill", company_id=company_b).json()["id"]

    resp = client.post(f"/documents/{bl_id}/link-existing-sb", json={"doc_ids": [sb_id]})
    assert resp.status_code == 400


def test_user_without_assigned_company_is_blocked_from_export_company(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]

    _make_user("outsider3")
    u = _login_as("outsider3")
    try:
        assert u.get(f"/companies/{company_id}").status_code == 403
        assert u.get(
            "/records/overview", params={"category": "export", "company_id": company_id}
        ).status_code == 403
        resp = _ingest(u, make_bl_pdf(SAMPLE_BL), company_id=company_id)
        assert resp.status_code == 403
    finally:
        u.__exit__(None, None, None)


def test_assigned_user_can_work_in_their_companys_export_workspace(client):
    uid = _make_user("exportuser")
    company_id = client.post(
        "/companies", json={**_company_body(), "assigned_user_id": uid}
    ).json()["id"]

    u = _login_as("exportuser")
    try:
        assert u.get(f"/companies/{company_id}").status_code == 200
        resp = _ingest(u, make_bl_pdf(SAMPLE_BL), company_id=company_id)
        assert resp.status_code == 201
        assert resp.json()["company_id"] == company_id
    finally:
        u.__exit__(None, None, None)


def test_analytics_overview_includes_documents_by_company(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    _ingest(client, make_bl_pdf(SAMPLE_BL), company_id=company_id)
    _ingest(client, make_bl_pdf(SAMPLE_BL))  # legacy/unassigned

    overview = client.get("/analytics/overview", params={"category": "export"}).json()
    by_company = {row["company_id"]: row["n"] for row in overview["documents_by_company"]}
    assert by_company.get(company_id) == 1
    assert by_company.get(None) == 1
