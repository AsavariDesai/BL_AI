"""Adaptive house Bill of Lading parser for JEENA & COMPANY shipments.

JEENA is the India delivery / discharge agent on Bills of Lading issued by many
different overseas carriers and forwarders (SupplyX, Multitrade / Balguerie,
Italsempione, Yang Ming via WINCO, …). The forms differ but almost all use the
same standard English box labels — Shipper, Consignee, Notify, Port of Loading,
Booking No., Bill of Lading No., etc. This parser reads those boxes by geometry;
when a form's labels are baked into a background image (no text layer for them)
it falls back to shape-based regex and left-column block clustering.

It never lifts a value out of unlabelled legal boilerplate.

Registered last, so a carrier-specific template (container_bl, breakbulk_bl,
aof_bl) still wins when it recognises the form.
"""
from __future__ import annotations

import re

from ..document import Document, Token
from ._common import (
    _cell_below,
    _clean,
    _find_label,
    _lines,
    _row_after,
    _party_lines,
    looks_like_boilerplate,
    split_party,
)

DOC_TYPE = "bill_of_lading"

_BL_SHAPE = re.compile(r"^(?=.*\d)[A-Z0-9][A-Z0-9/\-]{4,24}$")
_BOOKBL_RE = re.compile(r"\b(S\d{8,11})\s+([A-Z]{2,6}\d{6,}(?:/\d+)?)\b")
_FREIGHT_RE = re.compile(r"FREIGHT\s+(PREPAID|COLLECT)", re.I)
_MOVE_RE = re.compile(r"\b(CY[-/]CY|CY[-/]CFS|CFS[-/]CY|FCL/FCL|LCL/LCL)\b", re.I)
_ORIG_RE = re.compile(r"\b(ONE|TWO|THREE|FOUR|FIVE|SIX)\s*[\(/]\s*(\d)\s*\)?", re.I)
_HS_RE = re.compile(r"H\.?\s?S[\s.\-]*CODE\s*[:.]?\s*(\d{6,10})", re.I)
_WT_CBM_RE = re.compile(r"([\d][\d.,]*)\s*KGS?\s+([\d][\d.,]*)\s*CBM", re.I)
_NET_RE = re.compile(r"NET\s*W(?:EIGH)?T\.?\s*[:.]?\s*([\d][\d.,]*)\s*(KGS?|MTS?)", re.I)
_ONBOARD_RE = re.compile(
    r"SHIPPED ON BOARD\s*(?:DATE)?\s*[:.]?\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})",
    re.I,
)
_INV_RE = re.compile(
    r"INV(?:OICE)?[\s\-]*NO\.?\s*[:.]?\s*([0-9A-Z][0-9A-Z/\-]{2,})"
    r"(?:\s*,?\s*DT?D?\.?\s*([\d.\-/]{6,10}))?",
    re.I,
)
_PO_RE = re.compile(r"P\.?\s?O\.?\s*(?:#|NO\.?)\s*[:.]?\s*([A-Z0-9][A-Z0-9/\-]{3,})", re.I)
_CONT_RE = re.compile(r"\b([A-Z]{4}\d{7})\b")
_SEAL_RE = re.compile(r"SEAL\s*(?:NO\.?)?\s*[:.]?\s*([A-Z0-9]{5,14})", re.I)
_VOY_RE = re.compile(r"\b(?:VOY|VOYAGE)[- ]?(?:NO\.?)?\s*[:.]?\s*([A-Z0-9]{3,8})\b", re.I)
_VOY2_RE = re.compile(r"\bv\.?\s*([A-Z]{1,3}\d{2,5}[A-Z]?)\b")
_VESSEL_RE = re.compile(r"\b([A-Z][A-Z]{1,4}(?: [A-Z][A-Za-z]+){0,3} \d{2}/\d{5,6})\b")
_ISSUE_RE = re.compile(
    r"\b([A-Z][A-Za-z]{2,},\s?[A-Z][A-Za-z.]{2,}[, ]+"
    r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}))"
)
_EU_NUM_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+,\d+|\d+,\d{1,3})$")


def _norm_num(s: str) -> str:
    """European decimals -> plain: 10.518,324 -> 10518.324 ; 17363,00 -> 17363.00.
    Anything else (incl. plain 1,234.56) is left untouched."""
    s = s.strip()
    return s.replace(".", "").replace(",", ".") if _EU_NUM_RE.match(s) else s
_PLACE_TOK_RE = re.compile(r"^[A-Z][A-Za-z.]{2,}(?:[ ,][A-Z][A-Za-z.]{1,})*$")
_MARKS_JUNK_RE = re.compile(
    r"^(no\.?s?|and|type|of|description|goods|gross|weight|measurement|packages?)$",
    re.I,
)
_CARGO_LINE_RE = re.compile(
    r"^(n/?m|said to|shipper'?s? load|particular|parts? of|\d[\d,]*\s+(?:cartons?|"
    r"pallets?|pkgs?|bundles?|cases?|pcs?|boxes?|drums?)\b)",
    re.I,
)
_EMAIL_ONLY_RE = re.compile(r"^\S+@\S+\.\S+$")
_DATE_KEYS = {"shipped_on_board_date"}

