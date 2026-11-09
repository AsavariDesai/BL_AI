import io

from openpyxl import load_workbook

from app.classify import detect_doc_type

from tests.conftest import make_bl_pdf


def _ingest(client, pdf, doc_type=None, parent_id=None):
    data = {}
    if doc_type:
        data["doc_type"] = doc_type
    if parent_id:
        data["parent_id"] = parent_id
    return client.post(
        "/ingest", data=data, files={"file": ("d.pdf", pdf, "application/pdf")}
    )


def test_detect_doc_type_unit():
    assert detect_doc_type("SHIPPING BILL FOR EXPORT  LEO DATE  DRAWBACK  PCIN")[0] == "shipping_bill"
    assert detect_doc_type("COMBINED TRANSPORT BILL OF LADING  PORT OF DISCHARGE  VESSEL")[0] == "bill_of_lading"
    assert detect_doc_type("")[0] == "bill_of_lading"


def test_ingest_auto_detects_type(client, sb_pdf_bytes, bl_pdf_bytes):
    sb = _ingest(client, sb_pdf_bytes)
    assert sb.status_code == 201
    assert sb.json()["doc_type"] == "shipping_bill"
    assert len(sb.json()["fields"]) == 22

    bl = _ingest(client, bl_pdf_bytes)
    assert bl.json()["doc_type"] == "bill_of_lading"


def test_bl_auto_links_to_existing_shipping_bill(client, sb_pdf_bytes, bl_pdf_bytes):
    sb_id = _ingest(client, sb_pdf_bytes).json()["id"]

    bl = _ingest(client, bl_pdf_bytes).json()          # references "SB NO. 5778867"
    assert bl["parent_id"] == sb_id
    assert bl["link_source"] == "auto"

    sb_detail = client.get(f"/shipping-bills/{sb_id}").json()
    assert bl["id"] in {b["id"] for b in sb_detail["linked_bls"]}


def test_shipping_bill_adopts_bls_uploaded_before_it(client, sb_pdf_bytes, bl_pdf_bytes):
    bl_id = _ingest(client, bl_pdf_bytes).json()["id"]   # no SB yet -> stays unlinked
    assert client.get(f"/documents/{bl_id}").json()["parent_id"] is None

    sb_id = _ingest(client, sb_pdf_bytes).json()["id"]   # now the SB arrives
    linked = client.get(f"/shipping-bills/{sb_id}").json()["linked_bls"]
    assert {b["id"] for b in linked} == {bl_id}
    assert linked[0]["link_source"] == "auto"


def test_manual_link_is_not_overridden_by_auto(client, sb_pdf_bytes, bl_pdf_bytes):
    sb_a = _ingest(client, sb_pdf_bytes, doc_type="shipping_bill").json()["id"]
    sb_b = _ingest(client, sb_pdf_bytes, doc_type="shipping_bill").json()["id"]
    bl_id = _ingest(client, bl_pdf_bytes, parent_id=sb_b).json()["id"]  # explicit parent
    # even though the BL text references sb_a's number, the manual link to sb_b holds
    assert client.get(f"/documents/{bl_id}").json()["parent_id"] == sb_b


def test_hierarchy_endpoint(client, sb_pdf_bytes, bl_pdf_bytes):
    sb_id = _ingest(client, sb_pdf_bytes).json()["id"]
    _ingest(client, bl_pdf_bytes)                       # auto-links to the SB
    lone_bl = client.post(
        "/documents", data={"doc_type": "bill_of_lading"},
        files={"file": ("x.pdf", bl_pdf_bytes, "application/pdf")},
    ).json()["id"]  # not extracted -> no SB ref -> stays unlinked

    h = client.get("/hierarchy").json()
    assert len(h["shipping_bills"]) == 1
    sb = h["shipping_bills"][0]
    assert sb["id"] == sb_id
    assert sb["sb_number"] == "5778867"
    assert sb["bl_count"] == 1 and len(sb["linked_bls"]) == 1
    assert lone_bl in {b["id"] for b in h["unlinked_bls"]}


