import pytest


def _upload(client, pdf, doc_type="bill_of_lading", parent_id=None):
    data = {"doc_type": doc_type}
    if parent_id:
        data["parent_id"] = parent_id
    return client.post(
        "/documents", data=data, files={"file": ("d.pdf", pdf, "application/pdf")}
    )


def test_doc_types_and_catalogs(client):
    types = {t["key"] for t in client.get("/doc-types").json()}
    assert types == {"bill_of_lading", "shipping_bill", "master_bl", "house_bl"}

    assert len(client.get("/fields?doc_type=bill_of_lading").json()) == 50
    sb_fields = client.get("/fields?doc_type=shipping_bill").json()
    assert len(sb_fields) == 22
    assert {"sb_number", "leo_date", "cin_date", "shipper_code"} <= {f["key"] for f in sb_fields}
    # Master BL: real catalog, modeled on the Ocean Network Express ("ONE")
    # Sea Waybill form (see field_catalog.MASTER_BL / parsers.one_masterbl)
    master_fields = client.get("/fields?doc_type=master_bl").json()
    assert len(master_fields) == 36
    assert {"bl_number", "booking_number", "shipper", "consignee", "vessel_and_voyage"} \
        <= {f["key"] for f in master_fields}
    # House BL: real catalog, modeled on the Yusen Logistics form (see
    # field_catalog.HOUSE_BL / parsers.yusen_hbl)
    house_fields = client.get("/fields?doc_type=house_bl").json()
    assert len(house_fields) == 45
    assert {"bl_number", "shipper", "consignee", "hs_code"} <= {f["key"] for f in house_fields}
    assert client.get("/fields?doc_type=nonsense").status_code == 400


def test_shipping_bill_extraction(client, sb_pdf_bytes):
    up = _upload(client, sb_pdf_bytes, doc_type="shipping_bill")
    assert up.status_code == 201
    assert up.json()["doc_type"] == "shipping_bill"

    detail = client.post(f"/documents/{up.json()['id']}/extract").json()
    assert detail["doc_type"] == "shipping_bill"
    assert len(detail["fields"]) == 22
    m = {f["key"]: f["value"] for f in detail["fields"]}
    assert m["sb_number"] == "5778867"
    assert m["sb_date"] == "2026-08-08"
    assert m["leo_date"] == "2026-08-14"
    assert "ONION" in (m["cargo_description"] or "").upper()


def test_link_and_unlink_bls_under_a_shipping_bill(client, sb_pdf_bytes, bl_pdf_bytes):
    sb_id = _upload(client, sb_pdf_bytes, doc_type="shipping_bill").json()["id"]
    bl1 = _upload(client, bl_pdf_bytes).json()["id"]
    bl2 = _upload(client, bl_pdf_bytes).json()["id"]

    linked = client.post(f"/shipping-bills/{sb_id}/link", json={"doc_ids": [bl1, bl2]})
    assert linked.status_code == 200
    assert {b["id"] for b in linked.json()["linked_bls"]} == {bl1, bl2}
    assert all(b["parent_id"] == sb_id for b in linked.json()["linked_bls"])

    sbs = client.get("/shipping-bills").json()
    assert sbs[0]["bl_count"] == 2

    # unlinked filter excludes the linked BLs
    unlinked = client.get("/documents?doc_type=bill_of_lading&unlinked=true").json()
    assert bl1 not in {d["id"] for d in unlinked}

    detail = client.post(f"/shipping-bills/{sb_id}/unlink", json={"doc_ids": [bl1]})
    assert {b["id"] for b in detail.json()["linked_bls"]} == {bl2}
    assert client.get("/shipping-bills").json()[0]["bl_count"] == 1


def test_link_via_upload_parent_id(client, sb_pdf_bytes, bl_pdf_bytes):
    sb_id = _upload(client, sb_pdf_bytes, doc_type="shipping_bill").json()["id"]
    bl = _upload(client, bl_pdf_bytes, parent_id=sb_id)
    assert bl.status_code == 201
    assert bl.json()["parent_id"] == sb_id
    assert client.get(f"/shipping-bills/{sb_id}").json()["linked_bls"][0]["id"] == bl.json()["id"]


def test_cannot_parent_to_a_non_shipping_bill(client, bl_pdf_bytes):
    bl_a = _upload(client, bl_pdf_bytes).json()["id"]
    r = _upload(client, bl_pdf_bytes, parent_id=bl_a)
    assert r.status_code == 400


def test_shipping_bill_404(client):
    assert client.get("/shipping-bills/nope").status_code == 404