_IEC_RE = re.compile(
    r"\bIEC\b[\s.:#)\-]*(?:CODE|NO\.?)?[\s.:#)\-]*([0-9]{10}|[A-Z]{3}[A-Z0-9]{7})",
    re.I,
)
_GSTIN_RE = re.compile(
    r"\bGST(?:IN|N)?\b[\s.:#)\-]*(?:NO\.?)?[\s.:#)\-]*"
    r"(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9])",
    re.I,
)
# bare 15-char GSTIN with no label nearby (fallback)
_GSTIN_BARE_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9])\b")
_ORIG_VAL_RE = re.compile(
    r"^(?:\d\s*[/\-]?\s*(?:ZERO|\d)|ZERO|ONE|TWO|THREE|FOUR|FIVE|SIX)"
    r"(?:\s*\(\d\))?$",
    re.I,
)

_ROUTE_STOP = {
    "PORT", "PLACE", "OF", "LOADING", "DISCHARGE", "DELIVERY", "RECEIPT", "VESSEL",
    "OCEAN", "MOVEMENT", "TYPE", "FREIGHT", "PAYABLE", "AT", "NUMBER", "MARKS",
    "AND", "NUMBERS", "SHIPPER", "SHIPPERS", "CONSIGNEE", "CONSIGNEES", "NOTIFY",
    "FOR", "STAMP", "STOWAGE", "STATE", "REFERENCE", "REFERENCES", "IEC", "PAN",
    "GSTIN", "GALA", "EMAIL", "TEL", "FAX", "NO", "INTENTED", "INTENDED",
}


def _head(doc: Document) -> str:
    return " ".join(t.text for t in doc.pages[0].tokens).upper()


