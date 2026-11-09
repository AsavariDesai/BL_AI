"""Export's own Vessel Workspace — Company -> Vessel -> Bill of Lading /
Shipping Bill uploads, mirroring Import's. Vessels/Ports are shared
infrastructure between both sides now (see test_rights.py); this covers
the Export-specific upload/list/delete/bulk-upload behavior on top."""
import time

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


def _company_body(code="EVC1", **extra):
    body = {
        "company_code": code, "company_name": "Export Vessel Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }
    body.update(extra)
    return body


def _vessel_body(company_id, imo_code="9100001", **extra):
    body = {"name": "EXPORTER", "imo_code": imo_code, "call_sign": "EXP01", "company_id": company_id}
    body.update(extra)
    return body


def _wait_until_settled(client, doc_ids, timeout=10.0):
    """Bulk upload schedules extraction (and SB<->BL auto-link) in the
    background — poll until every id reaches a terminal status instead of
    racing it, same as a real caller would (the Vessel Workspace's own list
    just re-renders whenever it next polls)."""
    deadline = time.monotonic() + timeout
    pending = set(doc_ids)
    while pending and time.monotonic() < deadline:
        for doc_id in list(pending):
            row = repo.get_document(doc_id)
            if row and row["status"] in ("extracted", "error"):
                pending.discard(doc_id)
        if pending:
            time.sleep(0.1)
    assert not pending, f"still not settled after {timeout}s: {pending}"


def _company_and_vessel(client, **vessel_extra):
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    vessel_id = client.post("/vessels", json=_vessel_body(company_id, **vessel_extra)).json()["id"]
    return company_id, vessel_id


def test_bl_upload_scopes_to_vessel_and_inherits_company(client):
    company_id, vessel_id = _company_and_vessel(client)

    resp = client.post(
        "/documents", data={"doc_type": "bill_of_lading", "vessel_id": vessel_id},
        files={"file": ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["vessel_id"] == vessel_id
    row = repo.get_document(body["id"])
    assert row["company_id"] == company_id  # carried over from the vessel

    scoped = client.get(
        "/records/overview", params={"category": "export", "vessel_id": vessel_id}
    ).json()
    assert {r["id"] for r in scoped} == {body["id"]}


def test_ingest_accepts_vessel_id_and_auto_extracts(client):
    _, vessel_id = _company_and_vessel(client)
    resp = client.post(
        "/ingest", data={"vessel_id": vessel_id},
        files={"file": ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf")},
    )
    assert resp.status_code == 201
    detail = resp.json()
    assert detail["vessel_id"] == vessel_id
    assert detail["status"] == "extracted"
    assert any(f["value"] for f in detail["fields"])


def test_existing_company_scoped_records_still_show_without_a_vessel(client):
    """The chosen migration path: existing/non-vessel uploads keep showing
    under the Company exactly as before — nothing is forced into a vessel."""
    company_id = client.post("/companies", json=_company_body()).json()["id"]
    resp = client.post(
        "/ingest", data={"company_id": company_id},
        files={"file": ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf")},
    )
    assert resp.status_code == 201
    assert resp.json()["vessel_id"] is None

    company_scoped = client.get(
        "/records/overview", params={"category": "export", "company_id": company_id}
    ).json()
    assert len(company_scoped) == 1


def test_vessel_list_shows_bl_and_sb_counts(client):
    _, vessel_id = _company_and_vessel(client)
    client.post(
        "/documents", data={"doc_type": "bill_of_lading", "vessel_id": vessel_id},
        files={"file": ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf")},
    )
    client.post(
        "/documents", data={"doc_type": "shipping_bill", "vessel_id": vessel_id},
        files={"file": ("sb.pdf", make_bl_pdf(SAMPLE_SB), "application/pdf")},
    )

    listed = client.get("/vessels").json()
    v = next(x for x in listed if x["id"] == vessel_id)
    assert v["bl_count"] == 1
    assert v["sb_count"] == 1
    assert v["master_bl_count"] == 0


def test_bulk_upload_to_vessel_auto_detects_type_and_extracts(client):
    _, vessel_id = _company_and_vessel(client)
    files = [
        ("files", ("bl1.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf")),
        ("files", ("sb1.pdf", make_bl_pdf(SAMPLE_SB), "application/pdf")),
        ("files", ("bl2.pdf", make_bl_pdf(SAMPLE_BL.replace("181142608002", "999")), "application/pdf")),
    ]
    resp = client.post(f"/vessels/{vessel_id}/bulk-upload", files=files)
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["uploaded"]) == 3
    assert body["failed"] == []

    rows = [repo.get_document(i) for i in body["uploaded"]]
    assert sorted(r["doc_type"] for r in rows) == ["bill_of_lading", "bill_of_lading", "shipping_bill"]
    assert all(r["vessel_id"] == vessel_id for r in rows)

    _wait_until_settled(client, body["uploaded"])

    # The SB shares its number with bl1's SAMPLE_BL fixture, so it
    # auto-links and nests under that BL (same "expand the row" UX as
    # every other Shipping Bill linked to a BL) rather than showing as
    # its own top-level row — same exclusion rule as a linked House BL.
    scoped = client.get(
        "/records/overview", params={"category": "export", "vessel_id": vessel_id}
    ).json()
    assert len(scoped) == 2
    bl1 = next(r for r in scoped if r["doc_number"] != "999")
    assert bl1["linked_sb_count"] == 1


def test_bulk_upload_rejects_non_pdf(client):
    _, vessel_id = _company_and_vessel(client)
    resp = client.post(
        f"/vessels/{vessel_id}/bulk-upload",
        files=[("files", ("not-a-pdf.txt", b"hello", "text/plain"))],
    )
    assert resp.status_code == 400


def test_bulk_upload_requires_existing_vessel(client):
    resp = client.post(
        "/vessels/does-not-exist/bulk-upload",
        files=[("files", ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf"))],
    )
    assert resp.status_code == 404


def test_vessel_with_bl_or_sb_cannot_be_deleted(client):
    _, vessel_id = _company_and_vessel(client)
    client.post(
        "/documents", data={"doc_type": "bill_of_lading", "vessel_id": vessel_id},
        files={"file": ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf")},
    )
    resp = client.delete(f"/vessels/{vessel_id}")
    assert resp.status_code == 400
    assert client.get(f"/vessels/{vessel_id}").status_code == 200  # still there


def test_vessel_becomes_deletable_once_its_bl_is_deleted(client):
    _, vessel_id = _company_and_vessel(client)
    doc_id = client.post(
        "/documents", data={"doc_type": "bill_of_lading", "vessel_id": vessel_id},
        files={"file": ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf")},
    ).json()["id"]

    assert client.delete(f"/vessels/{vessel_id}").status_code == 400
    client.delete(f"/documents/{doc_id}")
    assert client.delete(f"/vessels/{vessel_id}").status_code == 200


def test_import_only_user_can_still_reach_vessels_but_not_bulk_upload(client):
    _, vessel_id = _company_and_vessel(client)
    _make_user("importer2", can_export=False, can_import=True)
    u = _login_as("importer2")
    try:
        assert u.get("/vessels").status_code == 200  # shared infrastructure
        resp = u.post(
            f"/vessels/{vessel_id}/bulk-upload",
            files=[("files", ("bl.pdf", make_bl_pdf(SAMPLE_BL), "application/pdf"))],
        )
        assert resp.status_code == 403  # bulk-upload itself is Export-only
    finally:
        u.__exit__(None, None, None)
