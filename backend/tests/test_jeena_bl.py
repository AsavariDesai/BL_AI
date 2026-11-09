"""Adaptive JEENA house-BL parser — fixtures rebuilt from four real layouts:
SupplyX, Multitrade/Balguerie, Italsempione and WINCO (Yang Ming).
"""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import jeena_bl
from app.parsers._common import split_party


def _mk(path, rows, *, w=595, h=842):
    d = pymupdf.open()
    p = d.new_page(width=w, height=h)
    for y, cols in rows:
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)
    d.save(path)
    d.close()
    return str(path)


# --------------------------------------------------------------- SupplyX (PDF1)
def _supplyx(path):
    return _mk(path, [
        (36, [(300, "EXPRESS BILL OF LADING")]),
        (46, [(34, "Shipper"), (300, "Bill Of Lading No."), (470, "EXSND326060001")]),
        (56, [(34, "GREINER BIO-ONE GMBH")]),
        (66, [(34, "MAYBACHSTR. 2")]),
        (76, [(34, "72636 FRICKENHAUSEN")]),
        (86, [(34, "GERMANY")]),
        (110, [(34, "Consignee")]),
        (120, [(34, "JAIN BIOLOGICALS (P) LTD.")]),
        (130, [(34, "S.C.O: 77-78, 2ND FLOOR")]),
        (140, [(34, "SWASTIK VIHAR, MANSA DEVI COMPLEX,")]),
        (150, [(34, "134109 PANCHKULA, HARYANA")]),
        (160, [(34, "INDIA")]),
        (185, [(34, "Notify")]),
        (195, [(34, "SAME AS CNEE")]),
        (205, [(34, "JBPLCHD@GMAIL.COM")]),
        (215, [(34, "IEC CODE :- 2295000696")]),
        (255, [(34, "Place of Receipt"), (200, "Port of Loading")]),
        (266, [(34, "FRICKENHAUSEN"), (200, "BREMERHAVEN")]),
        (285, [(34, "Ocean Vessel"), (200, "Port of Discharge")]),
        (296, [(34, "MSC ELAINE  v.IP625R"), (200, "NHAVA SHEVA")]),
        (314, [(34, "Place of Delivery")]),
        (325, [(34, "NHAVA SHEVA")]),
        (500, [(34, "For delivery of goods please apply to:")]),
        (512, [(34, "JEENA & COMPANY")]),
        (522, [(34, "ELPHINSTONE BLDG, 1ST FLOOR")]),
        (695, [(34, "Freight payable at"), (190, "Number of Original BL's"),
               (330, "Place and date of Issue")]),
        (706, [(34, "COLLECT"), (190, "0/ZERO"), (330, "STUTTGART  05.07.2026")]),
        (760, [(34, "TOTAL: 4 CONTAINER  10.518,324 KG  249,020 CBM")]),
        (770, [(34, "HS-CODE: 39233090")]),
    ])


# ----------------------------------------------------- Multitrade / Balguerie (PDF2)
def _multitrade(path):
    # box labels are a background image; only values are real text
    return _mk(path, [
        (54, [(24, "SKEYNDOR S.L.U."), (456, "ME2611285/1"), (533, "1 of 1")]),
        (64, [(24, "LABORATORIO DE PRODUCTOS COSMETICOS")]),
        (74, [(24, "NAVAS DE TOLOSA 148")]),
        (83, [(24, "08223 TERRASA (BARCELONA) -SPAIN")]),
        (132, [(24, "EKTA COSMETICS LIMITED")]),
        (142, [(24, "A-53, OKHLA INDUSTRIAL AREA")]),
        (152, [(24, "PHASE-2, NEW DELHI-110020.")]),
        (208, [(24, "THE SAME AS CONSIGNEE")]),
        (250, [(420, "BALGUERIE GROUP")]),
        (287, [(160, "BARCELONA")]),
        (301, [(98, "Voyage-No:")]),
        (311, [(24, "HMM GREEN"), (121, "004E"), (160, "MUNDRA"),
               (300, "TUGHLAKABAD"), (473, "0 - ZERO")]),
        (334, [(451, "KGS"), (530, "CBM")]),
        (352, [(163, "19"), (185, "PALLETS COSMETICS PRODUCTS"), (472, "5.481,00")]),
        (361, [(24, "ONEU6113145 (40'HC) / ESAD84842"), (185, "HS CODE: 33049900")]),
        (369, [(24, "FCL/FCL")]),
        (411, [(185, "FREIGHT COLLECT")]),
        (420, [(185, "SHIPPED ON BOARD 05/08/26")]),
        (602, [(290, "EXPRESS BILL OF LADING")]),
        (692, [(24, "M/S . JEENA & COMPANY")]),
        (702, [(24, "JEENA HOUSE, PLOT NO 170,")]),
        (712, [(24, "ANDHERI ( E), MUMBAI - 400099")]),
        (722, [(24, "IEC:-0388086301")]),
        (732, [(24, "GSTN:- 27AAAFJ1721H2ZQ")]),
        (766, [(386, "CASTELLDEFELS"), (484, "05/08/2026")]),
        (809, [(330, "MULTITRADE SPAIN SL")]),
    ])


