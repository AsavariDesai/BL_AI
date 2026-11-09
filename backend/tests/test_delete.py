"""Document delete: DELETE /documents/{id} and POST /documents/bulk-delete,
shared by Export (Bill of Lading / Shipping Bill) and Import (Master BL /
House BL) — lets a bad upload be removed and re-uploaded without deleting
the Company/Vessel it lives under."""
import os

from fastapi.testclient import TestClient

from app import auth
from app import repository as repo
from app.api import app
from tests.conftest import SAMPLE_BL, SAMPLE_SB, make_bl_pdf


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


def _upload_bl(client, text=SAMPLE_BL):
    return client.post(
        "/ingest", files={"file": ("bl.pdf", make_bl_pdf(text), "application/pdf")}
    ).json()


def _upload_sb(client, text=SAMPLE_SB):
    return client.post(
        "/ingest", files={"file": ("sb.pdf", make_bl_pdf(text), "application/pdf")}
    ).json()


def _upload_master(client, vessel_id, text="MASTER BILL OF LADING\n"):
    return client.post(
        "/documents", data={"doc_type": "master_bl", "vessel_id": vessel_id},
        files={"file": ("master.pdf", make_bl_pdf(text), "application/pdf")},
    ).json()


def _link_house(client, master_id, text="HOUSE BILL OF LADING\n"):
    resp = client.post(
        f"/documents/{master_id}/link-house-bl",
        files={"files": ("house.pdf", make_bl_pdf(text), "application/pdf")},
    )
    return resp.json()["linked_house_bls"][-1]  # the one just added (oldest-first order)


