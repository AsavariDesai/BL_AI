"""Global Steel Ships / PAREKH MARINE 'LINER BILL OF LADING' parser.

Two fixtures: the single-SB export (rebuilt from SCO38032C) and a multi-SB
export whose front page carries a full Export-Invoice / Shipping-Bill table.
"""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import gssw_bl


def _page(d, rows, *, w=612, h=792):
    p = d.new_page(width=w, height=h)
    for y, cols in rows:
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)
    return p


def _single_sb(path) -> str:
    d = pymupdf.open()
    _page(d, [
        (40, [(470, "LINER BILL OF LADING")]),
        (60, [(40, "SHIPPER/EXPORTER"), (330, "BOOKING NO."), (430, "B/L NO.")]),
        (72, [(40, "GVN FUELS LIMITED"), (430, "GSSWSCO38032C")]),
        (84, [(40, "PLOT NO. 106, SECTOR - 44")]),
        (96, [(40, "GURGAON, 122022")]),
        (108, [(40, "HARYANA - INDIA")]),
        (132, [(40, "CONSIGNEE")]),
        (144, [(40, "ARCELORMITTAL PROJECTS AMERICAS LLC,")]),
        (156, [(40, "19500 STATE HIGHWAY 249,")]),
        (168, [(40, "SUITE 650, HOUSTON TEXAS")]),
        (180, [(40, "77070, USA")]),
        (204, [(40, "NOTIFY PARTY")]),
        (216, [(40, "UTC OVERSEAS, INC / JAYNETTE (JAY JAY) KETTLER,")]),
        (228, [(40, "PHONE +1.713.422.2804,")]),
        (240, [(40, "EMAIL: J.KETTLER@UTCOVERSEAS.COM,")]),
        (300, [(40, "VESSEL"), (200, "FOR ON CARRIAGE TO")]),
        (312, [(60, "MV  SCOTER")]),
        (326, [(40, "PORT OF DISCHARGE"), (200, "PORT OF LOADING")]),
        (338, [(40, "HOUSTON PORT, USA"), (200, "MUMBAI PORT, INDIA")]),
        (352, [(200, "PARTICULARS FURNISHED BY THE MERCHANT")]),
        (372, [(40, "Marks & Numbers"), (100, "No. of Pkgs"),
               (250, "Description of Packages and Goods"), (403, "Gross Weight")]),
        (386, [(40, "PO# 10134595"), (100, "76"), (250, "SAID TO CONTAIN"),
               (366, "315.883"), (393, "MTS")]),
        (398, [(250, "76 BUNDLES CONTAINING 707 PIPES")]),
        (410, [(250, "DESCRIPTION OF GOODS")]),
        (422, [(250, "SEAMLESS CASING AS PER API 5CT PSL1 GRADE J-55. SIZE 5.5 X 0.415")]),
        (446, [(250, "CONTRACT GVN/SC/G/26-27/0031 TOLERANCES")]),
        (458, [(250, "SHIPPING TERMS: CFR HOUSTON PORT, USA (INCOTERMS 2020)")]),
        (470, [(250, "DOCUMENTARY CREDIT NUMBER : ILC26P0000012 DATED 260612")]),
        (482, [(250, "SHIPPING BILL NO. 4361813 DT. 22.06.2026")]),
        (494, [(250, "SHIPPED ON BOARD DATE: 15/07/2026")]),
        (506, [(250, "FREIGHT PREPAID")]),
        (518, [(250, "NET WEIGHT (MTS): 315.302 MTS")]),
        (530, [(250, "TOTAL NO. OF PACKAGES (in words): SEVENTY SIX ONLY.")]),
        (542, [(250, "Received the described goods said to contain goods in apparent "
                     "good order and condition. In accepting this Bill of Lading.")]),
        (560, [(40, "Number of Original Bs/L"), (200, "Place and date of issue")]),
        (572, [(40, "3"), (200, "MUMBAI, INDIA"), (330, "15 July 2026")]),
    ])
    d.save(path)
    d.close()
    return str(path)


