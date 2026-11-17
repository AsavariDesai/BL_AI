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
from ._common import (
    _ALNUM_RE, _cell_below, _cell_below_loc, _clean, _column_below, _cx, _cy, _find_label,
    _party_lines, split_party,
)

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
    # The spelled-out count and "CONTAINERS" are often separated by a
    # parenthesised digit restating it ("TWO (2) CONTAINERS ONLY"), and the
    # whole phrase may trail off with "ONLY" — both optional.
    r"\b(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE)\s*"
    r"(?:\(\s*\d{1,2}\s*\))?\s*CONTAINERS?\s*\(?S?\)?\s*(?:ONLY)?\b",
    re.I,
)
_PKG_RE = re.compile(
    r"\b(\d{1,6})\s*(PLT|PKG|PALLETS?(?:\(S\))?|PACKAGES?(?:\(S\))?|CARTONS?|CTNS?|PCS?|BAGS?(?:\(S\))?)\b",
    re.I,
)
_DATE_RE = re.compile(r"\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4}\b")
# HS codes print either as a plain digit run (6-10 digits) or tariff-style
# with an embedded decimal point ("8524.9190") — try the dotted shape first
# since it's the more specific of the two.
_HS_RE = re.compile(r"HS\.?\s*C[O0]DE\s*[:.]?\s*(\d{4}\.\d{2,6}|\d{6,10})", re.I)
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
                y_hi: float = 18.0, same_row_gap: float = 45.0,
                ) -> tuple[str, tuple[float, float, float, float] | None]:
    """Value for a boxed label: same-row remainder to the right (short
    inline values like "CY"), plus whatever sits in the cell directly below
    it (the common case — label on its own line, value wrapped beneath).
    Returns the value's own bbox alongside it — several of this form's cells
    hold a short, common value ("CY", a bare port name) that can also occur
    elsewhere on the page, so re-finding it afterwards by a page-wide text
    search (the generic fallback used when a parser doesn't supply a bbox)
    can land on the wrong occurrence; reading it straight from the tokens
    this cell was built from avoids that.

    The form packs several boxes per row with only ~90-130pt between label
    starts, so both windows default narrow — wide enough for one column,
    narrow enough to stop before the next label bleeds in.
    """
    lbl = _find_label(toks, phrase)
    if not lbl:
        return "", None
    anchor = lbl[1]
    same_row = sorted(
        (t for t in toks if abs(_cy(t) - _cy(anchor)) <= 4.0
         and 0 < t.x0 - anchor.x1 <= same_row_gap),
        key=lambda t: t.x0,
    )
    inline = _clean(" ".join(t.text for t in same_row))
    below_toks = [
        t for t in toks
        if anchor.y1 + 2.0 <= _cy(t) <= anchor.y1 + y_hi
        and abs(_cx(t) - _cx(anchor)) <= x_half
    ]
    below = ""
    if below_toks:
        y0 = min(t.y0 for t in below_toks)
        below_toks = [t for t in below_toks if abs(t.y0 - y0) <= 4]
        below_toks.sort(key=lambda t: t.x0)
        below = _clean(" ".join(t.text for t in below_toks))
    parts = [p for p in (inline, below) if p]
    value = _clean(" ".join(parts))
    if not value:
        return "", None
    cell_toks = list(same_row) + below_toks
    bbox = (min(t.x0 for t in cell_toks), min(t.y0 for t in cell_toks),
            max(t.x1 for t in cell_toks), max(t.y1 for t in cell_toks))
    return value, bbox


def _find_exact_label(page_tokens, label: str) -> Token | None:
    """A single token whose alnum-only text equals ``label`` exactly.

    `_find_label`'s substring match is unsafe for a label this short: "PAN"
    is also a substring of plenty of unrelated words that land on the same
    page — "JAPAN" among them, and this exact document's Place of Receipt /
    Port of Loading are both "TOKYO, JAPAN".
    """
    target = _ALNUM_RE.sub("", label.lower())
    for t in page_tokens:
        if _ALNUM_RE.sub("", t.text.lower()) == target:
            return t
    return None