def _company_and_vessel(client):
    company_id = client.post("/companies", json={
        "company_code": "DEL1", "company_name": "Delete Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }).json()["id"]
    vessel_id = client.post("/vessels", json={
        "name": "DELETER", "imo_code": "9000111", "call_sign": "DLT01", "company_id": company_id,
    }).json()["id"]
    return company_id, vessel_id


def test_delete_bill_of_lading(client):
    doc = _upload_bl(client)
    stored_path = repo.get_document(doc["id"])["stored_path"]
    assert os.path.exists(stored_path)

    resp = client.delete(f"/documents/{doc['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == [doc["id"]]
    assert repo.get_document(doc["id"]) is None
    assert not os.path.exists(stored_path)  # no other record shares this file


def test_delete_nonexistent_document_is_404(client):
    assert client.delete("/documents/does-not-exist").status_code == 404


def test_deleting_shipping_bill_only_unlinks_its_bl_not_deletes_it(client):
    bl = _upload_bl(client)
    sb = _upload_sb(client)
    # BL-first link: attach the already-uploaded SB to the BL.
    link_resp = client.post(f"/documents/{bl['id']}/link-existing-sb", json={"doc_ids": [sb["id"]]})
    assert link_resp.status_code == 200
    assert link_resp.json()["linked_shipping_bills"][0]["id"] == sb["id"]

    resp = client.delete(f"/documents/{sb['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == [sb["id"]]

    assert repo.get_document(sb["id"]) is None
    assert repo.get_document(bl["id"]) is not None  # BL survives, just unlinked
    detail = client.get(f"/documents/{bl['id']}").json()
    assert detail["linked_shipping_bills"] == []


def test_deleting_master_bl_cascades_its_house_bls(client):
    _, vessel_id = _company_and_vessel(client)
    master = _upload_master(client, vessel_id)
    house1 = _link_house(client, master["id"], "HOUSE BILL OF LADING A\n")
    house2 = _link_house(client, master["id"], "HOUSE BILL OF LADING B\n")

    resp = client.delete(f"/documents/{master['id']}")
    assert resp.status_code == 200
    assert set(resp.json()["deleted"]) == {master["id"], house1["id"], house2["id"]}

    assert repo.get_document(master["id"]) is None
    assert repo.get_document(house1["id"]) is None
    assert repo.get_document(house2["id"]) is None


def test_delete_house_bl_individually_leaves_master_and_siblings(client):
    _, vessel_id = _company_and_vessel(client)
    master = _upload_master(client, vessel_id)
    house1 = _link_house(client, master["id"], "HOUSE BILL OF LADING A\n")
    house2 = _link_house(client, master["id"], "HOUSE BILL OF LADING B\n")

    resp = client.delete(f"/documents/{house1['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == [house1["id"]]

    assert repo.get_document(master["id"]) is not None
    assert repo.get_document(house1["id"]) is None
    assert repo.get_document(house2["id"]) is not None
    detail = client.get(f"/documents/{master['id']}").json()
    assert [h["id"] for h in detail["linked_house_bls"]] == [house2["id"]]


def test_bulk_delete_mixed_bls_and_sbs(client):
    bl1 = _upload_bl(client, SAMPLE_BL)
    bl2 = _upload_bl(client, SAMPLE_BL.replace("181142608002", "181142608003"))
    sb = _upload_sb(client)

    resp = client.post("/documents/bulk-delete", json={"doc_ids": [bl1["id"], bl2["id"], sb["id"]]})
    assert resp.status_code == 200
    assert set(resp.json()["deleted"]) == {bl1["id"], bl2["id"], sb["id"]}
    assert repo.get_document(bl1["id"]) is None
    assert repo.get_document(bl2["id"]) is None
    assert repo.get_document(sb["id"]) is None


def test_bulk_delete_expands_master_bls_to_their_house_bls(client):
    _, vessel_id = _company_and_vessel(client)
    master1 = _upload_master(client, vessel_id, "MASTER 1\n")
    house1 = _link_house(client, master1["id"])
    master2 = _upload_master(client, vessel_id, "MASTER 2\n")
    house2 = _link_house(client, master2["id"])

    resp = client.post("/documents/bulk-delete", json={"doc_ids": [master1["id"], master2["id"]]})
    assert resp.status_code == 200
    assert set(resp.json()["deleted"]) == {master1["id"], master2["id"], house1["id"], house2["id"]}


def test_shared_stored_file_survives_until_every_referencing_doc_is_gone(client):
    content = make_bl_pdf(SAMPLE_BL)
    r1 = client.post("/ingest", files={"file": ("a.pdf", content, "application/pdf")}).json()
    r2 = client.post("/ingest", files={"file": ("b.pdf", content, "application/pdf")}).json()
    assert r1["id"] != r2["id"]
    stored_path = repo.get_document(r1["id"])["stored_path"]
    assert stored_path == repo.get_document(r2["id"])["stored_path"]  # deduped on disk

    client.delete(f"/documents/{r1['id']}")
    assert os.path.exists(stored_path)  # r2 still references it

    client.delete(f"/documents/{r2['id']}")
    assert not os.path.exists(stored_path)


def test_import_only_user_cannot_delete_a_bill_of_lading(client):
    bl = _upload_bl(client)
    _make_user("importer", can_export=False, can_import=True)
    u = _login_as("importer")
    try:
        assert u.delete(f"/documents/{bl['id']}").status_code == 403
    finally:
        u.__exit__(None, None, None)


def test_export_only_user_cannot_delete_a_master_bl(client):
    _, vessel_id = _company_and_vessel(client)
    master = _upload_master(client, vessel_id)
    _make_user("exporter", can_export=True, can_import=False)
    u = _login_as("exporter")
    try:
        assert u.delete(f"/documents/{master['id']}").status_code == 403
    finally:
        u.__exit__(None, None, None)


def test_outsider_cannot_delete_someone_elses_company_document(client):
    uid = _make_user("owner")
    company_id = client.post("/companies", json={
        "company_code": "DEL2", "company_name": "Owner Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT", "assigned_user_id": uid,
    }).json()["id"]
    vessel_id = client.post("/vessels", json={
        "name": "OWNED", "imo_code": "9000222", "call_sign": "OWN01", "company_id": company_id,
    }).json()["id"]
    master = _upload_master(client, vessel_id)

    _make_user("outsider")
    u = _login_as("outsider")
    try:
        assert u.delete(f"/documents/{master['id']}").status_code == 403
    finally:
        u.__exit__(None, None, None)
    assert repo.get_document(master["id"]) is not None