def _multi_sb(path) -> str:
    d = pymupdf.open()
    rows = [
        (55, [(416, "LINER BILL OF LADING")]),
        (77, [(28, "SHIPPER/EXPORTER"), (268, "BOOKING NO."), (339, "B/L NO.")]),
        (85, [(28, "IMMADI E-COMMERCE PRIVATE LIMITED"), (339, "GSSWSCO38065B")]),
        (92, [(28, "D. NO: 1-6-2, MAIN ROAD, S-HEIGHTS - 3RD FLOOR"),
              (268, "EXPORT REFERENCES")]),
        (99, [(28, "CHOWDARYPET AREA, NEAR MARUTHI NAGAR ARCH, GUNTUR,")]),
        (106, [(28, "GUNTUR DISTRICT - 522006, ANDHRA PRADESH, INDIA")]),
        (116, [(28, "CONSIGNEE")]),
        (124, [(28, "UNIMACTS MANUFACTURING MX.,LLC")]),
        (132, [(28, "14600 ARVILLE STREET, SLOAN, NV 89054 USA,LAS VEGAS, NEVADA,")]),
        (139, [(28, "UNITED STATES OF AMERICA -89054. ATTN: ANTONIO SOLARI")]),
        (144, [(28, "PHONE: +1 (814) 323-0828 EMAIL: A.SOLARI@UNIMACTS.COM")]),
        (162, [(28, "NOTIFY PARTY")]),
        (170, [(28, "DGL GLOBAL LOGISTICS")]),
        (177, [(28, "3505 NW 113TH CT DORAL, FL 33178")]),
        (184, [(28, "TEL: 786-600-0893")]),
        (228, [(28, "VESSEL")]),
        (237, [(28, "MV SCOTER")]),
        (245, [(28, "PORT OF DISCHARGE"), (127, "PORT OF LOADING")]),
        (253, [(28, "HOUSTON, USA"), (127, "MUMBAI, INDIA")]),
        (261, [(190, "PARTICULARS FURNISHED BY THE MERCHANT")]),
        (269, [(28, "Marks & Numbers"), (87, "No. of Pkgs"), (214, "Description of"),
               (403, "Gross Weight")]),
        (278, [(119, "631 BUNDLES"), (300, "SHIPPING BILL NO")]),
        (282, [(119, "GALVANISED STEEL STRUCTURE (I BEAM)"),
               (300, "4454194")]),
        (291, [(28, "ZET-AJIPL- 321 TO ZET-"), (300, "4454194")]),
        (297, [(28, "AJIPL- 436")]),
        (306, [(28, "ZET-AJIPL- 465 TO ZET-"), (300, "4552951")]),
        (311, [(28, "AJIPL- 778"), (300, "4552942")]),
        (330, [(28, "ZET-KSI- 114 TO ZET-KSI- 233"), (300, "4555254")]),
        (339, [(28, "ZET-MSMS- 363 TO ZET-MSMS- 463"), (404, "1304225.000")]),
        (345, [(97, "631"), (415, "KGS"), (300, "4790007")]),
        (446, [(260, "CARRIER NAME : G2 OCEAN A/S"), (119, "PROJECT: 26 LUNS")]),
        (450, [(260, "FREIGHT PREPAID")]),
        (455, [(260, "NET WT. 1297.915 MTS")]),
        (460, [(260, "GROSS WT. 1304.225 MTS")]),
        (465, [(260, "HS CODE: 7308909590")]),
        (470, [(260, "TOTAL NO. OF PACKAGES (IN WORDS): SIX HUNDRED AND THIRTY ONE ONLY.")]),
        (694, [(28, "Number of Original Bs/L"), (94, "Place and date of issue")]),
        (700, [(28, "3"), (94, "MUMBAI, INDIA")]),
        (707, [(94, "25 July 2026")]),
        (682, [(268, "SIGNED FOR AND AUTHORITY OF THE MASTER BY PAREKH MARINE "
                     "SERVICES PVT LTD, AS AGENTS")]),
    ]
    _page(d, rows)
    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def single_path(tmp_path):
    return _single_sb(tmp_path / "gssw_single.pdf")


