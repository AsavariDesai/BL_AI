"""Unified document loader.

Produces a page/token model that the extractors consume, regardless of whether
the source PDF has a real text layer (digital) or is an image-only scan.

  digital page  -> tokens straight from PyMuPDF (fast, exact, confidence 1.0)
  scanned page  -> rasterise at OCR_DPI, run the local OCR backend, scale boxes
                   from pixel space back into PDF points
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from . import config
from .config import settings

_TOKCACHE_DIR = config.DATA_DIR / "tokcache"


@dataclass
class Token:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    conf: float = 1.0
    origin: str = "pdf"          # "pdf" | "ocr"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class DocPage:
    number: int                 # 1-based
    width: float
    height: float
    tokens: list[Token] = field(default_factory=list)
    is_scanned: bool = False

    @property
    def text(self) -> str:
        return "\n".join(
            " ".join(t.text for t in row) for row in group_rows(self.tokens)
        )


@dataclass
class Document:
    path: str
    pages: list[DocPage]

    @property
    def full_text(self) -> str:
        return "\n\n".join(f"--- PAGE {p.number} ---\n{p.text}" for p in self.pages)

    @property
    def all_tokens(self) -> list[Token]:
        return [t for p in self.pages for t in p.tokens]

    @property
    def has_scanned_pages(self) -> bool:
        return any(p.is_scanned for p in self.pages)


def group_rows(tokens: list[Token], overlap_frac: float = 0.35) -> list[list[Token]]:
    """Cluster tokens into visual rows, each sorted left-to-right.

    Word bounding boxes from a PDF text layer carry ascender/descender/leading,
    so adjacent lines overlap vertically by a point or two. Two tokens share a
    row only when their y-intervals overlap by at least ``overlap_frac`` of the
    smaller height — enough to ignore that leading bleed but still merge a true
    same-line pair.
    """
    rows: list[list[Token]] = []
    for tok in sorted(tokens, key=lambda t: (t.y0, t.x0)):
        h = max(1.0, tok.y1 - tok.y0)
        placed = False
        for row in rows:
            ry0 = min(t.y0 for t in row)
            ry1 = max(t.y1 for t in row)
            overlap = min(tok.y1, ry1) - max(tok.y0, ry0)
            if overlap >= overlap_frac * min(h, ry1 - ry0):
                row.append(tok)
                placed = True
                break
        if not placed:
            rows.append([tok])
    rows.sort(key=lambda r: min(t.y0 for t in r))
    for row in rows:
        row.sort(key=lambda t: t.x0)
    return rows


_WATERMARK_RE = re.compile(
    r"^(ORIGINAL|SURRENDERED|COPY|DUPLICATE|TRIPLICATE|DRAFT|VOID|SPECIMEN|CANCELLED|"
    r"NON.?NEGOTIABLE)$",
    re.IGNORECASE,
)


def _strip_noise(tokens: list[Token]) -> list[Token]:
    """Drop watermark stamps ("ORIGINAL", "SURRENDERED", "COPY", …).

    A stamp gives itself away by being rotated (a box far taller than wide) *or*
    by repeating across the page, and by sitting away from any real neighbour on
    its own row. Dense/clustered text (CJK columns, a legitimate one-off value)
    is kept.
    """
    if not tokens:
        return tokens

    def _wm_key(t: Token) -> str:
        return t.text.strip().replace(" ", "").upper()

    counts: dict[str, int] = {}
    for t in tokens:
        if _WATERMARK_RE.match(_wm_key(t)):
            counts[_wm_key(t)] = counts.get(_wm_key(t), 0) + 1

    keep: list[Token] = []
    for t in tokens:
        if not t.text.strip():
            continue
        if _WATERMARK_RE.match(_wm_key(t)):
            w, h = t.x1 - t.x0, t.y1 - t.y0
            tall = h > max(1.0, w) * 2.2
            near = sum(
                1 for o in tokens
                if o is not t
                and abs(o.cx - t.cx) < 75 and abs(o.cy - t.cy) < 9
                and not _WATERMARK_RE.match(_wm_key(o))
            )
            if near == 0 and (tall or counts.get(_wm_key(t), 0) >= 2):
                continue
        keep.append(t)
    return keep


def _cache_path(sha: str, dpi: int, backend: str) -> Path:
    return config.DATA_DIR / "tokcache" / f"{sha}-{backend}-{dpi}.json"


def _to_cache(path: Path, document: Document) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pages": [
                {
                    "number": p.number, "width": p.width, "height": p.height,
                    "is_scanned": p.is_scanned,
                    "tokens": [
                        [t.text, t.x0, t.y0, t.x1, t.y1, t.page, t.conf, t.origin]
                        for t in p.tokens
                    ],
                }
                for p in document.pages
            ]
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:  # noqa: BLE001 — caching is best-effort
        pass


def _from_cache(path: Path, pdf_path: str) -> Document | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    pages = [
        DocPage(
            p["number"], p["width"], p["height"],
            [Token(*t) for t in p["tokens"]],
            is_scanned=p["is_scanned"],
        )
        for p in payload["pages"]
    ]
    return Document(path=pdf_path, pages=pages)


def load_document(
    pdf_path: str | Path,
    *,
    ocr_backend: str | None = None,
    dpi: int | None = None,
    use_cache: bool = True,
) -> Document:
    ocr_backend = ocr_backend if ocr_backend is not None else settings.ocr_backend
    dpi = dpi or settings.ocr_dpi

    # OCR is the expensive step. Cache the token model on disk keyed by the file's
    # content hash, so re-extract and every correction/save skip re-OCR.
    cache_file: Path | None = None
    if use_cache:
        try:
            sha = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()[:32]
            cache_file = _cache_path(sha, dpi, ocr_backend or "none")
            if cache_file.exists():
                cached = _from_cache(cache_file, str(pdf_path))
                if cached is not None:
                    return cached
        except Exception:  # noqa: BLE001
            cache_file = None

    doc = pymupdf.open(pdf_path)
    pages: list[DocPage] = []
    try:
        for index, page in enumerate(doc, start=1):
            rect = page.rect
            words = page.get_text("words")
            if words:
                tokens = [
                    Token(w[4], w[0], w[1], w[2], w[3], index, 1.0, "pdf")
                    for w in words
                    if w[4].strip()
                ]
                scanned = False
            elif ocr_backend and ocr_backend != "none":
                tokens = _ocr_page(page, index, dpi, ocr_backend)
                scanned = True
            else:
                tokens = []
                scanned = True
            pages.append(
                DocPage(index, rect.width, rect.height, _strip_noise(tokens),
                        is_scanned=scanned)
            )
    finally:
        doc.close()

    document = Document(path=str(pdf_path), pages=pages)
    # only persist when OCR actually ran (digital re-parse is already ~instant)
    if cache_file is not None and document.has_scanned_pages:
        _to_cache(cache_file, document)
    return document


def _ocr_page(page: "pymupdf.Page", index: int, dpi: int, backend_name: str) -> list[Token]:
    from .ocr import get_ocr_backend

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    png_bytes = pix.tobytes("png")

    backend = get_ocr_backend(backend_name)
    inv = 72.0 / dpi
    tokens: list[Token] = []
    for text, (x0, y0, x1, y1), conf in backend.read(png_bytes):
        box = (x0 * inv, y0 * inv, x1 * inv, y1 * inv)
        tokens.extend(_split_line_token(text, box, index, conf))
    return [t for t in tokens if t.text]


def _split_line_token(
    text: str,
    box: tuple[float, float, float, float],
    page: int,
    conf: float,
) -> list[Token]:
    """OCR backends emit line-level boxes; split into word tokens with
    x-coordinates interpolated by character offset so geometry logic works."""
    words = text.split()
    if len(words) <= 1:
        return [Token(text.strip(), *box, page, conf, "ocr")] if text.strip() else []

    x0, y0, x1, y1 = box
    span = x1 - x0
    total_chars = sum(len(w) for w in words) + (len(words) - 1)  # + spaces
    out: list[Token] = []
    cursor = 0
    for w in words:
        wx0 = x0 + span * (cursor / total_chars)
        cursor += len(w)
        wx1 = x0 + span * (cursor / total_chars)
        cursor += 1  # the space
        out.append(Token(w, wx0, y0, wx1, y1, page, conf, "ocr"))
    return out
