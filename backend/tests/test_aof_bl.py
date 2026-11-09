"""Parser tests against a fixture rebuilt from the real 'HBL-H680557 (1).pdf'
(AOF Cargo Multimodal Transport Bill of Lading)."""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import aof_bl


def _aof_pdf(path) -> str:
    d = pymupdf.open()
    p = d.new_page(width=612, height=792)

    def L(y, *cols):
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)

    # the real text layer starts with these stray lines, out of visual order
    L(24, (40, "N/M"), (90, "NHAVA SHEVA"), (170, "8,005.00 65.254"), (280, "KGS CBM"))
    L(48, (300, "Multimodal Transport Bill of Landing"))
    L(70, (330, "AOF CARGO LOGISTICS GUANGZHOU CO., LTD."))
    L(82, (330, "OCEAN BILL OF LADING"))
    L(70, (40, "Consignor"))
    L(82, (40, "XD THERMAL TECHNOLOGY CO., LTD"))
    L(94, (40, "903, TIANDU SOUTH BUILDING NO. 211 CHANGJIANG RD, SND"))
    L(106, (40, "SUZHOU, P.R.CHINA"))
    L(70, (330, "B/L No."), (430, "NGBNVS26080042"))
    L(84, (430, "SO. H680557"))

    L(124, (40, "Consigned to order of"))
    L(136, (40, "TO ORDER OF STANDARD CHARTERED BANK ,INDIA"))

    L(158, (40, "Notify address"))
    L(170, (40, "NOTIFY PARTY 1:"))
    L(182, (40, "JBM GREEN ENERGY SYSTEMS PRIVATE LIMITED"))
    L(194, (40, "PLOT NO. 322, SECTOR 3, PHASE-II"))
    L(206, (40, "REWARI BAWAL HARYANA INDIA"))
    L(218, (40, "NOTIFY PARTY 2:"))
    L(230, (40, "STANDARD CHARTERED BANK, INDIA"))

    L(250, (200, "Place of receipt"))
    L(264, (200, "SHANGHAI"))
    L(280, (40, "Ocean vessel"), (200, "Port of loading"))
    L(294, (40, "ZHONG GU XI AN V.2607W"), (200, "SHANGHAI"))
    L(310, (40, "Port of discharge"), (200, "Place of delivery"))
    L(324, (40, "NHAVA SHEVA"), (200, "NHAVA SHEVA"))

    L(350, (40, "Marks and numbers"), (170, "Number and kind of packages"),
       (330, "Description of goods"), (470, "Gross weight"), (545, "Measurement"))
    L(366, (40, "N/M"), (170, "45 PACKAGES"), (330, "SEE ATTACHED"),
       (470, "8,005.00 KGS"), (545, "65.254 CBM"))
    L(380, (170, "SHIPPER'S LOAD & COUNT S.T.C"), (545, "CY/CY"))

    L(430, (300, '"FREIGHT COLLECT"'))
    L(444, (300, "ON BOARD AUG.05.2026"))
    L(458, (300, "ONE (1) 20'GP AND ONE (1) 40' HIGH CUBE CONTAINERS ONLY."))
    L(472, (300, "CONT:CXDU1454061/20'GP/263773/CY/CY/13PACKAGES/1285KGS/9.126CBM"))
    L(484, (300, "SELU4309025/40'HQ/263772/CY/CY/32PACKAGES/6720KGS/56.128CBM"))

    L(520, (330, "Place and date of issue"))
    L(534, (330, "NINGBO,CHINA AUG.05.2026"))
    L(552, (330, "Number of Original"), (470, "AOF CARGO LOGISTICS NINGBO CO.,LTD"))
    L(566, (400, "THREE/3"), (470, "AS CARRIER"))
    L(590, (40, "JEENA & COMPANY"))
    L(602, (40, "JEENA HOUSE,PLOT NO 170,OM NAGAR,OFF PIPELINE ROAD ANDHERI EAST,"
                "MUMBAI - 400099,INDIA.IEC:0388086301 GSTIN:27AAAFJ1721H2ZQ"))

    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def aof_path(tmp_path):
    return _aof_pdf(tmp_path / "HBL-H680557.pdf")


def test_parser_matches(aof_path):
    from app.document import load_document

    assert aof_bl.matches(load_document(aof_path))


def test_aof_bl_fields(aof_path):
    res = AnchorExtractor().extract(aof_path, doc_id="a1", doc_type="bill_of_lading")
    m = res.as_map()

    assert m["bl_number"] == "NGBNVS26080042"
    assert m["reference_number"] == "SO H680557"
    assert "AOF CARGO LOGISTICS" in (m["carrier"] or "")
    assert m["gross_weight"] == "8,005.00 KGS"
    assert m["measurement_cbm"] == "65.254 CBM"
    assert m["number_and_kind_of_packages"].upper() == "45 PACKAGES"
    assert m["freight_terms"] == "FREIGHT COLLECT"
    assert m["movement_type"] == "CY/CY"
    assert m["shipped_on_board_date"] == "AUG.05.2026"
    assert m["number_of_original_bls"] == "THREE/3"
    assert m["iec_code"] == "0388086301"
    assert m["marks_and_numbers"] == "N/M"
    assert "CONTAINERS ONLY" in (m["total_containers"] or "")
    assert m["container_and_seal_numbers"] == "CXDU1454061/20'GP, SELU4309025/40'HQ"
    assert "JBM GREEN ENERGY" in (m["notify_party"] or "")
    assert m["notify_party_2"] and m["notify_party_2"].startswith("STANDARD CHARTERED BANK")
    assert "Place of" not in m["notify_party_2"]
    assert "JEENA" in (m["delivery_agent"] or "")
    assert "V.2607W" in (m["vessel_and_voyage"] or "")
    assert "NINGBO" in (m["place_and_date_of_issue"] or "")

    # geometric boxes
    assert "XD THERMAL TECHNOLOGY" in (m["shipper"] or "")
    assert "OCEAN BILL" not in (m["shipper"] or "")
    assert "STANDARD CHARTERED BANK" in (m["consignee"] or "")
    assert m["port_of_discharge"] == "NHAVA SHEVA"
    assert m["total_containers"].upper().startswith("ONE (1) 20'GP")
