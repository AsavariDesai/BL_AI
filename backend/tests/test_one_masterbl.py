"""Ocean Network Express ("ONE") Master BL parser — synthetic fixture built
from the exact label/value coordinates measured off the real samples
(M DENSO TEN UNO_BKK1287277..., M ITOCHU_BKK1288333..., ONEYTYOGF4006800),
the same way test_yusen_hbl.py mirrors the real Yusen House BL form.
"""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import one_masterbl


def _pdf(path) -> str:
    d = pymupdf.open()
    p = d.new_page(width=595, height=842)

    def L(y, *cols):
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)

    L(25, (200, "ORIGINAL NON NEGOTIABLE"), (480, "SEA WAYBILL"))
    # Every page of the real form repeats this sign-off at the bottom —
    # matches() looks only at page 1, so it must be present here too.
    L(768, (412, "OCEAN NETWORK EXPRESS PTE. LTD. (ONE), AS CARRIER"))
    L(61, (32, "SHIPPER/EXPORTER"), (344, "BOOKING NO."), (469, "SEA WAYBILL NO."))
    L(70, (30, "YUSEN LOGISTICS (THAILAND) CO.,LTD."),
      (342, "BKKGS7947600"), (479, "ONEYBKKGS7947600"))
    L(81, (30, "2525 ONE, TWO FYI CENTER"))
    L(102, (30, "KLONGTOEY BANGKOK 10110 THAILAND"))

    L(133, (32, "CONSIGNEE"), (344, "FORWARDING AGENT-REFERENCES"))
    L(140, (30, "YUSEN LOGISTICS (INDIA) PVT. LTD."))
    L(151, (30, "UNIT NO.511-513,5TH FLOOR,"))
    L(172, (30, "GURUGRAM, 122001, HARYANA INDIA"), (221, "CN>"))

    L(200, (32, "NOTIFY PARTY (It is agreed that no responsibility...)"))
    L(207, (30, "SAME AS CONSIGNEE"))

    L(268, (32, "PRE-CARRIAGE BY"), (188, "PLACE OF RECEIPT"))
    L(277, (186, "LAEM CHABANG, THAILAND"))

    L(289, (32, "OCEAN VESSEL VOYAGE NO. FLAG"), (188, "PORT OF LOADING"),
      (344, "FINAL DESTINATION(for the Merchant's reference only)"))
    L(296, (30, "BROOKLYN BRIDGE 0184W"), (186, "LAEM CHABANG, THAILAND"))

    L(314, (33, "PORT OF DISCHARGE"), (188, "PLACE OF DELIVERY"),
      (342, "TYPE OF MOVEMENT(IF MIXED, USE DESCRIPTION OF PACKAGES AND GOODS FIELD)"))
    L(322, (30, "PIPAVAV, INDIA"), (186, "ICD GARHI HARSARU, INDIA"),
      (342, "FCL / FCL"), (511, "CY / CY"))

    L(362, (27, "NYKU0842991"), (128, "THBV14490"))
    L(390, (30, "DENSO TEN UNO"), (189, "38"), (217, "SHIPPER'S LOAD & COUNT/STC."),
      (457, "5505.000KGS"), (537, "66.530CBM"))
    L(401, (30, "MINDA INDIA"), (159, "PALLETS"))
    L(422, (217, "HS. CODE: 85299030"))

    L(546, (30, "FREIGHT & CHARGES PAYABLE AT / BY:"), (232, "SERVICE"), (255, "CONTRACT"),
      (284, "NO."))
    L(556, (28, "BANGKOK"))
    L(558, (223, "R00000568F8"))
    L(549, (491, "[0] ORIGINAL BILLS(S) HAVE"))

    L(624, (491, "DATE LADEN ON BOARD"))
    L(631, (490, "23 AUG 2026"))
    L(645, (491, "PLACE OF BILL(S) ISSUE"))
    L(653, (489, "BANGKOK"))
    L(667, (491, "DATED"))
    L(674, (489, "23 AUG 2026"))

    # Page 2: freight terms and the carrier sign-off, exactly as the real
    # form carries them — on the cargo-detail continuation page, not page 1.
    p2 = d.new_page(width=595, height=842)
    p2.insert_text((30, 650), "FREIGHT COLLECT", fontsize=7)
    p2.insert_text((366, 726), "OCEAN NETWORK EXPRESS PTE. LTD. (ONE), AS CARRIER", fontsize=7)

    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def masterbl_path(tmp_path):
    return _pdf(tmp_path / "one_masterbl.pdf")


def test_parser_matches(masterbl_path):
    from app.document import load_document

    assert one_masterbl.matches(load_document(masterbl_path))


def test_one_masterbl_fields(masterbl_path):
    res = AnchorExtractor().extract(masterbl_path, doc_id="m1", doc_type="master_bl")
    m = res.as_map()

    assert m["document_type"] == "Sea Waybill"
    assert m["bl_number"] == "ONEYBKKGS7947600"
    assert m["booking_number"] == "BKKGS7947600"
    assert m["bl_release_type"] == "Original Non-Negotiable"
    assert "YUSEN LOGISTICS (THAILAND)" in (m["shipper_name"] or "")
    assert "YUSEN LOGISTICS (INDIA)" in (m["consignee_nm"] or "")
    assert "CN>" not in (m["consignee"] or "")  # the hidden box marker is stripped
    assert m["notify_name"] == "SAME AS CONSIGNEE"
    assert m["place_of_receipt"] == "LAEM CHABANG, THAILAND"
    assert m["vessel_and_voyage"] == "BROOKLYN BRIDGE 0184W"
    assert m["port_of_loading"] == "LAEM CHABANG, THAILAND"
    assert m["port_of_discharge"] == "PIPAVAV, INDIA"
    assert m["place_of_delivery"] == "ICD GARHI HARSARU, INDIA"
    assert m["movement_type"] == "FCL/FCL CY/CY"
    assert m["container_and_seal_numbers"] == "NYKU0842991"
    assert m["number_and_kind_of_packages"] == "38 PALLETS"
    assert m["gross_weight"] == "5505.000 KGS"
    assert m["measurement_cbm"] == "66.530 CBM"
    assert m["hs_code"] == "85299030"
    assert m["freight_payable_at"] == "BANGKOK"
    assert m["service_contract_number"] == "R00000568F8"
    assert m["number_of_original_bls"] == "0"
    assert m["shipped_on_board_date"] == "23 AUG 2026"
    assert m["place_and_date_of_issue"] == "BANGKOK, 23 AUG 2026"
    assert m["freight_terms"] == "FREIGHT COLLECT"
    assert m["carrier"] == "Ocean Network Express Pte. Ltd. (ONE), AS CARRIER"


def test_fingerprint_is_scoped_separately_from_export_bl(masterbl_path):
    """Learned corrections for an Export-side Bill of Lading must never
    leak into Master BL extraction (or vice versa) just because the
    generic title detector sees "Bill of Lading" boilerplate in both."""
    res = AnchorExtractor().extract(masterbl_path, doc_id="m1", doc_type="master_bl")
    assert res.detected_format == "Master Bill Of Lading"