# ------------------------------------------------------------- Italsempione (PDF3)
def _italsempione(path):
    return _mk(path, [
        (33, [(34, "Shipper"), (287, "EXPRESS BILL OF LADING"), (490, "302927/2026/20")]),
        (50, [(34, "SILICONATURE S.p.a.")]),
        (61, [(34, "Via Nazionale, 39")]),
        (73, [(34, "31010 GODEGA DI S.URBANO TV")]),
        (85, [(34, "ITALIA")]),
        (115, [(34, "Consignee")]),
        (131, [(34, "MEDICO ELECTRODES INTERNATIONAL LTD.")]),
        (143, [(34, "UNIT-I, PLOT NO. 142A/11 & 12, NOIDA SEZ,")]),
        (154, [(34, "PHASE-II, NOIDA 201305 INDIA")]),
        (166, [(34, "TEL.:+91 120 4880 600")]),
        (195, [(34, "Notify address"), (287, "2 Notify address")]),
        (211, [(34, "SAME AS CONSIGNEE")]),
        (223, [(34, "EMAIL: EXIM@MEDICOELECTRODES.COM")]),
        (274, [(34, "Vessel"), (164, "Place of receipt"),
               (287, "For delivery of goods please apply to:")]),
        (289, [(34, "MSC HARMONY III"), (164, "GODEGA"), (287, "JEENA & COMPANY")]),
        (303, [(34, "Port of loading"), (164, "Port of discharge"),
               (287, "GALA NO.T-01 TO T-06, 3RD FLOOR,")]),
        (319, [(34, "VENEZIA"), (164, "MUNDRA")]),
        (336, [(34, "Place of delivery"), (287, "IEC: 0388086301 PAN : AAAFJ1721H")]),
        (349, [(34, "ICD DADRI")]),
        (423, [(34, "MSNU1360819")]),
        (436, [(34, "SEAL H5969349")]),
        (513, [(252, "Net Wt.: 16,434.68 KGS")]),
        (525, [(252, "HS Code: 39209999")]),
        (623, [(32, "VOY : AQ629R")]),
        (709, [(339, "Place and date of issue"), (447, "VITTUONE, 15/07/2026")]),
    ])


# --------------------------------------------------------- WINCO / Yang Ming (PDF4)
def _winco(path):
    # box labels are a background image -> only values are real text
    return _mk(path, [
        (85, [(56, "GD MIDEA HEATING & VENTILATING EQUIPMENT CO.,LTD"),
              (340, "S224003786"), (435, "GDWV26076246")]),
        (94, [(56, "MIDEA INDUSTRIAL CITY, BEIJIAO, SHUNDE, FOSHAN, GUANGDONG P.R.CHINA")]),
        (148, [(55, "CARRIER AIRCONDITIONING & REFRIGERATION LIMITED"),
               (338, "JEENA & COMPANY")]),
        (156, [(55, "92,GODOWN NO. L-1,SAIDHARA W.H. COMPLEX,MUM.-NASIK H.WAY NH3,"),
               (338, "JEENA HOUSE,PLOT NO 170,OM NAGAR,OFF PIPELINE ROAD")]),
        (165, [(55, "BHOIRGAON VILLAGE,DIST THANE, VADAPE-BHIWANDI 421302 MAHARASHTRA")]),
        (174, [(55, "PAN: AAACC8414B GSTIN: 27AAACC8414B1Z4")]),
        (214, [(54, "CARRIER AIRCONDITIONING & REFRIGERATION LIMITED")]),
        (223, [(54, "NARSINGPUR, GURGAON JAIPUR ROAD, GURGAON, HARYANA # 122001, INDIA")]),
        (232, [(54, "PAN: AAACC8414B GSTIN: 06AAACC8414B1Z8")]),
        (307, [(56, "GUI GANG FU YU 05/260807"), (195, "BEIJIAO,CHINA")]),
        (333, [(55, "NHAVA SHEVA,INDIA"), (192, "NHAVA SHEVA,INDIA"),
               (338, "CY-CY"), (460, "THREE(3)")]),
        # goods table: no heading text — marks sit BELOW the packages row, the
        # description column runs down to the container list, weights at right
        (360, [(126, "455"), (152, "CARTONS"), (194, "SHIPPER'S LOAD,COUNT &")]),
        (364, [(380, "38070.840KGS"), (457, "275.920CBM")]),
        (368, [(194, "SEAL(5x40'HQ)CONTAINERS S.T.C.")]),
        (372, [(54, "N/M")]),
        (384, [(195, "PARTS OF VRF AIR CONDITIOER")]),
        (392, [(195, "HS CODE:84159000")]),
        (400, [(195, "DUCTED INDOOR UNITS")]),
        (408, [(195, "HS CODE:84158390")]),
        (416, [(195, "INVOICE NO: MDCAZ2608030013")]),
        (424, [(195, "PO# 5400026195, 5400026196")]),
        (432, [(195, "FREE TIME 21 DAYS FREE DETENTION AT DESTINATION")]),
        (456, [(55, "CONTAINERS/SEAL NO.:")]),
        (465, [(55, "YMMU7684324/40'HQ/YMAX171940/70 CARTONS")]),
        (474, [(55, "YMMU7684319/40'HQ/YMAX171938/74 CARTONS")]),
        (519, [(389, "SHIPPED ON BOARD 2026-08-08")]),
        (634, [(67, "FREIGHT PREPAID")]),
        (680, [(377, "SHENZHEN,CHINA 2026-08-08")]),
    ])