@pytest.fixture
def multi_path(tmp_path):
    return _multi_sb(tmp_path / "gssw_multi.pdf")


def _map(path):
    return AnchorExtractor().extract(path, doc_id="g", doc_type="bill_of_lading").as_map()


def test_parser_matches_both(single_path, multi_path):
    from app.document import load_document

    assert gssw_bl.matches(load_document(single_path))
    assert gssw_bl.matches(load_document(multi_path))


def test_single_sb_liner_bl(single_path):
    m = _map(single_path)
    assert m["document_type"] == "Liner Bill of Lading"
    assert m["bl_number"] == "GSSWSCO38032C"
    assert m["shipper_name"] == "GVN FUELS LIMITED"
    assert m["shipper_state"] == "HARYANA"
    assert m["consignee_nm"] == "ARCELORMITTAL PROJECTS AMERICAS LLC"
    assert m["consignee_state"] == "TEXAS"
    assert "UTC OVERSEAS" in (m["notify_name"] or "")
    assert m["vessel_and_voyage"] == "MV SCOTER"
    assert m["port_of_loading"] == "MUMBAI PORT, INDIA"
    assert m["port_of_discharge"] == "HOUSTON PORT, USA"
    assert m["number_and_kind_of_packages"] == "76 BUNDLES"
    assert "4361813" in (m["shipping_bill_number_and_date"] or "")
    assert m["net_weight"] == "315.302 MTS"
    assert m["gross_weight"] == "315.883 MTS"
    assert "INCOTERMS" in (m["incoterms"] or "")
    assert m["lc_number"].startswith("ILC26P0000012")
    assert m["shipped_on_board_date"] == "2026-07-15"
    assert m["number_of_original_bls"] == "3"
    desc = m["description_of_goods"] or ""
    assert "SEAMLESS CASING" in desc and "apparent good order" not in desc.lower()


def test_multi_sb_liner_bl(multi_path):
    m = _map(multi_path)
    assert m["bl_number"] == "GSSWSCO38065B"
    assert m["shipper_name"] == "IMMADI E-COMMERCE PRIVATE LIMITED"
    assert m["shipper_state"] == "ANDHRA PRADESH"
    assert "EXPORT" not in (m["shipper_addr"] or "")          # label must not bleed in
    assert m["consignee_nm"] == "UNIMACTS MANUFACTURING MX.,LLC"
    assert m["consignee_state"] == "NEVADA"
    assert m["notify_name"] == "DGL GLOBAL LOGISTICS"
    assert m["notify_state"] == "FL"
    assert m["port_of_discharge"] == "HOUSTON, USA"           # not bled with POL
    assert m["gross_weight"] == "1304.225 MTS"
    assert m["net_weight"] == "1297.915 MTS"
    assert m["hs_code"] == "7308909590"
    assert m["number_and_kind_of_packages"] == "631 BUNDLES"
    assert m["place_and_date_of_issue"] == "MUMBAI, INDIA 25 July 2026"
    # every Shipping Bill number off the front-page table
    refs = set((m["shipping_bill_number_and_date"] or "").replace(" ", "").split(","))
    assert {"4454194", "4552951", "4552942", "4790007"} <= refs


