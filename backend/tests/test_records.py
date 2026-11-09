import io
import zipfile

import pytest
from openpyxl import load_workbook

from tests.conftest import make_bl_pdf


def _ingest(client, pdf, doc_type=None):
    data = {"doc_type": doc_type} if doc_type else {}
    return client.post(
        "/ingest", data=data, files={"file": ("d.pdf", pdf, "application/pdf")}
    ).json()


def test_upload_and_submitted_pages_are_separate(client, sb_pdf_bytes):
    # a BL that doesn't cite the SB, so the two stay independent entries
    unrelated_bl = make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: PLAIN/001\nFREIGHT PREPAID\n"
    )
    sb = _ingest(client, sb_pdf_bytes)["id"]
    bl = _ingest(client, unrelated_bl)["id"]

    # both freshly ingested -> Upload page (pending), Submitted page empty
    pending = client.get("/uploads").json()
    assert {r["id"] for r in pending} == {sb, bl}
    assert all(r["submitted"] is False for r in pending)
    assert client.get("/records").json() == []
    assert client.get("/uploads/stats").json()["total"] == 2
    assert client.get("/records/stats").json()["total"] == 0

    # submit the SB -> it leaves Upload, appears in Submitted; BL stays pending
    n = client.post("/records/submit", json={"doc_ids": [sb]}).json()
    assert n == {"submitted": 1}

    assert {r["id"] for r in client.get("/uploads").json()} == {bl}
    submitted = client.get("/records").json()
    assert {r["id"] for r in submitted} == {sb}
    assert submitted[0]["submitted"] is True
    assert submitted[0]["job_id"].startswith("PDF-JOB-")
    assert submitted[0]["doc_number"] == "5778867"

    assert client.get("/uploads/stats").json()["total"] == 1
    assert client.get("/records/stats").json()["total"] == 1


def test_records_overview_shows_pending_and_submitted_together(client, sb_pdf_bytes):
    """The single Export screen's list: /records/overview, unlike /uploads and
    /records, shows every record regardless of submitted status in one call
    — no forced pending/submitted page split."""
    unrelated_bl = make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: OVERVIEW/001\nFREIGHT PREPAID\n"
    )
    sb = _ingest(client, sb_pdf_bytes)["id"]
    bl = _ingest(client, unrelated_bl)["id"]

    both = client.get("/records/overview").json()
    assert {r["id"] for r in both} == {sb, bl}

    client.post("/records/submit", json={"doc_ids": [sb]})
    still_both = client.get("/records/overview").json()
    assert {r["id"] for r in still_both} == {sb, bl}
    by_id = {r["id"]: r for r in still_both}
    assert by_id[sb]["submitted"] is True
    assert by_id[bl]["submitted"] is False

    # an explicit submitted filter still narrows it, for callers that want that
    only_pending = client.get("/records/overview", params={"submitted": False}).json()
    assert {r["id"] for r in only_pending} == {bl}


def test_records_overview_scopes_by_category(client, sb_pdf_bytes):
    """Export's overview never shows Import's Master BLs, and vice versa —
    the two top-level categories' document lists stay completely separate."""
    sb = _ingest(client, sb_pdf_bytes)["id"]
    master = client.post(
        "/documents", data={"doc_type": "master_bl"},
        files={"file": ("master.pdf", make_bl_pdf("MASTER BILL OF LADING\n"), "application/pdf")},
    ).json()["id"]

    export_ids = {r["id"] for r in client.get("/records/overview", params={"category": "export"}).json()}
    import_ids = {r["id"] for r in client.get("/records/overview", params={"category": "import"}).json()}
    assert sb in export_ids and master not in export_ids
    assert master in import_ids and sb not in import_ids

    assert client.get("/records/overview", params={"category": "nonsense"}).status_code == 400


def test_single_record_export_is_one_xlsx_file(client, sb_pdf_bytes):
    sb = _ingest(client, sb_pdf_bytes)["id"]
    client.post("/records/submit", json={"doc_ids": [sb]})

    xlsx = client.post("/records/export", json={"doc_ids": [sb], "fmt": "xlsx"})
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert xlsx.headers["content-disposition"].endswith('.xlsx"')
    wb = load_workbook(io.BytesIO(xlsx.content))
    assert wb.sheetnames == ["BL Export"]


