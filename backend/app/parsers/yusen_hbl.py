"""Yusen Logistics House Bill of Lading — "for Multimodal Transport or Ocean
Transport" form issued by Yusen Logistics (as carrier or as agent) to the
actual cargo consignee. Seen both as a native digital PDF and, more often, as
a scanned/faxed copy read through OCR — labels are reliable (fixed print),
so this leans on geometry (label -> cell) rather than full-text regex for
anything whose on-page position can shift a few points between a clean OCR
pass and a noisy one.

Distinguished from a Master Bill of Lading (carrier -> forwarder, e.g. a
Muskaan Group "BL DRAFT") by carrier branding — a different template owns
that form if/when samples for it are added.
"""
from __future__ import annotations

import re

from ..document import Document, Token
from ._common import _cell_below, _clean, _cx, _cy, _find_label, _party_lines, split_party

DOC_TYPE = "house_bl"

_ID_SHAPE_RE = re.compile(r"^[A-Z]{2,12}\d{4,12}$")
_ID_EXCLUDE = {"BILL", "NO", "OF", "LADING", "COPY", "ORIGINAL"}

_CONTAINER_RE = re.compile(r"\b([A-Z]{4}\d{7})\b")
_FREIGHT_RE = re.compile(r"FREIGHT\s+(PREPAID|COLLECT)", re.I)
# Printed as "1 (ONE)" / "3 (THREE)" — digit first, spelled-out word in
# parens, not the other way round.
_ORIGINALS_RE = re.compile(
    r"\b(\d+)\s*\(\s*(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)\s*\)", re.I
)
_TOTAL_CONT_RE = re.compile(
    r"\b(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE)\s*CONTAINERS?\s*\(?S?\)?",
    re.I,
)
_PKG_RE = re.compile(
    r"\b(\d{1,6})\s*(PLT|PKG|PALLETS?(?:\(S\))?|PACKAGES?(?:\(S\))?|CARTONS?|CTNS?|PCS?|BAGS?(?:\(S\))?)\b",
    re.I,
)
_DATE_RE = re.compile(r"\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4}\b")
_HS_RE = re.compile(r"HS\.?\s*C[O0]DE\s*[:.]?\s*(\d{6,10})", re.I)
# "No." is printed inconsistently across samples ("IEC NO.0512052298" vs
# "* IEC : 0588000591") — optional, not required.
_IEC_RE = re.compile(r"\bIEC\.?\s*(?:N[O0]\.?)?\s*[:.]?\s*(\d{6,12})", re.I)
_GSTIN_RE = re.compile(r"\bGST(?:IN)?\.?\s*(?:N[O0]\.?)?\s*[:.]?\s*([0-9A-Z]{10,16})", re.I)
# The strict Indian PAN shape (5 letters, 4 digits, 1 letter) rather than a
# loose alnum capture — "PAN" alone would otherwise false-match inside
# nearby cargo text like "PANEL ASSY".
_PAN_RE = re.compile(r"\bPAN\s*(?:N[O0]\.?)?\s*[:.]?\s*([A-Z]{5}\d{4}[A-Z])\b", re.I)
# "INV" itself OCRs cleanly; the rest of "(O|0)ICE" is dropped from the
# match rather than spelled out, since an O/0 misread there is common.
_INVOICE_RE = re.compile(r"INV[A-Z0]{0,4}\.?\s*N[O0]\.?\s*[:.]?\s*([A-Z0-9/.\-]+)", re.I)


def matches(doc: Document) -> bool:
    head = " ".join(t.text for t in doc.pages[0].tokens).upper()
    compact = re.sub(r"[^A-Z]", "", head)
    # The subtitle under "BILL OF LADING" is this form's actual fingerprint —
    # just checking for "YUSEN" anywhere on the page isn't specific enough,
    # since Yusen Logistics shows up as the *consignee*/notify party (not the
    # issuer) on a different carrier's own Master BL, e.g. one issued by
    # Muskaan ("for Combined Transport Shipment or Port to Port Shipment").
    return "FORMULTIMODALTRANSPORTOROCEANTRANSPORT" in compact


def _top_right_id(doc: Document) -> str:
    page = doc.pages[0]
    w, h = page.width or 595.0, page.height or 842.0
    cands = [
        t for t in page.tokens
        if t.x0 >= w * 0.6 and t.y0 <= h * 0.12
        and _ID_SHAPE_RE.match(t.text.strip())
        and t.text.strip().upper() not in _ID_EXCLUDE
    ]
    cands.sort(key=lambda t: t.y0)
    return cands[0].text.strip() if cands else ""


