"""Automatic document-type detection (Bill of Lading vs Shipping Bill).

Keyword/title scoring over the top of page 1. Deterministic, fast, no model.
Used at upload so the reviewer never has to pick the type by hand; an explicit
choice from the UI still wins.
"""
from __future__ import annotations

import pymupdf

_SB_HINTS = (
    "shipping bill", "let export order", "leo date", "leo no", "drawback",
    "pcin", "s/b no", "sb no.", "icegate", "customs house", "fob value",
    "ad code", "rbi", "ritc", "port of loading", "invoice value",
)
_BL_HINTS = (
    "bill of lading", "b/l no", "bl no", "port of discharge", "vessel",
    "notify party", "shipped on board", "freight prepaid", "freight collect",
    "container no", "place of delivery", "carrier", "gross weight",
)


def detect_doc_type(head_text: str) -> tuple[str, float]:
    """Return (doc_type, confidence 0-1). Defaults to bill_of_lading if unsure."""
    t = (head_text or "").lower()
    if not t.strip():
        return "bill_of_lading", 0.0

    sb = sum(h in t for h in _SB_HINTS) + (3 if "shipping bill" in t else 0)
    bl = sum(h in t for h in _BL_HINTS) + (3 if "bill of lading" in t else 0)
    total = sb + bl
    if total == 0:
        return "bill_of_lading", 0.0
    if sb > bl:
        return "shipping_bill", round(sb / total, 2)
    return "bill_of_lading", round(bl / total, 2)


def head_text_from_bytes(content: bytes, frac: float = 0.45) -> str:
    """Text from the top ``frac`` of page 1 of a digital PDF (empty for scans)."""
    try:
        with pymupdf.open(stream=content, filetype="pdf") as d:
            if d.page_count == 0:
                return ""
            page = d[0]
            cutoff = page.rect.height * frac
            return " ".join(w[4] for w in page.get_text("words") if w[1] < cutoff)
    except Exception:  # noqa: BLE001
        return ""
