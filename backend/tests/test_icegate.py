"""Parser tests against a fixture rebuilt from the real sb4649477.pdf text layer
(14-page ICEGATE "LET EXPORT COPY"): top grid + right-of-label + below-label
value placements, values wrapping lines, and duplicate HS codes across pages.
"""
import pymupdf
import pytest

from app.extraction.anchor_extractor import AnchorExtractor
from app.parsers import icegate_sb


def _icegate_pdf(path) -> str:
    d = pymupdf.open()

    def L(page, y, *cols):
        for x, t in cols:
            page.insert_text((x, y), t, fontsize=7)

    def grid(page):
        L(page, 40, (150, "INDIAN CUSTOMS EDI SYSTEM"))
        L(page, 62, (405, "Port Code"), (460, "SB No"), (515, "SB Date"))
        L(page, 74, (405, "INBOM1"), (462, "4649477"), (513, "01-JUL-26"))
        L(page, 86, (405, "IEC/Br"), (452, "0797000119"), (545, "8"))
        L(page, 98, (405, "GSTIN/TYPE"), (470, "27AAACK7297E3Z9 GSN"))
        L(page, 110, (405, "CB CODE"), (470, "AAACP9522HCH001"))
        L(page, 122, (405, "TYPE"), (475, "INV"), (510, "ITEM"), (548, "CONT"))
        L(page, 134, (405, "Nos"), (478, "4"), (512, "10"), (550, "0"))
        L(page, 146, (405, "PKG"), (450, "71"), (475, "G.WT"), (505, "MTS"), (530, "132.44"))
        L(page, 166, (250, "NEW CUSTOM HOUSE, BALLARD ESTATE, MUMBAI - 400038"))

    p1 = d.new_page(width=612, height=792)
    grid(p1)
    L(p1, 200, (48, "1.MODE"), (95, "2.ASSESS"), (300, "6.DBK"), (345, "7.RODTP"))
    L(p1, 212, (48, "SEA"), (98, "N"), (302, "Y"), (348, "Y"))
    L(p1, 224, (48, "12.PORT OF LOADING"), (170, "INBOM1 (Mumbai (Ex Bombay))"),
       (330, "13.COUNTRY OF FINALDESTINATION"), (500, "UNITED STATES"))
    L(p1, 236, (48, "14.STATE OF ORIGIN"), (170, "Maharashtra"),
       (330, "15.PORT OF FINAL DESTINATION"), (500, "USHOU (Houston)"))
    L(p1, 248, (48, "16.PORT OF DISCHARGE"), (170, "USHOU (Houston)"),
       (330, "17.COUNTRY OF DISCHARGE"), (500, "UNITED STATES"))

    L(p1, 272, (48, "1.EXPORTER'S NAME & ADDRESS"), (330, "7.CONSIGNEE NAME & ADDRESS"))
    L(p1, 284, (48, "KIRLOSKAR FERROUS INDUSTRIES LTD"), (330, "TO THE"))
    L(p1, 296, (48, "B 13 MIDC"), (330, "BAOWIN STEEL LLC"))
    L(p1, 308, (330, "2901 WILCREST ROAD, SUITE 235, HOUS TON,TX 77042, USA. HOUS"))
    L(p1, 320, (48, "BARAMATI"), (200, "2.Type"), (240, "Private"), (330, "US"))
    L(p1, 332, (48, "3. AD CODE:"), (110, "6390007"),
       (330, "8. GSTIN / TYPE"), (500, "27AAACK7297E3Z9 GSN"))

    # I. ANNEX — value row is ABOVE the label row
    L(p1, 372, (48, "WAREHOUSE SEALED"), (200, "PACKAGED"), (360, "71"), (450, "0"), (520, "71"))
    L(p1, 384, (48, "1.SEAL TYPE"), (200, "2.NATURE OF CARGO"), (360, "3.NO. OF PACKETS"),
       (450, "4.NO. OF CONTAINERS"))
    L(p1, 414, (48, "6.MARKS & NUMBERS"),
       (150, 'AS PER INVOICE ("WE INTEND TO CLAIM REWARDS UNDER REMISSION OF DUTIES '
             'AND TAXES ON EXPORTED PRODUCTS (RoDTEP)" INV. NO. 353271100030'))

    # E. MANIFEST — CIN: labels row, values row BELOW, column-aligned
    L(p1, 428, (48, "4. CIN NO."), (200, "5. CIN DT."), (330, "6. CIN SITE ID"))
    L(p1, 440, (48, "26PCEG07033580219700"), (200, "03-JUL-26"), (330, "INBOM1"))

    # E. MANIFEST — Invoice Amount / Currency: labels row, values row BELOW
    L(p1, 452, (350, "3. INV AMT."), (450, "4.CURRENCY"))
    L(p1, 462, (350, "44795.28"), (450, "USD"))

    # J. PROCESS — LEO: value BESIDE the label
    L(p1, 470, (48, "1.EVENT"), (170, "2.DATE"), (260, "3.TIME"), (340, "4.LEO NO."), (500, "1/6"))
    L(p1, 482, (48, "5.Submission"), (170, "01-JUL-26"), (260, "12:10"),
       (340, "6.LEO Date."), (500, "03-JUL-26"))
    L(p1, 494, (48, "9.LEO"), (170, "03-JUL-26"), (260, "14:28"),
       (340, "12.Vessel Name"), (500, "LADY R"))

    # PART II / III — invoice item rows with HS codes on later pages
    p2 = d.new_page(width=612, height=792)
    grid(p2)
    L(p2, 200, (48, "PART - II - INVOICE DETAILS"))
    L(p2, 220, (48, "1.ItemSNo"), (95, "2.HS CD"), (160, "3.DESCRIPTION"), (430, "4.QUANTITY"))
    L(p2, 234, (48, "1"), (95, "73043919"),
       (160, "(TUBES/PIPES SEAMLESS OF IRON OR STEEL NON ALLOY HOT FINISHED UP TO "
             "114.3 MM O UTER DIAMETER) SEAMLESS STEEL TUBE SIZE"), (430, "3423.107"))
    L(p2, 262, (48, "2"), (95, "73043919"),
       (160, "(TUBES/PIPES SEAMLESS OF IRON OR STEEL NON ALLOY HOT FINISHED UP TO "
             "114.3 MM O UTER DIAMETER) SEAMLESS STEEL TUBE SIZE"), (430, "3717.1"))

    p3 = d.new_page(width=612, height=792)
    grid(p3)
    L(p3, 220, (48, "1"), (95, "73043929"),
       (160, "(TUBES/PIPES SEAMLESS OF IRON OR STEEL N ON ALLOY HOT FINISHED ABOVE "
             "114.3 MM bu t up to 219.1mm outer) SEAMLESS STEEL T"), (430, "1701.837"))

    d.save(path)
    d.close()
    return str(path)


