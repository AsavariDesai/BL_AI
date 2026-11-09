"""BL No. / SB No. must be found across different label wordings and value
placements (beside the label, on the next line, split across tokens)."""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor


def _pdf(path, lines):
    d = pymupdf.open()
    p = d.new_page()
    for x, y, t in lines:
        p.insert_text((x, y), t, fontsize=9)
    d.save(path)
    d.close()
    return str(path)


@pytest.mark.parametrize(
    "layout, expected",
    [
        ([(40, 60, "COMBINED TRANSPORT BILL OF LADING"),
          (40, 80, "B/L No: MAEU581234567"),
          (40, 100, "Shipper: ACME")], "MAEU581234567"),
        ([(40, 60, "OCEAN BILL OF LADING"),
          (40, 80, "Document No"), (40, 94, "HLCUNBO2507ABCDE"),
          (40, 120, "Port of Discharge: NHAVA SHEVA")], "HLCUNBO2507ABCDE"),
        ([(40, 60, "HOUSE BILL OF LADING"),
          (40, 80, "HBL No.   NGBNVS26080042"),
          (40, 100, "MBL No.   COSU1234567890")], "NGBNVS26080042"),
    ],
)
def test_bl_number_across_layouts(tmp_path, layout, expected):
    path = _pdf(tmp_path / "bl.pdf", layout)
    res = AnchorExtractor().extract(path, doc_id="x", doc_type="bill_of_lading")
    assert res.get("bl_number").value == expected
    assert res.get("bl_number").confidence >= 0.7


@pytest.mark.parametrize(
    "layout, expected",
    [
        ([(40, 60, "SHIPPING BILL FOR EXPORT OF GOODS"),
          (40, 80, "SB No: 5778867")], "5778867"),
        ([(40, 60, "DRAWBACK SHIPPING BILL"),
          (40, 80, "Shipping Bill No."), (40, 94, "4649477")], "4649477"),
        ([(40, 60, "SHIPPING BILL"),
          (40, 80, "S/B No   7012345   Dt. 01-JUL-2026")], "7012345"),
    ],
)
def test_sb_number_across_layouts(tmp_path, layout, expected):
    path = _pdf(tmp_path / "sb.pdf", layout)
    res = AnchorExtractor().extract(path, doc_id="x", doc_type="shipping_bill")
    assert res.get("sb_number").value == expected
    assert res.get("sb_number").confidence >= 0.7
