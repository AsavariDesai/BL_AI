"""Master BL / House BL (Import category) upload + linking.

Master BL has a real catalog now (field_catalog.MASTER_BL + the Ocean
Network Express "ONE" Sea Waybill template, parsers.one_masterbl) — but a
plain, non-matching PDF (as these tests upload) doesn't trip that template's
own fingerprint, so none of its *structured* fields (shipper, containers,
etc.) come back populated; only the generic, doc_type-agnostic "Document
Type" fuzzy-title guess can still fire, since this text literally contains
the words "bill of lading". This module only exercises upload/linking, not
extraction content. House BL has its own real catalog (field_catalog.
HOUSE_BL + parsers.yusen_hbl) and auto-extracts for the additional, real
reason of populating its 45 fields, same as a Bill of Lading does for
Export.
"""
import time

from tests.conftest import make_bl_pdf


def _upload_master(client) -> str:
    resp = client.post(
        "/documents", data={"doc_type": "master_bl"},
        files={"file": ("master.pdf", make_bl_pdf("MASTER BILL OF LADING\n"), "application/pdf")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _house_file(name: str):
    return (name, make_bl_pdf(f"HOUSE BILL OF LADING {name}\n"), "application/pdf")


def _wait_settled(client, doc_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = client.get(f"/documents/{doc_id}").json()
        if d["status"] in ("extracted", "error"):
            return d
        time.sleep(0.05)
    raise AssertionError(f"{doc_id} did not settle within {timeout}s")


def test_master_bl_upload_has_no_populated_fields(client):
    master_id = _upload_master(client)
    detail = _wait_settled(client, master_id)
    assert detail["doc_type"] == "master_bl"
    assert all(not f["value"] for f in detail["fields"] if f["key"] != "document_type")
    assert detail["linked_house_bls"] == []


def test_link_and_unlink_house_bls(client):
    master_id = _upload_master(client)

    resp = client.post(
        f"/documents/{master_id}/link-house-bl",
        files=[("files", _house_file("h1.pdf")), ("files", _house_file("h2.pdf"))],
    )
    assert resp.status_code == 201
    detail = resp.json()
    assert len(detail["linked_house_bls"]) == 2
    house_ids = [h["id"] for h in detail["linked_house_bls"]]
    for h in detail["linked_house_bls"]:
        # auto-extracted on upload (ingest_upload schedules it for
        # doc_type="house_bl") — no longer stuck at "uploaded" forever.
        # Background extraction may or may not have finished by the time
        # this response was built, so any of queued/processing/extracted/
        # error is correct; "uploaded" specifically means it was never
        # scheduled at all.
        assert h["status"] in ("queued", "processing", "extracted", "error")
        assert h["link_source"] == "manual"

    # linked House BLs don't show up as their own top-level record in the
    # Upload/Submitted lists (same as a Shipping Bill nested under a BL)...
    upload_ids = {d["id"] for d in client.get("/uploads").json()}
    assert not (set(house_ids) & upload_ids)
    # ...but the Master BL's own row reports the count
    uploads = client.get("/uploads", params={"doc_type": "master_bl"}).json()
    row = next(r for r in uploads if r["id"] == master_id)
    assert row["linked_house_bl_count"] == 2

    unlink = client.post(f"/documents/{master_id}/unlink-house-bl/{house_ids[0]}")
    assert unlink.status_code == 200
    assert len(unlink.json()["linked_house_bls"]) == 1


def test_link_house_bl_requires_an_existing_master_bl(client):
    resp = client.post(
        "/documents/does-not-exist/link-house-bl",
        files=[("files", _house_file("h1.pdf"))],
    )
    assert resp.status_code == 404


def test_link_house_bl_rejects_non_pdf(client):
    master_id = _upload_master(client)
    resp = client.post(
        f"/documents/{master_id}/link-house-bl",
        files=[("files", ("not-a-pdf.txt", b"hello", "text/plain"))],
    )
    assert resp.status_code == 400