_MULTI_SB_BL = """COMBINED TRANSPORT BILL OF LADING
B/L No: HBL/MULTI/001
Shipper: EXPORT HOUSE PVT LTD, PUNE
Consignee: OVERSEAS BUYER LLC, DUBAI
Port of Discharge: JEBEL ALI
SHIPPING BILL NOS: 7412580, 7412581 & 7412599
Also cleared under Shipping Bill No. 7500001 DT. 09.09.2026
FREIGHT PREPAID
"""

_SB_TMPL = """SHIPPING BILL FOR EXPORT OF GOODS
SB No: {n}
SB Date: 09.09.2026
Field Location: INNSA1
Exporter Name: EXPORT HOUSE PVT LTD
HS Code: 07031019
"""


def test_bl_extracts_every_referenced_shipping_bill(client):
    bl = _ingest(client, make_bl_pdf(_MULTI_SB_BL)).json()
    refs = next(f["value"] for f in bl["fields"]
               if f["key"] == "shipping_bill_number_and_date")
    for n in ("7412580", "7412581", "7412599", "7500001"):
        assert n in refs


def test_shipping_bill_matches_bl_on_any_referenced_number(client):
    bl_id = _ingest(client, make_bl_pdf(_MULTI_SB_BL)).json()["id"]
    assert client.get(f"/documents/{bl_id}").json()["parent_id"] is None

    # a Shipping Bill for the *second* number in the BL's list still links it
    sb_id = _ingest(client, make_bl_pdf(_SB_TMPL.format(n="7412581"))).json()["id"]
    detail = client.get(f"/shipping-bills/{sb_id}").json()
    assert {b["id"] for b in detail["linked_bls"]} == {bl_id}
    assert detail["linked_bls"][0]["link_source"] == "auto"

    # the combined Excel export carries SB + BL on one row
    xlsx = client.get(f"/shipping-bills/{sb_id}/export?fmt=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_bl_auto_links_every_referenced_shipping_bill_already_uploaded(client):
    """The BL references 4 Shipping Bill numbers and all 4 already exist as
    uploaded documents before the BL itself is uploaded — auto-link must
    attach every one of them (via bl_sb_links), not just the first match,
    so the overview's count and the reconciliation both come out accurate."""
    sb_ids = {
        n: _ingest(client, make_bl_pdf(_SB_TMPL.format(n=n))).json()["id"]
        for n in ("7412580", "7412581", "7412599", "7500001")
    }
    bl_id = _ingest(client, make_bl_pdf(_MULTI_SB_BL)).json()["id"]

    detail = client.get(f"/documents/{bl_id}").json()
    linked_ids = {lsb["id"] for lsb in detail["linked_shipping_bills"]}
    assert linked_ids == set(sb_ids.values())
    assert detail["sb_reconciliation"]["missing_numbers"] == []
    assert detail["sb_reconciliation"]["total_uploaded"] == 4
    # the legacy single parent pointer still gets set, for older code that
    # reads it directly — doesn't matter which one, as long as it's one of them
    assert detail["parent_id"] in sb_ids.values()

    overview = client.get("/records/overview", params={"q": "", "category": "export"}).json()
    row = next(r for r in overview if r["id"] == bl_id)
    assert row["linked_sb_count"] == 4
    assert row["sb_referenced_count"] == 4
    assert row["sb_missing_count"] == 0
    assert row["sb_duplicate_count"] == 0


def test_sb_auto_link_is_scoped_to_its_own_vessel(client):
    """Two different vessels each have a Shipping Bill with the same short
    number — a BL on one vessel referencing that number must only auto-link
    to its own vessel's Shipping Bill, never the other vessel's."""
    company_id = client.post("/companies", json={
        "company_code": "ALNK1", "company_name": "Auto Link Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }).json()["id"]
    vessel_a = client.post("/vessels", json={
        "name": "ALINK VESSEL A", "imo_code": "9600001", "call_sign": "ALKA", "company_id": company_id,
    }).json()["id"]
    vessel_b = client.post("/vessels", json={
        "name": "ALINK VESSEL B", "imo_code": "9600002", "call_sign": "ALKB", "company_id": company_id,
    }).json()["id"]

    sb_a_id = client.post(
        "/ingest", data={"vessel_id": vessel_a},
        files={"file": ("sb_a.pdf", make_bl_pdf(_link_sb_text("4455667")), "application/pdf")},
    ).json()["id"]
    sb_b_id = client.post(
        "/ingest", data={"vessel_id": vessel_b},
        files={"file": ("sb_b.pdf", make_bl_pdf(_link_sb_text("4455667")), "application/pdf")},
    ).json()["id"]

    bl_text = _LINK_BL.replace("LNK/BL/001", "LNK/BL/002") + "SHIPPING BILL NOS: 4455667\n"
    bl_b_id = client.post(
        "/ingest", data={"vessel_id": vessel_b},
        files={"file": ("bl_b.pdf", make_bl_pdf(bl_text), "application/pdf")},
    ).json()["id"]

    detail = client.get(f"/documents/{bl_b_id}").json()
    linked_ids = {lsb["id"] for lsb in detail["linked_shipping_bills"]}
    assert linked_ids == {sb_b_id}
    assert sb_a_id not in linked_ids


def test_export_hierarchy_xlsx_and_pdf(client, sb_pdf_bytes, bl_pdf_bytes):
    sb_id = _ingest(client, sb_pdf_bytes).json()["id"]
    _ingest(client, bl_pdf_bytes)  # auto-links

    xlsx = client.get(f"/shipping-bills/{sb_id}/export?fmt=xlsx")
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"
    assert "shipping_bill_5778867_" in xlsx.headers["content-disposition"]

    pdf = client.get(f"/shipping-bills/{sb_id}/export?fmt=pdf&bl_fields=bl_number,port_of_discharge")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


# --------------------------------------------------------- BL-first SB linking
_LINK_BL = """COMBINED TRANSPORT BILL OF LADING
B/L No: LNK/BL/001
Shipper: LINK TEST EXPORTS, MUMBAI
Consignee: LINK TEST BUYER LLC, DUBAI
Port of Discharge: JEBEL ALI
FREIGHT PREPAID
"""

_LINK_SB = """SHIPPING BILL FOR EXPORT OF GOODS
SB No: 9988776
SB Date: 10.09.2026
CIN No: 26PCEG07033580219700 DT 03-JUL-26
No of Packages: 500
Gross Weight: 12000.000 KGS
Field Location: INNSA1
Destination: JEBEL ALI, UAE
Shipper Code: BMMPG8728K
HS Code: 39235090
Exporter Name: LINK TEST EXPORTS
Consignee Name: LINK TEST BUYER LLC
Consignee Address: DUBAI, UAE
Nature of Cargo: PACKAGED
LEO Date: 12.09.2026
LEO No: 2/9
"""


def _link_sb_text(number: str) -> str:
    return f"""SHIPPING BILL FOR EXPORT OF GOODS
SB No: {number}
SB Date: 10.09.2026
CIN No: 26PCEG07033580{number[-6:]} DT 03-JUL-26
No of Packages: 500
Gross Weight: 12000.000 KGS
Field Location: INNSA1
Destination: JEBEL ALI, UAE
Shipper Code: BMMPG8728K
HS Code: 39235090
Exporter Name: LINK TEST EXPORTS
"""


def test_bl_first_link_uploads_and_links_regardless_of_sb_number(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]  # no SB ref at all
    assert client.get(f"/documents/{bl_id}").json()["linked_shipping_bills"] == []

    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("sb.pdf", make_bl_pdf(_LINK_SB), "application/pdf"))],
    )
    assert r.status_code == 201
    detail = r.json()
    assert detail["id"] == bl_id
    linked = detail["linked_shipping_bills"]
    assert len(linked) == 1
    assert linked[0]["link_source"] == "manual"
    assert linked[0]["sb_number"] == "9988776"

    sb_id = linked[0]["id"]
    sb = client.get(f"/documents/{sb_id}").json()
    assert sb["doc_type"] == "shipping_bill"
    for f in sb["fields"]:
        if f["key"] == "sb_number":
            assert f["value"] == "9988776"