def _rider_bl(path) -> str:
    """A 2-page BL matching the real-world shape: page 1 carries the main
    content (shipper/consignee/cargo/GSTIN), page 2 is a "B/L RIDER" with
    Net Weight, Volume, Invoice numbers and the carrier's name — all of
    which must be read from wherever in the document they actually live,
    not just page 1."""
    d = pymupdf.open()
    _page(d, [
        (40, [(470, "LINER BILL OF LADING")]),
        (60, [(40, "SHIPPER/EXPORTER"), (330, "BOOKING NO."), (430, "B/L NO.")]),
        (72, [(40, "M S METALS AND STEELS PRIVATE LIMITED"), (430, "GSSWAME38867F")]),
        (84, [(40, "SURVEY NO.147/A, MADHARPAKKAM ROAD")]),
        (96, [(40, "PERIYA OBULAPURAM POST, GUMMIDIPOONDI")]),
        (108, [(40, "TIRUVALLUR, TAMILNADU, 601201")]),
        (118, [(40, "IEC: 0704023300 ; GSTIN: 33AAICS1940E1ZO")]),
        (132, [(40, "CONSIGNEE")]),
        (144, [(40, "TO ORDER")]),
        (300, [(40, "VESSEL"), (200, "PORT OF LOADING"), (380, "PORT OF DISCHARGE")]),
        (312, [(60, "AMELIE 2601"), (200, "MUMBAI, INDIA"), (380, "HOUSTON, USA")]),
        (352, [(200, "PARTICULARS FURNISHED BY THE MERCHANT")]),
        (372, [(40, "Marks & Numbers"), (100, "No. of Pkgs"),
               (250, "Description of Packages and Goods"), (403, "Gross Weight")]),
        (386, [(40, "BULK"), (100, "517"), (250, "PIERS- TRACKER PILES"),
               (403, "990200"), (430, "KGS")]),
        (410, [(250, "HS CODE : 73089090")]),
        (506, [(250, "FREIGHT PREPAID")]),
        (560, [(40, "SIGNED FOR AND ON BEHALF OF CARRIER, G2 OCEAN AS")]),
        (572, [(40, "Number of Original Bs/L"), (200, "Place and date of issue")]),
        (584, [(40, "3"), (200, "MUMBAI, INDIA"), (330, "25 AUG 2026")]),
    ])
    _page(d, [
        (40, [(470, "LINER BILL OF LADING DRAFT")]),
        (60, [(40, "B/L RIDER")]),
        (80, [(40, "PARTICULARS FURNISHED BY THE MERCHANT")]),
        # positioned in the description column (like the real rider page),
        # not the marks column at the left margin, with nothing at all in
        # the marks column — the guard this regresses against only fires
        # when marks is empty.
        (100, [(200, "SB NO'S & DATE 5043266 DT. 15.07.2026, 5136866 DT. 18.07.2026")]),
        (118, [(200, "INVOICE NO'S MSMS/EX/MAY/065 , MSMS/EX/MAY/083")]),
        (136, [(200, "NET WT. (IN KGS): 980000 KGS")]),
        (150, [(200, "VOLUME (IN CBM): 509.26 CBM")]),
        (164, [(200, "FREIGHT PREPAID")]),
    ])
    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def rider_path(tmp_path):
    return _rider_bl(tmp_path / "gssw_rider.pdf")


def test_rider_page_fields_read_from_wherever_they_live(rider_path):
    """Net Weight, Volume, Invoice numbers and Carrier only exist on the
    rider page (page 2) of this BL — and the shipper's state is written as
    one run-on word ("TAMILNADU") rather than "TAMIL NADU" — all of it must
    still be extracted and mapped to its correct field."""
    m = _map(rider_path)
    assert m["bl_number"] == "GSSWAME38867F"
    assert m["shipper_state"] == "TAMIL NADU"
    assert m["gstin"] == "33AAICS1940E1ZO"
    assert m["iec_code"] == "0704023300"
    assert m["carrier"] == "G2 OCEAN"
    assert m["net_weight"] == "980000 KGS"           # page-2-only value
    assert m["gross_weight"] == "990200 KGS"          # page-1 cargo row, unaffected
    assert m["measurement_cbm"] == "509.26 CBM"       # page-2-only value
    invoices = (m["invoice_number_and_date"] or "").replace(" ", "")
    assert "MSMS/EX/MAY/065" in invoices and "MSMS/EX/MAY/083" in invoices
    refs = set((m["shipping_bill_number_and_date"] or "").replace(" ", "").split(","))
    assert {"5043266", "5136866"} <= refs
    # the rider page's "SB NO'S & DATE" / "INVOICE NO'S" lists sit in the
    # same column position a genuine extra cargo row's description would —
    # with no real marks content on that page, they must NOT be mistaken for
    # one and appended to the page-1 cargo fields.
    assert m["marks_and_numbers"] == "BULK"
    assert m["description_of_goods"] == "PIERS- TRACKER PILES HS CODE : 73089090"


