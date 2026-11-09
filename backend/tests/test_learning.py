import pytest

from app.formats import format_key


def _upload_extract(client, pdf_bytes):
    doc_id = client.post(
        "/documents", files={"file": ("bl.pdf", pdf_bytes, "application/pdf")}
    ).json()["id"]
    return client.post(f"/documents/{doc_id}/extract").json(), doc_id


def test_correction_creates_rule_that_helps_the_next_bl(client, bl_pdf_bytes):
    detail, doc_id = _upload_extract(client, bl_pdf_bytes)

    # The generic pass leaves the label glued onto notify_party ("Party: SAME AS
    # CONSIGNEE"). Correct it to the clean on-page text.
    fixed = "SAME AS CONSIGNEE"
    r = client.put(
        f"/documents/{doc_id}/fields",
        json={"fields": [{"key": "notify_party", "value": fixed}]},
    )
    assert r.status_code == 200

    rules = client.get("/anchor-rules").json()
    notify_rules = [x for x in rules if x["field_key"] == "notify_party"]
    assert len(notify_rules) == 1
    assert notify_rules[0]["format"] == format_key(detail["format_fingerprint"])
    assert notify_rules[0]["label_text"]

    stats = client.get("/corrections/stats").json()
    assert stats["learned_rules"] >= 1
    assert stats["learned_formats"] >= 1

    # A brand-new BL of the same format: the learned rule should fire and produce
    # the clean value at higher confidence than the glued generic guess.
    detail2, _ = _upload_extract(client, bl_pdf_bytes)
    notify2 = next(f for f in detail2["fields"] if f["key"] == "notify_party")
    assert notify2["value"] == "SAME AS CONSIGNEE"
    assert notify2["confidence"] >= 0.7


def test_saved_template_is_suggested_for_matching_format(client, bl_pdf_bytes):
    detail, _ = _upload_extract(client, bl_pdf_bytes)
    fp = detail["format_fingerprint"]
    assert fp

    client.post(
        "/export-templates",
        json={
            "name": "std onion",
            "selected_fields": ["bl_number", "consignee", "gross_weight"],
            "format_fingerprint": fp,
        },
    )

    detail2, _ = _upload_extract(client, bl_pdf_bytes)
    assert detail2["suggested_export_fields"] == ["bl_number", "consignee", "gross_weight"]


def test_no_template_no_suggestion(client, bl_pdf_bytes):
    detail, _ = _upload_extract(client, bl_pdf_bytes)
    assert detail["suggested_export_fields"] == []
