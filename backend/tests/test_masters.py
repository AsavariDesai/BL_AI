"""Vessel / Company / Port master data screens — CRUD + the registration
workflow: a Company must be registered first, then its Vessels and Ports are
registered under it (both require an existing company_id)."""
from fastapi.testclient import TestClient

from app import auth
from app import repository as repo
from app.api import app


def _login_as(username: str, password: str) -> TestClient:
    c = TestClient(app)
    c.__enter__()
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


def _make_user(username: str, role: str = "user") -> str:
    return repo.create_user(username=username, password_hash=auth.hash_password("password123"), role=role)


def _company_body(code="BOX", **extra):
    body = {
        "company_code": code,
        "company_name": "Boxtrans Logistics (India) Services",
        "city_name": "Sonipat",
        "state_region": "Haryana",
        "country_name": "India",
        "company_address": "Inland Container Depot (DICT), Badshahpur Road",
        "zip_code": "131101",
        "phone": "09769947398",
        "email_id": "nisha.kothari398@gmail.com",
        "pan_no": "AACCB8054G",
        "gstin_no": "06AACCB8054G1ZT",
        "branches": [
            {
                "branch_code": "B1",
                "branch_name": "Mumbai Branch",
                "branch_address": "123 Dock Road, Mumbai",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zipcode": "400001",
                "telephone_no": "022-12345678",
                "email_id": "mumbai@boxtrans.in",
            }
        ],
    }
    body.update(extra)
    return body


def _port_body(company_id, code="INNSA1", **extra):
    body = {
        "company_id": company_id,
        "port_type": "SEA PORT",
        "port_code": code,
        "edi_port_code": code,
        "port_name": "Nhava Sheva",
        "country": "India",
        "active": True,
        "sez": False,
        "berths": [{"berth": "Berth 1", "fpd_code": "FPD01"}],
    }
    body.update(extra)
    return body


def _vessel_body(company_id, imo_code="9058960", **extra):
    body = {
        "name": "SPARROW",
        "imo_code": imo_code,
        "call_sign": "FHSLJ",
        "company_id": company_id,
    }
    body.update(extra)
    return body


def test_company_crud_with_branches(client):
    resp = client.post("/companies", json=_company_body())
    assert resp.status_code == 201
    company = resp.json()
    assert company["company_code"] == "BOX"
    assert len(company["branches"]) == 1
    assert company["branches"][0]["branch_name"] == "Mumbai Branch"
    assert company["updated_by"] == "testuser"

    cid = company["id"]
    got = client.get(f"/companies/{cid}")
    assert got.status_code == 200
    assert got.json()["company_name"] == "Boxtrans Logistics (India) Services"

    listed = client.get("/companies").json()
    assert any(c["id"] == cid for c in listed)

    # update replaces the branch set wholesale
    updated_body = _company_body()
    updated_body["branches"] = []
    upd = client.put(f"/companies/{cid}", json=updated_body)
    assert upd.status_code == 200
    assert upd.json()["branches"] == []

    dele = client.delete(f"/companies/{cid}")
    assert dele.status_code == 200
    assert client.get(f"/companies/{cid}").status_code == 404


def test_company_code_must_be_unique(client):
    assert client.post("/companies", json=_company_body("DUP")).status_code == 201
    dup = client.post("/companies", json=_company_body("DUP"))
    assert dup.status_code == 400


def _company(client, code="BOX"):
    return client.post("/companies", json=_company_body(code)).json()["id"]


def test_port_must_be_registered_under_an_existing_company(client):
    assert client.post("/ports", json=_port_body("does-not-exist")).status_code == 400


def test_port_crud_with_berths(client):
    company_id = _company(client)
    resp = client.post("/ports", json=_port_body(company_id))
    assert resp.status_code == 201
    port = resp.json()
    assert port["port_code"] == "INNSA1"
    assert port["active"] is True
    assert len(port["berths"]) == 1
    assert port["company_id"] == company_id
    assert port["company_name"] == "Boxtrans Logistics (India) Services"

    pid = port["id"]
    listed = client.get("/ports").json()
    assert any(p["id"] == pid for p in listed)

    # listing can be scoped to just this company's ports
    scoped = client.get("/ports", params={"company_id": company_id}).json()
    assert {p["id"] for p in scoped} == {pid}

    upd = client.put(f"/ports/{pid}", json=_port_body(company_id, active=False, berths=[]))
    assert upd.status_code == 200
    assert upd.json()["active"] is False
    assert upd.json()["berths"] == []

    assert client.delete(f"/ports/{pid}").status_code == 200
    assert client.get(f"/ports/{pid}").status_code == 404


def test_port_code_must_be_unique(client):
    company_id = _company(client)
    assert client.post("/ports", json=_port_body(company_id, "DUPPORT")).status_code == 201
    dup = client.post("/ports", json=_port_body(company_id, "DUPPORT"))
    assert dup.status_code == 400


def test_vessel_must_be_registered_under_an_existing_company(client):
    assert client.post("/vessels", json=_vessel_body("does-not-exist")).status_code == 400


