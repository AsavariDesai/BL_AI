"""Import's container-number reconciliation (Master BL <-> House BL) — the
Import-side counterpart of Export's SB-number reconciliation
(test_pipeline.py's test_sb_reconciliation_*). Master BL has no field
catalog of its own (field_catalog.MASTER_BL is still empty), so its
container numbers are scanned directly off the PDF (service.
_extract_container_numbers) rather than read from a canonical field — the
tests below exercise that path end to end, not just the regex.
"""
import time

from tests.conftest import make_bl_pdf


def _upload_master(client, vessel_id, containers: list[str]) -> str:
    text = "MASTER BILL OF LADING\n" + "\n".join(containers)
    resp = client.post(
        "/documents", data={"doc_type": "master_bl", "vessel_id": vessel_id},
        files={"file": ("master.pdf", make_bl_pdf(text), "application/pdf")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _link_house(client, master_id, containers: list[str], filename="house.pdf"):
    text = "HOUSE BILL OF LADING\n" + "\n".join(containers)
    resp = client.post(
        f"/documents/{master_id}/link-house-bl",
        files={"files": (filename, make_bl_pdf(text), "application/pdf")},
    )
    assert resp.status_code == 201
    return resp.json()["linked_house_bls"][-1]


def _company_and_vessel(client, code="CREC1", imo="9500001"):
    company_id = client.post("/companies", json={
        "company_code": code, "company_name": "Container Recon Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }).json()["id"]
    vessel_id = client.post("/vessels", json={
        "name": "RECON VESSEL", "imo_code": imo, "call_sign": "RCN01", "company_id": company_id,
    }).json()["id"]
    return company_id, vessel_id


def _wait_settled(client, doc_id, timeout=10.0):
    """Master BL / House BL auto-extract (OCR warm-up) in the background on
    upload — these are digital (text-layer) PDFs so it's near-instant, but
    still a real background thread, not synchronous with the request."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = client.get(f"/documents/{doc_id}").json()
        if d["status"] in ("extracted", "error"):
            return d
        time.sleep(0.05)
    raise AssertionError(f"{doc_id} did not settle within {timeout}s")


def test_reconciliation_clean_when_containers_match_exactly(client):
    _, vessel_id = _company_and_vessel(client)
    master_id = _upload_master(client, vessel_id, ["TSTU1111111", "TSTU2222222"])
    _wait_settled(client, master_id)
    _link_house(client, master_id, ["TSTU1111111"], "h1.pdf")
    _link_house(client, master_id, ["TSTU2222222"], "h2.pdf")

    detail = client.get(f"/documents/{master_id}").json()
    for h in detail["linked_house_bls"]:
        _wait_settled(client, h["id"])
    detail = client.get(f"/documents/{master_id}").json()

    rec = detail["container_reconciliation"]
    assert rec["total_master"] == 2
    assert rec["total_uploaded"] == 2
    assert rec["missing_containers"] == []
    assert rec["duplicate_containers"] == []
    assert rec["unrelated_containers"] == []
    for h in detail["linked_house_bls"]:
        assert h["has_duplicate_container"] is False
        assert h["has_unrelated_container"] is False


def test_reconciliation_reports_shortage(client):
    """Master BL has 3 containers; only 1 shows up on an uploaded House BL —
    the other two must be reported as missing (shortage)."""
    _, vessel_id = _company_and_vessel(client, code="CREC2", imo="9500002")
    master_id = _upload_master(client, vessel_id, ["AAAU1111111", "BBBU2222222", "CCCU3333333"])
    _wait_settled(client, master_id)
    house = _link_house(client, master_id, ["AAAU1111111"])
    _wait_settled(client, house["id"])

    detail = client.get(f"/documents/{master_id}").json()
    rec = detail["container_reconciliation"]
    assert rec["total_master"] == 3
    assert rec["total_uploaded"] == 1
    assert sorted(rec["missing_containers"]) == ["BBBU2222222", "CCCU3333333"]
    assert rec["duplicate_containers"] == []
    assert rec["unrelated_containers"] == []


def test_reconciliation_reports_excess_unrelated_container(client):
    """A House BL carries a container the Master BL never mentions — flagged
    as a possibly-incorrect (excess/unrelated) upload."""
    _, vessel_id = _company_and_vessel(client, code="CREC3", imo="9500003")
    master_id = _upload_master(client, vessel_id, ["DDDU1111111"])
    _wait_settled(client, master_id)
    house = _link_house(client, master_id, ["DDDU1111111", "ZZZU9999999"])
    _wait_settled(client, house["id"])

    detail = client.get(f"/documents/{master_id}").json()
    rec = detail["container_reconciliation"]
    assert rec["total_master"] == 1
    assert rec["total_uploaded"] == 2
    assert rec["missing_containers"] == []
    assert rec["unrelated_containers"] == ["ZZZU9999999"]

    house_row = next(h for h in detail["linked_house_bls"] if h["id"] == house["id"])
    assert house_row["has_unrelated_container"] is True
    assert house_row["has_duplicate_container"] is False


def test_reconciliation_reports_duplicate_across_house_bls(client):
    """The same container number uploaded under two different House BLs —
    must be flagged as a duplicate on both, with the count/number surfaced
    at the Master BL level too."""
    _, vessel_id = _company_and_vessel(client, code="CREC4", imo="9500004")
    master_id = _upload_master(client, vessel_id, ["EEEU1111111", "FFFU2222222"])
    _wait_settled(client, master_id)
    h1 = _link_house(client, master_id, ["EEEU1111111"], "h1.pdf")
    h2 = _link_house(client, master_id, ["EEEU1111111"], "h2.pdf")  # duplicate of h1
    _wait_settled(client, h1["id"])
    _wait_settled(client, h2["id"])

    detail = client.get(f"/documents/{master_id}").json()
    rec = detail["container_reconciliation"]
    assert rec["duplicate_containers"] == ["EEEU1111111"]
    assert rec["missing_containers"] == ["FFFU2222222"]  # never actually uploaded

    by_id = {h["id"]: h for h in detail["linked_house_bls"]}
    assert by_id[h1["id"]]["has_duplicate_container"] is True
    assert by_id[h2["id"]]["has_duplicate_container"] is True


def test_reconciliation_is_none_when_master_has_no_containers(client):
    """A Master BL whose text has no container-shaped numbers at all — there
    is nothing to reconcile against, so this stays None rather than showing
    a misleading all-zero report."""
    _, vessel_id = _company_and_vessel(client, code="CREC5", imo="9500005")
    master_id = _upload_master(client, vessel_id, [])  # no containers in the text
    _wait_settled(client, master_id)
    house = _link_house(client, master_id, ["GGGU1111111"])
    _wait_settled(client, house["id"])

    detail = client.get(f"/documents/{master_id}").json()
    assert detail["container_reconciliation"] is None
    # the House BL's own containers are still surfaced even with nothing to
    # check them against — just no "unrelated" flag without a reference.
    house_row = next(h for h in detail["linked_house_bls"] if h["id"] == house["id"])
    assert house_row["container_numbers"] == ["GGGU1111111"]
    assert house_row["has_unrelated_container"] is False


def test_reconciliation_waits_for_ocr_rather_than_running_inline(client):
    """A Master BL that hasn't finished extracting yet (still queued/
    processing) must not trigger an inline OCR pass just because its detail
    was fetched — reconciliation simply stays None/empty until it settles."""
    _, vessel_id = _company_and_vessel(client, code="CREC6", imo="9500006")
    master_id = _upload_master(client, vessel_id, ["HHHU1111111"])
    # deliberately do NOT wait — check immediately, mirroring a client that
    # fetches the detail page right after the upload response comes back.
    detail = client.get(f"/documents/{master_id}").json()
    assert detail["status"] in ("uploaded", "queued", "processing", "extracted")
    if detail["status"] != "extracted":
        assert detail["container_reconciliation"] is None
