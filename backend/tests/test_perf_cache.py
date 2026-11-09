"""The token cache must make a 2nd load of a scanned PDF skip OCR entirely,
without changing what gets extracted."""
import pymupdf
import pytest

from app import ocr


class _CountingBackend:
    def __init__(self):
        self.calls = 0

    def read(self, png_bytes):
        self.calls += 1
        # one fake OCR line: (text, (x0,y0,x1,y1) px, conf)
        return [("B/L No: TESTCACHE123", (40, 40, 400, 60), 0.99)]


@pytest.fixture
def scanned_pdf(tmp_path):
    """A single-page image-only PDF (no text layer -> OCR path)."""
    src = pymupdf.open()
    p = src.new_page(width=400, height=200)
    p.insert_text((20, 30), "anything", fontsize=10)
    pix = p.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    out = pymupdf.open()
    page = out.new_page(width=400, height=200)
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / "scanned.pdf"
    out.save(path)
    return str(path)


def test_second_load_is_served_from_cache(scanned_pdf, monkeypatch):
    from app import document

    backend = _CountingBackend()
    monkeypatch.setattr(ocr, "get_ocr_backend", lambda name: backend)  # default is rapidocr

    d1 = document.load_document(scanned_pdf)
    assert backend.calls == 1
    assert d1.has_scanned_pages
    assert "TESTCACHE123" in d1.full_text

    d2 = document.load_document(scanned_pdf)      # same bytes -> cache hit
    assert backend.calls == 1                     # OCR NOT run again
    assert d2.full_text == d1.full_text
    assert [t.text for t in d2.pages[0].tokens] == [t.text for t in d1.pages[0].tokens]

    d3 = document.load_document(scanned_pdf, use_cache=False)  # opt out
    assert backend.calls == 2


def test_digital_pdf_is_not_cached(tmp_path):
    from app import config, document

    p = pymupdf.open()
    pg = p.new_page()
    pg.insert_text((40, 60), "B/L No: DIGITAL999", fontsize=10)
    path = tmp_path / "digital.pdf"
    p.save(path)

    document.load_document(str(path))
    cache_dir = config.DATA_DIR / "tokcache"
    assert not cache_dir.exists() or not any(cache_dir.iterdir())
