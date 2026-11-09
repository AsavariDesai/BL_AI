"""Global Steel Ships "LINER BILL OF LADING" (Amended Conlinebill), issued
through PAREKH MARINE SERVICES as agents — BL numbers of the form
``GSSWSCO38065B`` / ``GSSWAME38958A``.

The form ships in two flavours: one where the box labels are real text
(SHIPPER/EXPORTER, CONSIGNEE, PORT OF LOADING …), and one where they are a
background image and only the filled-in values are text. This parser handles
both — label-anchored when the labels exist, fixed column-band + left-column
block clustering when they don't — and pulls **every** Shipping Bill number off
the front-page table / the B/L Rider page.
"""
from __future__ import annotations

import re

from ..document import Document, Token
from ._common import _cell_below, _clean, _find_label, _lines, _party_lines, split_party

DOC_TYPE = "bill_of_lading"

_BL_RE = re.compile(r"\b(GSS?W[A-Z]{2,4}\d{4,6}[A-Z]?)\b")
_AGENT_RE = re.compile(
    r"(PAREKH\s+MARINE\s+SERVICES[A-Z. ]*?,?\s*AS\s+AGENTS)", re.I
)
_CARRIER_RE = re.compile(
    r"CARRIER\s*NAME\s*[:.\-]*\s*([A-Z0-9][A-Za-z0-9 /&.\-]{2,40}?)\s+"
    r"(?=FREIGHT|NET\s*WT|GROSS\s*WT|HS\s*CODE|TOTAL\s*NO|PROJECT|$)",
    re.I,
)
# Some layouts never print a "CARRIER NAME:" label at all — the carrier only
# shows up in the signature block ("...ON BEHALF OF CARRIER, G2 OCEAN AS").
_CARRIER_BEHALF_RE = re.compile(
    r"ON\s+BEHALF\s+OF\s+CARRIER,?\s+([A-Z][A-Za-z0-9 &.\-]{1,40}?)\s+AS\b", re.I
)
_FREIGHT_RE = re.compile(r"FREIGHT\s+(PREPAID|COLLECT)", re.I)
# The unit is usually a bare "(MTS)"/"(KGS)", but real forms often print
# "(IN KGS)" instead — and "WT" is sometimes immediately followed by its own
# abbreviation period ("NET WT.") before that. The trailing "[:.]" stays
# *required*, not optional — these labels are also used bare as plain column
# headers elsewhere on the page ("Gross Weight" with no value anywhere near
# it), and without a mandatory separator the regex would latch onto the
# first unrelated number appearing later in the text (e.g. a package count).
_NETWT_RE = re.compile(
    r"(?:TOTAL\s*)?NET\s*W(?:EIGH)?T\.?\s*(?:\(\s*(?:IN\s+)?(KGS?|LBS?|MTS?)\s*\))?\s*[:.]\s*"
    r"([\d.,]+)\s*(MTS|KGS?)?",
    re.I,
)
_GROSSWT_RE = re.compile(
    r"(?:TOTAL\s*)?GROSS\s*W(?:EIGH)?T\.?\s*(?:\(\s*(?:IN\s+)?(KGS?|LBS?|MTS?)\s*\))?\s*[:.]\s*"
    r"([\d.,]+)\s*(MTS|KGS?)?",
    re.I,
)
_GSTIN_RE = re.compile(r"\bGSTIN\s*[:\-]?\s*(\d{2}[A-Z0-9]{13})\b", re.I)
_CBM_RE = re.compile(
    r"(?:VOLUME|MEASURE(?:MENT)?)\s*(?:\(\s*(?:IN\s+)?CBM\s*\))?\s*[:.]\s*([\d.,]+)\s*CBM",
    re.I,
)
# A rider page's "INVOICE NO'S" block lists several slash-delimited invoice
# references with no per-invoice date (unlike the SB number list) — collect
# the whole run of codes up to whatever section follows it.
_INVOICE_LIST_RE = re.compile(
    r"INVOICE\s*NO'?S?\.?\s*(.+?)(?:NET\s*W(?:EIGH)?T|VOLUME|FREIGHT|$)", re.I | re.S
)
_INVOICE_CODE_RE = re.compile(r"\b[A-Z0-9]{2,10}(?:/[A-Z0-9]{1,10}){1,4}\b")
_HS_RE = re.compile(r"H\.?S\.?N?\.?\s*CODE\s*[:.\-]?\s*(\d{6,10})", re.I)
_PKG_WORDS_RE = re.compile(
    r"TOTAL\s*NO\.?\s*OF\s*PACKAGES.*?:\s*([A-Z][A-Z ]+?ONLY)\.?", re.I
)
_PO_RE = re.compile(
    r"P\.?\s?O\.?\s*(?:#|NO\.?)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9/._\-]{3,})", re.I
)
_INCO_RE = re.compile(
    r"SHIPPING\s*TERMS\s*:?\s*([A-Z]{3}\b[^\n(]*\(INCOTERMS[^)]*\))", re.I
)
_LC_RE = re.compile(
    r"DOCUMENTARY\s*CREDIT\s*NUMBER\s*:?\s*([A-Z0-9]+(?:\s+DATED\s+\d+)?)", re.I
)
_ONBOARD_RE = re.compile(
    r"SHIPPED\s*ON\s*BOARD\s*(?:DATE)?\s*[:.]?\s*"
    r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}\s+[A-Za-z]{2,9}\s+\d{4})",
    re.I,
)
_ISSUE_RE = re.compile(
    r"\b([A-Z][A-Za-z]+,\s*[A-Z][A-Za-z]+)\s+(\d{1,2}\s+[A-Za-z]{2,9}\s+\d{4})"
)
_SB_DATE_RE = re.compile(r"\b(\d{6,8})\s+DATE\.?\s+\d{1,2}[./]\d{1,2}[./]\d{2,4}", re.I)
# "<SB No> <date>" where the date is either all-numeric (01.02.2026) or the
# ICEGATE-style DD-MMM-YY used on rider-page SB tables (14-JUL-26).
_SB_RIDER_RE = re.compile(
    r"\b(\d{6,8})\s+\d{1,2}[.\-/](?:\d{1,2}|[A-Z]{3})[.\-/]\d{2,4}\b", re.I
)
_SB_LABEL_RE = re.compile(
    r"SHIPPING\s*BILL\s*(?:NO|NOS|NUMBER)?\.?\s*(?:&\s*DATE)?\s*[:.\-]?\s*(\d{6,8})",
    re.I,
)
# "<SB No> DT. <date>" — the comma-separated list format used on "SB NO'S &
# DATE" rider pages (e.g. "4998440 DT. 14.07.2026, 5087975 DT. 16.07.2026").
_SB_DT_RE = re.compile(r"\b(\d{6,8})\s+DT\.?\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}", re.I)
_IEC_RE = re.compile(r"\bIEC\s*[:\-]?\s*(\d{8,10})\b", re.I)