def matches(doc: Document) -> bool:
    # doc_type is already gated to bill_of_lading by parse_with_template, so the
    # presence of JEENA as agent is enough to claim any BL not taken by a
    # carrier-specific template.
    return "JEENA" in _head(doc)


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    page = doc.pages[0]
    page_w = page.width or 595.0
    page_h = page.height or 842.0
    p1: list[Token] = sorted(page.tokens, key=lambda t: (round(t.y0), t.x0))
    full = " ".join(t.text for t in p1)
    full_all = " ".join(
        t.text
        for p in doc.pages
        for t in sorted(p.tokens, key=lambda t: (round(t.y0), t.x0))
    )
    out: dict[str, tuple[str, float]] = {}
    is_balguerie = bool(re.search(r"BALGUERIE|MULTITRADE SPAIN", full_all, re.I))

    def put(k: str, v: str | None, c: float) -> None:
        if not v:
            return
        v = _clean(v)
        if not v or looks_like_boilerplate(v):
            return
        if k in _DATE_KEYS:
            from ..extraction.validate import normalize_date
            v = normalize_date(v) or v
        out[k] = (v, c)

    # ---------------------------------------------------------------- identity
    up = full.upper()
    if is_balguerie or "COMBINED TRANSPORT BILL OF LADING" in up:
        put("document_type", "Combined Transport Bill of Lading", 0.85)
    elif "EXPRESS BILL OF LADING" in up:
        put("document_type", "Express Bill of Lading", 0.9)
    elif "MULTIMODAL" in up:
        put("document_type", "Multimodal Transport Bill of Lading", 0.9)
    else:
        put("document_type", "Bill of Lading", 0.7)

    labelled = _is_labelled_form(p1)
    book, bl = _booking_and_bl(p1, full, page_w, page_h)
    put("bl_number", bl, 0.9)
    put("booking_number", book, 0.9)

    # ----------------------------------------------------------------- parties
    _parties(p1, page_w, page_h, out, put, labelled)

    # ----------------------------------------------------------------- routing
    for labels, key in (
        (("place of receipt", "place of receipt by"), "place_of_receipt"),
        (("port of loading",), "port_of_loading"),
        (("port of discharge",), "port_of_discharge"),
        (("place of delivery", "final place of delivery"), "place_of_delivery"),
    ):
        put(key, _routed_value(p1, labels), 0.8)

    vessel = _routed_value(p1, ("ocean vessel", "vessel & voyage", "vessel voyage",
                                "intented vessel", "intended vessel", "vessel"))
    if not vessel:
        m = _VESSEL_RE.search(full)
        vessel = m.group(1) if m else None
    if vessel:
        m = _VOY_RE.search(full) or _VOY2_RE.search(full)
        if m and m.group(1).upper() not in vessel.upper():
            vessel = f"{vessel} {m.group(1)}"
        put("vessel_and_voyage", vessel, 0.78)

    # label-less grid: read the routing row(s) by position around the vessel line
    if not labelled and "port_of_discharge" not in out:
        if is_balguerie:
            _balguerie_route(p1, page_w, out, put)
        else:
            _labelless_route(p1, page_w, page_h, out, put)
    if is_balguerie:
        _balguerie_cargo(p1, out, put)

    if "place_and_date_of_issue" not in out:
        tail = " ".join(t.text for t in p1 if t.y0 > page_h * 0.78)
        m = re.search(
            r"\b([A-Z][A-Za-z]{3,}(?:,?\s[A-Z][A-Za-z.]{2,}){0,2}[, ]+"
            r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}))",
            tail)
        if m:
            put("place_and_date_of_issue", m.group(1), 0.7)

    # -------------------------------------------------------------- commercial
    m = _FREIGHT_RE.search(full_all)
    put("freight_terms", f"FREIGHT {m.group(1).upper()}" if m else None, 0.85)

    payable = _labelled_cell(p1, ("freight payable at", "payable at"),
                             x_half=110, below_only=True)
    if payable and len(payable) <= 30 and not _MARKS_JUNK_RE.match(payable):
        put("freight_payable_at", payable, 0.78)

    m = _MOVE_RE.search(full)
    put("movement_type", m.group(1).upper().replace("-", "/") if m else None, 0.8)

    orig = _labelled_cell(
        p1, ("number of original", "no of bills of lading", "number of originals",
             "no. of original"), x_half=85, below_only=True)
    if not orig:
        m = _ORIG_RE.search(full)
        orig = f"{m.group(1).upper()}({m.group(2)})" if m else None
    if orig and _ORIG_VAL_RE.match(orig.replace(" ", "")):
        put("number_of_original_bls", orig, 0.78)

    issue = _labelled_cell(
        p1, ("place and date of issue", "place & date of issue", "place and date issue"),
        y_hi=22, x_half=180)
    if issue:
        issue = re.sub(r"^(?:X\s+)?\d?\s*/?\s*ZERO\s+", "", issue, flags=re.I).strip()
    if not issue or not re.search(r"\d", issue):
        m = _ISSUE_RE.search(full)
        issue = m.group(1) if m else issue
    put("place_and_date_of_issue", issue, 0.78)

    m = _ONBOARD_RE.search(full_all)
    put("shipped_on_board_date", m.group(1) if m else None, 0.8)

    # --------------------------------------------------------------- cargo
    codes = list(dict.fromkeys(_HS_RE.findall(full_all)))
    put("hs_code", ", ".join(codes) if codes else None, 0.85)

    m = _WT_CBM_RE.search(full_all)
    if m:
        if "gross_weight" not in out:
            put("gross_weight", f"{_norm_num(m.group(1))} KGS", 0.72)
        if "measurement_cbm" not in out:
            put("measurement_cbm", f"{_norm_num(m.group(2))} CBM", 0.72)

    m = _NET_RE.search(full_all)
    if m:
        put("net_weight", f"{m.group(1)} {m.group(2).upper()}", 0.8)

    put("container_and_seal_numbers", _containers(full_all), 0.8)

    m = _INV_RE.search(full_all)
    if m:
        put("invoice_number_and_date",
            m.group(1) + (f" DT. {m.group(2)}" if m.group(2) else ""), 0.75)

    m = _PO_RE.search(full_all)
    put("purchase_order_number", m.group(1) if m else None, 0.72)

    if "marks_and_numbers" not in out:
        marks = _labelled_cell(
            p1, ("marks and numbers", "marks & numbers", "marks and nos", "marsk numbers"),
            y_hi=28, x_half=110, below_only=True)
        if marks and 3 <= len(marks) <= 60 and (
            re.search(r"\d", marks) or marks.upper() in ("N/M", "NM", "NIL", "AS ADDRESSED")
        ):
            put("marks_and_numbers", marks, 0.6)

    # goods table by position/content — for forms whose column headings aren't text
    _goods_grid(p1, page_w, page_h, out, put)

    # -------------------------------------------------------------- agents
    agent = _agent_block(p1, page_w, full_all)
    if agent:
        agent = re.split(r"[,\s]+(?:EMAIL|IEC|GSTIN|GSTN|TEL|FAX|BOARD NO|CTC)\b",
                         agent, maxsplit=1, flags=re.I)[0].rstrip(" ,")
        put("delivery_agent", agent, 0.7)

    # ------------------------------------------------- IEC / GSTIN (references)
    _iec_gstin(out, full_all, put)

    return {k: v for k, v in out.items() if v[0]}