def test_bl_first_link_supports_many_shipping_bills_on_one_bl(client):
    """The core of this feature: a BL can have many linked Shipping Bills,
    each upload adds to the set rather than replacing it."""
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]

    numbers = [f"100000{i}" for i in range(5)]
    for num in numbers:
        r = client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[("files", (f"sb_{num}.pdf", make_bl_pdf(_link_sb_text(num)), "application/pdf"))],
        )
        assert r.status_code == 201

    detail = client.get(f"/documents/{bl_id}").json()
    linked = detail["linked_shipping_bills"]
    assert len(linked) == 5
    assert {lsb["sb_number"] for lsb in linked} == set(numbers)

    # unlinking one leaves the other four untouched
    victim = linked[0]["id"]
    r = client.post(f"/documents/{bl_id}/unlink-sb/{victim}")
    assert r.status_code == 200
    remaining = r.json()["linked_shipping_bills"]
    assert len(remaining) == 4
    assert victim not in {lsb["id"] for lsb in remaining}


def test_bl_first_link_flags_sb_number_mismatch(client):
    """Linking a Shipping Bill to a BL always succeeds (BL-first linking
    doesn't wait on or get blocked by the number match), but once both sides
    are extracted, a Shipping Bill whose own number isn't among the BL's
    referenced numbers must be flagged so the user can double-check it."""
    bl_id = _ingest(client, make_bl_pdf(_MULTI_SB_BL)).json()["id"]

    client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("match.pdf", make_bl_pdf(_SB_TMPL.format(n="7412581")), "application/pdf"))],
    )
    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("mismatch.pdf", make_bl_pdf(_SB_TMPL.format(n="9999999")), "application/pdf"))],
    )
    assert r.status_code == 201

    by_number = {lsb["sb_number"]: lsb for lsb in r.json()["linked_shipping_bills"]}
    assert by_number["7412581"]["sb_number_match"] is True
    assert by_number["9999999"]["sb_number_match"] is False