@pytest.fixture
def icegate_path(tmp_path):
    return _icegate_pdf(tmp_path / "sb4649477.pdf")


def test_parser_matches(icegate_path):
    from app.document import load_document

    assert icegate_sb.matches(load_document(icegate_path))


def test_icegate_real_layout(icegate_path):
    res = AnchorExtractor().extract(icegate_path, doc_id="ic1", doc_type="shipping_bill")
    m = res.as_map()

    assert m["sb_number"] == "4649477"
    assert m["sb_field_location"] == "INBOM1"
    assert m["sb_date"] and "JUL" in m["sb_date"].upper()
    assert m["sb_packages"] == "71"
    assert m["sb_gross_weight"] == "132.44 MTS"

    assert m["shipper_code"] == "0797000119"          # IEC/Br, from the running header
    assert m["exporter_name"] == "KIRLOSKAR FERROUS INDUSTRIES LTD"
    assert "MIDC" in (m["shipper_address"] or "") and "BARAMATI" in (m["shipper_address"] or "")
    assert m["consignee_name"] == "BAOWIN STEEL LLC"
    assert "WILCREST" in (m["consignee_address"] or "")
    assert "TO THE" not in (m["consignee_name"] or "").upper()

    assert "USHOU" in (m["sb_destination"] or "") and "UNITED STATES" in (m["sb_destination"] or "")
    assert m["cin_number"] == "26PCEG07033580219700"
    assert m["cin_date"] and "JUL-26" in m["cin_date"]
    assert m["leo_number"] == "1/6"
    assert m["leo_date"] and "JUL" in m["leo_date"].upper()
    assert m["nature_of_cargo"] == "PACKAGED"

    assert m["gstin"] == "27AAACK7297E3Z9"
    assert m["marks_and_numbers"] and "AS PER INVOICE" in m["marks_and_numbers"]
    assert m["invoice_amount"] == "44795.28"
    assert m["currency"] == "USD"

    codes = (m["hs_code"] or "").split(", ")
    assert codes == ["73043919", "73043929"]              # unique, both, no dup
    desc = m["cargo_description"] or ""
    assert "TUBES" in desc
    # the HS code lives only in its own field now, never folded into Description
    assert "73043919" not in desc and "73043929" not in desc

    # nothing leaked from the generic pass — every populated field is a real value
    junk = [f.key for f in res.fields if f.value and f.value.upper() in ("SB DATE", "IEC/BR")]
    assert junk == []


