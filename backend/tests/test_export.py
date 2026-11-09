import pymupdf

from app.export import _cell, _fields_html, build_pdf, build_xlsx


def test_cell_truncates_runaway_values():
    long = "x" * 5000
    out = _cell(long)
    assert out.endswith("…") and len(out) < 1000
    assert _cell("SEAMLESS CASING") == "SEAMLESS CASING"
    assert _cell(None) == ""


def test_fields_html_is_label_value_pairs_not_a_table():
    html = _fields_html({"bl_number": "ABC123"}, [("bl_number", "B/L Number")])
    assert "<table" not in html
    assert "<span class='k'>B/L Number</span>" in html
    assert "<span class='v'>ABC123</span>" in html


def test_build_pdf_renders_a_long_value_without_overlap():
    row = {
        "_file": "x.pdf",
        "bl_number": "GSSWSCO38032C",
        "description_of_goods": "SEAMLESS CASING " * 400,  # ~6 KB
    }
    data = build_pdf([row], ["bl_number", "description_of_goods"])
    assert data[:4] == b"%PDF"
    doc = pymupdf.open(stream=data, filetype="pdf")
    assert doc.page_count == 1
    text = doc[0].get_text()
    # both the label and the value are present and legible
    assert "B/L Number" in text
    assert "GSSWSCO38032C" in text
    assert "…" in text  # the long description got truncated, not spilled
    doc.close()


def test_build_xlsx_still_ok():
    data = build_xlsx([{"_file": "a.pdf", "bl_number": "X1"}], ["bl_number"])
    assert data[:2] == b"PK"