# --------------------------------------------------------------------- helpers
def _is_labelled_form(toks: list[Token]) -> bool:
    """True when the box labels are real text (not baked into a background image).

    On these forms the printed labels are Title-Case ('Shipper', 'Consignee',
    'Port of loading') while every filled-in value is UPPER-CASE. So a
    Title-Case 'Shipper'/'Consignee' token means labels are real text, and
    'THE SAME AS CONSIGNEE' (all caps) is not mistaken for one."""
    return any(
        t.text.strip().strip(":") in ("Shipper", "Consignee", "Shipper/Exporter")
        for t in toks
    )


def _booking_and_bl(toks: list[Token], full: str, page_w: float,
                    page_h: float) -> tuple[str | None, str | None]:
    def _from_label(phrases: tuple[str, ...]) -> str | None:
        for phrase in phrases:
            lbl = _find_label(toks, phrase)
            if not lbl:
                continue
            pool = _row_after(toks, lbl[1], y_tol=7, max_tokens=5)
            pool += _cell_below(toks, lbl[1], y_hi=20, x_half=120).split()
            for raw in pool:
                tok = raw.strip(" :#.-|")
                if _BL_SHAPE.match(tok) and not re.fullmatch(r"\d{1,3}", tok):
                    return tok
        return None

    book = _from_label(("booking no", "booking ref", "booking reference", "booking number"))
    bl = _from_label(("bill of lading no", "b/l no", "bl number", "bl no",
                      "document no", "ocean b/l no"))

    if not (book and bl):
        m = _BOOKBL_RE.search(full)
        if m:
            book = book or m.group(1)
            bl = bl or m.group(2)

    if not bl:
        m = re.search(
            r"(?:EXPRESS |COMBINED TRANSPORT |MULTIMODAL |OCEAN )?BILL OF LADING\s+"
            r"([A-Z0-9]{3,}(?:[/\-][A-Z0-9]+){0,3})",
            full, re.I)
        if m and _BL_SHAPE.match(m.group(1).strip("/-")):
            bl = m.group(1).strip("/-")

    if not bl:
        # label-less form: the BL no. is the alpha-numeric code sitting alone in
        # the top-right corner (e.g. "ME2611285/1").
        top_right = sorted(
            (t for t in toks
             if t.y0 < page_h * 0.22 and t.x0 > page_w * 0.5),
            key=lambda t: (round(t.y0), t.x0),
        )
        for t in top_right:
            tok = t.text.strip(" :#.-|")
            if (_BL_SHAPE.match(tok) and any(c.isalpha() for c in tok)
                    and not re.fullmatch(r"\d{1,3}", tok)):
                bl = tok
                break

    if book and bl and book == bl:          # never report the BL as the booking
        book = None
    return book, bl


def _parties(toks, page_w, page_h, out, put, labelled: bool = True) -> None:
    specs = (
        ("shipper", ("shipper",),
         ("consignee", "bookingno", "countryoforigin", "placeofreceipt"),
         "shipper", "shipper_name", "shipper_addr", "shipper_state"),
        ("consignee", ("consigneeiftoorder", "consignee"),
         ("notifyparty", "notifyaddress", "notify", "forwardingagent",
          "placeofreceipt", "vessel"),
         "consignee", "consignee_nm", "consignee_addr", "consignee_state"),
        ("notify", ("notifypartyname", "notifyparty", "notifyaddress", "notify"),
         ("2ndnotify", "secondnotify", "placeofreceipt", "vessel", "portofloading",
          "fordelivery", "precarriage", "marksand"),
         "notify_party", "notify_name", "notify_addr", "notify_state"),
    )
    done: set[str] = set()
    for tag, starts, stops, ck, nk, ak, sk in specs:
        if not labelled:
            break  # box labels are an image → go straight to block clustering
        lines = [
            ln for ln in _party_lines(toks, page_w, starts, stops, right=False, reach=95)
            if not looks_like_boilerplate(ln)
        ]
        if not _valid_party(lines):
            continue
        name, addr, state = split_party(lines)
        put(ck, ", ".join(lines), 0.82)
        put(nk, name, 0.85)
        put(ak, addr, 0.8)
        put(sk, state, 0.75)
        done.add(tag)

    if len(done) == 3:
        return

    # label-less form (box labels are part of a background image), or a label
    # pass that only caught cargo text → cluster the left column into blocks and
    # fill whichever parties are still missing from the first three.
    blocks = _left_blocks(toks, page_w, page_h)
    slots = [
        ("shipper", "shipper", "shipper_name", "shipper_addr", "shipper_state"),
        ("consignee", "consignee", "consignee_nm", "consignee_addr", "consignee_state"),
        ("notify", "notify_party", "notify_name", "notify_addr", "notify_state"),
    ]
    for (tag, ck, nk, ak, sk), lines in zip(slots, blocks[:3]):
        if tag in done:
            continue
        lines = [ln for ln in lines if not looks_like_boilerplate(ln)]
        if not _valid_party(lines):
            continue
        name, addr, state = split_party(lines)
        put(ck, ", ".join(lines), 0.72)
        put(nk, name, 0.74)
        put(ak, addr, 0.7)
        put(sk, state, 0.65)


