"""Ocean Network Express ("ONE") Master Bill of Lading / Sea Waybill —
carrier -> forwarder document (Yusen Logistics' own branch offices appear as
both shipper and consignee: one office ships, another receives, on behalf of
whichever House BL this Master covers). Distinguished from the Yusen House
BL (app/parsers/yusen_hbl.py, carrier/forwarder -> actual cargo owner) by the
"BOOKING NO." / "SEA WAYBILL NO." box pair this form carries and that one
doesn't.

Seen as a native digital PDF (Thailand branch) and as a scanned/OCR'd copy
(Japan branch) — the Japan copy also runs noticeably noisier OCR (merged
words, full-width punctuation), so label geometry favours generous windows
and a handful of fields fall back to full-text regex rather than a fixed
column.
"""
from __future__ import annotations

import re

from ..document import Document, Token, group_rows
from ._common import _cell_below, _clean, _cy, _find_label, _party_lines, split_party

DOC_TYPE = "master_bl"

_CONTAINER_RE = re.compile(r"\b([A-Z]{4}\d{7})\b")
_MOVE_RE = re.compile(r"\b(FCL\s*/\s*FCL|CY\s*/\s*CY|CFS\s*/\s*CFS|LCL\s*/\s*LCL)\b", re.I)
_FREIGHT_RE = re.compile(r"FREIGHT\s+(PREPAID|COLLECT)", re.I)
_ORIGINALS_RE = re.compile(r"\[\s*(\d+)\s*\]")
_HS_RE = re.compile(r"HS\.?\s*C[O0]DE\s*[:.]?\s*(\d{4,10}(?:\.\d{2,4})?)", re.I)
_DATE_RE = re.compile(r"\b\d{1,2}\s*[-/]?\s*[A-Za-z]{3}\s*[-/]?\s*\d{2,4}\b")
_PKG_RE = re.compile(
    r"\b(\d{1,4})\b(?:(?!\d).){0,80}?\b"
    r"(PALLETS?|BAGS?|CARTONS?|PACKAGES?(?:\(S\))?|PCS?|CTNS?|PLT|PKG)\b",
    re.I | re.S,
)
_BOX_MARKER_RE = re.compile(r"\s*\b(CN|SH)>\s*$", re.I)


def matches(doc: Document) -> bool:
    head = " ".join(t.text for t in doc.pages[0].tokens).upper()
    compact = re.sub(r"[^A-Z]", "", head)
    return "OCEANNETWORKEXPRESS" in compact and "SEAWAYBILLNO" in compact


def _strip_box_marker(line: str) -> str:
    return _BOX_MARKER_RE.sub("", line).strip()


def _band_below(toks: list[Token], anchor: Token, x_lo: float, x_hi: float, *,
                 y_lo: float = 2.0, y_hi: float = 14.0) -> str:
    """Like _cell_below, but an explicit x range instead of a symmetric
    x_half around the anchor's own centre.

    Several of this form's label pairs (Port of Loading / Final
    Destination, Port of Discharge / Place of Delivery, ...) sit close
    enough together, with long enough values, that no single x_half can
    both reach a long value's far end and stay clear of the next column —
    a fixed column boundary (this form's grid repeats the same x positions
    across every such row) is the only thing that does both.
    """
    below = [
        t for t in toks
        if anchor.y1 + y_lo <= _cy(t) <= anchor.y1 + y_hi and x_lo <= t.x0 <= x_hi
    ]
    if not below:
        return ""
    y0 = min(t.y0 for t in below)
    row = sorted((t for t in below if abs(t.y0 - y0) <= 4), key=lambda t: t.x0)
    return _clean(" ".join(t.text for t in row))