# Trailing commercial-info labels that mark the END of the Marks&Numbers /
# Description cargo table. Shared by page 1 and "B/L RIDER" continuation
# pages, whichever one actually carries the long multi-group cargo list —
# a real multi-mark-group rider page can land on EITHER, and a label known
# to only one copy let the table bleed past a too-short fixed cutoff on the
# other.
_CARGO_STOP_PHRASES = (
    "declared value", "ships general remarks", "received the described",
    "export invoice", "carrier name", "freight prepaid", "freight collect",
)
# Keywords marking the end of real goods-description free text, reused to
# trim the Description column on both page 1 and rider continuation pages.
_DESC_TRIM_RE = re.compile(
    r"\b(?:SHIPS?\s+GENERAL\s+REMARKS|DOCUMENTARY\s+CREDIT|SHIPPING\s+TERMS|"
    r"SHIPPING\s+BILL\s+NO|SB\s+NO'?S?\s*&\s*DATE|IMO\s+NUMBER|"
    r"SHIPPED\s+ON\s+BOARD|NET\s+W(?:EIGH)?T|"
    r"FREIGHT\s+(?:PRE)?PAID|FREIGHT\s+COLLECT|TOTAL\s+NO\.?\s+OF\s+PACKAGES|"
    r"HOOK\s+TO\s+HOOK|TOTAL\s+QUANTITY|CARRIER\s+NAME|EXPORT\s+INVOICE\s+NO|"
    r"PROJECT\s*:)\b",
    re.I,
)
# A "PROJECT: <code>" commercial-info line sits in the same left-hand column
# as the marks list on "B/L RIDER" style tables and can bleed into that band.
_PROJECT_LINE_RE = re.compile(r"PROJECT\s*:\s*[A-Z0-9][A-Z0-9 /\-]{0,20}", re.I)
# Generous safety bounds, not real limits — real cargo tables with several
# mark groups / multi-paragraph descriptions must never be cut short.
_MARKS_MAX = 4000
_DESC_MAX = 4000


def _head(doc: Document) -> str:
    return " ".join(t.text for t in doc.pages[0].tokens).upper()


def _alltext(doc: Document) -> str:
    return " ".join(
        t.text
        for p in doc.pages
        for t in sorted(p.tokens, key=lambda t: (round(t.y0), t.x0))
    )


