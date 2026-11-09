"""The cumulative Summary file (xlsx + pdf) — how each BL's linked Shipping
Bills reconcile against its own referenced numbers, plus their combined
cargo totals. Third file of the split BL/SB export (see test_export_split.py).
"""
import io

import pymupdf
from openpyxl import load_workbook

from app.export import _sum_quantities, build_summary_pdf, build_summary_xlsx


def test_sum_quantities_groups_by_unit():
    assert _sum_quantities(["500", "300"]) == "800"
    assert _sum_quantities(["12000.000 KGS", "8000.000 KGS"]) == "20000 KGS"
    assert _sum_quantities(["5 MTS", "10 KGS"]) in ("5 MTS, 10 KGS", "10 KGS, 5 MTS")
    assert _sum_quantities([None, ""]) == ""


def _entry(bl_number, **summary):
    return {"bl": {"bl_number": bl_number}, "sbs": [], "summary": summary}


def test_build_summary_xlsx_one_row_per_hs_code():
    entries = [
        _entry("ABC123", hs_items=[
            {"sb_number": "1111111", "hs_code": "39235090", "description": "PVC PIPE FITTINGS"},
            {"sb_number": "2222222", "hs_code": "73181500", "description": "STEEL BOLTS"},
        ]),
        _entry("DEF456", hs_items=[
            {"sb_number": "3333333", "hs_code": "85444299", "description": "INSULATED CABLES"},
        ]),
        _entry("GHI789", hs_items=[]),  # no HS items at all — still gets a row
    ]
    wb = load_workbook(io.BytesIO(build_summary_xlsx(entries)))
    assert wb.sheetnames == ["Summary"]
    header = [c.value for c in wb.active[1]]
    assert header == [
        "BL No", "Shipping Bill No.", "IMO Code", "UNO No", "HS Code",
        "Cargo Item Description", "No. of Packages", "Type of Packages",
    ]
    rows = [dict(zip(header, r)) for r in wb.active.iter_rows(min_row=2, values_only=True)]
    assert len(rows) == 4  # 2 + 1 + 1 (blank placeholder for GHI789)
    abc_rows = [r for r in rows if r["BL No"] == "ABC123"]
    assert len(abc_rows) == 2
    r0 = next(r for r in abc_rows if r["HS Code"] == "39235090")
    assert r0["Shipping Bill No."] == "1111111"
    assert r0["Cargo Item Description"] == "PVC PIPE FITTINGS"
    assert not r0["IMO Code"] and not r0["UNO No"]
    assert not r0["No. of Packages"] and not r0["Type of Packages"]
    r1 = next(r for r in abc_rows if r["HS Code"] == "73181500")
    assert r1["Shipping Bill No."] == "2222222"
    assert r1["Cargo Item Description"] == "STEEL BOLTS"
    def_row = next(r for r in rows if r["BL No"] == "DEF456")
    assert def_row["HS Code"] == "85444299" and def_row["Shipping Bill No."] == "3333333"
    ghi_row = next(r for r in rows if r["BL No"] == "GHI789")
    assert not ghi_row["HS Code"] and not ghi_row["Shipping Bill No."]


def test_build_summary_pdf_one_page_per_bl():
    entries = [_entry("ABC123", sb_total=2, sb_matched=2, sb_mismatched=0,
                       sb_missing=0, sb_duplicate=0, total_packages="800",
                       total_gross_weight="20000 KGS")]
    data = build_summary_pdf(entries)
    assert data[:4] == b"%PDF"
    doc = pymupdf.open(stream=data, filetype="pdf")
    assert doc.page_count == 1
    text = doc[0].get_text()
    assert "Bill of Lading: ABC123" in text
    assert "800" in text
    doc.close()
