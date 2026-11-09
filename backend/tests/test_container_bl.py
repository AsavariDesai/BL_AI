"""Container BL parser — fixture rebuilt from WINCO-HBL / GDWV26076246."""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import container_bl


def _pdf(path) -> str:
    d = pymupdf.open()
    p = d.new_page(width=612, height=792)

    def L(y, *cols):
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)

    L(40, (250, "BILL OF LADING FOR COMBINED TRANSPORT OR PORT TO PORT SHIPMENT"))
    L(52, (40, "WINCO GROUP LIMITED"))
    L(70, (40, "SHIPPER (Name & Address)"))
    L(82, (40, "GD MIDEA HEATING & VENTILATING EQUIPMENT CO.,LTD"))
    L(94, (40, "MIDEA INDUSTRIAL CITY, BEIJIAO, SHUNDE, FOSHAN, GUANGDONG P.R.CHINA"))
    L(70, (330, "BOOKING NO."), (470, "BL NUMBER"))
    L(82, (330, "S224003786"), (470, "GDWV26076246"))

    L(120, (40, "CONSIGNEE (Not negotiable unless Consigned TO ORDER)"))
    L(132, (40, "CARRIER AIRCONDITIONING & REFRIGERATION LIMITED"))
    L(144, (40, "92,GODOWN NO. L-1,SAIDHARA W.H. COMPLEX,MUM.-NASIK H.WAY NH3,"))
    L(156, (40, "BHOIRGAON VILLAGE,DIST THANE, VADAPE-BHIWANDI 421302 MAHARASHTRA"))
    L(168, (40, "IEC NO: 0793001561"))
    L(120, (330, "DELIVERY AGENT"))
    L(132, (330, "JEENA & COMPANY"))
    L(144, (330, "JEENA HOUSE,PLOT NO 170,OM NAGAR,OFF PIPELINE ROAD"))
    L(156, (330, "ANDHERI EAST,MUMBAI - 400099,INDIA."))
    L(168, (330, "IEC:0388086301 GSTIN:27AAAFJ1721H2ZQ"))

    L(196, (40, "NOTIFY PARTY (Name & Address)"))
    L(208, (40, "CARRIER AIRCONDITIONING & REFRIGERATION LIMITED"))
    L(220, (40, "NARSINGPUR, GURGAON JAIPUR ROAD, GURGAON, HARYANA # 122001, INDIA"))
    L(232, (40, "IEC NO: 0793001561"))

    L(258, (40, "VESSEL & VOYAGE NO."), (240, "PORT OF LOADING"), (430, "FREIGHT PAYABLE AT"))
    L(272, (40, "GUI GANG FU YU 05/260807"), (240, "BEIJIAO,CHINA"))
    L(288, (40, "PORT OF DISCHARGE"), (240, "PLACE OF DELIVERY"), (430, "TYPE OF MOVE"),
       (520, "NUMBER OF ORIGINALS"))
    L(302, (40, "NHAVA SHEVA,INDIA"), (240, "NHAVA SHEVA,INDIA"), (430, "CY-CY"),
       (520, "THREE(3)"))

    L(330, (40, "MARKS AND NUMBERS"), (150, "NUMBER OF PACKAGES"), (280, "DESCRIPTION OF GOODS"),
       (470, "GROSS WEIGHT"), (545, "MEASUREMENT"))
    L(344, (40, "N/M"), (150, "455  CARTONS"), (280, "SHIPPER'S LOAD,COUNT & SEAL(5x40'HQ)CONTAINERS S.T.C."),
       (470, "38070.840KGS 275.920CBM"))
    L(356, (280, "PARTS OF VRF AIR CONDITIOER"))
    L(368, (280, "HS CODE:84159000"))
    L(380, (280, "DUCTED INDOOR UNITS"))
    L(392, (280, "HS CODE:84158390"))
    L(404, (280, "INVOICE NO: MDCAZ2608030013"))
    L(416, (280, "PO# 5400026195, 5400026196"))
    L(428, (280, "FREE TIME 21 DAYS FREE DETENTION AT DESTINATION"))

    L(470, (40, "CONTAINERS/SEAL NO.:"))
    L(482, (40, "YMMU7684324/40'HQ/YMAX171940/70 CARTONS/7286.380KGS/56.760CBM"))
    L(494, (40, "YMMU7684319/40'HQ/YMAX171938/74 CARTONS/7455.880KGS/56.780CBM"))
    L(506, (40, "YMLU8931744/40'HQ/YMAX171935/87 CARTONS/7728.880KGS/54.150CBM"))
    L(540, (250, "SAY TOTAL FIVE(5x40'HQ)CONTAINERS ONLY"))
    L(560, (330, "SHIPPED ON BOARD 2026-08-08"))
    L(576, (330, "Place and date of issue SHENZHEN,CHINA 2026-08-08"))

    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def cbl_path(tmp_path):
    return _pdf(tmp_path / "container_bl.pdf")


def test_parser_matches(cbl_path):
    from app.document import load_document

    assert container_bl.matches(load_document(cbl_path))


def test_container_bl_fields(cbl_path):
    res = AnchorExtractor().extract(cbl_path, doc_id="c1", doc_type="bill_of_lading")
    m = res.as_map()

    assert m["document_type"] == "Container Bill of Lading"
    assert m["bl_number"] == "GDWV26076246"
    assert m["booking_number"] == "S224003786"
    assert m["movement_type"] == "CY/CY"
    assert m["number_of_original_bls"] == "THREE(3)"
    assert m["number_and_kind_of_packages"] == "455 CARTONS"
    assert m["gross_weight"] == "38070.840 KGS"
    assert m["measurement_cbm"] == "275.920 CBM"
    assert m["hs_code"] == "84159000, 84158390"          # both, from the description
    assert m["container_and_seal_numbers"].startswith("YMMU7684324/40'HQ/YMAX171940")
    assert "GD MIDEA" in (m["shipper"] or "")
    assert "CARRIER AIRCONDITIONING" in (m["consignee"] or "")
    assert "CARRIER AIRCONDITIONING" in (m["notify_party"] or "")
    assert "JEENA" in (m["delivery_agent"] or "")
    assert m["vessel_and_voyage"] == "GUI GANG FU YU 05/260807"
    assert m["port_of_loading"] == "BEIJIAO,CHINA"
    assert m["port_of_discharge"] == "NHAVA SHEVA,INDIA"
    assert m["place_of_delivery"] == "NHAVA SHEVA,INDIA"
    assert m["marks_and_numbers"] == "N/M"