def _find_exact_label(toks: list[Token], words: list[str]) -> Token | None:
    """First run of consecutive same-row tokens matching ``words`` exactly.

    "Service Contract No." sits on the same crowded row as "Freight &
    Charges Payable At/By:" — _find_label's substring match would happily
    start its accumulation window at an *earlier*, unrelated token on that
    row (e.g. "&") as long as the target phrase turns up anywhere within
    the next few tokens, handing back the wrong anchor. Requiring an exact,
    ordered token match avoids that specific trap.
    """
    wanted = [w.strip(" :.").upper() for w in words]
    for i in range(len(toks) - len(wanted) + 1):
        window = toks[i:i + len(wanted)]
        if any(abs(window[0].y0 - t.y0) > 4.0 for t in window):
            continue
        if [t.text.strip(" :.").upper() for t in window] == wanted:
            return window[0]
    # OCR on a scanned page can glue the whole label into one token
    # ("SERVICECONTRACTNO.") — fall back to a compact substring match.
    compact_target = re.sub(r"[^A-Z]", "", "".join(wanted))
    for t in toks:
        if compact_target in re.sub(r"[^A-Z]", "", t.text.upper()):
            return t
    return None


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    toks: list[Token] = list(doc.pages[0].tokens)
    page_w = doc.pages[0].width or 595.0
    full = " ".join(t.text for t in toks)
    all_text = " ".join(t.text for p in doc.pages for t in p.tokens)
    out: dict[str, tuple[str, float]] = {}

    def put(k: str, v: str | None, c: float) -> None:
        if v and _clean(v):
            out[k] = (_clean(v), c)

    if re.search(r"SEA\s*WAYBILL", full, re.I):
        put("document_type", "Sea Waybill", 0.85)
    elif re.search(r"BILL\s*OF\s*LADING", full, re.I):
        put("document_type", "Master Bill of Lading", 0.8)

    if re.search(r"COPY\s*NON\s*-?\s*NEGOTIABLE", full, re.I):
        put("bl_release_type", "Copy Non-Negotiable", 0.8)
    elif re.search(r"ORIGINAL\s*NON\s*-?\s*NEGOTIABLE", full, re.I):
        put("bl_release_type", "Original Non-Negotiable", 0.8)
    elif re.search(r"\bSURRENDERED\b", all_text, re.I):
        put("bl_release_type", "Surrendered", 0.7)

    # ---- the two top-right id boxes, side by side: value sits directly
    # below its own label, not inline — a generous x_half covers the id's
    # own width without reaching into the neighbouring box.
    book_lbl = _find_label(toks, "bookingno")
    if book_lbl:
        put("booking_number", _cell_below(toks, book_lbl[1], y_hi=16, x_half=70), 0.85)

    bl_lbl = _find_label(toks, "seawaybillno")
    if bl_lbl:
        put("bl_number", _cell_below(toks, bl_lbl[1], y_hi=16, x_half=70), 0.85)

    # ---- labelled party boxes, stacked in the left column. A hidden
    # per-box marker token ("CN>"/"SH>") sometimes glues onto the last
    # address line — strip it before splitting name/address/state, or the
    # trailing-country detection in split_party silently fails to fire.
    #
    # The Notify Party box's own value is routinely "SAME AS CONSIGNEE" —
    # that phrase's own "CONSIGNEE" token can sit earlier in the PDF's raw
    # token list than the real "CONSIGNEE" box label (text layer order
    # here is not the same as visual/y order), so an unqualified label
    # search can lock onto it and read the wrong box entirely. Every real
    # box label in this form starts within ~70pt of the left margin, while
    # a label word appearing *inside* a value sits well to the right of
    # that — so tokens beyond the margin are excluded before searching.
    # The false-positive token never falls inside the Shipper or Consignee
    # boxes' own content range (it sits well below both, right where the
    # Notify Party box's real value is) — so stripping it only helps those
    # two boxes find the right label and never costs them real content.
    # The Notify box must keep the unfiltered tokens, since that exact
    # phrase *is* its legitimate value.
    _LABEL_MARGIN = 70.0
    _RISKY_LABEL_WORDS = {"CONSIGNEE", "SHIPPER", "NOTIFY"}
    margin_toks = [
        t for t in toks
        if not (t.text.strip(" :").upper() in _RISKY_LABEL_WORDS and t.x0 > _LABEL_MARGIN)
    ]

    def box(label_toks, starts, stops, reach=80.0):
        lines = _party_lines(label_toks, page_w, starts, stops, right=False, mid_frac=0.5, reach=reach)
        return [_strip_box_marker(ln) for ln in lines]

    for lines, ckey, nkey, akey, skey in (
        (box(margin_toks, ("shipperexporter", "shipper"), ("consignee",)),
         "shipper", "shipper_name", "shipper_addr", "shipper_state"),
        (box(margin_toks, ("consignee",), ("notifyparty",), reach=60.0),
         "consignee", "consignee_nm", "consignee_addr", "consignee_state"),
        (box(toks, ("notifyparty",), ("precarriageby",), reach=40.0),
         "notify_party", "notify_name", "notify_addr", "notify_state"),
    ):
        if not lines:
            continue
        name, addr, state = split_party(lines)
        put(ckey, ", ".join(lines), 0.78)
        put(nkey, name, 0.8)
        put(akey, addr, 0.75)
        put(skey, state, 0.7)

    # ---- routing. This form repeats the same 3-column grid (x~0-182 /
    # 182-340 / 340+) across both label rows below, so each value is read
    # by its column's fixed boundaries rather than a width guessed from
    # one sample — a short "PIPAVAV, INDIA" and a long "NHAVA SHEVA PORT IN
    # INDIA" both live in the same column and must both be read whole.
    _COL1, _COL2, _COL3 = 182.0, 340.0, 620.0

    pre_lbl = _find_label(toks, "precarriageby")
    if pre_lbl:  # usually left blank on this form
        put("pre_carriage_by", _band_below(toks, pre_lbl[1], 0, _COL1, y_hi=10), 0.6)

    recv_lbl = _find_label(toks, "placeofreceipt")
    if recv_lbl:
        put("place_of_receipt", _band_below(toks, recv_lbl[1], _COL1, _COL2), 0.78)

    vessel_lbl = _find_label(toks, "oceanvesselvoyagenoflag")
    if vessel_lbl:
        put("vessel_and_voyage", _band_below(toks, vessel_lbl[1], 0, _COL1), 0.78)

    pol_lbl = _find_label(toks, "portofloading")
    if pol_lbl:
        put("port_of_loading", _band_below(toks, pol_lbl[1], _COL1, _COL2), 0.78)

    dest_lbl = _find_label(toks, "finaldestination")
    if dest_lbl:
        put("final_destination", _band_below(toks, dest_lbl[1], _COL2, _COL3), 0.6)

    pod_lbl = _find_label(toks, "portofdischarge")
    if pod_lbl:
        put("port_of_discharge", _band_below(toks, pod_lbl[1], 0, _COL1), 0.78)

    pod2_lbl = _find_label(toks, "placeofdelivery")
    if pod2_lbl:
        put("place_of_delivery", _band_below(toks, pod2_lbl[1], _COL1, _COL2), 0.75)

    # "Type of Movement" value ("FCL / FCL", "CY / CY") sits in a box too
    # wide to isolate safely by geometry alone (it overlaps the neighbouring
    # Place of Delivery column) — a fixed-vocabulary full-text regex is the
    # reliable read here, same approach as app/parsers/container_bl.py.
    moves = list(dict.fromkeys(m.upper().replace(" ", "") for m in _MOVE_RE.findall(all_text)))
    put("movement_type", " ".join(moves) if moves else None, 0.75)

    # ---- cargo. The goods/totals block can spill onto page 2 on a longer
    # container list, so every cargo-field scan below works across every
    # page's tokens, not just page 1's.
    all_toks = [t for p in doc.pages for t in p.tokens]

    conts = list(dict.fromkeys(_CONTAINER_RE.findall(all_text)))
    put("container_and_seal_numbers", ", ".join(conts) if conts else None, 0.85)

    # The totals row — not any individual container row above it — carries
    # the shipment's real package count, weight and measurement, printed as
    # "<qty> <SHIPPER'S LOAD & COUNT/STC.> <wt>KGS <cbm>CBM" with the unit
    # word ("PALLETS"/"BAGS"/...) wrapped onto the next line in the same
    # narrow column. Weight/measurement are glued number+unit tokens
    # ("5505.000KGS"), not a separate number + unit pair. Found once, per
    # page (the goods block can spill onto page 2 on a longer container
    # list), then the quantity is read off that same row and its unit off
    # the row directly beneath it, rather than taking the first "<n> <unit>"
    # match in reading order — which would just be the first container's
    # own single-unit row ("1 BAG"), not the shipment total.
    _wt_re = re.compile(r"^([\d,]+\.\d{2,3})KGS?$", re.I)
    _cbm_re = re.compile(r"^([\d,]+\.\d{2,3})(?:CBM|M3)$", re.I)
    _unit_re = re.compile(r"^(PALLETS?|BAGS?|CARTONS?|PACKAGES?(?:\(S\))?|PCS?|CTNS?|PLT|PKG)$", re.I)
    for pg in sorted({t.page for t in all_toks}):
        page_toks = [t for t in all_toks if t.page == pg]
        page_rows = group_rows(page_toks)
        for i, row in enumerate(page_rows):
            wt = next((m.group(1) for t in row if (m := _wt_re.match(t.text))), None)
            cbm = next((m.group(1) for t in row if (m := _cbm_re.match(t.text))), None)
            if not (wt and cbm):
                continue
            put("gross_weight", f"{wt} KGS", 0.8)
            put("measurement_cbm", f"{cbm} CBM", 0.8)
            qty = next((t.text for t in row if re.fullmatch(r"\d{1,4}", t.text)), None)
            if qty and i + 1 < len(page_rows):
                unit = next((t.text for t in page_rows[i + 1] if _unit_re.match(t.text)), None)
                if unit:
                    put("number_and_kind_of_packages", f"{qty} {unit.upper()}", 0.75)
            break
        if "gross_weight" in out:
            break

    if "number_and_kind_of_packages" not in out:
        m = _PKG_RE.search(all_text)
        put("number_and_kind_of_packages", f"{m.group(1)} {m.group(2).upper()}" if m else None, 0.6)

    hs_codes = list(dict.fromkeys(_HS_RE.findall(all_text)))
    put("hs_code", ", ".join(hs_codes) if hs_codes else None, 0.75)

    # ---- commercial. Freight terms print on page 2 only (next to the
    # cargo detail), not page 1.
    m = _FREIGHT_RE.search(all_text)
    put("freight_terms", f"FREIGHT {m.group(1).upper()}" if m else None, 0.85)

    # "Freight & Charges Payable At / By:" and "Service Contract No." sit
    # side by side on one row; each value is a plain id/place directly
    # below its own label's *start* (not spanning the label's full width,
    # which would bleed into the next box on this row).
    payable_lbl = _find_label(toks, "freightchargespayableatby")
    if payable_lbl:
        put("freight_payable_at", _cell_below(toks, payable_lbl[0], y_hi=10, x_half=50), 0.65)

    contract_anchor = _find_exact_label(toks, ["SERVICE", "CONTRACT", "NO."])
    if contract_anchor:
        put("service_contract_number",
            _cell_below(toks, contract_anchor, y_hi=14, x_half=50), 0.7)

    m = _ORIGINALS_RE.search(full)
    put("number_of_original_bls", m.group(1) if m else None, 0.75)

    board_lbl = _find_label(toks, "dateladenonboard")
    if board_lbl:
        v = _cell_below(toks, board_lbl[1], y_hi=18, x_half=60)
        m2 = _DATE_RE.search(v) or _DATE_RE.search(all_text)
        put("shipped_on_board_date", m2.group(0) if m2 else (v or None), 0.7)

    issue_lbl = _find_label(toks, "placeofbillsissue")
    if issue_lbl:
        place = _cell_below(toks, issue_lbl[1], y_hi=18, x_half=70)
        dated_lbl = _find_label(toks, "dated", after_y=issue_lbl[1].y1)
        date_val = _cell_below(toks, dated_lbl[1], y_hi=18, x_half=70) if dated_lbl else ""
        if not date_val:
            m3 = _DATE_RE.search(all_text)
            date_val = m3.group(0) if m3 else ""
        if place or date_val:
            put("place_and_date_of_issue", ", ".join(p for p in (place, date_val) if p), 0.7)

    # Every sample of this form signs off with the same fixed carrier name —
    # a compact, punctuation-agnostic presence check is far more reliable
    # than reconstructing the exact wording, since a scanned copy's OCR can
    # turn the ")," into a full-width "），" with no ASCII comma at all.
    compact_all = re.sub(r"[^A-Z]", "", all_text.upper())
    if "OCEANNETWORKEXPRESS" in compact_all and "ASCARRIER" in compact_all:
        put("carrier", "Ocean Network Express Pte. Ltd. (ONE), AS CARRIER", 0.8)

    return {k: v for k, v in out.items() if v[0]}
