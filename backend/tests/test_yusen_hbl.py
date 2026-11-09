"""Yusen Logistics House BL parser — synthetic fixture modeled on the real
samples (BKK1287277 / YLJ26334763 / PKG00599xx / BKK1288333)."""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import yusen_hbl


def _pdf(path) -> str:
    d = pymupdf.open()
    p = d.new_page(width=612, height=792)

    def L(y, *cols):
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)

    L(16, (40, "Shipper"), (200, "BILL OF LADING for Multimodal Transport or Ocean Transport"),
      (460, "Bill No."))
    L(28, (40, "ACME EXPORTS LTD"), (250, "COPY NON-NEGOTIABLE"), (460, "TESTBL123456"))
    L(40, (40, "123 TRADE STREET"))
    L(52, (40, "SHANGHAI"))
    L(64, (40, "CHINA"))
    L(76, (40, "IEC NO: 0598765432"))
    L(88, (40, "GST NO: 27AAAAA0000A1Z5"))
    L(100, (40, "PAN NO: AAAAA1234A"))

    L(120, (40, "Consignee"))
    L(132, (40, "GLOBAL IMPORT CO LTD"))
    L(144, (40, "45 HARBOUR ROAD"))
    L(156, (40, "MAHARASHTRA"))

    L(180, (40, "Notify Party"))
    L(192, (40, "SAME AS CONSIGNEE"))
    L(204, (330, "Export/Import Reference (for the Merchant's and/or Carrier's reference only)"))

    L(230, (40, "Pre-carriage by"), (170, "Place of Receipt"))
    L(230, (220, "CY"))
    L(242, (170, "SHANGHAI, CHINA"))

    L(262, (40, "Port of Loading"), (170, "Port of Discharge"))
    L(274, (40, "SHANGHAI, CHINA"), (170, "MUMBAI, INDIA"))

    L(294, (40, "Ocean Vessel"), (230, "Voy. No."), (330, "Place of Delivery"))
    L(306, (40, "TEST VESSEL"), (230, "001E"), (330, "ICD TKD, DELHI, INDIA"))

    L(330, (250, "Description of Goods"), (440, "Gross"), (500, "Measurement"))
    L(344, (40, "TSTU1234567"), (170, "10 PLT"),
      (250, '"SHIPPER\'S LOAD AND COUNT" "SAID TO CONTAIN" TEST CARGO DESCRIPTION'),
      (440, "1000.000"), (500, "50.000"))
    L(356, (250, "HS CODE: 12345678"))

    L(380, (40, "FREIGHT COLLECT"))

    L(410, (180, "Prepaid at"), (280, "Payable at"), (380, "Place of Bill(s) Issued"))
    L(422, (280, "DESTINATION"), (380, "TESTCITY"), (460, "01-Jan-26"))
    L(434, (480, "3 (THREE)"))

    L(460, (460, "As Carrier"))
    L(472, (460, "TEST CARRIER CO., LTD."))

    L(500, (40, "For Delivery of Goods Please Apply to:"))
    L(512, (40, "TEST DELIVERY AGENT"))
    L(524, (40, "1 AGENT ROAD, MUMBAI"))

    L(560, (330, "Laden on Board Vessel"))
    L(572, (330, "Date: 01-Jan-26"))

    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def hbl_path(tmp_path):
    return _pdf(tmp_path / "yusen_hbl.pdf")


def test_parser_matches(hbl_path):
    from app.document import load_document

    assert yusen_hbl.matches(load_document(hbl_path))


def test_yusen_hbl_fields(hbl_path):
    res = AnchorExtractor().extract(hbl_path, doc_id="h1", doc_type="house_bl")
    m = res.as_map()

    assert m["document_type"] == "House Bill of Lading"
    assert m["bl_number"] == "TESTBL123456"
    assert m["bl_release_type"] == "Copy Non-Negotiable"
    assert m["carrier"] == "TEST CARRIER CO., LTD."
    assert "ACME EXPORTS" in (m["shipper_name"] or "")
    assert m["shipper_state"] == "CHINA"
    assert "GLOBAL IMPORT" in (m["consignee_nm"] or "")
    assert m["consignee_state"] == "MAHARASHTRA"
    assert m["notify_name"] == "SAME AS CONSIGNEE"
    assert m["port_of_loading"] == "SHANGHAI, CHINA"
    assert m["port_of_discharge"] == "MUMBAI, INDIA"
    assert m["place_of_delivery"] == "ICD TKD, DELHI, INDIA"
    assert m["vessel_and_voyage"] == "TEST VESSEL / 001E"
    assert m["container_and_seal_numbers"] == "TSTU1234567"
    assert m["number_and_kind_of_packages"] == "10 PLT"
    assert m["hs_code"] == "12345678"
    assert m["gross_weight"] == "1000.000 KGS"
    assert m["measurement_cbm"] == "50.000 CBM"
    assert m["freight_terms"] == "FREIGHT COLLECT"
    assert m["number_of_original_bls"] == "3(THREE)"
    assert m["shipped_on_board_date"] == "01-Jan-26"
    assert m["iec_code"] == "0598765432"
    assert m["gstin"] == "27AAAAA0000A1Z5"
    assert m["pan_no"] == "AAAAA1234A"
    assert "TEST DELIVERY AGENT" in (m["delivery_agent"] or "")