def test_template_fields_get_a_real_page_and_bbox_for_pdf_viewer_highlighting(icegate_path):
    """Template parsers (icegate_sb etc.) build values via regex/geometry, not
    individual token references, so the extractor has to locate each value's
    text again afterward — otherwise clicking a field never highlights
    anything, and worse, every field falsely claims to be on page 1."""
    res = AnchorExtractor().extract(icegate_path, doc_id="ic1", doc_type="shipping_bill")
    by_key = {f.key: f for f in res.fields}

    sb_no = by_key["sb_number"]
    assert sb_no.page == 1
    assert sb_no.bbox and len(sb_no.bbox) == 4

    # this fixture's HS codes only appear starting on page 2 — a field whose
    # value is introduced there must not be falsely claimed as page 1.
    assert by_key["hs_code"].page == 2
    assert by_key["hs_code"].bbox

    # sb_gross_weight is reported as "<value> <unit>" but the grid prints it
    # unit-first ("G.WT MTS 132.44") and sb_packages is a bare 1-2 digit
    # number — both defeat a literal page-text search, so icegate_sb carries
    # each one's own grid-cell bbox directly (see _pkg_gross) rather than
    # leaving the PDF viewer with nothing to highlight.
    weight = by_key["sb_gross_weight"]
    assert weight.value == "132.44 MTS"
    assert weight.page == 1 and weight.bbox and len(weight.bbox) == 4

    packages = by_key["sb_packages"]
    assert packages.value == "71"
    assert packages.page == 1 and packages.bbox and len(packages.bbox) == 4


def _icegate_with_buyer_pdf(path) -> str:
    """Page 1's "7.CONSIGNEE NAME & ADDRESS" is the B/L consignee — on a
    negotiable shipment that's just "TO ORDER" + a country, not a company.
    Page 2's "2.BUYER'S NAME & ADDRESS" (invoice terms) carries the real
    buyer and must be preferred over it."""
    d = pymupdf.open()

    def L(page, y, *cols):
        for x, t in cols:
            page.insert_text((x, y), t, fontsize=7)

    p1 = d.new_page(width=612, height=792)
    L(p1, 40, (150, "INDIAN CUSTOMS EDI SYSTEM"))
    L(p1, 62, (405, "Port Code"), (460, "SB No"), (515, "SB Date"))
    L(p1, 74, (405, "INBOM1"), (462, "4649477"), (513, "01-JUL-26"))
    L(p1, 272, (48, "1.EXPORTER'S NAME & ADDRESS"), (330, "7.CONSIGNEE NAME & ADDRESS"))
    L(p1, 284, (48, "KIRLOSKAR FERROUS INDUSTRIES LTD"), (330, "TO ORDER"))
    L(p1, 296, (48, "B 13 MIDC"), (330, "U.S.A"))

    p2 = d.new_page(width=612, height=792)
    L(p2, 40, (150, "INDIAN CUSTOMS EDI SYSTEM"))
    L(p2, 272, (48, "1.EXPORTER'S NAME & ADDRESS"), (330, "2.BUYER'S NAME & ADDRESS"))
    L(p2, 284, (48, "KIRLOSKAR FERROUS INDUSTRIES LTD"), (330, "PCL SOLAR CONSTRUCTORS USA INC."))
    L(p2, 296, (330, "MIRANDA SOLAR TLLDEN, TX 78072."))
    L(p2, 308, (48, "B 13 MIDC"), (330, "3.THIRD PARTY NAME & ADDRESS"))

    d.save(path)
    d.close()
    return str(path)