def test_vessel_crud_and_company_port_association(client):
    company_id = _company(client)
    dep_port_id = client.post("/ports", json=_port_body(company_id, "INNSA1")).json()["id"]
    dest_port_id = client.post(
        "/ports", json=_port_body(company_id, "AEJEA", port_name="Jebel Ali")
    ).json()["id"]

    vessel_body = _vessel_body(
        company_id,
        build_year="2015", gross_tonnage="25000", net_tonnage="15000", ship_type="Container",
        departure_port_id=dep_port_id, destination_port_id=dest_port_id,
    )
    resp = client.post("/vessels", json=vessel_body)
    assert resp.status_code == 201
    vessel = resp.json()
    assert vessel["name"] == "SPARROW"
    # the association resolves to the linked records' own names, not just ids
    assert vessel["company_name"] == "Boxtrans Logistics (India) Services"
    assert vessel["departure_port_name"] == "Nhava Sheva"
    assert vessel["destination_port_name"] == "Jebel Ali"

    vid = vessel["id"]
    listed = client.get("/vessels").json()
    assert any(v["id"] == vid and v["company_name"] for v in listed)

    # listing can be scoped to just this company's vessels
    scoped = client.get("/vessels", params={"company_id": company_id}).json()
    assert {v["id"] for v in scoped} == {vid}

    vessel_body["ship_type"] = "Bulk Carrier"
    upd = client.put(f"/vessels/{vid}", json=vessel_body)
    assert upd.status_code == 200
    assert upd.json()["ship_type"] == "Bulk Carrier"

    assert client.delete(f"/vessels/{vid}").status_code == 200
    assert client.get(f"/vessels/{vid}").status_code == 404


def test_vessel_imo_code_must_be_unique(client):
    company_id = _company(client)
    assert client.post("/vessels", json=_vessel_body(company_id)).status_code == 201
    dup = client.post("/vessels", json=_vessel_body(company_id, name="B"))
    assert dup.status_code == 400


def test_vessel_without_port_association_has_blank_port_names(client):
    """Company is mandatory (registration workflow), but a Vessel's
    departure/destination port is still optional."""
    company_id = _company(client)
    resp = client.post("/vessels", json=_vessel_body(company_id, imo_code="7654321", name="LONE"))
    assert resp.status_code == 201
    v = resp.json()
    assert v["company_id"] == company_id
    assert v["departure_port_name"] is None
    assert v["destination_port_name"] is None


def test_masters_require_login(client):
    client.post("/auth/logout")
    assert client.get("/vessels").status_code == 401
    assert client.get("/companies").status_code == 401
    assert client.get("/ports").status_code == 401


def test_company_master_is_admin_only(client):
    """A regular user can read the companies endpoint (to populate their own
    Vessel/Port dropdowns) but can never create, edit, or delete a company —
    only an admin registers companies and assigns them to user logins."""
    _make_user("nancy", role="user")
    nancy = _login_as("nancy", "password123")
    try:
        assert nancy.post("/companies", json=_company_body("NANCO")).status_code == 403

        cid = _company(client, "ADMINCO")
        assert nancy.put(f"/companies/{cid}", json=_company_body("ADMINCO")).status_code == 403
        assert nancy.delete(f"/companies/{cid}").status_code == 403
    finally:
        nancy.__exit__(None, None, None)


def test_company_assignment_restricts_access_to_the_assigned_user(client):
    """Each company is assigned to exactly one user login by the admin — a
    user only sees/uses companies (and the vessels/ports under them) that
    are assigned to them; everything else is invisible, even to read."""
    amy_id = _make_user("amy", role="user")
    ben_id = _make_user("ben", role="user")

    co_amy = client.post("/companies", json={**_company_body("AMYCO"), "assigned_user_id": amy_id}).json()
    co_ben = client.post("/companies", json={**_company_body("BENCO"), "assigned_user_id": ben_id}).json()
    assert co_amy["assigned_username"] == "amy"

    amy = _login_as("amy", "password123")
    try:
        listed = amy.get("/companies").json()
        assert {c["id"] for c in listed} == {co_amy["id"]}
        assert amy.get(f"/companies/{co_ben['id']}").status_code == 403

        # amy can register a vessel/port under her own assigned company...
        ok = amy.post("/vessels", json=_vessel_body(co_amy["id"]))
        assert ok.status_code == 201
        # ...but not under ben's — even though it's a perfectly valid company
        blocked = amy.post("/vessels", json=_vessel_body(co_ben["id"], imo_code="1112223"))
        assert blocked.status_code == 403
        blocked_port = amy.post("/ports", json=_port_body(co_ben["id"], "BENPORT"))
        assert blocked_port.status_code == 403
    finally:
        amy.__exit__(None, None, None)

    # an unassigned company stays admin-only
    unassigned = client.post("/companies", json=_company_body("NOBODY")).json()
    amy2 = _login_as("amy", "password123")
    try:
        assert not any(c["id"] == unassigned["id"] for c in amy2.get("/companies").json())
        assert amy2.get(f"/companies/{unassigned['id']}").status_code == 403
    finally:
        amy2.__exit__(None, None, None)