def _rider_bl_with_more_cargo(path) -> str:
    """Like ``_rider_bl``, but this time the rider page genuinely lists MORE
    cargo rows (its own Marks & Numbers / Description columns populated) —
    these must be appended to page 1's, not dropped just because they live
    on a later page."""
    d = pymupdf.open()
    _page(d, [
        (40, [(470, "LINER BILL OF LADING")]),
        (60, [(40, "SHIPPER/EXPORTER"), (330, "BOOKING NO."), (430, "B/L NO.")]),
        (72, [(40, "IMMADI E-COMMERCE PRIVATE LIMITED"), (430, "GSSWAME38867B")]),
        (84, [(40, "GUNTUR, ANDHRA PRADESH. INDIA")]),
        (132, [(40, "CONSIGNEE")]),
        (144, [(40, "TO ORDER")]),
        (300, [(40, "VESSEL"), (200, "PORT OF LOADING"), (380, "PORT OF DISCHARGE")]),
        (312, [(60, "AMELIE 2601"), (200, "MUMBAI, INDIA"), (380, "HOUSTON, USA")]),
        (352, [(200, "PARTICULARS FURNISHED BY THE MERCHANT")]),
        (372, [(40, "Marks & Numbers"), (100, "No. of Pkgs"),
               (250, "Description of Packages and Goods"), (403, "Gross Weight")]),
        (386, [(40, "ZET-ERA- 308 TO"), (100, "252"), (250, "GALVANISED STEEL"),
               (403, "528.397"), (430, "MTS")]),
        (396, [(40, "ZET-ERA- 389")]),
        (406, [(250, "STRUCTURE (I BEAM)")]),
        (416, [(250, "DETAILS PLEASE SEE ATTACHED")]),
        (506, [(250, "FREIGHT PREPAID")]),
        (572, [(40, "Number of Original Bs/L"), (200, "Place and date of issue")]),
        (584, [(40, "3"), (200, "MUMBAI, INDIA"), (330, "25 AUG 2026")]),
    ])
    _page(d, [
        (40, [(470, "LINER BILL OF LADING DRAFT")]),
        (60, [(40, "B/L RIDER")]),
        (80, [(40, "PARTICULARS FURNISHED BY THE MERCHANT")]),
        (100, [(40, "Marks & Numbers"), (100, "No. of Pkgs"),
               (250, "Description of Packages and Goods"), (403, "Gross Weight")]),
        (120, [(40, "ZET-KSI- 580 TO"), (250, "HDG-RED/DARK BLUE")]),
        (130, [(40, "ZET-KSI- 584"), (250, "HEAVY MOTOR PIER (HMP)")]),
        (160, [(40, "CARRIER NAME : G2 OCEAN AS")]),
        (174, [(40, "FREIGHT PREPAID")]),
        (188, [(40, "NET WT. 525.877 MT")]),
        (198, [(40, "GROSS WT. 528.397 MT")]),
    ])
    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def rider_cargo_path(tmp_path):
    return _rider_bl_with_more_cargo(tmp_path / "gssw_rider_cargo.pdf")


def test_rider_page_appends_genuine_extra_cargo_rows(rider_cargo_path):
    """The opposite of the guard above: when the rider page's Marks &
    Numbers column IS genuinely populated, its Description must be appended
    to page 1's rather than discarded — "DETAILS PLEASE SEE ATTACHED" on
    page 1 points directly at this continuation."""
    m = _map(rider_cargo_path)
    marks = m["marks_and_numbers"] or ""
    desc = m["description_of_goods"] or ""
    assert "ZET-ERA- 308" in marks and "ZET-KSI- 580" in marks  # page 1 + page 2
    assert "GALVANISED STEEL" in desc and "HDG-RED/DARK BLUE" in desc


