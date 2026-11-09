"""Break Bulk (Liner) Bill of Lading — no containers; pipe/bundle cargo, weights
in MTS, with the Shipping Bill No. and Net Weight carried inside the
"Description of Packages and Goods" block.
"""
from __future__ import annotations

import re

from ..document import Document, Token
from ._common import _cell_below, _clean, _find_label, _party_lines

DOC_TYPE = "bill_of_lading"

_SBNO_RE = re.compile(r"SHIPPING BILL NO\.?\s*[:.]?\s*(\d{5,})\s*(?:DT\.?\s*([\d./-]+))?", re.I)
_NETWT_RE = re.compile(r"NET WEIGHT\s*\(?\s*(MTS|KGS)?\s*\)?\s*[:.]?\s*([\d,]+\.?\d*)\s*(MTS|KGS)?", re.I)
_GROSSWT_RE = re.compile(r"([\d,]+\.\d+)\s*(MTS|KGS)\b", re.I)
_PKG_RE = re.compile(r"\b(\d{1,6})\s+(BUNDLES?|PACKAGES?|PKGS?|PIECES?|PCS?|COILS?|CASES?)\b", re.I)
_FREIGHT_RE = re.compile(r"FREIGHT\s+(PREPAID|COLLECT)", re.I)
_ONBOARD_RE = re.compile(r"SHIPPED ON BOARD\s*(?:DATE)?\s*[:.]?\s*(\d{1,2}[-/. ]\d{1,2}[-/. ]\d{2,4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
_ISSUE_DATE_RE = re.compile(r"\b(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})\b")
_INCO_RE = re.compile(r"(SHIPPING TERMS\s*:?\s*[A-Z]{3}[^\n(]*\(INCOTERMS[^)]*\))", re.I)
_LC_RE = re.compile(r"DOCUMENTARY CREDIT NUMBER\s*:?\s*([A-Z0-9]+\s*(?:DATED\s*\d+)?)", re.I)
_PO_RE = re.compile(r"PO#?\s*(\d{5,})", re.I)
_VESSEL_RE = re.compile(r"\b(M[VT]\s+[A-Z][A-Za-z]+)\b")


_DESC_STOP = (
    r"TOLERANCES|TOTAL QUANTITY|SHIPPING TERMS|DOCUMENTARY CREDIT|SHIPPING BILL NO"
    r"|IMO NUMBER|SHIPPED ON BOARD|NET WEIGHT|FREIGHT PREPAID|FREIGHT COLLECT"
    r"|DISCHARGE PORT|TOTAL NO\. OF PACKAGES|SHIPS GENERAL REMARKS"
)
_PKG_LINE_RE = re.compile(
    r"SAID TO CONTAIN\s+(\d[\d,]*\s+(?:BUNDLES?|PACKAGES?|PIECES?|PCS?|COILS?|CASES?)"
    r"(?:\s+CONTAINING\s+\d[\d,]*\s+[A-Z]+)?)",
    re.I,
)
_GOODS_RE = re.compile(
    rf"DESCRIPTION OF GOODS\s+([A-Z0-9][A-Za-z0-9 ,.\-/&()]{{15,400}}?)"
    rf"(?=\s+(?:{_DESC_STOP})|$)",
    re.I,
)
_BOILER = re.compile(
    r"apparent good order|merchant expressly accepts|IN WITNESS whereof|surrendered duly endorsed",
    re.I,
)


def _description(full: str) -> str | None:
    parts: list[str] = []
    m = _PKG_LINE_RE.search(full)
    if m:
        parts.append(_clean(m.group(1)))
    m = _GOODS_RE.search(full)
    if m and not _BOILER.search(m.group(1)):
        parts.append(_clean(m.group(1)))
    text = " / ".join(dict.fromkeys(p for p in parts if p))
    if not text or _BOILER.search(text):
        return None
    return text[:500].rstrip(" /-,")


def matches(doc: Document) -> bool:
    head = " ".join(t.text for t in doc.pages[0].tokens).upper()
    return "LINER BILL OF LADING" in head and (
        "PARTICULARS FURNISHED BY THE MERCHANT" in head
        or "SAID TO CONTAIN" in head
        or "NO. OF PKGS" in head
    )


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    toks: list[Token] = list(doc.pages[0].tokens)
    page_w = doc.pages[0].width or 595.0
    full = " ".join(t.text for t in toks)
    out: dict[str, tuple[str, float]] = {}

    def put(k: str, v: str | None, c: float) -> None:
        if v and _clean(v):
            out[k] = (_clean(v), c)

    put("document_type", "Break Bulk Bill of Lading", 0.9)
    # bl_number is filled by the extractor's cross-layout identifier pass

    # --- from the Description of Packages & Goods block
    m = _SBNO_RE.search(full)
    if m:
        sb = m.group(1) + (f" DT. {m.group(2)}" if m.group(2) else "")
        put("shipping_bill_number_and_date", sb, 0.9)

    m = _NETWT_RE.search(full)
    if m:
        unit = (m.group(3) or m.group(1) or "MTS").upper()
        put("net_weight", f"{m.group(2)} {unit}", 0.9)

    net_val = out.get("net_weight", ("",))[0].split(" ")[0]
    for gm in _GROSSWT_RE.finditer(full):
        if gm.group(1) != net_val:
            put("gross_weight", f"{gm.group(1)} {gm.group(2).upper()}", 0.8)
            break

    m = _PKG_RE.search(full)
    put("number_and_kind_of_packages", f"{m.group(1)} {m.group(2).upper()}" if m else None, 0.8)

    m = _FREIGHT_RE.search(full)
    put("freight_terms", f"FREIGHT {m.group(1).upper()}" if m else None, 0.85)

    m = _ONBOARD_RE.search(full)
    put("shipped_on_board_date", m.group(1) if m else None, 0.8)

    m = _INCO_RE.search(full)
    put("incoterms", m.group(1) if m else None, 0.8)

    m = _LC_RE.search(full)
    put("lc_number", m.group(1) if m else None, 0.75)

    m = _PO_RE.search(full)
    put("purchase_order_number", m.group(1) if m else None, 0.7)

    lbl = _find_label(toks, "vessel")
    if lbl:
        put("vessel_and_voyage", _cell_below(toks, lbl[1], y_hi=18, x_half=90), 0.8)
    if "vessel_and_voyage" not in out:
        m = _VESSEL_RE.search(full)
        put("vessel_and_voyage", m.group(1) if m else None, 0.7)

    m = _ISSUE_DATE_RE.search(full)
    put("place_and_date_of_issue", m.group(1) if m else None, 0.6)

    m = re.search(r"\bPO#\s*\d{5,}\b", full)
    if m:
        put("marks_and_numbers", m.group(0), 0.65)

    put("description_of_goods", _description(full), 0.7)

    # --- labelled boxes (geometry)
    def box(starts, stops, right):
        return ", ".join(_party_lines(toks, page_w, starts, stops, right=right)) or None

    put("shipper", box(("shipperexporter", "shipper"),
                        ("consignee", "bookingno"), False), 0.8)
    put("consignee", box(("consignee",),
                          ("notifyparty", "forwardingagent"), False), 0.8)
    put("notify_party", box(("notifyparty",),
                            ("precarried", "vessel", "exportreferences"), False), 0.8)

    lbl = _find_label(toks, "number of original")
    if lbl:
        v = _cell_below(toks, lbl[1], y_hi=18, x_half=60)
        if v and re.fullmatch(r"\d{1,2}", v):
            put("number_of_original_bls", v, 0.75)

    lbl = _find_label(toks, "place and date of issue")
    if lbl:
        v = _cell_below(toks, lbl[1], y_hi=18, x_half=200)
        if v:
            put("place_and_date_of_issue", v, 0.75)

    for label, key in (
        ("port of loading", "port_of_loading"),
        ("port of discharge", "port_of_discharge"),
    ):
        lbl = _find_label(toks, label)
        if lbl:
            v = _cell_below(toks, lbl[1], y_hi=18, x_half=90)
            if v and v.upper().split()[0] not in ("PORT", "OF", "LOADING", "DISCHARGE",
                                                  "PLACE", "PARTICULARS", "ONWARD"):
                put(key, v, 0.75)

    return {k: v for k, v in out.items() if v[0]}