def matches(doc: Document) -> bool:
    full = _alltext(doc).upper()
    if not _BL_RE.search(full):
        return False
    return (
        "PAREKH MARINE SERVICES" in full
        or "LINER BILL OF LADING" in _head(doc)
        or "PARTICULARS FURNISHED BY THE MERCHANT" in full
    )


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    page = doc.pages[0]
    pw = page.width or 612.0
    ph = page.height or 792.0
    p1: list[Token] = sorted(page.tokens, key=lambda t: (round(t.y0), t.x0))
    full = " ".join(t.text for t in p1)
    full_all = _alltext(doc)
    out: dict[str, tuple[str, float]] = {}

    def put(k: str, v: str | None, c: float) -> None:
        if not v:
            return
        v = _clean(v)
        if not v:
            return
        if k == "shipped_on_board_date":
            from ..extraction.validate import normalize_date

            v = normalize_date(v) or v
        out[k] = (v, c)

    put("document_type", "Liner Bill of Lading", 0.9)

    m = _BL_RE.search(full) or _BL_RE.search(full_all)
    bl = m.group(1) if m else None
    put("bl_number", bl, 0.92)

    labelled = any(
        t.text.strip().strip(":").upper().replace(" ", "")
        in ("SHIPPER/EXPORTER", "SHIPPEREXPORTER")
        for t in p1
    )

    if labelled:
        _labelled(p1, pw, ph, out, put)
    else:
        _labelless(p1, pw, ph, out, put, bl or "")

    # A "B/L RIDER" continuation page can list MORE marks+description rows
    # for the same shipment, regardless of which party-block flavour page 1
    # used — append them to whatever page 1 already found.
    if len(doc.pages) > 1:
        _rider_cargo_continuation(doc, out, put)

    # ---- cargo / commercial (layout-independent) --------------------------
    m = _FREIGHT_RE.search(full_all)
    put("freight_terms", f"FREIGHT {m.group(1).upper()}" if m else None, 0.85)

    m = _CARRIER_RE.search(full_all)
    if m:
        put("carrier", m.group(1).strip(" :"), 0.75)
    elif (m := _CARRIER_BEHALF_RE.search(full_all)):
        put("carrier", m.group(1).strip(" :"), 0.7)

    m = _AGENT_RE.search(full_all)
    if m:
        put("issued_by_agent", _clean(m.group(1)), 0.8)

    m = _NETWT_RE.search(full_all)
    if m and "net_weight" not in out:
        unit = (m.group(3) or m.group(1) or "KGS").upper()
        put("net_weight", f"{m.group(2)} {unit}", 0.8)

    m = _GROSSWT_RE.search(full_all)
    if m and "gross_weight" not in out:
        unit = (m.group(3) or m.group(1) or "KGS").upper()
        put("gross_weight", f"{m.group(2)} {unit}", 0.7)

    m = _CBM_RE.search(full_all)
    put("measurement_cbm", f"{m.group(1)} CBM" if m else None, 0.75)

    m = _GSTIN_RE.search(full_all)
    put("gstin", m.group(1).upper() if m else None, 0.85)

    m = _INVOICE_LIST_RE.search(full_all)
    if m:
        codes = list(dict.fromkeys(_INVOICE_CODE_RE.findall(m.group(1))))
        put("invoice_number_and_date", ", ".join(codes) if codes else None, 0.7)

    codes = list(dict.fromkeys(_HS_RE.findall(full_all)))
    put("hs_code", ", ".join(codes) if codes else None, 0.85)
    # number_and_kind_of_packages is read from the cargo table's own column
    # further down (_cargo_bands) — a blind full-text "<number> <noun>" scan
    # here had no column awareness and could latch onto an unrelated count
    # elsewhere in the document (e.g. a piece-count inside bulk packages).

    m = _PO_RE.search(full_all)
    put("purchase_order_number", m.group(1) if m else None, 0.7)

    m = _INCO_RE.search(full_all)
    put("incoterms", m.group(1).strip() if m else None, 0.8)

    m = _LC_RE.search(full_all)
    put("lc_number", m.group(1).strip() if m else None, 0.75)

    m = _ONBOARD_RE.search(full_all)
    if m:
        from ..extraction.validate import normalize_date

        put("shipped_on_board_date", normalize_date(m.group(1)) or m.group(1), 0.8)

    m = _ISSUE_RE.search(full_all)
    if m and "place_and_date_of_issue" not in out:
        put("place_and_date_of_issue", f"{m.group(1)} {m.group(2)}", 0.75)

    put("shipping_bill_number_and_date", _sb_numbers(doc, full_all), 0.85)

    m = _IEC_RE.search(full_all)
    put("iec_code", m.group(1) if m else None, 0.8)

    return {k: v for k, v in out.items() if v[0]}