def test_sb_reconciliation_reports_missing_numbers(client):
    """The BL references 4 Shipping Bill numbers (7412580, 7412581, 7412599,
    7500001) — uploading only one of them must surface the other three as
    missing, with the right total counts."""
    bl_id = _ingest(client, make_bl_pdf(_MULTI_SB_BL)).json()["id"]

    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("sb.pdf", make_bl_pdf(_SB_TMPL.format(n="7412581")), "application/pdf"))],
    )
    assert r.status_code == 201

    rec = r.json()["sb_reconciliation"]
    assert rec["total_referenced"] == 4
    assert rec["total_uploaded"] == 1
    assert rec["missing_numbers"] == ["7412580", "7412599", "7500001"]
    assert rec["duplicate_numbers"] == []
    assert rec["unrelated_numbers"] == []


def test_sb_reconciliation_is_none_when_bl_references_no_sb(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]  # no SB ref at all
    detail = client.get(f"/documents/{bl_id}").json()
    assert detail["sb_reconciliation"] is None


def test_sb_reconciliation_flags_duplicates_and_unrelated_uploads(client):
    """Same BL referencing 7412580/7412581/7412599/7500001 — upload 7412581
    twice (duplicate) and a number the BL never mentions (unrelated/possibly
    incorrect upload); both must be called out by exact number."""
    bl_id = _ingest(client, make_bl_pdf(_MULTI_SB_BL)).json()["id"]

    for fname in ("first.pdf", "second.pdf"):
        client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[("files", (fname, make_bl_pdf(_SB_TMPL.format(n="7412581")), "application/pdf"))],
        )
    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("stray.pdf", make_bl_pdf(_SB_TMPL.format(n="9999999")), "application/pdf"))],
    )
    assert r.status_code == 201

    rec = r.json()["sb_reconciliation"]
    assert rec["total_referenced"] == 4
    assert rec["total_uploaded"] == 3
    assert rec["duplicate_numbers"] == ["7412581"]
    assert rec["unrelated_numbers"] == ["9999999"]
    assert rec["missing_numbers"] == ["7412580", "7412599", "7500001"]