def _balguerie_route(toks, page_w, out, put) -> None:
    """Multitrade / Balguerie 'BILL OF LADING' form — fixed column grid, box
    labels are a background image. The vessel row carries a voyage number
    (e.g. '004E') around x110-140; routing reads off fixed x-bands, Port of
    Loading from the row above."""
    def cell(y: float, lo: float, hi: float) -> str:
        band = sorted((t for t in toks if abs(t.y0 - y) <= 5 and lo <= t.cx <= hi),
                      key=lambda t: t.x0)
        return _clean(" ".join(t.text for t in band))

    vrow = None
    for t in toks:
        if re.fullmatch(r"\d{3,4}[A-Z]", t.text) and 90 <= t.x0 <= 150:
            vrow = t.y0
            break
    if vrow is None:
        return

    put("vessel_and_voyage",
        _clean(f"{cell(vrow, 10, 95)} {cell(vrow, 95, 150)}"), 0.7)
    put("port_of_discharge", cell(vrow, 150, 210), 0.7)
    put("place_of_delivery", cell(vrow, 270, 360), 0.68)
    orig = cell(vrow, 440, 540)
    if orig:
        put("number_of_original_bls", re.sub(r"\s+", "", orig), 0.65)

    # Port of Loading / Place of Receipt sit on the nearest row above that
    # actually carries a value in the routing band (skip the 'Voyage-No:' line).
    for ay in sorted({round(t.y0) for t in toks if 10 <= vrow - t.y0 <= 55},
                     reverse=True):
        pol = cell(ay, 150, 210)
        if pol and _PLACE_TOK_RE.match(pol):
            put("port_of_loading", pol, 0.68)
            put("place_of_receipt", cell(ay, 10, 95), 0.6)
            break


_PKG_NOUN_RE = re.compile(
    r"\b(PALLETS?|CARTONS?|CASES?|BAGS?|BOXES?|DRUMS?|PIECES?|PCS?|BUNDLES?|"
    r"PKGS?|PACKAGES?|ROLLS?|CRATES?|CONTAINERS?)\b", re.I)


def _balguerie_cargo(toks, out, put) -> None:
    """Multitrade / Balguerie cargo grid: Marks & Numbers | No. of Pkgs |
    Description | Gross Weight, each in a fixed x-band. Values are on the rows
    just under the 'KGS / CBM' unit header."""
    hdr = next((t.y0 for t in toks if t.text.upper() == "KGS" and t.x0 > 380), None)
    if hdr is None:
        return
    lo, hi = hdr + 4, hdr + 90

    def col(x0: float, x1: float) -> list[str]:
        return [t.text for t in sorted(
            (t for t in toks if lo <= t.y0 <= hi and x0 <= t.cx < x1),
            key=lambda t: (round(t.y0), t.x0))]

    pkgs_no = " ".join(col(150, 183)).strip()
    desc = col(183, 435)
    gross = " ".join(col(435, 525)).strip()
    marks = _clean(" ".join(col(8, 150)))

    noun = _PKG_NOUN_RE.search(" ".join(desc))
    if pkgs_no and noun and "number_and_kind_of_packages" not in out:
        put("number_and_kind_of_packages", f"{pkgs_no} {noun.group(1).upper()}", 0.65)

    m = re.search(r"[\d][\d.,]*", gross)
    if m and "gross_weight" not in out:
        put("gross_weight", f"{_norm_num(m.group(0))} KGS", 0.65)

    if desc and "description_of_goods" not in out:
        text = _clean(" ".join(desc))
        text = re.split(r"\bH\.?\s?S[\s.\-]*CODE\b", text, flags=re.I)[0]
        text = re.sub(r"\b\d+\s+FREE\s+DAYS.*$", "", text, flags=re.I).strip(" ,")
        if len(text) >= 4:
            put("description_of_goods", text[:200], 0.62)

    marks = re.sub(r"^CONTAINER\s+NO&?SEAL\s+NO\.?\s*", "", marks, flags=re.I).strip()
    if marks and "marks_and_numbers" not in out:
        put("marks_and_numbers", marks[:120], 0.6)


# Package kinds only — unlike _PKG_NOUN_RE this leaves out "CONTAINER(S)": a container
# count ("4 CONTAINERS") is not the No. & kind of packages.
_GOODS_NOUN_RE = re.compile(
    r"(?:PALLETS?|CARTONS?|CASES?|BAGS?|BOXES?|DRUMS?|PIECES?|PCS?|BUNDLES?|PKGS?|"
    r"PACKAGES?|PACKS?|ROLLS?|CRATES?|BALES?|SACKS?|UNITS?)", re.I)