def test_bulk_export_of_submitted_records_is_one_file_per_pdf(client, sb_pdf_bytes):
    # a BL that doesn't cite the SB, so neither auto-links and each keeps its
    # own plain single-sheet export (that combined case is covered separately)
    unrelated_bl = make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: PLAIN/002\nFREIGHT PREPAID\n"
    )
    sb = _ingest(client, sb_pdf_bytes)["id"]
    bl = _ingest(client, unrelated_bl)["id"]
    client.post("/records/submit", json={"doc_ids": [sb, bl]})

    # multiple records -> a .zip holding one .xlsx per document, never merged
    xlsx = client.post("/records/export", json={"doc_ids": [sb, bl], "fmt": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert xlsx.headers["content-type"] == "application/zip"
    assert xlsx.headers["content-disposition"].endswith('.zip"')
    assert "bl_records_2_" in xlsx.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(xlsx.content)) as zf:
        names = zf.namelist()
        assert len(names) == 2
        for name in names:
            assert name.endswith(".xlsx")
            wb = load_workbook(io.BytesIO(zf.read(name)))
            assert wb.sheetnames == ["BL Export"]  # each file covers just its own PDF

    pdf = client.post("/records/export", json={"doc_ids": [sb, bl], "fmt": "pdf"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(pdf.content)) as zf:
        assert len(zf.namelist()) == 2
        assert all(n.endswith(".pdf") for n in zf.namelist())

    assert client.post("/records/export", json={"doc_ids": [], "fmt": "xlsx"}).status_code == 400
    assert client.post(
        "/records/export", json={"doc_ids": ["nope"], "fmt": "xlsx"}
    ).status_code == 404


def test_records_search_and_filter(client, sb_pdf_bytes, bl_pdf_bytes):
    ids = [_ingest(client, sb_pdf_bytes)["id"], _ingest(client, bl_pdf_bytes)["id"]]
    client.post("/records/submit", json={"doc_ids": ids})

    # this BL cites SB 5778867, so the SB is nested inside the BL's entry:
    # searching the SB number finds the BL, and the SB has no row of its own
    assert len(client.get("/records?q=5778867").json()) == 1
    assert len(client.get("/records?doc_type=bill_of_lading").json()) == 1
    assert client.get("/records?doc_type=shipping_bill").json() == []


def test_bulk_export_includes_a_bls_linked_shipping_bills(client):
    """"Separate Excel Files" mode (the default, ``combine`` omitted/false):
    one xlsx per BL, each laid out the same horizontal way as the combined
    export — a "Bills of Lading" sheet (this one BL's row) and a "Shipping
    Bills" sheet (its linked SBs), never a sheet per SB."""
    bl_id = _ingest(client, make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: BULK/BL/001\nFREIGHT PREPAID\n"
    ))["id"]
    for num in ("6060601", "6060602"):
        client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[("files", (f"sb_{num}.pdf", make_bl_pdf(
                f"SHIPPING BILL FOR EXPORT OF GOODS\nSB No: {num}\nSB Date: 01.09.2026\n"
                "Field Location: INNSA1\nDestination: JEBEL ALI, UAE\n"
            ), "application/pdf"))],
        )
    client.post("/records/submit", json={"doc_ids": [bl_id]})

    resp = client.post("/records/export", json={"doc_ids": [bl_id], "fmt": "xlsx"})
    assert resp.status_code == 200 and resp.content[:2] == b"PK"

    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["Bills of Lading", "Shipping Bills"]  # not a sheet per SB

    bl_headers, bl_rows = _table(wb["Bills of Lading"])
    assert len(bl_rows) == 1
    assert bl_rows[0]["B/L Number"] == "BULK/BL/001"

    sb_headers, sb_rows = _table(wb["Shipping Bills"])
    assert sb_headers[0] == "BL Number"
    assert {r["Shipping Bill No."] for r in sb_rows} == {"6060601", "6060602"}
    assert all(r["BL Number"] == "BULK/BL/001" for r in sb_rows)