# ------------------------------------------------------------ labelled variant
def _labelled(p1, pw, ph, out, put) -> None:
    for starts, stops, ck, nk, ak, sk in (
        (("shipperexporter", "shipper"), ("consignee", "bookingno"),
         "shipper", "shipper_name", "shipper_addr", "shipper_state"),
        (("consignee",), ("notifyparty", "forwardingagent", "pointand"),
         "consignee", "consignee_nm", "consignee_addr", "consignee_state"),
        (("notifyparty",), ("precarried", "placeofreceipt", "vessel", "domesticrouting"),
         "notify_party", "notify_name", "notify_addr", "notify_state"),
    ):
        lines = [
            ln for ln in _party_lines(p1, pw, starts, stops, right=False,
                                      reach=55, mid_frac=0.42)
            if not _is_junk_line(ln)
        ]
        if not lines:
            continue
        name, addr, state = split_party(lines)
        put(ck, ", ".join(lines), 0.82)
        put(nk, name, 0.85)
        put(ak, addr, 0.8)
        put(sk, state, 0.75)

    for labels, key, xh in (
        (("vessel",), "vessel_and_voyage", 80),
        (("port of discharge",), "port_of_discharge", 55),
        (("port of loading",), "port_of_loading", 55),
        (("place of receipt by", "place of receipt"), "place_of_receipt", 60),
    ):
        for phrase in labels:
            lbl = _find_label(p1, phrase)
            if not lbl:
                continue
            v = _cell_below(p1, lbl[1], y_lo=2, y_hi=22, x_half=xh)
            first = re.sub(r"[^A-Z]", "", v.upper().split(" ")[0]) if v else ""
            if v and first not in _ROUTE_STOP:
                put(key, v, 0.8)
            break

    lbl = _find_label(p1, "booking no")
    if lbl:
        v = _cell_below(p1, lbl[1], y_lo=2, y_hi=20, x_half=70)
        if v and re.fullmatch(r"\d{3,8}", v):
            put("booking_number", v, 0.8)

    # "original bs/l" is specific to the box label — "number of original" alone
    # also matches the boilerplate clause ("...has signed the number of
    # original Bills of Lading stated below...") and grabs the wrong row.
    lbl = _find_label(p1, "original bs") or _find_label(p1, "number of original")
    if lbl:
        # the value aligns under the *start* of "Number of Original Bs/L", not
        # its multi-word end — widen x_half rather than re-anchoring on lbl[0]
        # (which would risk pulling in the neighbouring cell on some layouts).
        v = _cell_below(p1, lbl[1], y_lo=-1, y_hi=30, x_half=80)
        m = re.match(r"\d{1,2}", v or "")
        if m:
            put("number_of_original_bls", m.group(0), 0.75)

    hdr = _find_label(p1, "particulars furnished") or _find_label(p1, "description of")
    y_top = (hdr[0].y0 + 10) if hdr else 262.0
    # Found once, used for two different things below: its x-position places
    # the "No. of Pkgs" column (needed regardless of which row it's on), and
    # — only when it sits at/after the naive y_top above — its y-position
    # pushes y_top past it too, since the column header can span two rows
    # ("MARKS AND NUMBER | ... DESCRIPTION OF ... GOODS" then "NO. OF PKGS."
    # right below it) and that second header row would otherwise get swept
    # into the data bands alongside the real cargo row.
    pkg_hdr = next((t for t in p1 if t.text.upper().rstrip(".") == "PKGS"), None)
    if pkg_hdr is not None and pkg_hdr.y0 >= y_top - 4:
        y_top = max(y_top, pkg_hdr.y0 + 6)
    # A "Declared Value / Freight payable at / Freight details, charges etc."
    # commercial-terms block often sits between the goods table and the legal
    # boilerplate ("received the described goods...") — stop at whichever of
    # these appears first (topmost), or the table's x-ranges end up sweeping
    # in that unrelated block too.
    stops = [
        lbl[0].y0 for phrase in _CARGO_STOP_PHRASES
        if (lbl := _find_label(p1, phrase))
    ]
    # No fixed pixel fallback: a "B/L RIDER" style table can legitimately run
    # most of the page (several mark groups, multi-line description) and a
    # small constant here truncated it before any real stop label was found.
    y_bot = (min(stops) - 2) if stops else (ph - 20)
    # The "No. of Pkgs" column's actual x-position drifts between real GSSW
    # layouts (a fixed pixel range missed it entirely on one real file) — use
    # the "PKGS" header token found above to place it, when available, rather
    # than a guessed constant.
    # The description column's right edge also drifts — a hardcoded 305 cut
    # real wrapped description text off mid-sentence on one layout where it
    # legitimately runs wider before reaching the Gross Weight column. Anchor
    # it to the "GROSS" header token instead, when found.
    gross_hdr = next((t for t in p1 if t.text.upper().rstrip(".") == "GROSS"), None)
    desc_right = (gross_hdr.x0 - 5) if gross_hdr else 305
    if pkg_hdr is not None:
        pkg_x = (pkg_hdr.x0 - 8, pkg_hdr.x1 + 15)
        desc_x = (pkg_x[1], desc_right)
    else:
        pkg_x, desc_x = (78, 128), (115, desc_right)
    marks_x = (12, 120)
    _cargo_bands(p1, out, put, marks_x=marks_x, pkg_x=pkg_x,
                 desc_x=desc_x, gross_x=(350, 485), y_top=y_top, y_bot=y_bot)

    # Some layouts print the gross weight as a bare column value with no
    # "GROSS WT" text anywhere nearby — only reachable by position. Anchor to
    # the exact row that carries the package count (the one unambiguous
    # cargo-table row) rather than scanning the whole cargo block, so an
    # unrelated wide line elsewhere in that x-range can't be mistaken for it.
    if "gross_weight" not in out:
        # the package count itself can land in the marks column rather than
        # the "No. of Pkgs" column proper on some layouts (e.g. a bare count
        # printed beside the marks block, with the real "<n> <noun>" restated
        # later in the description) — search the combined marks+pkg span
        # rather than pkg_x alone, or this anchor finds nothing for them.
        pkg_row_y = next(
            (t.y0 for t in p1
             if y_top <= t.y0 <= y_bot and marks_x[0] <= t.cx < pkg_x[1]
             and re.fullmatch(r"\d{1,5}", t.text)),
            None,
        )
        if pkg_row_y is not None:
            row = " ".join(
                t.text for t in p1
                if abs(t.y0 - pkg_row_y) <= 4 and 350 <= t.cx < 485
            )
            m = re.search(r"([\d][\d.,]*)\s*(KGS|MTS)\b", row, re.I)
            if m and float(m.group(1).replace(",", "")) > 1:
                put("gross_weight", f"{m.group(1)} {m.group(2).upper()}", 0.65)