def _row_bbox_for_label(doc: Document, phrase: str, value: str | None,
                        ) -> tuple[int, tuple[float, float, float, float]] | None:
    """Best-effort bbox for ``value`` taken from its own label's row, for an
    inline identifier (PAN/IEC/GSTIN) read via a doc-wide regex rather than
    `_label_cell`. A short ID's digits can recur as a substring of a longer,
    unrelated one elsewhere (a PAN is literally embedded inside its own
    GSTIN) — confirming the row actually contains it avoids handing the
    generic page-text locator a value it would gladly mismatch."""
    if not value:
        return None
    needle = re.sub(r"\s+", "", value).upper()
    if not needle:
        return None
    for page in doc.pages:
        anchor = _find_exact_label(page.tokens, phrase)
        if not anchor:
            continue
        row = sorted(
            (t for t in page.tokens if abs(_cy(t) - _cy(anchor)) <= 4.0
             and t.x0 >= anchor.x1 - 2),
            key=lambda t: t.x0,
        )
        if not row:
            continue
        row_text = re.sub(r"\s+", "", "".join(t.text for t in row)).upper()
        if needle in row_text:
            return page.number, (
                min(t.x0 for t in row), min(t.y0 for t in row),
                max(t.x1 for t in row), max(t.y1 for t in row),
            )
    return None


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    toks: list[Token] = list(doc.pages[0].tokens)
    page_w = doc.pages[0].width or 595.0
    full = " ".join(t.text for t in toks)
    all_text = " ".join(t.text for p in doc.pages for t in p.tokens)
    out: dict[str, tuple[str, float]] = {}

    def put(k: str, v: str | None, c: float,
            bbox: tuple[float, float, float, float] | None = None,
            bbox_page: int = 1) -> None:
        if v and _clean(v):
            out[k] = (_clean(v), c)
            if bbox is not None:
                out[f"__bbox__:{k}"] = (bbox_page, bbox)

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
    v, b = _label_cell(toks, "precarriageby", y_hi=8)
    put("pre_carriage_by", v, 0.7, bbox=b)
    v, b = _label_cell(toks, "placeofreceipt")
    put("place_of_receipt", v, 0.72, bbox=b)
    v, b = _label_cell(toks, "portofloading")
    put("port_of_loading", v, 0.75, bbox=b)
    v, b = _label_cell(toks, "portofdischarge")
    put("port_of_discharge", v, 0.75, bbox=b)
    v, b = _label_cell(toks, "placeofdelivery", x_half=85)
    put("place_of_delivery", v, 0.72, bbox=b)

    # "Ocean Vessel" and "Voy. No." are each their own labelled box on this
    # form (unlike one_masterbl.py's merged cell) — read and highlighted
    # independently, no need to split a joined value apart.
    vessel_lbl = _find_label(toks, "oceanvessel")
    if vessel_lbl:
        v, b = _cell_below_loc(toks, vessel_lbl[1], y_hi=18, x_half=85)
        put("vessel_name", v, 0.78, bbox=b)
    voy_lbl = _find_label(toks, "voyno")
    if voy_lbl:
        v, b = _cell_below_loc(toks, voy_lbl[1], y_hi=18, x_half=45)
        put("voyage_number", v, 0.78, bbox=b)

    # ---- cargo
    conts = list(dict.fromkeys(_CONTAINER_RE.findall(full)))
    put("container_and_seal_numbers", ", ".join(conts) if conts else None, 0.85)

    # "Marks and Nos." heads the same left-hand column as the Container/Seal
    # No. rows on this form — its own label sits a line below theirs, so the
    # value is read as a multi-line column rather than a single cell, with
    # any line that is itself a container number (the other field sharing
    # that column) dropped. Positional, so kept at a modest confidence —
    # a reviewer correction teaches the exact anchor for this template via
    # the learning loop (see learning.py) and future same-format docs read
    # it precisely from then on.
    marks_lbl = (_find_label(toks, "marksandnos") or _find_label(toks, "marksnos")
                 or _find_label(toks, "marksnumbers"))
    if marks_lbl:
        marks = _column_below(toks, marks_lbl[1], skip=_CONTAINER_RE)
        put("marks_and_numbers", marks[:300] if marks else None, 0.55)

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
    v, b = _label_cell(toks, "payableat", x_half=40, y_hi=14, same_row_gap=0)
    put("freight_payable_at", v, 0.7, bbox=b)
    v, b = _label_cell(toks, "prepaidat", x_half=40, y_hi=14, same_row_gap=0)
    put("prepaid_at", v, 0.65, bbox=b)

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
    iec = m.group(1) if m else None
    loc = _row_bbox_for_label(doc, "iec", iec)
    put("iec_code", iec, 0.75, bbox=loc[1] if loc else None, bbox_page=loc[0] if loc else 1)

    m = _GSTIN_RE.search(all_text)
    gstin = m.group(1) if m else None
    loc = _row_bbox_for_label(doc, "gst", gstin)
    put("gstin", gstin, 0.75, bbox=loc[1] if loc else None, bbox_page=loc[0] if loc else 1)

    # PAN's own digits are a literal substring of this party's GSTIN (a
    # GSTIN is built from state code + PAN + entity suffix) — printed just
    # below it, that makes the GSTIN line the page's *first* occurrence of
    # the PAN value, so the generic page-text locator used when no bbox is
    # supplied would otherwise highlight the GSTIN line instead of PAN's
    # own. Locating it from its own "PAN" label row sidesteps that.
    m = _PAN_RE.search(all_text)
    pan = m.group(1) if m else None
    loc = _row_bbox_for_label(doc, "pan", pan)
    put("pan_no", pan, 0.75, bbox=loc[1] if loc else None, bbox_page=loc[0] if loc else 1)

    return {k: v for k, v in out.items() if v[0]}
