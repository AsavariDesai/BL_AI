"""Parser for the AOF Cargo 'Multimodal Transport Bill of Lading' form
(AOF CARGO LOGISTICS ... CO., LTD — "OCEAN BILL OF LADING").

The text layer is heavily out of visual order, so the distinctive fields are
pulled by pattern from the full page text, and the labelled boxes (parties,
routing, issue place) by geometry.
"""
from __future__ import annotations

import re

from ..document import Document, Token
from .icegate_sb import _clean, _cx, _cy, _find_label, _lines, _value_in_column

DOC_TYPE = "bill_of_lading"

_CONTAINER_RE = re.compile(r"\b([A-Z]{4}\d{7})\b")
_CONT_SIZE_RE = re.compile(r"([A-Z]{4}\d{7})\s*/\s*(\d{2}'?[A-Z]{2})")
_WT_MEAS_RE = re.compile(r"([\d,]+\.\d{2})\s+([\d,]+\.\d{2,3})(?!\d)")
_WT_UNIT_RE = re.compile(r"([\d,]+\.\d{2})\s*KGS\b.{0,40}?([\d,]+\.\d{2,3})\s*CBM\b", re.I)
_PKG_RE = re.compile(r"\b\d{1,5}\s+PACKAGES?\b", re.I)
_ONBOARD_RE = re.compile(r"ON\s*BOARD\s+([A-Z]{3,4}\.?\s?\d{1,2}[.,]\s?\d{4})", re.I)
_ORIG_RE = re.compile(r"\b(ONE|TWO|THREE|FOUR|FIVE|SIX)\s*/\s*(\d)\b", re.I)
_MOVE_RE = re.compile(r"\b(CY/CY|CY/CFS|CFS/CY|CFS/CFS|FCL/FCL|LCL/LCL|FCL/LCL|LCL/FCL)\b", re.I)
_FREIGHT_RE = re.compile(r"FREIGHT\s+(PREPAID|COLLECT)", re.I)
_IEC_RE = re.compile(r"\bIEC\s*[:\-]?\s*(\d{8,10})\b", re.I)
_BLNO_RE = re.compile(r"\b([A-Z]{4,7}\d{8,})\b")
_SO_RE = re.compile(r"\bS\.?O\.?\s*[:.]?\s*([A-Z]?\d{5,})\b", re.I)
_CARRIER_RE = re.compile(r"(AOF\s+CARGO\s+LOGISTICS\s+[A-Z]+\s+CO\.,?\s*LTD)", re.I)
_VESSEL_RE = re.compile(r"\b([A-Z][A-Z ]{4,30}V\.?\s?\d{3,4}[A-Z]?)\b")
_ISSUE_RE = re.compile(r"\b([A-Z]+,\s*[A-Z]+\s+[A-Z]{3,4}\.?\s?\d{1,2}[.,]\s?\d{4})")