# --------------------------------------------------------- label-less variant
def _labelless(p1, pw, ph, out, put, bl: str) -> None:
    # booking number: the token just left of the GSSW B/L number on its row
    if bl:
        bltok = next((t for t in p1 if t.text == bl), None)
        if bltok:
            left = [t for t in p1 if abs(t.y0 - bltok.y0) <= 4 and t.x1 <= bltok.x0 - 2]
            for t in sorted(left, key=lambda t: -t.x0):
                if re.fullmatch(r"\d{3,8}", t.text):
                    put("booking_number", t.text, 0.75)
                    break

    for (ck, nk, ak, sk), lines in zip(
        (("shipper", "shipper_name", "shipper_addr", "shipper_state"),
         ("consignee", "consignee_nm", "consignee_addr", "consignee_state"),
         ("notify_party", "notify_name", "notify_addr", "notify_state")),
        _left_blocks(p1, pw, ph)[:3],
    ):
        lines = [ln for ln in lines if not _is_junk_line(ln)]
        if not lines:
            continue
        name, addr, state = split_party(lines)
        put(ck, ", ".join(lines), 0.7)
        put(nk, name, 0.72)
        put(ak, addr, 0.68)
        put(sk, state, 0.62)

    # routing: below the party blocks, the vessel value sits far left with Port
    # of Loading to its right; Port of Discharge is the place-token one row down.
    _COMPANY = re.compile(r"\b(LTD|LTD\.|INC|INC\.|LLC|CORP|CO\.|ENERGY|INDUSTRIES|"
                          r"INTERNATIONAL|INVOICE|PACKAGES?)\b", re.I)
    vrow_y = None
    for y in sorted({round(t.y0) for t in p1 if ph * 0.28 < t.y0 < ph * 0.55}):
        cells = _row_cells(p1, y, pw)
        if len(cells) >= 2 and not _COMPANY.search(cells[0]) and len(cells[0]) <= 22 \
                and _PLACE_RE.match(cells[1]):
            vrow_y = y
            put("vessel_and_voyage", cells[0], 0.65)
            put("port_of_loading", cells[1], 0.65)
            break
    if vrow_y is not None:
        by = min((t.y0 for t in p1 if 12 <= t.y0 - vrow_y <= 44), default=None)
        if by is not None:
            below = [c for c in _row_cells(p1, by, pw) if _PLACE_RE.match(c)]
            if below:
                put("port_of_discharge", below[0], 0.63)

    m = _ISSUE_RE.search(" ".join(t.text for t in p1))
    if m:
        put("place_and_date_of_issue", f"{m.group(1)} {m.group(2)}", 0.7)
    for t in p1:
        if re.fullmatch(r"\d", t.text) and t.x0 < pw * 0.12 and t.y0 > ph * 0.85:
            put("number_of_original_bls", t.text, 0.6)
            break

    _cargo_bands(p1, out, put, marks_x=(10, 130), pkg_x=(120, 175),
                 desc_x=(175, 400), gross_x=(420, 500), y_top=330, y_bot=470)


