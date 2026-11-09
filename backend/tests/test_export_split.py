"""/records/export-split — one .zip with three separate files: BL Data,
BL + Shipping Bill, and Summary. Works for xlsx and pdf, for a single BL or
several, and the download is always a .zip either way.
"""
import io
import zipfile

import pymupdf
from openpyxl import load_workbook

from tests.conftest import make_bl_pdf
from tests.test_pipeline import _LINK_BL, _ingest


def _sb_text(number: str, cin_suffix: str, packages: str, weight: str) -> str:
    return f"""SHIPPING BILL FOR EXPORT OF GOODS
SB No: {number}
SB Date: 10.09.2026
CIN No: 26PCEG0703358{cin_suffix} DT 03-JUL-26
No of Packages: {packages}
Gross Weight: {weight} KGS
Field Location: INNSA1
Destination: JEBEL ALI, UAE
Shipper Code: BMMPG8728K
HS Code: 39235090
Exporter Name: LINK TEST EXPORTS
Nature of Cargo: PACKAGED
"""


def _two_bls_with_sbs(client):
    bl1 = _ingest(client, make_bl_pdf(_LINK_BL.replace("LNK/BL/001", "LNK/BL/A"))).json()["id"]
    bl2 = _ingest(client, make_bl_pdf(_LINK_BL.replace("LNK/BL/001", "LNK/BL/B"))).json()["id"]
    for bl_id, num in ((bl1, "1111111"), (bl2, "2222222")):
        client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[(
                "files",
                (f"sb_{num}.pdf", make_bl_pdf(_sb_text(num, num[-3:], "100", "5000.000")), "application/pdf"),
            )],
        )
    return bl1, bl2