def matches(doc: Document) -> bool:
    head = " ".join(t.text for t in doc.pages[0].tokens).upper()
    return "AOF CARGO" in head and (
        "MULTIMODAL TRANSPORT BILL" in head or "OCEAN BILL OF LADING" in head
    )


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    toks: list[Token] = list(doc.pages[0].tokens)
    page_w = doc.pages[0].width or 595.0
    full = " ".join(t.text for t in toks)
    out: dict[str, tuple[str, float]] = {}

    def put(key: str, value: str | None, conf: float) -> None:
        if value and _clean(value):
            out[key] = (_clean(value), conf)

    put("document_type", "Multimodal Transport Bill of Lading", 0.9)

    # ---- pattern fields (order-independent, robust to the jumbled text layer)
    m = _BLNO_RE.search(full)
    put("bl_number", m.group(1) if m else None, 0.85)
    m = _SO_RE.search(full)
    put("reference_number", f"SO {m.group(1)}" if m else None, 0.7)

    m = _CARRIER_RE.search(full)
    if m:
        put("carrier", m.group(1), 0.8)
        put("issued_by_agent", f"{_clean(m.group(1))}, As Carrier", 0.7)

    m = _WT_MEAS_RE.search(full) or _WT_UNIT_RE.search(full)
    if m:
        put("gross_weight", f"{m.group(1)} KGS", 0.8)
        put("measurement_cbm", f"{m.group(2)} CBM", 0.8)

    m = _PKG_RE.search(full)
    put("number_and_kind_of_packages", m.group(0) if m else None, 0.8)

    m = _FREIGHT_RE.search(full)
    put("freight_terms", f"FREIGHT {m.group(1).upper()}" if m else None, 0.85)

    m = _MOVE_RE.search(full)
    put("movement_type", m.group(1).upper() if m else None, 0.85)

    m = _ONBOARD_RE.search(full)
    put("shipped_on_board_date", m.group(1) if m else None, 0.8)

    m = _ORIG_RE.search(full)
    put("number_of_original_bls", f"{m.group(1).upper()}/{m.group(2)}" if m else None, 0.8)

    m = _IEC_RE.search(full)
    put("iec_code", m.group(1) if m else None, 0.8)

    m = _VESSEL_RE.search(full)
    put("vessel_and_voyage", m.group(1) if m else None, 0.7)

    m = _ISSUE_RE.search(full)
    put("place_and_date_of_issue", m.group(1) if m else None, 0.7)

    if re.search(r"(?<![A-Z])N/M(?![A-Z])", full):
        put("marks_and_numbers", "N/M", 0.7)

    m = re.search(
        r"((?:ONE|TWO|THREE|FOUR)\s*\(\d\)[A-Za-z0-9 ()'.]*?CONTAINERS?\s+ONLY\.?)",
        full, re.I,
    )
    put("total_containers", m.group(1) if m else None, 0.7)

    # containers (+ size)
    sized = [f"{a}/{b}" for a, b in _CONT_SIZE_RE.findall(full)]
    conts = list(dict.fromkeys(sized or _CONTAINER_RE.findall(full)))
    put("container_and_seal_numbers", ", ".join(conts) if conts else None, 0.8)

    # notify parties
    nm = re.search(
        r"NOTIFY PARTY 1:\s*(.+?)\s*NOTIFY PARTY 2:\s*(.+?)"
        r"(?:\s+KGS\b|\s+JEENA\b|\s+Place of\b|\s+Ocean vessel\b|$)",
        full, re.I | re.S,
    )
    if nm:
        put("notify_party", nm.group(1), 0.8)
        put("notify_party_2", " ".join(nm.group(2).split()[:8]), 0.8)

    m = re.search(r"(JEENA\s*&\s*COMPANY.*?)(?:\s+IEC\s*:|\s+GSTIN\s*:|$)", full, re.I | re.S)
    put("delivery_agent", m.group(1) if m else None, 0.7)

    # ---- geometric boxes (parties + routing)
    _party_box(toks, page_w, out, ("consignor", "shipper"), "shipper",
               stop=("consignedtoorder", "notifyaddress", "notifyparty"))
    _party_box(toks, page_w, out, ("consignedtoorderof", "consignedtoorder"), "consignee",
               stop=("notifyaddress", "notifyparty", "placeofreceipt"))

    _STOP = {"PORT", "PLACE", "OF", "LOADING", "DISCHARGE", "RECEIPT",
             "DELIVERY", "OCEAN", "VESSEL", "MARKS", "NUMBERS"}
    for label, key in (
        ("place of receipt", "place_of_receipt"),
        ("port of loading", "port_of_loading"),
        ("port of discharge", "port_of_discharge"),
        ("place of delivery", "place_of_delivery"),
    ):
        lbl = _find_label(toks, label)
        if lbl:
            v = _cell_below(toks, lbl[1], y_hi=17, x_half=70)
            if v and v.upper().split()[0] not in _STOP:
                put(key, v, 0.75)

    return {k: v for k, v in out.items() if v[0]}


def _cell_below(toks: list[Token], anchor_end: Token, *,
                y_lo: float = 2.0, y_hi: float = 17.0, x_half: float = 90.0) -> str:
    """The full text of the cell directly beneath ``anchor_end`` (all tokens on
    the nearest row within the label's x-column)."""
    cx = _cx(anchor_end)
    below = [
        t for t in toks
        if anchor_end.y1 + y_lo <= _cy(t) <= anchor_end.y1 + y_hi
        and abs(_cx(t) - cx) <= x_half
    ]
    if not below:
        return ""
    y0 = min(t.y0 for t in below)
    row = sorted((t for t in below if abs(t.y0 - y0) <= 4), key=lambda t: t.x0)
    return _clean(" ".join(t.text for t in row))


def _party_box(toks, page_w, out, start_phrases, key, *, stop) -> None:
    start = None
    for ph in start_phrases:
        start = _find_label(toks, ph)
        if start:
            break
    if not start:
        return
    top = start[1].y1
    left = [t for t in toks if t.x0 < page_w * 0.48]

    bottom = top + 70
    for ph in stop:
        f = _find_label([t for t in left if t.y0 > top + 2], ph)
        if f:
            bottom = min(bottom, f[0].y0)

    lines: list[str] = []
    for ln in _lines([t for t in left if top - 1 <= t.y0 < bottom]):
        s = _clean(" ".join(t.text for t in ln))
        low = s.lower().replace(" ", "")
        if (not s or any(low.startswith(p) for p in start_phrases)
                or "notifyparty" in low or "billoflading" in low
                or "oceanbill" in low):
            continue
        lines.append(s)
    if lines:
        joined = ", ".join(lines)
        out[key] = (_clean(joined), 0.8)