_QTY_RE = re.compile(r"^\d[\d,]*$")
_UNITED_QTY_RE = re.compile(r"^\d[\d.,]*(?:KGS?|MTS?|CBM)$", re.I)
_UNIT_RE = re.compile(r"^(?:KGS?|MTS?|CBM)$", re.I)
_GOODS_END_RE = re.compile(
    r"^(?:CONTAINERS?\s*/\s*SEAL|CONTAINER\s+NO|SAY\s+TOTAL|SHIPPED\s+ON\s+BOARD|"
    r"TOTAL\s+NO\.?\s+OF)", re.I)


def _rows(toks: list[Token], tol: float = 4.0) -> list[list[Token]]:
    """Group tokens into visual rows (left-to-right), top to bottom."""
    rows: list[list[Token]] = []
    for t in sorted(toks, key=lambda t: (t.y0, t.x0)):
        if rows and abs(rows[-1][0].y0 - t.y0) <= tol:
            rows[-1].append(t)
        else:
            rows.append([t])
    return [sorted(r, key=lambda t: t.x0) for r in rows]


def _goods_grid(toks: list[Token], page_w: float, page_h: float, out, put) -> None:
    """Read the goods table — Marks & Numbers | No. & kind of packages |
    Description | Gross weight / Measurement — from position and content alone.

    Many carriers print the column headings as part of a background image, so
    nothing in the text layer says which column is which. What *is* there is a
    package count followed by its noun ("455 CARTONS"), which pins the packages
    column; the description column starts just right of it and ends where the
    weight figures begin; marks are whatever sits left of the packages column.
    The table ends at the container list / "SAY TOTAL" / "SHIPPED ON BOARD".
    Only fills fields the parser hasn't already found.
    """
    keys = ("number_and_kind_of_packages", "description_of_goods", "marks_and_numbers")
    if all(k in out for k in keys):
        return

    body = [t for t in toks if page_h * 0.25 <= t.y0 <= page_h * 0.9]
    rows = _rows(body)

    # -- anchor: "<count> <noun>" in the left ~45% of the page
    qty = noun = None
    for row in rows:
        for i, t in enumerate(row[:-1]):
            nxt = row[i + 1]
            if (
                _QTY_RE.match(t.text) and t.cx < page_w * 0.45
                and _GOODS_NOUN_RE.fullmatch(nxt.text.strip(".,"))
                and 0 <= nxt.x0 - t.x1 < 40
            ):
                qty, noun = t, nxt
                break
        if qty:
            break
    if not qty:
        return
    y_pk = qty.y0

    # -- vertical extent of the table
    y_top = y_pk - 30
    for row in rows:
        if row[0].y0 < y_pk and _MOVE_RE.search(" ".join(t.text for t in row)):
            y_top = max(y_top, row[0].y0 + 6)
    y_end = y_pk + page_h * 0.30
    for row in rows:
        if row[0].y0 > y_pk + 8 and _GOODS_END_RE.match(" ".join(t.text for t in row)):
            y_end = min(y_end, row[0].y0 - 1)
            break
    region = [t for t in body if y_top <= t.y0 < y_end]

    # -- where the weight / measurement figures start (right edge of description)
    wx0 = page_w * 0.62
    figs = []
    for row in rows:
        for i, t in enumerate(row):
            if not (y_top <= t.y0 < y_end) or t.x0 < noun.x1 + 40:
                continue
            nxt = row[i + 1] if i + 1 < len(row) else None
            if _UNITED_QTY_RE.match(t.text) or (
                _QTY_RE.match(t.text.replace(".", "")) and nxt and _UNIT_RE.match(nxt.text)
            ):
                figs.append(t.x0)
    if figs:
        wx0 = min(figs)

    # -- description column: starts at the first token right of the packages cell
    first_desc = next(
        (t for t in sorted(region, key=lambda t: (abs(t.y0 - y_pk) > 4, t.x0))
         if abs(t.y0 - y_pk) <= 4 and t.x0 >= noun.x1 + 2),
        None,
    )
    desc_x0 = first_desc.x0 - 2 if first_desc else noun.x1 + 4

    def text_of(pred) -> str:
        return " ".join(
            " ".join(t.text for t in row)
            for row in _rows([t for t in region if pred(t)])
        )

    if "number_and_kind_of_packages" not in out:
        put("number_and_kind_of_packages", f"{qty.text} {noun.text.strip('.,').upper()}", 0.7)

    if "description_of_goods" not in out:
        desc = text_of(lambda t: desc_x0 <= t.x0 < wx0 - 2)
        if len(desc) >= 4:
            put("description_of_goods", desc, 0.65)

    if "marks_and_numbers" not in out:
        marks = text_of(lambda t: t.x1 <= qty.x0 + 2)
        if marks and len(marks) <= 120:
            put("marks_and_numbers", marks, 0.65)