# ---------------------------------------------------------------- shared bits
_ROUTE_STOP = {"PORT", "PLACE", "OF", "LOADING", "DISCHARGE", "RECEIPT", "VESSEL",
               "FOR", "ON", "CARRIAGE", "PRECARRIED", "BY", "ONWARD"}
_PLACE_RE = re.compile(r"^[A-Z][A-Za-z]{2,}(?:[ ,]+[A-Z][A-Za-z.]{1,})*$")


def _is_junk_line(s: str) -> bool:
    if len(s) < 3:
        return True
    up = s.upper()
    if re.match(r"^(PHONE|TEL|FAX|E-?MAIL|EMAIL|ATTN|IEC|GST|PAN|CTC)\b", up):
        return True
    return up in ("ORIGINAL", "COPY", "DUPLICATE", "TRIPLICATE",
                  "SHIPPER/EXPORTER", "CONSIGNEE", "NOTIFY PARTY")


def _row_cells(toks, y: float, pw: float, *, x_min: float = 0.0) -> list[str]:
    band = sorted(
        (t for t in toks if abs(t.y0 - y) <= 5 and t.x0 >= x_min and t.cx < pw * 0.92),
        key=lambda t: t.x0,
    )
    cells: list[str] = []
    cur: list[str] = []
    prev: float | None = None
    for t in band:
        if prev is not None and t.x0 - prev > 20:
            cells.append(" ".join(cur))
            cur = []
        cur.append(t.text)
        prev = t.x1
    if cur:
        cells.append(" ".join(cur))
    return [c.strip(" ,") for c in cells if c.strip(" ,")]


def _left_blocks(toks, pw: float, ph: float) -> list[list[str]]:
    left = [t for t in toks if t.cx < pw * 0.42 and t.y0 < ph * 0.55]
    blocks: list[list[str]] = []
    cur: list[str] = []
    prev_bottom: float | None = None
    for ln in _lines(left, y_tol=4):
        txt = _clean(" ".join(t.text for t in ln))
        if not txt:
            continue
        top = min(t.y0 for t in ln)
        if prev_bottom is not None and top - prev_bottom > 22 and cur:
            blocks.append(cur)
            cur = []
        cur.append(txt)
        prev_bottom = max(t.y1 for t in ln)
    if cur:
        blocks.append(cur)
    return blocks


