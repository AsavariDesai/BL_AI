"""A Master BL's own extracted "Vessel / Voyage" text should name the
Vessel Workspace it was uploaded under — service._check_master_vessel_match
flags it as a (non-blocking) warning otherwise, the same way an OCR'd-page
notice already surfaces."""
import time

from tests.test_one_masterbl import _pdf


def _company_and_vessel(client, *, vessel_name, code, imo):
    company_id = client.post("/companies", json={
        "company_code": code, "company_name": "Vessel Match Co", "country_name": "India",
        "pan_no": "AACCB8054G", "gstin_no": "06AACCB8054G1ZT",
    }).json()["id"]
    vessel_id = client.post("/vessels", json={
        "name": vessel_name, "imo_code": imo, "call_sign": "VMC01", "company_id": company_id,
    }).json()["id"]
    return vessel_id


def _upload_and_settle(client, vessel_id, tmp_path, timeout=10.0):
    path = _pdf(tmp_path / "master.pdf")
    with open(path, "rb") as f:
        doc_id = client.post(
            "/ingest", data={"doc_type": "master_bl", "vessel_id": vessel_id},
            files={"file": ("master.pdf", f.read(), "application/pdf")},
        ).json()["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = client.get(f"/documents/{doc_id}").json()
        if d["status"] in ("extracted", "error"):
            return d
        time.sleep(0.05)
    raise AssertionError(f"{doc_id} did not settle within {timeout}s")


def test_warns_when_vessel_does_not_match(client, tmp_path):
    vessel_id = _company_and_vessel(
        client, vessel_name="QUEEN MARY", code="VMC1", imo="9700001",
    )
    detail = _upload_and_settle(client, vessel_id, tmp_path)
    assert any("BROOKLYN BRIDGE" in w and "QUEEN MARY" in w for w in detail["warnings"])


def test_no_warning_when_vessel_matches(client, tmp_path):
    vessel_id = _company_and_vessel(
        client, vessel_name="BROOKLYN BRIDGE", code="VMC2", imo="9700002",
    )
    detail = _upload_and_settle(client, vessel_id, tmp_path)
    assert not any("doesn't name" in w for w in detail["warnings"])


def test_no_warning_without_a_vessel(client, tmp_path):
    """A legacy/company-only Master BL (no vessel_id at all) has nothing to
    cross-check against — must never be flagged."""
    path = _pdf(tmp_path / "master.pdf")
    with open(path, "rb") as f:
        doc_id = client.post(
            "/ingest", data={"doc_type": "master_bl"},
            files={"file": ("master.pdf", f.read(), "application/pdf")},
        ).json()["id"]
    deadline = time.monotonic() + 10.0
    detail = None
    while time.monotonic() < deadline:
        detail = client.get(f"/documents/{doc_id}").json()
        if detail["status"] in ("extracted", "error"):
            break
        time.sleep(0.05)
    assert detail["status"] == "extracted"
    assert not any("doesn't name" in w for w in detail["warnings"])