def _row_cells(toks, y: float, page_w: float, *, x_min: float = 0.0) -> list[str]:
    band = sorted(
        (t for t in toks if abs(t.y0 - y) <= 6 and t.x0 >= x_min and t.cx < page_w * 0.92),
        key=lambda t: t.x0,
    )
    cells: list[str] = []
    cur: list[str] = []
    prev_x1: float | None = None
    for t in band:
        if prev_x1 is not None and t.x0 - prev_x1 > 20:
            cells.append(" ".join(cur))
            cur = []
        cur.append(t.text)
        prev_x1 = t.x1
    if cur:
        cells.append(" ".join(cur))
    return [c.strip(" ,") for c in cells if c.strip(" ,")]


def _labelless_route(toks, page_w, page_h, out, put) -> None:
    """Forms whose box labels are a background image. The routing values sit on
    the row that also carries the vessel / voyage number; some carriers put
    Port of Discharge + Place of Delivery on that same row, others on the row
    below."""
    vv = _VESSEL_RE.search(" ".join(t.text for t in toks))
    anchor_y: float | None = None
    anchor_x1 = 0.0
    for t in sorted(toks, key=lambda t: t.y0):
        row = _row_cells(toks, t.y0, page_w)
        joined = " ".join(row)
        has_voy = bool(re.search(r"\b\d{2,4}[A-Z]\b", joined)) or bool(
            vv and vv.group(1) in joined
        )
        places = [c for c in row if _PLACE_TOK_RE.match(c) and not _MOVE_RE.match(c)]
        if has_voy and places and t.y0 < page_h * 0.6:
            anchor_y = t.y0
            anchor_x1 = min(x.x1 for x in toks if abs(x.y0 - t.y0) <= 6)
            break
    if anchor_y is None:
        return

    def places(cells: list[str]) -> list[str]:
        return [
            c for c in cells
            if _PLACE_TOK_RE.match(c) and not _MOVE_RE.match(c)
            and not re.search(r"\d", c)
        ]

    row = _row_cells(toks, anchor_y, page_w)
    row_places = places(row)
    below_y = min((t.y0 for t in toks if 10 <= t.y0 - anchor_y <= 40), default=None)
    below_places = places(_row_cells(toks, below_y, page_w)) if below_y else []

    if len(row_places) >= 3:                 # vessel | POD | Place of delivery on one row
        put("vessel_and_voyage", row_places[0], 0.6)
        put("port_of_discharge", row_places[1], 0.6)
        put("place_of_delivery", row_places[2], 0.58)
        above_y = max((t.y0 for t in toks if 8 <= anchor_y - t.y0 <= 34), default=None)
        if above_y:
            ap = places(_row_cells(toks, above_y, page_w, x_min=anchor_x1))
            if ap:
                put("port_of_loading", ap[-1], 0.58)
    else:                                    # vessel | POL on the row, POD/delivery below
        if row_places:
            put("port_of_loading", row_places[-1], 0.6)
        if below_places:
            put("port_of_discharge", below_places[0], 0.6)
        if len(below_places) > 1:
            put("place_of_delivery", below_places[1], 0.58)

    m = re.search(r"\b(\d\s*[/\-]?\s*(?:ZERO|\d))\b", " ".join(row))
    if m and "number_of_original_bls" not in out:
        put("number_of_original_bls", re.sub(r"\s+", "", m.group(1)), 0.55)


def _valid_party(lines: list[str]) -> bool:
    """A real party block: a non-trivial first line that is not cargo/marks text."""
    if not lines:
        return False
    head = lines[0].strip()
    if len(head) < 4 or _CARGO_LINE_RE.match(head) or _MARKS_JUNK_RE.match(head):
        return False
    return not looks_like_boilerplate(" ".join(lines))


def _left_blocks(toks: list[Token], page_w: float, page_h: float) -> list[list[str]]:
    left = [t for t in toks if t.cx < page_w * 0.55 and t.y0 < page_h * 0.55]
    blocks: list[list[str]] = []
    cur: list[str] = []
    prev_bottom: float | None = None
    for ln in _lines(left, y_tol=4):
        txt = _clean(" ".join(t.text for t in ln))
        if not txt:
            continue
        top = min(t.y0 for t in ln)
        if prev_bottom is not None and top - prev_bottom > 16 and cur:
            blocks.append(cur)
            cur = []
        cur.append(txt)
        prev_bottom = max(t.y1 for t in ln)
    if cur:
        blocks.append(cur)
    return blocks