def test_is_duplicate_flag_clears_once_the_extra_copy_is_removed(client):
    """Both rows of a duplicate pair are flagged — remove one and the
    remaining row must stop being flagged as a duplicate on the very next
    fetch (it's recomputed fresh from current links, not cached)."""
    bl_id = _ingest(client, make_bl_pdf(_MULTI_SB_BL)).json()["id"]

    ids = []
    for fname in ("first.pdf", "second.pdf"):
        r = client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[("files", (fname, make_bl_pdf(_SB_TMPL.format(n="7412581")), "application/pdf"))],
        )
        ids.append(r.json()["linked_shipping_bills"][-1]["id"])

    linked = r.json()["linked_shipping_bills"]
    assert len(linked) == 2
    assert all(lsb["is_duplicate"] for lsb in linked)

    r = client.post(f"/documents/{bl_id}/unlink-sb/{ids[0]}")
    assert r.status_code == 200
    remaining = r.json()["linked_shipping_bills"]
    assert len(remaining) == 1
    assert remaining[0]["is_duplicate"] is False
    assert remaining[0]["sb_number_match"] is True


def test_one_unreadable_pdf_in_a_batch_does_not_block_the_rest(client):
    """A batch of 50 shouldn't fail entirely because one file is bad — the
    good ones still link, and the bad one is reported via a header instead
    of failing the whole request."""
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]

    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[
            ("files", ("sb_4444441.pdf", make_bl_pdf(_link_sb_text("4444441")), "application/pdf")),
            ("files", ("not_a_pdf.pdf", b"this is not a pdf at all", "application/pdf")),
            ("files", ("sb_4444442.pdf", make_bl_pdf(_link_sb_text("4444442")), "application/pdf")),
        ],
    )
    assert r.status_code == 201
    assert r.headers["x-failed-files"] == "not_a_pdf.pdf"

    linked = r.json()["linked_shipping_bills"]
    assert {lsb["sb_number"] for lsb in linked} == {"4444441", "4444442"}


def test_bl_first_link_accepts_multiple_files_in_one_request(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    numbers = ["2222221", "2222222", "2222223"]

    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[
            ("files", (f"sb_{n}.pdf", make_bl_pdf(_link_sb_text(n)), "application/pdf"))
            for n in numbers
        ],
    )
    assert r.status_code == 201
    linked = r.json()["linked_shipping_bills"]
    assert {lsb["sb_number"] for lsb in linked} == set(numbers)