def _single_page_long_rider(path) -> str:
    """The real-world shape that slipped through: a "B/L RIDER" style
    Marks&Numbers/Description table printed directly on page 1 (no separate
    front page), with FIVE mark groups and a four-sentence description that
    together run well past the old fixed 478pt cutoff, followed by a
    "PROJECT: <code>" line and an "EXPORT INVOICE NO ..." table — both of
    which must bound the table (not leak into it) without truncating any of
    the real cargo data above them."""
    d = pymupdf.open()
    _page(d, [
        (40, [(470, "LINER BILL OF LADING")]),
        (60, [(40, "SHIPPER/EXPORTER"), (330, "BOOKING NO."), (430, "B/L NO.")]),
        (72, [(40, "IMMADI E-COMMERCE PRIVATE LIMITED"), (430, "GSSWAME38900C")]),
        (84, [(40, "GUNTUR, ANDHRA PRADESH, INDIA")]),
        (132, [(40, "CONSIGNEE")]),
        (144, [(40, "TO ORDER")]),
        (300, [(40, "VESSEL"), (200, "PORT OF LOADING"), (380, "PORT OF DISCHARGE")]),
        (312, [(60, "AMELIE 2601"), (200, "MUMBAI, INDIA"), (380, "HOUSTON, USA")]),
        (352, [(200, "PARTICULARS FURNISHED BY THE MERCHANT")]),
        (372, [(40, "Marks & Numbers"), (100, "No. of Pkgs"),
               (250, "Description of Packages and Goods"), (403, "Gross Weight")]),
        (386, [(40, "ZET-KSI- 580 TO"), (250, "HDG-RED/DARK BLUE HEAVY MOTOR PIER (HMP)")]),
        (402, [(40, "ZET-KSI- 584")]),
        (418, [(40, "ZET-KSI- 627 TO"), (250, "STANDARD ARRAY PIER (SAP) - RED/RED")]),
        (434, [(40, "ZET-KSI- 684")]),
        (450, [(40, "ZET-MIC- 140 TO"), (250, "STANDARD ARRAY PIER EDGE (SAPE)")]),
        (466, [(40, "ZET-MIC- 158")]),
        (482, [(40, "ZET-MIC- 178 TO"), (250, "STANDARD MOTOR PIER (SMP) - PURPLE/RED")]),
        (498, [(40, "ZET-MIC- 235")]),
        (514, [(40, "ZET-VPL- 348 TO"), (250, "FINAL DESCRIPTION LINE - END OF GOODS")]),
        (530, [(40, "ZET-VPL- 358")]),
        (546, [(40, "PROJECT: DECOY")]),
        (562, [(40, "EXPORT INVOICE NO EXPORT INVOICE DATE SHIPPING BILL NO SB")]),
        (578, [(40, "EXP/869/26-27"), (120, "14-JUL-26"), (220, "5006887")]),
        (640, [(260, "CARRIER NAME : G2 OCEAN AS")]),
        (654, [(260, "FREIGHT PREPAID")]),
        (668, [(260, "NET WT. 525.877 MT")]),
        (682, [(260, "GROSS WT. 528.397 MT")]),
        (696, [(40, "Number of Original Bs/L"), (200, "Place and date of issue")]),
        (708, [(40, "3"), (200, "MUMBAI, INDIA"), (330, "25 AUG 2026")]),
    ])
    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def long_rider_path(tmp_path):
    return _single_page_long_rider(tmp_path / "gssw_long_rider.pdf")


def test_page1_rider_table_not_truncated_by_fixed_cutoff(long_rider_path):
    """All five mark groups and the full multi-sentence description must
    survive — not just the ones that happened to land above the old
    hardcoded 478pt row cutoff — and the trailing "PROJECT:"/export-invoice
    block must not bleed into either column."""
    m = _map(long_rider_path)
    marks = m["marks_and_numbers"] or ""
    desc = m["description_of_goods"] or ""
    for code in ("ZET-KSI- 580", "ZET-KSI- 627", "ZET-MIC- 140",
                 "ZET-MIC- 178", "ZET-VPL- 348", "ZET-VPL- 358"):
        assert code in marks, f"{code!r} missing from marks_and_numbers: {marks!r}"
    assert "PROJECT" not in marks.upper()
    assert "HDG-RED/DARK BLUE" in desc and "FINAL DESCRIPTION LINE" in desc
    assert "EXPORT INVOICE" not in desc.upper()
    assert m["gross_weight"].startswith("528.397")