def _cargo_bands(p1, out, put, *, marks_x, pkg_x, desc_x, gross_x, y_top, y_bot) -> None:
    def band(x_lo, x_hi, joiner=" "):
        rows = _lines(
            [t for t in p1 if y_top <= t.y0 <= y_bot and x_lo <= t.cx < x_hi], y_tol=4
        )
        return joiner.join(_clean(" ".join(t.text for t in r)) for r in rows).strip()

    if "marks_and_numbers" not in out:
        marks = _clean(band(*marks_x))
        marks = re.sub(r"\bZET-?\s+(?=[A-Z])", "ZET-", marks)
        marks = re.sub(r"\b(Marks?|Numbers?|No\.?|of|Pkgs?)\b", "", marks, flags=re.I)
        marks = _PROJECT_LINE_RE.sub("", marks)
        marks = _clean(re.sub(r"\s{2,}", " ", marks))
        # A stray package-count can bleed into this column and land as a bare
        # trailing number — but a mark range's own closing number (e.g.
        # "ZET-KSI- 538 TO ZET-KSI- 556") ends in a number too and must not
        # be stripped just because it's at the end; only strip one that
        # isn't part of such a code (i.e. not immediately preceded by "-").
        marks = re.sub(r"(?<!-)\s+\d{1,4}$", "", marks)
        if marks and len(marks) >= 4:
            put("marks_and_numbers", marks[:_MARKS_MAX], 0.6)

    if "number_and_kind_of_packages" not in out:
        # the pkg column's exact x-range drifts between real layouts and can
        # still catch stray text from an adjacent wide marks column (long
        # reference codes) — rather than trust everything found there, pick
        # out just the first purely-numeric token and ignore any text debris
        # alongside it (e.g. "ZET-..." marks fragments, "TO", etc.).
        pkg_num_tok = next(
            (t for t in p1
             if y_top <= t.y0 <= y_bot and pkg_x[0] <= t.cx < pkg_x[1]
             and re.fullmatch(r"\d[\d,]*", t.text)),
            None,
        )
        pkg_only = pkg_num_tok.text if pkg_num_tok else ""
        both = f"{pkg_only} {band(*desc_x)}"
        noun_re = (r"(BUNDLES?|PACKAGES?|PIECES?|PCS?|CASES?|CRATES?|"
                   r"SKIDS?|PALLETS?|COILS?|ROLLS?|BOXES?)")
        pkg_is_number = bool(re.fullmatch(r"\d[\d,]*", pkg_only))

        noun_tok = None
        if pkg_is_number:
            # prefer a noun specifically paired with the pkg-column's own
            # count — BLs often restate it ("SAID TO CONTAIN 76 BUNDLES...")
            # — over the first "<number> <noun>" found anywhere in the
            # description, which can belong to an unrelated count (e.g. a
            # piece-count inside bulk/project-cargo packages). Match it by
            # the noun token's own row (tight y-tolerance against the count
            # token itself), not the joined/banded text — a later row can
            # sit close enough to get merged into the same band line by the
            # shared y_tol=4 grouping, and then sort ahead of the same-row
            # noun if its x0 happens to be smaller.
            noun_tok = next(
                (t for t in p1
                 if abs(t.y0 - pkg_num_tok.y0) <= 1.5 and t.cx >= pkg_x[1]
                 and re.fullmatch(noun_re, t.text.upper().rstrip("."), re.I)),
                None,
            )

        m = None
        if noun_tok is not None:
            pass
        elif pkg_is_number:
            m = re.search(rf"\b({re.escape(pkg_only)})\s+{noun_re}\b", both, re.I)
        else:
            m = re.search(rf"\b(\d[\d,]*)\s+{noun_re}\b", both, re.I)

        if noun_tok is not None:
            put("number_and_kind_of_packages",
                f"{pkg_only} {noun_tok.text.upper().rstrip('.')}", 0.62)
        elif m:
            put("number_and_kind_of_packages",
                f"{m.group(1)} {m.group(2).upper()}", 0.62)
        elif pkg_is_number:
            # a bare count with no noun anywhere nearby (bulk/project cargo)
            # — trust it rather than grabbing an unrelated count+noun later
            put("number_and_kind_of_packages", pkg_only, 0.6)

    if "description_of_goods" not in out:
        desc = band(*desc_x)
        # The restated package-count ("252 BUNDLES") and the legal boilerplate
        # phrase "SAID TO CONTAIN" can sit in this same column, ahead of the
        # "Description of (Packages and) Goods" sub-header and the real free
        # text — strip everything up to and including the first "SAID TO
        # CONTAIN" (a no-op when the layout doesn't have it at all), then the
        # sub-header, which is now reliably at the start either way.
        desc = re.sub(r"^.*?\bSAID\s+TO\s+CONTAIN\b\s*", "", desc, flags=re.I)
        desc = re.sub(
            r"^Description\s+of\s+(?:Packages?\s+and\s+)?Goods?\b\s*",
            "", desc, flags=re.I,
        )
        desc = _DESC_TRIM_RE.split(desc)[0]
        desc = _clean(desc)
        if desc and len(desc) >= 5:
            put("description_of_goods", desc[:_DESC_MAX].rstrip(" ,-/"), 0.62)