def test_sb_fields_are_the_fixed_curated_set_and_dedups_hs_code(client):
    """There's no more "Key Details"/"All Details" choice — a linked SB's
    ``fields`` is always the one fixed set (field_catalog.SB_EXPORT_FIELDS),
    never the SB's full catalog."""
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]  # BL has no hs_code
    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("sb.pdf", make_bl_pdf(_LINK_SB), "application/pdf"))],
    )
    lsb = r.json()["linked_shipping_bills"][0]
    summary = {f["key"]: f["value"] for f in lsb["fields"]}

    # exactly the fixed set (that have values) — not the full SB catalog
    assert set(summary) <= {
        "sb_number", "sb_date", "cin_number", "cin_date", "sb_packages",
        "sb_gross_weight", "sb_field_location", "sb_destination", "shipper_code",
        "marks_and_numbers", "cargo_description", "hs_code", "exporter_name",
        "shipper_address", "leo_number", "leo_date", "gstin", "nature_of_cargo",
        "invoice_amount", "currency",
    }
    assert summary["sb_number"] == "9988776"
    assert summary["cin_number"].startswith("26PCEG07033580219700")
    assert summary["sb_packages"] == "500"
    assert "12000" in summary["sb_gross_weight"]
    assert summary["sb_field_location"] == "INNSA1"
    assert "JEBEL ALI" in summary["sb_destination"]
    assert summary["shipper_code"] == "BMMPG8728K"
    assert summary["hs_code"] == "39235090"  # BL had none -> SB's is shown
    assert "LINK TEST EXPORTS" in summary["exporter_name"]
    assert summary["nature_of_cargo"] == "PACKAGED"
    assert summary["leo_number"] == "2/9"
    # fields outside the fixed list must not leak in (e.g. consignee_name)
    assert "consignee_name" not in summary


def test_sb_fields_omit_hs_code_when_bl_already_has_one(client, bl_pdf_bytes):
    # SAMPLE_BL carries its own "HS Code: 07031019"
    bl_id = _ingest(client, bl_pdf_bytes).json()["id"]
    r = client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("sb.pdf", make_bl_pdf(_LINK_SB), "application/pdf"))],
    )
    lsb = r.json()["linked_shipping_bills"][0]
    summary = {f["key"]: f["value"] for f in lsb["fields"]}
    assert "hs_code" not in summary


def test_export_bl_with_sb_is_one_file_with_a_row_per_sb(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    for num in ("3333331", "3333332"):
        client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[("files", (f"sb_{num}.pdf", make_bl_pdf(_link_sb_text(num)), "application/pdf"))],
        )

    resp = client.get(f"/documents/{bl_id}/export-with-sb?fmt=xlsx")
    assert resp.status_code == 200 and resp.content[:2] == b"PK"
    assert "bl_sb_" in resp.headers["content-disposition"]

    wb = load_workbook(io.BytesIO(resp.content))
    # one vertical "Field"/"Value" sheet for the BL, plus one more per linked
    # SB (named by SB number) — never a tabular multi-row sheet
    assert wb.sheetnames == ["Bill of Lading", "SB 3333331", "SB 3333332"]

    bl_sheet = wb["Bill of Lading"]
    assert [c.value for c in bl_sheet[1]] == ["Field", "Value"]
    bl_fields = {r[0].value: r[1].value for r in bl_sheet.iter_rows(min_row=2)}
    assert bl_fields["B/L Number"] == "LNK/BL/001"

    sb_sheet = wb["SB 3333331"]
    assert [c.value for c in sb_sheet[1]] == ["Field", "Value"]
    sb_fields = {r[0].value: r[1].value for r in sb_sheet.iter_rows(min_row=2)}
    assert sb_fields["Shipping Bill No."] == "3333331"

    pdf = client.get(f"/documents/{bl_id}/export-with-sb?fmt=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    assert client.get(f"/documents/{bl_id}/export-with-sb?fmt=xls").status_code == 400


def test_export_bl_with_sb_has_the_fixed_field_set(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("sb.pdf", make_bl_pdf(_LINK_SB), "application/pdf"))],
    )

    resp = client.get(f"/documents/{bl_id}/export-with-sb?fmt=xlsx")
    assert resp.status_code == 200 and resp.content[:2] == b"PK"
    assert "bl_sb_" in resp.headers["content-disposition"]

    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["Bill of Lading", "SB 9988776"]
    ws = wb["SB 9988776"]
    assert [c.value for c in ws[1]] == ["Field", "Value"]  # still vertical, not tabular
    row = {r[0].value: r[1].value for r in ws.iter_rows(min_row=2)}

    assert row["Port of Loading"] == "INNSA1"
    assert row["Shipping Bill No."] == "9988776"
    assert row["No. of Packages"] == "500"
    assert "LINK TEST EXPORTS" in row["Exporter"]
    assert "JEBEL ALI" in row["Port of Discharge"]
    assert row["Nature of Cargo"] == "PACKAGED"
    assert row["HS Code"] == "39235090"
    assert row["LEO No."] == "2/9"
    assert row["IEC/BR"] == "BMMPG8728K"

    pdf = client.get(f"/documents/{bl_id}/export-with-sb?fmt=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    assert client.get(f"/documents/{bl_id}/export-with-sb?fmt=xls").status_code == 400


def test_export_bl_with_sb_excel_has_one_sheet_per_sb(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    numbers = [f"555555{i}" for i in range(6)]
    for num in numbers:
        client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[("files", (f"sb_{num}.pdf", make_bl_pdf(_link_sb_text(num)), "application/pdf"))],
        )

    resp = client.get(f"/documents/{bl_id}/export-with-sb?fmt=xlsx")
    wb = load_workbook(io.BytesIO(resp.content))

    assert wb.sheetnames[0] == "Bill of Lading"
    sb_sheets = wb.sheetnames[1:]
    assert len(sb_sheets) == len(numbers)
    assert len(set(sb_sheets)) == len(sb_sheets)  # every sheet name unique
    for name in sb_sheets:
        assert name.startswith("SB ")
        assert len(name) <= 31  # Excel's hard sheet-name limit


def test_export_bl_with_sb_requires_a_link(client, bl_pdf_bytes):
    bl_id = _ingest(client, bl_pdf_bytes).json()["id"]  # no SB uploaded/linked
    r = client.get(f"/documents/{bl_id}/export-with-sb?fmt=xlsx")
    assert r.status_code == 400


# ------------------------------------------- one list entry per BL (SBs nested)
def _link_one(client, bl_id, num):
    return client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", (f"sb_{num}.pdf", make_bl_pdf(_link_sb_text(num)), "application/pdf"))],
    )