def test_consignee_prefers_page_2_buyer_block_over_page_1_to_order(tmp_path):
    path = _icegate_with_buyer_pdf(tmp_path / "buyer.pdf")
    res = AnchorExtractor().extract(path, doc_id="ic2", doc_type="shipping_bill")
    m = res.as_map()

    assert m["consignee_name"] == "PCL SOLAR CONSTRUCTORS USA INC."
    assert "MIRANDA SOLAR TLLDEN" in (m["consignee_address"] or "")
    assert "TO ORDER" not in (m["consignee_name"] or "")


def _generic_sb_pdf(path) -> str:
    """A Shipping Bill that does NOT carry any of the ICEGATE template's own
    header markers — ``icegate_sb.matches()`` must return False for it, so
    its fields come from the generic label-anchor pass, not the template's
    own grid reader."""
    d = pymupdf.open()

    def L(page, y, *cols):
        for x, t in cols:
            page.insert_text((x, y), t, fontsize=7)

    p1 = d.new_page(width=612, height=792)
    L(p1, 40, (48, "SHIPPING BILL FOR EXPORT OF GOODS"))
    L(p1, 60, (48, "SB No:"), (100, "9988776"))
    L(p1, 72, (48, "SB Date:"), (100, "10.09.2026"))
    L(p1, 84, (48, "Exporter Name:"), (140, "PLAIN EXPORTS LTD"))

    # item rows spread across pages 2 and 3, same free-form layout a
    # non-ICEGATE forwarder's SB might use — no "HS CD"/"DESCRIPTION" labels.
    p2 = d.new_page(width=612, height=792)
    L(p2, 100, (48, "1"), (95, "73043919"),
      (160, "SEAMLESS STEEL TUBE FITTING ASSEMBLY"), (430, "100.000"))
    L(p2, 120, (48, "2"), (95, "85444299"),
      (160, "INSULATED COPPER CABLE REEL"), (430, "50.000"))

    p3 = d.new_page(width=612, height=792)
    L(p3, 100, (48, "3"), (95, "39235090"),
      (160, "PVC PIPE FITTINGS PACKAGING UNIT"), (430, "200.000"))

    d.save(path)
    d.close()
    return str(path)


def test_hs_codes_enriched_even_when_icegate_template_doesnt_match(tmp_path):
    from app.document import load_document

    path = _generic_sb_pdf(tmp_path / "generic_sb.pdf")
    assert not icegate_sb.matches(load_document(path))

    res = AnchorExtractor().extract(path, doc_id="plain1", doc_type="shipping_bill")
    m = res.as_map()

    assert m["hs_code"] == "73043919, 85444299, 39235090"
    descs = (m["cargo_description"] or "").split("\n")
    assert len(descs) == 3
    assert "SEAMLESS STEEL TUBE FITTING ASSEMBLY" in descs[0]
    assert "INSULATED COPPER CABLE REEL" in descs[1]
    assert "PVC PIPE FITTINGS PACKAGING UNIT" in descs[2]
    assert "U.S.A" != m["consignee_name"]