def test_bulk_export_uses_the_single_fixed_sb_field_set(client):
    """There's no more "Key Details"/"All Details" choice — every export uses
    the one fixed curated field set (field_catalog.SB_EXPORT_FIELDS)."""
    bl_id = _ingest(client, make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: BULK/BL/002\nFREIGHT PREPAID\n"
    ))["id"]
    client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", ("sb.pdf", make_bl_pdf(
            "SHIPPING BILL FOR EXPORT OF GOODS\nSB No: 7070701\nSB Date: 01.09.2026\n"
            "Field Location: INNSA1\nDestination: JEBEL ALI, UAE\nNature of Cargo: PACKAGED\n"
        ), "application/pdf"))],
    )
    client.post("/records/submit", json={"doc_ids": [bl_id]})

    resp = client.post("/records/export", json={"doc_ids": [bl_id], "fmt": "xlsx"})
    assert resp.status_code == 200

    wb = load_workbook(io.BytesIO(resp.content))
    sb_headers, sb_rows = _table(wb["Shipping Bills"])
    assert "Nature of Cargo" in sb_headers
    assert sb_rows[0]["Nature of Cargo"] == "PACKAGED"

    assert client.post(
        "/records/export", json={"doc_ids": [bl_id], "fmt": "xls"}
    ).status_code == 400


def _link_sb(client, bl_id, num, filename=None):
    client.post(
        f"/documents/{bl_id}/link-shipping-bill",
        data={"background": "false"},
        files=[("files", (filename or f"sb_{num}.pdf", make_bl_pdf(
            f"SHIPPING BILL FOR EXPORT OF GOODS\nSB No: {num}\nSB Date: 01.09.2026\n"
            "Field Location: INNSA1\nDestination: JEBEL ALI, UAE\nNature of Cargo: PACKAGED\n"
        ), "application/pdf"))],
    )


def _table(ws):
    """Header row (as a label list) + one dict per data row, keyed by that
    header — for asserting against a plain tabular (one row per document)
    sheet."""
    rows = list(ws.iter_rows(min_row=1))
    headers = [c.value for c in rows[0]]
    return headers, [
        {headers[i]: c.value for i, c in enumerate(r)} for r in rows[1:]
    ]


def test_combined_export_merges_multiple_bls_into_two_sheets(client):
    """``combine: true`` must produce exactly one file with exactly two
    sheets — "Bills of Lading" and "Shipping Bills" — no matter how many BLs
    or Shipping Bills are selected: one row per BL in the first, one row per
    Shipping Bill (led by its own "BL Number" column) in the second, rather
    than a sheet or section per document."""
    bl_a = _ingest(client, make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: COMBO/BL/A\nFREIGHT PREPAID\n"
    ))["id"]
    _link_sb(client, bl_a, "8080801")
    _link_sb(client, bl_a, "8080802")

    bl_b = _ingest(client, make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: COMBO/BL/B\nFREIGHT PREPAID\n"
    ))["id"]
    _link_sb(client, bl_b, "8080803")

    client.post("/records/submit", json={"doc_ids": [bl_a, bl_b]})

    resp = client.post(
        "/records/export",
        json={"doc_ids": [bl_a, bl_b], "fmt": "xlsx", "combine": True},
    )
    assert resp.status_code == 200 and resp.content[:2] == b"PK"
    assert "bl_records_combined_2_" in resp.headers["content-disposition"]

    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["Bills of Lading", "Shipping Bills"]  # exactly two sheets, always

    bl_headers, bl_rows = _table(wb["Bills of Lading"])
    assert "B/L Number" in bl_headers
    assert len(bl_rows) == 2  # one row per BL, not a block of rows each
    assert {r["B/L Number"] for r in bl_rows} == {"COMBO/BL/A", "COMBO/BL/B"}

    sb_headers, sb_rows = _table(wb["Shipping Bills"])
    assert sb_headers[0] == "BL Number"  # leading column names the parent BL
    assert "Shipping Bill No." in sb_headers
    assert len(sb_rows) == 3  # one row per SB
    by_sb = {r["Shipping Bill No."]: r for r in sb_rows}
    assert by_sb["8080801"]["BL Number"] == "COMBO/BL/A"
    assert by_sb["8080802"]["BL Number"] == "COMBO/BL/A"
    assert by_sb["8080803"]["BL Number"] == "COMBO/BL/B"


def test_combined_export_rejects_pdf(client):
    bl_id = _ingest(client, make_bl_pdf(
        "COMBINED TRANSPORT BILL OF LADING\nB/L No: COMBO/BL/C\nFREIGHT PREPAID\n"
    ))["id"]
    client.post("/records/submit", json={"doc_ids": [bl_id]})
    resp = client.post(
        "/records/export", json={"doc_ids": [bl_id], "fmt": "pdf", "combine": True},
    )
    assert resp.status_code == 400