def test_linked_shipping_bills_are_nested_under_their_bl_not_listed_separately(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    for num in ("6666661", "6666662"):
        _link_one(client, bl_id, num)
    standalone = _ingest(
        client, make_bl_pdf(_link_sb_text("7777777")), doc_type="shipping_bill"
    ).json()["id"]

    rows = {r["id"]: r for r in client.get("/uploads").json()}
    assert set(rows) == {bl_id, standalone}   # the 2 linked SBs have no rows of their own
    assert rows[bl_id]["linked_sb_count"] == 2
    assert rows[standalone]["linked_sb_count"] == 0
    assert client.get("/uploads/stats").json()["total"] == 2


def test_searching_a_shipping_bill_number_finds_the_bl_it_is_nested_under(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    _link_one(client, bl_id, "8888881")

    assert [r["id"] for r in client.get("/uploads?q=8888881").json()] == [bl_id]
    assert client.get("/uploads?q=no-such-thing").json() == []


def test_submitting_a_bl_submits_its_shipping_bills_with_it(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    _link_one(client, bl_id, "5151511")
    sb_id = client.get(f"/documents/{bl_id}").json()["linked_shipping_bills"][0]["id"]

    r = client.post("/records/submit", json={"doc_ids": [bl_id]})
    assert r.json()["submitted"] == 1                     # counts what was asked for
    assert client.get(f"/documents/{sb_id}").json()["submitted"] is True
    assert client.get("/uploads").json() == []            # nothing stranded as pending
    assert [x["id"] for x in client.get("/records").json()] == [bl_id]


def test_link_picker_only_offers_shipping_bills_not_attached_to_a_bl(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    _link_one(client, bl_id, "9999991")
    free = _ingest(
        client, make_bl_pdf(_link_sb_text("9999992")), doc_type="shipping_bill"
    ).json()["id"]

    offered = client.get("/documents", params={"doc_type": "shipping_bill", "unlinked": "true"}).json()
    assert [d["id"] for d in offered] == [free]
