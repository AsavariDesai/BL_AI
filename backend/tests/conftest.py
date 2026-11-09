"""Test fixtures: every test gets an isolated data dir + fresh sqlite db."""
from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import auth, config, db
from app import repository as repo
from app.api import app


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "bl.db")
    (tmp_path / "uploads").mkdir()
    db.init_db()
    yield


TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpassword123"


@pytest.fixture
def client(isolated_data):
    """A TestClient already signed in as a throwaway test user — every route
    except /health and /auth/login requires a session now, so tests that
    aren't specifically about auth shouldn't have to deal with logging in.

    This user is an admin (sees every record, not just its own) so the bulk
    of the test suite — written before per-user scoping existed — keeps
    working unchanged; tests that specifically exercise regular-user scoping
    create their own non-admin user instead (see test_roles.py)."""
    with TestClient(app) as c:
        repo.create_user(
            username=TEST_USERNAME, password_hash=auth.hash_password(TEST_PASSWORD), role="admin"
        )
        r = c.post("/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        assert r.status_code == 200
        yield c


def make_bl_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 60), text, fontsize=10)
    data = doc.write()
    doc.close()
    return data


SAMPLE_BL = """COMBINED TRANSPORT BILL OF LADING
B/L No: 181142608002
Shipper: BLUEWAVE EXIM, HYDERABAD 500032
Consignee: GREEN GOLD GLOBAL FZC LLC, AJMAN UAE
Notify Party: SAME AS CONSIGNEE
Vessel/Voyage: ARYA BHUM / 2630
Port of Loading: NHAVA SHEVA
Port of Discharge: KHOR FAKKAN
Gross Weight: 29500.000 KGS
Net Weight: 29400.000 KGS
HS Code: 07031019
Container No: CSQU3054383
SB NO. 5778867 DT. 08.08.2026
FREIGHT PREPAID
Shipped on Board: 14 AUG 2026
"""


SAMPLE_SB = """SHIPPING BILL FOR EXPORT OF GOODS
SB No: 5778867
SB Date: 08.08.2026
Field Location: INNSA1
PCIN No: PCIN2026001
SB Type: DBK
No of Packages: 1470
Gross Weight: 29500.000 KGS
LEO Date: 14.08.2026
Destination: KHOR FAKKAN, AE
Exporter Name: BLUEWAVE EXIM
Consignee Name: GREEN GOLD GLOBAL FZC LLC
Shipper Code: BMMPG8728K
Shipper Address: SHIVARAMANA APPARTMENTS, RANGAREDDY, TELANGANA 500032
Cargo Description: INDIAN FRESH ONION
HS Code: 07031019
"""


@pytest.fixture
def bl_pdf_bytes() -> bytes:
    return make_bl_pdf(SAMPLE_BL)


@pytest.fixture
def sb_pdf_bytes() -> bytes:
    return make_bl_pdf(SAMPLE_SB)


@pytest.fixture
def bl_pdf_path(tmp_path, bl_pdf_bytes) -> str:
    p = tmp_path / "bl.pdf"
    p.write_bytes(bl_pdf_bytes)
    return str(p)
