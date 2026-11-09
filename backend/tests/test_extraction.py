from app.extraction.anchor_extractor import AnchorExtractor
from app.extraction.validate import (
    container_check_digit_ok,
    cross_field_warnings,
    normalize_date,
    parse_quantity,
)
from app.field_catalog import FIELD_KEYS


def test_container_check_digit():
    assert container_check_digit_ok("CSQU3054383")        # canonical ISO 6346 example
    assert not container_check_digit_ok("CSQU3054384")
    assert not container_check_digit_ok("NONSENSE")


def test_normalize_date():
    assert normalize_date("14 AUG 2026") == "2026-08-14"
    assert normalize_date("08.08.2026") == "2026-08-08"
    assert normalize_date("not a date") is None


def test_parse_quantity():
    assert parse_quantity("29,500.000 KGS") == (29500.0, "KGS")
    assert parse_quantity("65.254 CBM") == (65.254, "CBM")
    assert parse_quantity("") is None


def test_cross_field_warnings_flags_bad_container_and_weights():
    w = cross_field_warnings(
        {
            "gross_weight": "100 KGS",
            "net_weight": "200 KGS",
            "container_and_seal_numbers": "CSQU3054384",
        }
    )
    assert any("gross" in x.lower() for x in w)
    assert any("6346" in x for x in w)


def test_anchor_extractor_core_fields(bl_pdf_path):
    result = AnchorExtractor().extract(bl_pdf_path, doc_id="t1")
    m = result.as_map()

    assert len(result.fields) == len(FIELD_KEYS)
    assert m["document_type"] and "bill of lading" in m["document_type"].lower()
    assert m["container_and_seal_numbers"] == "CSQU3054383"
    assert "KHOR FAKKAN" in (m["port_of_discharge"] or "").upper()
    assert (m["gross_weight"] or "").startswith("29500")
    assert result.get("shipped_on_board_date").value == "2026-08-14"

    # container passed its ISO 6346 check digit -> high confidence
    assert result.get("container_and_seal_numbers").confidence >= 0.8
    assert result.has_scanned_pages is False
