"""Import workflow: Company -> Vessel Workspace -> Master BL / House BL
uploads scoped to one vessel, plus the vessel-wise 3-file Excel export."""
import io
import zipfile

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import auth
from app import repository as repo
from app.api import app
from tests.conftest import make_bl_pdf


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


def _company_body(code="VCO", **extra):
    body = {
        "company_code": code, "company_name": "Vessel Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }
    body.update(extra)
    return body


def _vessel_body(company_id, imo_code="9058960", **extra):
    body = {"name": "SPARROW", "imo_code": imo_code, "call_sign": "FHSLJ", "company_id": company_id}
    body.update(extra)
    return body


def _port_body(company_id, code="INNSA1", **extra):
    body = {
        "company_id": company_id, "port_type": "SEA PORT", "port_code": code, "edi_port_code": code,
        "port_name": "Nhava Sheva", "country": "India", "active": True, "sez": False, "berths": [],
    }
    body.update(extra)
    return body


def _upload_master(client, vessel_id=None, text="MASTER BILL OF LADING\n"):
    data = {"doc_type": "master_bl"}
    if vessel_id:
        data["vessel_id"] = vessel_id
    return client.post(
        "/documents", data=data,
        files={"file": ("master.pdf", make_bl_pdf(text), "application/pdf")},
    )


def test_master_bl_upload_scopes_to_its_vessel(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]

    resp = _upload_master(client, vessel_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["vessel_id"] == vessel_id
    assert body["vessel_name"] == "SPARROW"

    overview = client.get("/records/overview", params={"category": "import", "vessel_id": vessel_id}).json()
    assert {r["id"] for r in overview} == {body["id"]}

    other_vessel_id = client.post("/vessels", json=_vessel_body(company_id, imo_code="1112223", name="OTHER")).json()["id"]
    other_scoped = client.get(
        "/records/overview", params={"category": "import", "vessel_id": other_vessel_id}
    ).json()
    assert other_scoped == []


def test_vessel_list_shows_master_bl_count(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]
    assert _upload_master(client, vessel_id).status_code == 201
    assert _upload_master(client, vessel_id, text="MASTER BILL OF LADING 2\n").status_code == 201

    listed = client.get("/vessels", params={"company_id": company_id}).json()
    assert next(v for v in listed if v["id"] == vessel_id)["master_bl_count"] == 2

    single = client.get(f"/vessels/{vessel_id}").json()
    assert single["master_bl_count"] == 2


def test_house_bl_inherits_masters_vessel(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]
    master_id = _upload_master(client, vessel_id).json()["id"]

    resp = client.post(
        f"/documents/{master_id}/link-house-bl",
        files={"files": ("house.pdf", make_bl_pdf("HOUSE BILL OF LADING\n"), "application/pdf")},
    )
    assert resp.status_code == 201
    house = resp.json()["linked_house_bls"][0]
    house_row = repo.get_document(house["id"])
    assert house_row["vessel_id"] == vessel_id


def test_user_without_assigned_company_is_blocked_from_its_vessel(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]
    master_id = _upload_master(client, vessel_id).json()["id"]

    _make_user("outsider")
    u = _login_as("outsider")
    try:
        # no company assigned at all -> no import rights into this vessel's data
        assert u.get(f"/vessels/{vessel_id}").status_code == 403
        assert u.get("/records/overview", params={"category": "import", "vessel_id": vessel_id}).status_code == 403
        resp = u.post(
            "/documents", data={"doc_type": "master_bl", "vessel_id": vessel_id},
            files={"file": ("x.pdf", make_bl_pdf("MASTER BILL OF LADING\n"), "application/pdf")},
        )
        assert resp.status_code == 403  # vessel's company isn't assigned to this user
        resp2 = u.post(
            f"/documents/{master_id}/link-house-bl",
            files={"files": ("h.pdf", make_bl_pdf("HOUSE BILL OF LADING\n"), "application/pdf")},
        )
        assert resp2.status_code == 403
    finally:
        u.__exit__(None, None, None)


def test_assigned_user_can_work_in_their_companys_vessel(client):
    uid = _make_user("vesseluser")
    company_id = client.post(
        "/companies", json={**_company_body(), "assigned_user_id": uid}
    ).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]

    u = _login_as("vesseluser")
    try:
        assert u.get(f"/vessels/{vessel_id}").status_code == 200
        resp = _upload_master(u, vessel_id)
        assert resp.status_code == 201
    finally:
        u.__exit__(None, None, None)


def test_master_bl_split_export_produces_three_xlsx_files(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]
    master_id = _upload_master(client, vessel_id).json()["id"]
    client.post(
        f"/documents/{master_id}/link-house-bl",
        files={"files": ("house.pdf", make_bl_pdf("HOUSE BILL OF LADING\n"), "application/pdf")},
    )

    resp = client.post("/records/export-master-bl-split", json={"doc_ids": [master_id], "fmt": "xlsx"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert any(n.startswith("master_bl_data_") for n in names)
    assert any(n.startswith("master_house_bl_") for n in names)
    assert any(n.startswith("summary_") for n in names)

    master_sheet = load_workbook(io.BytesIO(zf.read(next(n for n in names if n.startswith("master_bl_data_")))))
    ws = master_sheet.active
    assert ws.cell(row=1, column=1).value == "Job ID"
    assert ws.cell(row=2, column=3).value == "SPARROW"  # Vessel column


def test_export_master_bl_split_requires_import_rights(client):
    _make_user("noimport", can_export=True, can_import=False)
    u = _login_as("noimport")
    try:
        assert u.post("/records/export-master-bl-split", json={"doc_ids": ["x"], "fmt": "xlsx"}).status_code == 403
    finally:
        u.__exit__(None, None, None)


def test_vessel_with_master_bls_cannot_be_deleted(client):
    # The Vessel Workspace list only ever offers Delete (no Edit/Update), so
    # a vessel that already has Master BL data must refuse deletion instead
    # of silently orphaning that data's vessel link.
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]
    _upload_master(client, vessel_id)

    resp = client.delete(f"/vessels/{vessel_id}")
    assert resp.status_code == 400
    assert client.get(f"/vessels/{vessel_id}").status_code == 200  # still there


def test_empty_vessel_can_be_deleted(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]
    assert client.delete(f"/vessels/{vessel_id}").status_code == 200
    assert client.get(f"/vessels/{vessel_id}").status_code == 404


def test_vessel_rejects_identical_pol_and_pod(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    port_id = client.post("/ports", json=_port_body(company_id)).json()["id"]

    resp = client.post(
        "/vessels",
        json=_vessel_body(company_id, departure_port_id=port_id, destination_port_id=port_id),
    )
    assert resp.status_code == 400
    assert "cannot be the same" in resp.json()["detail"]


def test_vessel_update_also_rejects_identical_pol_and_pod(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    dep = client.post("/ports", json=_port_body(company_id, "INNSA1")).json()["id"]
    dest = client.post("/ports", json=_port_body(company_id, "AEJEA", port_name="Jebel Ali")).json()["id"]
    vessel_id = client.post(
        "/vessels", json=_vessel_body(company_id, departure_port_id=dep, destination_port_id=dest)
    ).json()["id"]

    body = _vessel_body(company_id, departure_port_id=dep, destination_port_id=dep)
    assert client.put(f"/vessels/{vessel_id}", json=body).status_code == 400


def test_port_can_be_toggled_active_and_inactive(client):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    port = client.post("/ports", json=_port_body(company_id)).json()
    assert port["active"] is True

    port["active"] = False
    resp = client.put(f"/ports/{port['id']}", json=port)
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    listed = client.get("/ports", params={"company_id": company_id}).json()
    assert next(p for p in listed if p["id"] == port["id"])["active"] is False


def test_outsider_cannot_update_or_delete_someone_elses_vessel(client):
    uid = _make_user("vesselowner")
    company_id = client.post(
        "/companies", json={**_company_body(), "assigned_user_id": uid}
    ).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id)).json()["id"]

    _make_user("outsider2")
    u = _login_as("outsider2")
    try:
        body = _vessel_body(company_id)
        body["ship_type"] = "Bulk Carrier"
        assert u.put(f"/vessels/{vessel_id}", json=body).status_code == 403
        assert u.delete(f"/vessels/{vessel_id}").status_code == 403
    finally:
        u.__exit__(None, None, None)