def test_export_split_xlsx_three_files_horizontal(client):
    bl1, bl2 = _two_bls_with_sbs(client)

    resp = client.post("/records/export-split", json={"doc_ids": [bl1, bl2], "fmt": "xlsx"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "bl_records_2_" in resp.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert len(names) == 3
    bl_file = next(n for n in names if n.startswith("bl_data_"))
    bl_sb_file = next(n for n in names if n.startswith("bl_shipping_bills_"))
    summary_file = next(n for n in names if n.startswith("summary_"))

    # BL Data: one sheet, one horizontal row per BL, full BL catalog as columns
    bl_wb = load_workbook(io.BytesIO(zf.read(bl_file)))
    assert bl_wb.sheetnames == ["Bills of Lading"]
    ws = bl_wb.active
    header = [c.value for c in ws[1]]
    assert "B/L Number" in header and "Shipper — Name" in header and "Gross Weight" in header
    bl_rows = {dict(zip(header, r))["B/L Number"] for r in ws.iter_rows(min_row=2, values_only=True)}
    assert bl_rows == {"LNK/BL/A", "LNK/BL/B"}

    # BL + Shipping Bill: a single worksheet, only SB data, BL Number leading
    # each row — the BL's own details are not repeated here.
    bl_sb_wb = load_workbook(io.BytesIO(zf.read(bl_sb_file)))
    assert bl_sb_wb.sheetnames == ["Shipping Bills"]
    sb_ws = bl_sb_wb.active
    sb_header = [c.value for c in sb_ws[1]]
    assert sb_header[0] == "BL Number"
    assert "Shipping Bill No." in sb_header and "CIN No." in sb_header
    sb_rows = [dict(zip(sb_header, r)) for r in sb_ws.iter_rows(min_row=2, values_only=True)]
    assert {r["BL Number"] for r in sb_rows} == {"LNK/BL/A", "LNK/BL/B"}
    assert {r["Shipping Bill No."] for r in sb_rows} == {"1111111", "2222222"}

    # Summary: one row per unique HS code, tagged with its Shipping Bill No.
    summary_wb = load_workbook(io.BytesIO(zf.read(summary_file)))
    assert summary_wb.sheetnames == ["Summary"]
    summary_header = [c.value for c in summary_wb.active[1]]
    assert summary_header == [
        "BL No", "Shipping Bill No.", "IMO Code", "UNO No", "HS Code",
        "Cargo Item Description", "No. of Packages", "Type of Packages",
    ]
    summary_rows = [
        dict(zip(summary_header, r))
        for r in summary_wb.active.iter_rows(min_row=2, values_only=True)
    ]
    assert len(summary_rows) == 2
    assert {r["BL No"] for r in summary_rows} == {"LNK/BL/A", "LNK/BL/B"}
    assert all(r["HS Code"] == "39235090" for r in summary_rows)
    assert {r["Shipping Bill No."] for r in summary_rows} == {"1111111", "2222222"}
    assert all(not r["IMO Code"] and not r["No. of Packages"] for r in summary_rows)


def test_export_split_summary_keeps_every_sb_even_with_duplicate_or_missing_hs_code(client):
    """A BL can have several linked Shipping Bills that happen to share an
    identical HS code/description (real cargo often repeats across
    shipments), or one with no HS code extracted at all. Every linked SB
    must still get its own row in the Summary — none should silently
    disappear because its (HS code, description) was already "seen" on an
    earlier SB, or because it has no HS code at all.
    """
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    dup_text = _sb_text("1111111", "100", "100", "5000.000")
    no_hs_text = (
        "SHIPPING BILL FOR EXPORT OF GOODS\nSB No: 3333333\nSB Date: 10.09.2026\n"
        "CIN No: 26PCEG0703358300 DT 03-JUL-26\nNo of Packages: 100\n"
        "Gross Weight: 5000.000 KGS\nField Location: INNSA1\n"
        "Destination: JEBEL ALI, UAE\nShipper Code: BMMPG8728K\n"
        "Exporter Name: LINK TEST EXPORTS\nNature of Cargo: PACKAGED\n"
    )
    for num, text in (
        ("1111111", dup_text),
        ("2222222", _sb_text("2222222", "200", "100", "5000.000")),
        ("3333333", no_hs_text),
    ):
        client.post(
            f"/documents/{bl_id}/link-shipping-bill",
            data={"background": "false"},
            files=[("files", (f"sb_{num}.pdf", make_bl_pdf(text), "application/pdf"))],
        )

    resp = client.post("/records/export-split", json={"doc_ids": [bl_id], "fmt": "xlsx"})
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    summary_file = next(n for n in zf.namelist() if n.startswith("summary_"))
    summary_wb = load_workbook(io.BytesIO(zf.read(summary_file)))
    header = [c.value for c in summary_wb.active[1]]
    rows = [dict(zip(header, r)) for r in summary_wb.active.iter_rows(min_row=2, values_only=True)]

    assert {r["Shipping Bill No."] for r in rows} == {"1111111", "2222222", "3333333"}
    assert all(r["HS Code"] == "39235090" for r in rows if r["Shipping Bill No."] in ("1111111", "2222222"))
    no_hs_row = next(r for r in rows if r["Shipping Bill No."] == "3333333")
    assert not no_hs_row["HS Code"] and not no_hs_row["Cargo Item Description"]


def test_export_split_pdf_three_files(client):
    bl1, bl2 = _two_bls_with_sbs(client)

    resp = client.post("/records/export-split", json={"doc_ids": [bl1, bl2], "fmt": "pdf"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert len(names) == 3
    bl_file = next(n for n in names if n.startswith("bl_data_") and n.endswith(".pdf"))
    bl_sb_file = next(n for n in names if n.startswith("bl_shipping_bills_") and n.endswith(".pdf"))
    summary_file = next(n for n in names if n.startswith("summary_") and n.endswith(".pdf"))

    bl_pdf = pymupdf.open(stream=zf.read(bl_file), filetype="pdf")
    assert bl_pdf.page_count == 2  # one page per BL
    assert "LNK/BL/A" in bl_pdf[0].get_text() or "LNK/BL/A" in bl_pdf[1].get_text()
    bl_pdf.close()

    bl_sb_pdf = pymupdf.open(stream=zf.read(bl_sb_file), filetype="pdf")
    assert bl_sb_pdf.page_count == 4  # 2 BL pages + 2 SB pages
    bl_sb_pdf.close()

    summary_pdf = pymupdf.open(stream=zf.read(summary_file), filetype="pdf")
    assert summary_pdf.page_count == 2  # one page per BL
    summary_pdf.close()


def test_export_split_single_bl_still_produces_a_zip(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    resp = client.post("/records/export-split", json={"doc_ids": [bl_id]})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert len(zf.namelist()) == 3


def test_export_split_requires_a_bill_of_lading(client):
    sb_id = _ingest(
        client, make_bl_pdf("SHIPPING BILL FOR EXPORT OF GOODS\nSB No: 1234567\n"),
        doc_type="shipping_bill",
    ).json()["id"]
    resp = client.post("/records/export-split", json={"doc_ids": [sb_id]})
    assert resp.status_code == 400


def test_export_split_rejects_bad_format(client):
    bl_id = _ingest(client, make_bl_pdf(_LINK_BL)).json()["id"]
    resp = client.post("/records/export-split", json={"doc_ids": [bl_id], "fmt": "docx"})
    assert resp.status_code == 400
