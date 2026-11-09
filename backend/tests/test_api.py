def test_full_flow(client, bl_pdf_bytes):
    up = client.post(
        "/documents",
        files={"file": ("bl.pdf", bl_pdf_bytes, "application/pdf")},
    )
    assert up.status_code == 201
    doc_id = up.json()["id"]
    assert up.json()["status"] == "uploaded"

    ex = client.post(f"/documents/{doc_id}/extract")
    assert ex.status_code == 200
    body = ex.json()
    assert body["status"] == "extracted"
    assert body["engine"] == "rules"
    assert len(body["fields"]) == 50

    detail = client.get(f"/documents/{doc_id}").json()
    by_key = {f["key"]: f for f in detail["fields"]}
    assert by_key["container_and_seal_numbers"]["value"] == "CSQU3054383"

    put = client.put(
        f"/documents/{doc_id}/fields",
        json={"fields": [
            {"key": "booking_number", "value": "BK-9910"},   # was empty
            {"key": "consignee", "value": "ACME TRADING LLC"},  # was different
        ]},
    )
    assert put.status_code == 200
    assert put.json()["status"] == "reviewed"
    edited = {f["key"]: f for f in put.json()["fields"]}
    assert edited["consignee"]["value"] == "ACME TRADING LLC"
    assert edited["consignee"]["source"] == "user"
    assert edited["consignee"]["confidence"] == 1.0

    corrections = client.get("/corrections").json()
    assert len(corrections) == 2
    keys = {c["field_key"] for c in corrections}
    assert keys == {"booking_number", "consignee"}

    # re-saving identical values must not log new corrections
    client.put(
        f"/documents/{doc_id}/fields",
        json={"fields": [{"key": "consignee", "value": "ACME TRADING LLC"}]},
    )
    assert len(client.get("/corrections").json()) == 2

    stats = client.get("/corrections/stats").json()
    assert stats["by_field"]["consignee"] == 1


def test_upload_rejects_non_pdf(client):
    r = client.post(
        "/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_get_missing_document_404(client):
    assert client.get("/documents/does-not-exist").status_code == 404


def test_fields_endpoint_lists_catalog(client):
    fields = client.get("/fields").json()
    assert len(fields) == 50
    assert {"key", "label", "group", "type", "aliases", "example"} <= set(fields[0])


def _extracted_doc(client, pdf_bytes):
    doc_id = client.post(
        "/documents", files={"file": ("bl.pdf", pdf_bytes, "application/pdf")}
    ).json()["id"]
    client.post(f"/documents/{doc_id}/extract")
    return doc_id


def test_export_xlsx_and_pdf(client, bl_pdf_bytes):
    doc_id = _extracted_doc(client, bl_pdf_bytes)

    xlsx = client.get(f"/documents/{doc_id}/export?fmt=xlsx&fields=bl_number,port_of_discharge")
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"  # xlsx is a zip
    assert "attachment" in xlsx.headers["content-disposition"]
    assert xlsx.headers["content-disposition"].endswith('.xlsx"')

    pdf = client.get(f"/documents/{doc_id}/export?fmt=pdf")
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"


def test_export_uses_saved_template(client, bl_pdf_bytes):
    doc_id = _extracted_doc(client, bl_pdf_bytes)
    tpl = client.post(
        "/export-templates",
        json={"name": "mini", "selected_fields": ["bl_number", "gross_weight"]},
    ).json()

    r = client.get(f"/documents/{doc_id}/export?fmt=xlsx&template_id={tpl['id']}")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_batch_export(client, bl_pdf_bytes):
    a = _extracted_doc(client, bl_pdf_bytes)
    b = _extracted_doc(client, bl_pdf_bytes)  # same sha -> same stored file, new doc row
    r = client.post("/exports", json={"doc_ids": [a, b], "fmt": "xlsx"})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
    assert "bl_export_2_" in r.headers["content-disposition"]


def test_export_bad_format_400(client, bl_pdf_bytes):
    doc_id = _extracted_doc(client, bl_pdf_bytes)
    assert client.get(f"/documents/{doc_id}/export?fmt=csv").status_code == 400


def test_export_template_roundtrip(client):
    payload = {
        "name": "Onion exports",
        "selected_fields": ["bl_number", "shipper", "port_of_discharge"],
        "output_type": "xlsx",
    }
    created = client.post("/export-templates", json=payload)
    assert created.status_code == 201
    assert created.json()["selected_fields"] == payload["selected_fields"]

    listed = client.get("/export-templates").json()
    assert any(t["name"] == "Onion exports" for t in listed)