def _rider_cargo_continuation(doc: Document, out: dict, put) -> None:
    """Page 1's cargo row often ends "DETAILS PLEASE SEE ATTACHED" — a "B/L
    RIDER" continuation page (page 2 onward) lists MORE marks+description
    rows for the same shipment, in the same two-column shape. Append them to
    whatever page 1 already found rather than leaving them out, since the
    front page itself points straight at this attachment for the rest."""
    for page in doc.pages[1:]:
        p = sorted(page.tokens, key=lambda t: (round(t.y0), t.x0))
        hdr = _find_label(p, "particulars furnished")
        if not hdr:
            continue
        y_top = hdr[0].y0 + 10
        pkg_hdr = next((t for t in p if t.text.upper().rstrip(".") == "PKGS"), None)
        if pkg_hdr is not None and pkg_hdr.y0 >= y_top - 4:
            y_top = max(y_top, pkg_hdr.y0 + 6)
        page_h = page.height or 792.0
        stops = [
            lbl[0].y0 for phrase in _CARGO_STOP_PHRASES
            if (lbl := _find_label(p, phrase))
        ]
        y_bot = (min(stops) - 2) if stops else (page_h - 20)
        gross_hdr = next((t for t in p if t.text.upper().rstrip(".") == "GROSS"), None)
        desc_right = (gross_hdr.x0 - 5) if gross_hdr else 305
        if pkg_hdr is not None:
            pkg_x = (pkg_hdr.x0 - 8, pkg_hdr.x1 + 15)
            desc_x = (pkg_x[1], desc_right)
        else:
            pkg_x, desc_x = (78, 128), (115, desc_right)
        marks_x = (12, 120)

        def band(x_lo, x_hi):
            rows = _lines(
                [t for t in p if y_top <= t.y0 <= y_bot and x_lo <= t.cx < x_hi], y_tol=4
            )
            return " ".join(_clean(" ".join(t.text for t in r)) for r in rows).strip()

        marks = _clean(band(*marks_x))
        marks = re.sub(r"\bZET-?\s+(?=[A-Z])", "ZET-", marks)
        marks = re.sub(r"\b(Marks?|Numbers?|No\.?|of|Pkgs?)\b", "", marks, flags=re.I)
        marks = _PROJECT_LINE_RE.sub("", marks)
        marks = _clean(re.sub(r"\s{2,}", " ", marks))
        marks = re.sub(r"(?<!-)\s+\d{1,4}$", "", marks)

        desc = band(*desc_x)
        desc = re.sub(r"^.*?\bSAID\s+TO\s+CONTAIN\b\s*", "", desc, flags=re.I)
        desc = re.sub(
            r"^Description\s+of\s+(?:Packages?\s+and\s+)?Goods?\b\s*", "", desc, flags=re.I,
        )
        desc = _DESC_TRIM_RE.split(desc)[0]
        desc = _clean(desc)

        # Some rider pages reuse this exact same column template for an
        # unrelated reference list instead (e.g. "SB NO'S & DATE" sitting
        # where the description text normally would) — the marks column is
        # then left completely empty, which a genuine extra cargo row never
        # is. Require real marks content before trusting either column here,
        # or a reference list gets mistaken for more cargo description.
        if marks and len(marks) >= 4:
            prev = out.get("marks_and_numbers", (None, 0))[0]
            combined = f"{prev}; {marks}" if prev and marks not in prev else (prev or marks)
            put("marks_and_numbers", combined[:_MARKS_MAX], 0.6)
            if desc and len(desc) >= 5:
                prev = out.get("description_of_goods", (None, 0))[0]
                combined = f"{prev}; {desc}" if prev and desc not in prev else (prev or desc)
                put("description_of_goods", combined[:_DESC_MAX].rstrip(" ,-/"), 0.6)

    # Gross weight is deliberately NOT read from a fixed column band: on the
    # narrative single-SB layout the "particulars" text is one wide block, not
    # real columns, and a band there just grabs stray digits from a nearby date
    # or reference number. The regex passes in parse() (label-anchored, unit
    # required) cover every layout without that risk.


def _sb_numbers(doc: Document, full_all: str) -> str | None:
    """The SB table isn't always on the BL's main page — some carriers push it
    to a 'B/L RIDER' continuation page instead, so every page is checked."""
    nums: list[str] = []

    for page in doc.pages:
        toks = page.tokens
        hdr = next(
            (t for t in toks
             if t.text.upper() == "SHIPPING"
             and any(o.text.upper() == "BILL" and 0 < o.x0 - t.x1 < 22
                     and abs(o.y0 - t.y0) <= 3 for o in toks)),
            None,
        )
        if hdr is None:
            continue
        y_stop = next((t.y0 for t in toks if t.text.upper() == "CARRIER"
                       and t.y0 > hdr.y0), 1e9)
        col = [
            t for t in toks
            if hdr.y0 - 2 < t.y0 < y_stop
            and hdr.x0 - 30 <= t.x0 <= hdr.x0 + 24
            and re.fullmatch(r"\d{6,8}", t.text)
        ]
        nums += [t.text for t in sorted(col, key=lambda t: (round(t.y0), t.x0))]

    for rx in (_SB_DATE_RE, _SB_LABEL_RE, _SB_RIDER_RE, _SB_DT_RE):
        nums += rx.findall(full_all)

    seen = list(dict.fromkeys(n for n in nums if n))
    return ", ".join(seen) if seen else None