def _label_cell(toks: list[Token], phrase: str, *, x_half: float = 45.0,
                y_hi: float = 18.0, same_row_gap: float = 45.0) -> str:
    """Value for a boxed label: same-row remainder to the right (short
    inline values like "CY"), plus whatever sits in the cell directly below
    it (the common case — label on its own line, value wrapped beneath).

    The form packs several boxes per row with only ~90-130pt between label
    starts, so both windows default narrow — wide enough for one column,
    narrow enough to stop before the next label bleeds in.
    """
    lbl = _find_label(toks, phrase)
    if not lbl:
        return ""
    anchor = lbl[1]
    same_row = sorted(
        (t for t in toks if abs(_cy(t) - _cy(anchor)) <= 4.0
         and 0 < t.x0 - anchor.x1 <= same_row_gap),
        key=lambda t: t.x0,
    )
    inline = _clean(" ".join(t.text for t in same_row))
    below = _cell_below(toks, anchor, y_hi=y_hi, x_half=x_half)
    parts = [p for p in (inline, below) if p]
    return _clean(" ".join(parts))


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    toks: list[Token] = list(doc.pages[0].tokens)
    page_w = doc.pages[0].width or 595.0
    full = " ".join(t.text for t in toks)
    all_text = " ".join(t.text for p in doc.pages for t in p.tokens)
    out: dict[str, tuple[str, float]] = {}

    def put(k: str, v: str | None, c: float) -> None:
        if v and _clean(v):
            out[k] = (_clean(v), c)

    put("document_type", "House Bill of Lading", 0.85)

    bl_no = _top_right_id(doc)
    put("bl_number", bl_no, 0.82 if bl_no else 0.0)

    if re.search(r"\bSURRENDERED\b", all_text, re.I):
        put("bl_release_type", "Surrendered", 0.7)
    elif re.search(r"COPY\s*NON-?NEGOTIABLE", full, re.I):
        put("bl_release_type", "Copy Non-Negotiable", 0.8)
    elif re.search(r"\bORIGINAL\b", full, re.I):
        put("bl_release_type", "Original", 0.6)

    # ---- labelled boxes (party blocks, stacked in the left column)
    # "referenceonly" (not "export/import reference") as the stop phrase —
    # OCR regularly misreads "Import" as "lmport" on noisy scans, and the
    # alnum-stripped match is literal, so a stop phrase containing that "I"
    # silently fails to fire; "...reference only)" is the unambiguous tail
    # both the Export/Import and Forwarding Agent reference boxes share.
    def box(starts, stops, reach=80.0):
        return _party_lines(toks, page_w, starts, stops, right=False, mid_frac=0.55, reach=reach)

    for lines, ckey, nkey, akey, skey in (
        (box(("shipper",), ("consignee", "billno", "billoflading")),
         "shipper", "shipper_name", "shipper_addr", "shipper_state"),
        (box(("consignee",), ("notifyparty", "referenceonly"), reach=60.0),
         "consignee", "consignee_nm", "consignee_addr", "consignee_state"),
        (box(("notifyparty",), ("referenceonly", "forwardingagent", "precarriage"), reach=55.0),
         "notify_party", "notify_name", "notify_addr", "notify_state"),
    ):
        if not lines:
            continue
        name, addr, state = split_party(lines)
        put(ckey, ", ".join(lines), 0.78)
        put(nkey, name, 0.8)
        put(akey, addr, 0.75)
        put(skey, state, 0.7)

    # a second ("Also Notify") block, when present, sits on a continuation
    # page as its own labelled line — not a boxed field, so read it as text.
    m = re.search(r"ALSO\s*NOTIFY\s*:?(.{0,250}?)(?:CONTACTEMAIL|$)", all_text.replace(" ", ""),
                  re.I)
    if m:
        put("notify_party_2", m.group(0)[:260], 0.6)

    # ---- routing (label above a short value, occasionally inline) — each
    # row packs 2-3 boxes ~130pt apart, so columns stay narrow on purpose.
    put("pre_carriage_by", _label_cell(toks, "precarriageby", y_hi=8), 0.7)
    put("place_of_receipt", _label_cell(toks, "placeofreceipt"), 0.72)
    put("port_of_loading", _label_cell(toks, "portofloading"), 0.75)
    put("port_of_discharge", _label_cell(toks, "portofdischarge"), 0.75)
    put("place_of_delivery", _label_cell(toks, "placeofdelivery", x_half=85), 0.72)

    vessel_lbl = _find_label(toks, "oceanvessel")
    voy_lbl = _find_label(toks, "voyno")
    vessel = _cell_below(toks, vessel_lbl[1], y_hi=18, x_half=85) if vessel_lbl else ""
    voy = _cell_below(toks, voy_lbl[1], y_hi=18, x_half=45) if voy_lbl else ""
    if vessel or voy:
        put("vessel_and_voyage", " / ".join(p for p in (vessel, voy) if p), 0.78)

    # ---- cargo
    conts = list(dict.fromkeys(_CONTAINER_RE.findall(full)))
    put("container_and_seal_numbers", ", ".join(conts) if conts else None, 0.85)

    m = _TOTAL_CONT_RE.search(full)
    put("total_containers", m.group(0).upper() if m else None, 0.75)

    m = _PKG_RE.search(full)
    put("number_and_kind_of_packages", f"{m.group(1)} {m.group(2).upper()}" if m else None, 0.75)

    # Gross weight / measurement: the first row after the column headers
    # pairing two decimal-shaped numbers is the shipment total (repeated,
    # unchanged, on the totals row further down the same table).
    rows = sorted({round(t.y0) for t in toks})
    for y in rows:
        row = sorted((t for t in toks if abs(t.y0 - y) <= 4), key=lambda t: t.x0)
        nums = [t.text for t in row if re.fullmatch(r"[\d,]+[.,_]\d{2,3}", t.text)]
        if len(nums) >= 2:
            gw = nums[0].replace("_", ".")
            cbm = nums[-1].replace("_", ".")
            put("gross_weight", f"{gw} KGS", 0.75)
            put("measurement_cbm", f"{cbm} CBM", 0.75)
            break

    hs_codes = list(dict.fromkeys(_HS_RE.findall(all_text)))
    put("hs_code", ", ".join(hs_codes) if hs_codes else None, 0.8)

    # Digital-page only: this matches "SAID TO CONTAIN" through to a stop
    # marker in *array* order, which is reading order for a real PDF text
    # layer but NOT for an OCR'd page — RapidOCR's token order follows box
    # detection, not layout, so the same regex on a scanned page would grab
    # whatever token happened to follow in the array (e.g. an unrelated
    # number from the weight column) instead of the actual description.
    if not doc.pages[0].is_scanned:
        m = re.search(
            r'SAID\s*TO\s*CONTAIN"?\s*(.+?)(?:CLEAN ON BOARD|FREIGHT\s+(?:PREPAID|COLLECT)|$)',
            full, re.I,
        )
        put("description_of_goods", m.group(1)[:300] if m else None, 0.6)

    # ---- commercial
    m = _FREIGHT_RE.search(full)
    put("freight_terms", f"FREIGHT {m.group(1).upper()}" if m else None, 0.85)

    # Ex. Rate / Prepaid at / Payable at / Place of Bill(s) Issued / Dated
    # pack five boxes into one row (~100-120pt apart) — narrow columns, no
    # same-row grab (the label row carries only labels; values sit below).
    put("freight_payable_at", _label_cell(toks, "payableat", x_half=40, y_hi=14, same_row_gap=0), 0.7)
    put("prepaid_at", _label_cell(toks, "prepaidat", x_half=40, y_hi=14, same_row_gap=0), 0.65)

    m = _ORIGINALS_RE.search(full)
    put("number_of_original_bls", f"{m.group(1)}({m.group(2).upper()})" if m else None, 0.78)

    m = _DATE_RE.search(full)
    put("shipped_on_board_date", m.group(0) if m else None, 0.6)

    issued_lbl = _find_label(toks, "placeofbillsissued")
    if issued_lbl:
        place = _cell_below(toks, issued_lbl[1], y_hi=18, x_half=45)
        m2 = _DATE_RE.search(full)
        if place or m2:
            put("place_and_date_of_issue",
                ", ".join(p for p in (place, m2.group(0) if m2 else "") if p), 0.72)

    carrier_lbl = _find_label(toks, "ascarrier")
    if carrier_lbl:
        put("carrier", _cell_below(toks, carrier_lbl[1], y_hi=20, x_half=110), 0.78)

    agent_lines = _party_lines(
        toks, page_w, ("fordeliveryofgoodspleaseapplyto",), ("ladenonboardvessel",),
        right=False, mid_frac=0.55,
    )
    put("delivery_agent", ", ".join(agent_lines) if agent_lines else None, 0.68)

    # ---- references
    m = _INVOICE_RE.search(all_text)
    put("invoice_number_and_date", m.group(1) if m else None, 0.65)

    m = re.search(r"CUSTOMER\s*ITEM\s*N[O0]\.?\s*[:.]?\s*([A-Z0-9]+)", all_text, re.I)
    put("customer_item_number", m.group(1) if m else None, 0.65)

    m = _IEC_RE.search(all_text)
    put("iec_code", m.group(1) if m else None, 0.75)

    m = _GSTIN_RE.search(all_text)
    put("gstin", m.group(1) if m else None, 0.75)

    m = _PAN_RE.search(all_text)
    put("pan_no", m.group(1) if m else None, 0.75)

    return {k: v for k, v in out.items() if v[0]}