@pytest.fixture(params=["supplyx", "multitrade", "italsempione", "winco"])
def sample(request, tmp_path):
    builder = {
        "supplyx": _supplyx, "multitrade": _multitrade,
        "italsempione": _italsempione, "winco": _winco,
    }[request.param]
    return request.param, builder(tmp_path / f"{request.param}.pdf")


def _map(path):
    return AnchorExtractor().extract(path, doc_id="j", doc_type="bill_of_lading").as_map()


def test_parser_claims_every_jeena_layout(sample):
    from app.document import load_document

    _, path = sample
    assert jeena_bl.matches(load_document(path))


EXPECT = {
    "supplyx": {
        "document_type": "Express Bill of Lading",
        "bl_number": "EXSND326060001",
        "booking_number": None,
        "shipper_name": "GREINER BIO-ONE GMBH",
        "shipper_state": "GERMANY",
        "consignee_nm": "JAIN BIOLOGICALS (P) LTD.",
        "consignee_state": "HARYANA",
        "notify_name": "SAME AS CNEE",
        "port_of_loading": "BREMERHAVEN",
        "port_of_discharge": "NHAVA SHEVA",
        "place_of_receipt": "FRICKENHAUSEN",
        "freight_payable_at": "COLLECT",
        "number_of_original_bls": "0/ZERO",
        "hs_code": "39233090",
    },
    "multitrade": {
        "document_type": "Combined Transport Bill of Lading",
        "bl_number": "ME2611285/1",
        "booking_number": None,
        "shipper_name": "SKEYNDOR S.L.U.",
        "shipper_state": "SPAIN",
        "consignee_nm": "EKTA COSMETICS LIMITED",
        "notify_name": "THE SAME AS CONSIGNEE",
        "port_of_loading": "BARCELONA",
        "port_of_discharge": "MUNDRA",
        "place_of_delivery": "TUGHLAKABAD",
        "vessel_and_voyage": "HMM GREEN 004E",
        "number_of_original_bls": "0-ZERO",
        "freight_terms": "FREIGHT COLLECT",
        "hs_code": "33049900",
        "container_and_seal_numbers": "ONEU6113145 / ESAD84842",
        "number_and_kind_of_packages": "19 PALLETS",
        "gross_weight": "5481.00 KGS",
        "marks_and_numbers": "ONEU6113145 (40'HC) / ESAD84842 FCL/FCL",
        "description_of_goods": "PALLETS COSMETICS PRODUCTS",
        "shipped_on_board_date": "2026-08-05",
        "iec_code": "0388086301",
        "gstin": "AAAFJ1721H2ZQ",
    },
    "italsempione": {
        "document_type": "Express Bill of Lading",
        "bl_number": "302927/2026/20",
        "booking_number": None,
        "shipper_name": "SILICONATURE S.p.a.",
        "shipper_state": "ITALIA",
        "consignee_nm": "MEDICO ELECTRODES INTERNATIONAL LTD.",
        "consignee_state": "INDIA",
        "notify_name": "SAME AS CONSIGNEE",
        "port_of_loading": "VENEZIA",
        "port_of_discharge": "MUNDRA",
        "place_of_delivery": "ICD DADRI",
        "place_of_receipt": "GODEGA",
        "hs_code": "39209999",
        "place_and_date_of_issue": "VITTUONE, 15/07/2026",
    },
    "winco": {
        "bl_number": "GDWV26076246",
        "booking_number": "S224003786",
        "shipper_name": "GD MIDEA HEATING & VENTILATING EQUIPMENT CO.,LTD",
        "consignee_nm": "CARRIER AIRCONDITIONING & REFRIGERATION LIMITED",
        "consignee_state": "MAHARASHTRA",
        "notify_name": "CARRIER AIRCONDITIONING & REFRIGERATION LIMITED",
        "notify_state": "HARYANA",
        "port_of_loading": "BEIJIAO,CHINA",
        "port_of_discharge": "NHAVA SHEVA,INDIA",
        "movement_type": "CY/CY",
        "freight_terms": "FREIGHT PREPAID",
        "number_of_original_bls": "THREE(3)",
        "hs_code": "84159000, 84158390",
        "shipped_on_board_date": "2026-08-08",
        "marks_and_numbers": "N/M",
        "number_and_kind_of_packages": "455 CARTONS",
        "gross_weight": "38070.840 KGS",
    },
}


