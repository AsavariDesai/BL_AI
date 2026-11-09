"""Container Bill of Lading — combined-transport / port-to-port form
(e.g. WINCO GROUP as agent for Yang Ming). Containerised cargo, CY move, HS codes
carried inside the description block.
"""
from __future__ import annotations

import re

from ..document import Document, Token
from ._common import (
    _cell_below,
    _clean,
    _find_label,
    _party_lines,
    _row_after,
    split_party,
)

DOC_TYPE = "bill_of_lading"

_BOOK_BL_RE = re.compile(r"\b(S\d{8,10})\s+([A-Z]{3,6}\d{6,})\b")
_WT_CBM_RE = re.compile(r"([\d,]+\.\d+)\s*KGS?\s+([\d,]+\.\d+)\s*CBM", re.I)
_MOVE_RE = re.compile(r"\b(CY[-/]CY|CY[-/]CFS|CFS[-/]CY|FCL/FCL|LCL/LCL)\b", re.I)
_ORIG_RE = re.compile(r"\b(ONE|TWO|THREE|FOUR|FIVE|SIX)\s*\(\s*(\d)\s*\)", re.I)
_PKG_RE = re.compile(r"\b(\d{1,6})\s+(CARTONS?|CTNS?|PACKAGES?|PKGS?|PCS?|BAGS?|PALLETS?)\b", re.I)
_FREIGHT_RE = re.compile(r"FREIGHT\s+(PREPAID|COLLECT)", re.I)
_ONBOARD_RE = re.compile(r"SHIPPED ON BOARD\s+(\d{4}-\d{2}-\d{2}|\d{1,2}[-/. ][A-Za-z0-9]{2,9}[-/. ]\d{2,4})", re.I)
_VESSEL_RE = re.compile(r"\b([A-Z][A-Z ]{3,28}\d{2}/\d{6})\b")
_ISSUE_RE = re.compile(r"\b([A-Z][A-Z]+,\s?[A-Z]+\s+\d{4}-\d{2}-\d{2})\b")
_CONT_RE = re.compile(r"\b([A-Z]{4}\d{7})/(\d{2}'[A-Z]{2})/([A-Z0-9]+)")
_HS_RE = re.compile(r"HS\s*CODE\s*[:.]?\s*(\d{6,10})", re.I)
_INV_RE = re.compile(r"INVOICE\s*NO\s*[:.]?\s*([A-Z0-9\-]+)", re.I)
_PO_RE = re.compile(r"PO#\s*([\d,\s]+\d)", re.I)


