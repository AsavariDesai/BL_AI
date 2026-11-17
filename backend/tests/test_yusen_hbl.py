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


def _pdf_cargo_variant(path) -> str:
    """A second fixture isolating the cargo-table quirks seen on the real
    YLJ26334763 sample: a dotted tariff-style HS code, a "TWO (2) CONTAINERS
    ONLY" total-containers phrase, and a multi-line "Marks and Nos." column
    that shares its left-hand column with the container-number rows."""
    d = pymupdf.open()
    p = d.new_page(width=612, height=792)

    def L(y, *cols):
        for x, t in cols:
            p.insert_text((x, y), t, fontsize=7)

    L(16, (200, "BILL OF LADING for Multimodal Transport or Ocean Transport"))

    L(100, (40, "Container No. Seal No."))
    L(112, (40, "Marks and Nos."))
    L(124, (40, "HAKUTO"))
    L(136, (40, "OBSG-47191"))
    L(148, (40, "CASE NO. 1-10"))

    L(250, (40, "TSTU7654321"))
    L(262, (250, "HS CODE: 8524.9190"))
    L(300, (480, "TWO (2) CONTAINERS ONLY"))

    # Place of Receipt's own value ("TOKYO, JAPAN", same as the real sample)
    # recurs verbatim as Port of Loading's value a few rows down — a page-text
    # search for the value string (rather than reading it from its own
    # label's cell) would find whichever occurrence comes first, regardless
    # of which field actually asked for it.
    L(400, (40, "Pre-carriage by"), (170, "Place of Receipt"), (260, "CY"))
    L(412, (170, "TOKYO, JAPAN"))
    L(430, (40, "Port of Loading"), (170, "Port of Discharge"), (330, "Place of Delivery"))
    L(442, (40, "TOKYO, JAPAN"), (170, "PIPAVAV, INDIA"), (330, "GARHI HARSARU, INDIA"))

    # A GSTIN is built from state code + PAN + entity suffix, so the PAN's
    # own digits are a literal substring of the GSTIN printed just above it.
    L(460, (40, "IEC NO.0512052298"))
    L(472, (40, "GST NO.06AACCF0162H1Z2"))
    L(484, (40, "PAN: AACCF0162H"))

    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def cargo_variant_path(tmp_path):
    return _pdf_cargo_variant(tmp_path / "yusen_hbl_cargo.pdf")


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
    assert m["vessel_name"] == "TEST VESSEL"
    assert m["voyage_number"] == "001E"
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


def test_total_containers_handles_parenthesised_digit_and_trailing_only(cargo_variant_path):
    res = AnchorExtractor().extract(cargo_variant_path, doc_id="h2", doc_type="house_bl")
    m = res.as_map()
    assert m["total_containers"] == "TWO (2) CONTAINERS ONLY"


def test_hs_code_handles_dotted_tariff_style(cargo_variant_path):
    res = AnchorExtractor().extract(cargo_variant_path, doc_id="h3", doc_type="house_bl")
    m = res.as_map()
    assert m["hs_code"] == "8524.9190"


def test_marks_and_numbers_reads_multiline_column_and_excludes_container_no(cargo_variant_path):
    res = AnchorExtractor().extract(cargo_variant_path, doc_id="h4", doc_type="house_bl")
    m = res.as_map()
    marks = m["marks_and_numbers"] or ""
    assert "HAKUTO" in marks
    assert "OBSG-47191" in marks
    assert "CASE NO. 1-10" in marks
    assert "TSTU7654321" not in marks


def test_place_of_receipt_highlight_is_its_own_cell_not_port_of_loading(cargo_variant_path):
    res = AnchorExtractor().extract(cargo_variant_path, doc_id="h5", doc_type="house_bl")
    por = res.get("place_of_receipt")
    pol = res.get("port_of_loading")

    assert por.value and "CY" in por.value and "TOKYO" in por.value
    assert pol.value == "TOKYO, JAPAN"

    # Both values legitimately contain "TOKYO, JAPAN" — a page-wide text
    # search for that string can't tell them apart, so each field's bbox
    # must come from its own label's column, not the first match on the page.
    assert por.bbox is not None and pol.bbox is not None
    assert por.bbox[0] > pol.bbox[0] + 50  # Place of Receipt's column sits well right of Port of Loading's


def test_vessel_name_and_voyage_number_extract_and_highlight_independently(hbl_path):
    res = AnchorExtractor().extract(hbl_path, doc_id="h7", doc_type="house_bl")
    vessel = res.get("vessel_name")
    voyage = res.get("voyage_number")
    assert vessel.value == "TEST VESSEL"
    assert voyage.value == "001E"
    assert vessel.bbox is not None and voyage.bbox is not None
    assert vessel.bbox != voyage.bbox


def test_pan_highlight_is_its_own_line_not_the_gstin_line(cargo_variant_path):
    res = AnchorExtractor().extract(cargo_variant_path, doc_id="h6", doc_type="house_bl")
    pan = res.get("pan_no")
    gstin = res.get("gstin")

    assert pan.value == "AACCF0162H"
    assert gstin.value == "06AACCF0162H1Z2"

    # PAN's digits are a literal substring of the GSTIN above it — the
    # highlight must land on PAN's own line, not the GSTIN's.
    assert pan.bbox is not None and gstin.bbox is not None
    assert pan.bbox != gstin.bbox
    assert pan.bbox[1] > gstin.bbox[1]
