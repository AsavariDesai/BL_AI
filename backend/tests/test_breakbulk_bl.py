"""Generic Break Bulk (Liner) BL parser — for LINER BLs that are *not* the
Global Steel Ships / PAREKH form (those are handled by gssw_bl). Fixture has a
plain BL number and the Shipping Bill No. carried inside the description block.
"""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import breakbulk_bl


def _pdf(path) -> str:
    d = pymupdf.open()
    p = d.new_page(width=612, height=792)

    def L(y, *cols):
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)

    L(40, (470, "LINER BILL OF LADING"))
    L(60, (40, "SHIPPER/EXPORTER"), (330, "BOOKING NO."), (430, "B/L NO."))
    L(72, (40, "OCEANIC BREAKBULK EXPORTS LLP"), (430, "OBX/BL/26-27/0042"))
    L(84, (40, "SURVEY NO 88, TALOJA MIDC"))
    L(108, (40, "NAVI MUMBAI, MAHARASHTRA - INDIA"))

    L(132, (40, "CONSIGNEE"))
    L(144, (40, "GULF STEEL TRADING FZE"))
    L(168, (40, "JEBEL ALI FREE ZONE, DUBAI, UAE"))

    L(204, (40, "NOTIFY PARTY"))
    L(216, (40, "SAME AS CONSIGNEE"))

    L(300, (40, "VESSEL"), (200, "FOR ON CARRIAGE TO"))
    L(312, (60, "MV STAR LILY"))
    L(288, (470, "Gross Weight  742.118 MTS"))
    L(326, (40, "PORT OF DISCHARGE"), (200, "PORT OF LOADING"))
    L(338, (40, "JEBEL ALI, UAE"), (200, "NHAVA SHEVA, INDIA"))
    L(352, (200, "PARTICULARS FURNISHED BY THE MERCHANT"))

    L(372, (40, "Marks & Numbers"), (150, "No. of Pkgs"),
       (250, "Description of Packages and Goods"))
    L(386, (40, "N/M"), (150, "310"), (250, "SAID TO CONTAIN 310 BUNDLES"))
    L(410, (250, "DESCRIPTION OF GOODS"))
    L(422, (250, "HOT ROLLED STEEL PLATES IS 2062 E250 GRADE"))
    L(446, (250, "SHIPPING BILL NO. 7712045 DT. 04.09.2026"))
    L(458, (250, "SHIPPED ON BOARD DATE: 12/09/2026"))
    L(470, (250, "FREIGHT COLLECT"))
    L(482, (250, "NET WEIGHT (MTS): 738.900 MTS"))

    L(560, (40, "Number of Original Bs/L"), (200, "Place and date of issue"))
    L(572, (40, "3"), (200, "NHAVA SHEVA, INDIA"), (330, "13 September 2026"))

    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def bbl_path(tmp_path):
    return _pdf(tmp_path / "breakbulk_bl.pdf")


def test_parser_matches(bbl_path):
    from app.document import load_document

    assert breakbulk_bl.matches(load_document(bbl_path))


def test_breakbulk_bl_fields(bbl_path):
    m = AnchorExtractor().extract(bbl_path, doc_id="b1", doc_type="bill_of_lading").as_map()

    assert m["document_type"] == "Break Bulk Bill of Lading"
    assert m["bl_number"] == "OBX/BL/26-27/0042"
    assert "OCEANIC BREAKBULK" in (m["shipper"] or "")
    assert "GULF STEEL" in (m["consignee"] or "")
    assert m["vessel_and_voyage"] == "MV STAR LILY"
    assert m["port_of_loading"] == "NHAVA SHEVA, INDIA"
    assert m["port_of_discharge"] == "JEBEL ALI, UAE"

    # break-bulk rules: values pulled from the description block
    assert m["shipping_bill_number_and_date"] == "7712045 DT. 04.09.2026"
    assert m["net_weight"] == "738.900 MTS"
    assert m["number_of_original_bls"] == "3"
    desc = m["description_of_goods"] or ""
    assert "HOT ROLLED STEEL" in desc and "apparent good order" not in desc.lower()