def test_fields(sample):
    name, path = sample
    m = _map(path)
    for key, want in EXPECT[name].items():
        got = m.get(key)
        if want is None:
            assert not got, f"{name}.{key}: expected blank, got {got!r}"
        else:
            assert got == want, f"{name}.{key}: {got!r} != {want!r}"


def test_booking_never_equals_bl(sample):
    name, path = sample
    m = _map(path)
    if m.get("booking_number"):
        assert m["booking_number"] != m.get("bl_number")


def test_split_party_name_address_state():
    name, addr, state = split_party([
        "JAIN BIOLOGICALS (P) LTD.",
        "S.C.O: 77-78, 2ND FLOOR",
        "SWASTIK VIHAR, MANSA DEVI COMPLEX,",
        "134109 PANCHKULA, HARYANA",
        "INDIA",
        "IEC CODE :- 2295000696",
    ])
    assert name == "JAIN BIOLOGICALS (P) LTD."
    assert state == "HARYANA"
    assert "PANCHKULA" in addr and "HARYANA" not in addr and "IEC" not in addr

    name, addr, state = split_party(["GREINER BIO-ONE GMBH", "MAYBACHSTR. 2",
                                     "72636 FRICKENHAUSEN", "GERMANY"])
    assert (name, state) == ("GREINER BIO-ONE GMBH", "GERMANY")
    assert addr == "MAYBACHSTR. 2, 72636 FRICKENHAUSEN"


def test_winco_goods_table_is_read_without_any_heading_text(tmp_path):
    """Marks & Numbers, No. & kind of packages and Description of Goods all
    came back empty on the real WINCO BL: its column headings are a background
    image, so only positions and content identify the columns."""
    m = _map(_winco(tmp_path / "winco_goods.pdf"))

    assert m["marks_and_numbers"] == "N/M"              # left of, and below, the packages row
    assert m["number_and_kind_of_packages"] == "455 CARTONS"

    desc = m["description_of_goods"]
    assert desc.startswith("SHIPPER'S LOAD,COUNT & SEAL(5x40'HQ)CONTAINERS S.T.C.")
    for line in ("PARTS OF VRF AIR CONDITIOER", "HS CODE:84159000", "DUCTED INDOOR UNITS",
                 "INVOICE NO: MDCAZ2608030013", "FREE TIME 21 DAYS FREE DETENTION AT DESTINATION"):
        assert line in desc                              # nothing from the block dropped
    assert "38070" not in desc and "275.920" not in desc  # weights belong to their own columns
    assert "YMMU7684324" not in desc                     # the container list ends the table
    assert "N/M" not in desc


def test_container_count_is_not_mistaken_for_packages(tmp_path):
    path = _mk(tmp_path / "cnt.pdf", [
        (40, [(300, "JEENA & COMPANY")]),
        (333, [(55, "NHAVA SHEVA,INDIA"), (338, "CY-CY")]),
        (360, [(126, "4"), (140, "CONTAINERS"), (194, "SAID TO CONTAIN GENERAL CARGO")]),
        (456, [(55, "CONTAINERS/SEAL NO.:")]),
    ])
    assert not _map(path).get("number_and_kind_of_packages")