def _routed_value(toks: list[Token], labels: tuple[str, ...]) -> str | None:
    for phrase in labels:
        lbl = _find_label(toks, phrase)
        if not lbl:
            continue
        v = _cell_below(toks, lbl[1], y_lo=2, y_hi=20, x_half=90)
        if not v or looks_like_boilerplate(v):
            continue
        first = re.sub(r"[^A-Z]", "", v.upper().split(" ")[0])
        if first in _ROUTE_STOP or len(v) < 2:
            continue
        return v
    return None


def _labelled_cell(toks: list[Token], labels: tuple[str, ...], *,
                   y_hi: float = 18.0, x_half: float = 90.0,
                   gap: float = 40.0, below_only: bool = False) -> str | None:
    for phrase in labels:
        lbl = _find_label(toks, phrase)
        if not lbl:
            continue
        end = lbl[1]
        if below_only:
            below = _cell_below(toks, end, y_lo=2, y_hi=y_hi, x_half=x_half)
            if below and len(below) >= 2 and not looks_like_boilerplate(below):
                return below
            continue
        cy = (end.y0 + end.y1) / 2
        beside = sorted(
            (t for t in toks
             if abs((t.y0 + t.y1) / 2 - cy) <= 6 and t.x0 >= end.x1 - 2),
            key=lambda t: t.x0,
        )
        run: list[Token] = []
        for t in beside:
            prev_x1 = run[-1].x1 if run else end.x1
            if t.x0 - prev_x1 > gap:
                break
            run.append(t)
            if max(t.x1 for t in run) - end.x1 > 230:  # don't cross the page
                break
        text = _clean(" ".join(t.text for t in run))
        if text and len(text) >= 2 and not looks_like_boilerplate(text):
            return text
        below = _cell_below(toks, end, y_lo=2, y_hi=y_hi, x_half=x_half)
        if below and len(below) >= 2 and not looks_like_boilerplate(below):
            return below
    return None


def _agent_block(toks: list[Token], page_w: float, full_all: str) -> str | None:
    for phrase in ("for delivery of goods", "for delivery please apply",
                   "delivery agent", "for delivery"):
        lbl = _find_label(toks, phrase)
        if not lbl:
            continue
        x0 = lbl[0].x0
        band = [t for t in toks
                if x0 - 12 <= t.x0 <= x0 + 210
                and lbl[1].y1 + 2 <= t.y0 <= lbl[1].y1 + 95]
        rows = _lines(band, y_tol=4)
        parts: list[str] = []
        for ln in rows[:5]:
            s = _clean(" ".join(t.text for t in ln))
            if s and not re.match(r"^(IEC|GST|PAN|TEL|FAX|E-?MAIL|BOARD|CTC)\b", s, re.I):
                parts.append(s)
        agent = _clean(", ".join(parts))
        if "JEENA" in agent.upper() and not looks_like_boilerplate(agent):
            return agent[:200]

    m = re.search(
        r"(JEENA\s*&?\s*(?:COMPANY|CO)\b[^,]{0,4}(?:,?\s*[A-Z0-9][^,]{2,40}){0,4})",
        full_all, re.I)
    if m:
        agent = _clean(m.group(1))
        noise = ("GROSS WEIGHT", "SHIPPER", "MEASUREMENT", "PORT OF", "PLACE OF")
        if not any(n in agent.upper() for n in noise):
            return agent[:200]
    return None


def _iec_gstin(out, full_all: str, put) -> None:
    """IEC code and GSTIN, taken from the Indian party that carries them —
    consignee first, then notify, then shipper, then anywhere on the doc.
    The GSTIN's leading 2-digit state code is dropped, as requested."""
    for src in (
        out.get("consignee", ("",))[0],
        out.get("notify_party", ("",))[0],
        out.get("shipper", ("",))[0],
        full_all,
    ):
        if not src:
            continue
        if "iec_code" not in out:
            m = _IEC_RE.search(src)
            if m:
                put("iec_code", m.group(1).upper(), 0.8)
        if "gstin" not in out:
            m = _GSTIN_RE.search(src) or _GSTIN_BARE_RE.search(src)
            if m:
                put("gstin", m.group(1).upper()[2:], 0.8)
        if "iec_code" in out and "gstin" in out:
            break


def _containers(full: str) -> str | None:
    pairs: list[str] = []
    for m in _CONT_RE.finditer(full):
        cont = m.group(1)
        lead = full[max(0, m.start() - 24): m.start()].upper()
        if "OCEAN B/L" in lead or "B/L NO" in lead:
            continue
        tail = full[m.end(): m.end() + 80]
        sm = _SEAL_RE.search(tail) or re.match(
            r"\s*(?:\([^)]*\)\s*)?/\s*([A-Z]{2,5}\d{4,10})\b", tail)
        pairs.append(f"{cont} / {sm.group(1)}" if sm else cont)
    uniq = list(dict.fromkeys(pairs))
    return ", ".join(uniq) if uniq else None