def matches(doc: Document) -> bool:
    head = " ".join(t.text for t in doc.pages[0].tokens).upper()
    return "COMBINED TRANSPORT OR PORT TO PORT" in head or (
        "WINCO GROUP" in head and "BILL OF LADING" in head
    )


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    toks: list[Token] = list(doc.pages[0].tokens)
    page_w = doc.pages[0].width or 595.0
    full = " ".join(t.text for t in toks)
    out: dict[str, tuple[str, float]] = {}

    def put(k: str, v: str | None, c: float) -> None:
        if v and _clean(v):
            out[k] = (_clean(v), c)

    put("document_type", "Container Bill of Lading", 0.9)

    m = _BOOK_BL_RE.search(full)
    if m:
        put("booking_number", m.group(1), 0.85)
        put("bl_number", m.group(2), 0.85)

    m = _WT_CBM_RE.search(full)
    if m:
        put("gross_weight", f"{m.group(1)} KGS", 0.85)
        put("measurement_cbm", f"{m.group(2)} CBM", 0.85)

    m = _MOVE_RE.search(full)
    put("movement_type", m.group(1).upper().replace("-", "/") if m else None, 0.85)

    m = _ORIG_RE.search(full)
    put("number_of_original_bls", f"{m.group(1).upper()}({m.group(2)})" if m else None, 0.8)

    m = _PKG_RE.search(full)
    put("number_and_kind_of_packages", f"{m.group(1)} {m.group(2).upper()}" if m else None, 0.8)

    m = _FREIGHT_RE.search(full)
    put("freight_terms", f"FREIGHT {m.group(1).upper()}" if m else None, 0.85)

    m = _ONBOARD_RE.search(full)
    put("shipped_on_board_date", m.group(1) if m else None, 0.8)

    lbl = _find_label(toks, "vessel voyage")
    if lbl:
        put("vessel_and_voyage", _cell_below(toks, lbl[1], y_hi=18, x_half=130), 0.8)
    if "vessel_and_voyage" not in out:
        m = _VESSEL_RE.search(full)
        put("vessel_and_voyage", m.group(1) if m else None, 0.7)

    m = _ISSUE_RE.search(full)
    put("place_and_date_of_issue", m.group(1) if m else None, 0.75)

    m = _INV_RE.search(full)
    put("invoice_number_and_date", f"INVOICE NO {m.group(1)}" if m else None, 0.7)

    m = _PO_RE.search(full)
    put("purchase_order_number", m.group(1) if m else None, 0.7)

    if re.search(r"(?<![A-Z])N/M(?![A-Z])", full):
        put("marks_and_numbers", "N/M", 0.7)

    conts = [f"{a}/{b}/{c}" for a, b, c in _CONT_RE.findall(full)]
    put("container_and_seal_numbers", ", ".join(dict.fromkeys(conts)) if conts else None, 0.85)
    m = re.search(r"((?:ONE|TWO|THREE|FOUR|FIVE|SIX)\s*\([\dx' A-Z]+\)\s*CONTAINERS?\s+ONLY)",
                  full, re.I)
    put("total_containers", m.group(1) if m else None, 0.7)

    # HS Code(s) from the description block — unique, in order
    codes = list(dict.fromkeys(_HS_RE.findall(full)))
    put("hs_code", ", ".join(codes) if codes else None, 0.85)

    m = re.search(r"(SHIPPER'S LOAD.*?DETENTION AT DESTINATION|PARTS OF .*?DETENTION AT DESTINATION)",
                  full, re.I | re.S)
    put("description_of_goods", m.group(1) if m else None, 0.7)

    m = re.search(r"(JEENA\s*&\s*COMPANY.*?)(?:\s+IEC\s*:|\s+EMAIL|$)", full, re.I | re.S)
    put("delivery_agent", m.group(1) if m else None, 0.7)

    # ---- labelled boxes (geometry)
    def box(starts, stops, right):
        return _party_lines(toks, page_w, starts, stops, right=right)

    for lines, ckey, nkey, akey, skey in (
        (box(("shippernameaddress", "shipper"),
             ("consignee", "bookingno", "exportreferences"), False),
         "shipper", "shipper_name", "shipper_addr", "shipper_state"),
        (box(("consignee",), ("notifyparty", "forwardingagent", "delivery"), False),
         "consignee", "consignee_nm", "consignee_addr", "consignee_state"),
        (box(("notifyparty",), ("precarriage", "vessel", "delivery"), False),
         "notify_party", "notify_name", "notify_addr", "notify_state"),
    ):
        if not lines:
            continue
        name, addr, state = split_party(lines)
        put(ckey, ", ".join(lines), 0.8)
        put(nkey, name, 0.82)
        put(akey, addr, 0.78)
        put(skey, state, 0.72)

    _STOP = ("PORT", "PLACE", "OF", "LOADING", "DISCHARGE", "DELIVERY", "TYPE",
             "MOVE", "FREIGHT", "PAYABLE", "NUMBER", "MARKS")
    for label, key in (
        ("port of loading", "port_of_loading"),
        ("port of discharge", "port_of_discharge"),
        ("place of delivery", "place_of_delivery"),
    ):
        lbl = _find_label(toks, label)
        if lbl:
            v = _cell_below(toks, lbl[1], y_hi=18, x_half=75)
            if v and v.upper().split()[0] not in _STOP:
                put(key, v, 0.75)

    return {k: v for k, v in out.items() if v[0]}
